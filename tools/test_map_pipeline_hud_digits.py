"""Offline donor selection, private atlas isolation and Globals preservation."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.map_pipeline import hud_digits
from tools.map_pipeline.backend import ConversionError, _tree


class FakeInvader:
    def __init__(self, mutation=None, corrupt=None):
        self.calls, self.mutation, self.corrupt = [], mutation, corrupt

    def read(self, root, name):
        return json.loads((Path(root) / name).read_text())

    def locate(self, body, field):
        parts = field.split(".")
        for part in parts[:-1]:
            name, index = part[:-1].split("[")
            body = body[name][int(index)]
        return body, parts[-1]

    def get(self, root, name, field):
        self.calls.append(("get", str(root), name, field))
        if self.mutation:
            mutation, self.mutation = self.mutation, None
            mutation()
        body, key = self.locate(self.read(root, name), field)
        return body[key]

    def count(self, root, name, field):
        self.calls.append(("count", str(root), name, field))
        return len(self.read(root, name)[field])

    def dump(self, body):
        lines = []

        def visit(name, value, depth):
            prefix = "    " * (depth - 1) + " ├──" if depth else ""
            if isinstance(value, list):
                lines.append(f"{prefix}{name}[{len(value)}] array")
                for index, item in enumerate(value):
                    child_prefix = "    " * depth + " ├──"
                    if isinstance(item, dict):
                        lines.append(f"{child_prefix}{name}[{index}] struct")
                        for field, child in sorted(item.items()):
                            visit(field, child, depth + 2)
                    else:
                        lines.append(f"{child_prefix}{name}[{index}] ({item}) value")
            else:
                lines.append(f"{prefix}{name} ({value}) value")

        for field, value in sorted(body.items()):
            visit(field, value, 0)
        return "\n".join(lines)

    def run(self, tool, *args):
        self.calls.append((tool, tuple(map(str, args))))
        root = Path(args[args.index("-t") + 1])
        name = args[-1]
        if tool == "dependency":
            found, pending = set(), [name]
            while pending:
                current = pending.pop()
                if current in found:
                    continue
                if not (root / current).is_file():
                    found.add(current + " [BROKEN]")
                    continue
                found.add(current)
                body = self.read(root, current)
                pending.extend(body.get("refs", []))
                if body.get("digits_bitmap") not in {None, "", ".bitmap"}:
                    pending.append(body["digits_bitmap"].replace("\\", "/"))
            return "\n".join(sorted(found - {name}))
        if tool != "edit":
            raise AssertionError(tool)
        body = self.read(root, name)
        if "-L" in args:
            return self.dump(body)
        if "-S" in args:
            index = args.index("-S")
            field, value = args[index + 1:index + 3]
            selected, key = self.locate(body, field)
            selected[key] = value
            if self.corrupt:
                self.corrupt(body, field, root, name)
            (root / name).write_text(json.dumps(body, sort_keys=True))
            return ""
        raise AssertionError(args)


class HUDDigitsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.stock, self.authored, self.workspace = [self.base / name for name in ("stock", "authored", "workspace")]
        for root in (self.stock, self.authored, self.workspace):
            root.mkdir()
        self.hud = "ui/hud/counter.hud_number"
        self.bitmap = "ui/hud/bitmaps/combined/hud_counter_numbers.bitmap"
        self.globals = {"interface_bitmaps": [{"hud_digits_definition": self.hud, "hud_globals": "ui/authored.hud_globals"}],
                        "weapon_list": [{"weapon": "weapons/original.weapon"}, {"weapon": "weapons/npc_completed.weapon"}],
                        "grenades": [{"maximum_count": 8}], "difficulty": [1, 2, 3]}
        self.metrics = {"digits_bitmap": self.bitmap, "bitmap_digit_width": 12, "screen_digit_width": 9,
                        "x_offset": 1, "y_offset": 0, "decimal_point_width": 6, "colon_width": 6}
        self.tag(self.stock, hud_digits.GLOBALS, **self.globals)
        self.tag(self.authored, hud_digits.GLOBALS, **self.globals)
        self.tag(self.stock, self.hud, **self.metrics)
        self.tag(self.stock, self.bitmap, width=128, height=128, format="a8y8", pixels="OG verified atlas", sequence_bounds=[0, 1])
        self.tag(self.authored, self.hud, **dict(self.metrics, bitmap_digit_width=48))
        self.tag(self.authored, self.bitmap, width=128, height=64, format="argb32", pixels="authored shared pixels", sequence_bounds=[0, 0.5])
        self.tag(self.authored, "ui/custom.weapon_hud_interface", shared_bitmap=self.bitmap)
        self.steps, self.repairs, self.protected = [], [], {}

    def tag(self, root, name, **body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, sort_keys=True))
        return path

    def run_overlay(self, tool=None, roots=None, workspace=None):
        return hud_digits.canonical_hud_digits_overlay(tool or FakeInvader(), self.stock, roots or [self.authored, self.stock],
                                                      workspace or self.workspace, self.steps, self.repairs, self.protected)

    def test_exact_donor_pair_and_native_metrics_with_only_active_globals_ref_changed(self):
        before = {root: _tree(root) for root in (self.stock, self.authored)}
        overlay = self.run_overlay()
        self.assertEqual({root: _tree(root) for root in before}, before)
        actual = json.loads((overlay / hud_digits.GLOBALS).read_text())
        alias = actual["interface_bitmaps"][0]["hud_digits_definition"]
        self.assertRegex(alias, r"^__native_hud/stock/[0-9a-f]{16}/ui/hud/counter\.hud_number$")
        actual["interface_bitmaps"][0]["hud_digits_definition"] = self.hud
        self.assertEqual(actual, self.globals)
        counter = json.loads((overlay / alias).read_text())
        private_bitmap = counter["digits_bitmap"]
        counter["digits_bitmap"] = self.bitmap
        self.assertEqual(counter, self.metrics)
        self.assertEqual((overlay / private_bitmap).read_bytes(), (self.stock / self.bitmap).read_bytes())
        self.assertFalse((overlay / self.bitmap).exists())
        self.assertFalse((overlay / self.hud).exists())
        self.assertEqual(set(_tree(overlay)), {hud_digits.GLOBALS, alias, private_bitmap})
        self.assertEqual(self.steps[-1]["native_hud_tags"], [alias])
        record = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertTrue(record["source_unchanged"])
        self.assertEqual(record["output_sha256"], _tree(overlay))
        self.assertTrue(record["actions"][-1]["weapon_registry_preserved"])
        self.assertEqual(record["presentation_validation"], "pending")

    def test_inactive_interface_records_preserved_even_if_provider_is_invalid(self):
        second = {"hud_digits_definition": "missing/inactive.hud_number", "hud_globals": "custom/inactive.hud_globals"}
        self.globals["interface_bitmaps"].append(second)
        self.tag(self.authored, hud_digits.GLOBALS, **self.globals)
        overlay = self.run_overlay()
        actual = json.loads((overlay / hud_digits.GLOBALS).read_text())
        self.assertEqual(actual["interface_bitmaps"][1], second)
        self.assertEqual(self.steps[-1]["authored_interface_count"], 2)

    def test_null_authored_active_provider_is_repaired_explicitly(self):
        self.globals["interface_bitmaps"][0]["hud_digits_definition"] = ".hud_number"
        self.tag(self.authored, hud_digits.GLOBALS, **self.globals)
        self.run_overlay()
        self.assertIsNone(self.repairs[-1]["reference_before"])

    def test_donor_globals_reference_is_followed_without_hardcoded_provider_selection(self):
        alternate = "ui/native/counter.hud_number"
        self.tag(self.stock, alternate, **self.metrics)
        donor = dict(self.globals, interface_bitmaps=[dict(self.globals["interface_bitmaps"][0], hud_digits_definition=alternate)])
        self.tag(self.stock, hud_digits.GLOBALS, **donor)
        overlay = self.run_overlay()
        alias = json.loads((overlay / hud_digits.GLOBALS).read_text())["interface_bitmaps"][0]["hud_digits_definition"]
        self.assertTrue(alias.endswith("/" + alternate))

    def test_winning_globals_registry_and_custom_shared_atlas_remain_authored(self):
        override = self.base / "override"
        override.mkdir()
        selected = dict(self.globals, weapon_list=[{"weapon": "custom/retained.weapon"}])
        self.tag(override, hud_digits.GLOBALS, **selected)
        before = (self.authored / self.bitmap).read_bytes()
        overlay = self.run_overlay(roots=[override, self.authored, self.stock])
        self.assertEqual(json.loads((overlay / hud_digits.GLOBALS).read_text())["weapon_list"], selected["weapon_list"])
        self.assertEqual((self.authored / self.bitmap).read_bytes(), before)
        self.assertFalse((overlay / "ui/custom.weapon_hud_interface").exists())

    def test_missing_or_empty_interface_records_fail_before_output(self):
        for root in (self.stock, self.authored):
            with self.subTest(root=root.name):
                self.tag(root, hud_digits.GLOBALS, **dict(self.globals, interface_bitmaps=[]))
                with self.assertRaisesRegex(ConversionError, "active interface record 0"):
                    self.run_overlay()
                self.assertFalse((self.workspace / "native-hud-digits").exists())
                self.tag(root, hud_digits.GLOBALS, **self.globals)
                self.protected.clear()

    def test_null_missing_or_wrong_class_donor_provider_fails_before_output(self):
        for ref in (".hud_number", "ui/missing.hud_number", "weapons/gameplay.weapon", "../escape.hud_number"):
            with self.subTest(ref=ref):
                self.tag(self.stock, hud_digits.GLOBALS, **dict(self.globals, interface_bitmaps=[{"hud_digits_definition": ref}]))
                self.protected.clear()
                with self.assertRaises(ConversionError):
                    self.run_overlay()
                self.assertFalse((self.workspace / "native-hud-digits").exists())

    def test_invalid_or_extra_donor_dependencies_rejected(self):
        for ref in (".bitmap", "ui/missing.bitmap", "weapons/gameplay.weapon"):
            with self.subTest(ref=ref):
                self.tag(self.stock, self.hud, **dict(self.metrics, digits_bitmap=ref))
                self.protected.clear()
                with self.assertRaises(ConversionError):
                    self.run_overlay()
        self.tag(self.stock, self.hud, **dict(self.metrics, refs=["ui/extra.bitmap"]))
        self.tag(self.stock, "ui/extra.bitmap", pixels="extra")
        self.protected.clear()
        with self.assertRaisesRegex(ConversionError, "pair only"):
            self.run_overlay()

    def test_input_mutation_rejected_before_overlay_publication(self):
        with self.assertRaisesRegex(ConversionError, "changed an input tree"):
            self.run_overlay(FakeInvader(mutation=lambda: self.tag(self.authored, self.bitmap, pixels="mutated")))
        self.assertFalse((self.workspace / "native-hud-digits").exists())

    def test_unrelated_globals_edit_and_native_metric_edit_fail_verification(self):
        for target in ("globals", "hud"):
            with self.subTest(target=target):
                workspace = self.base / target
                workspace.mkdir()

                def corrupt(body, field, root, name):
                    if target == "globals" and name == hud_digits.GLOBALS:
                        body["weapon_list"] = []
                    if target == "hud" and name.endswith(".hud_number"):
                        body["screen_digit_width"] = 18

                with self.assertRaisesRegex(ConversionError, "changed another Globals|changed a native metric"):
                    self.run_overlay(FakeInvader(corrupt=corrupt), workspace=workspace)

    def test_bitmap_payload_mutation_rejected(self):
        def corrupt(body, field, root, name):
            if name.endswith(".hud_number"):
                (root / body["digits_bitmap"]).write_text("modified atlas")

        with self.assertRaisesRegex(ConversionError, "bitmap was modified"):
            self.run_overlay(FakeInvader(corrupt=corrupt))

    def test_repeat_selection_is_idempotent_for_exact_prior_private_pair(self):
        first = self.run_overlay()
        second_workspace = self.base / "repeat"
        second_workspace.mkdir()
        second = self.run_overlay(roots=[first, self.authored, self.stock], workspace=second_workspace)
        self.assertEqual(_tree(second), _tree(first))

    def test_modified_private_namespace_is_not_accepted_as_prior_native_pair(self):
        first = self.run_overlay()
        alias = self.steps[-1]["native_hud_tags"][0]
        bitmap = json.loads((first / alias).read_text())["digits_bitmap"]
        attacker = self.base / "attacker"
        shutil.copytree(first, attacker)
        self.tag(attacker, bitmap, pixels="authored collision")
        second_workspace = self.base / "collision"
        second_workspace.mkdir()
        with self.assertRaisesRegex(ConversionError, "namespace collides"):
            self.run_overlay(roots=[attacker, self.authored, self.stock], workspace=second_workspace)

    def test_source_links_and_unsafe_display_paths_rejected(self):
        for name in ("/ui/x.bitmap", "ui//x.bitmap", "../x.bitmap", "ui/x.weapon", "ui/x.bitmap\n"):
            with self.subTest(name=name):
                with self.assertRaises(ConversionError):
                    hud_digits._name(name)
        linked = self.stock / "linked.bitmap"
        linked.symlink_to(self.stock / self.bitmap)
        with self.assertRaises(ConversionError) as caught:
            self.run_overlay()
        self.assertEqual(caught.exception.code, "invalid_input")

    def test_protected_input_change_and_nonfresh_output_rejected(self):
        self.protected[self.stock / self.bitmap] = "0" * 64
        with self.assertRaisesRegex(ConversionError, "protected HUD digits input changed"):
            self.run_overlay()
        self.protected.clear()
        self.run_overlay()
        with self.assertRaisesRegex(ConversionError, "output must be fresh"):
            self.run_overlay()

    def test_parser_proof_rejects_ambiguous_or_malformed_active_field(self):
        for dump in ("not a dependency", "hud_digits_definition (.hud_number) value",
                     "interface_bitmaps[1] array\n ├──interface_bitmaps[0] struct\n      ├──hud_digits_definition (.hud_number) value"):
            with self.subTest(dump=dump):
                with self.assertRaises(ConversionError):
                    hud_digits._without_reference(dump, "hud_digits_definition", True)


if __name__ == "__main__":
    unittest.main()
