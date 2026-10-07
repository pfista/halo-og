"""HUD conversion safety and source-version policy checks; no game execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.map_pipeline import hud, profiles
from tools.map_pipeline.backend import ConversionError


TAG = "ui/custom.weapon_hud_interface"


def plan():
    return {"tag": TAG, "status": "requires_conversion", "source_formats": ["mcc_hud_density"],
            "target_format": "native_xbox_hud", "field_rules": [
                {"field": "crosshairs[0].overlays[0].width_scale", "before": [1.2], "after": [0.3],
                 "reason": "MCC canvas and bitmap half-scale preserve authored relative size"}],
            "evidence": {"density_proofs": [], "visual_validation": "pending"}, "warnings": []}


class HudTests(unittest.TestCase):
    def test_generic_policy_explicit_and_legacy_preserves(self):
        original = json.loads((profiles.PROFILE_ROOT / "og-multiplayer-v5.json").read_text())
        self.assertEqual(profiles.validate_profile(original)["presentation_policy"], "native-xbox")
        self.assertEqual(profiles.validate_profile(original)["weapon_policy"], "bungie-originals")
        original.pop("presentation_policy")
        original.pop("stock_weapon_hud_policy", None)
        original.pop("weapon_policy")
        original.pop("weapon_placement_policy")
        self.assertEqual(profiles.validate_profile(original)["presentation_policy"], "preserve")
        for invalid in ("quarter-all", True, {}, None):
            original["presentation_policy"] = invalid
            with self.assertRaises((ValueError, TypeError)):
                profiles.validate_profile(original)

    def test_reject_gameplay_edits_and_invalid_numeric_plans(self):
        entry = plan()
        hud.validate_plan(entry, {TAG})
        for field in ("damage", "zoom_levels", "crosshairs[0].map_type", "../width_scale"):
            changed = copy.deepcopy(entry)
            changed["field_rules"][0]["field"] = field
            with self.subTest(field=field), self.assertRaises(ValueError):
                hud.validate_plan(changed, {TAG})
        for value in (float("nan"), float("inf"), True, "0.25"):
            changed = copy.deepcopy(entry)
            changed["field_rules"][0]["after"] = [value]
            with self.subTest(value=value), self.assertRaises(ValueError):
                hud.validate_plan(changed, {TAG})
        with self.assertRaises(ValueError):
            hud.validate_plan(entry, {"unrelated.weapon_hud_interface"})

    def test_checked_overlay_and_immutable_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tags, stock = root / "tags", root / "stock"
            stock.mkdir()
            (tags / TAG).parent.mkdir(parents=True)
            (tags / TAG).write_bytes(b"original")
            class Assets:
                def run(self, kind, mode, folder):
                    if mode == "--audit":
                        return [plan()]
                    (folder / "tags" / TAG).write_bytes(b"converted")
                    (folder / "conversion.completed").write_text("verified\n")
                    return [{"tag": TAG, "status": "converted", "source_formats": ["mcc_hud_density"],
                             "target_format": "native_xbox_hud", "authored_metadata_preserved": True,
                             "source_snapshots_preserved": True, "visual_validation": "pending",
                             "input_bytes": 8, "output_bytes": 9}]
                def provenance(self):
                    return {"test": True}
            class Editor:
                def get(self, at, name, field):
                    return "0.3" if (at / name).read_bytes() == b"converted" else "1.2"
            steps, repairs, protected = [], [], {}
            overlay = hud.normalize_mcc_hud(Assets(), Editor(), [tags, stock], stock, {TAG},
                                             root, steps, repairs, protected)
            self.assertEqual((tags / TAG).read_bytes(), b"original")
            self.assertEqual((overlay / TAG).read_bytes(), b"converted")
            self.assertEqual(steps[0]["status"], "converted")
            self.assertEqual(repairs[0]["kind"], "native_presentation")
            self.assertTrue(json.loads((overlay.parent / "conversion.json").read_text())["source_unchanged"])

    def test_unknown_layout_is_actionable_and_does_not_convert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tags = root / "tags"
            (tags / TAG).parent.mkdir(parents=True)
            (tags / TAG).write_bytes(b"original")
            class Assets:
                def run(self, kind, mode, folder):
                    if mode != "--audit":
                        raise AssertionError("Ambiguous HUD must not be converted")
                    result = plan()
                    result.update(status="needs_profile", reason="Unsupported MCC child anchor 8", blockers=["anchor 8"])
                    return [result]
            with self.assertRaises(ConversionError) as caught:
                hud.normalize_mcc_hud(Assets(), None, [tags], tags, {TAG}, root, [], [], {})
            self.assertEqual(caught.exception.code, "needs_profile")
            self.assertEqual(caught.exception.details["tag"], TAG)
            self.assertIn("anchor 8", caught.exception.message)
            self.assertFalse((root / "native-hud").exists())

    def test_fixed_atlas_shared_with_unhandled_hud_field_blocks_resize(self):
        bitmap = "ui/shared.bitmap"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tags = root / "tags"
            for name in (TAG, bitmap):
                (tags / name).parent.mkdir(parents=True, exist_ok=True)
                (tags / name).write_bytes(b"original")
            class Assets:
                def run(self, kind, mode, folder):
                    if kind == "hud":
                        result = plan()
                        result.update(tag=bitmap, field_rules=[], bitmap_divisor=4)
                        return [result]
                    return [{"tag": bitmap, "status": "classified", "consumers": [
                        {"tag": TAG, "class": "weapon_hud_interface", "field": "screen_effects[0].mask_fullscreen"}]}]
            with self.assertRaises(ConversionError) as caught:
                hud.normalize_mcc_hud(Assets(), None, [tags], tags, {TAG, bitmap}, root, [], [], {})
            self.assertEqual(caught.exception.details["tag"], bitmap)
            self.assertIn("screen_effects", caught.exception.details["consumers"][0]["field"])
            self.assertFalse((root / "native-hud").exists())


if __name__ == "__main__":
    unittest.main()
