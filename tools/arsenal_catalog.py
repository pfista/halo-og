#!/usr/bin/env python3
"""Prepare clean hidden-Fiesta delivery objects from reviewed authoring output.

Never uploads. Original maps, extracted tags, authoring paths, proofs and helper
binaries are not copied into this public object tree. Players still supply the
exact original map authenticated by each entry's base SHA-256.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if __package__:
    from .map_catalog import MAX_CATALOG_BYTES, MAX_MAPS, publish_directory, validate_map
    from .publish_map_catalog import PublishError, parse_json, read_regular
else:
    from map_catalog import MAX_CATALOG_BYTES, MAX_MAPS, publish_directory, validate_map
    from publish_map_catalog import PublishError, parse_json, read_regular

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "fiesta-arsenal-v1"
GENERATION = 1
WEAPON_LIST_SHA256 = "2856504cbd257e1b18c273caa64237fbfe77dc77d22cce1a7fa0a0abfc53f71f"
# Inventory revision is independent of the pinned generation-one weapon pack.
CATALOG_KEY = "catalogs/testing/arsenals-v2.json"
MAX_CACHE_BYTES = 512 * 1024 * 1024
MAX_BATCH_BYTES = 4 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 4096
LOGICAL_NAME = re.compile(r"[a-z0-9][a-z0-9_ -]{0,30}\Z")
RESERVED_NAMES = set("ui a10 a30 a50 b30 b40 c10 c20 c40 d20 d40 con prn aux nul".split())
RESERVED_NAMES.update(f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10))
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CATALOG_FIELDS = {"schema_version", "profile", "generation", "weapon_list_sha256", "arsenals"}
ENTRY_FIELDS = {"logical_map", "physical_map", "base_sha256", "cache_sha256", "cache_file_bytes",
                "cache_declared_bytes", "manifest_sha256", "manifest_bytes", "cache_object_key", "manifest_object_key"}
MANIFEST_FIELDS = {"schema_version", "generation", "logical_map", "physical_map", "cache_sha256",
                   "base_sha256", "weapon_list_sha256", "cache_file_bytes", "cache_declared_bytes"}


@dataclass(frozen=True)
class PreparedArsenals:
    directory: Path
    catalog: bytes
    arsenals: tuple
    objects: tuple

    @property
    def upload_bytes(self):
        return len(self.catalog) + sum(entry["file_bytes"] for entry in self.objects)


def physical_name(logical):
    # This is the same generation-one identity rule used by authoring/runtime.
    # A long logical name hashes into a separate prefix to avoid short-name
    # collisions. Object keys additionally distinguish original-cache revisions.
    if (not isinstance(logical, str) or not LOGICAL_NAME.fullmatch(logical)
            or logical.endswith(" ") or logical in RESERVED_NAMES):
        raise PublishError("Logical arsenal map is not a lowercase safe ASCII basename")
    return ("_fiesta_" + logical if len(logical) <= 23 else
            "_fiestah_" + hashlib.sha256(logical.encode("ascii")).hexdigest()[:16])


def ascii_json(data, limit):
    if not 1 <= len(data) <= limit or b"\\" in data:
        raise PublishError("Arsenal JSON must be bounded, unescaped ASCII")
    try:
        data.decode("ascii")
    except UnicodeError:
        raise PublishError("Arsenal JSON must be bounded, unescaped ASCII") from None
    return parse_json(data)


def bounded_integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def digest_value(value):
    return isinstance(value, str) and SHA256.fullmatch(value)


def validate_manifest(data):
    manifest = ascii_json(data, MAX_MANIFEST_BYTES)
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or type(manifest["generation"]) is not int or manifest["generation"] != GENERATION
            or manifest["weapon_list_sha256"] != WEAPON_LIST_SHA256
            or manifest["physical_map"] != physical_name(manifest["logical_map"])
            or not digest_value(manifest["base_sha256"]) or not digest_value(manifest["cache_sha256"])
            or not bounded_integer(manifest["cache_file_bytes"], 2048, MAX_CACHE_BYTES)
            or not bounded_integer(manifest["cache_declared_bytes"], 2048, MAX_CACHE_BYTES)):
        raise PublishError("Arsenal manifest has a different identity, pin, schema or byte bound")
    return manifest


def entry_from_manifest(data):
    manifest = validate_manifest(data)
    entry = {key: manifest[key] for key in ("logical_map", "physical_map", "base_sha256", "cache_sha256",
                                          "cache_file_bytes", "cache_declared_bytes")}
    entry.update(manifest_sha256=hashlib.sha256(data).hexdigest(), manifest_bytes=len(data),
                 cache_object_key=f"arsenals/v1/sha256/{manifest['cache_sha256']}/{manifest['physical_map']}.map",
                 manifest_object_key=f"arsenals/v1/sha256/{hashlib.sha256(data).hexdigest()}/{manifest['physical_map']}.json")
    return entry


def catalog_bytes(entries):
    catalog = {"schema_version": 1, "profile": PROFILE, "generation": GENERATION,
               "weapon_list_sha256": WEAPON_LIST_SHA256,
               "arsenals": sorted(entries, key=lambda entry: (entry["logical_map"], entry["base_sha256"]))}
    data = (json.dumps(catalog, indent=2, ensure_ascii=False) + "\n").encode("ascii")
    validate_catalog(data)
    return data


def validate_catalog(data, allowed_logical_maps=None):
    catalog = ascii_json(data, MAX_CATALOG_BYTES)
    if (not isinstance(catalog, dict) or set(catalog) != CATALOG_FIELDS
            or type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1
            or catalog["profile"] != PROFILE or type(catalog["generation"]) is not int
            or catalog["generation"] != GENERATION or catalog["weapon_list_sha256"] != WEAPON_LIST_SHA256
            or not isinstance(catalog["arsenals"], list) or not 1 <= len(catalog["arsenals"]) <= MAX_MAPS):
        raise PublishError("Arsenal catalog has a different schema, profile, pin or entry bound")
    identities, total = set(), len(data)
    for entry in catalog["arsenals"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise PublishError("Arsenal catalog entry has unexpected fields")
        logical, physical = entry["logical_map"], entry["physical_map"]
        if (physical != physical_name(logical) or not digest_value(entry["base_sha256"])
                or not digest_value(entry["cache_sha256"]) or not digest_value(entry["manifest_sha256"])
                or not bounded_integer(entry["cache_file_bytes"], 2048, MAX_CACHE_BYTES)
                or not bounded_integer(entry["cache_declared_bytes"], 2048, MAX_CACHE_BYTES)
                or not bounded_integer(entry["manifest_bytes"], 1, MAX_MANIFEST_BYTES)
                or entry["cache_object_key"] != f"arsenals/v1/sha256/{entry['cache_sha256']}/{physical}.map"
                or entry["manifest_object_key"] != f"arsenals/v1/sha256/{entry['manifest_sha256']}/{physical}.json"
                or (allowed_logical_maps is not None and logical not in allowed_logical_maps)):
            raise PublishError("Arsenal catalog entry has an invalid identity, digest, immutable key or byte bound")
        identity = logical, entry["base_sha256"]
        if identity in identities:
            raise PublishError("Duplicate arsenal logical-map/base-SHA identity")
        identities.add(identity)
        total += entry["cache_file_bytes"] + entry["manifest_bytes"]
        if total > MAX_BATCH_BYTES:
            raise PublishError("Arsenal catalog transfer exceeds the 4 GiB batch bound")
    return catalog


def object_entries(entries):
    objects = {}
    for entry in entries:
        for kind, digest, size, key in (
            ("cache", entry["cache_sha256"], entry["cache_file_bytes"], entry["cache_object_key"]),
            ("manifest", entry["manifest_sha256"], entry["manifest_bytes"], entry["manifest_object_key"]),
        ):
            record = {"id": entry["logical_map"] + " " + kind, "sha256": digest, "file_bytes": size,
                      "object_key": key, "content_type": "application/json" if kind == "manifest" else "application/octet-stream"}
            if key in objects and any(objects[key][field] != record[field] for field in ("sha256", "file_bytes", "content_type")):
                raise PublishError("Shared immutable arsenal object has conflicting metadata")
            objects.setdefault(key, record)
    return tuple(objects.values())


def validate_cache(path, manifest):
    try:
        header = validate_map(path)
    except ValueError:
        raise PublishError("Arsenal cache does not satisfy the native Xbox cache checks") from None
    if (header["name"] != manifest["physical_map"] or header["sha256"] != manifest["cache_sha256"]
            or header["file_bytes"] != manifest["cache_file_bytes"]
            or header["declared_bytes"] != manifest["cache_declared_bytes"]):
        raise PublishError("Arsenal cache differs from its manifest identity, digest or size")


def validate_prepared(directory, allowed_logical_maps=None):
    directory = Path(os.path.abspath(directory))
    if directory.is_symlink() or not directory.is_dir():
        raise PublishError("Select an existing prepared arsenal directory")
    data = read_regular(directory / "catalog.json", MAX_CATALOG_BYTES)
    entries = validate_catalog(data, allowed_logical_maps)["arsenals"]
    objects = object_entries(entries)
    expected_files = {"catalog.json", *(entry["object_key"] for entry in objects)}
    expected_dirs = set()
    for key in expected_files - {"catalog.json"}:
        parent = Path(key).parent
        while str(parent) != ".":
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    files, directories = set(), set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise PublishError("Prepared arsenal tree cannot contain symlinks")
        name = path.relative_to(directory).as_posix()
        if path.is_file():
            files.add(name)
        elif path.is_dir():
            directories.add(name)
        else:
            raise PublishError("Prepared arsenal tree contains a nonregular input")
    if files != expected_files or directories != expected_dirs:
        raise PublishError("Prepared arsenal tree must contain only the clean catalog and its declared cache/manifest objects")
    for entry in entries:
        manifest_data = read_regular(directory / entry["manifest_object_key"], MAX_MANIFEST_BYTES)
        if entry_from_manifest(manifest_data) != entry:
            raise PublishError("Prepared flat manifest differs from the delivery entry")
        validate_cache(directory / entry["cache_object_key"], validate_manifest(manifest_data))
    return PreparedArsenals(directory, data, tuple(entries), objects)


def prepare_catalog(authoring_catalog, arsenal, output, selected_maps=()):
    authoring_catalog, arsenal = Path(authoring_catalog), Path(arsenal)
    if authoring_catalog.is_symlink() or arsenal.is_symlink() or not arsenal.is_dir():
        raise PublishError("Select regular reviewed authoring inputs")
    # Private provenance is read only to qualify/compare selected outputs. None
    # of its nested paths or source-tree records enter the public JSON.
    authoring = parse_json(read_regular(authoring_catalog, 4 * MAX_CATALOG_BYTES))
    if (not isinstance(authoring, dict) or type(authoring.get("schema_version")) is not int
            or authoring.get("schema_version") != 1 or type(authoring.get("generation")) is not int
            or authoring.get("generation") != GENERATION or authoring.get("weapon_list_sha256") != WEAPON_LIST_SHA256
            or authoring.get("failures") or not isinstance(authoring.get("maps"), dict)):
        raise PublishError("Authoring catalog is incomplete or differs from the pinned arsenal generation")
    names = sorted(set(selected_maps) if selected_maps else authoring["maps"])
    if not 1 <= len(names) <= MAX_MAPS or any(name not in authoring["maps"] for name in names):
        raise PublishError("Select one to 115 reviewed authoring maps")
    entries, sources = [], {}
    for name in names:
        physical = physical_name(name)
        source_manifest = arsenal / (physical + ".json")
        source_cache = arsenal / (physical + ".map")
        if source_manifest.is_symlink() or source_cache.is_symlink():
            raise PublishError("Arsenal inputs cannot contain selected symlinks")
        manifest_data = read_regular(source_manifest, MAX_MANIFEST_BYTES)
        manifest = validate_manifest(manifest_data)
        reviewed = authoring["maps"][name]
        proof = reviewed.get("compiled_player_proof", {}) if isinstance(reviewed, dict) else {}
        weapons = reviewed.get("eligible_weapons", []) if isinstance(reviewed, dict) else []
        if (not isinstance(reviewed, dict) or any(reviewed.get(key) != value for key, value in manifest.items())
                or reviewed.get("all_count") != 31 or reviewed.get("uncut_count") != 9
                or not isinstance(proof, dict)
                or proof.get("all_other_compiled_player_bytes_equal") is not True
                or proof.get("compiled_multiplayer_globals_reference_verified") is not True
                or not isinstance(weapons, list) or len(weapons) != 31
                or any(not isinstance(weapon, str) for weapon in weapons)
                or hashlib.sha256(("\n".join(sorted(weapons)) + "\n").encode("ascii")).hexdigest() != WEAPON_LIST_SHA256):
            raise PublishError("Authoring cache lacks the full reviewed 31/9 arsenal or player preservation proof")
        validate_cache(source_cache, manifest)
        entry = entry_from_manifest(manifest_data)
        entries.append(entry)
        sources[entry["cache_object_key"]] = source_cache
        sources[entry["manifest_object_key"]] = source_manifest
    data = catalog_bytes(entries)
    if ".." in Path(output).parts:
        raise PublishError("Prepared output cannot traverse directories")
    output = Path(os.path.abspath(output))
    if any(parent.is_symlink() for parent in (output, *output.parents)):
        raise PublishError("Prepared output cannot traverse or follow symlink directories")
    output = output.resolve(strict=False)
    if not output.is_relative_to((ROOT / "build").resolve()) or output == (ROOT / "build").resolve():
        raise PublishError("Use a fresh child of this repository's ignored build directory")
    protected = (authoring_catalog.resolve().parent, arsenal.resolve())
    if any(output == path or output.is_relative_to(path) for path in protected):
        raise PublishError("Prepared output cannot be inside reviewed inputs")
    if os.path.lexists(output):
        raise FileExistsError("Prepared output already exists; choose a fresh build directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="." + output.name + "-", suffix=".partial", dir=output.parent))
    try:
        for key, source in sources.items():
            target = staged / key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target, follow_symlinks=False)
        (staged / "catalog.json").write_bytes(data)
        validate_prepared(staged)
        publish_directory(staged, output)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return PreparedArsenals(output, data, tuple(entries), object_entries(entries))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authoring-catalog", type=Path, required=True)
    parser.add_argument("--arsenal", type=Path, required=True, help="Reviewed maps/arsenal/v1 input directory")
    parser.add_argument("--output", type=Path, required=True, help="New ignored build directory")
    parser.add_argument("--map", action="append", default=[], help="Optional reviewed logical-map subset")
    args = parser.parse_args()
    try:
        prepared = prepare_catalog(args.authoring_catalog, args.arsenal, args.output, args.map)
        print(f"Prepared {len(prepared.arsenals)} hidden arsenals; {prepared.upload_bytes} upload bytes including the clean catalog")
        print("No credentials read or files uploaded.")
    except (PublishError, OSError, ValueError, UnicodeError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, PublishError) else "Local arsenal inputs could not be safely prepared"
        parser.exit(1, "Arsenal preparation failed: " + message + "\n")


if __name__ == "__main__":
    main()
