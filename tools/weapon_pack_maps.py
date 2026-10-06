#!/usr/bin/env python3
"""Build private Xbox map derivatives with a namespaced, explicit weapon pack.

Inputs are reviewed compatible HEK tag trees, never downloaded executables.
Additional palette references embed assets without placing new world objects.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import sys
import zlib

from community_maps import (Invader, MAX_CACHE_BYTES, NAME, NTSC_BUILD, ROOT,
                            TAG_ARENA_BYTES, cache_header, digest)
from weapon_pack_animation_audit import compare_clips, graph_records

PREFIX = "community/weapon_pack/"
# Pinned Invader src/hek/map.cpp: XBOX_REQUIRED_TAGS_ALL_2276 and
# XBOX_REQUIRED_TAGS_MP. These are compiler inputs outside scenario references.
XBOX_MP_REQUIRED_TAGS = (
    "globals/globals.globals", "ui/shell/bitmaps/white.bitmap",
    "ui/multiplayer_game_text.unicode_string_list", "ui/shell/multiplayer.ui_widget_collection",
)


def output_path(value: Path, inputs: list[Path]) -> Path:
    output = value.absolute()
    if any(parent.is_symlink() for parent in [output, *output.parents]):
        raise ValueError("Symlink output refused")
    output = output.resolve()
    if not output.is_relative_to(ROOT / "build") or output == ROOT / "build":
        raise ValueError("Output must be a fresh child of this repo's build/")
    if any(output == root or output.is_relative_to(root) for root in inputs):
        raise ValueError("Output cannot be inside an input tree")
    return output


def tag_path(value: str) -> str:
    value = value.replace("\\", "/")
    part = PurePosixPath(value)
    if (not value or part.is_absolute() or str(part) != value
            or any(p in (".", "..") for p in part.parts)
            or any(c in value for c in "\t\r\n:") or not part.suffix):
        raise ValueError(f"Unsafe tag path: {value}")
    return value


def resolve_tag(roots: list[Path], name: str) -> Path:
    name = tag_path(name)
    for root in roots:
        at = root
        for component in PurePosixPath(name).parts:
            at /= component
            if at.is_symlink():
                raise ValueError(f"Symlink tag dependency: {name}")
        if at.is_file():
            return at
    raise ValueError(f"Missing dependency: {name}")


def root_paths(values: list[Path]) -> list[Path]:
    roots = []
    for value in values:
        if value.is_symlink():
            raise ValueError("Symlink tag root")
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Tag root is not a directory")
        if root not in roots:
            roots.append(root)
    return roots


def root_args(roots: list[Path]) -> list[str | Path]:
    return [value for root in roots for value in ("-t", root)]


def closure(tool: Invader, roots: list[Path], names: list[str]) -> dict[str, Path]:
    found = {}
    for name in names:
        dependencies = tool.run("dependency", "-r", *root_args(roots), name).splitlines()
        for relative in [name, *dependencies]:
            relative = tag_path(relative.strip())
            found[relative] = resolve_tag(roots, relative)
    return dict(sorted(found.items()))


def copy_tags(files: dict[str, Path], destination: Path) -> dict[str, dict[str, str]]:
    records = {}
    for name, source in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        before = digest(source)
        shutil.copyfile(source, target)
        if digest(target) != before:
            raise RuntimeError("Copied dependency differs from its source")
        records[name] = {"path": str(source), "sha256": before}
    return records


def verify_inputs(records: dict[str, dict[str, str]]) -> None:
    for record in records.values():
        if digest(Path(record["path"])) != record["sha256"]:
            raise RuntimeError("Source changed during weapon pack build")


def playable_weapon(tool: Invader, roots: list[Path], name: str) -> dict[str, str]:
    if not name.endswith(".weapon"):
        raise ValueError("Selected weapon must end in .weapon")
    flags = {}
    for flag in ("must_be_readied", "doesnt_count_toward_maximum"):
        value = tool.run("edit", *root_args(roots[:1]), "-G", "weapon_flags." + flag, name)
        flags[flag] = value
        if value != "0":
            raise ValueError(f"Objective/noninventory weapon refused: {name}")
    fp = tool.run("edit", *root_args(roots[:1]), "-G", "first_person_model", name)
    animations = tool.run("edit", *root_args(roots[:1]), "-G", "first_person_animations", name)
    if (fp.startswith(".") or animations.startswith(".") or
            not fp.endswith(".model") or not animations.endswith(".model_animations")):
        raise ValueError(f"Weapon needs reviewed Xbox first-person assets: {name}")
    return {"label": tool.get(roots[0], name, "label"),
            "first_person_model": fp, "first_person_animations": animations, **flags}


def animation_labels(tool: Invader, tags: Path, graph: str) -> dict:
    if not graph.endswith(".model_animations"):
        raise ValueError("Base player needs an animation graph")
    parsed = graph_records(tags / graph)["seat_weapon_labels"]
    labels = {seat: parsed.get(seat, []) for seat in ("stand", "crouch")}
    if any(not values for values in labels.values()):
        raise ValueError("Base player lacks stand/crouch weapon animation labels")
    return {"animation_graph": graph,
            "seat_weapon_labels": {seat: sorted(values) for seat, values in labels.items()}}


def player_animation_labels(tool: Invader, tags: Path) -> dict:
    globals_tag = "globals/globals.globals"
    if tool.count(tags, globals_tag, "multiplayer_information") != 1:
        raise ValueError("Pack requires one reviewed multiplayer player definition")
    field = "multiplayer_information[0].unit"
    player = tag_path(tool.get(tags, globals_tag, field))
    if not player.endswith(".biped"):
        raise ValueError("Base player must resolve to a biped")
    graph = tag_path(tool.get(tags, player, "animation_graph"))
    return {"player": player, "globals_unit_field": field, **animation_labels(tool, tags, graph)}


def graph_metadata(tool: Invader, tags: Path, graph: str) -> dict:
    parsed = graph_records(tags / graph)
    clips = [{field: str(record["header_fields"][field])
              for field in ("node_count", "node_list_checksum")}
             for record in parsed["clips"].values()]
    return {"nodes": parsed["nodes"], "clips": clips}


def validate_graph_metadata(stock: dict, imported: dict, model_nodes: list[str]) -> None:
    if not stock["nodes"] or stock["nodes"] != imported["nodes"]:
        raise ValueError("Fiesta player graph differs from the stock skeleton hierarchy")
    if [node["name"] for node in imported["nodes"]] != model_nodes:
        raise ValueError("Fiesta graph node order differs from the stock player model")
    counts = {clip["node_count"] for clip in stock["clips"] + imported["clips"]}
    stock_checksums = {clip["node_list_checksum"] for clip in stock["clips"]}
    imported_checksums = {clip["node_list_checksum"] for clip in imported["clips"]}
    if (not stock["clips"] or not imported["clips"] or counts != {str(len(model_nodes))}
            or len(stock_checksums) != 1 or imported_checksums != stock_checksums):
        raise ValueError("Fiesta animation clips have incompatible node counts/checksums")


def fiesta_graph_compatibility(tool: Invader, base: Path, scratch: Path,
                              player: dict, imported_graph: str) -> dict:
    model = tag_path(tool.get(base, player["player"], "model"))
    stock = graph_metadata(tool, base, player["animation_graph"])
    imported = graph_metadata(tool, scratch, imported_graph)
    model_nodes = [tool.get(base, model, f"nodes[{index}].name")
                   for index in range(tool.count(base, model, "nodes"))]
    validate_graph_metadata(stock, imported, model_nodes)
    return {"stock_model": model, "stock_graph": player["animation_graph"],
            "imported_graph": imported_graph, "skeleton": imported["nodes"],
            "node_count": len(model_nodes), "stock_clip_count": len(stock["clips"]),
            "imported_clip_count": len(imported["clips"]),
            "node_list_checksum": imported["clips"][0]["node_list_checksum"],
            "shared_clip_audit": compare_clips(base / player["animation_graph"], scratch / imported_graph),
            "label_substitution": False}


def prove_reference_change(tool: Invader, tags: Path, name: str, field: str,
                           original: str, expected_sha: str, proof: Path) -> None:
    target = proof / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tags / name, target)
    tool.run("edit", "-t", proof, "-S", field, original, name)
    if digest(target) != expected_sha:
        raise RuntimeError("Fiesta player edit changed bytes beyond its approved reference")


def install_fiesta_player(tool: Invader, base: Path, pack: Path, player: dict,
                         mapped_graph: str, proof: Path) -> dict:
    derived = PREFIX + "player/cyborg.biped"
    if (base / derived).exists() or (pack / derived).exists():
        raise ValueError("Fiesta player identity collides with an existing dependency")
    target = pack / derived
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base / player["player"], target)
    tool.run("edit", "-t", pack, "-S", "animation_graph", mapped_graph, derived)
    prove_reference_change(tool, pack, derived, "animation_graph", player["animation_graph"],
                           digest(base / player["player"]), proof / "player")
    globals_tag = "globals/globals.globals"
    original_sha = digest(base / globals_tag)
    field = player["globals_unit_field"]
    tool.run("edit", "-t", base, "-S", field, derived, globals_tag)
    prove_reference_change(tool, base, globals_tag, field, player["player"],
                           original_sha, proof / "globals")
    return {"player": derived, "animation_graph": mapped_graph,
            "globals_unit_field": field, "original_multiplayer_player": player["player"],
            "globals_tag": globals_tag, "globals_sha256": digest(base / globals_tag),
            "player_sha256": digest(target), "reference_reverse_proofs": True,
            "scope": "This derivative's player only; ordinary caches and source definitions unchanged"}


def unsupported_labels(checks: dict, player: dict) -> dict:
    # Matches unit_set_or_test_seat_and_weapon_label: case-insensitive labels,
    # with 'unarmed' matching an empty animation weapon label.
    supported = player["seat_weapon_labels"]
    return {name: record["label"] for name, record in checks.items()
            if any(("" if record["label"] == "unarmed" else record["label"].casefold()) not in values
                   for values in supported.values())}


def namespace_mapping(names: dict, base_inputs: dict) -> dict[str, str]:
    mapping = {name: PREFIX + name for name in names}
    base_names = {name.casefold() for name in base_inputs}
    if any(name.casefold() in base_names for name in mapping.values()):
        raise ValueError("Base dependencies collide with the imported weapon namespace")
    if len({name.casefold() for name in mapping.values()}) != len(mapping):
        raise ValueError("Imported dependencies have case-insensitive identity collisions")
    return mapping


def script_inputs(data_root: Path, scenario: str) -> dict[str, Path]:
    root = root_paths([data_root])[0]
    names = []
    if (root / "global_scripts.hsc").exists():
        names.append("global_scripts.hsc")
    relative = str(PurePosixPath(scenario).parent / "scripts")
    folder = root / relative
    if folder.is_symlink():
        raise ValueError("Symlink script source directory refused")
    if folder.is_dir():
        names.extend(str(PurePosixPath(relative) / file.name) for file in sorted(folder.iterdir())
                     if file.suffix == ".hsc" and file.is_file())
    if not names:
        raise ValueError("No original HSC source files found")
    return {name: resolve_tag([root], name) for name in names}


def append_palette(tool: Invader, tags: Path, scenario: str, weapons: list[str]) -> int:
    count = tool.count(tags, scenario, "weapon_palette")
    if count + len(weapons) > 100:
        raise ValueError("Weapon palette would exceed the original Xbox limit")
    args = ["-t", tags, "-I", "weapon_palette", str(len(weapons)), "end"]
    for index, name in enumerate(weapons, count):
        args += ["-S", f"weapon_palette[{index}].name", name]
    tool.run("edit", *args, scenario)
    if tool.count(tags, scenario, "weapon_palette") != count + len(weapons):
        raise RuntimeError("Palette append count differs")
    for index, name in enumerate(weapons, count):
        actual = tool.get(tags, scenario, f"weapon_palette[{index}].name").replace("\\", "/")
        if actual != name:
            raise RuntimeError("Palette append identity differs")
    return count


def compiled_tag_paths(path: Path, retail_padding: bool = False) -> set[tuple[int, str]]:
    header = cache_header(path)
    if (header["declared_bytes"] > MAX_CACHE_BYTES or header["file_bytes"] > MAX_CACHE_BYTES
            or header["tag_bytes"] > TAG_ARENA_BYTES):
        raise ValueError("Compiled map exceeds native resource limits")
    if header["declared_bytes"] < 2048 + 16 or header["tag_bytes"] < 16:
        raise ValueError("Compiled map lacks a complete tag header")
    packed = path.read_bytes()
    if len(packed) == header["declared_bytes"]:
        data = packed
    else:
        inflater = zlib.decompressobj()
        tail = inflater.decompress(packed[2048:], header["declared_bytes"] - 2048 + 1)
        # Invader src/compress/compression.cpp pads Xbox streams to 4096 bytes.
        # Permit only that bounded zero padding after the complete zlib stream.
        padding = inflater.unused_data
        alignment = 2048 if retail_padding else 4096
        valid_padding = (not padding or
                         (len(padding) < alignment and len(packed) % alignment == 0 and not any(padding)))
        if (len(tail) != header["declared_bytes"] - 2048
                or not inflater.eof or inflater.unconsumed_tail or not valid_padding):
            raise ValueError("Invalid or oversized compressed cache")
        data = packed[:2048] + tail
    offset = struct.unpack_from("<I", data, 16)[0]
    if offset < 2048 or offset + header["tag_bytes"] > len(data):
        raise ValueError("Tag arena lies outside the map")
    def address(pointer: int, size: int = 1) -> int:
        result = offset + pointer - 0x803A6000
        if result < offset or result + size > offset + header["tag_bytes"]:
            raise ValueError("Tag pointer lies outside the tag arena")
        return result
    pointer, _, _, count = struct.unpack_from("<4I", data, offset)
    if count > 32767:
        raise ValueError("Tag count exceeds native iterator capacity")
    table = address(pointer, count * 32)
    result = set()
    for index in range(count):
        entry = struct.unpack_from("<8I", data, table + index * 32)
        at = address(entry[4])
        end = data.find(b"\0", at, min(at + 256, offset + header["tag_bytes"]))
        if end < 0:
            raise ValueError("Invalid compiled tag name")
        name = data[at:end].decode("ascii").replace("\\", "/")
        result.add((entry[0], name))
    return result


def build(args: argparse.Namespace) -> dict:
    bases, imports = root_paths(args.base_tags), root_paths(args.weapon_tags)
    scenario = tag_path(args.scenario)
    if not scenario.endswith(".scenario"):
        raise ValueError("Base scenario must end in .scenario")
    weapons = list(dict.fromkeys(tag_path(name) for name in args.weapon))
    base_weapons = list(dict.fromkeys(tag_path(name) for name in getattr(args, "base_weapon", [])))
    fiesta_graph = getattr(args, "fiesta_player_graph", None)
    if fiesta_graph:
        fiesta_graph = tag_path(fiesta_graph)
        if not fiesta_graph.endswith(".model_animations"):
            raise ValueError("Fiesta player graph must end in .model_animations")
    if not weapons or any(not name.endswith(".weapon") for name in [*weapons, *base_weapons]):
        raise ValueError("Select at least one explicit weapon")
    if (not NAME.fullmatch(args.name) or args.name.casefold() == Path(scenario).stem.casefold()):
        raise ValueError("Use a distinct safe cache identity")
    output = output_path(args.output, [*bases, *imports])
    output.mkdir(parents=True, exist_ok=False)
    logs, base, scratch, pack, maps = [output / name for name in ("logs", "base-tags", "scratch-tags", "pack-tags", "maps")]
    for folder in (logs, base, scratch, pack, maps):
        folder.mkdir()
    report = {"schema_version": 1, "status": "preparing", "namespace": PREFIX,
              "base_roots": list(map(str, bases)), "weapon_roots": list(map(str, imports)),
              "base_scenario": scenario, "selected_weapons": weapons, "base_palette_weapons": base_weapons,
              "tool_sha256": digest(Path(__file__)), "native_runtime_validation": "pending",
              "scope": "Namespaced content derivative; source maps, stock definitions and placements are preserved; no installation or publication"}
    manifest = output / "manifest.json"
    def save():
        manifest.write_text(json.dumps(report, indent=2) + "\n")
    save()
    try:
        tool = Invader(args.invader_bin, args.invader_manifest, logs)
        report["invader_commit"] = tool.commit
        report["helper_sha256"] = tool.provenance
        report["invader_manifest_sha256"] = digest(args.invader_manifest)
        report["compiler_required_tags"] = list(XBOX_MP_REQUIRED_TAGS)
        report["base_inputs"] = copy_tags(closure(tool, bases, [scenario, *XBOX_MP_REQUIRED_TAGS, *base_weapons]), base)
        report["weapon_inputs"] = copy_tags(closure(tool, imports, weapons + ([fiesta_graph] if fiesta_graph else [])), scratch)
        report["playable_checks"] = {name: playable_weapon(tool, [scratch], name) for name in weapons}
        report["base_player_animation_checks"] = player_animation_labels(tool, base)
        effective_player = report["base_player_animation_checks"]
        if fiesta_graph:
            report["fiesta_graph_compatibility"] = fiesta_graph_compatibility(
                tool, base, scratch, effective_player, fiesta_graph)
            effective_player = animation_labels(tool, scratch, fiesta_graph)
            report["fiesta_player_animation_checks"] = effective_player
            report["scope"] = "Hidden Fiesta-only content derivative with compatible reviewed player graph; source caches and world placements preserved"
        unsupported = unsupported_labels(report["playable_checks"], effective_player)
        report["base_playable_checks"] = {name: playable_weapon(tool, [base], name) for name in base_weapons}
        unsupported.update(unsupported_labels(report["base_playable_checks"], effective_player))
        report["unsupported_weapon_labels"] = unsupported
        if unsupported:
            raise ValueError("Selected weapons need reviewed base player animations: " +
                             ", ".join(f"{name} (label {label!r})" for name, label in unsupported.items()))
        if tool.count(base, scenario, "encounters"):
            raise ValueError("Combat-AI maps require their own reviewed conversion profile")
        scripts = tool.count(base, scenario, "scripts")
        inline_source = tool.count(base, scenario, "source_files")
        if scripts and not inline_source and not args.data:
            raise ValueError("Compiled-only scripts need their original reviewed HSC source")
        if args.data:
            if not scripts or inline_source:
                raise ValueError("--data is only for compiled-only scripts missing their original HSC source")
            data_copy = output / "data"
            data_copy.mkdir()
            report["script_inputs"] = copy_tags(script_inputs(args.data, scenario), data_copy)
        mapping = namespace_mapping(report["weapon_inputs"], report["base_inputs"])
        args_copy = ["-t", scratch, "-M", "copy"]
        for before, after in mapping.items():
            args_copy += ["-T", before, after]
        tool.run("refactor", *args_copy)
        copy_tags({after: resolve_tag([scratch], after) for after in mapping.values()}, pack)
        # Original closure remains untouched; only copies receive new identities.
        for name, record in report["weapon_inputs"].items():
            if digest(scratch / name) != record["sha256"]:
                raise RuntimeError("Refactoring changed an original source copy")
        if fiesta_graph:
            report["fiesta_player_override"] = install_fiesta_player(
                tool, base, pack, report["base_player_animation_checks"], mapping[fiesta_graph],
                output / "player-reference-proof-tags")
        renamed = str(PurePosixPath(scenario).with_name(args.name + ".scenario"))
        if (base / renamed).exists():
            raise ValueError("Derivative scenario identity collides with a base dependency")
        shutil.copyfile(base / scenario, base / renamed)
        counts = {key: tool.count(base, renamed, key) for key in
                  ("weapons", "netgame_equipment", "player_starting_locations", "netgame_flags", "player_starting_profile", "scripts", "globals")}
        imported = [mapping[name] for name in weapons]
        appended = [*imported, *base_weapons]
        old_count = append_palette(tool, base, renamed, appended)
        if any(tool.count(base, renamed, key) != count for key, count in counts.items()):
            raise RuntimeError("Palette edit changed base scenario counts")
        # Erasing the appended palette must produce the original scenario bytes.
        reverse = output / "reverse-proof-tags"
        reverse.mkdir()
        target = reverse / renamed
        target.parent.mkdir(parents=True)
        shutil.copyfile(base / renamed, target)
        tool.run("edit", "-t", reverse, "-E", f"weapon_palette[{old_count}-{old_count + len(appended) - 1}]", renamed)
        if digest(target) != digest(base / scenario):
            raise RuntimeError("Scenario differs beyond the appended weapon palette")
        report.update(derivative_scenario=renamed, imported_weapons=imported,
                      original_palette_count=old_count, appended_palette_count=len(appended),
                      base_scenario_counts=counts, scenario_reverse_proof=True,
                      namespaced_tags={name: digest(pack / name) for name in mapping.values()},
                      mapping=mapping)
        resolved = closure(tool, [pack], imported)
        if any(not name.startswith(PREFIX) for name in resolved):
            raise RuntimeError("Imported weapon still references an unnamespaced dependency")
        binary = tool.binary / "invader-build"
        compiler = {"path": str(binary), "sha256": digest(binary)}
        if args.reviewed_build_manifest:
            reviewed = json.loads(args.reviewed_build_manifest.read_text())
            binary = Path(reviewed["binary"]).resolve(strict=True)
            if reviewed["original_invader_commit"] != tool.commit or digest(binary) != reviewed["binary_sha256"]:
                raise ValueError("Reviewed builder manifest/hash differs")
            compiler = {"path": str(binary), "sha256": digest(binary),
                        "reviewed_manifest_sha256": digest(args.reviewed_build_manifest)}
        # This port permits larger caches than retail Xbox multiplayer (47 MiB).
        # The reviewed community compiler profile uses -E; enforce this port's
        # smaller explicit 128 MiB/22 MiB limits on the resulting cache below.
        command = [str(binary), "-g", "xbox-ntsc", "-E", "-T", str(TAG_ARENA_BYTES),
                   "-t", str(base), "-t", str(pack), "-m", str(maps)]
        if args.data:
            command += ["-d", str(data_copy), "-S", "data"]
        else:
            command += ["-S", "tags"]
        command += [renamed.removesuffix(".scenario")]
        report.update(status="compiling", compiler=compiler, compile_command=command)
        save()
        result = subprocess.run(command, capture_output=True, text=True)
        (logs / "compile.log").write_text(result.stdout + result.stderr)
        report["compile_exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError("Compilation failed; inspect logs/compile.log")
        cache = maps / (args.name + ".map")
        header = cache_header(cache)
        if header["version"] != 5 or header["build"] != NTSC_BUILD or header["type"] != 1:
            raise ValueError("Compiled output is not Xbox NTSC v5 multiplayer data")
        paths = compiled_tag_paths(cache)
        if any((0x77656170, name.removesuffix(".weapon")) not in paths for name in imported):
            raise RuntimeError("An appended weapon was not embedded in the compiled cache")
        if any((0x77656170, name.removesuffix(".weapon")) not in paths for name in base_weapons):
            raise RuntimeError("An explicit base arsenal weapon was not embedded in the compiled cache")
        if fiesta_graph:
            override = report["fiesta_player_override"]
            if ((0x62697064, override["player"].removesuffix(".biped")) not in paths or
                    (0x616e7472, override["animation_graph"].removesuffix(".model_animations")) not in paths):
                raise RuntimeError("The scoped Fiesta player/graph was not embedded")
        for name, record in report["base_inputs"].items():
            override = report.get("fiesta_player_override", {})
            if name == override.get("globals_tag"):
                if digest(base / name) != override["globals_sha256"]:
                    raise RuntimeError("Fiesta globals changed after the approved player reference")
                continue
            if digest(base / name) != record["sha256"]:
                raise RuntimeError("A base source definition changed")
        verify_inputs(report["base_inputs"])
        verify_inputs(report["weapon_inputs"])
        if args.data:
            verify_inputs(report["script_inputs"])
            for name, record in report["script_inputs"].items():
                if digest(data_copy / name) != record["sha256"]:
                    raise RuntimeError("A copied HSC source changed")
        report.update(status="built; native runtime and multiplayer validation pending",
                      map=header, output_map=str(cache), source_inputs_unchanged=True,
                      base_definitions_unchanged=not bool(fiesta_graph),
                      base_definitions_unchanged_except=(["globals/globals.globals"] if fiesta_graph else []),
                      compiled_selected_weapons_verified=True,
                      resource_limits={"cache_bytes": MAX_CACHE_BYTES, "tag_arena_bytes": TAG_ARENA_BYTES})
        save()
        return report
    except Exception as error:
        report.update(status="failed", error=str(error))
        save()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-tags", type=Path, action="append", required=True, help="Ordered compatible base tag roots")
    parser.add_argument("--weapon-tags", type=Path, action="append", required=True, help="Ordered reviewed Xbox weapon tag roots")
    parser.add_argument("--scenario", required=True, help="Base scenario path including .scenario")
    parser.add_argument("--weapon", action="append", required=True, help="Explicit playable .weapon; repeat to select a pack")
    parser.add_argument("--base-weapon", action="append", default=[], help="Explicit original base .weapon to retain in the derivative palette")
    parser.add_argument("--name", required=True, help="Unique derivative cache identity")
    parser.add_argument("--output", type=Path, required=True, help="Fresh ignored build/ directory")
    parser.add_argument("--invader-bin", type=Path, required=True)
    parser.add_argument("--invader-manifest", type=Path, required=True)
    parser.add_argument("--reviewed-build-manifest", type=Path)
    parser.add_argument("--data", type=Path, help="Original reviewed HSC data root, if scripts need it")
    parser.add_argument("--fiesta-player-graph", help="Explicit reviewed compatible .model_animations, scoped to this Fiesta-only derivative")
    try:
        report = build(parser.parse_args())
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in ("status", "output_map", "map", "appended_palette_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
