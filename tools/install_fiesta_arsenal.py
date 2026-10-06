#!/usr/bin/env python3
"""Install reviewed hidden Fiesta caches beside independently owned game data.

Checks every source/base before writing. Original maps are never replaced;
different previous arsenal files are retained in a private backup directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

try:
    from .community_maps import MAX_CACHE_BYTES, TAG_ARENA_BYTES, cache_header, digest
    from .build_fiesta_arsenal import EXPECTED_WEAPON_SHA, GENERATION, physical_name, weapon_list_bytes
    from .weapon_pack_maps import compiled_tag_paths
except ImportError:
    from community_maps import MAX_CACHE_BYTES, TAG_ARENA_BYTES, cache_header, digest
    from build_fiesta_arsenal import EXPECTED_WEAPON_SHA, GENERATION, physical_name, weapon_list_bytes
    from weapon_pack_maps import compiled_tag_paths

NAME = re.compile(r"[a-z0-9_ -]{1,31}\Z")
FIELDS = {"schema_version", "generation", "logical_map", "physical_map", "cache_sha256",
          "base_sha256", "weapon_list_sha256", "cache_file_bytes", "cache_declared_bytes"}


def manifest_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate arsenal manifest field: {key}")
        result[key] = value
    return result


def prepare(arsenal: Path, data: Path, additional_map_roots: list[Path]) -> list[dict]:
    arsenal, data = arsenal.resolve(strict=True), data.resolve(strict=True)
    roots = [data / "maps", *additional_map_roots]
    expected = set(weapon_list_bytes().decode("ascii").splitlines())
    records = []
    for path in sorted(arsenal.glob("*.json")):
        if path.is_symlink() or not 1 <= path.stat().st_size <= 4096:
            raise ValueError(f"Manifest must be a small regular file: {path}")
        manifest_bytes = path.read_bytes()
        if not 1 <= len(manifest_bytes) <= 4096:
            raise ValueError(f"Manifest must be a small regular file: {path}")
        # Runtime metadata is flat ASCII with unescaped names/digests. Match
        # that grammar so successful installation also means it can be read.
        if b"\\" in manifest_bytes:
            raise ValueError(f"Arsenal manifest strings must be unescaped ASCII: {path}")
        manifest = json.loads(manifest_bytes.decode("ascii"), object_pairs_hook=manifest_object)
        if (not isinstance(manifest, dict) or set(manifest) != FIELDS
                or any(type(manifest[key]) is not int for key in
                       ("schema_version", "generation", "cache_file_bytes", "cache_declared_bytes"))
                or manifest["schema_version"] != 1
                or manifest["generation"] != GENERATION
                or manifest["weapon_list_sha256"] != EXPECTED_WEAPON_SHA):
            raise ValueError(f"Unsupported arsenal manifest: {path}")
        logical, physical = manifest["logical_map"], manifest["physical_map"]
        expected_physical = physical_name(logical) if isinstance(logical, str) else None
        if (not isinstance(logical, str) or not NAME.fullmatch(logical)
                or physical != expected_physical or not NAME.fullmatch(physical)
                or path.stem != physical):
            raise ValueError(f"Unsafe or mismatched arsenal identity: {path}")
        cache = arsenal / (physical + ".map")
        if cache.is_symlink() or not cache.is_file():
            raise ValueError(f"Cache must be a regular file: {cache}")
        header = cache_header(cache)
        if (header["version"] != 5 or header["type"] != 1
                or header["name"] != physical
                or header["sha256"] != manifest["cache_sha256"]
                or header["file_bytes"] != manifest["cache_file_bytes"]
                or header["declared_bytes"] != manifest["cache_declared_bytes"]
                or header["declared_bytes"] > MAX_CACHE_BYTES
                or header["file_bytes"] > MAX_CACHE_BYTES or header["tag_bytes"] > TAG_ARENA_BYTES):
            raise ValueError(f"Cache differs from reviewed manifest: {cache}")
        names = {name.lower().replace("/", "\\") for group, name in compiled_tag_paths(cache)
                 if group == 0x77656170}
        if not expected.issubset(names):
            raise ValueError(f"Incomplete global arsenal: {cache}")
        base = next((root / (logical + ".map") for root in roots
                     if (root / (logical + ".map")).is_file()), None)
        if base is None or digest(base) != manifest["base_sha256"]:
            raise ValueError(f"Original {logical} map is missing or differs from the arsenal base")
        records.append({"manifest": manifest, "manifest_path": path, "cache_path": cache,
                        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                        "base_path": base, "base_sha256": manifest["base_sha256"]})
    if not records:
        raise ValueError("No reviewed Fiesta manifests found")
    return records


def install(arsenal: Path, data: Path, additional_map_roots: list[Path]) -> dict:
    records = prepare(arsenal, data, additional_map_roots)
    destination = data.resolve(strict=True) / "maps/arsenal/v1"
    if any(parent.is_symlink() for parent in (destination, destination.parent, destination.parent.parent)):
        raise ValueError("Hidden arsenal destination directories cannot be symbolic links")
    destination.mkdir(parents=True, exist_ok=True)
    backup = None
    installed = []
    copied_bases = []
    for record in records:
        # An overlay-only community base travels with its hidden derivative when
        # the user later manages a copy of this game-data folder.
        base_target = data.resolve(strict=True) / "maps" / (record["manifest"]["logical_map"] + ".map")
        if not base_target.exists():
            with tempfile.NamedTemporaryFile(prefix=".staging-", dir=base_target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    with record["base_path"].open("rb") as original:
                        shutil.copyfileobj(original, stream)
                    stream.flush()
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                if digest(temporary) != record["base_sha256"]:
                    raise RuntimeError("Copied community base differs from its original")
                # Publish only a complete base, without replacing an existing
                # map even if another importer creates it during staging.
                os.link(temporary, base_target)
            finally:
                temporary.unlink(missing_ok=True)
            copied_bases.append(str(base_target))
        if not base_target.is_file() or digest(base_target) != record["base_sha256"]:
            raise RuntimeError("The active original map differs from its reviewed base")
        for source in (record["cache_path"], record["manifest_path"]):
            target = destination / source.name
            expected = (record["manifest"]["cache_sha256"] if source == record["cache_path"]
                        else record["manifest_sha256"])
            if target.is_symlink():
                raise ValueError(f"Refusing to replace a non-regular arsenal file: {target}")
            if target.is_file() and digest(target) == expected:
                continue
            if target.exists():
                if not target.is_file() or target.is_symlink():
                    raise ValueError(f"Refusing to replace a non-regular arsenal file: {target}")
                if backup is None:
                    backup = Path(tempfile.mkdtemp(prefix=".previous-", dir=destination))
                shutil.copy2(target, backup / target.name)
            with tempfile.NamedTemporaryFile(prefix=".staging-", dir=destination, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    with source.open("rb") as original:
                        shutil.copyfileobj(original, stream)
                    stream.flush()
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                if digest(temporary) != expected:
                    raise RuntimeError("Staged arsenal digest changed")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        installed.append(record["manifest"])
    if any(digest(record["base_path"]) != record["base_sha256"] for record in records):
        raise RuntimeError("An original map changed during installation")
    return {"status": "installed", "destination": str(destination),
            "previous_arsenal_backup": str(backup) if backup else None,
            "original_maps_unchanged": True, "copied_overlay_base_maps": copied_bases, "maps": installed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arsenal", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--additional-map-root", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = install(args.arsenal, args.data_root, args.additional_map_root)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "destination", "original_maps_unchanged")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
