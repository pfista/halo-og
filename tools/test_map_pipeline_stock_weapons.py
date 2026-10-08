"""Full original weapon closure, unique identity and registry boundaries."""
import hashlib
import json
from pathlib import Path
import shutil
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
        if field.startswith(("weapon_list[", "tags[")):
            array = field.split("[")[0]
            return body[array][int(field.split("[")[1].split("]")[0])]
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
                    body = json.loads(path.read_text())
                    pending += body.get("refs", [])
                    pending += body.get("tags", [])
            found.remove(args[-1])
            return "\n".join(sorted(name if winner(name) else name + " [BROKEN]" for name in found))
        if tool == "edit":
            name = args[-1]
            if "-N" in args:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"tags": []}))
            body = self.load(root, name)
            if "-L" in args:
                if "weapon_list" not in body:
                    return json.dumps(body, sort_keys=True)
                other = [f"{key} = {json.dumps(value, sort_keys=True)}" for key, value in sorted(body.items()) if key != "weapon_list"]
                block = [f"weapon_list[{len(body['weapon_list'])}] array"] + [f" └──weapon[{index}] = {value}" for index, value in enumerate(body["weapon_list"])]
                return "\n".join(other[:1] + block + other[1:])
            if "-E" in args:
                field = args[args.index("-E") + 1].split("[")[0]
                body[field] = []
            if "-I" in args:
                index = args.index("-I")
                field, count = args[index + 1], int(args[index + 2])
                position = len(body[field]) if args[index + 3] == "end" else int(args[index + 3])
                maximum = 20 if field == "weapon_list" else 200
                if len(body[field]) + count > maximum:
                    raise AssertionError(f"{field} exceeds the Invader limit of {maximum}")
                body[field][position:position] = [None] * count
            for index, value in enumerate(args):
                if value == "-S":
                    field = args[index + 1]
                    array = field.split("[")[0]
                    body[array][int(field.split("[")[1].split("]")[0])] = args[index + 2]
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
        self.soul = "ui/shell/multiplayer.ui_widget_collection"
        self.resident_collection = "__native_policy/admitted_weapon_assets_v1.tag_collection"
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
            self.tag(root, self.soul, tags=[self.bitmap, self.sound],
                     authored_layout="stock" if root == self.stock else "keep")
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

    def convert(self, tool=None, **kwargs):
        return original.canonical_weapon_overlay(tool or FakeInvader(), self.stock, [self.source, self.stock], set(), self.scenario,
                                                 self.workspace, self.steps, self.repairs, self.protected, **kwargs)

    def assert_resident_roots(self, overlay, weapons):
        source_soul = json.loads((self.source / self.soul).read_text())
        output_soul = json.loads((overlay / self.soul).read_text())
        self.assertEqual(output_soul["tags"], [*source_soul["tags"], self.resident_collection])
        self.assertEqual({key: value for key, value in output_soul.items() if key != "tags"},
                         {key: value for key, value in source_soul.items() if key != "tags"})
        resident = json.loads((overlay / self.resident_collection).read_text())
        self.assertEqual(resident["tags"], sorted(weapons))
        dependencies = set(FakeInvader().run("dependency", "-r", "-t", overlay, "-t", self.source,
                                              "-t", self.stock, self.soul).splitlines())
        self.assertIn(self.resident_collection, dependencies)
        self.assertTrue(set(weapons).issubset(dependencies))
        self.assertFalse(any(name.endswith(" [BROKEN]") for name in dependencies))
        return dependencies

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

    def test_original_glow_dependency_is_copied_and_references_are_relocated(self):
        glow = "weapons/energy sword/c energy sword glow lower.glow"
        for root in (self.stock, self.source):
            self.tag(root, self.weapon, **self.identity, refs=self.refs + [glow])
            self.tag(root, glow, refs=[self.bitmap], appearance="stock" if root == self.stock else "MCC")
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert()
        weapon = json.loads((overlay / self.weapon).read_text())
        relocated = next(name for name in weapon["refs"] if name.endswith(".glow"))
        self.assertTrue(relocated.startswith(original.NAMESPACE + "/"))
        output = json.loads((overlay / relocated).read_text())
        self.assertEqual(output["appearance"], "stock")
        self.assertTrue(output["refs"][0].startswith(original.NAMESPACE + "/"))
        self.assertTrue((overlay / output["refs"][0]).is_file())
        self.assertEqual({root: _tree(root) for root in before}, before)

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
        self.assertIn("without admitted lineage or an explicit exception", str(error.exception))
        self.assertEqual(error.exception.details["unrelated_weapon"], self.extra)
        self.assertFalse((self.workspace / "canonical-weapons").exists())

    def test_registry_only_original_npc_completion_resident_without_registry_append(self):
        path, fields = self.unfinished_weapon("weapons/plasma cannon/plasma cannon.weapon")
        self.tag(self.stock, original.GLOBALS, weapon_list=[self.weapon, self.grenade], authored_setting="stock")
        self.tag(self.source, original.GLOBALS, weapon_list=[self.extra, path, self.weapon, self.grenade], authored_setting="keep")
        self.tag(self.source, self.scenario, refs=[self.weapon])
        overlay = self.convert()
        registry = json.loads((overlay / original.GLOBALS).read_text())["weapon_list"]
        self.assertEqual(registry, [self.weapon, self.grenade])
        self.assertIn(path, self.steps[-1]["authored_original_completions"])
        self.assertEqual(self.steps[-1]["additional_original_registry"], [])
        self.assertEqual(self.steps[-1]["resident_original_weapon_roots"], [path])
        self.assertEqual(self.steps[-1]["removed_registry_references"], sorted([self.extra, path]))
        self.assert_resident_roots(overlay, [path])
        self.assertFalse((overlay / path).exists())
        self.assertNotIn(fields["hud_interface"], self.steps[-1]["native_hud_tags"])

    def test_registry_only_original_npc_without_completion_still_uses_canonical_original(self):
        path, _ = self.unfinished_weapon("weapons/plasma cannon/plasma cannon.weapon", completed=False)
        self.tag(self.stock, original.GLOBALS, weapon_list=[self.weapon, self.grenade], authored_setting="stock")
        self.tag(self.source, self.scenario, refs=[self.weapon])
        overlay = self.convert()
        self.assertEqual(json.loads((overlay / original.GLOBALS).read_text())["weapon_list"], [self.weapon, self.grenade])
        self.assert_resident_roots(overlay, [path])
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

    def native_registry(self, additional=()):
        """Model the native twelve-gun/two-grenade index prefix."""
        guns = [self.weapon]
        for index in range(11):
            name = f"weapons/original_{index}/original_{index}.weapon"
            for root in (self.stock, self.source):
                self.tag(root, name, model=self.model, weapon_type="undefined", label=f"w{index}",
                         refs=self.refs, damage=50 if root == self.stock else 999)
            guns.append(name)
        second_grenade = "weapons/second_grenade.equipment"
        for root in (self.stock, self.source):
            self.tag(root, second_grenade, refs=[self.bitmap])
        prefix = guns + [self.grenade, second_grenade]
        self.tag(self.stock, original.GLOBALS, weapon_list=prefix, authored_setting="stock")
        self.tag(self.source, original.GLOBALS, weapon_list=[self.extra, *additional, *reversed(prefix)],
                 authored_setting="keep", nested={"difficulty": [1, 2, 3]})
        return prefix

    def test_original_fourteen_entry_order_and_placed_weapon_references_survive_canonicalization(self):
        prefix = self.native_registry()
        placement = {"palette_index": 0, "position": [1, 2, 3], "rotation": [0, 0, 1], "respawn_seconds": 30}
        self.tag(self.source, self.scenario, refs=[self.weapon], weapon_palette=[self.weapon], weapons=[placement])
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert()
        globals_output = json.loads((overlay / original.GLOBALS).read_text())
        self.assertEqual(len(prefix), 14)
        self.assertEqual(globals_output["weapon_list"], prefix)
        self.assertEqual(globals_output["nested"], {"difficulty": [1, 2, 3]})
        self.assertEqual({root: _tree(root) for root in before}, before)
        self.assertEqual(json.loads((self.source / self.scenario).read_text())["weapons"], [placement])
        self.assertFalse((overlay / self.scenario).exists())
        self.assertEqual(json.loads((overlay / self.weapon).read_text())["damage"], 50)

    def restored_weapon(self, name="weapons/restored/restored.weapon", model_class="model"):
        folder = str(Path(name).parent)
        identity = {"model": f"{folder}/world.{model_class}", "weapon_type": "plasma_pistol", "label": "recovered"}
        fields = {"first_person_model": f"{folder}/fp.{model_class}",
                  "first_person_animations": f"{folder}/fp.model_animations",
                  "hud_interface": f"{folder}/hud.weapon_hud_interface"}
        projectile = f"{folder}/restored.projectile"
        self.tag(self.source, identity["model"], geometry="reviewed recovered original")
        self.tag(self.source, fields["first_person_model"], geometry="completed original FP")
        self.tag(self.source, fields["first_person_animations"], frames="completed original animation")
        self.tag(self.source, fields["hud_interface"], refs=[self.bitmap], width=4)
        self.tag(self.source, projectile, damage=777)
        self.tag(self.source, name, **identity, **fields,
                 refs=[identity["model"], *fields.values(), projectile], damage=777)
        self.tag(self.source, self.scenario, refs=[name, self.weapon], weapon_palette=[name],
                 weapons=[{"palette_index": 0, "position": [4, 5, 6], "respawn_seconds": 45}])
        return name, fields, projectile

    def reviewed_entry(self, name, outcome="original-completion", stock_weapon=None):
        names = {name, *FakeInvader().run("dependency", "-r", "-t", self.source, name).splitlines()}
        hashes = {tag: hashlib.sha256((self.source / tag).read_bytes()).hexdigest() for tag in sorted(names)}
        body = json.loads((self.source / name).read_text())
        return {"asset_id": "halo1-reviewed-original-fixture", "variant_id": "reviewed-source-v1",
                "weapon": name, "weapon_sha256": hashes[name],
                "identity": {key: body[key] for key in original.IDENTITY_FIELDS},
                "closure_sha256": hashes, "outcome": outcome,
                "ancestor": {"kind": "retail-xbox" if stock_weapon else "recovered-halo1",
                             "asset_id": "halo1-original-ancestor-fixture", "stock_weapon": stock_weapon},
                "evidence": [{"title": "Reviewed original Halo 1 recovery fixture",
                              "url": "https://www.halowaypoint.com/news/digsite-deliveries"}],
                "reason": "Reviewed recovered original asset with completed authored implementation"}

    def reviewed_catalog(self, *entries):
        from tools.map_pipeline.weapon_lineage import load_catalog
        path = self.base / "reviewed-lineage.json"
        path.write_text(json.dumps({"schema_version": 1, "id": "reviewed-fixture", "version": "1.0.0",
                                    "entries": list(entries)}))
        return load_catalog(path.resolve())

    def community_entry(self, name):
        entry = self.reviewed_entry(name, outcome="approved-community")
        entry.update(asset_id="ce-revolver-fixture", ancestor=None, evidence=[],
                     reason="Explicitly approved community revolver exception",
                     approval={"kind": "user-decision", "date": "2026-10-08",
                               "reference": "thread://01a116b1-1414-7ea2-ad25-7cdf34ebce54",
                               "statement": "Allow the reviewed CE Revolver as a community weapon exception."})
        return entry

    def assert_lineage_failure(self, catalog, token, weapon, **kwargs):
        before = {root: _tree(root) for root in (self.stock, self.source)}
        with self.assertRaises(ConversionError) as error:
            self.convert(lineage_catalog=catalog, lineage_source=self.source, **kwargs)
        self.assertEqual(error.exception.code, "needs_profile")
        details = json.dumps(error.exception.details, sort_keys=True)
        self.assertIn(weapon, details)
        self.assertIn(token, details)
        self.assertFalse((self.workspace / "canonical-weapons").exists())
        self.assertEqual({root: _tree(root) for root in before}, before)

    def test_reviewed_recovered_original_without_retail_donor_preserves_payload_and_native_prefix(self):
        name, fields, projectile = self.restored_weapon()
        prefix = self.native_registry([name])
        entry = self.reviewed_entry(name)
        catalog = self.reviewed_catalog(entry)
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=catalog, lineage_source=self.source)
        self.assertFalse((self.stock / name).exists())
        self.assertFalse((overlay / name).exists())
        self.assertEqual(json.loads((self.source / name).read_text())["damage"], 777)
        self.assertEqual(json.loads((self.source / projectile).read_text())["damage"], 777)
        registry = json.loads((overlay / original.GLOBALS).read_text())["weapon_list"]
        self.assertEqual(registry, prefix)
        self.assert_resident_roots(overlay, [name])
        self.assertEqual({root: _tree(root) for root in before}, before)
        self.assertNotIn(fields["hud_interface"], self.steps[-1]["native_hud_tags"])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        proof = record["reviewed_lineage_matches"][name]
        self.assertEqual(proof["asset_id"], entry["asset_id"])
        self.assertEqual(proof["original_source_closure_sha256"], entry["closure_sha256"])
        self.assertEqual(record["lineage_catalog"]["sha256"], catalog["sha256"])
        completion = record["authored_original_completions"][name]
        self.assertIsNone(completion["stock_weapon"])
        self.assertEqual(completion["classification"], "reviewed_recovered_halo1_weapon")
        self.assertIn(fields["hud_interface"], record["authored_completion_hud_tags"])

    def test_approved_community_weapon_retains_reviewed_assets_residency_and_approval(self):
        name, fields, projectile = self.restored_weapon("weapons/ce revolver/ce revolver.weapon")
        prefix = self.native_registry([name])
        entry = self.community_entry(name)
        catalog = self.reviewed_catalog(entry)
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=catalog, lineage_source=self.source)
        self.assertFalse((self.stock / name).exists())
        self.assertFalse((overlay / name).exists())
        self.assertFalse((overlay / self.scenario).exists())
        self.assertEqual(json.loads((self.source / name).read_text())["damage"], 777)
        self.assertEqual(json.loads((self.source / projectile).read_text())["damage"], 777)
        globals_output = json.loads((overlay / original.GLOBALS).read_text())
        self.assertEqual(globals_output["weapon_list"], prefix)
        self.assert_resident_roots(overlay, [name])
        self.assertEqual(len(prefix), 14)
        self.assertEqual(globals_output["authored_setting"], "keep")
        self.assertEqual(globals_output["nested"], {"difficulty": [1, 2, 3]})
        self.assertEqual({root: _tree(root) for root in before}, before)
        record = json.loads((overlay.parent / "conversion.json").read_text())
        proof = record["reviewed_lineage_matches"][name]
        self.assertEqual(proof["outcome"], "approved-community")
        self.assertEqual(proof["applied_outcome"], "approved-community")
        self.assertEqual(proof["approval"], entry["approval"])
        self.assertIsNone(proof["ancestor"])
        self.assertEqual(proof["original_source_closure_sha256"], entry["closure_sha256"])
        exception = record["authored_community_exceptions"][name]
        self.assertEqual(exception["classification"], "approved_community_weapon")
        self.assertEqual(exception["reviewed_lineage"]["approval"], entry["approval"])
        self.assertIsNone(exception["stock_weapon"])
        self.assertNotIn(name, record["authored_original_completions"])
        self.assertEqual(record["additional_community_registry"], [])
        self.assertEqual(record["resident_community_weapon_roots"], [name])
        self.assertNotIn(name, record["additional_original_registry"])
        self.assertEqual(self.steps[-1]["authored_community_exceptions"][name], exception)
        self.assertEqual(self.steps[-1]["additional_community_registry"], [])
        self.assertEqual(self.steps[-1]["resident_community_weapon_roots"], [name])
        self.assertNotIn(fields["hud_interface"], record["native_hud_tags"])
        self.assertIn(fields["hud_interface"], record["authored_completion_hud_tags"])
        actions = [action for action in self.repairs if action["tag"] == name
                   and action["kind"] == "approved_community_weapon"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["operation"], "retain_approved_community_weapon")
        self.assertEqual(actions[0]["reviewed_lineage"]["approval"], entry["approval"])
        self.assertFalse(actions[0]["canonical_og_payload"])

    def test_registry_only_approved_community_weapon_is_not_silently_dropped(self):
        name, _, _ = self.restored_weapon("weapons/ce revolver/ce revolver.weapon")
        prefix = self.native_registry([name])
        self.tag(self.source, self.scenario, refs=[self.weapon])
        before = _tree(self.source)
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(self.community_entry(name)),
                               lineage_source=self.source)
        self.assertEqual(json.loads((overlay / original.GLOBALS).read_text())["weapon_list"], prefix)
        self.assert_resident_roots(overlay, [name])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertIn(name, record["authored_community_exceptions"])
        self.assertIn(name, record["removed_registry_references"])
        self.assertIn(name, record["resident_community_weapon_roots"])
        self.assertEqual(_tree(self.source), before)

    def test_community_approval_cannot_approve_a_changed_projectile_overlay(self):
        name, _, projectile = self.restored_weapon("weapons/ce revolver/ce revolver.weapon")
        catalog = self.reviewed_catalog(self.community_entry(name))
        before = {root: _tree(root) for root in (self.stock, self.source)}
        changed = self.base / "changed-community-projectile-overlay"
        changed.mkdir()
        self.tag(changed, projectile, damage=888)
        changed_before = _tree(changed)
        with self.assertRaises(ConversionError) as error:
            original.canonical_weapon_overlay(FakeInvader(), self.stock, [changed, self.source, self.stock], set(),
                                              self.scenario, self.workspace, self.steps, self.repairs, self.protected,
                                              lineage_catalog=catalog, lineage_source=self.source)
        self.assertEqual(error.exception.code, "needs_profile")
        details = json.dumps(error.exception.details)
        self.assertIn("unreviewed_overlay", details)
        self.assertIn(name, details)
        self.assertIn(projectile, details)
        self.assertFalse((self.workspace / "canonical-weapons").exists())
        self.assertEqual(_tree(changed), changed_before)
        self.assertEqual({root: _tree(root) for root in before}, before)

    def test_excluded_reachable_battle_rifle_blocks_with_reviewed_decision(self):
        name, _, _ = self.restored_weapon("weapons/battle rifle/battle rifle.weapon")
        self.native_registry([name])
        entry = self.reviewed_entry(name, outcome="unsupported")
        entry.update(asset_id="excluded-battle-rifle-fixture", ancestor=None, evidence=[],
                     reason="Battle Rifle is explicitly excluded from this conversion policy.")
        self.assert_lineage_failure(self.reviewed_catalog(entry), "unsupported", name)

    def test_reviewed_original_npc_with_changed_model_type_label_keeps_completed_implementation(self):
        ancestor = "characters/sentinel/sentinel.weapon"
        self.tag(self.stock, ancestor, model=".model", weapon_type="undefined", label="ar", refs=[], damage=1)
        name, fields, _ = self.restored_weapon("weapons/sentinel beam/sentinel beam.weapon")
        prefix = self.native_registry([name])
        entry = self.reviewed_entry(name, stock_weapon=ancestor)
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(entry), lineage_source=self.source)
        self.assertFalse((overlay / name).exists())
        registry = json.loads((overlay / original.GLOBALS).read_text())["weapon_list"]
        self.assertEqual(registry, prefix)
        self.assert_resident_roots(overlay, [name])
        self.assertEqual({root: _tree(root) for root in before}, before)
        self.assertEqual(json.loads((self.source / name).read_text())["damage"], 777)
        self.assertNotIn(fields["hud_interface"], self.steps[-1]["native_hud_tags"])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        completion = record["authored_original_completions"][name]
        self.assertEqual(completion["reviewed_lineage"]["ancestor"]["stock_weapon"], ancestor)
        self.assertEqual(completion["original_source_closure_sha256"], entry["closure_sha256"])

    def test_reviewed_placed_original_completion_is_rooted_even_without_source_registry_entry(self):
        name, _, _ = self.restored_weapon()
        prefix = self.native_registry()
        self.assertNotIn(name, json.loads((self.source / original.GLOBALS).read_text())["weapon_list"])
        before = _tree(self.source)
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(self.reviewed_entry(name)), lineage_source=self.source)
        self.assertEqual(json.loads((overlay / original.GLOBALS).read_text())["weapon_list"], prefix)
        self.assert_resident_roots(overlay, [name])
        self.assertFalse((overlay / name).exists())
        self.assertEqual(_tree(self.source), before)

    def test_more_than_twenty_admitted_weapons_are_resident_with_exact_native_registry(self):
        names, entries = [], []
        for index in range(21):
            name, _, _ = self.restored_weapon(f"weapons/recovered_{index:02d}/recovered_{index:02d}.weapon")
            entry = self.reviewed_entry(name)
            entry.update(asset_id=f"halo1-recovered-fixture-{index:02d}", variant_id=f"reviewed-fixture-{index:02d}")
            names.append(name)
            entries.append(entry)
        prefix = self.native_registry(names)
        # Every added asset is rooted solely through the source registry. The
        # output must retain all of them without relying on map placements or
        # increasing Invader's actual twenty-entry Globals bound.
        self.tag(self.source, self.scenario, refs=[self.weapon], authored_geometry=True)
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(*entries), lineage_source=self.source)
        output_globals = json.loads((overlay / original.GLOBALS).read_text())
        self.assertEqual(len(prefix), 14)
        self.assertEqual(output_globals["weapon_list"], prefix)
        resident = self.assert_resident_roots(overlay, names)
        for entry in entries:
            self.assertTrue(set(entry["closure_sha256"]).issubset(resident), entry["weapon"])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertEqual(record["resident_weapon_roots"], names)
        self.assertEqual(record["resident_original_weapon_roots"], names)
        self.assertEqual(record["resident_community_weapon_roots"], [])
        self.assertEqual(record["additional_original_registry"], [])
        self.assertEqual(record["additional_community_registry"], [])
        self.assertEqual(set(record["authored_original_completions"]), set(names))
        residency = [action for action in self.repairs if action["kind"] == "admitted_weapon_residency"]
        self.assertEqual(len(residency), 1)
        self.assertEqual(residency[0]["weapon_references"], names)
        self.assertTrue(residency[0]["dependency_residency_verified"])
        self.assertEqual({root: _tree(root) for root in before}, before)

    def test_inherited_reviewed_resident_weapon_survives_native_shell_replacement(self):
        name, _, _ = self.restored_weapon()
        prefix = self.native_registry()
        self.tag(self.source, original.GLOBALS, weapon_list=prefix, authored_setting="keep")
        self.tag(self.source, self.scenario, refs=[self.weapon], authored_geometry=True)
        self.tag(self.source, self.resident_collection, tags=[name])
        soul = json.loads((self.source / self.soul).read_text())
        soul["tags"].append(self.resident_collection)
        self.tag(self.source, self.soul, **soul)
        entry = self.reviewed_entry(name)
        catalog = self.reviewed_catalog(entry)
        native = self.base / "native-shell"
        native.mkdir()
        self.tag(native, self.soul, tags=[self.bitmap], authored_layout="native-shell")
        before = {root: _tree(root) for root in (self.source, self.stock, native)}
        for replaced in (False, True):
            with self.subTest(native_shell_replaced_source_soul=replaced):
                roots = [native, self.source, self.stock] if replaced else [self.source, self.stock]
                workspace = self.workspace / ("replaced-soul" if replaced else "inherited-soul")
                workspace.mkdir()
                steps, repairs, protected = [], [], {}
                overlay = original.canonical_weapon_overlay(FakeInvader(), self.stock, roots, set(), self.scenario,
                                                            workspace, steps, repairs, protected,
                                                            lineage_catalog=catalog, lineage_source=self.source)
                self.assertEqual(json.loads((overlay / original.GLOBALS).read_text())["weapon_list"], prefix)
                self.assertFalse((overlay / name).exists())
                winning_soul = json.loads((roots[0] / self.soul).read_text())
                output_soul = json.loads((overlay / self.soul).read_text())
                expected_refs = winning_soul["tags"] + ([] if self.resident_collection in winning_soul["tags"]
                                                        else [self.resident_collection])
                self.assertEqual(output_soul["tags"], expected_refs)
                self.assertEqual(output_soul["tags"].count(self.resident_collection), 1)
                self.assertEqual(output_soul["authored_layout"], winning_soul["authored_layout"])
                self.assertEqual(json.loads((overlay / self.resident_collection).read_text())["tags"], [name])
                resident = set(FakeInvader().run("dependency", "-r", "-t", overlay,
                                                  *(arg for root in roots for arg in ("-t", root)), self.soul).splitlines())
                self.assertTrue(set(entry["closure_sha256"]).issubset(resident))
                record = json.loads((overlay.parent / "conversion.json").read_text())
                self.assertEqual(record["inherited_resident_weapons"], [name])
                self.assertEqual(steps[-1]["inherited_resident_weapons"], [name])
                self.assertEqual(record["resident_original_weapon_roots"], [name])
                self.assertEqual(record["reviewed_lineage_matches"][name]["original_source_closure_sha256"],
                                 entry["closure_sha256"])
                self.assertEqual({root: _tree(root) for root in before}, before)

    def test_reviewed_stock_gun_alias_uses_complete_original_assets(self):
        name, _, _ = self.restored_weapon("community/reviewed_sniper.weapon")
        entry = self.reviewed_entry(name, outcome="canonical-stock", stock_weapon=self.weapon)
        before = _tree(self.source)
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(entry), lineage_source=self.source)
        output = json.loads((overlay / name).read_text())
        self.assertEqual(output["damage"], 50)
        self.assertEqual(json.loads((overlay / output["refs"][2]).read_text())["damage"], 10)
        self.assertEqual(json.loads((overlay / output["refs"][3]).read_text())["audio"], "stock")
        self.assertTrue(output["model"].startswith(original.NAMESPACE + "/"))
        self.assertEqual(_tree(self.source), before)

    def test_lineage_weapon_digest_mismatch_blocks_before_output(self):
        name, _, _ = self.restored_weapon()
        catalog = self.reviewed_catalog(self.reviewed_entry(name))
        body = json.loads((self.source / name).read_text())
        body["damage"] = 888
        self.tag(self.source, name, **body)
        self.assert_lineage_failure(catalog, "changed_dependencies", name)

    def test_lineage_dependency_digest_mismatch_blocks_before_output(self):
        name, _, projectile = self.restored_weapon()
        catalog = self.reviewed_catalog(self.reviewed_entry(name))
        self.tag(self.source, projectile, damage=888)
        self.assert_lineage_failure(catalog, "changed_dependencies", name)

    def test_lineage_identity_mismatch_blocks_before_output(self):
        name, _, _ = self.restored_weapon()
        entry = self.reviewed_entry(name)
        entry["identity"]["label"] = "different-reviewed-identity"
        self.assert_lineage_failure(self.reviewed_catalog(entry), "identity_changes", name)

    def test_unverified_lineage_entry_does_not_approve_a_weapon(self):
        name, _, _ = self.restored_weapon()
        entry = self.reviewed_entry(name, outcome="unverified")
        entry["ancestor"], entry["evidence"] = None, []
        self.assert_lineage_failure(self.reviewed_catalog(entry), "unverified", name)

    def test_unsupported_lineage_entry_stays_blocked(self):
        name, _, _ = self.restored_weapon()
        entry = self.reviewed_entry(name, outcome="unsupported")
        self.assert_lineage_failure(self.reviewed_catalog(entry), "unsupported", name)

    def test_reviewed_completion_cannot_import_an_unreviewed_nested_weapon(self):
        name, _, _ = self.restored_weapon()
        body = json.loads((self.source / name).read_text())
        body["refs"].append(self.extra)
        self.tag(self.source, name, **body)
        entry = self.reviewed_entry(name)
        catalog = self.reviewed_catalog(entry)
        before = _tree(self.source)
        with self.assertRaises(ConversionError) as error:
            self.convert(lineage_catalog=catalog, lineage_source=self.source)
        self.assertEqual(error.exception.code, "needs_profile")
        self.assertIn(self.extra, json.dumps(error.exception.details))
        self.assertFalse((self.workspace / "canonical-weapons").exists())
        self.assertEqual(_tree(self.source), before)

    def test_reviewed_completion_cannot_repurpose_an_original_registry_path(self):
        ancestor = "characters/sentinel/sentinel.weapon"
        self.tag(self.stock, ancestor, model=".model", weapon_type="undefined", label="ar", refs=[], damage=1)
        name, _, _ = self.restored_weapon(self.weapon)
        entry = self.reviewed_entry(name, stock_weapon=ancestor)
        catalog = self.reviewed_catalog(entry)
        before = _tree(self.source)
        with self.assertRaises(ConversionError) as error:
            self.convert(lineage_catalog=catalog, lineage_source=self.source)
        self.assertEqual(error.exception.code, "needs_profile")
        self.assertIn("registry", str(error.exception))
        self.assertEqual(error.exception.details["weapon"], self.weapon)
        self.assertFalse((self.workspace / "canonical-weapons").exists())
        self.assertEqual(_tree(self.source), before)

    def test_lineage_matches_raw_source_across_legitimate_model_conversion_overlay(self):
        name, fields, _ = self.restored_weapon(model_class="gbxmodel")
        entry = self.reviewed_entry(name)
        catalog = self.reviewed_catalog(entry)
        before = {root: _tree(root) for root in (self.stock, self.source)}
        models = self.base / "model-overlay"
        # Match the backend's complete copied working tree, including assets
        # whose bytes survive trusted model conversion unchanged.
        shutil.copytree(self.source, models)
        body = json.loads((self.source / name).read_text())
        for field in ("model", "first_person_model"):
            old = body[field]
            new = old.removesuffix(".gbxmodel") + ".model"
            self.tag(models, new, geometry="converted source geometry")
            body[field] = new
            body["refs"] = [new if value == old else value for value in body["refs"]]
        self.tag(models, name, **body)
        converted_before = _tree(models)
        overlay = original.canonical_weapon_overlay(FakeInvader(), self.stock, [models, self.source, self.stock], set(),
                                                   self.scenario, self.workspace, self.steps, self.repairs, self.protected,
                                                   lineage_catalog=catalog, lineage_source=self.source,
                                                   lineage_derived=_tree(models))
        self.assertFalse((overlay / name).exists())
        self.assertEqual(_tree(models), converted_before)
        self.assertEqual({root: _tree(root) for root in before}, before)
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertEqual(record["reviewed_lineage_matches"][name]["original_source_closure_sha256"], entry["closure_sha256"])
        completion = record["authored_original_completions"][name]
        self.assertEqual(completion["authored_completed_fields"]["first_person_model"]["reference"], body["first_person_model"])
        self.assertNotIn(fields["hud_interface"], record["native_hud_tags"])

    def test_complete_original_gun_stays_canonical_with_a_reviewed_completion_entry(self):
        for root in (self.stock, self.source):
            body = json.loads((root / self.weapon).read_text())
            body.update(first_person_model=self.model, first_person_animations="weapons/sniper/fp.model_animations", hud_interface=self.hud)
            body["refs"].append(body["first_person_animations"])
            self.tag(root, self.weapon, **body)
            self.tag(root, body["first_person_animations"], frames="OG" if root == self.stock else "custom")
        entry = self.reviewed_entry(self.weapon, stock_weapon=self.weapon)
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(entry), lineage_source=self.source)
        output = json.loads((overlay / self.weapon).read_text())
        self.assertEqual(output["damage"], 50)
        self.assertEqual(json.loads((overlay / output["first_person_animations"]).read_text())["frames"], "OG")
        self.assertFalse(self.steps[-1]["authored_original_completions"])

    def test_source_receipt_cannot_approve_gameplay_changes_in_a_winning_overlay(self):
        name, _, _ = self.restored_weapon()
        catalog = self.reviewed_catalog(self.reviewed_entry(name))
        before = {root: _tree(root) for root in (self.stock, self.source)}
        changed = self.base / "changed-overlay"
        changed.mkdir()
        body = json.loads((self.source / name).read_text())
        body["damage"] = 888
        self.tag(changed, name, **body)
        changed_before = _tree(changed)
        with self.assertRaises(ConversionError) as error:
            original.canonical_weapon_overlay(FakeInvader(), self.stock, [changed, self.source, self.stock], set(),
                                              self.scenario, self.workspace, self.steps, self.repairs, self.protected,
                                              lineage_catalog=catalog, lineage_source=self.source)
        self.assertEqual(error.exception.code, "needs_profile")
        details = json.dumps(error.exception.details)
        self.assertIn("unreviewed_overlay", details)
        self.assertIn(name, details)
        self.assertFalse((self.workspace / "canonical-weapons").exists())
        self.assertEqual(_tree(changed), changed_before)
        self.assertEqual({root: _tree(root) for root in before}, before)

    def test_source_receipt_cannot_approve_a_changed_projectile_in_a_winning_overlay(self):
        name, _, projectile = self.restored_weapon()
        catalog = self.reviewed_catalog(self.reviewed_entry(name))
        before = {root: _tree(root) for root in (self.stock, self.source)}
        changed = self.base / "changed-projectile-overlay"
        changed.mkdir()
        self.tag(changed, projectile, damage=888)
        changed_before = _tree(changed)
        with self.assertRaises(ConversionError) as error:
            original.canonical_weapon_overlay(FakeInvader(), self.stock, [changed, self.source, self.stock], set(),
                                              self.scenario, self.workspace, self.steps, self.repairs, self.protected,
                                              lineage_catalog=catalog, lineage_source=self.source)
        self.assertEqual(error.exception.code, "needs_profile")
        details = json.dumps(error.exception.details)
        self.assertIn(name, details)
        self.assertIn(projectile, details)
        self.assertFalse((self.workspace / "canonical-weapons").exists())
        self.assertEqual(_tree(changed), changed_before)
        self.assertEqual({root: _tree(root) for root in before}, before)

    def registry_completion_with_nested_weapon(self, outcome):
        parent, _ = self.unfinished_weapon()
        nested, fields, _ = self.restored_weapon("weapons/nested/restored.weapon")
        body = json.loads((self.source / parent).read_text())
        body["refs"].append(nested)
        self.tag(self.source, parent, **body)
        # The parent is rooted only through Globals. Its nested gun has no
        # direct source registry or scenario reference of its own.
        self.tag(self.source, self.scenario, refs=[self.weapon])
        ancestor = parent if outcome == "canonical-stock" else None
        entry = self.reviewed_entry(nested, outcome=outcome, stock_weapon=ancestor)
        return parent, nested, fields, entry

    def test_nested_reviewed_canonical_stock_outcome_replaces_an_unfinished_ancestor(self):
        parent, nested, _, entry = self.registry_completion_with_nested_weapon("canonical-stock")
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(entry), lineage_source=self.source)
        stock_damage = json.loads((self.stock / parent).read_text())["damage"]
        self.assertEqual(json.loads((overlay / nested).read_text())["damage"], stock_damage)
        self.assertEqual(json.loads((self.source / nested).read_text())["damage"], 777)
        self.assertEqual({root: _tree(root) for root in before}, before)
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertEqual(record["source_weapon_aliases"][nested], parent)
        self.assertEqual(record["reviewed_lineage_matches"][nested]["outcome"], "canonical-stock")
        self.assertNotIn(nested, record["authored_original_completions"])

    def test_nested_reviewed_recovered_completion_is_recorded_and_resident(self):
        _, nested, fields, entry = self.registry_completion_with_nested_weapon("original-completion")
        prefix = json.loads((self.stock / original.GLOBALS).read_text())["weapon_list"]
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(entry), lineage_source=self.source)
        self.assertFalse((overlay / nested).exists())
        self.assertEqual(json.loads((overlay / original.GLOBALS).read_text())["weapon_list"], prefix)
        self.assert_resident_roots(overlay, [nested])
        self.assertEqual({root: _tree(root) for root in before}, before)
        record = json.loads((overlay.parent / "conversion.json").read_text())
        completion = record["authored_original_completions"][nested]
        self.assertEqual(completion["reviewed_lineage"]["outcome"], "original-completion")
        self.assertIsNone(completion["stock_weapon"])
        self.assertNotIn(fields["hud_interface"], record["native_hud_tags"])

    def complete_gun_with_contradictory_catalog(self, ancestor=None, outcome="original-completion"):
        for root in (self.stock, self.source):
            body = json.loads((root / self.weapon).read_text())
            body.update(first_person_model=self.model, first_person_animations="weapons/sniper/fp.model_animations", hud_interface=self.hud)
            body["refs"].append(body["first_person_animations"])
            self.tag(root, self.weapon, **body)
            self.tag(root, body["first_person_animations"], frames="OG" if root == self.stock else "custom")
        name = "community/known_complete_sniper.weapon"
        self.tag(self.source, name, **json.loads((self.source / self.weapon).read_text()))
        self.tag(self.source, self.scenario, refs=[name])
        if ancestor:
            self.tag(self.stock, ancestor, model="weapons/prototype/world.model", weapon_type="undefined", label="prototype", refs=[], damage=1)
        entry = self.community_entry(name) if outcome == "approved-community" else self.reviewed_entry(name, stock_weapon=ancestor)
        before = {root: _tree(root) for root in (self.stock, self.source)}
        overlay = self.convert(lineage_catalog=self.reviewed_catalog(entry), lineage_source=self.source)
        output = json.loads((overlay / name).read_text())
        self.assertEqual(output["damage"], 50)
        self.assertEqual(json.loads((overlay / output["first_person_animations"]).read_text())["frames"], "OG")
        self.assertEqual({root: _tree(root) for root in before}, before)
        record = json.loads((overlay.parent / "conversion.json").read_text())
        proof = record["reviewed_lineage_matches"][name]
        self.assertEqual(proof["outcome"], outcome)
        self.assertEqual(proof["applied_outcome"], "canonical-stock")
        self.assertEqual(proof["canonical_stock_preference"], self.weapon)
        self.assertNotIn(name, record["authored_original_completions"])
        self.assertNotIn(name, record["authored_community_exceptions"])

    def test_community_approval_cannot_override_complete_original_gun_assets(self):
        self.complete_gun_with_contradictory_catalog(outcome="approved-community")

    def test_catalog_cannot_disguise_a_known_complete_stock_gun_as_a_recovered_completion(self):
        self.complete_gun_with_contradictory_catalog()

    def test_catalog_cannot_map_a_known_complete_stock_gun_to_an_unfinished_ancestor(self):
        self.complete_gun_with_contradictory_catalog("weapons/prototype/prototype.weapon")


if __name__ == "__main__":
    unittest.main()
