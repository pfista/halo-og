#!/usr/bin/env python3
"""Independent CPU audit of an actual-camera static roof capture.

Original color deltas measure visible RGB contribution, not original GPU
coverage. Cross-renderer depth arithmetic and whole-scene shading remain
separate limits. This tool never launches GPU work or changes sources.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def verify(bindings):
    for path, expected in bindings.items():
        if sha(path) != expected:
            raise ValueError("Audit input changed: " + path)


def bbox(mask):
    y, x = np.where(mask)
    return [int(x.min()), int(y.min()), int(x.max())+1, int(y.max())+1] if len(x) else None


def run(args):
    angle, native, out = args.angle_run.resolve(), args.replay.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError("Audit output already exists; preserve attempts")
    prepared, native_result = read(native / "prepared.json"), read(native / "result.json")
    angle_result, angle_execution = read(angle / "result.json"), read(angle / "execution.json")
    if not native_result["complete"] or not angle_result["complete"] or not angle_execution["complete"] or angle_execution["exit_code"]:
        raise ValueError("Both actual capture processes must complete before audit")
    verify(prepared["original_bindings"]); verify(prepared["frozen_bindings"])
    verify(native_result["outputs"]); verify(angle_result["output_bindings"]); verify(angle_result["captured_payload_bindings"])
    if native_result["prepared_sha256"] != sha(native / "prepared.json"):
        raise ValueError("Native result references a different preparation")
    out.mkdir(parents=True)
    frame = angle / "saves/metal-frames/frame480"
    draw = read(frame / "draw-0074.json")
    events = [json.loads(line) for line in (frame / "events.jsonl").read_text().splitlines()]
    event = next(e for e in events if e.get("use") == 74 and e["kind"] == "draw")
    targets = {(t["target_id"], t["version"]): (p, t) for p in frame.glob("target*.json") for t in [read(p)]}
    def attachment(which, boundary, payload, dtype, shape):
        ref = event[boundary][which]
        path, target = targets[(ref["target_id"], ref["version"])]
        if not target["complete"] or (target["width"], target["height"], target["orientation"]) != (640, 480, "top_left"):
            raise ValueError("Unexpected actual original target geometry/orientation")
        blob = frame / target[payload]["file"]
        if blob.stat().st_size != target[payload]["bytes"]:
            raise ValueError("Original attachment extent mismatch")
        return np.frombuffer(blob.read_bytes(), dtype=dtype).reshape(shape), {"record": str(path), "record_sha256": sha(path),
            "payload": str(blob), "sha256": sha(blob), "target_id": ref["target_id"], "version": ref["version"]}
    before, before_ref = attachment("color", "before", "color", np.uint8, (480, 640, 4))
    after, after_ref = attachment("color", "after", "color", np.uint8, (480, 640, 4))
    original_depth, depth_ref = attachment("depth_stencil", "before", "depth_values", "<f4", (480, 640))
    original_after_depth, _ = attachment("depth_stencil", "after", "depth_values", "<f4", (480, 640))
    stencil, stencil_ref = attachment("depth_stencil", "before", "stencil_values", np.uint8, (480, 640))
    after_stencil, _ = attachment("depth_stencil", "after", "stencil_values", np.uint8, (480, 640))
    if not np.array_equal(original_depth.view("<u4"), original_after_depth.view("<u4")) or not np.array_equal(stencil, after_stencil) or not np.array_equal(before[:, :, 3], after[:, :, 3]):
        raise ValueError("Original glyph unexpectedly changed alpha/depth/stencil")
    delta = after[:, :, :3].astype(np.int16)-before[:, :, :3].astype(np.int16)
    if np.any(delta < 0):
        raise ValueError("Original additive glyph decreased RGB")
    original_rgb = np.any(delta != 0, axis=2)
    Image.fromarray(np.asarray(delta, dtype=np.uint8)).save(out / "original-use74-visible-rgb-delta.png")
    rows, records = [], []
    for variant in ("static-arithmetic", "original-viewport-bridge"):
        data = {}
        for suffix in ("full-scene", "opaque", "glyph-lequal", "glyph-always", "glyph-depth-mrt"):
            png = native / "captures" / (variant+"-"+suffix+".png")
            meta = read(str(png)+".json")
            run_record = next(r for r in native_result["actual_runs"] if r["name"] == variant+"-"+suffix)
            if run_record["exit_code"] or not run_record["api_validation_observed"] or "Metal API Validation Enabled" not in png.with_suffix(".log").read_text():
                raise ValueError("An actual native child failed or API validation was absent")
            probe, measurement = meta["roof_probe"], meta["roof_depth_measurement"]
            for extension, expected in ((".bgra8", probe["color_bgra_sha256"]), (".depth32", probe["depth_sha256"]),
                (".visibility.u64", probe["visibility_sha256"]), (".world-vp.f32", probe["world_vp_sha256"])):
                if sha(str(png)+extension) != expected:
                    raise ValueError("Producer metadata differs from actual raw bytes")
            if Path(str(png)+".world-vp.f32").read_bytes() != (native / "captured-world-vp.f32").read_bytes() or measurement["captured_frame_sha256"] != sha(native / "captured-frame.f32"):
                raise ValueError("Native matrix/frame differs from actual original captured inputs")
            bgra = np.fromfile(str(png)+".bgra8", dtype=np.uint8).reshape(480, 640, 4)
            rgb = bgra[:, :, [2, 1, 0]]
            if not np.array_equal(rgb, np.asarray(Image.open(png).convert("RGB"))):
                raise ValueError("Native PNG and raw target RGB disagree")
            words = np.fromfile(str(png)+".visibility.u64", dtype="<u8")
            if words.size != measurement["query_word_count"]:
                raise ValueError("Native query extent mismatch")
            indices = [v["query_word_index"] for v in probe["visibility"]]
            if len(indices) != len(set(indices)) or any(i < 0 or i >= words.size for i in indices):
                raise ValueError("Invalid query index mapping")
            for v in probe["visibility"]:
                if int(words[v["query_word_index"]]) != v["accepted_samples"]:
                    raise ValueError("Query metadata does not match GPU words")
            if any(int(word) for i, word in enumerate(words) if i not in indices):
                raise ValueError("Unrelated query word was written")
            depth = np.fromfile(str(png)+".depth32", dtype="<f4").reshape(480, 640)
            if not np.all(np.isfinite(depth)) or np.any(depth < 0) or np.any(depth > 1):
                raise ValueError("Invalid native stored depth")
            if suffix != "full-scene" and suffix != "opaque":
                nonzero = [v for v in probe["visibility"] if v["accepted_samples"]]
                if len(nonzero) != 1 or nonzero[0]["source_surface_first"] != 5427:
                    raise ValueError("Contribution query does not identify exactly source5427")
            data[suffix] = {"png": str(png), "rgb": rgb, "depth": depth, "meta": meta}
            records.append({"variant": variant, "control": suffix, "png": str(png), "png_sha256": sha(png),
                "raw_rgb_exact": True, "query_words_verified": True, "actual_exit": run_record["exit_code"]})
        opaque = data["opaque"]["depth"]
        if any(item["depth"].tobytes() != opaque.tobytes() for item in data.values()):
            raise ValueError("A no-depth-write diagnostic changed stored opaque depth")
        mrt_png = data["glyph-depth-mrt"]["png"]
        measurement = data["glyph-depth-mrt"]["meta"]["roof_depth_measurement"]
        if sha(mrt_png+".depth-compare.rgba32f") != measurement["comparison_file_sha256"] or sha(mrt_png+".opaque-copy.depth32") != measurement["opaque_copy_file_sha256"]:
            raise ValueError("MRT/barrier payload hash mismatch")
        mrt = np.fromfile(mrt_png+".depth-compare.rgba32f", dtype="<f4").reshape(480, 640, 4)
        copied = np.fromfile(mrt_png+".opaque-copy.depth32", dtype="<f4").reshape(480, 640)
        if copied.tobytes() != opaque.tobytes() or not np.array_equal(data["glyph-depth-mrt"]["rgb"], data["glyph-always"]["rgb"]):
            raise ValueError("MRT instrumentation changed original RGB or stored/copied opaque depth")
        covered = mrt[:, :, 0] >= 0
        if not np.all(np.isfinite(mrt[covered])) or not np.array_equal(mrt[:, :, 1][covered].view("<u4"), opaque[covered].view("<u4")):
            raise ValueError("Fragment sampled a different opaque depth")
        lequal = covered & (mrt[:, :, 0] <= opaque)
        if not np.array_equal(mrt[:, :, 3][covered].astype(bool), lequal[covered]):
            raise ValueError("GPU fragment compare disagrees with exact CPU float32 compare")
        always_query = next(v["accepted_samples"] for v in data["glyph-always"]["meta"]["roof_probe"]["visibility"] if v["source_surface_first"] == 5427)
        lequal_query = next(v["accepted_samples"] for v in data["glyph-lequal"]["meta"]["roof_probe"]["visibility"] if v["source_surface_first"] == 5427)
        if int(covered.sum()) != always_query or int(lequal.sum()) != lequal_query:
            raise ValueError("Independent MRT coverage/depth comparison differs from GPU queries")
        native_loss = np.any(data["glyph-always"]["rgb"] != data["glyph-lequal"]["rgb"], axis=2)
        if np.any(native_loss & lequal):
            raise ValueError("RGB difference occurs despite accepted identical fragment")
        failed = covered & ~lequal
        original_depth_pass = covered & (mrt[:, :, 0] <= original_depth)
        visible_original_loss = native_loss & original_rgb
        loss_png = np.zeros((480, 640, 3), dtype=np.uint8)
        loss_png[native_loss] = [255, 0, 0]
        loss_png[visible_original_loss] = [255, 255, 0]
        Image.fromarray(loss_png).save(out / (variant+"-native-loss-mask.png"))
        pixel_records = []
        for y, x in zip(*np.where(failed)):
            glyph = mrt[y, x, 0]
            pixel_records.append({"x": int(x), "y": int(y), "glyph_z_bits": int(glyph.view("<u4")),
                "native_opaque_z_bits": int(opaque[y, x].view("<u4")), "original_opaque_z_bits": int(original_depth[y, x].view("<u4")),
                "glyph_minus_native_opaque_ulps": int(glyph.view("<u4"))-int(opaque[y, x].view("<u4")),
                "native_rgb_lost": bool(native_loss[y, x]), "original_rgb_delta": delta[y, x].tolist(),
                "would_pass_original_stored_depth_using_native_glyph_z": bool(original_depth_pass[y, x]),
                "original_stencil": int(stencil[y, x])})
        write(out / (variant+"-depth-rejections.json"), pixel_records)
        roi_mask = covered | original_rgb
        region = bbox(roi_mask)
        x0, y0, x1, y1 = region
        roi = [max(0, x0-5), max(0, y0-5), min(640, x1+5), min(480, y1+5)]
        originals = np.asarray(Image.open(angle / "selected-frame.png").convert("RGB"))
        tiles = [("Original ANGLE", originals), ("Static full scene", data["full-scene"]["rgb"]),
                 ("Original visible RGB delta x4", np.minimum(delta*4, 255).astype(np.uint8)),
                 ("Static LEQUAL", data["glyph-lequal"]["rgb"]), ("Static Always control", data["glyph-always"]["rgb"]),
                 ("Native depth loss; yellow=original RGB", loss_png)]
        tile_w, tile_h = (roi[2]-roi[0])*4, (roi[3]-roi[1])*4+24
        montage = Image.new("RGB", (tile_w*3, tile_h*2), "#333333")
        painter = ImageDraw.Draw(montage)
        for i, (label, image) in enumerate(tiles):
            tile = Image.fromarray(image).crop(roi).resize((tile_w, tile_h-24), Image.Resampling.NEAREST)
            left, top = (i % 3)*tile_w, (i // 3)*tile_h
            montage.paste(tile, (left, top+24)); painter.text((left+3, top+5), label, fill="white")
        montage.save(out / (variant+"-glyph-comparison.png"))
        rows.append({"variant": variant, "native_fragment_coverage": int(covered.sum()), "native_lequal_samples": int(lequal.sum()),
            "native_depth_rejected_samples": int(failed.sum()), "native_nonzero_rgb_loss_pixels": int(native_loss.sum()),
            "native_rgb_loss_bbox": bbox(native_loss), "native_rgb_loss_with_original_visible_rgb_delta": int(visible_original_loss.sum()),
            "native_glyph_would_pass_original_stored_depth_samples": int(original_depth_pass.sum()),
            "native_rejections_would_pass_original_stored_depth": int((failed & original_depth_pass).sum()),
            "original_stencil_nonzero_at_native_rejections": int(np.count_nonzero(stencil[failed])),
            "exact_gpu_query_matches_independent_mrt_compare": True, "opaque_depth_barrier_readback_byte_exact": True,
            "mrt_original_rgb_byte_exact": True, "review_crop": roi,
            "scope": "Original delta is visible RGB contribution; native query/MRT is GPU coverage/depth. These are different measurements."})
    verify(prepared["original_bindings"]); verify(prepared["frozen_bindings"]); verify(native_result["outputs"])
    verify(angle_result["output_bindings"]); verify(angle_result["captured_payload_bindings"])
    closure = {"kind": "independent_actual_camera_roof_comparison", "complete": True, "gpu_launched_by_auditor": False,
        "auditor": {"file": str(Path(__file__).resolve()), "sha256": sha(__file__)},
        "angle_result": {"file": str(angle / "result.json"), "sha256": sha(angle / "result.json")},
        "native_result": {"file": str(native / "result.json"), "sha256": sha(native / "result.json")},
        "source_and_payload_hashes_rederived_before_after": True, "actual_native_runs_verified": len(records), "native_controls": records,
        "actual_original_event": event, "original_before_color": before_ref, "original_after_color": after_ref,
        "original_before_depth": depth_ref, "original_before_stencil": stencil_ref,
        "original_visible_rgb_delta_pixels": int(original_rgb.sum()), "original_visible_rgb_delta_bbox": bbox(original_rgb),
        "original_alpha_depth_stencil_unchanged": True, "variants": rows,
        "production_changes": False, "clipping_fix_proven": False, "user_exact_camera_reproduction": False,
        "original_Xbox_hardware_or_fullgame_parity": False, "limits": prepared["limits"] + [
            "Reference delta can be zero due to black texels, saturation or output quantization; it is not original GPU coverage",
            "Using native glyph depth against original stored depth is a cross-renderer diagnostic, not original glyph fragment-depth readback",
            "Whole-scene RGB differs because the static viewer does not execute every original pass/object"]}
    closure["audit_outputs"] = {str(p): sha(p) for p in out.rglob("*") if p.is_file()}
    write(out / "closure.json", closure)
    print(json.dumps({"closure": str(out / "closure.json"), "sha256": sha(out / "closure.json"),
        "original_visible_pixels": int(original_rgb.sum()), "variants": rows}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--angle-run", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
