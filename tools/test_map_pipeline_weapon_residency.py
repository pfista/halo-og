"""Native weapon residency without extra Globals weapon roles or game runs."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.map_pipeline import weapon_residency as residency
from tools.map_pipeline.backend import ConversionError, _tree, legacy


class FakeInvader:
    stage = "canonical_weapons"

    def __init__(self, fault=None):
        self.fault = fault

    def body(self, root, name):
        return json.loads((Path(root) / name).read_text())

    def count(self, root, name, field):
        return len(self.body(root, name)[field])

    def get(self, root, name, field):
        return self.body(root, name)["tags"][int(field.split("[")[1].split("]")[0])]["reference"]

    def run(self, kind, *args):
        args = list(map(str, args))
        roots = [Path(args[index + 1]) for index, arg in enumerate(args) if arg == "-t"]
        tag = args[-1]
        if kind == "dependency":
            seen = set()
            def walk(name):
                if name in seen:
                    return
                seen.add(name)
                at = next(root / name for root in roots if (root / name).is_file())
                body = json.loads(at.read_text())
                refs = [entry["reference"] for entry in body.get("tags", [])] + body.get("dependencies", [])
                for reference in refs:
                    walk(reference)
            walk(tag)
            return "\n".join(sorted(seen - {tag}))
        if kind != "edit":
            raise AssertionError(kind)
        target = roots[0] / tag
        body = {"tags": []} if "-N" in args else self.body(roots[0], tag)
        index = 0
        while index < len(args) - 1:
            if args[index] == "-I":
                array, count, at = args[index + 1:index + 4]
                at = len(body[array]) if at == "end" else int(at)
                body[array][at:at] = [{"reference": ""} for _ in range(int(count))]
                index += 4
            elif args[index] == "-S":
                field, value = args[index + 1:index + 3]
                body["tags"][int(field.split("[")[1].split("]")[0])]["reference"] = value
                index += 3
            else:
                index += 1
        if self.fault:
            self.fault(tag, body)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, sort_keys=True))
        return ""


class ResidencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source, self.overlay = self.base / "source", self.base / "overlay"
        self.source.mkdir()
        self.overlay.mkdir()
        self.ui = "ui/native_pause.ui_widget_definition"
        self.weapon = "weapons/recovered/example.weapon"
        self.model = "weapons/recovered/example.model"
        self.tag(self.source, residency.SOUL, {"tags": [{"reference": self.ui}]})
        self.tag(self.source, self.ui, {"dependencies": []})
        self.tag(self.source, self.weapon, {"dependencies": [self.model]})
        self.tag(self.source, self.model, {"dependencies": []})
        self.tag(self.overlay, "unchanged.bitmap", {"dependencies": []})
        self.protected = {}

    def tag(self, root, name, body):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, sort_keys=True))

    def attach(self, weapons=None, tool=None, roots=None, overlay=None):
        return residency.attach_weapon_residency(tool or FakeInvader(), roots or [self.overlay, self.source],
            [self.weapon] if weapons is None else weapons, overlay or self.overlay, self.protected)

    def test_admitted_assets_are_resident_and_native_soul_prefix_and_sources_preserved(self):
        before = _tree(self.source)
        old_owned = legacy.digest(self.overlay / "unchanged.bitmap")
        action = self.attach()
        self.assertEqual(_tree(self.source), before)
        self.assertEqual(legacy.digest(self.overlay / "unchanged.bitmap"), old_owned)
        self.assertEqual(action["weapon_references"], [self.weapon])
        self.assertEqual(action["soul_references_after"], [self.ui, residency.COLLECTION])
        self.assertEqual(set(action["dependency_tags"]), {residency.COLLECTION, self.weapon, self.model})
        self.assertTrue(action["native_reparse_verified"] and action["dependency_residency_verified"])
        self.assertEqual(action["gameplay_validation"], "pending")
        self.assertEqual({path.name for path in self.overlay.iterdir()}, {"unchanged.bitmap", "__native_policy", "ui"})
        for name, checksum in action["output_sha256"].items():
            self.assertEqual(self.protected[self.overlay / name], checksum)

    def test_empty_admission_does_not_write_any_collection(self):
        before = _tree(self.overlay)
        self.assertIsNone(self.attach(weapons=[]))
        self.assertEqual(_tree(self.overlay), before)

    def test_more_than_twenty_weapons_use_resident_collection_without_matg(self):
        weapons = [self.weapon]
        for index in range(30):
            name = f"weapons/recovered/asset_{index}.weapon"
            self.tag(self.source, name, {"dependencies": []})
            weapons.append(name)
        action = self.attach(weapons=weapons)
        self.assertEqual(action["weapon_references"], weapons)
        self.assertFalse((self.overlay / "globals/globals.globals").exists())
        self.assertEqual(FakeInvader().count(self.overlay, residency.COLLECTION, "tags"), 31)

    def test_weapon_bound_soul_capacity_and_missing_assets_fail_closed(self):
        with self.assertRaises(ConversionError):
            self.attach(weapons=[self.weapon] * 201)
        with self.assertRaises(ConversionError):
            self.attach(weapons=["unreviewed/missing.weapon"])
        self.protected.clear()
        self.tag(self.source, residency.SOUL, {"tags": [{"reference": self.ui}] * 200})
        with self.assertRaisesRegex(ConversionError, "cannot safely attach"):
            self.attach()
        self.assertFalse((self.overlay / residency.COLLECTION).exists())

    def test_reimport_verifies_reserved_scope_rederives_and_keeps_one_link(self):
        first = self.attach()
        second_overlay = self.base / "repeat"
        second_overlay.mkdir()
        second = self.attach(roots=[self.overlay, self.source], overlay=second_overlay)
        self.assertEqual(second["weapon_references"], first["weapon_references"])
        self.assertEqual(second["inserted_soul_references"], [])
        self.assertEqual(second["soul_references_after"].count(residency.COLLECTION), 1)
        self.assertEqual(second["output_sha256"][residency.COLLECTION], first["output_sha256"][residency.COLLECTION])

    def test_stale_or_duplicate_reserved_scope_is_rejected(self):
        self.tag(self.source, residency.COLLECTION, {"tags": [{"reference": self.weapon}, {"reference": self.weapon}]})
        with self.assertRaisesRegex(ConversionError, "stale or unapproved"):
            self.attach()
        self.protected.clear()
        self.tag(self.source, residency.COLLECTION, {"tags": [{"reference": self.weapon}]})
        self.tag(self.source, residency.SOUL, {"tags": [{"reference": residency.COLLECTION}] * 2})
        with self.assertRaisesRegex(ConversionError, "duplicate reserved"):
            self.attach()

    def test_mutation_readback_prefix_change_and_dependency_cycle_are_rejected(self):
        before = _tree(self.source)
        def wrong(tag, body):
            if tag == residency.SOUL:
                body["tags"][0]["reference"] = self.weapon
        with self.assertRaisesRegex(ConversionError, "existing Xbox Soul reference"):
            self.attach(tool=FakeInvader(wrong))
        self.assertEqual(_tree(self.source), before)
        shutil.rmtree(self.overlay)
        self.overlay.mkdir()
        self.protected.clear()
        self.tag(self.source, self.weapon, {"dependencies": [residency.SOUL]})
        with self.assertRaisesRegex(ConversionError, "cycle"):
            self.attach()

    def test_source_mutation_is_rejected_even_on_other_helper_failure(self):
        def changed(tag, body):
            self.tag(self.source, self.model, {"dependencies": [], "mutated": True})
        with self.assertRaisesRegex(ConversionError, "immutable input tree"):
            self.attach(tool=FakeInvader(changed))

    def test_collection_readback_and_missing_soul_are_precise_failures(self):
        def wrong(tag, body):
            if tag == residency.COLLECTION:
                body["tags"][0]["reference"] = self.ui
        with self.assertRaisesRegex(ConversionError, "exact native readback"):
            self.attach(tool=FakeInvader(wrong))
        shutil.rmtree(self.overlay)
        self.overlay.mkdir()
        self.protected.clear()
        (self.source / residency.SOUL).unlink()
        with self.assertRaisesRegex(ConversionError, "implicit multiplayer Soul"):
            self.attach()


if __name__ == "__main__":
    unittest.main()
