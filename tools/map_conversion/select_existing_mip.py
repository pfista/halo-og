#!/usr/bin/env python3
"""Select a reviewed existing lower bitmap mip in a fresh community overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

CONVERSION = "select_existing_lower_bitmap_mip"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(root: Path, name: str) -> Path:
    if not isinstance(name, str):
        raise ValueError("Bitmap path must be text")
    part = PurePosixPath(name)
    if (not name or part.is_absolute() or str(part) != name
            or any(p in (".", "..") for p in part.parts)
            or any(c in name for c in "\t\r\n\\") or part.suffix != ".bitmap"):
        raise ValueError(f"Unsafe bitmap path: {name}")
    at = root
    if at.is_symlink():
        raise ValueError("Symlink source root")
    for component in part.parts:
        at /= component
        if at.is_symlink():
            raise ValueError(f"Symlink source bitmap: {name}")
    if not at.is_file() or at.stat().st_nlink != 1:
        raise ValueError(f"Missing or hard-linked source bitmap: {name}")
    return at


def convert(source: Path, profile_path: Path, helper: Path,
            helper_sha256: str, output: Path) -> dict:
    profile = json.loads(profile_path.read_text())
    if (profile.get("schema_version") != 1 or profile.get("target_engine") != "xbox"
            or profile.get("write_policy") != "fresh_overlay"
            or profile.get("conversion") != CONVERSION):
        raise ValueError("Unsupported authored mip selection profile")
    tags, actions = profile.get("tags"), profile.get("actions")
    if not isinstance(tags, dict) or not tags or not isinstance(actions, list) or not actions:
        raise ValueError("Profile must pin reviewed bitmap inputs and explicit actions")
    selected = []
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"tag", "bitmap_index", "drop_top_mips"}:
            raise ValueError("Unsupported authored mip action")
        name = action["tag"]
        if (not isinstance(name, str) or name not in tags or name in selected
                or type(action["bitmap_index"]) is not int or action["bitmap_index"] != 0
                or type(action["drop_top_mips"]) is not int or action["drop_top_mips"] != 1):
            raise ValueError("Only one reviewed top mip of bitmap index zero is supported")
        selected.append(name)
    if set(selected) != set(tags):
        raise ValueError("Every pinned input must have exactly one reviewed mip action")
    if (not helper.is_file() or helper.is_symlink() or helper.stat().st_nlink != 1
            or sha256(helper) != helper_sha256):
        raise ValueError("Authored mip helper hash mismatch")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be new")
    if any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Symlink output ancestor refused")
    sources = {}
    for name, expected in tags.items():
        if (not isinstance(expected, str) or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)):
            raise ValueError(f"Invalid expected SHA256: {name}")
        path = checked_path(source, name)
        if sha256(path) != expected:
            raise ValueError(f"Changed source bitmap: {name}")
        sources[name] = path
    output.mkdir(parents=True)
    record = {
        "schema_version": 1, "status": "pending", "conversion": CONVERSION,
        "origin": profile.get("origin", "imported community bitmap; authorship unverified"),
        "source_root": str(source.resolve()), "profile_path": str(profile_path.resolve()),
        "profile_sha256": sha256(profile_path), "converter": str(helper.resolve()),
        "converter_sha256": helper_sha256, "input_sha256": tags, "actions": actions,
        "preservation": "All retained authored compressed mip bytes are exact; no resampling or recompression; all other bitmap parameters stay unchanged",
        "quality_tradeoff": "Highest authored 2048 mip is omitted; original 1024 and lower mips become the active texture",
        "community_departure": "Map-local texture resolution adaptation to fit the unchanged stock texture cache",
        "cache_evidence": profile.get("cache_evidence"),
        "runtime_acceptance": "pending separate in-game texture-cache and appearance validation",
    }
    record_path = output / "conversion.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    for name, source_file in sources.items():
        for subtree in ("source-snapshots", "tags"):
            destination = output / subtree / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, destination)
    (output / "mip-actions.tsv").write_text("".join(
        f"{action['tag']}\t0\t1\n" for action in actions))
    command = [str(helper.resolve()), str(output.resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / "convert.log").write_text(result.stdout + result.stderr)
    proven = set()
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if (len(fields) == 11 and fields[:1] == ["bitmap"]
                and fields[2:4] == ["0", "1"]
                and fields[-2:] == ["lower_mip_bytes_preserved", "all_other_parameters_preserved"]):
            proven.add(fields[1])
    record.update(command=command, returncode=result.returncode,
                  lower_mip_bytes_preserved=proven == set(selected),
                  source_unchanged=all(sha256(sources[name]) == expected for name, expected in tags.items()),
                  snapshots_unchanged=all(sha256(output / "source-snapshots" / name) == expected
                                          for name, expected in tags.items()),
                  output_sha256={name: sha256(output / "tags" / name) for name in selected})
    record["status"] = ("converted" if result.returncode == 0 and all(record[key] for key in
                        ("source_unchanged", "snapshots_unchanged", "lower_mip_bytes_preserved"))
                        else "failed")
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "converted":
        raise RuntimeError(f"Authored mip selection failed; inspect {output / 'convert.log'}")
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
    print(f"Selected existing lower authored mips for {len(record['output_sha256'])} bitmaps; runtime validation pending")


if __name__ == "__main__":
    main()
