#!/usr/bin/env python3
"""Guarded, explicit community PCM sound conversion into a fresh overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    part = PurePosixPath(relative)
    if (not relative or part.is_absolute() or str(part) != relative
            or any(p in (".", "..") for p in part.parts)
            or any(c in relative for c in "\t\r\n\\") or part.suffix != ".sound"):
        raise ValueError(f"Unsafe sound path: {relative}")
    at = root
    if at.is_symlink():
        raise ValueError(f"Symlink source root: {root}")
    for component in part.parts:
        at /= component
        if at.is_symlink():
            raise ValueError(f"Symlink source path: {relative}")
    if not at.is_file():
        raise ValueError(f"Missing source sound: {relative}")
    return at


def convert(source: Path, profile_path: Path, converter: Path,
            converter_sha256: str, output: Path) -> dict:
    profile = json.loads(profile_path.read_text())
    if (profile.get("schema_version") != 1 or profile.get("target_engine") != "xbox"
            or profile.get("write_policy") != "fresh_overlay"
            or profile.get("conversion") != "16_bit_pcm_to_xbox_adpcm"):
        raise ValueError("Unsupported sound conversion profile")
    tags = profile.get("tags")
    if not isinstance(tags, dict) or not tags:
        raise ValueError("Profile must name reviewed source hashes")
    if not converter.is_file() or converter.is_symlink() or sha256(converter) != converter_sha256:
        raise ValueError("Converter hash mismatch")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be new")
    # Verify every source expectation before creating files or executing code.
    paths = {}
    for relative, expected in tags.items():
        if (not isinstance(expected, str) or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)):
            raise ValueError(f"Invalid expected SHA256: {relative}")
        path = checked_path(source, relative)
        if sha256(path) != expected:
            raise ValueError(f"Changed source sound: {relative}")
        paths[relative] = path
    output.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "status": "pending",
        "conversion": profile["conversion"],
        "origin": profile.get("origin", "imported community asset; historical authorship unverified"),
        "source_root": str(source.resolve()),
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": sha256(profile_path),
        "converter": str(converter.resolve()),
        "converter_sha256": converter_sha256,
        "input_sha256": tags,
        "preservation": "No resampling, gain normalization, pitch or event-reference edits; ADPCM is lossy",
        "runtime_acceptance": "pending separate in-game validation",
    }
    record_path = output / "conversion.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    for relative, source_file in paths.items():
        for folder in ("source-snapshots", "tags"):
            destination = output / folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, destination)
    (output / "sound-paths.txt").write_text("\n".join(paths) + "\n")
    command = [str(converter.resolve()), str(output.resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / "convert.log").write_text(result.stdout + result.stderr)
    record["command"] = command
    record["returncode"] = result.returncode
    unchanged = all(sha256(paths[name]) == expected for name, expected in tags.items())
    record["source_unchanged"] = unchanged
    record["output_sha256"] = {
        name: sha256(output / "tags" / name) for name in paths
    }
    record["status"] = "converted" if result.returncode == 0 and unchanged else "failed"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "converted":
        raise RuntimeError(f"Sound conversion failed; inspect {output / 'convert.log'}")
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
        record = convert(args.source_tags, args.profile, args.converter,
                         args.converter_sha256, args.output)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Converted {len(record['output_sha256'])} sound tags; runtime validation pending")


if __name__ == "__main__":
    main()
