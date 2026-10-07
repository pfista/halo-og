"""Stock weapon identity, display closure isolation and input preservation."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.map_pipeline import stock_hud
from tools.map_pipeline.backend import ConversionError, _tree


class FakeInvader:
    def __init__(self, mutation=None):
        self.calls, self.mutation = [], mutation

    def get(self, root, name, field):
        self.calls.append(("get", name, field))
        if self.mutation:
            mutation, self.mutation = self.mutation, None
            mutation()
        return json.loads((Path(root) / name).read_text())[field]

    def run(self, tool, *args):
        self.calls.append((tool, args))
        root = Path(args[args.index("-t") + 1])
        if tool == "dependency":
            found, pending = set(), list(json.loads((root / args[-1]).read_text()).get("refs", []))
            while pending:
                name = pending.pop()
                if name in found:
                    continue
                found.add(name)
                path = root / name
                if path.is_file():
                    pending += json.loads(path.read_text()).get("refs", [])
            return "\n".join(sorted(name if (root / name).is_file() else name + " [BROKEN]" for name in found))
        if tool != "refactor":
            raise AssertionError(tool)
        pairs = {args[index + 1]: args[index + 2] for index, value in enumerate(args) if value == "-T"}
        self.assert_isolated = True
        for path in list(root.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(root).as_posix()
            body = json.loads(path.read_text())
            body["refs"] = [pairs.get(ref, ref) for ref in body.get("refs", [])]
            target = root / pairs.get(name, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(body))
            if target != path:
                path.unlink()
        return ""


class StockHUDTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.stock, self.authored, self.workspace = [self.base / value for value in ("stock", "authored", "workspace")]
        for root in (self.stock, self.authored, self.workspace):
            root.mkdir()
        self.weapon = "weapons/sniper rifle/sniper rifle.weapon"
        self.hud = "weapons/sniper rifle/sniper rifle.weapon_hud_interface"
        self.master = "ui/hud/master.weapon_hud_interface"
        self.bitmap = "ui/hud/bitmaps/combined/weapon.bitmap"
        self.identity = {"model": "weapons/sniper rifle/sniper rifle.model", "weapon_type": "undefined", "label": "sr"}
        self.tag(self.stock, self.weapon, **self.identity, hud_interface=self.hud)
        self.tag(self.authored, self.weapon, **self.identity, hud_interface=self.hud, damage=100)
        self.tag(self.stock, self.hud, refs=[self.master], density=1)
        self.tag(self.stock, self.master, refs=[self.bitmap], density=1)
        self.tag(self.stock, self.bitmap, pixels="native pixels")
        self.tag(self.authored, self.hud, refs=[self.master], density=4)
        self.tag(self.authored, self.master, refs=[self.bitmap], density=4)
        self.tag(self.authored, self.bitmap, pixels="MCC shared pixels")
        self.required = {self.weapon, self.hud, self.master, self.bitmap}
        self.steps, self.repairs, self.protected = [], [], {}

    def tag(self, root, name, **body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
        return path

    def run_overlay(self, tool=None, roots=None):
        return stock_hud.stock_weapon_hud_overlay(tool or FakeInvader(), self.stock, roots or [self.authored, self.stock],
                                                   self.required, self.workspace, self.steps, self.repairs, self.protected)

    def test_matching_weapon_uses_stock_hud_with_private_dependencies_only(self):
        before = {root: _tree(root) for root in (self.stock, self.authored)}
        overlay = self.run_overlay()
        self.assertEqual({root: _tree(root) for root in before}, before)
        self.assertFalse((overlay / self.weapon).exists())
        self.assertFalse((overlay / self.bitmap).exists())
        self.assertFalse((overlay / self.master).exists())
        reused = json.loads((overlay / self.hud).read_text())
        self.assertEqual(reused["density"], 1)
        private_master = reused["refs"][0]
        self.assertTrue(private_master.startswith(stock_hud.NAMESPACE + "/"))
        master = json.loads((overlay / private_master).read_text())
        private_bitmap = master["refs"][0]
        self.assertTrue(private_bitmap.startswith(stock_hud.NAMESPACE + "/"))
        self.assertEqual(json.loads((overlay / private_bitmap).read_text())["pixels"], "native pixels")
        self.assertEqual(json.loads((self.authored / self.weapon).read_text())["damage"], 100)
        self.assertEqual(json.loads((self.authored / self.bitmap).read_text())["pixels"], "MCC shared pixels")
        self.assertEqual(self.steps[-1]["weapons_reused"], 1)
        self.assertEqual(self.steps[-1]["gameplay_tags_replaced"], 0)
        self.assertIn(self.hud, self.steps[-1]["native_hud_tags"])
        manifest = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertTrue(manifest["source_unchanged"])
        action = next(action for action in manifest["actions"] if action["kind"] == "canonical_weapon_hud")
        self.assertEqual(action["identity"][self.weapon]["label"], {"source": "sr", "stock": "sr"})
        self.assertEqual(set(manifest["output_sha256"]), set(_tree(overlay)))

    def test_relocated_authored_hud_reference_remains_unchanged(self):
        source_hud = "community/weapon/sniper_hud.weapon_hud_interface"
        body = json.loads((self.authored / self.weapon).read_text())
        body["hud_interface"] = source_hud
        self.tag(self.authored, self.weapon, **body)
        self.tag(self.authored, source_hud, refs=[self.bitmap])
        self.required.add(source_hud)
        overlay = self.run_overlay()
        self.assertTrue((overlay / source_hud).is_file())
        self.assertEqual(json.loads((self.authored / self.weapon).read_text())["hud_interface"], source_hud)
        self.assertFalse((overlay / self.weapon).exists())

    def test_identity_mismatch_or_empty_evidence_preserves_authored(self):
        for field, value in (("model", "weapons/custom.model"), ("weapon_type", "plasma_pistol"), ("label", "custom"), ("label", "")):
            with self.subTest(field=field, value=value):
                self.protected.clear()
                body = dict(self.identity, hud_interface=self.hud)
                body[field] = value
                self.tag(self.authored, self.weapon, **body)
                overlay = self.run_overlay()
                self.assertIsNone(overlay)
                self.assertFalse((self.workspace / "stock-weapon-hud").exists())
                self.assertTrue(self.steps[-1]["authored_preserved"][0]["authored_hud_preserved"])

    def test_null_invader_dependency_is_preserved(self):
        self.tag(self.authored, self.weapon, **self.identity, hud_interface=".weapon_hud_interface")
        self.assertIsNone(self.run_overlay())
        self.assertEqual(self.steps[-1]["weapons_reused"], 0)

    def test_same_basename_does_not_establish_weapon_identity(self):
        custom = "custom/sniper rifle.weapon"
        self.tag(self.authored, custom, **self.identity, hud_interface=self.hud)
        self.required = {custom, self.hud, self.bitmap, self.master}
        self.assertIsNone(self.run_overlay())
        self.assertEqual(self.steps[-1]["weapons_reused"], 0)

    def test_custom_weapon_sharing_hud_is_preserved(self):
        custom = "custom/weapon.weapon"
        self.tag(self.authored, custom, **self.identity, hud_interface=self.hud)
        self.required.add(custom)
        self.assertIsNone(self.run_overlay())
        self.assertIn("Shared HUD", self.steps[-1]["authored_preserved"][-1]["reason"])

    def test_conflicting_canonical_huds_fail_before_output(self):
        second = "weapons/second.weapon"
        second_hud = "weapons/second.weapon_hud_interface"
        self.tag(self.authored, second, **self.identity, hud_interface=self.hud)
        self.tag(self.stock, second, **self.identity, hud_interface=second_hud)
        self.tag(self.stock, second_hud, refs=[self.bitmap])
        self.required.add(second)
        with self.assertRaisesRegex(ConversionError, "different canonical"):
            self.run_overlay()
        self.assertFalse((self.workspace / "stock-weapon-hud").exists())

    def test_non_display_and_missing_stock_dependencies_fail_before_output(self):
        for dependency in ("weapons/gameplay.weapon", "ui/missing.bitmap"):
            with self.subTest(dependency=dependency):
                self.protected.clear()
                self.tag(self.stock, self.hud, refs=[dependency])
                if dependency.endswith(".weapon"):
                    self.tag(self.stock, dependency)
                with self.assertRaises(ConversionError) as error:
                    self.run_overlay()
                self.assertEqual(error.exception.stage, "presentation_stock_hud")
                self.assertFalse((self.workspace / "stock-weapon-hud").exists())

    def test_source_mutation_is_detected(self):
        with self.assertRaisesRegex(ConversionError, "changed an input"):
            self.run_overlay(FakeInvader(lambda: self.tag(self.authored, self.bitmap, pixels="mutated")))
        self.assertFalse((self.workspace / "stock-weapon-hud").exists())

    def test_effective_root_order_controls_identity(self):
        override = self.base / "override"
        override.mkdir()
        self.tag(override, self.weapon, **dict(self.identity, label="custom"), hud_interface=self.hud)
        self.assertIsNone(self.run_overlay(roots=[override, self.authored, self.stock]))

    def test_unsafe_paths_rejected_and_linked_inputs_not_followed(self):
        for name in ("../ui/x.bitmap", "/ui/x.bitmap", "ui//x.bitmap", "ui/x.weapon", "ui/x.bitmap\n"):
            with self.subTest(name=name):
                with self.assertRaises(ConversionError):
                    stock_hud._name(name)
        linked = self.authored / "linked.bitmap"
        linked.symlink_to(self.stock / self.bitmap)
        with self.assertRaises(ValueError):
            self.run_overlay()


if __name__ == "__main__":
    unittest.main()
