"""Offline approval binding and exact reference omission regressions."""
import copy
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tools.map_pipeline import weapon_omissions as omission
from tools.map_pipeline.backend import ConversionError, _tree, legacy
from tools.map_pipeline.weapon_lineage import load_catalog
from tools.map_pipeline.weapon_placements import NET_FIELDS, START_FIELDS, WEAPON_FIELDS


class FakeInvader:
    def __init__(self, fault=None, mutation=None):
        self.fault, self.mutation = fault, mutation

    def read(self, root, tag):
        return json.loads((Path(root) / tag).read_text())

    def selected(self, body, field):
        for part in field.split("."):
            match = re.fullmatch(r"(.+)\[([0-9]+)\]", part)
            body = body[match[1]][int(match[2])] if match else body[part]
        return body

    def get(self, root, tag, field):
        return str(self.selected(self.read(root, tag), field))

    def count(self, root, tag, field):
        return len(self.selected(self.read(root, tag), field))

    def refs(self, body):
        if isinstance(body, dict):
            return set().union(*(self.refs(value) for value in body.values())) if body else set()
        if isinstance(body, list):
            return set().union(*(self.refs(value) for value in body)) if body else set()
        if isinstance(body, str) and "." in body and not body.startswith("."):
            return {body} if body.rsplit(".", 1)[1] in omission.CLASSES else set()
        return set()

    def listing(self, body):
        lines = []

        def value(key, data, depth):
            prefix = "" if not depth else " " + "│   " * (depth - 1) + "├──"
            if isinstance(data, list):
                lines.append(prefix + f"{key}[{len(data)}]  array")
                for index, child in enumerate(data):
                    value(f"{key}[{index}]", child, depth + 1)
            elif isinstance(data, dict):
                lines.append(prefix + key + "  struct")
                for child, content in data.items():
                    value(child, content, depth + 1)
            else:
                kind = "dependency" if (isinstance(data, str) and data.rsplit(".", 1)[-1] in omission.CLASSES) or data == "" else "string"
                lines.append(prefix + key + (f" ({data})" if data != "" else "") + "  " + kind)
        for key, data in body.items():
            value(key, data, 0)
        return "\n".join(lines)

    def run(self, tool, *args):
        roots = [Path(args[i + 1]) for i, arg in enumerate(args[:-1]) if arg == "-t"]
        tag = args[-1]
        if self.mutation:
            mutation, self.mutation = self.mutation, None
            mutation()
        if tool == "dependency":
            winning = {}
            for root in reversed(roots):
                winning.update({name: root for name in _tree(root)})
            if "-R" in args:
                return "\n".join(sorted(name for name, root in winning.items() if tag in self.refs(self.read(root, name))))
            result = set()

            def walk(name):
                for ref in self.refs(self.read(winning[name], name)):
                    if ref in result:
                        continue
                    result.add(ref)
                    if ref in winning and "-r" in args:
                        walk(ref)
            walk(tag)
            return "\n".join(sorted(ref if ref in winning else ref + " [BROKEN]" for ref in result))
        if tool == "edit":
            body = self.read(roots[0], tag)
            if "-L" in args:
                return self.listing(body)
            field = args[args.index("-S") + 1] if "-S" in args else args[args.index("-E") + 1]
            parent, leaf = field.rsplit(".", 1) if "." in field else (None, field)
            owner = self.selected(body, parent) if parent else body
            if "-S" in args:
                owner[leaf] = args[args.index("-S") + 2]
            else:
                match = re.fullmatch(r"(.+)\[([0-9]+)\]", leaf)
                del owner[match[1]][int(match[2])]
            if self.fault:
                self.fault(body)
            (roots[0] / tag).write_text(json.dumps(body, sort_keys=True))
            return ""
        raise AssertionError(tool)


class OmissionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source, self.working, self.workspace = [self.base / name for name in ("source", "working", "workspace")]
        for root in (self.source, self.working, self.workspace):
            root.mkdir()
        self.weapon = "community/custom/excluded prototype.weapon"
        self.other = "weapons/retained/retained.weapon"
        self.model = "community/custom/world.model"
        self.scenario = "levels/another_map/arena.scenario"
        self.collection = "item collections/custom/random.item_collection"
        self.scenario_body = {"child_scenarios": [], "weapon_palette": [], "weapons": [],
                              "netgame_equipment": [], "starting_equipment": [], "player_starting_profile": [],
                              "unchanged": "authored scenario details"}
        self.tag(self.source, self.weapon, {"model": self.model, "weapon_type": "rifle", "label": "cut", "rounds": "9"})
        self.tag(self.source, self.model, {"geometry": "reviewed model"})
        self.tag(self.source, self.other, {"model": ".model", "weapon_type": "pistol", "label": "retained"})
        self.tag(self.source, omission.GLOBALS, {"weapon_list": [{"weapon": self.other}], "unchanged": "authored globals"})
        self.collection_body = {"default_spawn_time": "37", "permutations": [
            {"item": self.other, "weight": "25.000000"}, {"item": self.weapon, "weight": "11.000000"},
            {"item": self.other, "weight": "63.000000"}]}
        self.tag(self.source, self.collection, self.collection_body)
        self.scenario_body["netgame_equipment"] = [self.net(self.collection)]
        self.tag(self.source, self.scenario, self.scenario_body)
        self.sync()
        self.steps, self.omissions, self.protected = [], [], {}
        self.catalog = self.review()

    def tag(self, root, name, body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, sort_keys=True))

    def sync(self):
        shutil.copytree(self.source, self.working, dirs_exist_ok=True)

    def fields(self, fields):
        result = {}
        for field in fields:
            current = result
            parts = field.split(".")
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = "0"
        return result

    def net(self, collection):
        return dict(self.fields(NET_FIELDS), item_collection=collection)

    def start(self, collection):
        return dict(self.fields(START_FIELDS), **{f"item_collection_{i}": collection if i == 1 else ".item_collection" for i in range(1, 7)})

    def direct(self, index, name="-1"):
        return dict(self.fields(WEAPON_FIELDS), type=str(index), name=name, rounds_reserved="41", rounds_loaded="7")

    def review(self):
        inventory = _tree(self.source)
        closure = {name: inventory[name] for name in (self.weapon, self.model)}
        entry = {"asset_id": "explicitly-excluded", "variant_id": "reviewed-variant",
                 "weapon": self.weapon, "weapon_sha256": closure[self.weapon],
                 "identity": {"model": self.model, "weapon_type": "rifle", "label": "cut"},
                 "closure_sha256": closure, "outcome": "omit", "ancestor": None, "evidence": [],
                 "reason": "User explicitly excludes this exact weapon variant",
                 "approval": {"kind": "user-decision", "date": "2026-10-08",
                              "reference": "thread://01a116b1-1414-7ea2-ad25-7cdf34ebce54",
                              "statement": "Omit this weapon's references and report every omission"}}
        path = self.base / "catalog.json"
        path.write_text(json.dumps({"schema_version": 1, "id": "test-lineage", "version": "1.0.0", "entries": [entry]}))
        return load_catalog(path)

    def convert(self, tool=None, catalog=None, roots=None, **kwargs):
        return omission.omit_reviewed_weapons(tool or FakeInvader(), catalog or self.catalog, self.source,
                                             roots or [self.working], self.scenario, self.workspace,
                                             self.steps, self.omissions, self.protected, **kwargs)

    def manifest(self):
        return json.loads(Path(self.steps[-1]["manifest"]).read_text())

    def test_generic_mixed_collection_preserves_order_weights_spawn_and_sources(self):
        before = {root: _tree(root) for root in (self.source, self.working)}
        overlay = self.convert()
        self.assertEqual(set(_tree(overlay)), {self.collection})
        expected = copy.deepcopy(self.collection_body)
        del expected["permutations"][1]
        self.assertEqual(FakeInvader().read(overlay, self.collection), expected)
        self.assertEqual({root: _tree(root) for root in before}, before)
        receipt = self.manifest()
        self.assertEqual(receipt["omitted_reference_count"], 1)
        self.assertEqual(receipt["references"][0]["field"], "permutations[1].item")
        self.assertEqual(receipt["references"][0]["original_tag_sha256"], before[self.source][self.collection])
        self.assertEqual(receipt["references"][0]["reviewed_lineage"][0]["original_source_closure_sha256"], self.catalog["entries"][0]["closure_sha256"])
        manifest = Path(self.steps[-1]["manifest"])
        self.assertEqual(self.protected[manifest], legacy.digest(manifest))
        self.assertTrue(receipt["source_unchanged"])

    def test_empty_collection_removes_spawn_and_clears_only_starting_slot(self):
        self.tag(self.source, self.collection, dict(self.collection_body, permutations=[{"item": self.weapon, "weight": "9"}]))
        self.scenario_body["starting_equipment"] = [self.start(self.collection)]
        self.tag(self.source, self.scenario, self.scenario_body)
        self.sync()
        overlay = self.convert()
        body = FakeInvader().read(overlay, self.scenario)
        self.assertEqual(body["netgame_equipment"], [])
        self.assertEqual(body["starting_equipment"][0]["item_collection_1"], "")
        self.assertEqual(body["starting_equipment"][0]["item_collection_2"], ".item_collection")
        self.assertEqual(self.manifest()["omitted_reference_count"], 3)

    def test_direct_palette_and_registry_removal_remaps_kept_instances(self):
        self.scenario_body["weapon_palette"] = [{"name": self.other}, {"name": self.weapon}, {"name": self.other}]
        self.scenario_body["weapons"] = [self.direct(2), self.direct(1), self.direct(0), self.direct(2)]
        self.scenario_body["player_starting_profile"] = [{"primary_weapon": self.weapon, "secondary_weapon": self.other, "ammo": "42"}]
        self.tag(self.source, self.scenario, self.scenario_body)
        self.tag(self.source, omission.GLOBALS, {"weapon_list": [{"weapon": self.other}, {"weapon": self.weapon}, {"weapon": self.other}], "unchanged": "authored globals"})
        self.sync()
        overlay = self.convert()
        body = FakeInvader().read(overlay, self.scenario)
        self.assertEqual([item["type"] for item in body["weapons"]], ["1", "0", "1"])
        self.assertEqual([item["rounds_reserved"] for item in body["weapons"]], ["41"] * 3)
        self.assertEqual(body["weapon_palette"], [{"name": self.other}] * 2)
        self.assertEqual(body["player_starting_profile"][0], {"primary_weapon": "", "secondary_weapon": self.other, "ammo": "42"})
        self.assertEqual(FakeInvader().read(overlay, omission.GLOBALS)["weapon_list"], [{"weapon": self.other}] * 2)
        receipt = self.manifest()
        self.assertEqual(receipt["omitted_reference_count"], 5)
        self.assertEqual(len(receipt["palette_index_adjustments"]), 2)
        self.assertNotEqual(receipt["source_placement_graph"], receipt["omitted_placement_graph"])

    def test_named_direct_instances_fail_closed_before_overlay(self):
        self.scenario_body["weapon_palette"] = [{"name": self.weapon}, {"name": self.other}]
        self.scenario_body["weapons"] = [self.direct(0), self.direct(1, "3")]
        self.tag(self.source, self.scenario, self.scenario_body)
        self.sync()
        with self.assertRaisesRegex(ConversionError, "named object links"):
            self.convert()
        self.assertFalse((self.workspace / "weapon-omissions").exists())

    def test_unrecognized_reachable_reference_shape_cannot_be_omitted(self):
        self.scenario_body["unreviewed_script_operand"] = self.weapon
        self.tag(self.source, self.scenario, self.scenario_body)
        self.sync()
        with self.assertRaisesRegex(ConversionError, "unsupported reachable reference shape"):
            self.convert()
        self.assertFalse((self.workspace / "weapon-omissions").exists())

    def test_empty_collection_unknown_referrer_fails_closed(self):
        self.tag(self.source, self.collection, dict(self.collection_body, permutations=[{"item": self.weapon, "weight": "9"}]))
        self.scenario_body["unreviewed_collection_operand"] = self.collection
        self.tag(self.source, self.scenario, self.scenario_body)
        self.sync()
        with self.assertRaisesRegex(ConversionError, "unsupported reachable reference shape"):
            self.convert()

    def test_changed_raw_dependency_does_not_match_approved_variant(self):
        self.tag(self.source, self.model, {"geometry": "unreviewed modification"})
        self.sync()
        with self.assertRaisesRegex(ConversionError, "differs from its explicitly approved variant"):
            self.convert()

    def test_changed_winning_dependency_cannot_use_valid_raw_receipt(self):
        override = self.base / "override"
        self.tag(override, self.model, {"geometry": "unreviewed override"})
        with self.assertRaisesRegex(ConversionError, "changed beyond verified format conversion"):
            self.convert(roots=[override, self.working])

    def test_derived_model_snapshot_accepts_only_verified_format_bytes(self):
        new_model = self.model.removesuffix(".model") + ".gbxmodel"
        for root in (self.source, self.working):
            (root / self.model).rename(root / new_model)
            body = FakeInvader().read(root, self.weapon)
            body["model"] = new_model
            self.tag(root, self.weapon, body)
        self.model = new_model
        self.catalog = self.review()
        native_model = new_model.removesuffix(".gbxmodel") + ".model"
        (self.working / new_model).rename(self.working / native_model)
        self.tag(self.working, native_model, {"geometry": "verified model layout"})
        body = FakeInvader().read(self.working, self.weapon)
        body["model"] = native_model
        self.tag(self.working, self.weapon, body)
        self.convert(lineage_derived=_tree(self.working))
        self.assertTrue(self.manifest()["references"][0]["reviewed_lineage"][0]["verified_format_conversion"])

    def test_unrelated_editor_mutation_rejected_by_full_native_readback(self):
        with self.assertRaisesRegex(ConversionError, "outside its approved reference edits"):
            self.convert(tool=FakeInvader(fault=lambda body: body.update(default_spawn_time="999")))
        self.assertEqual(self.steps, [])
        self.assertEqual(self.omissions, [])

    def test_authored_whitespace_inside_unrelated_strings_is_not_normalized(self):
        body = dict(self.collection_body, author_notes="keep  these   exact spaces")
        self.tag(self.source, self.collection, body)
        self.sync()
        with self.assertRaisesRegex(ConversionError, "outside its approved reference edits"):
            self.convert(tool=FakeInvader(fault=lambda body: body.update(author_notes="keep these exact spaces")))
        self.assertEqual(FakeInvader().read(self.source, self.collection)["author_notes"], "keep  these   exact spaces")

    def test_input_tree_mutation_detected_even_on_failure(self):
        def mutate():
            self.tag(self.source, self.model, {"geometry": "changed while authoring"})
        with self.assertRaisesRegex(ConversionError, "changed an input tree"):
            self.convert(tool=FakeInvader(mutation=mutate))

    def test_no_used_exclusion_does_not_create_overlay(self):
        self.tag(self.source, self.collection, dict(self.collection_body, permutations=[{"item": self.other, "weight": "9"}]))
        self.sync()
        self.assertIsNone(self.convert())
        self.assertFalse((self.workspace / "weapon-omissions").exists())
        self.assertEqual(self.steps, [])

    def test_child_scenario_cannot_reintroduce_excluded_weapon(self):
        self.scenario_body["child_scenarios"] = [{"child_scenario": self.scenario}]
        self.tag(self.source, self.scenario, self.scenario_body)
        self.sync()
        with self.assertRaisesRegex(ConversionError, "flattened scenario"):
            self.convert()


if __name__ == "__main__":
    unittest.main()
