#!/usr/bin/env python3
"""Freeze and instrument the existing static viewer for a bounded roof audit.

Preparation compiles host executables only. Execution is a separate, explicit
step; it records diagnostics, not an original-Xbox fidelity verdict.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/macos/metal-poc"
GLYPH = r"levels\test\bloodgulch\shaders\bloodgulch light red"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Viewer source anchor is absent or ambiguous: " + old[:80])
    return source.replace(old, new)


def make_probe_source(original):
    """Retain the renderer; add observability and explicit diagnostic controls."""
    source = replace_once(original, "    NSTextField *help;", """    NSTextField *help;
    // Test-only state: all words are zeroed before each synchronous frame.
    NSUInteger roofProbeMode, roofTargetSurface;
    id<MTLBuffer> roofVisibility, roofDepthReadback;
    std::vector<NSUInteger> roofSurfaces;
    std::vector<bool> roofTargets;
    NSUInteger roofPassDraws[5];
    simd_float4x4 roofWorldMatrix;
    NSData *roofMatrixOverride;
""")
    source = replace_once(source, "        transparentBspMeshes.push_back(mesh);", """        transparentBspMeshes.push_back(mesh);
        roofSurfaces.push_back([m[@"source_surface_first"] unsignedIntegerValue]);
        roofTargets.push_back([m[@"name"] isEqualToString:@"levels\\\\test\\\\bloodgulch\\\\shaders\\\\bloodgulch light red"]);
""")
    source = replace_once(source, "    triangleCount = opaqueTriangleCount", """    roofVisibility = [device newBufferWithLength:std::max((NSUInteger)8,
        (NSUInteger)transparentBspMeshes.size() * 8) options:MTLResourceStorageModeShared];
    require(roofVisibility != nil, @"Roof visibility allocation failed");
    triangleCount = opaqueTriangleCount""")
    source = replace_once(source,
        "    Uniforms uniforms = {cameraMatrix(position, yaw, pitch, aspect, verticalFov), mode, exposure, {0, 0}};",
        """    Uniforms uniforms = {cameraMatrix(position, yaw, pitch, aspect, verticalFov), mode, exposure, {0, 0}};
    if (roofMatrixOverride) memcpy(&uniforms.viewProjection, roofMatrixOverride.bytes, 64);
    roofWorldMatrix = uniforms.viewProjection;
    memset(roofPassDraws, 0, sizeof(roofPassDraws));
    if (roofProbeMode) {
        memset(roofVisibility.contents, 0, roofVisibility.length);
        pass.depthAttachment.storeAction = MTLStoreActionStore;
        if (roofProbeMode != 2) pass.visibilityResultBuffer = roofVisibility;
    }
""")
    for ordinal, mesh_type, mesh_list in [(0, "SkyMesh", "skyMeshes"), (1, "Mesh", "meshes"),
                                         (2, "DecalMesh", "decalMeshes"), (4, "TeleporterMesh", "teleporterMeshes")]:
        anchor = f"for (const {mesh_type} &m : {mesh_list}) {{"
        source = replace_once(source, anchor, anchor + f"\n            roofPassDraws[{ordinal}]++;")
    source = replace_once(source, "    if (!decalMeshes.empty()) {", """    if (roofProbeMode == 2) { [encoder endEncoding]; return; }
    if (roofProbeMode >= 3) {
        // Preserve the unchanged opaque shader/discard/depth pass, then clear
        // color only. This diagnostic contribution pass does not move geometry.
        [encoder endEncoding];
        MTLRenderPassDescriptor *contribution = [pass copy];
        contribution.colorAttachments[0].loadAction = MTLLoadActionClear;
        contribution.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 1);
        contribution.depthAttachment.loadAction = MTLLoadActionLoad;
        encoder = [command renderCommandEncoderWithDescriptor:contribution];
        require(encoder != nil, @"Roof contribution encoder creation failed");
        [encoder setVertexBuffer:vertices offset:0 atIndex:0];
        [encoder setTriangleFillMode:wireframe ? MTLTriangleFillModeLines : MTLTriangleFillModeFill];
    }
    if (roofProbeMode < 2 && !decalMeshes.empty()) {""")
    block = """        [encoder setRenderPipelineState:transparentBspPipeline];
        [encoder setDepthStencilState:overlayDepthState];"""
    source = replace_once(source, block, """        [encoder setRenderPipelineState:transparentBspPipeline];
        [encoder setDepthStencilState:roofProbeMode >= 4 ? skyDepthState : overlayDepthState];""")
    source = replace_once(source,
        """        for (const TransparentBspMesh &m : transparentBspMeshes) {
            [encoder setCullMode:m.twoSided ? MTLCullModeNone : MTLCullModeBack];""",
        """        NSUInteger roofOrdinal = 0;
        for (const TransparentBspMesh &m : transparentBspMeshes) {
            NSUInteger roofIndex = roofOrdinal++;
            bool target = roofTargets[roofIndex];
            if (roofProbeMode >= 3 && (!target ||
                (roofTargetSurface && roofSurfaces[roofIndex] != roofTargetSurface))) continue;
            roofPassDraws[3]++;
            [encoder setCullMode:roofProbeMode == 5 || m.twoSided ? MTLCullModeNone : MTLCullModeBack];
            if (roofProbeMode && target)
                [encoder setVisibilityResultMode:MTLVisibilityResultModeCounting offset:roofIndex * 8];""")
    draw = """            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                                 indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
        }
        [encoder setDepthBias:0 slopeScale:0 clamp:0];
    }
    if (!teleporterMeshes.empty()) {"""
    source = replace_once(source, draw, """            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                                 indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
            if (roofProbeMode && target)
                [encoder setVisibilityResultMode:MTLVisibilityResultModeDisabled offset:0];
        }
        [encoder setDepthBias:0 slopeScale:0 clamp:0];
    }
    if (roofProbeMode < 2 && !teleporterMeshes.empty()) {""")
    source = replace_once(source, "    double cpu = 0, gpu = 0;", """    NSUInteger roofDepthPitch = (width * 4 + 255) & ~(NSUInteger)255;
    if (roofProbeMode) {
        roofDepthReadback = [device newBufferWithLength:roofDepthPitch * height
                                               options:MTLResourceStorageModeShared];
        require(roofDepthReadback != nil, @"Roof depth readback allocation failed");
    }
    double cpu = 0, gpu = 0;""")
    source = replace_once(source,
        """            [self encode:command pass:pass size:CGSizeMake(width, height)];
            [command commit];""",
        """            [self encode:command pass:pass size:CGSizeMake(width, height)];
            if (roofProbeMode && i == count + 9) {
                id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
                require(blit != nil, @"Roof depth blit creation failed");
                [blit copyFromTexture:depth sourceSlice:0 sourceLevel:0
                        sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(width, height, 1)
                           toBuffer:roofDepthReadback destinationOffset:0
                 destinationBytesPerRow:roofDepthPitch destinationBytesPerImage:roofDepthPitch * height];
                [blit endEncoding];
            }
            [command commit];""")
    source = replace_once(source,
        "    NSData *json = [NSJSONSerialization dataWithJSONObject:metrics options:NSJSONWritingPrettyPrinted error:nil];",
        """    if (roofProbeMode) {
        std::vector<uint8_t> tightDepth(width * height * 4);
        for (NSUInteger row = 0; row < height; row++)
            memcpy(tightDepth.data() + row * width * 4,
                   (const uint8_t *)roofDepthReadback.contents + row * roofDepthPitch, width * 4);
        NSData *depthData = [NSData dataWithBytes:tightDepth.data() length:tightDepth.size()];
        NSData *colorData = [NSData dataWithBytes:bytes.data() length:bytes.size()];
        NSData *queryData = [NSData dataWithBytes:roofVisibility.contents length:roofVisibility.length];
        NSData *matrix = [NSData dataWithBytes:&roofWorldMatrix length:64];
        for (NSArray *record in @[@[@".depth32", depthData], @[@".bgra8", colorData],
                                  @[@".visibility.u64", queryData], @[@".world-vp.f32", matrix]])
            require([record[1] writeToFile:[path stringByAppendingString:record[0]] atomically:YES],
                    @"Roof diagnostic write failed");
        NSMutableArray *counts = [NSMutableArray array];
        const uint64_t *words = (const uint64_t *)roofVisibility.contents;
        for (NSUInteger i = 0; i < roofTargets.size(); i++) if (roofTargets[i])
            [counts addObject:@{@"source_surface_first": @(roofSurfaces[i]),
                                @"first_index": @(transparentBspMeshes[i].first),
                                @"accepted_samples": @(words[i])}];
        NSMutableArray *vp = [NSMutableArray array];
        const uint32_t *bits = (const uint32_t *)&roofWorldMatrix;
        for (NSUInteger i = 0; i < 16; i++) [vp addObject:@(bits[i])];
        NSMutableDictionary *augmented = [metrics mutableCopy];
        NSArray *passNames = @[@"sky", @"opaque", @"decals", @"transparent_bsp", @"teleporters"];
        NSMutableDictionary *actualPassDraws = [NSMutableDictionary dictionary];
        NSUInteger actualDraws = 0;
        for (NSUInteger i = 0; i < 5; i++) {
            actualPassDraws[passNames[i]] = @(roofPassDraws[i]);
            actualDraws += roofPassDraws[i];
        }
        augmented[@"roof_probe"] = @{@"mode": @(roofProbeMode),
            @"target_surface": @(roofTargetSurface), @"sample_count": @1,
            @"visibility": counts, @"depth_format": @"Depth32Float", @"depth_orientation": @"top_left",
            @"depth_sha256": sha256(depthData), @"color_bgra_sha256": sha256(colorData),
            @"visibility_sha256": sha256(queryData), @"world_vp_sha256": sha256(matrix),
            @"world_vp_column_major_float32_bits": vp, @"vp_override": @(roofMatrixOverride != nil),
            @"fresh_visibility_words_per_frame": @YES,
            @"actual_encoded_draws": @(actualDraws), @"actual_pass_draws": actualPassDraws,
            @"scene_inventory_counts_above_are_not_executed_control_counts": @YES,
            @"scope": @"Test-only static viewer GPU diagnostics; no clipping or original parity verdict"};
        metrics = augmented;
    }
    NSData *json = [NSJSONSerialization dataWithJSONObject:metrics options:NSJSONWritingPrettyPrinted error:nil];""")
    source = replace_once(source, "        bool overview = false;", """        NSUInteger roofMode = 0, roofTarget = 0;
        NSString *roofVP = nil;
        bool overview = false;""")
    source = replace_once(source,
        "            if ([arg isEqualToString:@\"--overview\"]) overview = true;",
        """            if ([arg isEqualToString:@"--roof-probe-mode"] && i + 1 < argc)
                roofMode = parseInteger(argv[++i], 5, @"Roof mode must be 1..5");
            else if ([arg isEqualToString:@"--roof-target"] && i + 1 < argc)
                roofTarget = parseInteger(argv[++i], 100000, @"Invalid roof surface");
            else if ([arg isEqualToString:@"--roof-vp"] && i + 1 < argc) roofVP = @(argv[++i]);
            else if ([arg isEqualToString:@"--overview"]) overview = true;""")
    source = replace_once(source,
        "        renderer->captureWidth = width; renderer->captureHeight = height; renderer->verticalFov = verticalFov;",
        """        require(!roofMode || capture != nil, @"Roof probes require an offscreen capture");
        require(!roofTarget || roofMode >= 3, @"Target surface requires contribution mode");
        require(!roofVP || roofMode, @"VP override requires an instrumented probe");
        renderer->roofProbeMode = roofMode; renderer->roofTargetSurface = roofTarget;
        if (roofVP) {
            renderer->roofMatrixOverride = readFile(roofVP);
            require(renderer->roofMatrixOverride.length == 64, @"VP override must be 16 float32 values");
            const float *values = (const float *)renderer->roofMatrixOverride.bytes;
            for (NSUInteger i = 0; i < 16; i++) require(std::isfinite(values[i]), @"Nonfinite VP override");
        }
        renderer->captureWidth = width; renderer->captureHeight = height; renderer->verticalFov = verticalFov;""")
    return source


def bind_tree(directory):
    return {str(p.resolve()): sha(p) for p in sorted(Path(directory).rglob("*")) if p.is_file()}


def verify_bindings(bindings):
    for filename, digest in bindings.items():
        if sha(filename) != digest:
            raise ValueError("Frozen input changed: " + filename)


def prepare(args):
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Output already exists")
    scene = args.scene.resolve()
    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text())
    manifest = json.loads((scene / "scene.json").read_text())
    if manifest["map"] != "bloodgulch" or manifest["source_sha256"] != "50fe52406f075d975e24100a65b26ff696458023dd3509878953052ab0ef858f":
        raise ValueError("Probe requires the original Blood Gulch scene")
    targets = [m for m in manifest["transparent_bsp_meshes"] if m["name"] == GLYPH]
    if sorted(m["source_surface_first"] for m in targets) != list(range(5423, 5438, 2)):
        raise ValueError("Unexpected original glyph geometry")
    if any(m["is_decal"] or m["two_sided"] or m["alpha_test"] or m["fade_mode"] != 0 or m["blend"] != "add" for m in targets):
        raise ValueError("Unexpected original glyph state")
    originals = bind_tree(SOURCE) | bind_tree(scene) | {str(plan_path): sha(plan_path), str(Path(__file__).resolve()): sha(__file__)}
    if args.original_binary:
        originals[str(args.original_binary.resolve())] = sha(args.original_binary)
    out.mkdir(parents=True)
    snapshot = out / "source-snapshot"
    shutil.copytree(SOURCE, snapshot / "viewer")
    shutil.copytree(scene, out / "scene")
    shutil.copyfile(plan_path, out / "plan.json")
    if args.original_binary:
        shutil.copyfile(args.original_binary, out / "historical-viewer-0.6")
    main = snapshot / "viewer/main.mm"
    probe = out / "probe-main.mm"
    probe.write_text(make_probe_source(main.read_text()))
    commands = []
    for src, binary in [(main, out / "baseline"), (probe, out / "probe")]:
        command = ["xcrun", "clang++", "-std=c++17", "-O2", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-parameter", "-mmacosx-version-min=13.0", str(src), "-framework", "Cocoa",
                   "-framework", "Metal", "-framework", "MetalKit", "-framework", "QuartzCore", "-o", str(binary)]
        with (out / (binary.name + "-build.log")).open("w") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        commands.append({"command": command, "exit_code": completed.returncode})
        if completed.returncode:
            write_json(out / "preparation-failure.json", {"commands": commands, "gpu_executed": False})
            raise ValueError("Host compilation failed: " + binary.name)
    cases = []
    for camera in plan["proposed_cameras"]:
        for width, height in plan["resolutions"]:
            stem = camera["name"] + f"-{width}x{height}"
            for name, mode, target in [("baseline", 0, 0), ("instrumented", 1, 0), ("opaque", 2, 0),
                *[(f"surface{surface}-{name}", mode, surface) for surface in (5423, 5427)
                  for name, mode in (("lequal", 3), ("always", 4), ("always-nocull", 5))]]:
                cases.append({"name": stem + "-" + name, "group": stem, "mode": mode, "surface": target,
                              "camera": camera, "width": width, "height": height, "mip": None})
    if args.mip_controls:
        camera = plan["prior_evidence"]["minimum_case"]
        camera = {"name": camera["name"], "pose": camera["pose"], "vertical_fov": camera["fov"], "recorded": False}
        for level in (0, 3, 4, 6):
            folder = out / f"shader-mip{level}"
            shutil.copytree(snapshot / "viewer", folder)
            p = folder / "TransparentBsp.metal"
            p.write_text(replace_once(p.read_text(), "if (material.kind == 3) color = texture0.sample(repeating, in.uv0);",
                f"if (material.kind == 3) color = texture0.sample(repeating, in.uv0, level({level}.0));"))
            for width, height in plan["resolutions"]:
                group = camera["name"] + f"-{width}x{height}"
                for name, mode in (("lequal", 3), ("always", 4)):
                    cases.append({"name": group + f"-surface5427-{name}-mip{level}", "group": group,
                        "mode": mode, "surface": 5427, "camera": camera, "width": width, "height": height, "mip": level})
    verify_bindings(originals)
    frozen = bind_tree(snapshot) | bind_tree(out / "scene")
    frozen |= {str(p.resolve()): sha(p) for p in (out / "baseline", out / "probe", probe, out / "plan.json")}
    for p in out.glob("shader-mip*"):
        frozen |= bind_tree(p)
    if args.original_binary:
        frozen[str((out / "historical-viewer-0.6").resolve())] = sha(out / "historical-viewer-0.6")
    write_json(out / "prepared.json", {"kind": "roof_static_viewer_gpu_preparation", "schema_version": 1,
        "complete": True, "gpu_executed": False, "production_edits": False, "clipping_reproduced": False,
        "original_source_bindings": originals, "frozen_bindings": frozen, "commands": commands, "cases": cases,
        "source_requested_material": GLYPH, "target_surfaces": [5423, 5427],
        "baseline_source_is_unmodified": True, "historical_binary_source_build_provenance": "not established by this preparation",
        "depth_format": "Depth32Float", "stored_depth_is_after_opaque": "Later original passes have no depth writes",
        "limits": ["No GPU run in preparation", "Existing recorded camera save is not proof of original render-time pose/roll",
                   "Explicit mip, Always and CullNone are test controls, never production fixes", "Static viewer lighting differs from the original game",
                   "No original-Xbox/ANGLE image parity or clipping verdict"]})
    print(json.dumps({"prepared": str(out / "prepared.json"), "sha256": sha(out / "prepared.json"),
                      "case_count": len(cases), "gpu_executed": False}))


def execute(args):
    # This command must be scheduled independently by the caller who owns GPU.
    import numpy as np
    from PIL import Image
    out = args.out.resolve()
    prepared = json.loads((out / "prepared.json").read_text())
    if (out / "execution.json").exists() or (out / "captures").exists():
        raise ValueError("Execution output already exists; preserve the prior attempt")
    verify_bindings(prepared["original_source_bindings"])
    verify_bindings(prepared["frozen_bindings"])
    captures = out / "captures"
    captures.mkdir()
    env = dict(os.environ, MTL_DEBUG_LAYER="1")  # Established test-only API validation setting.
    execution = {"kind": "roof_static_viewer_gpu_execution", "complete": False, "gpu_executed": True,
                 "prepared_sha256": sha(out / "prepared.json"), "environment_overrides": {"MTL_DEBUG_LAYER": "1"}, "runs": []}
    write_json(out / "execution.json", execution)
    images, rows = {}, []
    try:
        for case in prepared["cases"]:
            png = captures / (case["name"] + ".png")
            shaders = out / (f"shader-mip{case['mip']}" if case["mip"] is not None else "source-snapshot/viewer")
            command = [str(out / ("probe" if case["mode"] else "baseline")), "--scene", str(out / "scene"),
                "--shader", str(shaders / "Scene.metal"), "--capture", str(png), "--frames", "1", "--time", "0",
                "--width", str(case["width"]), "--height", str(case["height"]), "--vertical-fov", str(case["camera"]["vertical_fov"]),
                "--camera", *[str(v) for v in case["camera"]["pose"]]]
            if case["mode"]:
                command += ["--roof-probe-mode", str(case["mode"])]
            if case["surface"]:
                command += ["--roof-target", str(case["surface"])]
            if case["mode"] >= 2:
                # Use the exact accepted instrumented-baseline matrix, rather
                # than recalculating a potentially differently optimized VP.
                vp = captures / (case["group"] + "-instrumented.png.world-vp.f32")
                command += ["--roof-vp", str(vp)]
            start = time.monotonic()
            with png.with_suffix(".log").open("w") as log:
                completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
            execution["runs"].append({"name": case["name"], "command": command,
                "exit_code": completed.returncode, "wall_seconds": time.monotonic() - start,
                "api_validation_observed": "Metal API Validation Enabled" in png.with_suffix(".log").read_text()})
            write_json(out / "execution.json", execution)
            if completed.returncode:
                raise ValueError("Capture process failed: " + case["name"])
            if not execution["runs"][-1]["api_validation_observed"]:
                raise ValueError("Metal API validation was not observed")
            image = np.array(Image.open(png).convert("RGBA"))
            images[case["name"]] = image
            metadata = json.loads(Path(str(png) + ".json").read_text())
            row = {"case": case, "image_sha256": sha(png), "metadata_sha256": sha(str(png) + ".json")}
            if case["mode"] == 1:
                baseline = images[case["group"] + "-baseline"]
                row["baseline_differing_pixels"] = int(np.count_nonzero(np.any(image != baseline, axis=2)))
                if row["baseline_differing_pixels"]:
                    rows.append(row)
                    raise ValueError("Instrumentation changed baseline RGB; diagnostic inference is invalid")
            if case["mode"]:
                probe = metadata["roof_probe"]
                for suffix, digest in ((".depth32", probe["depth_sha256"]), (".bgra8", probe["color_bgra_sha256"]),
                                       (".visibility.u64", probe["visibility_sha256"]), (".world-vp.f32", probe["world_vp_sha256"])):
                    if sha(str(png) + suffix) != digest:
                        raise ValueError("Diagnostic payload hash mismatch")
                depth = np.fromfile(str(png) + ".depth32", dtype="<f4")
                if depth.size != case["width"] * case["height"] or not np.all(np.isfinite(depth)) or np.any(depth < 0) or np.any(depth > 1):
                    raise ValueError("Invalid stored depth readback")
                row["depth_range"] = [float(depth.min()), float(depth.max())]
                row["visibility"] = probe["visibility"]
                if case["mode"] >= 3:
                    opaque_name = case["group"] + "-opaque.png.depth32"
                    row["opaque_depth_byte_identical"] = sha(str(png) + ".depth32") == sha(captures / opaque_name)
                    if not row["opaque_depth_byte_identical"]:
                        raise ValueError("Contribution diagnostic changed original opaque depth")
            rows.append(row)
        pairs = []
        for case in prepared["cases"]:
            if case["mode"] != 3:
                continue
            name = case["name"]
            other = name.replace("-lequal", "-always")
            a, b = images[name][:, :, :3], images[other][:, :, :3]
            changed = np.any(a != b, axis=2)
            loss = np.any(b > a, axis=2)
            pair = {"lequal": name, "always": other, "differing_pixels": int(changed.sum()),
                    "pixels_brighter_when_depth_disabled": int(loss.sum()),
                    "max_channel_difference": int(np.abs(b.astype(int) - a.astype(int)).max()),
                    "inference": "A diagnostic depth-dependent contribution difference is not an original-parity bug verdict"}
            if np.any(loss):
                y, x = np.nonzero(loss)
                pair["depth_loss_bbox"] = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
            pairs.append(pair)
        verify_bindings(prepared["original_source_bindings"])
        verify_bindings(prepared["frozen_bindings"])
        result = {"kind": "roof_static_viewer_gpu_diagnostics", "complete": True,
                  "prepared_sha256": execution["prepared_sha256"], "cases": rows, "depth_control_pairs": pairs,
                  "instrumented_baselines_rgb_byte_exact": True, "production_edits": False,
                  "original_clipping_reproduced": False, "fix_proven": False,
                  "limits": prepared["limits"], "outputs": bind_tree(captures)}
        write_json(out / "result.json", result)
        execution["complete"] = True
        execution["result_sha256"] = sha(out / "result.json")
    except Exception as error:
        execution["error"] = str(error)
        write_json(out / "partial-diagnostics.json", {"rows": rows, "complete": False})
        raise
    finally:
        write_json(out / "execution.json", execution)
    print(json.dumps({"result": str(out / "result.json"), "sha256": sha(out / "result.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--out", type=Path, required=True)
    prepare_parser.add_argument("--scene", type=Path, required=True)
    prepare_parser.add_argument("--plan", type=Path, required=True)
    prepare_parser.add_argument("--original-binary", type=Path)
    prepare_parser.add_argument("--mip-controls", action="store_true")
    execute_parser = commands.add_parser("execute")
    execute_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.action == "prepare" else execute)(args)


if __name__ == "__main__":
    main()
