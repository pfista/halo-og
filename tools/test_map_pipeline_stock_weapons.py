"""Full original weapon closure, unique identity and registry boundaries."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.map_pipeline import stock_weapons as original
from tools.map_pipeline.backend import ConversionError, _tree


class FakeInvader:
    def __init__(self, mutation=None):
        self.mutation = mutation

    def load(self, root, name):
        return json.loads((Path(root) / name).read_text())

    def get(self, root, name, field):
        if self.mutation:
            callback, self.mutation = self.mutation, None
            callback()
        body = self.load(root, name)
        if field.startswith("weapon_list["):
            return body["weapon_list"][int(field.split("[")[1].split("]")[0])]
        if field in original.COMPLETION_FIELDS and field not in body:
            return "." + original.COMPLETION_FIELDS[field]
        return body[field]

    def count(self, root, name, field):
        return len(self.load(root, name)[field])

    def run(self, tool, *args):
        roots = [Path(args[index + 1]) for index, value in enumerate(args) if value == "-t"]
        root = roots[0]
        if tool == "dependency":
            def winner(name):
                return next((candidate / name for candidate in roots if (candidate / name).is_file()), None)
            found, pending = set(), [args[-1]]
            while pending:
                name = pending.pop()
                if name in found:
                    continue
                found.add(name)
                path = winner(name)
                if path:
                    pending += json.loads(path.read_text()).get("refs", [])
            found.remove(args[-1])
            return "\n".join(sorted(name if winner(name) else name + " [BROKEN]" for name in found))
        if tool == "edit":
            name, body = args[-1], self.load(root, args[-1])
            if "-L" in args:
                other = [f"{key} = {json.dumps(value, sort_keys=True)}" for key, value in sorted(body.items()) if key != "weapon_list"]
                block = [f"weapon_list[{len(body['weapon_list'])}] array"] + [f" └──weapon[{index}] = {value}" for index, value in enumerate(body["weapon_list"])]
                return "\n".join(other[:1] + block + other[1:])
            if "-E" in args:
                body["weapon_list"] = []
            if "-I" in args:
                body["weapon_list"] += [None] * int(args[args.index("-I") + 2])
            for index, value in enumerate(args):
                if value == "-S":
                    field = args[index + 1]
                    body["weapon_list"][int(field.split("[")[1].split("]")[0])] = args[index + 2]
            (root / name).write_text(json.dumps(body))
            return ""
        if tool != "refactor":
            raise AssertionError(tool)
        pairs = {args[index + 1]: args[index + 2] for index, value in enumerate(args) if value == "-T"}
        def replace(value):
            if isinstance(value, str):
                return pairs.get(value, value)
            if isinstance(value, list):
                return [replace(item) for item in value]
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            return value
        for path in list(root.rglob("*")):
            if path.is_file():
                name = path.relative_to(root).as_posix()
                target = root / pairs.get(name, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(replace(json.loads(path.read_text()))))
                if target != path:
                    path.unlink()
        return ""


class OriginalWeaponTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.stock, self.source, self.workspace = [self.base / name for name in ("stock", "source", "workspace")]
        for root in (self.stock, self.source, self.workspace):
            root.mkdir()
        self.weapon = "weapons/sniper/sniper.weapon"
        self.model = "weapons/sniper/sniper.model"
        self.hud = "weapons/sniper/sniper.weapon_hud_interface"
        self.bitmap = "ui/hud/shared.bitmap"
        self.projectile = "weapons/sniper/round.projectile"
        self.sound = "sound/sniper.sound"
        self.grenade = "weapons/grenade.equipment"
        self.scenario = "levels/custom/custom.scenario"
        self.identity = {"model": self.model, "weapon_type": "undefined", "label": "sr"}
        self.refs = [self.model, self.hud, self.projectile, self.sound]
        for root in (self.stock, self.source):
            self.tag(root, self.weapon, **self.identity, refs=self.refs, damage=50 if root == self.stock else 99)
            self.tag(root, self.model, refs=[self.bitmap], geometry="stock" if root == self.stock else "MCC")
            self.tag(root, self.hud, refs=[self.bitmap], width=1 if root == self.stock else 4)
            self.tag(root, self.bitmap, pixels="stock" if root == self.stock else "MCC")
            self.tag(root, self.projectile, damage=10 if root == self.stock else 100)
            self.tag(root, self.sound, audio="stock" if root == self.stock else "MCC")
            self.tag(root, self.grenade, refs=[self.bitmap])
        self.tag(self.stock, original.GLOBALS, weapon_list=[self.weapon, self.grenade], authored_setting="stock")
        self.extra = "weapons/mcc_only.weapon"
        self.tag(self.source, self.extra, model="weapons/mcc.model", weapon_type="undefined", label="mcc")
        self.tag(self.source, original.GLOBALS, weapon_list=[self.extra, self.weapon, self.extra], authored_setting="keep", nested={"difficulty": [1, 2, 3]})
        self.tag(self.source, self.scenario, refs=[self.weapon], authored_geometry=True)
        self.steps, self.repairs, self.protected = [], [], {}

    def tag(self, root, name, **body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
        return path

    def convert(self, tool=None):
        return original.canonical_weapon_overlay(tool or FakeInvader(), self.stock, [self.source, self.stock], set(), self.scenario,
                                                 self.workspace, self.steps, self.repairs, self.protected)

    def test_full_original_assets_registry_and_authored_globals_preserved(self):
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert()
        self.assertEqual({root: _tree(root) for root in before}, before)
        weapon = json.loads((overlay / self.weapon).read_text())
        self.assertEqual(weapon["damage"], 50)
        self.assertTrue(weapon["model"].startswith(original.NAMESPACE + "/"))
        for reference in weapon["refs"]:
            self.assertTrue(reference.startswith(original.NAMESPACE + "/"))
            self.assertTrue((overlay / reference).is_file())
        self.assertEqual(json.loads((overlay / weapon["refs"][2]).read_text())["damage"], 10)
        self.assertEqual(json.loads((overlay / weapon["refs"][3]).read_text())["audio"], "stock")
        for name in (self.bitmap, self.scenario, self.extra):
            self.assertFalse((overlay / name).exists())
        globals_output = json.loads((overlay / original.GLOBALS).read_text())
        self.assertEqual(globals_output["weapon_list"], [self.weapon, self.grenade])
        self.assertEqual(globals_output["authored_setting"], "keep")
        self.assertEqual(globals_output["nested"], {"difficulty": [1, 2, 3]})
        self.assertEqual(self.steps[-1]["removed_registry_references"], [self.extra])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertEqual(record["output_sha256"], _tree(overlay))
        self.assertIn(weapon["refs"][1], record["native_hud_tags"])
        self.assertEqual(self.steps[-1]["canonical_assets"], 7)

    def test_relocated_weapon_uses_unique_identity(self):
        relocated = "community/mp_sniper.weapon"
        self.tag(self.source, relocated, **self.identity, refs=self.refs, damage=500)
        self.tag(self.source, self.scenario, refs=[relocated])
        overlay = self.convert()
        self.assertEqual(json.loads((overlay / relocated).read_text())["damage"], 50)
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertEqual(record["identity_proofs"][relocated]["match"], "unique_stock_model_type_label")

    def test_unknown_scenario_weapon_blocks_before_output(self):
        self.tag(self.source, self.scenario, refs=[self.extra])
        with self.assertRaises(ConversionError) as error:
            self.convert()
        self.assertEqual(error.exception.code, "needs_profile")
        self.assertEqual(error.exception.details["unknown_weapons"][0]["weapon"], self.extra)
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def test_ambiguous_relocated_identity_is_not_guessed(self):
        relocated = "community/mp_sniper.weapon"
        self.tag(self.source, relocated, **self.identity, refs=self.refs)
        self.tag(self.source, self.scenario, refs=[relocated])
        self.tag(self.stock, "weapons/duplicate.weapon", **self.identity, refs=self.refs)
        with self.assertRaises(ConversionError) as error:
            self.convert()
        self.assertEqual(len(error.exception.details["unknown_weapons"][0]["stock_candidates"]), 2)

    def test_same_path_identity_wins_over_duplicate_stock_identity(self):
        self.tag(self.stock, "weapons/duplicate.weapon", **self.identity, refs=self.refs)
        self.assertTrue((self.convert() / self.weapon).is_file())

    def test_stock_globals_dependency_cannot_replace_authored_globals(self):
        self.tag(self.stock, self.weapon, **self.identity, refs=[original.GLOBALS])
        with self.assertRaisesRegex(ConversionError, "non-asset class"):
            self.convert()
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def test_shared_stock_dependencies_copied_once(self):
        second = "weapons/pistol/pistol.weapon"
        for root in (self.stock, self.source):
            self.tag(root, second, model=self.model, weapon_type="pistol", label="pi", refs=[self.bitmap])
        self.tag(self.source, self.scenario, refs=[self.weapon, second])
        copies = [name for name in _tree(self.convert()) if name.endswith(self.bitmap)]
        self.assertEqual(len(copies), 1)

    def test_input_mutation_detected_before_output(self):
        with self.assertRaisesRegex(ConversionError, "changed an input"):
            self.convert(FakeInvader(lambda: self.tag(self.source, self.bitmap, pixels="changed")))
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def test_previous_source_fingerprinted_model_namespace_recognized(self):
        fingerprint = hashlib.sha256(json.dumps(_tree(self.stock), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        alias = f"{original.NAMESPACE}/{fingerprint[:16]}/{self.model}"
        self.tag(self.source, self.weapon, **dict(self.identity, model=alias), refs=[alias])
        self.tag(self.source, alias, refs=[])
        self.assertEqual(json.loads((self.convert() / self.weapon).read_text())["damage"], 50)

    def test_previous_library_model_namespace_survives_stock_expansion(self):
        old_fingerprint = hashlib.sha256(json.dumps(_tree(self.stock), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        old_alias = f"{original.NAMESPACE}/{old_fingerprint[:16]}/{self.model}"
        self.tag(self.source, self.weapon, **dict(self.identity, model=old_alias), refs=[old_alias], damage=999)
        self.tag(self.source, old_alias, geometry="previous converted library")
        self.tag(self.stock, "weapons/new_npc/npc.weapon", model="weapons/new_npc/npc.model", weapon_type="undefined", label="npc", refs=[])
        current_fingerprint = hashlib.sha256(json.dumps(_tree(self.stock), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertNotEqual(old_fingerprint, current_fingerprint)
        overlay = self.convert()
        output = json.loads((overlay / self.weapon).read_text())
        self.assertEqual(output["damage"], 50)
        self.assertEqual(output["model"], f"{original.NAMESPACE}/{current_fingerprint[:16]}/{self.model}")
        self.assertEqual(json.loads((overlay / output["model"]).read_text())["geometry"], "stock")
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertTrue(record["identity_proofs"][self.weapon]["previous_native_model_namespace"])

    def test_previous_native_alias_requires_exact_shape_and_unique_current_identity(self):
        bad_alias = f"{original.NAMESPACE}/not-a-stock-hash/{self.model}"
        self.tag(self.source, self.weapon, **dict(self.identity, model=bad_alias), refs=[bad_alias])
        self.tag(self.source, bad_alias)
        with self.assertRaises(ConversionError):
            self.convert()
        self.protected.clear()
        alias = f"{original.NAMESPACE}/0123456789abcdef/{self.model}"
        self.tag(self.source, self.weapon, **dict(self.identity, model=alias), refs=[alias])
        self.tag(self.source, alias)
        self.tag(self.stock, "weapons/duplicate.weapon", **self.identity, refs=self.refs)
        with self.assertRaises(ConversionError) as error:
            self.convert()
        self.assertEqual(len(error.exception.details["unknown_weapons"][0]["stock_candidates"]), 2)
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def unfinished_weapon(self, path="weapons/gravity rifle/gravity rifle.weapon", completed=True, partial=False):
        identity = {"model": "weapons/gravity rifle/gravity rifle.model", "weapon_type": "undefined", "label": "ar"}
        self.tag(self.stock, identity["model"], geometry="original prototype")
        self.tag(self.stock, path, **identity, damage=1, refs=[identity["model"]])
        self.tag(self.source, identity["model"], geometry="authored original-lineage geometry")
        fields, refs = {}, [identity["model"]]
        if completed:
            fields["first_person_model"] = "weapons/gravity rifle/finished_fp.model"
            self.tag(self.source, fields["first_person_model"], geometry="finished FP")
            refs.append(fields["first_person_model"])
            if not partial:
                fields["first_person_animations"] = "weapons/gravity rifle/finished_fp.model_animations"
                fields["hud_interface"] = "weapons/gravity rifle/finished.weapon_hud_interface"
                self.tag(self.source, fields["first_person_animations"], frames="finished animations")
                self.tag(self.source, fields["hud_interface"], refs=[self.bitmap], width=4)
                refs.extend([fields["first_person_animations"], fields["hud_interface"]])
        self.tag(self.source, path, **identity, **fields, damage=777, refs=refs, melee_only=True)
        self.tag(self.stock, original.GLOBALS, weapon_list=[self.weapon, self.grenade, path], authored_setting="stock")
        self.tag(self.source, original.GLOBALS, weapon_list=[path, self.weapon, self.grenade], authored_setting="keep")
        self.tag(self.source, self.scenario, refs=[path, self.weapon])
        return path, fields

    def test_finished_original_gravity_keeps_authored_gameplay_fp_and_mcc_hud(self):
        path, fields = self.unfinished_weapon()
        before = _tree(self.source)
        overlay = self.convert()
        self.assertEqual(_tree(self.source), before)
        self.assertFalse((overlay / path).exists())
        self.assertEqual(json.loads((self.source / path).read_text())["damage"], 777)
        completion = self.steps[-1]["authored_original_completions"][path]
        self.assertEqual(set(completion["authored_completed_fields"]), set(original.COMPLETION_FIELDS))
        self.assertEqual(set(completion["stock_missing_fields"]), set(original.COMPLETION_FIELDS))
        self.assertEqual(completion["remaining_missing_fields"], [])
        self.assertIn(fields["hud_interface"], self.steps[-1]["authored_completion_hud_tags"])
        self.assertNotIn(fields["hud_interface"], self.steps[-1]["native_hud_tags"])
        self.assertEqual(completion["gameplay_validation"], "pending")
        self.assertEqual(json.loads((overlay / self.weapon).read_text())["damage"], 50)

    def test_partial_original_npc_completion_retained_with_precise_remaining_gaps(self):
        path, fields = self.unfinished_weapon("weapons/plasma cannon/plasma cannon.weapon", partial=True)
        overlay = self.convert()
        self.assertFalse((overlay / path).exists())
        completion = self.steps[-1]["authored_original_completions"][path]
        self.assertEqual(completion["remaining_missing_fields"], ["first_person_animations", "hud_interface"])
        self.assertIn("remaining player-interface gaps", completion["diagnostic"])
        self.assertIn("first_person_model", completion["authored_completed_fields"])

    def test_uncompleted_original_prototype_keeps_original_asset_and_reports_catalog_gaps(self):
        path, _ = self.unfinished_weapon(completed=False)
        overlay = self.convert()
        self.assertEqual(json.loads((overlay / path).read_text())["damage"], 1)
        self.assertFalse(self.steps[-1]["authored_original_completions"])
        catalog = self.steps[-1]["original_asset_catalog"][path]
        self.assertEqual(catalog["classification"], "unfinished_original_player_interface")
        self.assertEqual(set(catalog["missing_fields"]), set(original.COMPLETION_FIELDS))

    def test_complete_original_player_gun_modifications_still_canonical(self):
        # Use existing original assets as complete player-use references.
        for root in (self.stock, self.source):
            body = json.loads((root / self.weapon).read_text())
            body.update(first_person_model=self.model, first_person_animations="weapons/sniper/fp.model_animations", hud_interface=self.hud)
            body["refs"].append(body["first_person_animations"])
            self.tag(root, self.weapon, **body)
            self.tag(root, body["first_person_animations"], frames="original" if root == self.stock else "modified")
        overlay = self.convert()
        self.assertEqual(json.loads((overlay / self.weapon).read_text())["damage"], 50)
        self.assertFalse(self.steps[-1]["authored_original_completions"])
        self.assertEqual(self.steps[-1]["original_asset_catalog"][self.weapon]["classification"], "complete_original_weapon")

    def test_completion_cannot_smuggle_unrelated_new_weapon_dependency(self):
        path, _ = self.unfinished_weapon()
        body = json.loads((self.source / path).read_text())
        body["refs"].append(self.extra)
        self.tag(self.source, path, **body)
        with self.assertRaises(ConversionError) as error:
            self.convert()
        self.assertIn("original Halo 1 lineage", str(error.exception))
        self.assertEqual(error.exception.details["unrelated_weapon"], self.extra)
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def test_registry_only_original_npc_completion_rooted_after_native_prefix(self):
        path, fields = self.unfinished_weapon("weapons/plasma cannon/plasma cannon.weapon")
        self.tag(self.stock, original.GLOBALS, weapon_list=[self.weapon, self.grenade], authored_setting="stock")
        self.tag(self.source, original.GLOBALS, weapon_list=[self.extra, path, self.weapon, self.grenade], authored_setting="keep")
        self.tag(self.source, self.scenario, refs=[self.weapon])
        overlay = self.convert()
        registry = json.loads((overlay / original.GLOBALS).read_text())["weapon_list"]
        self.assertEqual(registry, [self.weapon, self.grenade, path])
        self.assertIn(path, self.steps[-1]["authored_original_completions"])
        self.assertEqual(self.steps[-1]["additional_original_registry"], [path])
        self.assertEqual(self.steps[-1]["removed_registry_references"], [self.extra])
        self.assertFalse((overlay / path).exists())
        self.assertNotIn(fields["hud_interface"], self.steps[-1]["native_hud_tags"])

    def test_registry_only_original_npc_without_completion_still_uses_canonical_original(self):
        path, _ = self.unfinished_weapon("weapons/plasma cannon/plasma cannon.weapon", completed=False)
        self.tag(self.stock, original.GLOBALS, weapon_list=[self.weapon, self.grenade], authored_setting="stock")
        self.tag(self.source, self.scenario, refs=[self.weapon])
        overlay = self.convert()
        self.assertEqual(json.loads((overlay / original.GLOBALS).read_text())["weapon_list"], [self.weapon, self.grenade, path])
        self.assertEqual(json.loads((overlay / path).read_text())["damage"], 1)
        self.assertFalse(self.steps[-1]["authored_original_completions"])

    def test_original_completion_cannot_occupy_another_original_registry_path(self):
        gravity, _ = self.unfinished_weapon()
        self.tag(self.source, self.weapon, **json.loads((self.source / gravity).read_text()))
        self.tag(self.source, self.scenario, refs=[self.weapon])
        with self.assertRaises(ConversionError) as error:
            self.convert()
        self.assertIn("different original registry weapon path", str(error.exception))
        self.assertEqual(error.exception.details["weapon"], self.weapon)
        self.assertEqual(error.exception.details["completion_ancestor"], gravity)
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def test_all_output_hud_payloads_are_marked_native(self):
        self.unfinished_weapon()
        overlay = self.convert()
        expected = sorted(name for name in _tree(overlay) if Path(name).suffix[1:] in original.HUD_CLASSES)
        self.assertEqual(self.steps[-1]["native_hud_tags"], expected)


if __name__ == "__main__":
    unittest.main()
