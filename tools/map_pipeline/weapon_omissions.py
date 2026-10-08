"""Remove explicitly approved weapon references through a checked private overlay.

Approval names a reviewed asset variant, not a map filename or a replacement gun.
Only bounded, understood reference fields can be edited. All source tag trees
remain immutable; native parser readback proves the rest of each edited tag.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil

from .backend import ConversionError, _tree, legacy
from .stock_hud import IDENTITY_FIELDS
from .stock_weapons import ASSET_CLASSES, GLOBALS, _dependencies, _identity, _name, _winner
from .weapon_lineage import catalog_metadata, match_variant
from .weapon_placements import _placements

CLASSES = ASSET_CLASSES | {"globals", "scenario", "scenario_structure_bsp"}
IMPLICIT_ROOTS = (GLOBALS, "ui/ui_tags_loaded_multiplayer_scenario_type.tag_collection",
                  "ui/shell/multiplayer.ui_widget_collection")
KEY = re.compile(r"\A([A-Za-z_][A-Za-z_0-9]*(?:\[[0-9]+\])?)(.*)\Z")
INDEX = re.compile(r"\A([A-Za-z_][A-Za-z_0-9]*)\[([0-9]+)\](?:\.(.*))?\Z")


def _fail(message, code="needs_profile", **details):
    raise ConversionError(code, "weapon_omissions", message, details)


def _rows(listing):
    """Recover full field paths from the approved native editor's tree listing."""
    if len(listing.encode("utf-8")) > 4 * 1024 * 1024:
        _fail("Weapon omission parser listing exceeds its bounded scope")
    stack, rows = {}, []
    for line in listing.splitlines():
        branch = max(line.find("├──"), line.find("└──"))
        if branch >= 0:
            if branch < 1 or (branch - 1) % 4:
                _fail("Native parser returned an unsupported field tree", "invalid_output")
            depth, text = (branch - 1) // 4 + 1, line[branch + 3:]
        else:
            depth, text = 0, line
        match = KEY.fullmatch(text)
        if not match:
            _fail("Native parser returned an unsupported field listing", "invalid_output", line=line)
        key, tail = match.groups()
        parent = stack.get(depth - 1, "") if depth else ""
        # Array elements repeat the array header's name in invader-edit -L.
        if parent and key.split("[")[0] == parent.rsplit(".", 1)[-1].split("[")[0]:
            parent = parent.rsplit(".", 1)[0] if "." in parent else ""
        path = parent + "." + key if parent else key
        stack[depth] = path
        for old in tuple(stack):
            if old > depth:
                del stack[old]
        tail = tail.strip()
        # Native columns pad between the closing value delimiter and its
        # field type. Preserve every character inside authored values.
        columns = re.fullmatch(r"(\(.*\))[ \t]{2,}([A-Za-z].*)", tail)
        if columns:
            tail = columns[1] + " " + columns[2]
        rows.append((path, tail))
    return rows


def _references(rows, target):
    marker = "(" + target + ")"
    return [field for field, value in rows if marker in value.replace("\\", "/")]


def _count(tool, root, tag, field, maximum=4096):
    value = tool.count(root, tag, field)
    if type(value) is not int or not 0 <= value <= maximum:
        _fail("Weapon omission array exceeds its bounded scope", tag=tag, field=field, count=value)
    return value


def omit_reviewed_weapons(tool, catalog, source, roots, scenario, workspace,
                          steps, omissions, protected, *, lineage_derived=None):
    """Return a fresh referrer overlay, or None when no excluded asset is used."""
    source, workspace = Path(source), Path(workspace)
    roots = [Path(root) for root in roots]
    selected = {entry["weapon"] for entry in catalog["entries"] if entry["outcome"] == "omit"}
    if not selected:
        return None
    scenario = scenario.replace("\\", "/")
    if not scenario.endswith(".scenario"):
        scenario += ".scenario"
    _name(scenario, {"scenario"})
    folder, overlay = workspace / "weapon-omissions", workspace / "weapon-omissions/tags"
    if workspace.is_symlink() or not workspace.is_dir() or folder.exists() or folder.is_symlink():
        _fail("Weapon omission output requires a fresh regular workspace", "invalid_output")
    inventories = {root: _tree(root) for root in dict.fromkeys([source, *roots])}
    for root, inventory in inventories.items():
        for tag, checksum in inventory.items():
            path = root / tag
            if path in protected and protected[path] != checksum:
                _fail("Protected input changed before weapon omission", "input_changed", tag=tag)
            protected[path] = checksum

    def unchanged():
        for root, inventory in inventories.items():
            if _tree(root) != inventory:
                _fail("Weapon omission changed an input tree", "input_changed", tree=str(root))

    tool.stage = "weapon_omissions"
    origins = [scenario, *(tag for tag in IMPLICIT_ROOTS if _winner(roots, tag, CLASSES))]

    def reachable(active_roots):
        tags = set()
        for origin in origins:
            tags.update(_dependencies(tool, active_roots, origin, CLASSES))
        if len(tags) > 100000:
            _fail("Weapon omission dependency graph exceeds its bounded scope")
        return tags

    try:
        used = reachable(roots)
        selected &= used
        if not selected:
            return None
        scenario_root, _ = _winner(roots, scenario, CLASSES)
        if _count(tool, scenario_root, scenario, "child_scenarios"):
            _fail("Weapon omission requires a flattened scenario; child merges could restore excluded weapons", tag=scenario)
        proofs = {}
        for weapon in sorted(selected):
            if weapon not in inventories[source]:
                _fail("Excluded weapon is absent from immutable source tags", weapon=weapon)
            identity = dict(zip(IDENTITY_FIELDS, _identity(tool, source, weapon)))
            raw = {tag: inventories[source][tag]
                   for tag in sorted(_dependencies(tool, [source], weapon))}
            entry, mismatches = match_variant(catalog, weapon, identity, raw)
            if entry is None or entry["outcome"] != "omit" or not entry.get("approval"):
                _fail("Excluded weapon differs from its explicitly approved variant", weapon=weapon,
                      lineage_mismatches=mismatches)

            def converted(tag):
                if lineage_derived is not None:
                    if tag.endswith(".gbxmodel"):
                        return tag.removesuffix(".gbxmodel") + ".model"
                    if tag.endswith(".shader_transparent_chicago_extended"):
                        return tag.removesuffix(".shader_transparent_chicago_extended") + ".shader_transparent_chicago"
                return tag
            expected = {converted(tag): lineage_derived.get(converted(tag))
                        if lineage_derived is not None else checksum for tag, checksum in raw.items()}
            working = {tag: legacy.digest(_winner(roots, tag)[1])
                       for tag in sorted(_dependencies(tool, roots, weapon))}
            if working != expected:
                _fail("Excluded weapon closure changed beyond verified format conversion", weapon=weapon,
                      missing_tags=sorted(set(expected) - set(working)), extra_tags=sorted(set(working) - set(expected)),
                      changed_dependencies={tag: {"expected": expected[tag], "actual": working[tag]}
                                            for tag in sorted(set(expected) & set(working)) if expected[tag] != working[tag]})
            proofs[weapon] = {"asset_id": entry["asset_id"], "variant_id": entry["variant_id"],
                              "outcome": "omit", "reason": entry["reason"], "approval": copy.deepcopy(entry["approval"]),
                              "source_sha256": raw[weapon], "original_source_closure_sha256": raw,
                              "working_source_closure_sha256": working,
                              "verified_format_conversion": lineage_derived is not None}

        # Each plan is fully discovered and validated before any output mutation.
        plans, records, adjustments = {}, [], []

        def plan(tag):
            if tag not in plans:
                root, path = _winner(roots, tag, CLASSES)
                listing = tool.run("edit", "-t", root, "-L", tag)
                plans[tag] = {"root": root, "path": path, "before": inventories[root][tag],
                              "rows": _rows(listing), "erase": {}, "sets": {}}
            return plans[tag]

        def reverse(target):
            args = sum((["-t", root] for root in roots), [])
            names = set()
            for line in tool.run("dependency", "-R", *args, target).splitlines():
                if not line.strip():
                    continue
                if line.endswith(" [BROKEN]"):
                    _fail("Excluded weapon reverse references include an unresolved tag", tag=target)
                name = _name(line.replace("\\", "/"), CLASSES)
                if name in used:
                    names.add(name)
            if len(names) > 4096:
                _fail("Excluded weapon reverse references exceed their bounded scope", tag=target)
            return sorted(names)

        def record(tag, field, weapons, action, **extra):
            entries = [proofs[name] for name in sorted(weapons)]
            records.append({"kind": "weapon_reference_omission", "status": "omitted", "tag": tag,
                            "field": field, "action": action, "weapon": sorted(weapons)[0],
                            "weapons": sorted(weapons), "sha256_before": plan(tag)["before"],
                            "original_tag_sha256": inventories[source].get(tag),
                            "reason": "; ".join(entry["reason"] for entry in entries),
                            "approval": entries[0]["approval"], "reviewed_lineage": copy.deepcopy(entries), **extra})

        def erase(tag, array, index):
            p = plan(tag)
            maximum = 32 if array == "permutations" else 64 if array == "weapon_list" else 4096
            count = _count(tool, p["root"], tag, array, maximum)
            if not 0 <= index < count:
                _fail("Native parser reference index is outside its array", "invalid_output", tag=tag, field=array, index=index)
            p["erase"].setdefault(array, set()).add(index)

        # Every direct reachable referrer must expose exactly supported fields.
        for weapon in sorted(selected):
            found = False
            for tag in reverse(weapon):
                fields = _references(plan(tag)["rows"], weapon)
                if not fields:
                    _fail("Native dependency and field parsers disagree about an excluded weapon", "invalid_output", tag=tag, weapon=weapon)
                for field in fields:
                    found = True
                    match = INDEX.fullmatch(field)
                    array, index, leaf = (match[1], int(match[2]), match[3]) if match else (None, None, None)
                    if tag.endswith(".item_collection") and array == "permutations" and leaf == "item":
                        erase(tag, array, index)
                        record(tag, field, {weapon}, "erase_item_permutation", weight=tool.get(plan(tag)["root"], tag, f"permutations[{index}].weight"))
                    elif tag == GLOBALS and array == "weapon_list" and leaf == "weapon":
                        erase(tag, array, index)
                        record(tag, field, {weapon}, "erase_globals_weapon_entry")
                    elif tag == scenario and array == "weapon_palette" and leaf == "name":
                        erase(tag, array, index)
                        record(tag, field, {weapon}, "erase_weapon_palette_entry")
                    elif tag == scenario and array == "player_starting_profile" and leaf in {"primary_weapon", "secondary_weapon"}:
                        plan(tag)["sets"][field] = ""
                        record(tag, field, {weapon}, "clear_player_starting_weapon")
                    else:
                        _fail("Excluded weapon has an unsupported reachable reference shape", tag=tag, field=field, weapon=weapon)
            if not found:
                _fail("Reachable excluded weapon has no supported direct referrer", weapon=weapon)

        # Empty collections cannot remain in a spawn/start slot. Mixed ones keep
        # every other weighted entry, in its authored order.
        for collection in tuple(plans):
            p = plans[collection]
            removed = p["erase"].get("permutations", set())
            if not removed or len(removed) != _count(tool, p["root"], collection, "permutations", 32):
                continue
            weapons = {item["weapon"] for item in records if item["tag"] == collection}
            for tag in reverse(collection):
                fields = _references(plan(tag)["rows"], collection)
                if not fields:
                    _fail("Native parsers disagree about an empty item collection", "invalid_output", tag=tag)
                for field in fields:
                    match = INDEX.fullmatch(field)
                    array, index, leaf = (match[1], int(match[2]), match[3]) if match else (None, None, None)
                    if tag == scenario and array == "netgame_equipment" and leaf == "item_collection":
                        erase(tag, array, index)
                        record(tag, field, weapons, "erase_empty_collection_spawn", item_collection=collection)
                    elif tag == scenario and array == "starting_equipment" and leaf in {f"item_collection_{slot}" for slot in range(1, 7)}:
                        plan(tag)["sets"][field] = ""
                        record(tag, field, weapons, "clear_empty_starting_collection", item_collection=collection)
                    else:
                        _fail("Empty excluded item collection has an unsupported reachable reference shape", tag=tag, field=field, item_collection=collection)

        # Erasing palette entries requires removing their authored instances and
        # explicitly translating every surviving instance's palette index.
        if scenario in plans and plans[scenario]["erase"].get("weapon_palette"):
            p = plans[scenario]
            removed = p["erase"]["weapon_palette"]
            palette_count = _count(tool, p["root"], scenario, "weapon_palette")
            for index in range(_count(tool, p["root"], scenario, "weapons")):
                field = f"weapons[{index}].type"
                text = tool.get(p["root"], scenario, field).strip()
                try:
                    old = int(text)
                except (ValueError, TypeError):
                    _fail("Direct weapon placement has an invalid palette index", tag=scenario, field=field, value=text)
                if old in {-1, 65535}:
                    continue
                if not 0 <= old < palette_count:
                    _fail("Direct weapon placement points outside its palette", tag=scenario, field=field, value=text)
                if old in removed:
                    weapon = tool.get(p["root"], scenario, f"weapon_palette[{old}].name").replace("\\", "/")
                    erase(scenario, "weapons", index)
                    record(scenario, field, {weapon}, "erase_direct_weapon_instance", palette_index=old)
                else:
                    new = old - sum(value < old for value in removed)
                    if new != old:
                        p["sets"][field] = str(new)
                        adjustments.append({"tag": scenario, "field": field, "old_palette_index": old, "new_palette_index": new})
            if p["erase"].get("weapons"):
                # HEK object_names contains names only; the cache compiler
                # derives object type/index links from placed-object .name.
                # Refuse named weapon arrays rather than guessing those links
                # or changing HSC object operands as placement indices shift.
                for index in range(_count(tool, p["root"], scenario, "weapons")):
                    field = f"weapons[{index}].name"
                    value = tool.get(p["root"], scenario, field).strip()
                    if value not in {"-1", "65535"}:
                        _fail("Direct weapon omission cannot safely rewrite named object links", tag=scenario, field=field, value=value)

        source_graph = _placements(tool, roots, scenario)
        overlay.mkdir(parents=True)
        changes = []
        for tag, p in sorted(plans.items()):
            if not p["erase"] and not p["sets"]:
                continue
            target = overlay / tag
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p["path"], target)
            # Sets use original indices first; erases then shift surviving rows.
            for field, value in sorted(p["sets"].items()):
                tool.run("edit", "-t", overlay, "-S", field, value, tag)
            for array, indices in sorted(p["erase"].items()):
                for index in sorted(indices, reverse=True):
                    tool.run("edit", "-t", overlay, "-E", f"{array}[{index}]", tag)

            def translate(field):
                match = INDEX.fullmatch(field)
                if not match or match[1] not in p["erase"]:
                    return field
                array, index, leaf = match[1], int(match[2]), match[3]
                if index in p["erase"][array]:
                    return None
                index -= sum(value < index for value in p["erase"][array])
                return f"{array}[{index}]" + ("." + leaf if leaf else "")

            excluded_fields = {translate(field) for field in p["sets"]}
            if None in excluded_fields:
                _fail("Weapon omission field edit overlaps an erased array row", "invalid_output", tag=tag)
            expected = []
            for field, value in p["rows"]:
                match = INDEX.fullmatch(field)
                if value == "array" and match and match[1] in p["erase"]:
                    continue  # Separately counted below; this index is its count.
                field = translate(field)
                if field is not None and field not in excluded_fields:
                    expected.append((field, value))
            actual = []
            for field, value in _rows(tool.run("edit", "-t", overlay, "-L", tag)):
                match = INDEX.fullmatch(field)
                if value == "array" and match and match[1] in p["erase"]:
                    continue
                if field not in excluded_fields:
                    actual.append((field, value))
            if expected != actual:
                _fail("Weapon omission changed fields outside its approved reference edits", "invalid_output", tag=tag)
            for array, indices in p["erase"].items():
                maximum = 32 if array == "permutations" else 64 if array == "weapon_list" else 4096
                before_count = _count(tool, p["root"], tag, array, maximum)
                if _count(tool, overlay, tag, array, maximum) != before_count - len(indices):
                    _fail("Weapon omission array count failed native readback", "invalid_output", tag=tag, field=array)
            for field, value in p["sets"].items():
                translated = translate(field)
                actual_value = tool.get(overlay, tag, translated).strip()
                if actual_value != value and not (value == "" and actual_value in {".weapon", ".item_collection"}):
                    _fail("Weapon omission field failed native readback", "invalid_output", tag=tag, field=translated)
            changes.append({"tag": tag, "sha256_before": p["before"], "sha256_after": legacy.digest(target),
                            "erased_indices": {key: sorted(value) for key, value in p["erase"].items()},
                            "set_fields": dict(p["sets"]), "native_reparse_verified": True})

        remaining = sorted(selected & reachable([overlay, *roots]))
        if remaining:
            _fail("Excluded weapons remain reachable after approved reference edits", "invalid_output", weapons=remaining)
        omitted_graph = _placements(tool, [overlay, *roots], scenario)
        unchanged()
        by_tag = {change["tag"]: change for change in changes}
        for item in records:
            item["sha256_after"] = by_tag[item["tag"]]["sha256_after"]
        manifest = folder / "conversion.json"
        body = {"schema_version": 1, "operation": "weapon_omissions", "catalog": catalog_metadata(catalog),
                "scenario": scenario, "references": records, "omitted_reference_count": len(records),
                "palette_index_adjustments": adjustments, "changes": changes,
                "source_placement_graph": source_graph, "omitted_placement_graph": omitted_graph,
                "source_unchanged": True, "unrelated_fields_preserved": True, "excluded_weapons_unreachable": True}
        manifest.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        manifest_hash = legacy.digest(manifest)
        protected[manifest] = manifest_hash
        for tag, checksum in _tree(overlay).items():
            protected[overlay / tag] = checksum
        steps.append({"operation": "weapon_omissions", "manifest": str(manifest), "manifest_sha256": manifest_hash,
                      "omitted_reference_count": len(records), "changes": changes, "references": records})
        omissions.extend(records)
        return overlay
    finally:
        unchanged()
