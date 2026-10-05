"""Authored mip selection boundaries; no proprietary bitmap data."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("select_existing_mip", Path(__file__).with_name("select_existing_mip.py"))
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class ExistingMipBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.tag = "reviewed.bitmap"
        (self.source / self.tag).write_bytes(b"boundary fixture; not a real bitmap")
        self.helper = self.root / "helper"
        self.helper.write_bytes(b"not executed")
        self.output = self.root / "output"
        self.profile_path = self.root / "profile.json"
        self.profile = {
            "schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
            "conversion": converter.CONVERSION,
            "tags": {self.tag: converter.sha256(self.source / self.tag)},
            "actions": [{"tag": self.tag, "bitmap_index": 0, "drop_top_mips": 1}],
        }

    def rejected(self, helper_hash=None):
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaises(ValueError):
                converter.convert(self.source, self.profile_path, self.helper,
                                  helper_hash or converter.sha256(self.helper), self.output)
            execute.assert_not_called()

    def test_changed_bitmap_fails_before_output(self):
        (self.source / self.tag).write_bytes(b"changed")
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_action_requires_pinned_input(self):
        self.profile["actions"][0]["tag"] = "other.bitmap"
        self.rejected()

    def test_traversal_fails_before_output(self):
        action = self.profile["actions"][0]
        action["tag"] = "../outside.bitmap"
        self.profile["tags"] = {action["tag"]: "0" * 64}
        self.rejected()

    def test_only_reviewed_single_top_mip_supported(self):
        for field, bad in (("bitmap_index", 1), ("bitmap_index", False),
                           ("drop_top_mips", 2), ("drop_top_mips", True)):
            with self.subTest(field=field, bad=bad):
                action = self.profile["actions"][0]
                previous = action[field]
                action[field] = bad
                self.rejected()
                action[field] = previous

    def test_duplicate_action_is_rejected(self):
        self.profile["actions"] *= 2
        self.rejected()

    def test_symlink_bitmap_is_rejected(self):
        file = self.source / self.tag
        outside = self.root / self.tag
        file.rename(outside)
        file.symlink_to(outside)
        self.rejected()

    def test_hard_link_bitmap_is_rejected(self):
        (self.root / "linked.bitmap").hardlink_to(self.source / self.tag)
        self.rejected()

    def test_stale_helper_is_rejected(self):
        self.rejected("0" * 64)

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("existing work")
        self.rejected()
        self.assertEqual(sentinel.read_text(), "existing work")

    def test_native_success_without_preservation_proof_is_failed(self):
        self.profile_path.write_text(json.dumps(self.profile))
        result = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(converter.subprocess, "run", return_value=result):
            with self.assertRaises(RuntimeError):
                converter.convert(self.source, self.profile_path, self.helper,
                                  converter.sha256(self.helper), self.output)
        record = json.loads((self.output / "conversion.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertFalse(record["lower_mip_bytes_preserved"])
        self.assertEqual((self.source / self.tag).read_bytes(),
                         (self.output / "source-snapshots" / self.tag).read_bytes())


if __name__ == "__main__":
    unittest.main()
