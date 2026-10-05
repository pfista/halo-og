"""Sound overlay boundary checks; no proprietary fixture or codec tool needed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("convert_sounds", Path(__file__).with_name("convert_sounds.py"))
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class SoundOverlayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.tag = self.source / "example.sound"
        self.tag.write_bytes(b"not an audio asset; boundary-only fixture")
        self.helper = self.root / "helper"
        self.helper.write_bytes(b"not executed")
        self.output = self.root / "output"
        self.profile_path = self.root / "profile.json"
        self.profile = {
            "schema_version": 1, "target_engine": "xbox",
            "write_policy": "fresh_overlay", "conversion": "16_bit_pcm_to_xbox_adpcm",
            "tags": {"example.sound": converter.sha256(self.tag)},
        }

    def rejected_before_execution(self, helper_hash=None):
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaises(ValueError):
                converter.convert(self.source, self.profile_path, self.helper,
                                  helper_hash or converter.sha256(self.helper), self.output)
            execute.assert_not_called()

    def test_stale_source_hash_creates_no_output(self):
        self.tag.write_bytes(b"changed input")
        self.rejected_before_execution()
        self.assertFalse(self.output.exists())

    def test_traversal_creates_no_output(self):
        self.profile["tags"] = {"../example.sound": "0" * 64}
        self.rejected_before_execution()
        self.assertFalse(self.output.exists())

    def test_symlink_source_creates_no_output(self):
        real = self.root / "outside.sound"
        self.tag.rename(real)
        self.tag.symlink_to(real)
        self.rejected_before_execution()
        self.assertFalse(self.output.exists())

    def test_helper_hash_mismatch_creates_no_output(self):
        self.rejected_before_execution("0" * 64)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("existing user work")
        self.rejected_before_execution()
        self.assertEqual(sentinel.read_text(), "existing user work")


if __name__ == "__main__":
    unittest.main()
