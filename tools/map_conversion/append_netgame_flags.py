#!/usr/bin/env python3
"""Append individually reviewed source markers to a fresh multiplayer overlay."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

CONVERSION = "append_reviewed_netgame_flags"
TYPES = {"ctf_flag": 0, "oddball_ball_spawn": 2, "race_track": 3,
         "teleport_from": 6, "teleport_to": 7}
MAX_FLAGS = 200


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def checked_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise ValueError("Scenario tag path must be a string")
    part = PurePosixPath(relative)
    if (not relative or part.is_absolute() or str(part) != relative or part.suffix != ".scenario"
            or any(p in (".", "..") for p in part.parts) or any(c in relative for c in "\t\r\n\\")):
        raise ValueError("Unsafe scenario tag path")
    at = root
    if at.is_symlink():
        raise ValueError("Symlink source root")
    for component in part.parts:
        at /= component
        if at.is_symlink():
            raise ValueError("Symlink scenario input")
    if not at.is_file() or at.stat().st_nlink != 1:
        raise ValueError("Missing or hard-linked scenario input")
    return at


def count(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_FLAGS


def validate_profile(profile: object) -> None:
    if (not isinstance(profile, dict) or profile.get("schema_version") != 1 or profile.get("target_engine") != "xbox"
            or profile.get("write_policy") != "fresh_overlay" or profile.get("conversion") != CONVERSION):
        raise ValueError("Unsupported multiplayer marker conversion profile")
    selected, source_rule, target_rule = profile.get("selection"), profile.get("source"), profile.get("target")
    if (not isinstance(source_rule, dict) or set(source_rule) != {"tag", "sha256", "expected_selected_type_count"}
            or not isinstance(target_rule, dict) or set(target_rule) != {"tag", "sha256", "expected_flag_count", "expected_selected_type_count"}
            or not isinstance(selected, dict) or set(selected) != {"type", "usage_ids"}):
        raise ValueError("Expected explicit source, target and marker selection")
    if not isinstance(profile.get("origin"), str) or not profile["origin"].strip():
        raise ValueError("Record source and compatibility provenance")
    if not isinstance(selected["type"], str) or selected["type"] not in TYPES:
        raise ValueError("Unsupported marker type; polygon and vehicle semantics require separate review")
    ids = selected["usage_ids"]
    limit = 31 if selected["type"] == "race_track" else (1 if selected["type"] == "ctf_flag" else 65534)
    if (not isinstance(ids, list) or not ids or any(type(i) is not int or i < 0 or i > limit for i in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Expected distinct native-range marker usage IDs")
    if (not count(source_rule["expected_selected_type_count"]) or
            not count(target_rule["expected_selected_type_count"]) or
            not count(target_rule["expected_flag_count"]) or
            target_rule["expected_selected_type_count"] > target_rule["expected_flag_count"] or
            source_rule["expected_selected_type_count"] < len(ids) or
            target_rule["expected_flag_count"] + len(ids) > MAX_FLAGS):
        raise ValueError("Invalid counts or native netgame flag limit exceeded")
    for rule in (source_rule, target_rule):
        name = rule["tag"]
        if (not isinstance(name, str) or not name or PurePosixPath(name).is_absolute()
                or str(PurePosixPath(name)) != name or PurePosixPath(name).suffix != ".scenario"
                or any(part in (".", "..") for part in PurePosixPath(name).parts)
                or any(c in name for c in "\t\r\n\\") or not valid_hash(rule["sha256"])):
            raise ValueError("Invalid reviewed scenario path or hash")
    if not valid_hash(profile.get("converter_source_sha256")):
        raise ValueError("Invalid reviewed converter source hash")


def action_tsv(profile: dict) -> str:
    source, target, selected = profile["source"], profile["target"], profile["selection"]
    return (f"{source['tag']}\t{target['tag']}\t{TYPES[selected['type']]}\t"
            f"{source['expected_selected_type_count']}\t{target['expected_flag_count']}\t"
            f"{target['expected_selected_type_count']}\n" + "".join(f"{i}\n" for i in selected["usage_ids"]))


def convert(source: Path, target: Path, profile_path: Path, helper: Path,
            helper_sha256: str, output: Path) -> dict:
    profile = json.loads(profile_path.read_text())
    validate_profile(profile)
    selected, source_rule, target_rule = profile["selection"], profile["source"], profile["target"]
    converter_source = Path(__file__).with_suffix(".cpp")
    if not valid_hash(profile.get("converter_source_sha256")) or sha256(converter_source) != profile["converter_source_sha256"]:
        raise ValueError("Converter source differs from reviewed profile")
    if (not valid_hash(helper_sha256) or not helper.is_file() or helper.is_symlink()
            or helper.stat().st_nlink != 1 or sha256(helper) != helper_sha256):
        raise ValueError("Marker helper hash mismatch or unsafe helper")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be new")
    sources = {}
    for label, root, rule in (("source", source, source_rule), ("target", target, target_rule)):
        path = checked_path(root, rule["tag"])
        if not valid_hash(rule["sha256"]) or sha256(path) != rule["sha256"]:
            raise ValueError("Scenario differs from reviewed " + label + " hash")
        sources[label] = path
    output.mkdir(parents=True)
    record = {
        "schema_version": 1, "conversion": CONVERSION, "status": "pending", "origin": profile["origin"],
        "source_root": str(source.resolve()), "target_root": str(target.resolve()),
        "profile_path": str(profile_path.resolve()), "profile_sha256": sha256(profile_path),
        "converter": str(helper.resolve()), "converter_sha256": helper_sha256,
        "converter_source_sha256": profile["converter_source_sha256"],
        "input_sha256": {label: {rule["tag"]: rule["sha256"]} for label, rule in (("source", source_rule), ("target", target_rule))},
        "source": source_rule, "target": target_rule, "selection": selected,
        "preservation": "Append exact selected source marker structs; every original target field stays unchanged",
        "runtime_acceptance": "pending separate native gameplay and multiplayer checks",
        "engine_rules_changed": False,
    }
    record_path = output / "conversion.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    for label, rule in (("source", source_rule), ("target", target_rule)):
        snapshot = output / "source-snapshots" / label / rule["tag"]
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sources[label], snapshot)
    (output / "converter-source.cpp").write_bytes(converter_source.read_bytes())
    (output / "reviewed-profile.json").write_bytes(profile_path.read_bytes())
    (output / "netgame-flags.tsv").write_text(action_tsv(profile))
    command = [str(helper.resolve()), str(output.resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / "convert.log").write_text(result.stdout + result.stderr)
    destination = output / "tags" / target_rule["tag"]
    unchanged = all(sha256(sources[label]) == rule["sha256"] for label, rule in (("source", source_rule), ("target", target_rule)))
    snapshots = all(sha256(output / "source-snapshots" / label / rule["tag"]) == rule["sha256"]
                    for label, rule in (("source", source_rule), ("target", target_rule)))
    valid_output = destination.is_file() and not destination.is_symlink() and destination.stat().st_nlink == 1
    outputs = {target_rule["tag"]: sha256(destination)} if valid_output else {}
    record.update(command=command, returncode=result.returncode, source_unchanged=unchanged,
                  snapshots_unchanged=snapshots, output_sha256=outputs,
                  converter_source_snapshot_unchanged=sha256(output / "converter-source.cpp") == profile["converter_source_sha256"],
                  profile_snapshot_unchanged=sha256(output / "reviewed-profile.json") == record["profile_sha256"])
    record["status"] = "converted" if (result.returncode == 0 and unchanged and snapshots and valid_output
        and record["converter_source_snapshot_unchanged"] and record["profile_snapshot_unchanged"]) else "failed"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "converted":
        raise RuntimeError("Marker conversion failed; inspect " + str(output / "convert.log"))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tags", type=Path, required=True)
    parser.add_argument("--target-tags", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--converter-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        convert(args.source_tags, args.target_tags, args.profile, args.converter, args.converter_sha256, args.output)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print("Converted reviewed netgame markers; native runtime acceptance pending")


if __name__ == "__main__":
    main()
