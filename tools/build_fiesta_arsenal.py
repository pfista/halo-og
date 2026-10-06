#!/usr/bin/env python3
"""Prepare original Xbox sources and compile hidden full-Fiesta stock variants.

Generated outputs remain private until explicitly installed by the app workflow.
Original maps and authored source tags are never overwritten.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from community_maps import Invader, NTSC_BUILD, cache_header, digest, prepare_stock
from weapon_pack_maps import (PREFIX, ROOT, build, compiled_tag_paths, output_path,
                              playable_weapon, unsupported_labels, closure, copy_tags,
                              resolve_tag, verify_inputs, prove_reference_change)

STOCK_MAPS = ("beavercreek", "sidewinder", "damnation", "ratrace", "prisoner",
              "hangemhigh", "chillout", "carousel", "boardingaction", "bloodgulch",
              "wizard", "putput", "longest")
GENERATION = 1
PLAYER_GRAPH = "characters/cyborg/cyborg.model_animations"
IMPORTS = (
    "vehicles/scorpion/scorpion cannon.weapon", "weapons/smg/smg.weapon",
    "weapons/beam rifle/beam rifle.weapon", "weapons/magnum/magnum.weapon",
    "weapons/excavator/excavator.weapon",
    "community/digsite_compat/weapons/flamethrower/flamethrower.weapon",
    "weapons/machete/machete.weapon", "vehicles/rwarthog/rwarthog_gun.weapon",
    "weapons/grenade launcher/assault rifle.weapon", "weapons/gravity_wrench/gravity_wrench.weapon",
    "vehicles/banshee/mp_banshee gun.weapon", "weapons/plasma_cannon/plasma_cannon.weapon",
    "weapons/chaingun/chaingun.weapon", "weapons/speargun/speargun.weapon",
    "weapons/bolt action rifle/bolt action rifle.weapon", "weapons/battle rifle/battle rifle.weapon",
    "weapons/space luger/space luger.weapon", "weapons/missile launcher/missile launcher.weapon",
    "weapons/sentinel beam/sentinel beam.weapon",
    "weapons/needler/mp_needler.weapon",
    "weapons/rocket launcher/rocket launcher longshot.weapon",
    "weapons/rocket launcher/rocket launcher empty.weapon",
    "weapons/ball/skull.weapon",
)
UNCUT = ("weapons/smg/smg", "weapons/grenade launcher/assault rifle", "weapons/chaingun/chaingun",
         "weapons/excavator/excavator", "weapons/gravity_wrench/gravity_wrench", "weapons/machete/machete",
         "weapons/speargun/speargun", "weapons/space luger/space luger", "weapons/missile launcher/missile launcher")
RETAIL = ("weapons/assault rifle/assault rifle", "weapons/needler/needler", "weapons/pistol/pistol",
          "weapons/plasma pistol/plasma pistol", "weapons/plasma rifle/plasma rifle",
          "weapons/rocket launcher/rocket launcher", "weapons/shotgun/shotgun", "weapons/sniper rifle/sniper rifle")
CANONICAL_FLAME = "weapons/flamethrower/flamethrower"
IMPORTED_FLAME = PREFIX + "community/digsite_compat/weapons/flamethrower/flamethrower"
EXPECTED_WEAPON_SHA = "2856504cbd257e1b18c273caa64237fbfe77dc77d22cce1a7fa0a0abfc53f71f"


def physical_name(logical: str) -> str:
    if not re.fullmatch(r"[a-z0-9_ -]{1,31}", logical):
        raise ValueError("Logical map must be a lowercase safe ASCII basename")
    return ("_fiesta_" + logical if len(logical) <= 23 else
            "_fiestah_" + hashlib.sha256(logical.encode("ascii")).hexdigest()[:16])


def weapon_list_bytes() -> bytes:
    names = [*RETAIL, CANONICAL_FLAME,
             *(PREFIX + name.removesuffix(".weapon") for name in IMPORTS
               if PREFIX + name.removesuffix(".weapon") != IMPORTED_FLAME)]
    return ("\n".join(sorted(name.lower().replace("/", "\\") for name in names)) + "\n").encode("ascii")


def save(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2) + "\n")


def prepare(args: argparse.Namespace) -> dict:
    source = args.stock_maps.resolve(strict=True)
    output = output_path(args.output, [source])
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "logs"
    logs.mkdir()
    tool = Invader(args.invader_bin, args.invader_manifest, logs)
    report = {"schema_version": 1, "status": "preparing", "source_maps": str(source),
              "tool_sha256": digest(Path(__file__)), "invader_commit": tool.commit,
              "helper_sha256": tool.provenance, "maps": {}}
    manifest = output / "manifest.json"
    save(manifest, report)
    try:
        for name in STOCK_MAPS:
            path = source / (name + ".map")
            header = cache_header(path)
            if header["version"] != 5 or header["build"] != NTSC_BUILD or header["type"] != 1:
                raise ValueError("Use complete original Xbox NTSC2276 multiplayer sources")
            scenarios = [tag for kind, tag in compiled_tag_paths(path, retail_padding=True) if kind == 0x73636e72]
            if len(scenarios) != 1:
                raise ValueError("Original stock map must contain exactly one scenario")
            report["maps"][name] = {"source": str(path), "header": header,
                                    "scenario": scenarios[0] + ".scenario"}
        tags = output / "stock-tags"
        report["stock_preparation"] = prepare_stock(tool, source, tags)
        # Without -O, shared stock definitions already audited above take
        # precedence; each remaining map adds its own geometry/scenario closure.
        for name in STOCK_MAPS:
            if name != "bloodgulch":
                tool.run("extract", "-t", tags, source / (name + ".map"))
        for record in report["maps"].values():
            if not (tags / record["scenario"]).is_file():
                raise RuntimeError("An original stock scenario was not extracted")
            if digest(Path(record["source"])) != record["header"]["sha256"]:
                raise RuntimeError("Original stock map changed during extraction")
        report.update(status="prepared", tag_root=str(tags), source_maps_unchanged=True,
                      tag_sha256={tag.relative_to(tags).as_posix(): digest(tag)
                                  for tag in sorted(tags.rglob("*")) if tag.is_file()})
        save(manifest, report)
        return report
    except Exception as error:
        report.update(status="failed", error=str(error))
        save(manifest, report)
        raise


def eligible_pool(tool: Invader, report: dict) -> list[str]:
    base, pack = Path(report["compile_command"][report["compile_command"].index("-t") + 1]), None
    # Compiled identities define the inventory; read their exact copied sources.
    pack = Path(report["output_map"]).parents[1] / "pack-tags"
    candidates = sorted(tag for kind, tag in compiled_tag_paths(Path(report["output_map"])) if kind == 0x77656170)
    labels = report["fiesta_player_animation_checks"]
    eligible = set()
    for name in candidates:
        root = base if (base / (name + ".weapon")).is_file() else pack
        try:
            check = playable_weapon(tool, [root], name + ".weapon")
        except ValueError:
            continue
        if not unsupported_labels({name: check}, labels):
            eligible.add(name)
    # Scoped private-player caches prefer their global imported definitions over
    # authored same-path copies; the reviewed canonical flame alias wins.
    result = {name for name in eligible
              if name.startswith(PREFIX) or PREFIX + name not in eligible}
    if CANONICAL_FLAME in eligible:
        result.discard(IMPORTED_FLAME)
    return sorted(name.lower().replace("/", "\\") for name in result)


def prepare_installed(args: argparse.Namespace) -> dict:
    inventory = json.loads(args.inventory.read_text())
    stock = json.loads((args.prepared / "manifest.json").read_text())
    if stock.get("status") != "prepared":
        raise ValueError("Reviewed stock preparation is incomplete")
    source_tags = Path(stock["tag_root"])
    for name, sha in stock["tag_sha256"].items():
        if digest(source_tags / name) != sha:
            raise ValueError("Prepared stock tag changed")
    selected = set(args.map or [])
    entries = [record for record in inventory["maps"]
               if not selected or record["logical_map"] in selected]
    if selected - {record["logical_map"] for record in entries}:
        raise ValueError("Requested map is absent from the normal-resolver inventory")
    for record in entries:
        physical_name(record["logical_map"])
        if digest(Path(record["path"])) != record["base_sha256"]:
            raise ValueError("Installed map differs from its frozen resolver inventory")
    output = output_path(args.output, [source_tags, *(Path(item["path"]) for item in entries)])
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "status": "preparing", "maps": {}, "failures": {},
              "inventory_sha256": digest(args.inventory), "inventory_path": str(args.inventory),
              "stock_manifest_sha256": digest(args.prepared / "manifest.json"),
              "tool_sha256": digest(Path(__file__))}

    def extract(record: dict) -> tuple[str, dict]:
        logical, source = record["logical_map"], Path(record["path"])
        header = cache_header(source)
        if header["version"] != 5 or header["build"] != NTSC_BUILD or header["type"] != 1:
            raise ValueError("Installed map needs Xbox NTSC2276 multiplayer data")
        scenarios = [tag for kind, tag in compiled_tag_paths(source, retail_padding=bool(record.get("stock")))
                     if kind == 0x73636e72]
        if len(scenarios) != 1:
            raise ValueError("Installed map needs exactly one scenario")
        if record.get("stock"):
            original = stock["maps"][logical]
            if original["header"]["sha256"] != header["sha256"]:
                raise ValueError("Prepared stock map does not match selected installed original")
            return logical, {**original, "tag_roots": [str(source_tags)],
                             "tag_sha256": stock["tag_sha256"]}
        private = output / "sources" / logical
        private.mkdir(parents=True)
        logs, tags = private / "logs", private / "tags"
        logs.mkdir()
        tags.mkdir()
        tool = Invader(args.invader_bin, args.invader_manifest, logs)
        tool.run("extract", "-t", tags, source)
        scenario = scenarios[0] + ".scenario"
        if not (tags / scenario).is_file() or digest(source) != header["sha256"]:
            raise RuntimeError("Installed original changed or scenario extraction failed")
        return logical, {"source": str(source), "header": header, "scenario": scenario,
                         "tag_roots": [str(tags), str(source_tags)],
                         "tag_sha256": {tag.relative_to(tags).as_posix(): digest(tag)
                                        for tag in sorted(tags.rglob("*")) if tag.is_file()},
                         "extraction_helpers": tool.provenance, "invader_commit": tool.commit,
                         "stock_fallback_manifest_sha256": digest(args.prepared / "manifest.json")}

    save(output / "manifest.json", report)
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(extract, entry): entry["logical_map"] for entry in entries}
        for future in as_completed(futures):
            name = futures[future]
            try:
                _, record = future.result()
                report["maps"][name] = record
            except Exception as error:
                report["failures"][name] = str(error)
            save(output / "manifest.json", report)
    report["status"] = "prepared" if not report["failures"] else "failed"
    save(output / "manifest.json", report)
    if report["failures"]:
        raise RuntimeError("Installed source extraction failed; inspect manifest.json")
    return report


def prepare_extra_weapons(args: argparse.Namespace) -> dict:
    if len(args.source_root) != len(args.weapon):
        raise ValueError("Pair each exact extracted source root with one selected weapon")
    sources = [path.resolve(strict=True) for path in args.source_root]
    output = output_path(args.output, sources)
    output.mkdir(parents=True, exist_ok=False)
    tags = output / "tags"
    tags.mkdir()
    report = {"schema_version": 1, "status": "preparing", "maps": {},
              "tool_sha256": digest(Path(__file__)), "tag_root": str(tags), "weapons": {}}
    save(output / "manifest.json", report)
    for index, (source, weapon) in enumerate(zip(sources, args.weapon)):
        private = output / ("source-" + str(index))
        logs = output / ("logs-" + str(index))
        logs.mkdir()
        private.mkdir()
        tool = Invader(args.invader_bin, args.invader_manifest, logs)
        inputs = copy_tags(closure(tool, [source], [weapon]), private)
        # Keep the reviewed weapon identity, but isolate all its dependencies
        # from Digsite/base overlays so that closure resolution preserves the
        # exact authored variant assets and projectile/damage definitions.
        mapping = {name: "community/weapon_variant/" + str(index) + "/" + name
                   for name in inputs if name != weapon}
        arguments = ["-t", private, "-M", "move"]
        for before, after in mapping.items():
            arguments += ["-T", before, after]
        if mapping:
            tool.run("refactor", *arguments)
        for name in [weapon, *mapping.values()]:
            if (tags / name).exists():
                raise ValueError("Extra weapon identities collide")
        outputs = copy_tags({name: resolve_tag([private], name)
                             for name in [weapon, *mapping.values()]}, tags)
        actual = closure(tool, [tags], [weapon])
        if set(actual) != {weapon, *mapping.values()}:
            raise RuntimeError("Extra variant dependency isolation is incomplete")
        verify_inputs(inputs)
        report["weapons"][weapon] = {"source_root": str(source), "original_inputs": inputs,
                                      "isolated_dependencies": mapping, "generated_inputs": outputs,
                                      "source_inputs_unchanged": True, "helpers": tool.provenance}
        save(output / "manifest.json", report)
    report.update(status="prepared", tag_sha256={tag.relative_to(tags).as_posix(): digest(tag)
                                                for tag in sorted(tags.rglob("*")) if tag.is_file()})
    save(output / "manifest.json", report)
    return report


def frozen_base_roots(prepared: dict, names: list[str]) -> set[Path]:
    frozen = {}
    for record in prepared["maps"].values():
        root = Path(record.get("tag_roots", [prepared.get("tag_root")])[0]).resolve(strict=True)
        hashes = record.get("tag_sha256", prepared.get("tag_sha256", {}))
        if root in frozen and frozen[root] != hashes:
            raise ValueError("Prepared roots have conflicting frozen source hashes")
        frozen[root] = hashes
    roots = {Path(value).resolve(strict=True) for name in names
             for value in prepared["maps"][name].get("tag_roots", [prepared.get("tag_root")])}
    for root in roots:
        if root not in frozen or not frozen[root]:
            raise ValueError("A fallback source root lacks frozen extraction hashes")
        for relative, sha in frozen[root].items():
            source = resolve_tag([root], relative)
            if digest(source) != sha:
                raise ValueError("Prepared primary/fallback source differs from its frozen extraction")
    return roots


def prove_compiled_multiplayer_player(tool: Invader, original: Path, derived: Path,
                                     report: dict, directory: Path) -> dict:
    baseline, candidate = directory / "original", directory / "derived"
    baseline.mkdir(parents=True)
    candidate.mkdir()
    globals_tag, field = "globals/globals.globals", "multiplayer_information[0].unit"
    override = report["fiesta_player_override"]
    tool.run("extract", "-t", baseline, "-s", globals_tag, original)
    original_player = tool.get(baseline, globals_tag, field).replace("\\", "/")
    if original_player != override["original_multiplayer_player"]:
        raise RuntimeError("Prepared multiplayer player differs from the original cache")
    tool.run("extract", "-t", baseline, "-s", original_player, original)
    tool.run("extract", "-t", candidate, "-s", globals_tag, "-s", override["player"], derived)
    if tool.get(candidate, globals_tag, field).replace("\\", "/") != override["player"]:
        raise RuntimeError("Compiled multiplayer player does not select the compatible scoped graph")
    original_graph = tool.get(baseline, original_player, "animation_graph")
    original_sha = digest(baseline / original_player)
    # Fresh extraction removes cache addresses/datums. Reversing the one graph
    # reference must reproduce every original multiplayer biped HEK byte,
    # including physics, vitality, flags, weapons, collision and animation data.
    prove_reference_change(tool, candidate, override["player"], "animation_graph",
                           original_graph, original_sha, directory / "reverse-proof")
    return {"original_multiplayer_player": original_player, "compiled_player": override["player"],
            "original_extracted_biped_sha256": original_sha,
            "all_other_compiled_player_bytes_equal": True,
            "compiled_multiplayer_globals_reference_verified": True,
            "allowed_difference": "animation_graph", "proof_directory": str(directory)}


def compile_variants(args: argparse.Namespace) -> dict:
    prepared = json.loads((args.prepared / "manifest.json").read_text())
    if prepared.get("status") != "prepared":
        raise ValueError("Stock preparation is incomplete")
    names = list(dict.fromkeys(args.map or prepared["maps"]))
    if any(name not in prepared["maps"] for name in names):
        raise ValueError("Select only maps in the frozen reviewed source inventory")
    for logical in names:
        physical_name(logical)
    roots = frozen_base_roots(prepared, names)
    output = output_path(args.output, [*roots, *args.weapon_tags])
    output.mkdir(parents=True, exist_ok=False)
    library = output / "maps/arsenal/v1"
    library.mkdir(parents=True)
    canonical = weapon_list_bytes()
    weapon_sha = hashlib.sha256(canonical).hexdigest()
    if weapon_sha != EXPECTED_WEAPON_SHA:
        raise ValueError("The v1 global weapon list changed; review a new generation")
    (library / "global-weapons.txt").write_bytes(canonical)
    catalog = {"schema_version": 1, "generation": GENERATION, "weapon_list_sha256": weapon_sha,
               "weapon_list": canonical.decode("ascii").splitlines(),
               "uncut_weapons": sorted((PREFIX + name).replace("/", "\\") for name in UNCUT),
               "status": "building", "prepared_manifest_sha256": digest(args.prepared / "manifest.json"),
               "maps": {}, "failures": {}}
    save(output / "catalog.json", catalog)
    def compile_one(logical: str) -> tuple[str, dict]:
            original = prepared["maps"][logical]
            if digest(Path(original["source"])) != original["header"]["sha256"]:
                raise ValueError("Original stock cache differs from the prepared base digest")
            physical = physical_name(logical)
            variant = output / "variants" / physical
            bases = [Path(value) for value in original.get("tag_roots", [prepared.get("tag_root")])]
            data = args.digsite_data if logical == "chillout_digsite" else None
            if data:
                preflight = output / "script-preflight" / physical
                preflight.mkdir(parents=True)
                reader = Invader(args.invader_bin, args.invader_manifest, preflight)
                if (not reader.count(bases[0], original["scenario"], "scripts") or
                        reader.count(bases[0], original["scenario"], "source_files")):
                    data = None
            report = build(argparse.Namespace(base_tags=bases, weapon_tags=args.weapon_tags,
                scenario=original["scenario"], weapon=list(IMPORTS),
                base_weapon=[name + ".weapon" for name in (*RETAIL, CANONICAL_FLAME)], name=physical, output=variant,
                invader_bin=args.invader_bin, invader_manifest=args.invader_manifest,
                reviewed_build_manifest=args.reviewed_build_manifest, data=data,
                fiesta_player_graph=PLAYER_GRAPH))
            eligibility_logs = variant / "eligibility-logs"
            eligibility_logs.mkdir()
            tool = Invader(args.invader_bin, args.invader_manifest, eligibility_logs)
            player_proof = prove_compiled_multiplayer_player(tool, Path(original["source"]),
                Path(report["output_map"]), report, variant / "compiled-player-proof")
            save(variant / "compiled-player-proof.json", player_proof)
            actual = eligible_pool(tool, report)
            if ("\n".join(actual) + "\n").encode("ascii") != canonical:
                raise RuntimeError("Compiled eligible pool differs from the full v1 global arsenal")
            if not set(catalog["uncut_weapons"]).issubset(actual):
                raise RuntimeError("A recovered Uncut weapon is absent or incompatible")
            source = Path(report["output_map"])
            target = library / (physical + ".map")
            shutil.copyfile(source, target)
            if digest(target) != report["map"]["sha256"]:
                raise RuntimeError("Hidden cache copy differs from the compiled derivative")
            flat = {"schema_version": 1, "generation": GENERATION,
                    "logical_map": logical, "physical_map": physical,
                    "cache_sha256": report["map"]["sha256"], "base_sha256": original["header"]["sha256"],
                    "weapon_list_sha256": weapon_sha, "cache_file_bytes": report["map"]["file_bytes"],
                    "cache_declared_bytes": report["map"]["declared_bytes"]}
            save(library / (physical + ".json"), flat)
            return logical, {**flat, "authoring_manifest": str(variant / "manifest.json"),
                             "compiled_player_proof": player_proof, "eligible_weapons": actual,
                             "uncut_count": len(UNCUT), "all_count": len(actual)}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(compile_one, name): name for name in names}
        for future in as_completed(futures):
            logical = futures[future]
            try:
                _, record = future.result()
                catalog["maps"][logical] = record
            except Exception as error:
                catalog["failures"][logical] = str(error)
            save(output / "catalog.json", catalog)
    catalog["status"] = "built; native validation and installation pending" if not catalog["failures"] else "failed"
    save(output / "catalog.json", catalog)
    if catalog["failures"]:
        raise RuntimeError("One or more arsenal variants failed; inspect catalog.json")
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("prepare")
    source.add_argument("--stock-maps", type=Path, required=True)
    installed = commands.add_parser("prepare-installed")
    installed.add_argument("--inventory", type=Path, required=True)
    installed.add_argument("--prepared", type=Path, required=True)
    installed.add_argument("--map", action="append")
    extras = commands.add_parser("prepare-extra-weapons")
    extras.add_argument("--source-root", type=Path, action="append", required=True)
    extras.add_argument("--weapon", action="append", required=True)
    compile_parser = commands.add_parser("build")
    compile_parser.add_argument("--prepared", type=Path, required=True)
    compile_parser.add_argument("--weapon-tags", type=Path, action="append", required=True)
    compile_parser.add_argument("--map", action="append")
    compile_parser.add_argument("--reviewed-build-manifest", type=Path)
    compile_parser.add_argument("--digsite-data", type=Path)
    for command in (installed, compile_parser):
        command.add_argument("--jobs", type=int, choices=range(1, 5), default=2)
    for command in (source, installed, extras, compile_parser):
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--invader-bin", type=Path, required=True)
        command.add_argument("--invader-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (prepare(args) if args.command == "prepare" else
                  prepare_installed(args) if args.command == "prepare-installed" else
                  prepare_extra_weapons(args) if args.command == "prepare-extra-weapons" else compile_variants(args))
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "maps": list(result["maps"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
