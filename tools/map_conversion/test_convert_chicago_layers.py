"""Shader overlay boundary checks; no proprietary art or native helper needed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("convert_chicago_layers", Path(__file__).with_name("convert_chicago_layers.py"))
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class ChicagoOverlayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.parent = "counter.shader_transparent_chicago"
        self.child = "duplicate.shader_transparent_chicago"
        for name in (self.parent, self.child, "counter.bitmap", "duplicate.bitmap"):
            (self.source / name).write_bytes(b"boundary-only fixture; no game asset")
        self.helper = self.root / "helper"
        self.helper.write_bytes(b"not executed")
        self.output = self.root / "output"
        self.profile_path = self.root / "profile.json"
        self.profile = {
            "schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
            "conversion": converter.CONVERSION,
            "tags": {p.name: converter.sha256(p) for p in self.source.iterdir()},
            "actions": [{"parent": self.parent, "duplicate_layer": self.child}],
        }

    def rejected(self, helper_hash=None):
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaises(ValueError):
                converter.convert(self.source, self.profile_path, self.helper,
                                  helper_hash or converter.sha256(self.helper), self.output)
            execute.assert_not_called()

    def test_changed_dependency_fails_before_output(self):
        (self.source / self.child).write_bytes(b"changed input")
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_action_requires_guarded_child(self):
        del self.profile["tags"][self.child]
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_traversal_fails_before_output(self):
        self.profile["tags"]["../counter.bitmap"] = "0" * 64
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_duplicate_action_fails_before_output(self):
        self.profile["actions"] *= 2
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_symlink_dependency_fails_before_output(self):
        name = self.source / self.child
        outside = self.root / self.child
        name.rename(outside)
        name.symlink_to(outside)
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_hard_link_dependency_fails_before_output(self):
        outside = self.root / "linked.bitmap"
        outside.hardlink_to(self.source / "counter.bitmap")
        self.rejected()
        self.assertFalse(self.output.exists())

    def test_stale_helper_fails_before_output(self):
        self.rejected("0" * 64)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("existing work")
        self.rejected()
        self.assertEqual(sentinel.read_text(), "existing work")


if __name__ == "__main__":
    unittest.main()
