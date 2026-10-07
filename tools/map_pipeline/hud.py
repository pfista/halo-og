"""Checked, source-bound presentation overlays for MCC HUD dependencies."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil

from .assets import checked_tag
from .backend import ConversionError
from ..community_maps import digest

HUD_TYPES = {".unit_hud_interface", ".weapon_hud_interface", ".grenade_hud_interface",
             ".hud_globals", ".hud_number"}
ALLOWED_FIELDS = {"width_scale", "height_scale", "anchor_offset", "flags",
                  "digit_width", "bitmap_digit_width", "screen_digit_width", "x_offset", "y_offset", "scaling_flags",
                  "decimal_point_width", "colon_width", "offset_from_reference_corner"}
GLOBALS_DISPLAY_FIELDS = {"hud_damage_top_offset", "hud_damage_bottom_offset", "hud_damage_left_offset", "hud_damage_right_offset",
                          "top_offset", "bottom_offset", "left_offset", "right_offset", "width_offset", "motion_sensor_scale", "default_chapter_title_bounds"}
FIELD = re.compile(r"[a-z_]+(?:\[[0-9]+\])?(?:\.[a-z_]+(?:\[[0-9]+\])?)*\Z")
FIXED_BITMAP_FIELDS = {("hud_number", "digits_bitmap"), ("hud_globals", "icon_bitmap"),
                       ("hud_globals", "hud_damage_indicator_bitmap"), ("hud_globals", "arrow_bitmap")}


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def validate_plan(entry, required):
    """Reject unsafe paths, out-of-scope edits and incomplete helper evidence."""
    name = entry.get("tag")
    if (name not in required or Path(name).suffix not in HUD_TYPES | {".bitmap"}
            or entry.get("status") not in {"requires_conversion", "needs_profile", "unchanged"}
            or entry.get("source_formats") != ["mcc_hud_density"]
            or entry.get("target_format") != "native_xbox_hud"):
        raise ValueError("HUD audit must identify a reachable presentation tag and target")
    rules = entry.get("field_rules")
    if not isinstance(rules, list) or len(rules) > 10000:
        raise ValueError("HUD audit needs bounded numeric field rules")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("HUD field rule must be an object")
        field = rule.get("field")
        leaf = field.rsplit(".", 1)[-1] if isinstance(field, str) else ""
        if (not isinstance(field, str) or len(field) > 2048 or not FIELD.fullmatch(field)
                or (leaf not in ALLOWED_FIELDS and not (Path(name).suffix == ".hud_globals" and leaf in GLOBALS_DISPLAY_FIELDS)
                    and not leaf.endswith(("_width_scale", "_height_scale", "_anchor_offset", "_scaling_flags"))
                    and not field.endswith("flags.use_high_res_scale")) or field in seen
                or Path(name).suffix == ".bitmap"):
            raise ValueError("HUD rule may only alter numeric display fields")
        seen.add(field)
        before, after = rule.get("before"), rule.get("after")
        if (not isinstance(before, list) or not 1 <= len(before) <= 4 or not isinstance(after, list)
                or len(before) != len(after)
                or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 2**31
                       for v in [*before, *after])
                or not isinstance(rule.get("reason"), str) or not rule["reason"]):
            raise ValueError("HUD rule needs finite before/after values and a reason")
        if (leaf in {"flags", "scaling_flags"} or leaf.endswith("_scaling_flags")) and (
                len(before) != 1 or int(before[0]) != before[0] or int(after[0]) != after[0]
                or int(after[0]) != (int(before[0]) & ~4)):
            raise ValueError("HUD flags may only clear the unsupported high-resolution placement bit")
    divisor = entry.get("bitmap_divisor")
    if divisor is not None and (type(divisor) is not int or divisor not in (2, 4)
                                or Path(name).suffix != ".bitmap"):
        raise ValueError("HUD bitmap resize must select a proved 2x or 4x image")
    evidence = entry.get("evidence")
    if (not isinstance(evidence, dict) or evidence.get("visual_validation") != "pending"
            or not isinstance(evidence.get("density_proofs"), list)):
        raise ValueError("HUD audit must record its density evidence and pending visual check")
    if entry["status"] == "requires_conversion" and not rules and divisor is None:
        raise ValueError("Selected HUD tag has no conversion decision")


def _numbers(value):
    return [float(item.strip()) for item in value.split(",")]


def _verify_fields(tool, root, name, rules, key):
    for rule in rules:
        expected = rule[key]
        leaf = rule["field"].rsplit(".", 1)[-1]
        if leaf in {"flags", "scaling_flags"} or leaf.endswith("_scaling_flags"):
            # Invader edit exposes named bits, rather than a bitfield integer.
            # The source-bound helper independently compares every other bit.
            actual = _numbers(tool.get(root, name, rule["field"] + ".use_high_res_scale"))
            expected = [int(expected[0]) >> 2 & 1]
        else:
            actual = _numbers(tool.get(root, name, rule["field"]))
        if len(actual) != len(expected) or any(not math.isfinite(a) or not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5)
                                              for a, b in zip(actual, expected)):
            raise ValueError("HUD field differs from its audited " + key + " value: " + name + " " + rule["field"])


def normalize_mcc_hud(asset_tools, tool, roots, stock, required, workspace, steps, repairs, protected, native_tags=frozenset()):
    index = workspace / "hud-index"
    index.mkdir()
    for root in [*roots, stock]:
        if any(c in str(root) for c in "\0\r\n"):
            raise ValueError("HUD root contains a control character")
    (index / "roots.txt").write_text("\n".join(str(root.resolve()) for root in roots) + "\n", encoding="utf-8")
    (index / "stock-root.txt").write_text(str(stock.resolve()) + "\n", encoding="utf-8")
    (index / "required-tags.txt").write_text("\n".join(sorted(required)) + "\n", encoding="utf-8")
    native = sorted(set(native_tags) & set(required))
    if any(Path(name).suffix not in HUD_TYPES for name in native):
        raise ValueError("Native HUD reuse markers must identify only verified HUD tags")
    (index / "native-hud-tags.txt").write_text("\n".join(native) + ("\n" if native else ""), encoding="utf-8")
    effective = {}
    before = {}
    for name in sorted(required):
        suffix = Path(name).suffix
        if suffix not in HUD_TYPES | {".bitmap"}:
            continue
        for root in roots:
            if (root / name).exists() or (root / name).is_symlink():
                path = checked_tag(root, name, suffix)
                effective[name] = (root, path)
                before[name] = digest(path)
                break
        else:
            raise ConversionError("missing_dependency", "presentation_hud", "Required presentation tag is missing", {"tag": name})
    for path in index.iterdir():
        protected[path] = digest(path)
    entries = asset_tools.run("hud", "--audit", index)
    plans = {}
    for entry in entries:
        validate_plan(entry, required)
        name = entry["tag"]
        if name in plans:
            raise ValueError("HUD audit repeats a tag: " + name)
        plans[name] = entry
    for name, expected in before.items():
        if digest(effective[name][1]) != expected:
            raise ConversionError("input_changed", "presentation_hud", "HUD audit changed a source tag", {"tag": name})
    audit = index / "audit.json"
    _write_json(audit, {"schema_version": 1, "plans": entries, "input_sha256": before, "source_unchanged": True})
    protected[audit] = digest(audit)
    blocked = [entry for entry in entries if entry["status"] == "needs_profile"]
    selected = {name: entry for name, entry in plans.items() if entry["status"] == "requires_conversion"}
    step = {"operation": "presentation_hud", "policy": "native-xbox", "source_cache_version": 13,
            "selection": "reachable HUD tags and matched Xbox sprite geometry", "selected_tags": len(selected),
            "blockers": blocked, "audit": str(audit), "audit_sha256": digest(audit), "status": "audited",
            "warnings": [warning for entry in entries for warning in entry.get("warnings", [])]}
    steps.append(step)
    if blocked:
        raise ConversionError("needs_profile", "presentation_hud", blocked[0].get("reason", "HUD layout needs an explicit conversion decision"),
                              {"tag": blocked[0]["tag"], "hud_blockers": blocked})
    if not selected:
        step["status"] = "unchanged"
        return None
    physical = {name for name, entry in selected.items() if "bitmap_divisor" in entry}
    if physical:
        # A physical resize also changes every direct user of this image. Prove
        # its complete reachable consumer set before altering any copied tag.
        usage = asset_tools.run("mips", "--usage", index)
        classifications = {entry.get("tag"): entry for entry in usage}
        if len(classifications) != len(usage) or set(classifications) != {name for name in required if name.endswith(".bitmap")}:
            raise ValueError("HUD bitmap consumer proof must classify each required bitmap exactly once")
        for name in physical:
            entry = classifications[name]
            consumers = entry.get("consumers")
            if (entry.get("status") != "classified" or not isinstance(consumers, list) or not consumers
                    or any(not isinstance(consumer, dict) or consumer.get("tag") not in required
                           or (consumer.get("class"), consumer.get("field")) not in FIXED_BITMAP_FIELDS for consumer in consumers)):
                raise ConversionError("needs_profile", "presentation_hud", "HUD image is shared with an unsupported reachable consumer",
                                      {"tag": name, "consumers": consumers,
                                       "reason": "Physical HUD resize requires only audited fixed-size native HUD draw fields"})
        proof = index / "bitmap-consumers.json"
        _write_json(proof, {"schema_version": 1, "classifications": usage, "physical_hud_bitmaps": sorted(physical)})
        protected[proof] = digest(proof)
        step.update(bitmap_consumers=str(proof), bitmap_consumers_sha256=digest(proof))
    folder = workspace / "native-hud"
    folder.mkdir()
    fields, bitmaps = [], []
    for name, entry in selected.items():
        root, path = effective[name]
        _verify_fields(tool, root, name, entry["field_rules"], "before")
        for child in ("source-snapshots", "tags"):
            destination = folder / child / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        for rule in entry["field_rules"]:
            values = [",".join(format(v, ".9g") for v in rule[key]) for key in ("before", "after")]
            fields.append("\t".join([name, rule["field"], *values]))
        if "bitmap_divisor" in entry:
            bitmaps.append(name + "\t" + str(entry["bitmap_divisor"]))
    for filename, lines in (("field-rules.tsv", fields), ("bitmap-rules.tsv", bitmaps)):
        path = folder / filename
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        protected[path] = digest(path)
    manifest = folder / "conversion.json"
    record = {"schema_version": 1, "operation": "presentation_hud", "status": "pending", "plans": list(selected.values()),
              "toolchain": asset_tools.provenance(), "gameplay_validation": "pending"}
    _write_json(manifest, record)
    try:
        measurements = asset_tools.run("hud", "--convert", folder)
        by_tag = {entry.get("tag"): entry for entry in measurements}
        if len(by_tag) != len(measurements) or set(by_tag) != set(selected):
            raise ValueError("HUD conversion must measure each selected tag exactly once")
        if not (folder / "conversion.completed").is_file():
            raise ValueError("HUD helper did not confirm completion")
        outputs = {}
        for name, entry in selected.items():
            measured = by_tag[name]
            if (measured.get("status") != "converted" or measured.get("target_format") != "native_xbox_hud"
                    or measured.get("source_formats") != ["mcc_hud_density"]
                    or measured.get("authored_metadata_preserved") is not True
                    or measured.get("source_snapshots_preserved") is not True
                    or measured.get("visual_validation") != "pending"
                    or measured.get("bitmap_divisor") != entry.get("bitmap_divisor")
                    or measured.get("input_bytes") != effective[name][1].stat().st_size
                    or measured.get("output_bytes") != (folder / "tags" / name).stat().st_size):
                raise ValueError("HUD conversion did not verify its permitted changes: " + name)
            if "bitmap_divisor" in entry and (measured.get("sequence_metadata_preserved") is not True
                    or measured.get("filter") != "alpha_weighted_box" or measured.get("pixel_resampling_lossy") is not True):
                raise ValueError("HUD bitmap conversion must verify sequence preservation and its resampling filter")
            if digest(effective[name][1]) != before[name] or digest(folder / "source-snapshots" / name) != before[name]:
                raise ConversionError("input_changed", "presentation_hud", "HUD conversion changed an original source", {"tag": name})
            checked = checked_tag(folder / "tags", name, Path(name).suffix)
            _verify_fields(tool, folder / "tags", name, entry["field_rules"], "after")
            outputs[name] = digest(checked)
            repairs.append({"kind": "native_presentation", "operation": "presentation_hud", "tag": name,
                            "sha256_before": before[name], "sha256_after": outputs[name], "decision": entry})
        record.update(status="converted", output_sha256=outputs, measurements=measurements, source_unchanged=True)
        step.update(status="converted", converted_tags=len(outputs), measurements=measurements)
    except Exception:
        record["status"] = "failed"
        _write_json(manifest, record)
        raise
    _write_json(manifest, record)
    protected[manifest] = digest(manifest)
    step.update(manifest=str(manifest), manifest_sha256=digest(manifest))
    return folder / "tags"
