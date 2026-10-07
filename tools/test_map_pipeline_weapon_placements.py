"""Offline native remap capability, placement preservation and cache proof."""
import copy
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools.map_pipeline import weapon_placements as placement
from tools.map_pipeline.backend import ConversionError, _tree, legacy


class FakeInvader:
    def __init__(self, mutation=None, edit_fault=None, compiled_roots=None):
        self.mutation, self.edit_fault, self.compiled_roots = mutation, edit_fault, compiled_roots

    def read(self, root, name):
        return json.loads((Path(root) / name).read_text())

    def selected(self, body, field):
        for part in field.split("."):
            if "[" in part:
                name, index = part[:-1].split("[")
                body = body[name][int(index)]
            else:
                body = body[part]
        return body

    def count(self, root, name, field):
        if self.mutation:
            mutation, self.mutation = self.mutation, None
            mutation()
        if name == placement.MARKER:
            placement.verify_marker((Path(root) / name).read_bytes())
            return 1
        return len(self.selected(self.read(root, name), field))

    def get(self, root, name, field):
        value = self.selected(self.read(root, name), field)
        return str(value)

    def run(self, tool, *args):
        root = Path(args[args.index("-t") + 1])
        if tool == "dependency":
            return ""
        if tool == "extract":
            for source in reversed(self.compiled_roots):
                for name in _tree(source):
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, target)
            return ""
        if tool == "edit":
            body = self.read(root, args[-1])
            body["tags"].append({"reference": placement.MARKER})
            if self.edit_fault:
                self.edit_fault(body)
            (root / args[-1]).write_text(json.dumps(body, sort_keys=True))
            return ""
        raise AssertionError(tool)


class PlacementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source, self.working, self.workspace = [self.base / name for name in ("source", "working", "workspace")]
        for folder in (self.source, self.working, self.workspace):
            folder.mkdir()
        self.original_scenario = "levels/custom/arena.scenario"
        self.scenario = "levels/custom/community_arena.scenario"
        self.collection = "item collections/flame.item_collection"
        self.flame = "weapons/flamethrower/flamethrower.weapon"
        self.rocket = "weapons/rocket launcher/rocket launcher.weapon"
        self.pistol = "weapons/pistol/pistol.weapon"
        self.registry = ["weapons/assault.weapon", self.flame, "weapons/gravity.weapon", "weapons/needler.weapon",
                         self.pistol, "weapons/plasma pistol.weapon", "weapons/plasma rifle.weapon", self.rocket,
                         "weapons/shotgun.weapon", "weapons/sniper.weapon", "weapons/ball.weapon", "weapons/flag.weapon",
                         "weapons/frag.equipment", "weapons/plasma.equipment"]
        net = {"flags": {"levitate": "0"}, "type_0": "all_games", "type_1": "none", "type_2": "none", "type_3": "none", "team_index": "0",
               "spawn_time": "0", "position": "1.000000,2.000000,3.000000", "facing": "90.000000", "item_collection": self.collection}
        weapon = {"type": "0", "name": "-1", "not_placed": {name: "0" for name in ("automatically", "on_easy", "on_normal", "on_hard", "use_player_appearance")},
                  "desired_permutation": "0", "position": "4.000000,5.000000,6.000000", "rotation": "0.000000,0.000000,0.000000",
                  "rounds_reserved": "20", "rounds_loaded": "5", "flags": {name: "0" for name in ("initially_at_rest", "obsolete", "does_accelerate")}}
        self.scenario_body = {"child_scenarios": [], "netgame_equipment": [net], "starting_equipment": [], "weapons": [weapon], "weapon_palette": [{"name": self.flame}]}
        self.collection_body = {"default_spawn_time": "120", "permutations": [{"item": self.flame, "weight": "100.000000"}]}
        for root, scenario in ((self.source, self.original_scenario), (self.working, self.scenario)):
            self.tag(root, scenario, self.scenario_body)
            self.tag(root, self.collection, self.collection_body)
            self.tag(root, placement.GLOBALS, {"weapon_list": [{"weapon": name} for name in self.registry], "unchanged": "custom settings"})
            for weapon in (self.flame, self.rocket, self.pistol):
                self.tag(root, weapon, {"original_gameplay": "preserved"})
        self.tag(self.working, placement.SOUL, {"tags": [{"reference": "ui/pause.ui_widget_definition"}], "native": "unchanged UI"})
        canonical = self.workspace / "canonical.json"
        canonical.write_text(json.dumps({"target_registry": self.registry}))
        self.steps = [{"operation": "canonical_weapons", "manifest": str(canonical), "manifest_sha256": legacy.digest(canonical)}]
        self.repairs, self.protected = [], {}

    def tag(self, root, name, body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, sort_keys=True))

    def audit(self, policy="authored-default", tool=None, roots=None, workspace=None):
        return placement.audit_weapon_placements(tool or FakeInvader(), self.source, self.original_scenario,
                roots or [self.working], self.scenario, workspace or self.workspace, self.steps, self.repairs, self.protected, policy)

    def test_explicit_capability_preserves_netgame_and_direct_placements_registry_and_og_assets(self):
        before = {root: _tree(root) for root in (self.source, self.working)}
        overlay, record = self.audit()
        self.assertEqual({root: _tree(root) for root in before}, before)
        self.assertEqual(set(_tree(overlay)), {placement.MARKER, placement.SOUL})
        placement.verify_marker((overlay / placement.MARKER).read_bytes())
        refs = json.loads((overlay / placement.SOUL).read_text())
        self.assertEqual(refs["tags"], [{"reference": "ui/pause.ui_widget_definition"}, {"reference": placement.MARKER}])
        self.assertEqual(refs["native"], "unchanged UI")
        self.assertEqual(len(record["conflicts"]), 2)
        self.assertEqual({check["kind"] for check in record["checks"]}, {"weapons", "netgame_equipment"})
        self.assertTrue(all(check["registry_slot"] == 1 and check["retail_normal_weapon"] == self.rocket
                            and check["effective_normal_weapon"] == self.flame for check in record["checks"]))
        self.assertTrue(all(item["severity"] == "info" for item in record["diagnostics"]))
        self.assertTrue(record["placements_preserved"] and record["registry_preserved"])
        self.assertEqual(record["gameplay_validation"], "pending")

    def test_engine_native_records_actionable_default_remap_without_marker_or_rewrite(self):
        overlay, record = self.audit("engine-native")
        self.assertIsNone(overlay)
        self.assertIsNone(record["capability"])
        self.assertEqual(len(record["diagnostics"]), 2)
        self.assertTrue(all(item["code"] == "native_weapon_remap_conflict" and item["severity"] == "warning" for item in record["diagnostics"]))
        self.assertTrue(all(check["effective_normal_weapon"] == self.rocket for check in record["checks"]))
        self.assertEqual(self.repairs, [])

    def test_no_conflict_no_capability_even_with_explicit_policy(self):
        body = copy.deepcopy(self.scenario_body)
        body["weapon_palette"][0]["name"] = self.pistol
        collection = dict(self.collection_body, permutations=[{"item": self.pistol, "weight": "100"}])
        for root, scenario in ((self.source, self.original_scenario), (self.working, self.scenario)):
            self.tag(root, scenario, body)
            self.tag(root, self.collection, collection)
        overlay, record = self.audit()
        self.assertIsNone(overlay)
        self.assertEqual(record["conflicts"], [])

    def test_zero_weight_permutation_does_not_enable_capability(self):
        body = dict(self.scenario_body, weapons=[])
        collection = dict(self.collection_body, permutations=[{"item": self.flame, "weight": "0"}])
        for root, scenario in ((self.source, self.original_scenario), (self.working, self.scenario)):
            self.tag(root, scenario, body)
            self.tag(root, self.collection, collection)
        overlay, record = self.audit()
        self.assertIsNone(overlay)
        self.assertEqual(record["checks"], [])

    def test_starting_equipment_only_flame_gets_capability_with_exact_start_rules(self):
        body = dict(self.scenario_body, weapons=[], netgame_equipment=[])
        start = {"flags": {name: "0" for name in ("no_grenades", "plasma_grenades_only", "type2_grenades_only", "type3_grenades_only")},
                 "type_0": "all_games", "type_1": "none", "type_2": "none", "type_3": "none",
                 **{f"item_collection_{slot}": self.collection if slot == 3 else ".item_collection" for slot in range(1, 7)}}
        body["starting_equipment"] = [start]
        for root, scenario in ((self.source, self.original_scenario), (self.working, self.scenario)):
            self.tag(root, scenario, body)
        overlay, record = self.audit()
        self.assertIsNotNone(overlay)
        self.assertEqual(len(record["checks"]), 1)
        self.assertEqual(record["checks"][0]["kind"], "starting_equipment")
        self.assertEqual(record["checks"][0]["collection_field"], "item_collection_3")
        self.assertEqual(record["source_placements"], record["placements"])

    def test_fractional_weights_and_inert_direct_spawns_do_not_enable_capability(self):
        for weight, palette in (("0.5", "-1"), ("0", "65535")):
            with self.subTest(weight=weight, palette=palette):
                body = copy.deepcopy(self.scenario_body)
                body["weapons"][0]["type"] = palette
                collection = dict(self.collection_body, permutations=[{"item": self.flame, "weight": weight}])
                for root, scenario in ((self.source, self.original_scenario), (self.working, self.scenario)):
                    self.tag(root, scenario, body)
                    self.tag(root, self.collection, collection)
                if (self.workspace / "weapon-placements").exists():
                    shutil.rmtree(self.workspace / "weapon-placements")
                self.protected.clear()
                overlay, record = self.audit()
                self.assertIsNone(overlay)
                self.assertEqual(record["checks"], [])

    def test_engine_native_child_merges_are_reported_as_unaudited_without_rejection(self):
        self.tag(self.source, self.original_scenario, dict(self.scenario_body, child_scenarios=["levels/child.scenario"]))
        overlay, record = self.audit("engine-native")
        self.assertIsNone(overlay)
        self.assertTrue(record["skip_compiled"])
        self.assertEqual(self.steps[-1]["status"], "unavailable")
        self.assertEqual(self.steps[-1]["diagnostics"][0]["code"], "weapon_placement_audit_unavailable")
        placement.verify_compiled_placements(FakeInvader(), self.base / "result.map", self.workspace, record, self.steps)
        self.assertEqual(self.steps[-1]["status"], "unavailable")

    def test_authored_capability_requires_flattened_children_before_claiming_preservation(self):
        self.tag(self.source, self.original_scenario, dict(self.scenario_body, child_scenarios=["levels/child.scenario"]))
        with self.assertRaisesRegex(ConversionError, "requires a flattened scenario"):
            self.audit()
        self.assertFalse((self.workspace / "weapon-placements").exists())

    def test_positions_timing_collection_weights_and_palette_substitution_are_not_silent(self):
        for field in ("position", "spawn_time", "item", "weight", "palette"):
            with self.subTest(field=field):
                body, collection = copy.deepcopy(self.scenario_body), copy.deepcopy(self.collection_body)
                if field in {"position", "spawn_time"}:
                    body["netgame_equipment"][0][field] = "changed"
                elif field == "palette":
                    body["weapon_palette"][0]["name"] = self.pistol
                else:
                    collection["permutations"][0][field] = self.pistol if field == "item" else "50"
                self.tag(self.working, self.scenario, body)
                self.tag(self.working, self.collection, collection)
                with self.assertRaisesRegex(ConversionError, "changed an authored placement"):
                    self.audit()
                self.protected.clear()

    def test_nan_negative_and_infinite_weights_rejected(self):
        for weight in ("nan", "inf", "-1", "32769", "malformed"):
            with self.subTest(weight=weight):
                self.tag(self.source, self.collection, dict(self.collection_body, permutations=[{"item": self.flame, "weight": weight}]))
                self.protected.clear()
                with self.assertRaisesRegex(ConversionError, "weight is invalid"):
                    self.audit()

    def test_missing_and_invalid_palette_dependencies_rejected(self):
        body = copy.deepcopy(self.scenario_body)
        body["weapons"][0]["type"] = "17"
        self.tag(self.source, self.original_scenario, body)
        with self.assertRaisesRegex(ConversionError, "invalid palette"):
            self.audit()
        self.tag(self.source, self.original_scenario, self.scenario_body)
        self.protected.clear()
        (self.source / self.flame).unlink()
        with self.assertRaisesRegex(ConversionError, "dependency is missing"):
            self.audit()

    def test_input_mutation_and_registry_provenance_mutation_rejected(self):
        with self.assertRaisesRegex(ConversionError, "changed an input tree"):
            self.audit(tool=FakeInvader(mutation=lambda: self.tag(self.working, self.flame, {"mutated": True})))
        self.protected.clear()
        manifest = Path(self.steps[0]["manifest"])
        manifest.write_text("{}")
        with self.assertRaisesRegex(ConversionError, "provenance changed"):
            self.audit()

    def test_registry_changed_after_canonical_stage_rejected(self):
        registry = self.registry.copy()
        registry[1] = self.pistol
        self.tag(self.working, placement.GLOBALS, {"weapon_list": [{"weapon": name} for name in registry]})
        with self.assertRaisesRegex(ConversionError, "differs from verified original"):
            self.audit()

    def test_existing_reference_mutation_during_attachment_rejected(self):
        with self.assertRaisesRegex(ConversionError, "changed an existing UI"):
            self.audit(tool=FakeInvader(edit_fault=lambda body: body["tags"][0].update(reference="ui/replaced.ui_widget_definition")))

    def test_repeated_audit_is_idempotent_and_does_not_duplicate_soul_marker(self):
        overlay, first = self.audit()
        workspace = self.base / "repeat"
        workspace.mkdir()
        second, record = self.audit(roots=[overlay, self.working], workspace=workspace)
        self.assertEqual(_tree(second), _tree(overlay))
        self.assertEqual(record["soul_references"].count(placement.MARKER), 1)
        self.assertEqual(self.repairs[-1]["inserted_references"], [])

    def test_reserved_marker_collision_and_engine_native_inheritance_rejected(self):
        self.tag(self.working, placement.MARKER, {"not": "a capability"})
        with self.assertRaisesRegex(ConversionError, "invalid count, class or payload"):
            self.audit()
        self.protected.clear()
        (self.working / placement.MARKER).write_bytes(placement.marker_bytes())
        with self.assertRaisesRegex(ConversionError, "requires the authored-default"):
            self.audit("engine-native")

    def test_capability_readback_verifies_final_graph_registry_and_link(self):
        overlay, record = self.audit()
        tool = FakeInvader(compiled_roots=[overlay, self.working])
        with patch.object(placement, "compiled_marker_index", return_value=17):
            placement.verify_compiled_placements(tool, self.base / "result.map", self.workspace, record, self.steps)
        self.assertEqual(self.steps[-1]["capability_absolute_index"], 17)
        self.assertTrue(self.steps[-1]["compiled_placements_preserved"])

    def test_compiled_marker_payload_link_and_placement_changes_rejected(self):
        overlay, record = self.audit()
        for field in ("marker", "link", "placement", "registry"):
            with self.subTest(field=field):
                copy_root = self.base / field
                shutil.copytree(self.working, copy_root)
                for name in _tree(overlay):
                    target = copy_root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(overlay / name, target)
                if field == "marker":
                    (copy_root / placement.MARKER).write_bytes(placement.marker_bytes()[:-1] + b"X")
                elif field == "link":
                    self.tag(copy_root, placement.SOUL, {"tags": [{"reference": "ui/pause.ui_widget_definition"}]})
                elif field == "placement":
                    body = copy.deepcopy(self.scenario_body)
                    body["netgame_equipment"][0]["spawn_time"] = "15"
                    self.tag(copy_root, self.scenario, body)
                else:
                    self.tag(copy_root, placement.GLOBALS, {"weapon_list": []})
                target_workspace = self.base / (field + "-verification")
                (target_workspace / "weapon-placements").mkdir(parents=True)
                with patch.object(placement, "compiled_marker_index", return_value=17):
                    with self.assertRaises(ConversionError):
                        placement.verify_compiled_placements(FakeInvader(compiled_roots=[copy_root]), self.base / "result.map", target_workspace, record, [])


def synthetic_cache(path, marker_index=3, compressed=False, marker_name=None, class_bytes=b"#rts"):
    count = marker_index + 1
    name = (marker_name or placement.MARKER.removesuffix(".string_list")).replace("/", "\\").encode() + b"\0"
    arena = bytearray(36 + count * 32 + len(name))
    struct.pack_into("<4I", arena, 0, 0x803A6000 + 36, 0, 0, count)
    entry = 36 + marker_index * 32
    arena[entry:entry + 4] = class_bytes
    struct.pack_into("<I", arena, entry + 16, 0x803A6000 + 36 + count * 32)
    arena[-len(name):] = name
    header = bytearray(2048)
    header[:4], header[2044:2048] = b"daeh", b"toof"
    struct.pack_into("<I", header, 4, 5)
    struct.pack_into("<I", header, 8, 2048 + len(arena))
    struct.pack_into("<II", header, 16, 2048, len(arena))
    path.write_bytes(header + (zlib.compress(arena) if compressed else arena))


class CompiledMarkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name) / "result.map"

    def test_plain_and_compressed_exact_marker_is_addressable(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                synthetic_cache(self.cache, compressed=compressed)
                self.assertEqual(placement.compiled_marker_index(self.cache), 3)

    def test_last_addressable_marker_passes_and_next_slot_fails(self):
        synthetic_cache(self.cache, marker_index=32767, compressed=True)
        self.assertEqual(placement.compiled_marker_index(self.cache), 32767)
        synthetic_cache(self.cache, marker_index=32768, compressed=True)
        with self.assertRaisesRegex(ConversionError, "below absolute index 32768"):
            placement.compiled_marker_index(self.cache)

    def test_wrong_class_similar_name_and_truncated_compression_fail(self):
        for kwargs in ({"marker_name": "__native_policy/arbitrary_v1"}, {"class_bytes": b"rtsu"}):
            with self.subTest(kwargs=kwargs):
                synthetic_cache(self.cache, **kwargs)
                with self.assertRaises(ConversionError):
                    placement.compiled_marker_index(self.cache)
        synthetic_cache(self.cache, compressed=True)
        self.cache.write_bytes(self.cache.read_bytes()[:-3])
        with self.assertRaisesRegex(ConversionError, "incomplete"):
            placement.compiled_marker_index(self.cache)

    def test_forward_slash_cache_marker_name_cannot_enable_exact_runtime_contract(self):
        synthetic_cache(self.cache)
        self.cache.write_bytes(self.cache.read_bytes().replace(b"__native_policy\\authored_weapon_placements_v1", b"__native_policy/authored_weapon_placements_v1"))
        with self.assertRaisesRegex(ConversionError, "one resident string-list"):
            placement.compiled_marker_index(self.cache)

    def test_marker_payload_is_exact_and_bounded(self):
        encoded = placement.marker_bytes()
        placement.verify_marker(encoded)
        self.assertEqual(encoded[36:40], b"str#")
        self.assertEqual(encoded[96:], placement.PAYLOAD)
        self.assertEqual(struct.unpack_from(">I", encoded, 64)[0], 1)
        for data in (encoded[:-1], encoded + b"\0", encoded[:-1] + b"X", encoded[:64] + struct.pack(">I", 2) + encoded[68:]):
            with self.subTest(size=len(data)):
                with self.assertRaises(ConversionError):
                    placement.verify_marker(data)


if __name__ == "__main__":
    unittest.main()
