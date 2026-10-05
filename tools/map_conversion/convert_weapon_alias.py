#!/usr/bin/env python3
"""Create a reviewed map-local weapon alias without changing stock globals."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess

CONVERSION = "map_local_weapon_alias"
GLOBALS = "globals/globals.globals"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(name: str, suffixes: tuple[str, ...]) -> PurePosixPath:
    if not isinstance(name, str):
        raise ValueError("Tag path must be text")
    part = PurePosixPath(name)
    if (not name or part.is_absolute() or str(part) != name
            or any(p in (".", "..") for p in part.parts)
            or any(c in name for c in "\t\r\n\\") or part.suffix not in suffixes):
        raise ValueError(f"Unsafe weapon alias path: {name}")
    return part


def checked_path(root: Path, name: str) -> Path:
    part = relative_path(name, (".weapon", ".globals", ".scenario", ".item_collection"))
    at = root
    if at.is_symlink():
        raise ValueError("Symlink source root")
    for component in part.parts:
        at /= component
        if at.is_symlink():
            raise ValueError(f"Symlink source dependency: {name}")
    if not at.is_file() or at.stat().st_nlink != 1:
        raise ValueError(f"Missing or hard-linked source dependency: {name}")
    return at


def convert(source: Path, profile_path: Path, helper: Path,
            helper_sha256: str, output: Path) -> dict:
    profile = json.loads(profile_path.read_text())
    if (profile.get("schema_version") != 1 or profile.get("target_engine") != "xbox"
            or profile.get("write_policy") != "fresh_overlay"
            or profile.get("conversion") != CONVERSION):
        raise ValueError("Unsupported weapon alias profile")
    alias, rules, tags = profile.get("alias"), profile.get("reference_rules"), profile.get("tags")
    if (not isinstance(alias, dict) or set(alias) != {"source_weapon", "alias_weapon", "globals_tag", "reserved_slot"}
            or not isinstance(rules, list) or not rules or not isinstance(tags, dict)):
        raise ValueError("Profile needs one explicit alias and reviewed authored references")
    original, destination = alias["source_weapon"], alias["alias_weapon"]
    relative_path(original, (".weapon",))
    relative_path(destination, (".weapon",))
    if (original == destination or not destination.startswith("community/")
            or alias["globals_tag"] != GLOBALS
            or type(alias["reserved_slot"]) is not int or alias["reserved_slot"] < 0):
        raise ValueError("Invalid community alias or reserved globals proof")
    owners = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"tag", "expected_replacements"}:
            raise ValueError("Unsupported authored-reference rule")
        relative_path(rule["tag"], (".scenario", ".item_collection"))
        if (rule["tag"] in owners or type(rule["expected_replacements"]) is not int
                or rule["expected_replacements"] < 1):
            raise ValueError("Duplicate owner or invalid replacement count")
        owners.append(rule["tag"])
    if set(tags) != {original, GLOBALS, *owners}:
        raise ValueError("Input hashes must exactly cover the original weapon, globals and authored owners")
    if (not helper.is_file() or helper.is_symlink() or helper.stat().st_nlink != 1
            or sha256(helper) != helper_sha256):
        raise ValueError("Weapon alias helper hash mismatch")
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
            raise ValueError(f"Changed source dependency: {name}")
        sources[name] = path
    at = source
    for component in PurePosixPath(destination).parts:
        at /= component
        if at.is_symlink():
            raise ValueError("Symlink alias source path")
    if at.exists():
        raise ValueError("Community alias already exists in source tags")
    output.mkdir(parents=True)
    record = {
        "schema_version": 1, "status": "pending", "conversion": CONVERSION,
        "origin": profile.get("origin", "imported community weapon; authorship unverified"),
        "source_root": str(source.resolve()), "profile_path": str(profile_path.resolve()),
        "profile_sha256": sha256(profile_path), "converter": str(helper.resolve()),
        "converter_sha256": helper_sha256, "input_sha256": tags,
        "alias": alias, "reference_rules": rules,
        "community_departure": "Authored grants use a map-local identity to avoid the stock multiplayer reserved-weapon remap",
        "preservation": "Alias weapon bytes are identical; only reviewed authored dependency identities change; stock globals and engine remap remain unchanged",
        "runtime_bug_source": profile.get("runtime_bug_source"),
        "runtime_acceptance": "pending separate in-game validation",
    }
    record_path = output / "conversion.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    for name, source_file in sources.items():
        snapshot = output / "source-snapshots" / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, snapshot)
        if name in owners:
            target = output / "tags" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target)
    target = output / "tags" / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sources[original], target)
    (output / "weapon-alias.tsv").write_text(
        f"{original}\t{destination}\t{GLOBALS}\t{alias['reserved_slot']}\n")
    (output / "reference-rules.tsv").write_text("".join(
        f"{rule['tag']}\t{rule['expected_replacements']}\n" for rule in rules))
    command = [str(helper.resolve()), str(output.resolve())]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / "convert.log").write_text(result.stdout + result.stderr)
    outputs = {name: sha256(output / "tags" / name) for name in [destination, *owners]}
    record.update(command=command, returncode=result.returncode, output_sha256=outputs,
                  source_unchanged=all(sha256(sources[name]) == expected for name, expected in tags.items()),
                  snapshots_unchanged=all(sha256(output / "source-snapshots" / name) == expected
                                          for name, expected in tags.items()),
                  alias_bytes_identical=outputs[destination] == tags[original],
                  globals_unchanged=sha256(sources[GLOBALS]) == tags[GLOBALS]
                  and not (output / "tags" / GLOBALS).exists())
    record["status"] = ("converted" if result.returncode == 0 and all(record[key] for key in
                        ("source_unchanged", "snapshots_unchanged", "alias_bytes_identical", "globals_unchanged"))
                        else "failed")
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    if record["status"] != "converted":
        raise RuntimeError(f"Weapon alias conversion failed; inspect {output / 'convert.log'}")
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
    print(f"Created byte-identical weapon alias and converted {len(record['reference_rules'])} authored reference owners; runtime validation pending")


if __name__ == "__main__":
    main()
