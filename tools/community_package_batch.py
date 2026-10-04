#!/usr/bin/env python3
"""Audit and verify whole-tag v1 packages from reviewed prepared collections.

Producer-only tooling: no uploads, app launches, runtime helper changes or
rights claims. Every accepted output must reproduce its approved complete map.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import community_packages as packages

SCOPE = ("Only complete prepared tags equal to complete freshly extracted stock tags "
         "are omitted. Modified, differently serialized and unknown assets remain "
         "whole literals. This is not an authorship or rights clearance audit.")


def _json(path):
    path = packages._regular(path)
    if path.stat().st_size > packages.MAX_MANIFEST_BYTES:
        raise packages.PackageError("Producer metadata exceeds limits")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=packages._unique_json)


def _write_json(path, record):
    # Every batch is a new directory; even its metadata is exclusive.
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _tree_identity(root):
    tree = packages._tree(root)
    records = [{"path": name, "size": item["size"], "sha256": item["sha256"]}
               for name, item in tree.items()]
    encoded = json.dumps(records, separators=(",", ":"), sort_keys=True).encode()
    return {"files": len(tree), "bytes": sum(item["size"] for item in tree.values()),
            "inventory_sha256": hashlib.sha256(encoded).hexdigest()}


def _helpers(tool_bin, toolchain_manifest):
    platform = packages._consumer_platform()
    record = packages._toolchain(toolchain_manifest)
    if record.get("consumer_platform", platform) != platform:
        raise packages.PackageError("Trusted producer tools are for another platform")
    pins = packages._tool_hashes(record)
    suffix = ".exe" if platform == "windows" else ""
    binaries = {name: Path(tool_bin).absolute() / ("invader-" + name + suffix) for name in pins}
    for name, path in binaries.items():
        if packages.digest(packages._regular(path)) != pins[name]:
            raise packages.PackageError("Producer helper differs from reviewed manifest")
    return pins, binaries


def inventory_collection(*, prepared_collections, approved_catalog, stock_maps,
                         tool_bin, toolchain_manifest, expected_count=40):
    """Read-only identity gate; do not infer an approved map from a directory name."""
    packages._integer(expected_count, 1, 1000, "expected map count")
    pins, _ = _helpers(tool_bin, toolchain_manifest)
    stock = packages._stock_inputs(stock_maps)
    catalog = _json(approved_catalog)
    if (not isinstance(catalog, dict) or type(catalog.get("schema_version")) is not int or
            catalog["schema_version"] != 1 or
            catalog.get("profile") != "stock-xbox-ntsc" or not isinstance(catalog.get("maps"), list) or
            len(catalog["maps"]) != expected_count):
        raise packages.PackageError("Approved catalog profile or exact map count differs")
    approved = {}
    for item in catalog["maps"]:
        ident = item.get("id") if isinstance(item, dict) else None
        if (not isinstance(ident, str) or not packages.ID.fullmatch(ident) or
                ident in packages.STOCK_IDS or ident in approved or
                type(item.get("cache_version")) is not int or item["cache_version"] != 5 or
                type(item.get("scenario_type")) is not int or item["scenario_type"] != 1 or
                item.get("cache_build") != packages.NTSC_BUILD):
            raise packages.PackageError("Invalid or duplicate approved community identity")
        packages._sha(item.get("sha256"))
        packages._integer(item.get("file_bytes"), 2048, packages.MAX_CACHE_BYTES, "approved map bytes")
        approved[ident] = item
    maps, collections = {}, []
    for supplied in prepared_collections:
        root = Path(supplied).absolute()
        packages._tree(root / "stock-tags")
        build = _json(root / "build.json")
        if (not isinstance(build, dict) or build.get("profile") != "stock-xbox-ntsc" or
                build.get("invader_commit") != packages.INVADER_COMMIT or
                not isinstance(build.get("maps"), list) or not isinstance(build.get("tool_sha256"), dict) or
                any(build["tool_sha256"].get(name) != pin for name, pin in pins.items())):
            raise packages.PackageError("Prepared collection provenance differs from producer pins")
        source_stock = build.get("stock", {}).get("inputs", {})
        if not isinstance(source_stock, dict):
            raise packages.PackageError("Missing prepared stock identity")
        for entry in stock:
            recorded = source_stock.get(entry["name"], {})
            if any(recorded.get(key) != entry[key] for key in ("name", "sha256", "type")) or \
                    recorded.get("file_bytes") != entry["size"]:
                raise packages.PackageError("Prepared stock caches differ from the selected exact originals")
        collections.append({"path": str(root), "build_sha256": packages.digest(root / "build.json"),
                            "stock_tags": _tree_identity(root / "stock-tags")})
        for item in build["maps"]:
            ident = item.get("id") if isinstance(item, dict) else None
            if ident not in approved or ident in maps:
                raise packages.PackageError("Unexpected or duplicate prepared community map")
            folder = root / ident
            manifest = _json(folder / "manifest.json")
            cache = packages._cache(folder / "maps" / (ident + ".map"))
            selected = approved[ident]
            scenario = packages._path(manifest.get("compiled_scenario", ""))
            if (manifest.get("id") != ident or manifest.get("profile") != "stock-xbox-ntsc" or
                    scenario.rsplit("/", 1)[-1] != ident or cache["name"] != ident or cache["type"] != 1 or
                    cache["sha256"] != selected["sha256"] or cache["size"] != selected["file_bytes"] or
                    manifest.get("sha256") != cache["sha256"] or manifest.get("file_bytes") != cache["size"]):
                raise packages.PackageError("Prepared map differs from its approved exact output")
            maps[ident] = {"id": ident, "scenario": scenario, "collection": str(root),
                "prepared_tags": str(folder / "tags"), "prepared_data": str(folder / "data"),
                "patched_stock_tags": str(root / "stock-tags"),
                "expected_map": str(folder / "maps" / (ident + ".map")),
                "source_manifest_sha256": packages.digest(folder / "manifest.json"),
                "tags_identity": _tree_identity(folder / "tags"),
                "data_identity": _tree_identity(folder / "data"),
                "output": {key: cache[key] for key in ("size", "sha256", "declared_bytes", "tag_bytes")}}
    if set(maps) != set(approved):
        raise packages.PackageError("Prepared collections do not cover the exact approved catalog")
    return {"schema_version": 1, "scope": SCOPE, "map_count": len(maps),
            "approved_catalog": {"path": str(Path(approved_catalog).absolute()),
                                 "sha256": packages.digest(approved_catalog)},
            "stock_inputs": stock, "tool_sha256": pins, "collections": collections,
            "maps": [maps[ident] for ident in sorted(maps)]}


def asset_audit(manifest, original_stock_tags):
    """Inspect whole-file package decisions without mislabeling differing assets."""
    counts = Counter()
    byte_counts = Counter()
    stock = packages._tree(original_stock_tags)
    original_hashes = {(entry["size"], entry["sha256"]) for entry in stock.values()}
    literal_matches = []
    for entry in manifest["files"]:
        counts[entry["classification"]] += 1
        byte_counts[entry["classification"]] += entry["size"]
        if entry["kind"] == "literal" and (entry["size"], entry["sha256"]) in original_hashes:
            literal_matches.append({key: entry[key] for key in ("tree", "path", "size", "sha256")})
    return {"schema_version": 1, "id": manifest["id"], "scope": SCOPE,
            "classifications": {name: {"files": counts[name], "bytes": byte_counts[name]}
                                for name in sorted(packages.CLASSIFICATIONS)},
            "omitted_whole_stock_bytes": byte_counts["unchanged-stock"],
            "literal_payload_bytes": manifest["payload_bytes"],
            "literal_whole_stock_matches": literal_matches,
            # This complete table is the scope evidence; there are no chunk decisions.
            "files": manifest["files"]}


def _fresh_stock(binaries, stock_maps, destination, logs):
    destination.mkdir()
    logs.mkdir()
    for name in packages.STOCK_NAMES:
        result = subprocess.run([str(binaries["extract"]), "-t", str(destination),
                                 str(Path(stock_maps).absolute() / (name + ".map"))],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=180, shell=False, cwd=destination.parent)
        (logs / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise packages.PackageError("Fresh original-stock extraction failed: " + name)
    packages._tree(destination)


def verify_collection(*, prepared_collections, approved_catalog, stock_maps, tool_bin,
                      toolchain_manifest, destination, expected_count=40, progress=None):
    """Fresh isolated batch, preserving failed diagnostics and refusing all overwrites."""
    destination = Path(destination).absolute()
    prepared_collections = list(prepared_collections)
    packages._outside(destination, (*prepared_collections, stock_maps, tool_bin))
    arguments = dict(prepared_collections=prepared_collections, approved_catalog=approved_catalog,
                     stock_maps=stock_maps, tool_bin=tool_bin, toolchain_manifest=toolchain_manifest,
                     expected_count=expected_count)
    inventory = inventory_collection(**arguments)
    _, binaries = _helpers(tool_bin, toolchain_manifest)
    destination.mkdir(parents=True, exist_ok=False)
    _write_json(destination / "inventory.json", inventory)
    started = time.monotonic()
    report = {"schema_version": 1, "status": "failed", "scope": SCOPE, "maps": [],
              "consumer_platform": packages._consumer_platform(), "inventory": "inventory.json",
              "source_sha256": {str(Path(__file__).relative_to(Path(__file__).parents[1])): packages.digest(__file__),
                                  "tools/community_packages.py": packages.digest(packages.__file__)}}
    try:
        original = destination / "original-stock-tags"
        _fresh_stock(binaries, stock_maps, original, destination / "stock-extraction-logs")
        report["original_stock_tags"] = _tree_identity(original)
        output = destination / "maps"
        output.mkdir()
        for number, item in enumerate(inventory["maps"], 1):
            folder = output / item["id"]
            folder.mkdir()
            result = {"id": item["id"], "status": "failed", "approved_output": item["output"]}
            before = time.monotonic()
            try:
                package = folder / (item["id"] + ".hogpkg")
                manifest = packages.prepare_package(prepared_tags=item["prepared_tags"],
                    prepared_data=item["prepared_data"], original_stock_tags=original,
                    patched_stock_tags=item["patched_stock_tags"], stock_maps=stock_maps,
                    expected_map=item["expected_map"], scenario=item["scenario"],
                    toolchain_manifest=toolchain_manifest, destination=package)
                _write_json(folder / "manifest.json", manifest)
                audit = asset_audit(manifest, original)
                _write_json(folder / "asset-audit.json", audit)
                if audit["literal_whole_stock_matches"]:
                    raise packages.PackageError("A literal asset still equals a complete original stock tag")
                result.update(package_bytes=package.stat().st_size, package_sha256=packages.digest(package),
                              classifications=audit["classifications"],
                              omitted_whole_stock_bytes=audit["omitted_whole_stock_bytes"])
                rebuilt = folder / "reconstructed"
                provenance = packages.reconstruct_package(package=package, stock_maps=stock_maps,
                    tool_bin=tool_bin, toolchain_manifest=toolchain_manifest, destination=rebuilt)
                final = packages._cache(rebuilt / "maps" / (item["id"] + ".map"))
                if (provenance["status"] != "exact-reconstruction" or
                        {key: final[key] for key in item["output"]} != item["output"]):
                    shutil.rmtree(rebuilt)
                    raise packages.PackageError("Batch final map differs from the approved exact output")
                result.update(status="exact-reconstruction", reconstructed_sha256=final["sha256"],
                              reconstructed_bytes=final["size"])
            except (packages.PackageError, OSError, ValueError, subprocess.SubprocessError) as error:
                result["error"] = str(error)
            result["elapsed_seconds"] = round(time.monotonic() - before, 3)
            report["maps"].append(result)
            if progress:
                progress({"map": item["id"], "number": number, "total": expected_count,
                          "status": result["status"], "error": result.get("error")})
        report["verified_maps"] = sum(item["status"] == "exact-reconstruction" for item in report["maps"])
        report["failed_maps"] = expected_count - report["verified_maps"]
        report["package_bytes"] = sum(item.get("package_bytes", 0) for item in report["maps"])
        report["omitted_whole_stock_bytes_across_packages"] = sum(
            item.get("omitted_whole_stock_bytes", 0) for item in report["maps"])
        report["inputs_unchanged"] = inventory_collection(**arguments) == inventory
        report["original_stock_tags_unchanged"] = _tree_identity(original) == report["original_stock_tags"]
        report["status"] = ("exact-reconstruction-complete" if not report["failed_maps"] and
                             report["inputs_unchanged"] and report["original_stock_tags_unchanged"] else "failed")
    except (packages.PackageError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _write_json(destination / "audit.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "verify"))
    parser.add_argument("--prepared-collection", dest="prepared_collections", type=Path, action="append", required=True)
    for option in ("approved-catalog", "stock-maps", "tool-bin", "toolchain-manifest"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=40)
    parser.add_argument("--destination", type=Path)
    arguments = vars(parser.parse_args())
    command = arguments.pop("command")
    destination = arguments.pop("destination")
    if command == "verify" and not destination:
        parser.error("verify requires a fresh --destination")
    if command == "inventory" and destination:
        parser.error("inventory is read-only; omit --destination")
    try:
        if command == "inventory":
            print(json.dumps(inventory_collection(**arguments), indent=2))
        else:
            report = verify_collection(**arguments, destination=destination,
                progress=lambda record: print(json.dumps(record), flush=True))
            print(json.dumps({key: report.get(key) for key in
                ("status", "verified_maps", "failed_maps", "elapsed_seconds", "error")}))
            if report["status"] != "exact-reconstruction-complete":
                parser.exit(1)
    except (packages.PackageError, OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"community package batch: {error}\n")


if __name__ == "__main__":
    main()
