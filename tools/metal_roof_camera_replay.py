#!/usr/bin/env python3
"""Prepare a bounded static roof replay from an actual original draw camera.

The unchanged static vertex calculation and a source-derived viewport bridge
are separate controls. Neither control changes production renderer sources.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

from metal_roof_depth_validate import verify_capture_payloads
from metal_roof_gpu_validate import bind_tree, replace_once, sha, verify_bindings, write_json


def frustum_rows(frustum, offsets):
    import numpy as np
    n = np.frombuffer(frustum, dtype="<f4", count=12, offset=offsets["world_to_view"]+4).reshape(4, 3)
    projection = np.frombuffer(frustum, dtype="<f4", count=16, offset=offsets["projection_matrix"]).reshape(4, 4)
    result = np.zeros((4, 4), dtype=np.float32)
    # Exact original source order: each product and each left-associated add
    # rounds to float32; original CPU compilation disables FP contraction.
    for column in range(4):
        for row in range(4):
            a = np.float32(n[row, 0]*projection[0, column])
            b = np.float32(n[row, 1]*projection[1, column])
            c = np.float32(n[row, 2]*projection[2, column])
            result[column, row] = np.float32(np.float32(a+b)+c)
        result[column, 3] = np.float32(result[column, 3]+projection[3, column])
    return result, projection


def actual_frame_probe(source):
    source = replace_once(source, "    NSData *roofMatrixOverride;", "    NSData *roofMatrixOverride, *roofFrameOverride;")
    source = replace_once(source, "    float seconds = (float)(fixedAnimationTime ? animationTime : CACurrentMediaTime() - startTime);", """    if (roofFrameOverride) {
        const float *actual = (const float *)roofFrameOverride.bytes;
        forward = {actual[16], actual[17], actual[18]};
        fog.coordinatePlane = {actual[20], actual[21], actual[22], actual[23]};
    }
    float seconds = (float)(fixedAnimationTime ? animationTime : CACurrentMediaTime() - startTime);""")
    initializer = """        TeleporterFrameUniforms frame = {uniforms.viewProjection, {forward.x, forward.y, forward.z, exposure},
                                        fog.coordinatePlane, {fogRawDensity, seconds, 0, 0}};"""
    if source.count(initializer) != 2:
        raise ValueError("Expected both original transparent frame initializers")
    source = source.replace(initializer, initializer + "\n        if (roofFrameOverride) memcpy(&frame, roofFrameOverride.bytes, sizeof(frame));")
    source = replace_once(source, "        NSString *roofVP = nil;", "        NSString *roofVP = nil, *roofFrame = nil;")
    source = replace_once(source, '            else if ([arg isEqualToString:@"--roof-vp"] && i + 1 < argc) roofVP = @(argv[++i]);',
                          '            else if ([arg isEqualToString:@"--roof-vp"] && i + 1 < argc) roofVP = @(argv[++i]);\n            else if ([arg isEqualToString:@"--roof-frame"] && i + 1 < argc) roofFrame = @(argv[++i]);')
    source = replace_once(source, "        renderer->captureWidth = width;", """        if (roofFrame) {
            require(roofVP && roofMode, @"Captured frame requires exact VP and an instrumented probe");
            renderer->roofFrameOverride = readFile(roofFrame);
            require(renderer->roofFrameOverride.length == 112, @"Captured frame must contain 112 exact bytes");
            require(!memcmp(renderer->roofFrameOverride.bytes, renderer->roofMatrixOverride.bytes, 64),
                    @"Captured frame and matrix disagree");
            const float *actual = (const float *)renderer->roofFrameOverride.bytes;
            for (NSUInteger j = 0; j < 28; j++) require(std::isfinite(actual[j]), @"Nonfinite captured frame");
        }
        renderer->captureWidth = width;""")
    source = replace_once(source, '            @"query_word_count": @(roofVisibility.length / 8),',
                          '            @"query_word_count": @(roofVisibility.length / 8),\n            @"captured_frame_sha256": roofFrameOverride ? sha256(roofFrameOverride) : @"",')
    return source


def llvm_strings(source):
    result = {}
    for name, size, text in re.findall(r'(@[\w.]+) = private unnamed_addr constant \[(\d+) x i8\] c"([^"\n]*)"', source):
        raw = re.sub(r"\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), text).encode("latin1")
        if len(raw) != int(size):
            raise ValueError("Original LLVM string extent mismatch")
        result[name] = raw.rstrip(b"\0").decode()
    return result


def viewport_helper(scale, offset, constant_scale, constant_offset, screen_offset):
    def literal(value):
        value = format(float(value), ".17g")
        return value + ("f" if "." in value or "e" in value.lower() else ".0f")

    def vector(values):
        return "float3(" + ",".join(literal(v) for v in values) + ")"
    # This is the captured original emitter's clip-capture branch, with the
    # actual bank58/59 and draw scale/offset substituted, in the same stages.
    return """// Test-only original captured viewport constants; logical top-left.
float4 roof_capture_viewport(float4 clip) {
    float3 scaled_clip = clip.xyz * %s;
    float3 screen_origin = %s + %s;
    float3 origin_delta = screen_origin - %s;
    float3 clip_delta = origin_delta * clip.w;
    float3 numerator = scaled_clip + clip_delta;
    float3 position = numerator / %s;
    return float4(position, clip.w);
}
""" % (vector(constant_scale), vector(constant_offset), vector([.5+screen_offset, .5, 0]), vector(offset), vector(scale))


def prepare(args):
    import numpy as np
    angle, prior, out = args.angle_run.resolve(), args.prior.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError("Output exists; preserve attempts")
    original_result = json.loads((angle / "result.json").read_bytes())
    original_execution = json.loads((angle / "execution.json").read_bytes())
    if not original_result["complete"] or not original_execution["complete"] or original_execution["exit_code"]:
        raise ValueError("A completed source/config-bound original capture is required")
    verify_bindings(original_result["output_bindings"])
    verify_bindings(original_result["captured_payload_bindings"])
    old = json.loads((prior / "prepared.json").read_bytes())
    old_result = json.loads((prior / "result.json").read_bytes())
    verify_bindings(old["original_bindings"]); verify_bindings(old["frozen_bindings"])
    verify_bindings(old_result["output_bindings"])
    frame = angle / "saves/metal-frames/frame480"
    draw_file = frame / "draw-0074.json"
    draw = json.loads(draw_file.read_bytes())
    state = draw["render_camera_diagnostic"]
    camera_raw = (frame / state["camera_blob"]["file"]).read_bytes()
    frustum_raw = (frame / state["frustum_blob"]["file"]).read_bytes()
    constants_raw = (frame / draw["vertex_constants"]["file"]).read_bytes()
    draw_uniforms_raw = (frame / draw["draw_uniforms"]["file"]).read_bytes()
    constants = np.frombuffer(constants_raw, dtype="<f4").reshape(192, 4)
    rows, projection = frustum_rows(frustum_raw, state["frustum_offsets"])
    if rows.tobytes() != constants[:4].tobytes():
        raise ValueError("Original frustum source formula differs from captured matrix constants")
    if state["long_bytes"] != 4 or state["float_bytes"] != 4 or draw["viewport"] != {
        "origin_x": 0, "origin_y": 0, "width": 640, "height": 480, "znear": 0, "zfar": 1}:
        raise ValueError("Unexpected actual original draw viewport/ABI")
    bank_scale, bank_offset = constants[58].tolist(), constants[59].tolist()
    scale, offset = struct.unpack_from("<4f", draw_uniforms_raw), struct.unpack_from("<4f", draw_uniforms_raw, 16)
    screen_offset = struct.unpack_from("<f", draw_uniforms_raw, 36)[0]
    if tuple(bank_scale) != scale or tuple(bank_offset) != offset or screen_offset != 0:
        raise ValueError("Unexpected captured bank/draw viewport constants")
    # Resolve the static surface through authored positions, UVs and triangle
    # order, rather than identifying it from its approximate screenshot shape.
    scene = prior / "scene"
    manifest = json.loads((scene / "scene.json").read_bytes())
    mesh = next(m for m in manifest["transparent_bsp_meshes"] if m["source_surface_first"] == 5427)
    static_vertices = np.frombuffer((scene / "vertices.bin").read_bytes(), dtype="<f4").reshape(-1, 7)
    static_indices = np.frombuffer((scene / "indices.bin").read_bytes(), dtype="<u4")
    static = static_vertices[static_indices[mesh["first_index"]:mesh["first_index"]+mesh["index_count"]], :5]
    stream = draw["streams"][0]
    raw = (frame / stream["payload"]["file"]).read_bytes()
    if draw["source_first_vertex"] or draw["source_base_vertex"] or stream["stride"] != 32 or draw["vertex_count"] != 4 or draw["index_count"] != 6:
        raise ValueError("Unexpected source glyph stream/index declaration")
    original_vertices = np.frombuffer(raw, dtype="<f4").reshape(4, 8)[:, [0, 1, 2, 6, 7]]
    original_indices = np.frombuffer((frame / draw["indices"]["file"]).read_bytes(), dtype="<u2")
    if static.tobytes() != original_vertices[original_indices].tobytes():
        raise ValueError("Static geometry/UV/triangle order differs from actual original draw")
    texture = manifest["textures"][mesh["textures"][0]]
    mip_bytes = b"".join((scene / m["file"]).read_bytes() for m in texture["native_mipmaps"])
    if mip_bytes != (frame / draw["textures"][0]["payload"]["file"]).read_bytes():
        raise ValueError("Static authored compressed chain differs from actual original draw")
    # Source code strings are recovered from the actual historical ILP32
    # emitter LLVM artifact, whose object is part of the new reference link.
    root = Path(__file__).resolve().parents[1]
    provenance_file = root / "build/macos-capture/provenance.json"
    provenance = json.loads(provenance_file.read_bytes())
    old_ir = root / "build/macos-capture/nv2a_vsh.ll"
    old_obj = root / "build/macos-capture/nv2a_vsh.o"
    for p in (old_ir, old_obj):
        entry = next(e for e in provenance["generated_artifacts"] if e["path"] == str(p))
        if sha(p) != entry["sha256"]:
            raise ValueError("Historical original vertex emitter artifact changed")
    strings = llvm_strings(old_ir.read_text())
    unviewport = next(v for v in strings.values() if "if (clip_captured)" in v and "clip_position.xyz * c[%d]" in v)
    y_z = next(v for v in strings.values() if "gl_Position.y = -gl_Position.y" in v)
    if "vec3(0.5 + screen_offset, 0.5, 0.0)" not in unviewport or "gl_Position.z = 2.0 * gl_Position.z - gl_Position.w" not in y_z:
        raise ValueError("Original compiled bridge does not have the expected pixel/Z operations")
    out.mkdir(parents=True)
    shutil.copytree(scene, out / "scene")
    (out / "original-compiled-unviewport.txt").write_text(unviewport + "\n" + y_z)
    shutil.copy2(old_ir, out / "original-nv2a-vsh.ll")
    shutil.copy2(old_obj, out / "original-nv2a-vsh.o")
    (out / "captured-world-vp.f32").write_bytes(rows.T.astype("<f4").tobytes())
    frame_values = [*rows.T.flatten(), *constants[5, :3], 1, *constants[8], constants[11, 0], 0, 0, 0]
    (out / "captured-frame.f32").write_bytes(struct.pack("<28f", *frame_values))
    # Raw projection and all camera data are retained, not rebuilt from yaw.
    for name, blob in (("camera.bin", camera_raw), ("frustum.bin", frustum_raw),
                       ("vertex-constants.bin", constants_raw), ("draw-uniforms.bin", draw_uniforms_raw)):
        (out / name).write_bytes(blob)
    source = actual_frame_probe((prior / "depth-probe-main.mm").read_text())
    (out / "camera-probe-main.mm").write_text(source)
    helper = viewport_helper(scale[:3], offset[:3], bank_scale[:3], bank_offset[:3], screen_offset)
    for variant in ("static-arithmetic", "original-viewport-bridge"):
        target = out / variant
        shutil.copytree(prior / "original", target)
        if variant == "original-viewport-bridge":
            p = target / "Scene.metal"
            p.write_text(replace_once(p.read_text(), "vertex Varyings scene_vertex(", helper + "\nvertex Varyings scene_vertex(").replace(
                "uniforms.viewProjection * float4(float3(v.position), 1)",
                "roof_capture_viewport(uniforms.viewProjection * float4(float3(v.position), 1))"))
            p = target / "TransparentBsp.metal"
            p.write_text(replace_once(p.read_text(), "frame.viewProjection*float4(position, 1.0)",
                                     "roof_capture_viewport(frame.viewProjection*float4(position, 1.0))"))
        (target / "combined.metal").write_text("\n".join((target / name).read_text().replace('#include "Fog.metal"', "") for name in
            ("Fog.metal", "Scene.metal", "Sky.metal", "Decal.metal", "Teleporter.metal", "TransparentBsp.metal", "RoofGlyphDepth.metal")))
    command = ["xcrun", "clang++", "-std=c++17", "-O2", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
        "-mmacosx-version-min=13.0", str(out / "camera-probe-main.mm"), "-framework", "Cocoa", "-framework", "Metal",
        "-framework", "MetalKit", "-framework", "QuartzCore", "-o", str(out / "camera-probe")]
    with (out / "compile.log").open("w") as log:
        cp = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if cp.returncode:
        raise ValueError("Strict isolated host compile failed")
    offsets = state["camera_offsets"]
    position = struct.unpack_from("<3f", camera_raw, offsets["position"])
    forward = struct.unpack_from("<3f", camera_raw, offsets["forward"])
    yaw, pitch = math.atan2(forward[1], forward[0]), math.asin(forward[2])
    effective_fov = math.degrees(2*math.atan(1/float(projection[1, 1])))
    pose = [*position, yaw, pitch]
    cases = [{"name": variant + "-" + name, "variant": variant, "mode": mode, "surface": 5427 if mode >= 3 else 0,
              "width": 640, "height": 480, "camera": {"pose": pose, "vertical_fov": effective_fov}}
             for variant in ("static-arithmetic", "original-viewport-bridge")
             for mode, name in ((1, "full-scene"), (2, "opaque"), (3, "glyph-lequal"), (4, "glyph-always"), (7, "glyph-depth-mrt"))]
    inputs = {str(Path(__file__).resolve()): sha(__file__), str(angle / "result.json"): sha(angle / "result.json"),
        str(angle / "execution.json"): sha(angle / "execution.json"), str(prior / "prepared.json"): sha(prior / "prepared.json"),
        str(prior / "result.json"): sha(prior / "result.json"), str(provenance_file): sha(provenance_file), str(old_ir): sha(old_ir), str(old_obj): sha(old_obj)}
    inputs.update(original_result["output_bindings"])
    inputs.update(old["frozen_bindings"])
    for module in ("metal_roof_depth_validate.py", "metal_roof_gpu_validate.py"):
        p = Path(__file__).with_name(module); inputs[str(p)] = sha(p)
    audit = {"kind": "actual_original_roof_camera_static_inputs", "complete": True, "actual_draw_use": 74, "original_program_id": draw["program_id"],
        "static_source_surface": 5427, "positions_uvs_triangle_order_byte_exact": True,
        "authored_bc1_mips_byte_exact": True, "authored_mips": len(texture["native_mipmaps"]),
        "captured_world_constants_equal_original_source_frustum_product": True, "original_bank_rows": rows.tolist(),
        "original_constants_register_api": "SetVertexShaderConstant(-96,8): captured bank rows0..3 are the world clip matrix",
        "camera": {"position": list(position), "forward": list(forward), "up": list(struct.unpack_from("<3f", camera_raw, offsets["up"])),
            "raw_safe_frame_vertical_fov_degrees": math.degrees(struct.unpack_from("<f", camera_raw, offsets["vertical_field_of_view"])[0]),
            "effective_projection_vertical_fov_degrees": effective_fov, "near": .0625, "far": 1024},
        "captured_viewport": {"scale": scale, "offset": offset, "bank58": bank_scale, "bank59": bank_offset, "screen_offset": screen_offset},
        "pixel_offset_sign": "Original +0.5,+0.5 screen pixels becomes +0.5/320 clipX and +0.5/-240 clipY; native top-first raster maps both to +0.5 pixels",
        "original_gl_z_conversion": "2*z-w is present in actual original emitter artifact; ANGLE zero-one conversion (z+w)*0.5 is source-derived backend behavior, not newly intercepted for this program",
        "stencil_scope": "Original draw EQUAL0/readmask1/no writes; static viewer has no stencil-writing actors and no stencil attachment",
        "no_production_changes": True,
        "limits": ["Static matmul remains different from original program DP3H instruction/compiler arithmetic",
                   "Static safe math differs from original ANGLE Fast compiler policy",
                   "The viewport bridge keeps native 0..1 depth; original GLES-to-Metal Z rounding remains a precision difference",
                   "Actual captured forward/fog plane/rawdensity are copied exactly; sky still uses static yaw/pitch camera path",
                   "Synthetic roof pose is not the unseen exact user pose", "No depth bias/invariance correction or native fullgame claim"]}
    write_json(out / "input-audit.json", audit)
    frozen = bind_tree(out)
    write_json(out / "prepared.json", {"kind": "actual_camera_static_roof_replay_preparation", "complete": True, "gpu_executed": False,
        "original_bindings": inputs, "frozen_bindings": frozen, "command": command, "strict_host_compile_exit": cp.returncode,
        "cases": cases, "input_audit_sha256": sha(out / "input-audit.json"), "limits": audit["limits"]})
    verify_bindings(inputs); verify_bindings(frozen)
    print(json.dumps({"prepared": str(out / "prepared.json"), "sha256": sha(out / "prepared.json"),
        "input_audit": str(out / "input-audit.json"), "cases": len(cases), "gpu_executed": False}))


def execute(args):
    import numpy as np
    from PIL import Image
    out = args.out.resolve()
    prepared = json.loads((out / "prepared.json").read_bytes())
    if (out / "execution.json").exists() or (out / "captures").exists():
        raise ValueError("Already attempted; preserve old outputs")
    verify_bindings(prepared["original_bindings"]); verify_bindings(prepared["frozen_bindings"])
    captures = out / "captures"; captures.mkdir()
    execution = {"kind": "actual_camera_static_roof_replay_execution", "complete": False,
        "prepared_sha256": sha(out / "prepared.json"), "runs": []}
    write_json(out / "execution.json", execution)
    for case in prepared["cases"]:
        png = captures / (case["name"] + ".png")
        command = [str(out / "camera-probe"), "--scene", str(out / "scene"), "--shader", str(out / case["variant"] / "Scene.metal"),
            "--capture", str(png), "--frames", "1", "--time", "0", "--width", str(case["width"]), "--height", str(case["height"]),
            "--vertical-fov", str(case["camera"]["vertical_fov"]), "--camera", *map(str, case["camera"]["pose"]),
            "--roof-probe-mode", str(case["mode"]), "--roof-vp", str(out / "captured-world-vp.f32"), "--roof-frame", str(out / "captured-frame.f32")]
        if case["surface"]:
            command += ["--roof-target", str(case["surface"])]
        start = time.monotonic()
        with png.with_suffix(".log").open("w") as log:
            cp = subprocess.run(command, env=dict(os.environ, MTL_DEBUG_LAYER="1"), stdout=log, stderr=subprocess.STDOUT, timeout=60)
        validation = "Metal API Validation Enabled" in png.with_suffix(".log").read_text()
        execution["runs"].append({"name": case["name"], "command": command, "exit_code": cp.returncode,
            "api_validation_observed": validation, "wall_seconds": time.monotonic()-start})
        write_json(out / "execution.json", execution)
        if cp.returncode or not validation:
            raise ValueError("Static capture failed or API validation not observed")
        metadata = json.loads(Path(str(png) + ".json").read_bytes())
        verify_capture_payloads(png, metadata)
        if Path(str(png) + ".world-vp.f32").read_bytes() != (out / "captured-world-vp.f32").read_bytes() or metadata["roof_depth_measurement"]["captured_frame_sha256"] != sha(out / "captured-frame.f32"):
            raise ValueError("Measured captured matrix/frame was not retained")
        bgra = np.fromfile(str(png)+".bgra8", dtype=np.uint8).reshape(case["height"], case["width"], 4)
        if not np.array_equal(np.asarray(Image.open(png).convert("RGB")), bgra[:, :, [2, 1, 0]]):
            raise ValueError("PNG and raw target RGB disagree")
    verify_bindings(prepared["original_bindings"]); verify_bindings(prepared["frozen_bindings"])
    result = {"kind": "actual_camera_static_roof_replay_capture", "complete": True, "gpu_executed": True,
        "prepared_sha256": sha(out / "prepared.json"), "actual_runs": execution["runs"], "outputs": bind_tree(captures),
        "clipping_fix_proven": False, "native_game_or_original_hardware_parity": False, "limits": prepared["limits"]}
    write_json(out / "result.json", result)
    execution["complete"] = True; execution["result_sha256"] = sha(out / "result.json")
    write_json(out / "execution.json", execution)
    print(json.dumps({"result": str(out / "result.json"), "sha256": sha(out / "result.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--angle-run", type=Path, required=True); p.add_argument("--prior", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("execute"); p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args)
    else:
        execute(args)
