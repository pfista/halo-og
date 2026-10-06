"""Alias overlay boundaries; fixtures contain no game assets."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("convert_weapon_alias", Path(__file__).with_name("convert_weapon_alias.py"))
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class WeaponAliasBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.original = "weapons/example/example.weapon"
        self.alias = "community/example/example.weapon"
        self.owner = "item collections/example.item_collection"
        for name in (self.original, converter.GLOBALS, self.owner):
            file = self.source / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"boundary fixture; not a real tag")
        self.helper = self.root / "helper"
        self.helper.write_bytes(b"not executed")
        self.output = self.root / "output"
        self.profile_path = self.root / "profile.json"
        self.profile = {
            "schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
            "conversion": converter.CONVERSION,
            "alias": {"source_weapon": self.original, "alias_weapon": self.alias,
                      "globals_tag": converter.GLOBALS, "reserved_slot": 1},
            "reference_rules": [{"tag": self.owner, "expected_replacements": 1}],
            "tags": {name: converter.sha256(self.source / name)
                     for name in (self.original, converter.GLOBALS, self.owner)},
        }

    def rejected(self, helper_hash=None):
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaises(ValueError):
                converter.convert(self.source, self.profile_path, self.helper,
                                  helper_hash or converter.sha256(self.helper), self.output)
            execute.assert_not_called()

    def test_changed_weapon_is_rejected_before_output(self):
        (self.source / self.original).write_bytes(b"changed")
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_globals_cannot_be_a_reference_owner(self):
        self.profile["reference_rules"] = [{"tag": converter.GLOBALS, "expected_replacements": 1}]
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_unpinned_owner_is_rejected(self):
        del self.profile["tags"][self.owner]
        self.rejected()

    def test_alias_must_have_community_identity(self):
        self.profile["alias"]["alias_weapon"] = "weapons/renamed.weapon"
        self.rejected()

    def test_alias_traversal_is_rejected(self):
        self.profile["alias"]["alias_weapon"] = "community/../outside.weapon"
        self.rejected()

    def test_replacement_count_must_be_positive_integer(self):
        for invalid in (0, -1, True, "1"):
            with self.subTest(invalid=invalid):
                self.profile["reference_rules"][0]["expected_replacements"] = invalid
                self.rejected()

    def test_duplicate_owner_is_rejected(self):
        self.profile["reference_rules"] *= 2
        self.rejected()

    def test_existing_alias_is_preserved(self):
        file = self.source / self.alias
        file.parent.mkdir(parents=True)
        file.write_bytes(b"existing author identity")
        self.rejected()
        self.assertEqual(file.read_bytes(), b"existing author identity")

    def test_symlink_owner_is_rejected(self):
        file = self.source / self.owner
        outside = self.root / "outside.item_collection"
        file.rename(outside)
        file.symlink_to(outside)
        self.rejected()

    def test_hard_link_weapon_is_rejected(self):
        (self.root / "linked.weapon").hardlink_to(self.source / self.original)
        self.rejected()

    def test_stale_helper_is_rejected(self):
        self.rejected("0" * 64)

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("existing work")
        self.rejected()
        self.assertEqual(sentinel.read_text(), "existing work")


if __name__ == "__main__":
    unittest.main()
