"""Audit authored gun placements and opt in to a narrow native capability.

The audit preserves placements except separately approved, verified omissions.
A verified str#
tag resident through Xbox's implicit Soul root enables the runtime's reviewed
default-mode exception; restricted weapon sets keep their original remaps.
"""
from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
import shutil
import struct
import zlib

from .backend import ConversionError, _tree, legacy
from .diagnostics import diagnostic

MARKER = "__native_policy/authored_weapon_placements_v1.string_list"
PAYLOAD = b"halo-og:authored-weapon-placements:v1\0"
SOUL = "ui/shell/multiplayer.ui_widget_collection"
GLOBALS = "globals/globals.globals"
NET_FIELDS = ("flags.levitate", "type_0", "type_1", "type_2", "type_3", "team_index", "spawn_time", "position", "facing")
START_FIELDS = ("flags.no_grenades", "flags.plasma_grenades_only", "flags.type2_grenades_only", "flags.type3_grenades_only", "type_0", "type_1", "type_2", "type_3")
WEAPON_FIELDS = ("type", "name", "not_placed.automatically", "not_placed.on_easy", "not_placed.on_normal", "not_placed.on_hard",
                 "not_placed.use_player_appearance", "desired_permutation", "position", "rotation", "rounds_reserved", "rounds_loaded",
                 "flags.initially_at_rest", "flags.obsolete", "flags.does_accelerate")


def _fail(message, code="needs_profile", **details):
    raise ConversionError(code, "weapon_placements", message, details)


def _name(value):
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(c in value for c in "\t\n\r\0:") or not path.suffix):
        _fail("Weapon placement references an unsafe tag name", tag=value)
    return value


def _winner(roots, name):
    name = _name(name)
    for root in roots:
        at = Path(root)
        for part in PurePosixPath(name).parts:
            at /= part
            if at.is_symlink():
                _fail("Weapon placement tags must not be linked", tag=name)
        if at.is_file():
            if at.stat().st_nlink != 1:
                _fail("Weapon placement tags must not be hard linked", tag=name)
            return Path(root), at
    _fail("A weapon placement dependency is missing", tag=name)


def marker_bytes():
    # HEK TagFileHeader, a one-entry 12-byte StringList reflexive, followed by
    # its 20-byte TagData descriptor and NUL-terminated ASCII bytes. str# v1.
    body = struct.pack(">3I", 1, 0, 0) + struct.pack(">5I", len(PAYLOAD), 0, 0, 0, 0) + PAYLOAD
    header = bytearray(64)
    struct.pack_into(">I", header, 0, 0xFFFFFFFF)
    header[36:40] = b"str#"
    struct.pack_into(">II", header, 40, zlib.crc32(body) ^ 0xFFFFFFFF, 64)
    struct.pack_into(">HH", header, 56, 1, 255)
    header[60:64] = b"blam"
    return bytes(header) + body


def verify_marker(data):
    expected = marker_bytes()
    # Extracted HEK tags may carry another unused ID/checksum. Verify all
    # meaningful header/body fields and the entire exact descriptor/payload.
    if (len(data) != len(expected) or data[36:40] != b"str#" or data[44:64] != expected[44:64]
            or data[64:] != expected[64:]):
        _fail("Reserved authored-weapon capability tag has an invalid count, class or payload", "invalid_output", tag=MARKER)


def _count(tool, root, name, field, maximum=4096):
    count = tool.count(root, name, field)
    if type(count) is not int or not 0 <= count <= maximum:
        _fail("Weapon placement array exceeds its bounded audit", tag=name, field=field, value=count)
    return count


def _placements(tool, roots, scenario):
    root, _ = _winner(roots, scenario)
    records, collections = [], {}
    def collection(ref):
        if ref in collections:
            return
        collection_root, _ = _winner(roots, ref)
        entries = []
        for permutation in range(_count(tool, collection_root, ref, "permutations", 32)):
            weight_text = tool.get(collection_root, ref, f"permutations[{permutation}].weight")
            try:
                weight = float(weight_text)
            except (ValueError, TypeError):
                weight = float("nan")
            if not math.isfinite(weight) or not 0 <= weight <= 32768:
                _fail("Item permutation weight is invalid", tag=ref, field=f"permutations[{permutation}].weight", value=weight_text)
            item = tool.get(collection_root, ref, f"permutations[{permutation}].item").replace("\\", "/").strip()
            item = None if item in {"", ".weapon", ".equipment", ".garbage", ".item"} else _name(item)
            if int(weight) > 0 and not item:
                _fail("An active item permutation has no item reference", tag=ref, field=f"permutations[{permutation}].item")
            if item:
                _winner(roots, item)
            entries.append({"index": permutation, "item": item, "weight": weight})
        collections[ref] = {"default_spawn_time": tool.get(collection_root, ref, "default_spawn_time"), "permutations": entries}

    for kind, fields_to_read, collection_fields in (
            ("netgame_equipment", NET_FIELDS, ("item_collection",)),
            ("starting_equipment", START_FIELDS, tuple(f"item_collection_{slot}" for slot in range(1, 7)))):
        for index in range(_count(tool, root, scenario, kind)):
            prefix = f"{kind}[{index}]"
            fields = {field: tool.get(root, scenario, f"{prefix}.{field}") for field in fields_to_read}
            for field in collection_fields:
                ref = tool.get(root, scenario, f"{prefix}.{field}").replace("\\", "/").strip()
                ref = None if ref in {"", ".item_collection"} else _name(ref)
                if ref and not ref.endswith(".item_collection"):
                    _fail("Authored equipment has a non-collection reference", tag=scenario, field=f"{prefix}.{field}")
                if ref:
                    collection(ref)
                records.append({"kind": kind, "index": index, "fields": fields, "collection": ref, "collection_field": field})
    palette = _count(tool, root, scenario, "weapon_palette")
    for index in range(_count(tool, root, scenario, "weapons")):
        prefix = f"weapons[{index}]"
        fields = {field: tool.get(root, scenario, f"{prefix}.{field}") for field in WEAPON_FIELDS}
        try:
            palette_index = int(fields["type"])
        except (TypeError, ValueError):
            _fail("Placed weapon has a malformed palette index", tag=scenario, field=prefix + ".type", value=fields["type"])
        if palette_index in {-1, 65535}:
            records.append({"kind": "weapons", "index": index, "fields": fields, "weapon": None})
            continue
        if not 0 <= palette_index < palette:
            _fail("Placed weapon has an invalid palette index", tag=scenario, field=prefix + ".type", value=fields["type"])
        reference = tool.get(root, scenario, f"weapon_palette[{palette_index}].name").replace("\\", "/").strip()
        if reference in {"", ".weapon"}:
            records.append({"kind": "weapons", "index": index, "fields": fields, "weapon": None})
            continue
        weapon = _name(reference)
        if not weapon.endswith(".weapon"):
            _fail("Placed weapon palette references a non-weapon tag", tag=scenario, field=f"weapon_palette[{palette_index}].name")
        _winner(roots, weapon)
        records.append({"kind": "weapons", "index": index, "fields": fields, "weapon": weapon})
    return {"placements": records, "collections": collections}


def _registry(tool, roots):
    if not any((root / GLOBALS).is_file() for root in roots):
        return []
    root, _ = _winner(roots, GLOBALS)
    result = []
    for index in range(_count(tool, root, GLOBALS, "weapon_list", 64)):
        reference = tool.get(root, GLOBALS, f"weapon_list[{index}].weapon").replace("\\", "/").strip()
        result.append(None if reference in {"", ".weapon", ".equipment"} else _name(reference))
    return result


def _guns(graph):
    for placement in graph["placements"]:
        if placement["kind"] == "weapons":
            if not placement["weapon"]:
                continue
            if placement["fields"]["not_placed.automatically"].lower() in {"1", "true"}:
                continue
            yield placement, None, placement["weapon"]
        elif placement["collection"]:
            if all(placement["fields"]["type_" + str(index)] == "none" for index in range(4)):
                continue
            for entry in graph["collections"][placement["collection"]]["permutations"]:
                if int(entry["weight"]) > 0 and entry["item"].endswith(".weapon"):
                    yield placement, entry["index"], entry["item"]


def audit_weapon_placements(tool, source_root, source_scenario, roots, scenario,
                            workspace, steps, repairs, protected, policy="engine-native", source_fallback=None):
    roots = [Path(root) for root in roots]
    workspace, source_root = Path(workspace), Path(source_root)
    folder, overlay = workspace / "weapon-placements", workspace / "weapon-placements/tags"
    verified_omission = None
    if folder.exists() or folder.is_symlink():
        _fail("Weapon placement audit output must be fresh", "invalid_output")
    inventories = {root: _tree(root) for root in dict.fromkeys([source_root, *roots])}
    for root, inventory in inventories.items():
        for name, value in inventory.items():
            at = root / name
            if at in protected and protected[at] != value:
                _fail("Protected weapon placement input changed", "input_changed", tag=name)
            protected[at] = value

    def unchanged():
        if any(_tree(root) != inventory for root, inventory in inventories.items()):
            _fail("Weapon placement audit changed an input tree", "input_changed")
        if verified_omission is not None and legacy.digest(verified_omission[0]) != verified_omission[1]:
            _fail("Approved weapon omission receipt changed during placement audit", "input_changed")

    tool.stage = "weapon_placements"
    source_scenario_root, _ = _winner([source_root], source_scenario)
    children = _count(tool, source_scenario_root, source_scenario, "child_scenarios")
    if children:
        if policy != "engine-native":
            _fail("Authored placement capability requires a flattened scenario; child merges need an explicit audited source",
                  tag=source_scenario, field="child_scenarios", value=children)
        warning = diagnostic("weapon_placement_audit_unavailable", "weapon_placements",
            "Engine-native conversion merges child scenarios; a single-source placement equality proof is unavailable.",
            tag=source_scenario, field="child_scenarios", value=children, severity="warning",
            suggested_fix="Supply a flattened authored scenario before selecting the authored-default placement capability.")
        unchanged()
        steps.append({"operation": "weapon_placement_audit", "policy": policy, "status": "unavailable",
                      "diagnostics": [warning], "capability": None, "gameplay_validation": "pending"})
        return None, {"capability": None, "skip_compiled": True, "reason": "Child scenarios are merged by the compiler"}
    source_graph = _placements(tool, [source_root, *([Path(source_fallback)] if source_fallback else [])], source_scenario)
    final_graph = _placements(tool, roots, scenario)
    expected_graph, omission_receipt = source_graph, None
    omission_steps = [step for step in steps if step.get("operation") == "weapon_omissions"]
    if len(omission_steps) > 1:
        _fail("Weapon placement audit requires one unambiguous omission receipt", "invalid_output")
    if omission_steps:
        omission = omission_steps[0]
        checksum = omission.get("manifest_sha256")
        if (not isinstance(omission.get("manifest"), str) or not omission["manifest"]
                or not isinstance(checksum, str) or len(checksum) != 64
                or any(c not in "0123456789abcdef" for c in checksum)):
            _fail("Approved weapon omission receipt is missing or malformed", "invalid_output")
        manifest = Path(omission["manifest"])
        if (not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_nlink != 1
                or manifest.stat().st_size > 32 * 1024 * 1024 or not isinstance(checksum, str)
                or protected.get(manifest) != checksum or legacy.digest(manifest) != checksum):
            _fail("Approved weapon omission receipt is missing, unprotected or changed", "input_changed")
        with manifest.open("r", encoding="utf-8") as stream:
            content = stream.read(32 * 1024 * 1024 + 1)
        if len(content.encode("utf-8")) > 32 * 1024 * 1024 or legacy.digest(manifest) != checksum:
            _fail("Approved weapon omission receipt changed during placement audit", "input_changed")
        try:
            receipt = json.loads(content)
        except (ValueError, TypeError) as error:
            _fail("Approved weapon omission receipt is malformed", "invalid_output", reason=str(error))
        if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int
                or receipt["schema_version"] != 1 or receipt.get("operation") != "weapon_omissions"
                or receipt.get("scenario") != scenario or receipt.get("source_unchanged") is not True
                or not isinstance(receipt.get("source_placement_graph"), dict)
                or not isinstance(receipt.get("omitted_placement_graph"), dict)):
            _fail("Approved weapon omission receipt lacks its verified placement graphs", "invalid_output")
        if receipt["source_placement_graph"] != source_graph:
            _fail("Pre-omission placements differ from immutable authored source", "invalid_output", tag=scenario)
        expected_graph = receipt["omitted_placement_graph"]
        verified_omission = manifest, checksum
        omission_receipt = {"manifest": str(manifest), "sha256": checksum,
                            "omitted_reference_count": omission.get("omitted_reference_count")}
    if expected_graph != final_graph:
        _fail("Conversion changed an authored placement, collection permutation or spawn timing", "invalid_output", tag=scenario)
    source_placements_preserved = source_graph == final_graph
    registry = _registry(tool, roots)
    if policy not in {"engine-native", "authored-default"}:
        _fail("Unknown weapon placement policy")
    if policy == "authored-default":
        canonical = next((step for step in steps if step.get("operation") == "canonical_weapons"), None)
        if not canonical:
            _fail("Authored placement capability requires the original-weapon provenance stage")
        manifest = Path(canonical["manifest"])
        if legacy.digest(manifest) != canonical["manifest_sha256"]:
            _fail("Original-weapon provenance changed before placement audit", "input_changed")
        if json.loads(manifest.read_text())["target_registry"] != registry:
            _fail("Effective weapon registry differs from verified original-weapon provenance", "invalid_output", tag=GLOBALS)
    markers = [root / MARKER for root in roots if (root / MARKER).exists() or (root / MARKER).is_symlink()]
    for marker in markers:
        _, at = _winner([marker.parents[len(PurePosixPath(MARKER).parts) - 1]], MARKER)
        verify_marker(at.read_bytes())
    if markers and policy == "engine-native":
        _fail("Inherited authored-weapon capability requires the authored-default profile policy", tag=MARKER)
    checks, conflicts = [], []
    for placement, permutation, weapon in _guns(final_graph):
        slot = registry.index(weapon) if weapon in registry else None
        retail = registry[7] if slot == 1 and len(registry) > 7 else None if slot == 1 else weapon
        check = {"kind": placement["kind"], "index": placement["index"], "collection": placement.get("collection"), "collection_field": placement.get("collection_field"),
                 "permutation": permutation, "authored_weapon": weapon, "registry_slot": slot,
                 "retail_normal_weapon": retail, "effective_normal_weapon": weapon if policy == "authored-default" else retail}
        checks.append(check)
        if retail != weapon:
            conflicts.append(check)
    if markers and not conflicts:
        _fail("An inherited capability marker has no audited native default conflict", tag=MARKER)
    diagnostics = [diagnostic("native_weapon_remap_preserved" if policy == "authored-default" else "native_weapon_remap_conflict",
                    "weapon_placements", "The original Xbox default remap changes this authored placement; " +
                    ("the explicit map capability preserves its gun identity in unrestricted modes." if policy == "authored-default"
                     else "engine-native policy retains that remap."), tag=scenario, field=f"{entry['kind']}[{entry['index']}]",
                    value=entry, severity="info" if policy == "authored-default" else "warning",
                    suggested_fix="Use the explicit authored-default placement policy to preserve original-lineage authored guns in unrestricted modes."
                    if policy == "engine-native" else "Restricted weapon sets retain their original remaps; gameplay validation remains pending.")
                   for entry in conflicts]
    unchanged()
    folder.mkdir()
    output = None
    soul_references = []
    if conflicts and policy == "authored-default":
        soul_root, soul = _winner(roots, SOUL)
        count = _count(tool, soul_root, SOUL, "tags", 200)
        soul_references = [_name(tool.get(soul_root, SOUL, f"tags[{index}].reference")) for index in range(count)]
        if soul_references.count(MARKER) > 1 or (MARKER not in soul_references and count == 200):
            _fail("Xbox implicit UI collection cannot safely attach the placement capability", tag=SOUL)
        overlay.mkdir()
        marker = overlay / MARKER
        marker.parent.mkdir(parents=True)
        marker.write_bytes(marker_bytes())
        verify_marker(marker.read_bytes())
        if tool.count(overlay, MARKER, "strings") != 1 or tool.run("dependency", "-r", "-t", overlay, MARKER).strip():
            _fail("Approved authoring helper rejected the standalone capability marker", "invalid_output", tag=MARKER)
        target = overlay / SOUL
        target.parent.mkdir(parents=True)
        shutil.copyfile(soul, target)
        already_linked = MARKER in soul_references
        if not already_linked:
            tool.run("edit", "-t", overlay, "-I", "tags", 1, "end", "-S", f"tags[{count}].reference", MARKER, SOUL)
            soul_references.append(MARKER)
        if _count(tool, overlay, SOUL, "tags", 200) != len(soul_references):
            _fail("Capability attachment changed the Xbox UI collection count", "invalid_output", tag=SOUL)
        for index, ref in enumerate(soul_references):
            if _name(tool.get(overlay, SOUL, f"tags[{index}].reference")) != ref:
                _fail("Capability attachment changed an existing UI collection reference", "invalid_output", tag=SOUL)
        actions = [{"operation": "authored_weapon_placements_capability", "tag": MARKER,
                    "sha256_after": legacy.digest(marker), "policy": policy, "restricted_modes_preserved": True,
                    "reason": "Preserve verified original-lineage authored gun identity in unrestricted modes"},
                   {"operation": "authored_weapon_placements_residency", "tag": SOUL,
                    "sha256_before": legacy.digest(soul), "sha256_after": legacy.digest(target),
                    "existing_references_preserved": True, "inserted_references": [] if already_linked else [MARKER],
                    "reason": "Make the explicit capability resident through the Xbox implicit UI root"}]
        repairs.extend(actions)
        output = overlay
    unchanged()
    record = {"schema_version": 1, "operation": "weapon_placement_audit", "policy": policy,
              "scenario": scenario,
              "placements": final_graph, "source_placements": source_graph, "registry": registry,
              "authorized_expected_placements": expected_graph, "approved_omission_receipt": omission_receipt,
              "checks": checks, "conflicts": conflicts, "diagnostics": diagnostics,
              "capability": MARKER if output else None, "soul_references": soul_references,
              "source_unchanged": True, "placements_preserved": source_placements_preserved,
              "authorized_placements_preserved": True, "registry_preserved": True,
              "gameplay_validation": "pending"}
    manifest = folder / "conversion.json"
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    protected[manifest] = legacy.digest(manifest)
    if output:
        protected.update({output / name: value for name, value in _tree(output).items()})
    steps.append({"operation": "weapon_placement_audit", "policy": policy, "placed_gun_candidates": len(checks),
                  "native_default_conflicts": len(conflicts), "capability": record["capability"],
                  "diagnostics": diagnostics, "placements_preserved": source_placements_preserved,
                  "authorized_placements_preserved": True, "approved_omission_receipt": omission_receipt,
                  "registry_preserved": True,
                  "manifest": str(manifest), "manifest_sha256": legacy.digest(manifest), "gameplay_validation": "pending"})
    return output, record


def compiled_marker_index(cache):
    """Read only the bounded Xbox tag arena, inflating streams incrementally."""
    with Path(cache).open("rb") as stream:
        header = stream.read(2048)
        if len(header) != 2048 or header[:4] != b"daeh" or struct.unpack_from("<I", header, 4)[0] != 5:
            _fail("Capability verification requires a valid Xbox v5 cache", "invalid_output")
        declared, offset, size = [struct.unpack_from("<I", header, at)[0] for at in (8, 16, 20)]
        if not 2048 <= declared <= 512 * 1024 * 1024 or not 36 <= size <= 22 * 1024 * 1024 or offset < 2048 or size > declared - offset:
            _fail("Capability cache tag arena has invalid bounds", "invalid_output")
        if Path(cache).stat().st_size == declared:
            stream.seek(offset)
            arena = stream.read(size)
        else:
            decoder, chunks, total = zlib.decompressobj(), [], 0
            while compressed := stream.read(65536):
                pending = compressed
                while pending:
                    decoded = decoder.decompress(pending, 65536)
                    pending = decoder.unconsumed_tail
                    start, end = max(0, offset - 2048 - total), min(len(decoded), offset + size - 2048 - total)
                    if end > start:
                        chunks.append(decoded[start:end])
                    total += len(decoded)
                    if total > declared - 2048:
                        _fail("Capability cache exceeds declared bounds", "invalid_output")
                    if decoder.eof:
                        pending = b""
            if not decoder.eof or total != declared - 2048:
                _fail("Capability cache compressed data is incomplete", "invalid_output")
            arena = b"".join(chunks)
    if len(arena) != size:
        _fail("Capability tag arena is incomplete", "invalid_output")
    pointer, _, _, count = struct.unpack_from("<4I", arena)
    base = 0x803A6000
    table = pointer - base
    if not 0 < count <= 65535 or table < 36 or count * 32 > len(arena) - table:
        _fail("Capability cache tag table has invalid bounds", "invalid_output")
    matches = []
    for index in range(count):
        entry = table + index * 32
        if arena[entry:entry + 4] != b"#rts":
            continue
        at = struct.unpack_from("<I", arena, entry + 16)[0] - base
        if not 0 <= at < len(arena):
            _fail("Capability cache string tag name pointer is invalid", "invalid_output")
        end = arena.find(b"\0", at, min(at + 256, len(arena)))
        if end < 0:
            _fail("Capability cache string tag name is unterminated", "invalid_output")
        if arena[at:end] == MARKER.removesuffix(".string_list").replace("/", "\\").encode():
            matches.append(index)
    if len(matches) != 1 or matches[0] >= 32768:
        _fail("Compiled capability must have one resident string-list tag below absolute index 32768", "invalid_output", tag=MARKER, value=matches)
    return matches[0]


def verify_compiled_placements(tool, cache, workspace, expected, steps):
    if expected.get("skip_compiled"):
        steps.append({"operation": "verify_weapon_placements", "status": "unavailable", "reason": expected["reason"],
                      "gameplay_validation": "pending"})
        return
    folder = Path(workspace) / "weapon-placements/compiled-tags"
    folder.mkdir()
    args = ["-t", folder, "-m", Path(cache).parent, "-s", "*.scenario", "-s", "*.item_collection", "-s", GLOBALS]
    marker_index = None
    if expected["capability"]:
        marker_index = compiled_marker_index(cache)
        args += ["-s", MARKER, "-s", SOUL]
    tool.stage = "weapon_placements_verify"
    tool.run("extract", *args, cache)
    scenarios = list(folder.rglob("*.scenario"))
    if len(scenarios) != 1:
        _fail("Compiled placement scenario is ambiguous or absent", "invalid_output")
    scenario = scenarios[0].relative_to(folder).as_posix()
    if scenario != expected["scenario"]:
        _fail("Compiled weapon placement scenario differs from the audited identity", "invalid_output", tag=scenario)
    # _placements normally proves dependency files exist. Include all weapon
    # and item dependencies in this narrow extract to keep that proof intact.
    tool.run("extract", "-t", folder, "-m", Path(cache).parent, "-s", "*.weapon", "-s", "*.equipment", "-s", "*.garbage", "-s", "*.item", cache)
    actual = _placements(tool, [folder], scenario)
    if actual != expected["placements"] or _registry(tool, [folder]) != expected["registry"]:
        _fail("Compiled map changed authored weapon placements, permutations, timing or registry", "invalid_output", tag=scenario)
    if expected["capability"]:
        verify_marker((folder / MARKER).read_bytes())
        count = _count(tool, folder, SOUL, "tags", 200)
        refs = [_name(tool.get(folder, SOUL, f"tags[{index}].reference")) for index in range(count)]
        if refs != expected["soul_references"] or refs.count(MARKER) != 1:
            _fail("Compiled Xbox implicit UI root does not link the exact placement capability", "invalid_output", tag=SOUL)
    steps.append({"operation": "verify_weapon_placements", "status": "verified", "compiled_placements_preserved": True,
                  "compiled_registry_preserved": True, "capability": expected["capability"],
                  "capability_absolute_index": marker_index, "gameplay_validation": "pending"})
