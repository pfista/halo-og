#!/usr/bin/env python3
"""Development helpers for community content conversion, separate from retail gameplay.

Keep original extracted tags immutable. Changes belong to copied tags or fresh
overlays, with source hashes and explicit stock/community provenance. This is an
authoring assistant, not an automatic guarantee of Xbox or multiplayer fidelity.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from community_maps import (Invader, MAX_CACHE_BYTES, NAME, NTSC_BUILD, ROOT,
                            SCENARIO, TAG_ARENA_BYTES, cache_header, digest,
                            output_directory, safe_tag)

SCHEMA = 1
SCRIPT_SHA256 = digest(Path(__file__))


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Conversion tag trees must not contain symlinks")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def load_workspace(path):
    folder = path.resolve(strict=True)
    if not folder.is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Conversion workspaces must stay under ignored build/")
    record = json.loads((folder / "conversion.json").read_text())
    if record["schema_version"] != SCHEMA:
        raise ValueError("Unsupported workspace manifest version")
    if tree(folder / "source-tags") != record["source_tags"]:
        raise ValueError("Original extracted source tags changed; use a new workspace")
    if tree(folder / "stock-tags") != record["stock_tags"]:
        raise ValueError("Stock baseline changed; make compatibility edits in an explicit overlay")
    if digest(Path(record["source_map"]["path"])) != record["source_map"]["sha256"]:
        raise ValueError("Original source map changed; use a new workspace")
    return folder, record


def tool_for(folder, record):
    attempt = len(record["steps"]) + 1
    logs = folder / "logs" / f"step-{attempt:03d}"
    while logs.exists():
        attempt += 1
        logs = folder / "logs" / f"step-{attempt:03d}"
    logs.mkdir(exist_ok=False)
    tool = Invader(Path(record["invader_bin"]), Path(record["invader_manifest"]), logs)
    return tool, logs


def finish(folder, record, step):
    step["created_at"] = datetime.now(timezone.utc).isoformat()
    step["category"] = "community-conversion"
    step["import_tool_sha256"] = SCRIPT_SHA256
    record["steps"].append(step)
    save(folder / "conversion.json", record)


def changes(before, after):
    return [{"tag": name, "before": before.get(name), "after": after.get(name),
             "origin": "community-conversion"}
            for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]


def prepare(args):
    source = args.source_map.resolve(strict=True)
    source_header = cache_header(source)
    folder = output_directory(args.output)
    (folder / "logs").mkdir()
    record = {"schema_version": SCHEMA, "target_engine": "xbox-ntsc-2276",
              "content_origin": args.origin, "source_map": {"path": str(source), **source_header},
              "invader_bin": str(args.invader_bin.resolve(strict=True)),
              "invader_manifest": str(args.invader_manifest.resolve(strict=True)),
              "steps": [], "status": "prepared; conversion and validation pending"}
    tool, logs = tool_for(folder, record)
    originals = folder / "source-tags"
    originals.mkdir()
    tool.run("extract", "-t", originals, source)
    record["source_tags"] = tree(originals)
    shutil.copytree(originals, folder / "tags")
    stock = folder / "stock-tags"
    stock.mkdir()
    record["stock_sources"] = []
    for input_map in args.stock_map:
        path = input_map.resolve(strict=True)
        header = cache_header(path)
        if header["version"] != 5 or header["build"] != NTSC_BUILD:
            raise ValueError("Stock fallback must use the Xbox NTSC 2276 baseline")
        tool.run("extract", "-t", stock, path)
        record["stock_sources"].append({"path": str(path), **header})
    record["stock_tags"] = tree(stock)
    record["invader_commit"] = tool.commit
    record["tool_sha256"] = tool.provenance
    record["import_tool_sha256"] = SCRIPT_SHA256
    if digest(source) != source_header["sha256"]:
        raise ValueError("Source map changed during extraction")
    finish(folder, record, {"operation": "prepare", "logs": str(logs),
                           "source_tag_count": len(record["source_tags"]),
                           "stock_policy": "authored tags first; stock supplies missing dependencies only"})
    return {"workspace": str(folder), "source_tag_count": len(record["source_tags"])}


def models(args):
    folder, record = load_workspace(args.workspace)
    before = tree(folder / "tags")
    sources = [name for name in before if name.endswith(".gbxmodel")]
    if any((folder / "tags" / name).with_suffix(".model").exists() for name in sources):
        raise ValueError("Model conversion would overwrite existing model tags")
    tool, logs = tool_for(folder, record)
    if sources:
        tool.run("convert", "-t", folder / "tags", "-g", "gbxmodel", "model", "-b", "*.gbxmodel")
        tool.run("refactor", "-t", folder / "tags", "-M", "no-move", "-g", "gbxmodel", "model")
    step = {"operation": "models", "logs": str(logs), "models_converted": len(sources),
            "changes": changes(before, tree(folder / "tags")),
            "reason": "Community PC model representation and references converted for Xbox; no weapon balance edits"}
    finish(folder, record, step)
    return {"models_converted": len(sources), "changed_tags": len(step["changes"])}


def hud_overlay(args):
    folder, record = load_workspace(args.workspace)
    profile = json.loads(args.profile.read_text())
    if (profile["schema_version"] != SCHEMA or profile["target_engine"] != "xbox" or
            profile["write_policy"] != "fresh_overlay" or profile["source_tree"] not in ("source-tags", "tags")):
        raise ValueError("Expected a reviewed Xbox HUD profile with fresh_overlay write policy")
    converter = args.converter.resolve(strict=True)
    if digest(converter) != args.converter_sha256:
        raise ValueError("HUD converter binary differs from its reviewed hash")
    selected = profile["tags"]
    rules = profile["field_rules"]
    resamples = profile["bitmap_resamples"]
    for rule in [*rules, *resamples]:
        if rule["tag"] not in selected or not rule["reason"]:
            raise ValueError("Every rule needs a selected source tag and a reason")
        if any(character in rule["tag"] for character in "\t\r\n"):
            raise ValueError("HUD tag names must not contain rule-file delimiters")
    for rule in rules:
        if any(character in rule["field"] for character in "\t\r\n"):
            raise ValueError("HUD field names must not contain rule-file delimiters")
        for value in (rule["before"], rule["after"]):
            if not all(type(item) in (int, float) and math.isfinite(item)
                       for item in (value if isinstance(value, list) else [value])):
                raise ValueError("HUD field rules must contain finite numeric values")
    for rule in resamples:
        if rule["divisor"] not in (2, 4):
            raise ValueError("Only explicitly reviewed half/quarter HUD renditions are supported")
    source_root = folder / profile["source_tree"]
    paths = {name: safe_tag(source_root, name) for name in selected}
    if any(digest(paths[name]) != expected for name, expected in selected.items()):
        raise ValueError("HUD source differs from the reviewed profile; inspect this map's assets first")
    output = output_directory(args.output)
    for root in ("tags", "source-snapshots"):
        for name, path in paths.items():
            destination = output / root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    def numbers(value):
        items = value if isinstance(value, list) else [value]
        return ",".join(str(item) for item in items)
    (output / "field-rules.tsv").write_text("".join(
        f"{rule['tag']}\t{rule['field']}\t{numbers(rule['before'])}\t{numbers(rule['after'])}\n" for rule in rules))
    (output / "bitmap-rules.tsv").write_text("".join(
        f"{rule['tag']}\t{rule['divisor']}\n" for rule in resamples))
    result = subprocess.run([str(converter), str(output)], capture_output=True, text=True)
    (output / "conversion.log").write_text(result.stdout + result.stderr)
    step = {"operation": "hud-overlay", "output": str(output), "exit_code": result.returncode,
            "profile_sha256": digest(args.profile), "converter_sha256": digest(converter),
            "profile": profile, "changes": changes(selected, tree(output / "tags")),
            "source_unchanged": all(digest(paths[name]) == value for name, value in selected.items())}
    save(output / "conversion.json", step)
    finish(folder, record, step)
    if result.returncode or not step["source_unchanged"]:
        raise RuntimeError("HUD conversion failed; inspect the recorded overlay log")
    return {"overlay": str(output), "changed_tags": len(step["changes"])}


def overlay_roots(overlays):
    roots = []
    for path in overlays:
        overlay = path.resolve(strict=True)
        root = overlay / "tags"
        if root.is_symlink():
            raise ValueError("Overlay tags directories must not be symlinks")
        if not root.is_dir():
            raise ValueError("Every overlay must contain a tags directory")
        manifest = overlay / "conversion.json"
        if manifest.is_file():
            record = json.loads(manifest.read_text())
            if ("operation" in record and record["operation"] != "hud-overlay") or (
                    "conversion" in record and record["conversion"] not in {
                        "16_bit_pcm_to_xbox_adpcm", "remove_proven_duplicate_chicago_extra_layer",
                        "map_local_weapon_alias", "select_existing_lower_bitmap_mip",
                        "append_reviewed_netgame_flags"}):
                raise ValueError("Unknown overlay conversion discriminator")
            if "operation" in record and "conversion" in record:
                raise ValueError("Ambiguous overlay conversion discriminator")
            if record.get("operation") == "hud-overlay":
                if record.get("exit_code") != 0 or record.get("source_unchanged") is not True:
                    raise ValueError("Failed HUD overlays must not be compiled or used for provenance")
                expected = dict(record["profile"]["tags"])
                for change in record["changes"]:
                    if change["tag"] not in expected or change["after"] is None:
                        raise ValueError("HUD overlay manifest contains unexpected tag changes")
                    expected[change["tag"]] = change["after"]
                if tree(root) != expected:
                    raise ValueError("HUD overlay tags changed after recorded conversion")
            elif record.get("conversion") == "16_bit_pcm_to_xbox_adpcm":
                if (record.get("status") != "converted" or record.get("returncode") != 0
                        or record.get("source_unchanged") is not True):
                    raise ValueError("Incomplete or failed sound overlays must not be compiled or used for provenance")
                inputs, outputs = record.get("input_sha256"), record.get("output_sha256")
                if (record.get("schema_version") != 1 or not isinstance(inputs, dict) or not inputs
                        or not isinstance(outputs, dict) or inputs.keys() != outputs.keys()):
                    raise ValueError("Sound overlay manifest must preserve reviewed input and output identities")
                snapshots = overlay / "source-snapshots"
                if snapshots.is_symlink() or not snapshots.is_dir() or tree(snapshots) != inputs:
                    raise ValueError("Sound overlay source snapshots changed after recorded conversion")
                if tree(root) != outputs:
                    raise ValueError("Sound overlay tags changed after recorded conversion")
            elif record.get("conversion") == "remove_proven_duplicate_chicago_extra_layer":
                if (record.get("status") != "converted" or record.get("returncode") != 0
                        or record.get("source_unchanged") is not True
                        or record.get("snapshots_unchanged") is not True):
                    raise ValueError("Incomplete or failed shader overlays must not be compiled or used for provenance")
                inputs, outputs, actions = (record.get("input_sha256"), record.get("output_sha256"),
                                           record.get("actions"))
                if (record.get("schema_version") != 1 or not isinstance(inputs, dict) or not inputs
                        or not isinstance(outputs, dict) or not isinstance(actions, list) or not actions):
                    raise ValueError("Shader overlay manifest lacks reviewed input and output identities")
                parents = set()
                for action in actions:
                    if (not isinstance(action, dict) or set(action) != {"parent", "duplicate_layer"}
                            or not all(isinstance(v, str) and v in inputs for v in action.values())
                            or action["parent"] == action["duplicate_layer"] or action["parent"] in parents):
                        raise ValueError("Shader overlay actions differ from reviewed input identities")
                    parents.add(action["parent"])
                if set(outputs) != parents:
                    raise ValueError("Shader overlay outputs differ from reviewed parent identities")
                snapshots = overlay / "source-snapshots"
                if snapshots.is_symlink() or not snapshots.is_dir() or tree(snapshots) != inputs:
                    raise ValueError("Shader overlay source snapshots changed after recorded conversion")
                if tree(root) != outputs:
                    raise ValueError("Shader overlay tags changed after recorded conversion")
            elif record.get("conversion") == "map_local_weapon_alias":
                if (record.get("status") != "converted" or record.get("returncode") != 0
                        or any(record.get(field) is not True for field in (
                            "source_unchanged", "snapshots_unchanged", "alias_bytes_identical", "globals_unchanged"))):
                    raise ValueError("Incomplete or failed weapon alias overlays must not be compiled or used for provenance")
                inputs, outputs = record.get("input_sha256"), record.get("output_sha256")
                alias, rules = record.get("alias"), record.get("reference_rules")
                if (record.get("schema_version") != 1 or not isinstance(inputs, dict) or not inputs
                        or not isinstance(outputs, dict) or not isinstance(alias, dict)
                        or set(alias) != {"source_weapon", "alias_weapon", "globals_tag", "reserved_slot"}
                        or not all(isinstance(alias.get(field), str) and alias[field] in inputs
                                   for field in ("source_weapon", "globals_tag"))
                        or not isinstance(alias.get("alias_weapon"), str)
                        or alias["alias_weapon"] in inputs
                        or type(alias.get("reserved_slot")) is not int or alias["reserved_slot"] < 0
                        or not isinstance(rules, list) or not rules):
                    raise ValueError("Weapon alias overlay manifest lacks reviewed input and output identities")
                owners = set()
                for rule in rules:
                    if (not isinstance(rule, dict) or set(rule) != {"tag", "expected_replacements"}
                            or not isinstance(rule["tag"], str) or rule["tag"] not in inputs
                            or rule["tag"] in {alias["source_weapon"], alias["globals_tag"]} or rule["tag"] in owners
                            or type(rule["expected_replacements"]) is not int or rule["expected_replacements"] < 1):
                        raise ValueError("Weapon alias reference rules differ from reviewed input identities")
                    owners.add(rule["tag"])
                if (set(inputs) != owners | {alias["source_weapon"], alias["globals_tag"]}
                        or set(outputs) != owners | {alias["alias_weapon"]}
                        or outputs.get(alias["alias_weapon"]) != inputs[alias["source_weapon"]]):
                    raise ValueError("Weapon alias overlay must preserve weapon bytes and exclude stock globals output")
                snapshots = overlay / "source-snapshots"
                if snapshots.is_symlink() or not snapshots.is_dir() or tree(snapshots) != inputs:
                    raise ValueError("Weapon alias source snapshots changed after recorded conversion")
                if tree(root) != outputs:
                    raise ValueError("Weapon alias tags changed after recorded conversion")
            elif record.get("conversion") == "select_existing_lower_bitmap_mip":
                if (record.get("status") != "converted" or record.get("returncode") != 0
                        or any(record.get(field) is not True for field in (
                            "source_unchanged", "snapshots_unchanged", "lower_mip_bytes_preserved"))):
                    raise ValueError("Incomplete or failed mip overlays must not be compiled or used for provenance")
                inputs, outputs, actions = (record.get("input_sha256"), record.get("output_sha256"),
                                           record.get("actions"))
                if (record.get("schema_version") != 1 or not isinstance(inputs, dict) or not inputs
                        or not isinstance(outputs, dict) or inputs.keys() != outputs.keys()
                        or not isinstance(actions, list) or not actions):
                    raise ValueError("Mip overlay manifest lacks reviewed input and output identities")
                changed = set()
                for action in actions:
                    if (not isinstance(action, dict) or set(action) != {"tag", "bitmap_index", "drop_top_mips"}
                            or not isinstance(action["tag"], str) or action["tag"] not in inputs
                            or not action["tag"].endswith(".bitmap") or action["tag"] in changed
                            or type(action["bitmap_index"]) is not int or action["bitmap_index"] != 0
                            or type(action["drop_top_mips"]) is not int or action["drop_top_mips"] != 1):
                        raise ValueError("Mip overlay actions differ from the reviewed single-image top-mip selection")
                    changed.add(action["tag"])
                if changed != set(inputs):
                    raise ValueError("Mip overlay actions differ from reviewed tag identities")
                snapshots = overlay / "source-snapshots"
                if snapshots.is_symlink() or not snapshots.is_dir() or tree(snapshots) != inputs:
                    raise ValueError("Mip overlay source snapshots changed after recorded conversion")
                if tree(root) != outputs:
                    raise ValueError("Mip overlay tags changed after recorded conversion")
            elif record.get("conversion") == "append_reviewed_netgame_flags":
                from map_conversion.append_netgame_flags import validate_profile, valid_hash, action_tsv
                if (record.get("schema_version") != 1 or record.get("status") != "converted"
                        or record.get("returncode") != 0 or any(record.get(field) is not True for field in (
                            "source_unchanged", "snapshots_unchanged", "converter_source_snapshot_unchanged",
                            "profile_snapshot_unchanged"))):
                    raise ValueError("Incomplete or failed marker overlays must not be compiled or used for provenance")
                profile_file, source_file, action_file = (overlay / "reviewed-profile.json",
                                                        overlay / "converter-source.cpp", overlay / "netgame-flags.tsv")
                if (any(path.is_symlink() or not path.is_file() for path in (profile_file, source_file, action_file))
                        or not valid_hash(record.get("profile_sha256"))
                        or not valid_hash(record.get("converter_source_sha256"))
                        or digest(profile_file) != record["profile_sha256"]
                        or digest(source_file) != record["converter_source_sha256"]):
                    raise ValueError("Marker profile or converter source snapshot changed after conversion")
                profile = json.loads(profile_file.read_text())
                validate_profile(profile)
                if (any(record.get(field) != profile[field] for field in (
                        "origin", "source", "target", "selection", "converter_source_sha256"))
                        or action_file.read_text() != action_tsv(profile)):
                    raise ValueError("Marker actions differ from the reviewed profile")
                inputs = {label: {profile[label]["tag"]: profile[label]["sha256"]} for label in ("source", "target")}
                outputs = record.get("output_sha256")
                if (record.get("input_sha256") != inputs or not isinstance(outputs, dict)
                        or set(outputs) != {profile["target"]["tag"]} or not all(valid_hash(v) for v in outputs.values())):
                    raise ValueError("Marker overlay input or output identities differ from the reviewed profile")
                snapshots = overlay / "source-snapshots"
                expected = {label + "/" + name: value for label, values in inputs.items() for name, value in values.items()}
                if snapshots.is_symlink() or not snapshots.is_dir() or tree(snapshots) != expected:
                    raise ValueError("Marker source snapshots changed after recorded conversion")
                if tree(root) != outputs:
                    raise ValueError("Marker overlay tags changed after recorded conversion")
        roots.append(root)
    return roots


def provenance(args):
    folder, record = load_workspace(args.workspace)
    roots = overlay_roots(args.overlay)
    roots += [folder / "tags", folder / "stock-tags"]
    inventories = [tree(path) for path in roots]
    resolved = {}
    for index, inventory in enumerate(inventories):
        for name, sha in inventory.items():
            if name in resolved:
                continue
            if index == len(roots) - 1 or sha == record["stock_tags"].get(name):
                origin = "stock-xbox"
            elif sha == record["source_tags"].get(name):
                origin = record["content_origin"]
            else:
                origin = "community-conversion"
            resolved[name] = {"origin": origin, "sha256": sha, "tree": str(roots[index])}
    report = {"scope": "lookup provenance for all candidate tags; not scenario reachability or historical authorship",
              "priority": [str(path) for path in roots], "tags": resolved}
    save(folder / "provenance.json", report)
    return {"report": str(folder / "provenance.json"), "candidate_tags": len(resolved)}


def compile_map(args):
    folder, record = load_workspace(args.workspace)
    scenario = args.scenario
    if (not SCENARIO.fullmatch(scenario) or ".." in Path(scenario).parts or Path(scenario).is_absolute() or
            not NAME.fullmatch(Path(scenario).name)):
        raise ValueError("Expected a safe scenario tag path without extension")
    tool, logs = tool_for(folder, record)
    binary = tool.binary / "invader-build"
    compiler = {"binary": str(binary), "sha256": digest(binary), "invader_commit": tool.commit}
    if args.reviewed_build_manifest:
        reviewed = json.loads(args.reviewed_build_manifest.read_text())
        binary = Path(reviewed["binary"]).resolve(strict=True)
        if reviewed["original_invader_commit"] != tool.commit or digest(binary) != reviewed["binary_sha256"]:
            raise ValueError("Reviewed compiler does not match the pinned toolchain or binary hash")
        compiler = reviewed
    roots = overlay_roots(args.overlay) + [folder / "tags", folder / "stock-tags"]
    snapshots = {str(root): tree(root) for root in roots}
    data = args.data.resolve(strict=True) if args.data else folder / "data"
    data.mkdir(exist_ok=True)
    data_hashes = tree(data)
    attempt = len(record["steps"]) + 1
    output = folder / "builds" / f"{attempt:03d}"
    while output.exists():
        attempt += 1
        output = folder / "builds" / f"{attempt:03d}"
    maps = output / "maps"
    maps.mkdir(parents=True, exist_ok=False)
    command = [str(binary), "-g", "xbox-ntsc"]
    for root in roots:
        command += ["-t", str(root)]
    command += ["-d", str(data), "-m", str(maps), "-S", "data", "-E", scenario]
    result = subprocess.run(command, capture_output=True, text=True)
    (logs / "compile.log").write_text(result.stdout + result.stderr)
    step = {"operation": "compile", "command": command, "compiler": compiler,
            "exit_code": result.returncode, "logs": str(logs),
            "input_tags": snapshots, "data": {"path": str(data), "files": data_hashes},
            "input_data_unchanged": tree(data) == data_hashes,
            "input_tags_unchanged": all(tree(Path(root)) == snapshot for root, snapshot in snapshots.items()),
            "status": "compiled; runtime validation pending" if result.returncode == 0 else "compile failed"}
    if result.returncode == 0:
        header = cache_header(maps / (Path(scenario).name + ".map"))
        step["map"] = header
        step["within_native_limits"] = (header["version"] == 5 and header["type"] == 1 and
            header["build"] == NTSC_BUILD and header["declared_bytes"] <= MAX_CACHE_BYTES and
            header["tag_bytes"] <= TAG_ARENA_BYTES)
    finish(folder, record, step)
    if result.returncode or not step.get("within_native_limits") or not step["input_tags_unchanged"] or not step["input_data_unchanged"]:
        raise RuntimeError("Compilation or native cache checks failed; inspect the recorded build log")
    return {"output": str(maps), "map": step["map"], "status": step["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare", help="Extract one map into a fresh private conversion workspace")
    setup.add_argument("--source-map", type=Path, required=True)
    setup.add_argument("--output", type=Path, required=True)
    setup.add_argument("--invader-bin", type=Path, required=True)
    setup.add_argument("--invader-manifest", type=Path, required=True)
    setup.add_argument("--stock-map", type=Path, action="append", default=[])
    setup.add_argument("--origin", default="community-authored", help="Content source label, e.g. digsite-restoration")
    for name in ("models", "hud-overlay", "provenance", "compile"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name in ("compile", "provenance"):
            command.add_argument("--overlay", type=Path, action="append", default=[])
        if name == "compile":
            command.add_argument("--scenario", required=True)
            command.add_argument("--data", type=Path)
            command.add_argument("--reviewed-build-manifest", type=Path)
        if name == "hud-overlay":
            command.add_argument("--profile", type=Path, required=True)
            command.add_argument("--converter", type=Path, required=True)
            command.add_argument("--converter-sha256", required=True)
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    operations = {"prepare": prepare, "models": models, "hud-overlay": hud_overlay,
                  "provenance": provenance, "compile": compile_map}
    print(json.dumps(operations[args.command](args), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Community conversion failed: " + str(error), file=sys.stderr)
        sys.exit(1)
