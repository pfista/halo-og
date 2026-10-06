"""Marker import guards; synthetic boundary fixtures contain no game assets."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("append_netgame_flags", Path(__file__).with_name("append_netgame_flags.py"))
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class MarkerOverlayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.target = self.root / "source", self.root / "target"
        self.source.mkdir(); self.target.mkdir()
        (self.source / "source.scenario").write_bytes(b"source fixture; no asset")
        (self.target / "target.scenario").write_bytes(b"target fixture; no asset")
        self.helper = self.root / "helper"
        self.helper.write_bytes(b"not executed")
        self.output = self.root / "output"
        self.profile_path = self.root / "profile.json"
        self.profile = {
            "schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
            "conversion": converter.CONVERSION, "origin": "reviewed synthetic compatibility fixture",
            "converter_source_sha256": converter.sha256(Path(converter.__file__).with_suffix(".cpp")),
            "source": {"tag": "source.scenario", "sha256": converter.sha256(self.source / "source.scenario"), "expected_selected_type_count": 3},
            "target": {"tag": "target.scenario", "sha256": converter.sha256(self.target / "target.scenario"), "expected_flag_count": 0, "expected_selected_type_count": 0},
            "selection": {"type": "race_track", "usage_ids": [0, 1, 2]},
        }

    def rejected(self, helper_hash=None):
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaises(ValueError):
                converter.convert(self.source, self.target, self.profile_path, self.helper,
                                  helper_hash or converter.sha256(self.helper), self.output)
            execute.assert_not_called()

    def test_changed_source_and_target_fail_before_output(self):
        for root, name in ((self.source, "source.scenario"), (self.target, "target.scenario")):
            with self.subTest(name=name):
                previous = (root / name).read_bytes()
                (root / name).write_bytes(b"changed")
                self.rejected(); self.assertFalse(self.output.exists())
                (root / name).write_bytes(previous)

    def test_traversal_and_unnormalized_paths_rejected(self):
        for name in ("../source.scenario", "/source.scenario", "x//source.scenario", "x\\source.scenario", "source.weapon"):
            self.profile["source"]["tag"] = name
            self.rejected(); self.assertFalse(self.output.exists())

    def test_duplicate_boolean_and_out_of_range_race_ids_rejected(self):
        for ids in ([0, 0], [True], [-1], [32], []):
            self.profile["selection"]["usage_ids"] = ids
            self.rejected(); self.assertFalse(self.output.exists())

    def test_native_flag_limit_and_count_expectations_rejected(self):
        for source_count, target_count, target_type in ((2, 0, 0), (3, 198, 0), (3, True, 0), (3, 0, 1)):
            self.profile["source"]["expected_selected_type_count"] = source_count
            self.profile["target"]["expected_flag_count"] = target_count
            self.profile["target"]["expected_selected_type_count"] = target_type
            self.rejected(); self.assertFalse(self.output.exists())

    def test_polygon_vehicle_and_unknown_types_rejected(self):
        for type_name in ("hill_flag", "race_vehicle", "ctf_vehicle", "unknown"):
            self.profile["selection"]["type"] = type_name
            self.rejected(); self.assertFalse(self.output.exists())

    def test_no_provenance_or_stale_converter_source_rejected(self):
        self.profile["origin"] = ""
        self.rejected()
        self.profile["origin"] = "reviewed source"
        self.profile["converter_source_sha256"] = "0" * 64
        self.rejected(); self.assertFalse(self.output.exists())

    def test_symlink_and_hard_link_scenarios_rejected(self):
        source_file = self.source / "source.scenario"
        original = self.root / "original.scenario"
        source_file.rename(original); source_file.symlink_to(original)
        self.rejected(); source_file.unlink(); source_file.hardlink_to(original)
        self.rejected(); self.assertFalse(self.output.exists())

    def test_stale_helper_rejected(self):
        self.rejected("0" * 64); self.assertFalse(self.output.exists())

    def test_existing_output_preserved(self):
        self.output.mkdir(); sentinel = self.output / "keep.txt"; sentinel.write_text("existing work")
        self.rejected(); self.assertEqual(sentinel.read_text(), "existing work")

    def test_failed_native_helper_cannot_be_converted(self):
        self.profile_path.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="duplicate native marker")):
            with self.assertRaises(RuntimeError):
                converter.convert(self.source, self.target, self.profile_path, self.helper,
                                  converter.sha256(self.helper), self.output)
        record = json.loads((self.output / "conversion.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["output_sha256"], {})

    def test_success_records_exact_independent_snapshots_and_pending_acceptance(self):
        self.profile_path.write_text(json.dumps(self.profile))
        def fake_native(command, **kwargs):
            output = Path(command[1]); tags = output / "tags"; tags.mkdir()
            (tags / "target.scenario").write_bytes(b"synthetic output; no asset")
            return SimpleNamespace(returncode=0, stdout="fields preserved", stderr="")
        with patch.object(converter.subprocess, "run", side_effect=fake_native):
            result = converter.convert(self.source, self.target, self.profile_path, self.helper,
                                       converter.sha256(self.helper), self.output)
        self.assertEqual(result["status"], "converted")
        self.assertIn("pending", result["runtime_acceptance"])
        self.assertEqual((self.output / "netgame-flags.tsv").read_text(), "source.scenario\ttarget.scenario\t3\t3\t0\t0\n0\n1\n2\n")
        for label, original in (("source", self.source), ("target", self.target)):
            snapshot = self.output / "source-snapshots" / label / (label + ".scenario")
            self.assertEqual(snapshot.read_bytes(), (original / (label + ".scenario")).read_bytes())
            self.assertEqual(snapshot.stat().st_nlink, 1)


if __name__ == "__main__":
    unittest.main()
