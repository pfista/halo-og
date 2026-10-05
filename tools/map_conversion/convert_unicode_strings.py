#!/usr/bin/env python3
"""Replace exact reviewed UTF-16 tag entries in an independent map overlay."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

CONVERSION = "replace_reviewed_unicode_entries"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def valid_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    name = PurePosixPath(value)
    return (bool(value) and not name.is_absolute() and str(name) == value and
            name.suffix == ".unicode_string_list" and not any(p in (".", "..") for p in name.parts)
            and not any(c in value for c in "\t\r\n\\"))


def checked_path(root: Path, relative: str) -> Path:
    if not valid_name(relative):
        raise ValueError("Unsafe Unicode tag path")
    at = root
    if at.is_symlink():
        raise ValueError("Symlink source root")
    for part in PurePosixPath(relative).parts:
        at /= part
        if at.is_symlink():
            raise ValueError("Symlink Unicode input")
    if not at.is_file() or at.stat().st_nlink != 1:
        raise ValueError("Missing or hard-linked Unicode input")
    return at


def utf16(value: object) -> bytes:
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("Expected text without interior nulls")
    try:
        data = (value + "\0").encode("utf-16-le")
    except UnicodeEncodeError as error:
        raise ValueError("Invalid Unicode surrogate in reviewed text") from error
    if len(data) > 32768:
        raise ValueError("Reviewed UTF-16 entry exceeds tag limit")
    return data


def validate_profile(profile: object) -> None:
    if (not isinstance(profile, dict) or profile.get("schema_version") != 1 or profile.get("target_engine") != "xbox"
            or profile.get("write_policy") != "fresh_overlay" or profile.get("conversion") != CONVERSION
            or profile.get("encoding") != "utf-16-le"):
        raise ValueError("Unsupported reviewed Unicode conversion profile")
    if not isinstance(profile.get("origin"), str) or not profile["origin"].strip():
        raise ValueError("Record Unicode compatibility provenance")
    if not valid_hash(profile.get("converter_source_sha256")):
        raise ValueError("Invalid reviewed converter source hash")
    tags, actions = profile.get("tags"), profile.get("actions")
    if not isinstance(tags, dict) or not tags or not isinstance(actions, list) or not actions:
        raise ValueError("Expected reviewed Unicode tags and entry actions")
    for name, rule in tags.items():
        if (not valid_name(name) or not isinstance(rule, dict) or set(rule) != {"sha256", "expected_string_count"}
                or not valid_hash(rule["sha256"]) or type(rule["expected_string_count"]) is not int
                or not 1 <= rule["expected_string_count"] <= 800):
            raise ValueError("Invalid reviewed Unicode tag hash or entry count")
    seen = set()
    for action in actions:
        if (not isinstance(action, dict) or set(action) != {"tag", "index", "before", "after", "reason"}
                or not isinstance(action["tag"], str) or action["tag"] not in tags
                or type(action["index"]) is not int or not 0 <= action["index"] < tags[action["tag"]]["expected_string_count"]
                or not isinstance(action["reason"], str) or not action["reason"].strip()
                or (action["tag"], action["index"]) in seen):
            raise ValueError("Invalid, duplicate or out-of-range Unicode entry action")
        if utf16(action["before"]) == utf16(action["after"]):
            raise ValueError("Unicode entry action must change the reviewed text")
        seen.add((action["tag"], action["index"]))
    if {name for name, _ in seen} != set(tags):
        raise ValueError("Every selected Unicode tag needs a reviewed entry action")


def action_tsv(profile: dict) -> str:
    return "".join(f"{a['tag']}\t{profile['tags'][a['tag']]['expected_string_count']}\t{a['index']}\t"
                   f"{utf16(a['before']).hex()}\t{utf16(a['after']).hex()}\n" for a in profile["actions"])


def inventory(root: Path) -> dict:
    values = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in Unicode output tree")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError("Hard-linked Unicode output")
            values[path.relative_to(root).as_posix()] = sha256(path)
    return values


def convert(source: Path, profile_path: Path, helper: Path, helper_sha256: str, output: Path) -> dict:
    profile = json.loads(profile_path.read_text())
    validate_profile(profile)
    converter_source = Path(__file__).with_suffix(".cpp")
    if sha256(converter_source) != profile["converter_source_sha256"]:
        raise ValueError("Unicode converter source differs from reviewed profile")
    if (not valid_hash(helper_sha256) or not helper.is_file() or helper.is_symlink()
            or helper.stat().st_nlink != 1 or sha256(helper) != helper_sha256):
        raise ValueError("Unicode helper hash mismatch or unsafe helper")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be new")
    sources = {}
    for name, rule in profile["tags"].items():
        path = checked_path(source, name)
        if sha256(path) != rule["sha256"]:
            raise ValueError("Unicode source differs from reviewed hash")
        sources[name] = path
    output.mkdir(parents=True)
    inputs = {name: rule["sha256"] for name, rule in profile["tags"].items()}
    record = dict(schema_version=1, conversion=CONVERSION, status="pending", origin=profile["origin"],
                  encoding=profile["encoding"], tags=profile["tags"], actions=profile["actions"],
                  source_root=str(source.resolve()), profile_path=str(profile_path.resolve()), profile_sha256=sha256(profile_path),
                  converter=str(helper.resolve()), converter_sha256=helper_sha256,
                  converter_source_sha256=profile["converter_source_sha256"], input_sha256=inputs,
                  preservation="Exact selected UTF-16 entries only; every unselected entry and field is reparsed and compared",
                  runtime_acceptance="pending separate native presentation and multiplayer checks", engine_rules_changed=False)
    record_path = output / "conversion.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    for name, path in sources.items():
        snapshot = output / "source-snapshots" / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, snapshot)
    (output / "converter-source.cpp").write_bytes(converter_source.read_bytes())
    (output / "reviewed-profile.json").write_bytes(profile_path.read_bytes())
    (output / "unicode-strings.tsv").write_text(action_tsv(profile))
    command = [str(helper.resolve()), str(output.resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / "convert.log").write_text(result.stdout + result.stderr)
    outputs = inventory(output / "tags")
    source_unchanged = all(sha256(path) == inputs[name] for name, path in sources.items())
    snapshots_unchanged = inventory(output / "source-snapshots") == inputs
    source_snapshot_unchanged = sha256(output / "converter-source.cpp") == profile["converter_source_sha256"]
    profile_unchanged = sha256(output / "reviewed-profile.json") == record["profile_sha256"]
    valid_output = set(outputs) == set(inputs)
    record.update(command=command, returncode=result.returncode, output_sha256=outputs,
                  source_unchanged=source_unchanged, snapshots_unchanged=snapshots_unchanged,
                  converter_source_snapshot_unchanged=source_snapshot_unchanged,
                  profile_snapshot_unchanged=profile_unchanged,
                  untouched_entries_verified=result.returncode == 0,
                  output_reparse_verified=result.returncode == 0)
    record["status"] = "converted" if (result.returncode == 0 and source_unchanged and snapshots_unchanged
        and source_snapshot_unchanged and profile_unchanged and valid_output) else "failed"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "converted":
        raise RuntimeError("Unicode conversion failed; inspect " + str(output / "convert.log"))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tags", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--converter-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        convert(args.source_tags, args.profile, args.converter, args.converter_sha256, args.output)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print("Converted reviewed Unicode entries; native runtime acceptance pending")


if __name__ == "__main__":
    main()
