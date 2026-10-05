#!/usr/bin/env python3
"""Test-only actual roof glyph depth and invariance audit; never edits the viewer."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

from metal_roof_gpu_validate import bind_tree, replace_once, sha, verify_bindings, write_json


def prior_control_paths(prior, case):
    """Inputs used by focused identity/query checks, retained before execution."""
    capture = prior / "captures"
    opaque = capture / (case["group"] + "-opaque.png")
    always = capture / (case["group"] + f"-surface{case['surface']}-always.png")
    lequal = capture / (case["group"] + f"-surface{case['surface']}-lequal.png.json")
    return (opaque, Path(str(opaque) + ".depth32"), always, lequal)


def verify_capture_payloads(png, data):
    """Check producer metadata against actual raw bytes, independently of PNG."""
    probe = data["roof_probe"]
    for extension, key in ((".depth32", "depth_sha256"), (".bgra8", "color_bgra_sha256"),
                           (".visibility.u64", "visibility_sha256"), (".world-vp.f32", "world_vp_sha256")):
        if sha(str(png) + extension) != probe[key]:
            raise ValueError("Capture raw payload hash disagrees with producer metadata: " + extension)
    words = Path(str(png) + ".visibility.u64").read_bytes()
    measurement = data["roof_depth_measurement"]
    if len(words) != measurement["query_word_count"] * 8:
        raise ValueError("Unexpected visibility word extent")
    raw = struct.unpack("<" + "Q" * measurement["query_word_count"], words)
    indices = [q["query_word_index"] for q in probe["visibility"]]
    if len(set(indices)) != len(indices) or any(i < 0 or i >= len(raw) for i in indices):
        raise ValueError("Unexpected visibility word indices")
    if [raw[i] for i in indices] != [q["accepted_samples"] for q in probe["visibility"]]:
        raise ValueError("Counting metadata disagrees with actual GPU words")
    if any(word for i, word in enumerate(raw) if i not in indices):
        raise ValueError("An unrelated visibility word was written")
    if probe["mode"] == 7:
        for extension, key in ((".depth-compare.rgba32f", "comparison_file_sha256"),
                               (".opaque-copy.depth32", "opaque_copy_file_sha256")):
            if sha(str(png) + extension) != measurement[key]:
                raise ValueError("Depth measurement payload hash disagrees with metadata")


def comparison_fragment(source):
    body = source[source.index("fragment TransparentBspFragmentOutput transparent_bsp_fragment("):source.index("// Host:")]
    body = replace_once(body, "fragment TransparentBspFragmentOutput transparent_bsp_fragment(",
                        "fragment RoofGlyphDepthOutput roof_glyph_depth_fragment(")
    body = replace_once(body, "    constant TeleporterFrameUniforms &frame [[buffer(0)]],",
                        "    depth2d<float> opaqueDepth [[texture(7)]],\n    constant TeleporterFrameUniforms &frame [[buffer(0)]],")
    body = replace_once(body, "    constexpr sampler repeating(filter::linear, mip_filter::linear, address::repeat);",
                        """    float opaqueZ = opaqueDepth.read(uint2(in.position.xy));
    float4 depths = float4(in.position.z, opaqueZ, in.position.z-opaqueZ,
                           in.position.z <= opaqueZ ? 1.0 : 0.0);
    constexpr sampler repeating(filter::linear, mip_filter::linear, address::repeat);""")
    body = replace_once(body, "return {float4(0.0), 0xffffffffu};", "return {float4(0.0), depths, 0xffffffffu};")
    body = replace_once(body, "return {float4(contribution, clamp(color.a, 0.0, 1.0)), 0xffffffffu};",
                        "return {float4(contribution, clamp(color.a, 0.0, 1.0)), depths, 0xffffffffu};")
    return """// Test-only fragment: the original RGB body is retained below. Depth
// comparison reads a distinct, stored then blit-copied opaque depth texture.
struct RoofGlyphDepthOutput {
    float4 color [[color(0)]];
    float4 depths [[color(1)]];
    uint sampleMask [[sample_mask]];
};
""" + body


def make_depth_probe(source):
    source = replace_once(source, '@"first_index": @(transparentBspMeshes[i].first),',
                          '@"first_index": @(transparentBspMeshes[i].first), @"query_word_index": @(i),')
    source = replace_once(source, "    id<MTLBuffer> roofVisibility, roofDepthReadback;", """    id<MTLBuffer> roofVisibility, roofDepthReadback, roofReferenceReadback;
    id<MTLTexture> roofDepthReference, roofDepthComparison;
    id<MTLRenderPipelineState> roofComparisonPipeline;
    id<MTLDepthStencilState> roofGlyphWriteState;""")
    source = replace_once(source, "    desc.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;", """    if ([fragment isEqualToString:@"roof_glyph_depth_fragment"])
        desc.colorAttachments[1].pixelFormat = MTLPixelFormatRGBA32Float;
    desc.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;""")
    source = replace_once(source, '@"Teleporter.metal", @"TransparentBsp.metal"]',
                          '@"Teleporter.metal", @"TransparentBsp.metal", @"RoofGlyphDepth.metal"]')
    source = replace_once(source, "    MTLDepthStencilDescriptor *depth = [MTLDepthStencilDescriptor new];", """    roofComparisonPipeline = scenePipeline(device, library, @"transparent_bsp_vertex", @"roof_glyph_depth_fragment",
        true, MTLBlendFactorOne, MTLBlendFactorOne, true);
    MTLDepthStencilDescriptor *depth = [MTLDepthStencilDescriptor new];""")
    source = replace_once(source, "    require(depthState && skyDepthState && overlayDepthState, @\"Could not create depth states\");", """    require(depthState && skyDepthState && overlayDepthState, @"Could not create depth states");
    depth.depthCompareFunction = MTLCompareFunctionAlways;
    depth.depthWriteEnabled = YES;
    roofGlyphWriteState = [device newDepthStencilStateWithDescriptor:depth];
    require(roofGlyphWriteState != nil, @"Could not create glyph depth measurement state");""")
    source = replace_once(source, "        MTLRenderPassDescriptor *contribution = [pass copy];", """        if (roofProbeMode == 7) {
            // Store from the first encoder precedes this exact texture copy.
            // Sampling a distinct resource avoids an attachment feedback loop.
            id<MTLBlitCommandEncoder> copy = [command blitCommandEncoder];
            require(copy != nil, @"Could not create opaque depth copy encoder");
            [copy copyFromTexture:pass.depthAttachment.texture sourceSlice:0 sourceLevel:0
                     sourceOrigin:MTLOriginMake(0, 0, 0)
                       sourceSize:MTLSizeMake((NSUInteger)size.width, (NSUInteger)size.height, 1)
                        toTexture:roofDepthReference destinationSlice:0 destinationLevel:0
                destinationOrigin:MTLOriginMake(0, 0, 0)];
            [copy endEncoding];
        }
        MTLRenderPassDescriptor *contribution = [pass copy];
        if (roofProbeMode == 7) {
            contribution.colorAttachments[1].texture = roofDepthComparison;
            contribution.colorAttachments[1].loadAction = MTLLoadActionClear;
            contribution.colorAttachments[1].storeAction = MTLStoreActionStore;
            contribution.colorAttachments[1].clearColor = MTLClearColorMake(-1, -1, -1, -1);
        }""")
    source = replace_once(source, "        [encoder setRenderPipelineState:transparentBspPipeline];", """        [encoder setRenderPipelineState:roofProbeMode == 7 ? roofComparisonPipeline : transparentBspPipeline];
        if (roofProbeMode == 7) [encoder setFragmentTexture:roofDepthReference atIndex:7];""")
    source = replace_once(source, "[encoder setDepthStencilState:roofProbeMode >= 4 ? skyDepthState : overlayDepthState];",
                          "[encoder setDepthStencilState:roofProbeMode == 6 ? roofGlyphWriteState : (roofProbeMode >= 4 ? skyDepthState : overlayDepthState)];")
    source = replace_once(source, "    double cpu = 0, gpu = 0;", """    if (roofProbeMode == 7) {
        MTLTextureDescriptor *reference = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float
            width:width height:height mipmapped:NO];
        reference.storageMode = MTLStorageModePrivate; reference.usage = MTLTextureUsageShaderRead;
        roofDepthReference = [device newTextureWithDescriptor:reference];
        reference.pixelFormat = MTLPixelFormatRGBA32Float;
        reference.storageMode = MTLStorageModeShared; reference.usage = MTLTextureUsageRenderTarget;
        roofDepthComparison = [device newTextureWithDescriptor:reference];
        roofReferenceReadback = [device newBufferWithLength:roofDepthPitch * height options:MTLResourceStorageModeShared];
        require(roofDepthReference && roofDepthComparison && roofReferenceReadback, @"Depth comparison allocation failed");
    }
    double cpu = 0, gpu = 0;""")
    source = replace_once(source, "                [blit endEncoding];", """                if (roofProbeMode == 7)
                    [blit copyFromTexture:roofDepthReference sourceSlice:0 sourceLevel:0
                            sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(width, height, 1)
                               toBuffer:roofReferenceReadback destinationOffset:0
                 destinationBytesPerRow:roofDepthPitch destinationBytesPerImage:roofDepthPitch * height];
                [blit endEncoding];""")
    source = replace_once(source, "        NSMutableDictionary *augmented = [metrics mutableCopy];", """        NSData *comparisonData = nil, *referenceData = nil;
        if (roofProbeMode == 7) {
            std::vector<float> comparison(width * height * 4);
            [roofDepthComparison getBytes:comparison.data() bytesPerRow:width * 16
                              fromRegion:MTLRegionMake2D(0, 0, width, height) mipmapLevel:0];
            comparisonData = [NSData dataWithBytes:comparison.data() length:comparison.size() * 4];
            std::vector<uint8_t> reference(width * height * 4);
            for (NSUInteger row = 0; row < height; row++)
                memcpy(reference.data() + row * width * 4,
                    (const uint8_t *)roofReferenceReadback.contents + row * roofDepthPitch, width * 4);
            referenceData = [NSData dataWithBytes:reference.data() length:reference.size()];
            require([comparisonData writeToFile:[path stringByAppendingString:@".depth-compare.rgba32f"] atomically:YES] &&
                    [referenceData writeToFile:[path stringByAppendingString:@".opaque-copy.depth32"] atomically:YES],
                    @"Depth comparison write failed");
        }
        NSMutableDictionary *augmented = [metrics mutableCopy];
        augmented[@"roof_depth_measurement"] = @{@"original_fragment_shader": @(roofProbeMode != 7),
            @"query_word_count": @(roofVisibility.length / 8),
            @"glyph_depth_write": @(roofProbeMode == 6), @"depth_compare": @"Always_for_measurement",
            @"comparison_shader_rgb_retains_original_body": @(roofProbeMode == 7),
            @"comparison_channels": @[@"actual_raster_glyph_z", @"stored_opaque_z", @"glyph_minus_opaque", @"glyph_LEQUAL_opaque"],
            @"comparison_file_sha256": comparisonData ? sha256(comparisonData) : @"",
            @"opaque_copy_file_sha256": referenceData ? sha256(referenceData) : @"",
            @"stored_then_blit_copied_distinct_opaque_depth": @(roofProbeMode == 7)};""")
    source = replace_once(source, 'parseInteger(argv[++i], 5, @"Roof mode must be 1..5")',
                          'parseInteger(argv[++i], 7, @"Roof mode must be 1..7")')
    return source


def prepare(args):
    prior, out = args.prior.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError("Output already exists")
    old = json.loads((prior / "prepared.json").read_text())
    result = json.loads((prior / "result.json").read_text())
    verify_bindings(old["frozen_bindings"]); verify_bindings(old["original_source_bindings"]); verify_bindings(result["outputs"])
    if not result["complete"] or not result["instrumented_baselines_rgb_byte_exact"]:
        raise ValueError("Prior GPU baseline identity is required")
    out.mkdir(parents=True)
    shutil.copytree(prior / "scene", out / "scene")
    for variant in ("original", "invariant"):
        folder = out / variant
        shutil.copytree(prior / "source-snapshot/viewer", folder)
        if variant == "invariant":
            for name in ("Scene.metal", "TransparentBsp.metal"):
                p = folder / name
                p.write_text(replace_once(p.read_text(), "float4 position [[position]];", "float4 position [[position, invariant]];"))
        (folder / "RoofGlyphDepth.metal").write_text(comparison_fragment((folder / "TransparentBsp.metal").read_text()))
        combined = "\n".join((folder / name).read_text().replace('#include "Fog.metal"', "") for name in
            ("Fog.metal", "Scene.metal", "Sky.metal", "Decal.metal", "Teleporter.metal", "TransparentBsp.metal", "RoofGlyphDepth.metal"))
        (folder / "combined.metal").write_text(combined)
    probe = out / "depth-probe-main.mm"
    probe.write_text(make_depth_probe((prior / "probe-main.mm").read_text()))
    commands = [["xcrun", "clang++", "-std=c++17", "-O2", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-mmacosx-version-min=13.0", str(probe), "-framework", "Cocoa", "-framework", "Metal",
        "-framework", "MetalKit", "-framework", "QuartzCore", "-o", str(out / "depth-probe")]]
    commands.extend(["xcrun", "-sdk", "macosx", "metal", "-std=metal3.0", "-fno-fast-math", "-c",
                     str(out / variant / "combined.metal"), "-o", str(out / variant / "validation.air")]
                    for variant in ("original", "invariant"))
    observed = []
    offline_msl_validated = True
    for index, command in enumerate(commands):
        with (out / f"compile-{index}.log").open("w") as log:
            cp = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        observed.append({"command": command, "exit_code": cp.returncode})
        if cp.returncode:
            if index > 0 and "cannot execute tool 'metal' due to missing Metal Toolchain" in (out / f"compile-{index}.log").read_text():
                observed[-1]["limitation"] = "Offline Metal compiler unavailable; runtime compilation remains required"
                offline_msl_validated = False
                continue
            write_json(out / "preparation-failure.json", {"commands": observed, "gpu_executed": False})
            raise ValueError("Strict host or offline Metal compilation failed")
    cases = []
    for c in old["cases"]:
        if c["mode"] != 1:
            continue
        if args.focused and c["camera"]["name"] != "center-z6.5-surface5427":
            continue
        surface = 5423 if c["camera"]["name"] == "roof-3" else 5427
        for variant in ("original", "invariant"):
            for label, mode in (("baseline", 1), ("opaque", 2), ("lequal", 3), ("always", 4), ("glyph-depth", 6), ("gpu-compare", 7)):
                if args.focused and mode not in (2, 4, 6, 7):
                    continue
                cases.append({"name": c["group"] + f"-{variant}-{label}", "group": c["group"],
                    "variant": variant, "mode": mode, "surface": surface if mode >= 3 else 0,
                    "camera": c["camera"], "width": c["width"], "height": c["height"],
                    "vp": str(prior / "captures" / (c["name"] + ".png.world-vp.f32")),
                    "prior_baseline": str(prior / "captures" / (c["name"] + ".png"))})
    shutil.copy2(Path(__file__), out / "preparation-helper.py")
    shutil.copy2(Path(__file__).with_name("metal_roof_gpu_validate.py"), out / "preparation-dependency.py")
    frozen = bind_tree(out)
    originals = {str(Path(__file__).resolve()): sha(__file__), str(prior / "prepared.json"): sha(prior / "prepared.json"),
        str(prior / "result.json"): sha(prior / "result.json"), str(prior / "probe-main.mm"): sha(prior / "probe-main.mm"),
        str(Path(__file__).with_name("metal_roof_gpu_validate.py")): sha(Path(__file__).with_name("metal_roof_gpu_validate.py"))}
    for c in cases:
        for field in ("vp", "prior_baseline"):
            originals[c[field]] = sha(c[field])
        if c["surface"]:
            for path in prior_control_paths(prior, c):
                originals[str(path)] = sha(path)
    verify_bindings(old["frozen_bindings"]); verify_bindings(result["outputs"])
    write_json(out / "prepared.json", {"kind": "roof_actual_glyph_depth_preparation", "complete": True,
        "gpu_executed": False, "production_edits": False, "prior": str(prior), "original_bindings": originals,
        "frozen_bindings": frozen, "commands": observed, "cases": cases,
        "strict_host_compile_passed": True, "offline_msl_validated": offline_msl_validated,
        "focused16": args.focused,
        "barrier_contract": "Opaque encoder Store -> separate blit copy -> next contribution encoder samples distinct texture7",
        "limits": ["GPU not executed in preparation", "Offline Metal compiler unavailable; runtime shader syntax/compilation remains unverified",
                   "No original ANGLE comparison yet", "Actual user pose remains unknown",
                   "Always+write and MRT/invariance are test-only controls; no production fix"]})
    print(json.dumps({"prepared": str(out / "prepared.json"), "sha256": sha(out / "prepared.json"), "cases": len(cases), "gpu_executed": False}))


def execute(args):
    import numpy as np
    from PIL import Image
    out = args.out.resolve()
    prep = json.loads((out / "prepared.json").read_text())
    if (out / "captures").exists() or (out / "execution.json").exists():
        raise ValueError("Execution already attempted; preserve it")
    verify_bindings(prep["original_bindings"]); verify_bindings(prep["frozen_bindings"])
    captures = out / "captures"; captures.mkdir()
    env = dict(os.environ, MTL_DEBUG_LAYER="1")
    execution = {"kind": "roof_actual_glyph_depth_execution", "complete": False, "prepared_sha256": sha(out / "prepared.json"),
        "environment_overrides": {"MTL_DEBUG_LAYER": "1"}, "runs": []}
    write_json(out / "execution.json", execution)
    rows = []
    images, depths, metadata = {}, {}, {}
    try:
        for c in prep["cases"]:
            png = captures / (c["name"] + ".png")
            command = [str(out / "depth-probe"), "--scene", str(out / "scene"), "--shader", str(out / c["variant"] / "Scene.metal"),
                "--capture", str(png), "--frames", "1", "--time", "0", "--width", str(c["width"]), "--height", str(c["height"]),
                "--vertical-fov", str(c["camera"]["vertical_fov"]), "--camera", *map(str, c["camera"]["pose"]),
                "--roof-probe-mode", str(c["mode"]), "--roof-vp", c["vp"]]
            if c["surface"]:
                command += ["--roof-target", str(c["surface"])]
            start = time.monotonic()
            with png.with_suffix(".log").open("w") as log:
                cp = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=60)
            validation = "Metal API Validation Enabled" in png.with_suffix(".log").read_text()
            execution["runs"].append({"name": c["name"], "command": command, "exit_code": cp.returncode,
                                      "wall_seconds": time.monotonic()-start, "api_validation_observed": validation})
            write_json(out / "execution.json", execution)
            if cp.returncode or not validation:
                raise ValueError("Capture failed or API validation was not observed: " + c["name"])
            rgb = np.asarray(Image.open(png).convert("RGB"))
            image_key = (c["group"], c["variant"], c["mode"])
            images[image_key] = rgb
            data = json.loads(Path(str(png) + ".json").read_text())
            verify_capture_payloads(png, data)
            metadata[image_key] = data
            depth = np.fromfile(str(png) + ".depth32", dtype="<f4").reshape(c["height"], c["width"])
            depths[image_key] = depth
            if not np.all(np.isfinite(depth)) or np.any(depth < 0) or np.any(depth > 1):
                raise ValueError("Invalid GPU depth")
            if Path(str(png) + ".world-vp.f32").read_bytes() != Path(c["vp"]).read_bytes():
                raise ValueError("Saved original VP was not retained")
            row = {"case": c, "png_sha256": sha(png), "depth_sha256": sha(str(png) + ".depth32")}
            if c["mode"] == 1 and c["variant"] == "original":
                if not np.array_equal(rgb, np.asarray(Image.open(c["prior_baseline"]).convert("RGB"))):
                    raise ValueError("New original instrumentation changed the frozen prior baseline")
                row["prior_baseline_rgb_exact"] = True
            if prep["focused16"] and c["variant"] == "original" and c["mode"] in (2, 4):
                suffix = "-opaque" if c["mode"] == 2 else f"-surface{c['surface']}-always"
                prior_path = Path(prep["prior"]) / "captures" / (c["group"] + suffix + ".png")
                if not np.array_equal(rgb, np.asarray(Image.open(prior_path).convert("RGB"))):
                    raise ValueError("Focused original control changed prior RGB")
                if c["mode"] == 2 and Path(str(png) + ".depth32").read_bytes() != Path(str(prior_path) + ".depth32").read_bytes():
                    raise ValueError("Focused original opaque control changed prior depth")
                row["prior_component_rgb_exact"] = True
            if c["mode"] in (6, 7) and not np.array_equal(rgb, images[(c["group"], c["variant"], 4)]):
                raise ValueError("Glyph measurement changed original Always RGB")
            if c["mode"] == 7:
                reference = np.fromfile(str(png) + ".opaque-copy.depth32", dtype="<f4").reshape(c["height"], c["width"])
                if not np.array_equal(reference.view(np.uint32), depths[(c["group"], c["variant"], 2)].view(np.uint32)):
                    raise ValueError("Opaque depth copy/barrier changed stored bits")
                values = np.fromfile(str(png) + ".depth-compare.rgba32f", dtype="<f4").reshape(c["height"], c["width"], 4)
                covered = values[:, :, 3] != -1
                if not np.all(np.isfinite(values)) or not np.all(np.isin(values[covered, 3], [0, 1])):
                    raise ValueError("Invalid comparison values")
                r, g, delta, less_equal = values[covered].T
                if not np.array_equal(g.view(np.uint32), reference[covered].view(np.uint32)):
                    raise ValueError("Per-fragment opaque fetch disagrees with stored depth")
                if not np.array_equal(delta.view(np.uint32), (r-g).view(np.uint32)) or not np.array_equal(less_equal, (r<=g).astype(np.float32)):
                    raise ValueError("GPU float comparison/subtraction disagrees with raw float32 oracle")
                glyph_stored = depths[(c["group"], c["variant"], 6)]
                row["glyph_raster_vs_written_depth_differing_words"] = int(np.count_nonzero(r.view(np.uint32) != glyph_stored[covered].view(np.uint32)))
                row["covered_pixels"] = int(covered.sum())
                row["gpu_LEQUAL_pixels"] = int(np.count_nonzero(less_equal))
                row["gpu_farther_pixels"] = int(np.count_nonzero(r>g))
                row["max_glyph_opaque_abs_difference"] = float(np.abs(delta).max()) if len(delta) else 0
                count = next(q["accepted_samples"] for q in data["roof_probe"]["visibility"] if q["source_surface_first"] == c["surface"])
                lequal_metadata = metadata.get((c["group"], c["variant"], 3))
                if lequal_metadata is None and c["variant"] == "original":
                    prior_lequal = Path(prep["prior"]) / "captures" / (c["group"] + f"-surface{c['surface']}-lequal.png.json")
                    lequal_metadata = json.loads(prior_lequal.read_text())
                lequal_count = next(q["accepted_samples"] for q in lequal_metadata["roof_probe"]["visibility"] if q["source_surface_first"] == c["surface"]) if lequal_metadata else None
                row["Counting_query_matches_covered_pixels"] = count == row["covered_pixels"]
                row["Counting_LEQUAL_matches_GPU_float_comparison"] = lequal_count == row["gpu_LEQUAL_pixels"] if lequal_count is not None else None
            rows.append(row)
        verify_bindings(prep["original_bindings"]); verify_bindings(prep["frozen_bindings"])
        result = {"kind": "roof_actual_glyph_depth_result", "complete": True, "rows": rows,
            "prepared_sha256": execution["prepared_sha256"], "output_bindings": bind_tree(captures),
            "production_edits": False, "original_ANGLE_parity": False, "user_clipping_reproduced": False, "fix_proven": False}
        write_json(out / "result.json", result)
        execution["complete"] = True; execution["result_sha256"] = sha(out / "result.json")
    except Exception as error:
        execution["error"] = str(error)
        write_json(out / "partial-result.json", {"rows": rows, "complete": False})
        raise
    finally:
        write_json(out / "execution.json", execution)
    print(json.dumps({"result": str(out / "result.json"), "sha256": sha(out / "result.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    p = commands.add_parser("prepare"); p.add_argument("--prior", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--focused", action="store_true", help="Sixteen synthetic-pose depth cases first; recorded controls remain a separate72-case preparation")
    p = commands.add_parser("execute"); p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.action == "prepare" else execute)(args)


if __name__ == "__main__":
    main()
