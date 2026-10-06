#!/usr/bin/env python3
"""Convert proven duplicate Chicago shader layers in a fresh community overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess


CONVERSION = "remove_proven_duplicate_chicago_extra_layer"
SHADER = ".shader_transparent_chicago"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    part = PurePosixPath(relative)
    if (not relative or part.is_absolute() or str(part) != relative
            or any(p in (".", "..") for p in part.parts)
            or any(c in relative for c in "\t\r\n\\")
            or part.suffix not in (SHADER, ".bitmap")):
        raise ValueError(f"Unsafe shader dependency path: {relative}")
    at = root
    if at.is_symlink():
        raise ValueError("Symlink source root")
    for component in part.parts:
        at /= component
        if at.is_symlink():
            raise ValueError(f"Symlink source dependency: {relative}")
    if not at.is_file() or at.stat().st_nlink != 1:
        raise ValueError(f"Missing or hard-linked source dependency: {relative}")
    return at


def convert(source: Path, profile_path: Path, helper: Path,
            helper_sha256: str, output: Path) -> dict:
    profile = json.loads(profile_path.read_text())
    if (profile.get("schema_version") != 1 or profile.get("target_engine") != "xbox"
            or profile.get("write_policy") != "fresh_overlay"
            or profile.get("conversion") != CONVERSION):
        raise ValueError("Unsupported shader conversion profile")
    tags, actions = profile.get("tags"), profile.get("actions")
    if not isinstance(tags, dict) or not tags or not isinstance(actions, list) or not actions:
        raise ValueError("Profile must name reviewed dependencies and explicit actions")
    parents = []
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"parent", "duplicate_layer"}:
            raise ValueError("Unsupported shader action")
        parent, child = action["parent"], action["duplicate_layer"]
        if (not isinstance(parent, str) or not isinstance(child, str)
                or not parent.endswith(SHADER) or not child.endswith(SHADER)
                or parent == child or parent not in tags or child not in tags or parent in parents):
            raise ValueError("Invalid or duplicate reviewed shader action")
        parents.append(parent)
    if not helper.is_file() or helper.is_symlink() or sha256(helper) != helper_sha256:
        raise ValueError("Shader helper hash mismatch")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be new")
    sources = {}
    for name, expected in tags.items():
        if (not isinstance(expected, str) or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)):
            raise ValueError(f"Invalid expected SHA256: {name}")
        path = checked_path(source, name)
        if sha256(path) != expected:
            raise ValueError(f"Changed source dependency: {name}")
        sources[name] = path
    output.mkdir(parents=True)
    record = {
        "schema_version": 1, "status": "pending", "conversion": CONVERSION,
        "origin": profile.get("origin", "imported community shader; authorship unverified"),
        "source_root": str(source.resolve()), "profile_path": str(profile_path.resolve()),
        "profile_sha256": sha256(profile_path), "converter": str(helper.resolve()),
        "converter_sha256": helper_sha256, "input_sha256": tags, "actions": actions,
        "preservation": "Only the proven duplicate extra layer is removed; all primary shader parameters and art stay unchanged",
        "appearance_limit": "Removing a repeated blend pass can change grayscale brightness; requires in-game visual review",
        "runtime_bug_source": profile.get("runtime_bug_source"),
        "runtime_acceptance": "pending separate in-game validation",
    }
    record_path = output / "conversion.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    for name, source_file in sources.items():
        snapshot = output / "source-snapshots" / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, snapshot)
        if name in parents:
            destination = output / "tags" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, destination)
    (output / "shader-actions.tsv").write_text("".join(
        f"{action['parent']}\t{action['duplicate_layer']}\n" for action in actions))
    command = [str(helper.resolve()), str(output.resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / "convert.log").write_text(result.stdout + result.stderr)
    record.update(command=command, returncode=result.returncode,
                  source_unchanged=all(sha256(sources[name]) == expected for name, expected in tags.items()),
                  snapshots_unchanged=all(sha256(output / "source-snapshots" / name) == expected
                                          for name, expected in tags.items()),
                  output_sha256={name: sha256(output / "tags" / name) for name in parents})
    record["status"] = ("converted" if result.returncode == 0 and record["source_unchanged"]
                        and record["snapshots_unchanged"] else "failed")
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "converted":
        raise RuntimeError(f"Shader conversion failed; inspect {output / 'convert.log'}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tags", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--converter-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = convert(args.source_tags, args.profile, args.converter, args.converter_sha256, args.output)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Converted {len(record['output_sha256'])} shader tags; visual/runtime validation pending")


if __name__ == "__main__":
    main()
