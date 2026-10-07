"""Format-based asset overlays produced by local, source-bound native helpers."""
from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
import shutil
import subprocess

from .backend import ConversionError
from .profiles import ROOT
from ..community_maps import digest

KINDS = {"audio": (".sound", "convert_audio.cpp", "xbox_adpcm"),
         "bitmaps": (".bitmap", "convert_bitmaps.cpp", "dxt5"),
         "mips": (".bitmap", "select_native_mips.cpp", "existing_authored_mips"),
         "packing": (".bitmap", "pack_lossless_bitmaps.cpp", "lossless_native_pixels"),
         "extensions": (".hud_globals", "omit_mcc_extensions.cpp", "native_xbox_fields"),
         "hud": (".hud", "normalize_mcc_hud.cpp", "native_xbox_hud")}
MAX_OUTPUT = 8 * 1024 * 1024


def _json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def checked_tag(root: Path, name: str, suffix: str) -> Path:
    relative = PurePosixPath(name)
    if (not name or relative.is_absolute() or relative.as_posix() != name
            or any(part in ("", ".", "..") for part in name.split("/"))
            or any(c in name for c in "\\\0\r\n\t:") or relative.suffix != suffix):
        raise ValueError("Unsafe asset tag path: " + name)
    at = root
    if at.is_symlink():
        raise ValueError("Asset root must not be a symlink")
    for part in relative.parts:
        at /= part
        if at.is_symlink():
            raise ValueError("Asset paths must not contain symlinks: " + name)
    if not at.is_file() or at.stat().st_nlink != 1:
        raise ValueError("Expected an independent regular asset tag: " + name)
    return at


class AssetTools:
    def __init__(self, manifest: Path, logs: Path, commands: list):
        if manifest.is_symlink() or manifest.stat().st_size > 1024 * 1024:
            raise ValueError("Expected a regular asset-tool manifest smaller than 1 MiB")
        self.manifest = manifest.resolve(strict=True)
        self.manifest_hash = digest(self.manifest)
        self.logs, self.commands = logs, commands
        self.receipt = json.loads(self.manifest.read_text(encoding="utf-8"))
        pins = json.loads((ROOT / "tools/community-toolchain/pins.json").read_text())
        if (not isinstance(self.receipt, dict) or self.receipt.get("schema") != 1 or
                any(self.receipt.get(key) != pins[key] for key in ("invader_commit", "riat_commit"))):
            raise ValueError("Asset helpers require the pinned Invader and RIAT source revisions")

    def binary(self, kind):
        spec = self.receipt.get("binaries", {}).get(kind, {})
        name = spec.get("file", "")
        if not name or Path(name).name != name or name in (".", ".."):
            raise ValueError("Asset helper needs a filename inside its manifest directory")
        path = self.manifest.parent / name
        if path.is_symlink() or not path.is_file() or digest(path) != spec.get("sha256"):
            raise ValueError("Asset helper differs from its build manifest: " + kind)
        source = ROOT / "tools/map_conversion" / KINDS[kind][1]
        if digest(source) != spec.get("source_sha256"):
            raise ValueError("Asset helper source changed; rebuild the helper: " + kind)
        if digest(self.manifest) != self.manifest_hash:
            raise ValueError("Asset helper manifest changed during conversion")
        return path

    def run(self, kind, mode, root, shader_only=None):
        command = [str(self.binary(kind)), mode, str(root)]
        if shader_only is not None:
            if kind != "mips" or mode != "--audit":
                raise ValueError("Shader usage proof only applies to mip auditing")
            command += ["--shader-only", str(shader_only)]
        stage = "asset_" + kind
        log = self.logs / (f"asset-{len(self.commands) + 1:04d}-{kind}.log")
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired as error:
            raise ConversionError("tool_timeout", stage, "Asset helper exceeded 300 seconds",
                                  {"command": command}) from error
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        record = {"stage": stage, "tool": "convert-" + kind, "command": command,
                  "exit_code": result.returncode, "log": str(log),
                  "stdout": result.stdout[-16000:], "stderr": result.stderr[-16000:],
                  "output": (result.stdout + "\n" + result.stderr)[-16000:]}
        self.commands.append(record)
        if result.returncode:
            raise ConversionError("needs_profile", stage, "Asset helper rejected the selected content", record)
        if len(result.stdout.encode("utf-8")) > MAX_OUTPUT:
            raise ConversionError("invalid_asset_report", stage, "Asset helper output exceeds its bound")
        try:
            entries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        except ValueError as error:
            raise ConversionError("invalid_asset_report", stage, "Asset helper did not return valid JSON lines") from error
        if len(entries) > 20000 or any(not isinstance(entry, dict) for entry in entries):
            raise ConversionError("invalid_asset_report", stage, "Asset helper returned an invalid report")
        return entries

    def provenance(self):
        return {"manifest": str(self.manifest), "manifest_sha256": self.manifest_hash,
                "invader_commit": self.receipt["invader_commit"], "riat_commit": self.receipt["riat_commit"],
                "binaries": self.receipt["binaries"]}


def validate_measurement(kind: str, record: dict, source: dict) -> None:
    target = KINDS[kind][2]
    if (record.get("status") != "converted" or record.get("target_format") != target
            or not isinstance(record.get("source_formats"), list) or not record["source_formats"]
            or record["source_formats"] != source.get("source_formats")):
        raise ValueError("Asset report must confirm its conversion status and source/target formats")
    def integer(value, minimum=0):
        return type(value) is int and value >= minimum
    def number(value, minimum=0):
        return type(value) in (int, float) and math.isfinite(value) and value >= minimum
    if kind == "extensions":
        before, after = record.get("counts_before"), record.get("counts_after")
        if (record.get("authored_metadata_preserved") is not True
                or record.get("target_capability") != "xbox_v5_no_anniversary_hud_remaps"
                or record.get("fields") != ["anniversary_hud_remaps"]
                or not isinstance(before, dict) or set(before) != {"anniversary_hud_remaps"}
                or not integer(before["anniversary_hud_remaps"], 1)
                or after != {"anniversary_hud_remaps": 0}
                or not isinstance(record.get("reason"), str) or not record["reason"]
                or not integer(record.get("input_bytes"), 1) or not integer(record.get("output_bytes"), 1)):
            raise ValueError("Target extension omission must verify the selected field and preserved metadata")
        if source.get("counts_before") is not None and before != source["counts_before"]:
            raise ValueError("Extension omission changed the audited source field count")
    elif kind == "audio":
        meta, permutations = record.get("metadata"), record.get("permutations")
        if (record.get("authored_metadata_preserved") is not True or not isinstance(meta, dict)
                or not isinstance(permutations, list) or not integer(record.get("converted_permutations"))
                or len(permutations) != record["converted_permutations"]
                or not integer(record.get("preserved_adpcm_permutations"))
                or not integer(record.get("padding_frames_total"))
                or not integer(record.get("input_bytes"), 1) or not integer(record.get("output_bytes"), 1)
                or type(meta.get("channels")) is not int or meta["channels"] not in (1, 2)
                or type(meta.get("sample_rate")) is not int or meta["sample_rate"] not in (22050, 44100)
                or (meta["channels"] == 1 and meta["sample_rate"] != 22050)
                or meta.get("permutations") != len(permutations) + record["preserved_adpcm_permutations"]):
            raise ValueError("Audio report must verify authored metadata and complete permutation measurements")
        if source.get("metadata") is not None and source["metadata"] != meta:
            raise ValueError("Audio report changed the audited playback metadata")
        identities = set()
        for item in permutations:
            if (not isinstance(item, dict) or not integer(item.get("pitch_range"))
                    or not integer(item.get("permutation")) or not integer(item.get("frames"), 1)
                    or not integer(item.get("padding_frames")) or item["padding_frames"] > 63
                    or item.get("decoded_bits_per_sample") not in (16, 24)
                    or not number(item.get("padding_ms")) or not number(item.get("rms_error_normalized"))
                    or not number(item.get("peak_error_normalized"))
                    or type(item.get("signal_is_silent")) is not bool or type(item.get("waveform_exact")) is not bool
                    or (item.get("snr_db") is not None and not number(item["snr_db"], -10000))
                    or item.get("source_format") not in {"ogg_vorbis", "16-bit_pcm"}
                    or item.get("encoded_bytes") != ((item["frames"] + item["padding_frames"]) // 64) * 36 * meta["channels"]
                    or (item["frames"] + item["padding_frames"]) % 64):
                raise ValueError("Audio report has invalid duration, block or waveform measurements")
            identity = (item["pitch_range"], item["permutation"])
            if identity in identities:
                raise ValueError("Audio report duplicates a permutation")
            identities.add(identity)
        if sum(item["padding_frames"] for item in permutations) != record["padding_frames_total"]:
            raise ValueError("Audio padding total differs from its permutation measurements")
    elif kind == "bitmaps":
        quality, sizes, images = record.get("pixel_quality"), record.get("sizes"), record.get("images")
        if (record.get("metadata_preserved") is not True or record.get("unselected_pixels_preserved") is not True
                or not integer(record.get("images_converted"), 1) or not isinstance(images, list) or not images
                or not isinstance(quality, dict) or quality.get("comparison") != "decoded_bc7_vs_decoded_dxt5"
                or quality.get("visual_validation") != "pending" or not integer(quality.get("pixels"), 1)
                or any(not number(quality.get(key)) for key in ("rgb_rmse", "alpha_rmse", "rgb_max_error", "alpha_max_error"))
                or not isinstance(sizes, dict)
                or any(not integer(sizes.get(key), 1) for key in ("tag_before", "tag_after", "pixel_before", "pixel_after"))
                or sizes["pixel_before"] != sizes["pixel_after"]):
            raise ValueError("Bitmap report must verify preserved metadata/pixels and complete quality measurements")
    elif kind == "mips":
        images, sizes = record.get("images"), record.get("sizes")
        if (record.get("retained_mip_bytes_exact") is not True
                or record.get("metadata_preserved_except_dimensions") is not True
                or record.get("unselected_pixels_preserved") is not True
                or record.get("authored_mip_generation_setting_preserved") is not True
                or record.get("visual_validation") != "pending"
                or not integer(record.get("images_selected"), 1)
                or not isinstance(images, list) or len(images) != record["images_selected"]
                or not isinstance(sizes, dict)
                or any(not integer(sizes.get(key), 1) for key in ("tag_before", "tag_after", "pixel_before", "pixel_after"))):
            raise ValueError("Mip selection must verify exact retained bytes and bounded metadata changes")
        identities = set()
        for image in images:
            if not isinstance(image, dict):
                raise ValueError("Mip selection requires per-image dimension measurements")
            before, after, limits = image.get("before"), image.get("after"), image.get("native_limit")
            dropped = image.get("mips_removed")
            if (not integer(image.get("index")) or image["index"] in identities
                    or not integer(dropped, 1) or dropped > 16 or not integer(image.get("bytes_removed"), 1)
                    or not integer(image.get("retained_bytes"), 1)
                    or image.get("registration_point_preserved") is not True
                    or not all(isinstance(value, dict) for value in (before, after, limits))
                    or any(not integer(value.get(key), 1) for value in (before, after) for key in ("width", "height", "depth", "mips"))
                    or any(not integer(limits.get(key), 1) for key in ("width", "height", "depth"))
                    or before["mips"] - dropped != after["mips"]
                    or any(after[key] != max(1, before[key] // (2 ** dropped)) or after[key] > limits[key]
                           for key in ("width", "height", "depth"))):
                raise ValueError("Mip report has invalid level selection or resulting dimensions")
            identities.add(image["index"])
        if sizes["pixel_before"] - sizes["pixel_after"] != sum(image["bytes_removed"] for image in images):
            raise ValueError("Mip report pixel reduction differs from its selected images")
    else:
        images, sizes = record.get("images"), record.get("sizes")
        if (record.get("decoded_pixels_exact") is not True or record.get("native_gpu_pixels_exact") is not True
                or record.get("software_pixels_exact") is not True or record.get("metadata_preserved") is not True
                or record.get("unselected_pixels_preserved") is not True
                or record.get("visual_validation") != "pending"
                or not integer(record.get("images_packed"), 1)
                or not isinstance(images, list) or len(images) != record["images_packed"]
                or not isinstance(sizes, dict)
                or any(not integer(sizes.get(key), 1) for key in ("tag_before", "tag_after", "pixel_before", "pixel_after"))):
            raise ValueError("Lossless packing must verify exact decoded pixels and preserved metadata")
        identities = set()
        for image in images:
            if (not isinstance(image, dict) or not integer(image.get("index")) or image["index"] in identities
                    or image.get("decoded_pixels_exact") is not True
                    or not isinstance(image.get("source_format"), str) or not isinstance(image.get("target_format"), str)
                    or not integer(image.get("bytes_before"), 1) or not integer(image.get("bytes_after"), 1)
                    or image["bytes_after"] >= image["bytes_before"]
                    or any(not integer(image.get(key), 1) for key in ("width", "height", "depth", "faces", "mips"))):
                raise ValueError("Lossless packing report has invalid image or byte measurements")
            identities.add(image["index"])
        if sizes["pixel_before"] - sizes["pixel_after"] != sum(image["bytes_before"] - image["bytes_after"] for image in images):
            raise ValueError("Lossless packing byte reduction differs from its packed images")


def convert_assets(tool: AssetTools, kind: str, roots: list[Path], required: set[str],
                   workspace: Path, steps: list, repairs: list, shader_only: Path | None = None) -> Path | None:
    """Select by encoding and winning lookup root, never map or weapon names."""
    suffix, _, target = KINDS[kind]
    effective = {}
    candidates = {}
    for root in roots:
        inventory = {}
        for path in sorted(root.rglob("*" + suffix)):
            name = path.relative_to(root).as_posix()
            checked = checked_tag(root, name, suffix)
            inventory[name] = checked
        entries = (tool.run(kind, "--audit", root, shader_only=shader_only) if shader_only is not None
                   else tool.run(kind, "--audit", root))
        seen = set()
        for entry in entries:
            name = entry.get("tag", "")
            if name in seen or name not in inventory or entry.get("status") not in {"convertible", "unsupported"}:
                raise ConversionError("invalid_asset_report", "asset_" + kind, "Invalid or duplicate audited tag")
            seen.add(name)
            if name not in effective and name in required:
                candidates[name] = entry
        for name, path in inventory.items():
            effective.setdefault(name, path)
    selected = {name: entry for name, entry in sorted(candidates.items()) if entry["status"] == "convertible"}
    blocked = [{**entry, "stage": "asset_" + kind} for entry in candidates.values() if entry["status"] == "unsupported"]
    step = {"operation": "asset_" + kind, "target": target, "selection": "required dependencies by source format and target capability",
            "required_tags": sum(name.endswith(suffix) for name in required), "selected_tags": len(selected),
            "blockers": blocked, "status": "audited"}
    steps.append(step)
    overlay = None
    if selected:
        folder = workspace / ("asset-" + kind)
        folder.mkdir()
        for name in selected:
            for subdirectory in ("source-snapshots", "tags"):
                destination = folder / subdirectory / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(effective[name], destination)
        inputs = {name: digest(effective[name]) for name in selected}
        record = {"schema_version": 1, "operation": "asset_" + kind, "status": "pending",
                  "input_sha256": inputs, "target": target, "source_formats": selected,
                  "toolchain": tool.provenance(), "gameplay_validation": "pending"}
        manifest = folder / "conversion.json"
        _json(manifest, record)
        (folder / "asset-paths.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
        if shader_only is not None:
            shutil.copyfile(shader_only, folder / "shader-only.txt")
            record["shader_usage_proof_sha256"] = digest(shader_only)
        try:
            measurements = tool.run(kind, "--convert", folder)
            by_tag = {entry.get("tag"): entry for entry in measurements}
            if len(by_tag) != len(measurements) or set(by_tag) != set(selected):
                raise ValueError("Conversion report does not identify each selected tag exactly once")
            for name in selected:
                validate_measurement(kind, by_tag[name], selected[name])
            outputs = {}
            for name, before in inputs.items():
                if digest(effective[name]) != before or digest(folder / "source-snapshots" / name) != before:
                    raise ConversionError("input_changed", "asset_" + kind, "Asset conversion changed an original input", {"tag": name})
                outputs[name] = digest(checked_tag(folder / "tags", name, suffix))
                repairs.append({"kind": "target_capability_omission" if kind == "extensions" else "asset_codec",
                                "operation": "asset_" + kind, "tag": name,
                                "source_formats": selected[name].get("source_formats"), "target": target,
                                "sha256_before": before, "sha256_after": outputs[name], "measurements": by_tag[name]})
            record.update(status="converted", output_sha256=outputs, measurements=measurements, source_unchanged=True)
            step.update(status="converted", manifest=str(manifest), manifest_sha256=None,
                        converted_tags=len(outputs), measurements=measurements)
            overlay = folder / "tags"
        except Exception:
            record["status"] = "failed"
            _json(manifest, record)
            raise
        _json(manifest, record)
        step["manifest_sha256"] = digest(manifest)
    if blocked:
        first = blocked[0]
        raise ConversionError("needs_profile", "asset_" + kind,
                              first.get("reason", "A required asset cannot satisfy the selected conversion policy"),
                              {"tag": first["tag"], "tag_type": suffix[1:], "asset_blockers": blocked})
    return overlay


def bitmap_usage_proof(tool: AssetTools, roots: list[Path], required: set[str],
                       workspace: Path, steps: list) -> Path:
    """Prove every reachable direct bitmap consumer using the actual winning tags."""
    folder = workspace / "bitmap-usage"
    folder.mkdir()
    for root in roots:
        if any(c in str(root) for c in "\0\r\n"):
            raise ValueError("Tag root cannot contain a control character")
    before = {}
    for name in sorted(required):
        for root in roots:
            if (root / name).exists() or (root / name).is_symlink():
                before[name] = (checked_tag(root, name, Path(name).suffix), digest(root / name))
                break
        else:
            raise ConversionError("missing_dependency", "asset_bitmap_usage", "Required tag is missing", {"tag": name})
    (folder / "roots.txt").write_text("\n".join(str(root.resolve()) for root in roots) + "\n", encoding="utf-8")
    (folder / "required-tags.txt").write_text("\n".join(sorted(required)) + "\n", encoding="utf-8")
    entries = tool.run("mips", "--usage", folder)
    expected = {name for name in required if name.endswith(".bitmap")}
    by_tag = {entry.get("tag"): entry for entry in entries}
    if len(by_tag) != len(entries) or set(by_tag) != expected:
        raise ConversionError("invalid_asset_report", "asset_bitmap_usage", "Usage proof must classify every required bitmap exactly once")
    selected = []
    for name, entry in by_tag.items():
        consumers = entry.get("consumers")
        if (entry.get("status") != "classified" or type(entry.get("shader_only")) is not bool
                or not isinstance(consumers, list) or not isinstance(entry.get("metadata"), dict)
                or entry["metadata"].get("consumer_count") != len(consumers)
                or entry["metadata"].get("usage_scope") != "required_reachable_tags"):
            raise ConversionError("invalid_asset_report", "asset_bitmap_usage", "Invalid bitmap consumer proof", {"tag": name})
        for consumer in consumers:
            if (not isinstance(consumer, dict) or consumer.get("tag") not in required
                    or not isinstance(consumer.get("class"), str) or not isinstance(consumer.get("field"), str)
                    or not consumer["field"] or len(consumer["field"]) > 2048):
                raise ConversionError("invalid_asset_report", "asset_bitmap_usage", "Invalid bitmap consumer identity", {"tag": name})
        if entry["shader_only"]:
            if not consumers or any(consumer["class"] not in {"shader_model", "shader_environment"} for consumer in consumers):
                raise ConversionError("invalid_asset_report", "asset_bitmap_usage", "Unsupported shader-only classification", {"tag": name})
            selected.append(name)
    for name, (path, expected_hash) in before.items():
        if digest(path) != expected_hash:
            raise ConversionError("input_changed", "asset_bitmap_usage", "Usage proof changed a required tag", {"tag": name})
    report = folder / "usage.json"
    _json(report, {"schema_version": 1, "usage_scope": "required_reachable_tags", "classifications": entries,
                   "input_sha256": {name: value[1] for name, value in before.items()}, "source_unchanged": True})
    selected_file = folder / "shader-only.txt"
    selected_file.write_text("\n".join(sorted(selected)) + ("\n" if selected else ""), encoding="utf-8")
    steps.append({"operation": "asset_bitmap_usage", "status": "verified", "required_bitmaps": len(expected),
                  "shader_only_bitmaps": len(selected), "manifest": str(report), "manifest_sha256": digest(report),
                  "shader_only_sha256": digest(selected_file)})
    return selected_file
