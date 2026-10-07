"""Lower supported MCC child anchors into native parent-first HUD chains.

Native render_weapon_hud draws parent first, then static, meter, number and
overlay arrays in that order. Contiguous anchor groups preserve that ordering.
Only copied weapon_hud_interface tags are changed; gameplay tags remain inputs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .assets import checked_tag
from .backend import ConversionError, legacy

SUFFIX = ".weapon_hud_interface"
ARRAYS = ("static_elements", "meter_elements", "number_elements", "overlay_elements")
NON_DRAW_ARRAYS = ("crosshairs", "screen_effect")
ANCHORS = frozenset({"top_left", "top_right", "bottom_left", "bottom_right", "center"})
# Native hud_weapon.c:99,736,991 rejects reaching its sixteen-entry hierarchy.
MAX_CHAIN = 15
MAX_ARRAY = 4096


def _fail(message, **details):
    raise ConversionError("needs_profile", "presentation_anchors", message, details)


def _reference(value):
    value = value.strip().replace("\\", "/")
    if value in {"", SUFFIX}:
        return None
    path = Path(value)
    if (path.is_absolute() or path.as_posix() != value or not value.endswith(SUFFIX)
            or any(part in {".", ".."} for part in path.parts)
            or any(char in value for char in "\0\r\n\t:")):
        _fail("Unsafe weapon HUD parent reference", value=value)
    return value


def _winner(roots, name):
    for root in roots:
        if (root / name).exists() or (root / name).is_symlink():
            return root, checked_tag(root, name, SUFFIX)
    _fail("Weapon HUD parent dependency is missing", tag=name)


def _count(tool, root, name, field):
    count = tool.count(root, name, field)
    if type(count) is not int or not 0 <= count <= MAX_ARRAY:
        _fail("Weapon HUD array count exceeds structural bounds", tag=name, field=field, value=count)
    return count


def _depths(parents):
    depths, pending = {}, []
    def visit(name):
        if name in pending:
            _fail("Weapon HUD parent chain contains a cycle", tag=name, dependency_chain=[*pending, name])
        if name in depths:
            return depths[name]
        if name not in parents:
            _fail("Weapon HUD parent is outside the complete dependency graph", tag=name)
        if len(pending) >= MAX_CHAIN:
            _fail("Weapon HUD chain exceeds the native fifteen-definition capacity", tag=name,
                  dependency_chain=[*pending, name], chain_depth=len(pending) + 1, maximum=MAX_CHAIN)
        pending.append(name)
        parent = parents[name]
        depth = 1 + (visit(parent) if parent else 0)
        pending.pop()
        if depth > MAX_CHAIN:
            _fail("Weapon HUD chain exceeds the native fifteen-definition capacity", tag=name,
                  chain_depth=depth, maximum=MAX_CHAIN)
        depths[name] = depth
        return depth
    for name in parents:
        visit(name)
    return depths


def _groups(elements):
    groups = []
    for element in elements:
        if not groups or groups[-1]["anchor"] != element["effective_anchor"]:
            groups.append({"anchor": element["effective_anchor"], "elements": []})
        groups[-1]["elements"].append(element)
    return groups


def normalize_weapon_hud_anchors(tool, roots, required, workspace, steps, repairs, protected,
                                 native_tags=frozenset()):
    roots = [Path(root) for root in roots]
    workspace = Path(workspace)
    folder = workspace / "native-hud-anchors"
    if workspace.is_symlink() or not workspace.is_dir():
        _fail("Weapon HUD anchor workspace must be a regular directory")
    if folder.exists() or folder.is_symlink():
        _fail("Weapon HUD anchor output must be fresh")
    names = sorted(name for name in required if name.endswith(SUFFIX))
    if not names:
        return None
    tool.stage = "presentation_anchors"
    inputs, definitions, parents, plans = {}, {}, {}, {}
    for name in names:
        _reference(name)
        root, path = _winner(roots, name)
        expected = legacy.digest(path)
        if path in protected and protected[path] != expected:
            raise ConversionError("input_changed", "presentation_anchors", "Weapon HUD input changed before anchor planning", {"tag": name})
        inputs[name] = (root, path, expected)
        protected[path] = expected
        parent = _reference(tool.get(root, name, "child_hud"))
        if parent and parent not in names:
            _fail("Weapon HUD parent is absent from reachable dependency inventory", tag=name,
                  field="child_hud", value=parent)
        parents[name] = parent
        # Canonical Xbox definitions use the native renderer's original meaning.
        # Keep their parent edges in cycle/depth proofs without interpreting their
        # child fields as MCC presentation data.
        if name in native_tags:
            continue
        anchor = tool.get(root, name, "anchor").strip()
        if anchor not in ANCHORS:
            _fail("Weapon HUD root anchor is unsupported by the native renderer", tag=name, field="anchor", value=anchor)
        counts, elements, explicit = {}, [], False
        for array in ARRAYS:
            counts[array] = _count(tool, root, name, array)
            for index in range(counts[array]):
                field = f"{array}[{index}].anchor"
                value = tool.get(root, name, field).strip()
                if value != "from_parent" and value not in ANCHORS:
                    _fail("MCC child anchor requires an unsupported native reference corner", tag=name,
                          field=field, value=value, supported=["from_parent", *sorted(ANCHORS)])
                explicit |= value != "from_parent"
                elements.append({"array": array, "source_index": index, "source_anchor": value,
                                 "effective_anchor": anchor if value == "from_parent" else value})
        for array in NON_DRAW_ARRAYS:
            counts[array] = _count(tool, root, name, array)
        definitions[name] = {"anchor": anchor, "parent": parent, "counts": counts, "elements": elements}
        if explicit:
            groups = _groups(elements)
            identity = hashlib.sha256(json.dumps({"tag": name, "source_sha256": expected,
                                                  "groups": groups}, sort_keys=True).encode()).hexdigest()[:24]
            generated = [f"__native_hud/anchors/{identity}_{index}{SUFFIX}" for index in range(len(groups) - 1)]
            for generated_name in generated:
                if any((root / generated_name).exists() or (root / generated_name).is_symlink() for root in roots):
                    _fail("Generated native HUD identity collides with existing content", tag=name, generated_tag=generated_name)
            plans[name] = {"groups": groups, "generated": generated}
    before_depths = _depths(parents)
    proposed = dict(parents)
    for name, plan in plans.items():
        previous = parents[name]
        for generated in plan["generated"]:
            if generated in proposed:
                _fail("Generated native HUD identities collide", generated_tag=generated)
            proposed[generated] = previous
            previous = generated
        proposed[name] = previous
    after_depths = _depths(proposed)

    def verify_inputs():
        for name, (_, path, expected) in inputs.items():
            if legacy.digest(path) != expected:
                raise ConversionError("input_changed", "presentation_anchors", "Anchor conversion changed an original HUD input", {"tag": name})
        for path, expected in protected.items():
            try:
                unchanged = legacy.digest(path) == expected
            except OSError:
                unchanged = False
            if not unchanged:
                raise ConversionError("input_changed", "presentation_anchors", "Anchor conversion changed a protected input")
    verify_inputs()
    if not plans:
        steps.append({"operation": "weapon_hud_child_anchors", "status": "unchanged",
                      "definitions_checked": len(names), "canonical_native_definitions_skipped": len(set(names) & set(native_tags)),
                      "maximum_native_chain": MAX_CHAIN})
        return None
    overlay = folder / "tags"
    overlay.mkdir(parents=True)
    records = []
    for name, plan in plans.items():
        root, path, expected = inputs[name]
        snapshot = folder / "source-snapshots" / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, snapshot)
        protected[snapshot] = expected
        output_names = [*plan["generated"], name]
        previous = parents[name]
        nodes = []
        for output_name, group in zip(output_names, plan["groups"]):
            target = overlay / output_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snapshot, target)
            kept = {array: [element for element in group["elements"] if element["array"] == array] for array in ARRAYS}
            args = ["-t", overlay, "-S", "anchor", group["anchor"], "-S", "child_hud", previous or ""]
            for array in ARRAYS:
                indices = {element["source_index"] for element in kept[array]}
                for index in reversed(range(definitions[name]["counts"][array])):
                    if index not in indices:
                        args += ["-E", f"{array}[{index}]"]
                for index in range(len(kept[array])):
                    args += ["-S", f"{array}[{index}].anchor", "from_parent"]
            if output_name != name:
                for array in NON_DRAW_ARRAYS:
                    if definitions[name]["counts"][array]:
                        args += ["-E", array + "[*]"]
            tool.run("edit", *args, output_name)
            if (tool.get(overlay, output_name, "anchor").strip() != group["anchor"]
                    or _reference(tool.get(overlay, output_name, "child_hud")) != previous):
                _fail("Native HUD anchor output changed its planned root or parent", tag=output_name)
            output_counts = {}
            for array in ARRAYS:
                count = _count(tool, overlay, output_name, array)
                if count != len(kept[array]):
                    _fail("Native HUD anchor output changed its element count", tag=output_name, field=array)
                output_counts[array] = count
                for index in range(count):
                    if tool.get(overlay, output_name, f"{array}[{index}].anchor").strip() != "from_parent":
                        _fail("Native HUD child anchor was not lowered to parent placement", tag=output_name, field=array)
            for array in NON_DRAW_ARRAYS:
                count = _count(tool, overlay, output_name, array)
                expected_count = definitions[name]["counts"][array] if output_name == name else 0
                if count != expected_count:
                    _fail("Native HUD anchor output changed preserved crosshair/screen-effect ownership", tag=output_name, field=array)
                output_counts[array] = count
            nodes.append({"tag": output_name, "parent": previous, "anchor": group["anchor"], "counts": output_counts,
                          "elements": [{**element, "target_index": index} for array in ARRAYS
                                       for index, element in enumerate(kept[array])],
                          "source_sha256": expected, "sha256_after": legacy.digest(target),
                          "crosshair_screen_effect_owner": output_name == name})
            previous = output_name
        before_order = [(element["array"], element["source_index"]) for element in definitions[name]["elements"]]
        after_order = [(element["array"], element["source_index"]) for node in nodes for element in node["elements"]]
        if before_order != after_order:
            _fail("Native HUD anchor lowering changed native element draw order", tag=name)
        records.append({"kind": "native_hud_child_anchors", "operation": "weapon_hud_child_anchors", "tag": name,
                        "sha256_before": expected, "sha256_after": legacy.digest(overlay / name),
                        "original_anchor": definitions[name]["anchor"], "original_parent": parents[name],
                        "counts_before": definitions[name]["counts"], "nodes": nodes,
                        "chain_depth_before": before_depths[name], "chain_depth_after": after_depths[name],
                        "draw_order_before": before_order, "draw_order_after": after_order,
                        "draw_order_preserved": True, "other_parameters_preserved_by_source_clone": True,
                        "reason": "Lower explicit MCC child reference corners into ordered native parent HUD definitions",
                        "visual_validation": "pending"})
    actual = dict(parents)
    for name in proposed:
        if (overlay / name).is_file():
            actual[name] = _reference(tool.get(overlay, name, "child_hud"))
    if actual != proposed:
        _fail("Native HUD output hierarchy differs from its validated plan")
    _depths(actual)
    verify_inputs()
    manifest = folder / "conversion.json"
    record = {"schema_version": 1, "operation": "weapon_hud_child_anchors", "status": "converted",
              "maximum_native_chain": MAX_CHAIN, "actions": records, "source_unchanged": True,
              "gameplay_validation": "pending"}
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    protected[manifest] = legacy.digest(manifest)
    repairs.extend(records)
    steps.append({"operation": "weapon_hud_child_anchors", "status": "converted", "definitions_checked": len(names),
                  "canonical_native_definitions_skipped": len(set(names) & set(native_tags)),
                  "definitions_converted": len(plans), "generated_definitions": sum(len(plan["generated"]) for plan in plans.values()),
                  "maximum_native_chain": MAX_CHAIN, "draw_order_preserved": True, "source_unchanged": True,
                  "manifest": str(manifest), "manifest_sha256": legacy.digest(manifest), "visual_validation": "pending"})
    return overlay
