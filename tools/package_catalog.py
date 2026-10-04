#!/usr/bin/env python3
"""Prepare package-only delivery after exact rebuild and whole-stock-asset audit.

No upload occurs. Original stock tags and complete maps are read-only local
acceptance inputs; the public tree contains only catalog.json and .mapog files.
Modified original assets remain within the explicitly selected v1 scope.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import community_packages as packages
from tools import mapog
from tools.map_catalog import MAX_CATALOG_BYTES, MAX_MAPS, publish_directory, validate_map

ENTRY_FIELDS = {"id", "sha256", "file_bytes", "cache_version", "cache_build",
                "scenario_type", "object_key", "prefetch", "package_sha256", "package_bytes"}
MAX_BATCH_BYTES = 4 * 1024 * 1024 * 1024


def _entries(directory, catalog, allowed_ids=None):
    if (not isinstance(catalog, dict) or set(catalog) != {"schema_version", "profile", "maps"}
            or type(catalog["schema_version"]) is not int or catalog["schema_version"] != 2
            or catalog["profile"] != "stock-xbox-ntsc" or not isinstance(catalog["maps"], list)
            or not 1 <= len(catalog["maps"]) <= MAX_MAPS):
        raise ValueError("Only version-2 package catalogs are permitted")
    seen, total = set(), 0
    for entry in catalog["maps"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise ValueError("Package catalog entry has unexpected fields")
        identity = entry["id"]
        if (not isinstance(identity, str) or not packages.ID.fullmatch(identity)
                or identity in packages.STOCK_IDS):
            raise ValueError("Package identity is invalid or reserved for original game content")
        packages._consumer_path(identity + ".map", "windows")
        if identity in seen or (allowed_ids is not None and identity not in allowed_ids):
            raise ValueError("Package identity is duplicate or outside the reviewed collection")
        seen.add(identity)
        if (not isinstance(entry["package_sha256"], str) or not packages.SHA.fullmatch(entry["package_sha256"])
                or not isinstance(entry["sha256"], str) or not packages.SHA.fullmatch(entry["sha256"])
                or type(entry["package_bytes"]) is not int or not 56 <= entry["package_bytes"] <= packages.MAX_PACKAGE_BYTES
                or type(entry["file_bytes"]) is not int or not 2048 <= entry["file_bytes"] <= packages.MAX_CACHE_BYTES
                or type(entry["cache_version"]) is not int or entry["cache_version"] != 5
                or entry["cache_build"] != packages.NTSC_BUILD
                or type(entry["scenario_type"]) is not int or entry["scenario_type"] != 1
                or type(entry["prefetch"]) is not bool):
            raise ValueError("Package delivery metadata or bounds are invalid")
        expected = f"packages/sha256/{entry['package_sha256']}/{identity}.mapog"
        if entry["object_key"] != expected:
            raise ValueError("Only immutable compressed .mapog objects may be served")
        path = directory / expected
        packages._regular(path)
        if path.stat().st_size != entry["package_bytes"] or packages.digest(path) != entry["package_sha256"]:
            raise ValueError("Package object differs from the catalog")
        manifest = packages.read_package(path)
        if not mapog.is_compressed(path):
            raise ValueError("Public packages must use the compressed .mapog envelope")
        if (manifest["id"] != identity or manifest["output"]["size"] != entry["file_bytes"]
                or manifest["output"]["sha256"] != entry["sha256"]):
            raise ValueError("Package output identity differs from the catalog")
        total += entry["package_bytes"]
        if total > MAX_BATCH_BYTES:
            raise ValueError("Package collection exceeds the 4 GiB transfer limit")
    return catalog["maps"]


def validate_public_tree(directory, allowed_ids=None):
    directory = Path(os.path.abspath(directory))
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Select a real prepared package delivery directory")
    path = packages._regular(directory / "catalog.json")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or packages._reparse(info):
            raise ValueError("Catalog must be a regular file without links")
        data = stream.read(MAX_CATALOG_BYTES + 1)
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError("Catalog exceeds the 1 MiB limit")
    catalog = json.loads(data, object_pairs_hook=packages._unique_json)
    entries = _entries(directory, catalog, allowed_ids)
    expected = {"catalog.json"} | {item["object_key"] for item in entries}
    actual, directories, expected_dirs = set(), set(), set()
    for key in expected - {"catalog.json"}:
        parent = Path(key).parent
        while parent != Path("."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    for path in directory.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or packages._reparse(info):
            raise ValueError("Delivery must not contain links")
        if stat.S_ISREG(info.st_mode):
            actual.add(path.relative_to(directory).as_posix())
        elif stat.S_ISDIR(info.st_mode):
            directories.add(path.relative_to(directory).as_posix())
        else:
            raise ValueError("Delivery must contain only regular files and directories")
    if actual != expected or directories != expected_dirs:
        raise ValueError("Delivery must contain exactly catalog.json and declared packages; no maps, stock assets, logs or helpers")
    return data, catalog


def prepare_package_catalog(package_files, rebuilt_maps, original_stock_tags, output, prefetch=()):
    output = Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise FileExistsError("Choose a new package delivery directory")
    if not 1 <= len(package_files) <= MAX_MAPS:
        raise ValueError("Select between 1 and 115 packages")
    originals = packages._tree(original_stock_tags)
    original_hashes = {(item["size"], item["sha256"]) for item in originals.values()}
    maps = {}
    for path in rebuilt_maps:
        header = validate_map(path)
        identity = header["name"].casefold()
        if identity in maps:
            raise ValueError("Duplicate rebuilt map")
        maps[identity] = header
    selected, audits = {}, []
    for path in package_files:
        path = packages._regular(path)
        source_identity = (path.stat().st_size, packages.digest(path))
        with mapog.raw_package(path) as raw:
            raw_identity = (raw.stat().st_size, packages.digest(raw))
            manifest = packages.read_package(raw)
            if (raw.stat().st_size, packages.digest(raw)) != raw_identity:
                raise ValueError("Package source changed during asset audit")
        if (path.stat().st_size, packages.digest(path)) != source_identity:
            raise ValueError("Package source changed during asset audit")
        identity = manifest["id"]
        if identity in selected:
            raise ValueError("Duplicate package identity")
        packages._verify_originals(manifest, originals)
        matched_literals = [entry["tree"] + "/" + entry["path"] for entry in manifest["files"]
                            if entry["kind"] == "literal" and (entry["size"], entry["sha256"]) in original_hashes]
        if matched_literals:
            raise ValueError("An unchanged whole original asset remains literal: " + matched_literals[0])
        header = maps.get(identity)
        expected = manifest["output"]
        if (not header or header["sha256"] != expected["sha256"] or header["file_bytes"] != expected["size"]
                or header["declared_bytes"] != expected["declared_bytes"] or header["tag_bytes"] != expected["tag_bytes"]):
            raise ValueError("A package lacks an exact independently rebuilt local map: " + identity)
        selected[identity] = (path, manifest, source_identity, raw_identity)
        counts = Counter(entry["classification"] for entry in manifest["files"])
        audits.append({"id": identity, "whole_asset_classifications": dict(counts),
                       "unchanged_original_bytes_omitted": sum(entry["size"] for entry in manifest["files"] if entry["kind"] == "stock-reference"),
                       "unchanged_original_literals": 0, "exact_rebuilt_map_sha256": header["sha256"]})
    if set(maps) != set(selected):
        raise ValueError("Select exactly one rebuilt map for every package")
    requested = set(prefetch)
    if requested - selected.keys():
        raise ValueError("Prefetch map was not selected")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".package-delivery-", dir=output.parent))
    try:
        entries = []
        for identity, (source, manifest, source_identity, raw_identity) in sorted(selected.items()):
            if (source.stat().st_size, packages.digest(source)) != source_identity:
                raise ValueError("Package source changed after asset audit")
            compressed = staged / (identity + ".mapog")
            if mapog.is_compressed(source):
                shutil.copyfile(source, compressed)
            else:
                mapog.compress_package(source, compressed)
            if (source.stat().st_size, packages.digest(source)) != source_identity:
                raise ValueError("Package source changed while preparing delivery")
            with mapog.raw_package(compressed) as raw:
                if (raw.stat().st_size, packages.digest(raw)) != raw_identity:
                    raise ValueError("Staged package differs from the audited source")
            digest = packages.digest(compressed)
            key = f"packages/sha256/{digest}/{identity}.mapog"
            destination = staged / key
            destination.parent.mkdir(parents=True)
            os.rename(compressed, destination)
            entries.append({"id": identity, "sha256": manifest["output"]["sha256"],
                            "file_bytes": manifest["output"]["size"], "cache_version": 5,
                            "cache_build": packages.NTSC_BUILD, "scenario_type": 1,
                            "object_key": key, "prefetch": identity in requested,
                            "package_sha256": digest, "package_bytes": destination.stat().st_size})
        catalog = {"schema_version": 2, "profile": "stock-xbox-ntsc", "maps": entries}
        encoded = (json.dumps(catalog, indent=2) + "\n").encode()
        if len(encoded) > MAX_CATALOG_BYTES:
            raise ValueError("Catalog exceeds the 1 MiB limit")
        (staged / "catalog.json").write_bytes(encoded)
        validate_public_tree(staged)
        publish_directory(staged, output)
        return catalog, {"scope": "whole-byte-identical-original-tags-only", "modified_originals_retained": True,
                         "catalog_sha256": hashlib.sha256(encoded).hexdigest(), "maps": audits}
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, action="append", required=True)
    parser.add_argument("--rebuilt-map", type=Path, action="append", required=True)
    parser.add_argument("--original-stock-tags", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True, help="Fresh private audit receipt outside the public tree")
    parser.add_argument("--prefetch", action="append", default=[])
    args = parser.parse_args()
    if args.audit.exists() or args.audit.resolve().is_relative_to(args.output.resolve()):
        parser.error("Audit must be a new file outside the public delivery directory")
    catalog, audit = prepare_package_catalog(args.package, args.rebuilt_map, args.original_stock_tags, args.output, args.prefetch)
    with args.audit.open("x", encoding="utf-8") as file:
        json.dump(audit, file, indent=2); file.write("\n")
    print(f"Prepared {len(catalog['maps'])} audited package objects. No complete maps or original stock files in delivery; no upload occurred.")


if __name__ == "__main__":
    main()
