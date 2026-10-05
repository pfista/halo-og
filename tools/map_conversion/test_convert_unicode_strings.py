"""Unicode overlay boundaries; synthetic fixtures contain no game data."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("convert_unicode_strings", Path(__file__).with_name("convert_unicode_strings.py"))
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class UnicodeOverlayBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"; self.source.mkdir()
        self.name = "test.unicode_string_list"
        (self.source / self.name).write_bytes(b"synthetic input; native parser tested separately")
        self.helper = self.root / "helper"; self.helper.write_bytes(b"not executed")
        self.output = self.root / "output"; self.profile_file = self.root / "profile.json"
        self.profile = dict(schema_version=1, target_engine="xbox", write_policy="fresh_overlay",
                            conversion=converter.CONVERSION, encoding="utf-16-le", origin="synthetic reviewed test",
                            converter_source_sha256=converter.sha256(Path(converter.__file__).with_suffix(".cpp")),
                            tags={self.name: dict(sha256=converter.sha256(self.source / self.name), expected_string_count=3)},
                            actions=[dict(tag=self.name, index=1, before="old", after="new", reason="synthetic compatibility")])

    def rejected(self, helper_hash=None):
        self.profile_file.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaises(ValueError):
                converter.convert(self.source, self.profile_file, self.helper,
                                  helper_hash or converter.sha256(self.helper), self.output)
            execute.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_source_hash_and_helper_source_guards_precede_output(self):
        (self.source / self.name).write_bytes(b"changed original")
        self.rejected()
        self.profile["tags"][self.name]["sha256"] = converter.sha256(self.source / self.name)
        self.profile["converter_source_sha256"] = "0" * 64
        self.rejected()

    def test_entry_count_index_boolean_duplicates_and_noop_rejected(self):
        original = json.loads(json.dumps(self.profile))
        for count, index in [(0, 0), (801, 1), (True, 0), (3, -1), (3, 3), (3, True)]:
            self.profile = json.loads(json.dumps(original))
            self.profile["tags"][self.name]["expected_string_count"] = count
            self.profile["actions"][0]["index"] = index
            self.rejected()
        self.profile = json.loads(json.dumps(original)); self.profile["actions"] *= 2; self.rejected()
        self.profile = json.loads(json.dumps(original)); self.profile["actions"][0]["after"] = "old"; self.rejected()

    def test_utf16_null_surrogate_and_size_guards(self):
        for text in ["bad\0inside", "\ud800", "x" * 16384, None]:
            self.profile["actions"][0]["after"] = text
            self.rejected()

    def test_rule_file_encoding_cannot_be_injected_by_text(self):
        self.profile["actions"][0].update(before='\t"example" 😀\r\n', after="replacement\t🧪")
        converter.validate_profile(self.profile)
        line = converter.action_tsv(self.profile)
        self.assertEqual(len(line.splitlines()), 1)
        fields = line.rstrip("\n").split("\t")
        self.assertEqual(len(fields), 5)
        self.assertEqual(bytes.fromhex(fields[3]).decode("utf-16-le"), self.profile["actions"][0]["before"] + "\0")
        self.assertEqual(bytes.fromhex(fields[4]).decode("utf-16-le"), self.profile["actions"][0]["after"] + "\0")

    def test_paths_hashes_provenance_and_selection_guards(self):
        original = json.loads(json.dumps(self.profile))
        for name in ["../test.unicode_string_list", "/test.unicode_string_list", "x//test.unicode_string_list", "test.weapon", "x\\test.unicode_string_list"]:
            self.profile = json.loads(json.dumps(original))
            rule = self.profile["tags"].pop(self.name); self.profile["tags"][name] = rule
            self.profile["actions"][0]["tag"] = name; self.rejected()
        self.profile = json.loads(json.dumps(original)); self.profile["origin"] = ""; self.rejected()
        self.profile = json.loads(json.dumps(original)); self.rejected("0" * 64)
        self.profile = json.loads(json.dumps(original)); self.profile["tags"]["unselected.unicode_string_list"] = self.profile["tags"][self.name]; self.rejected()

    def test_symlink_and_hard_link_sources_rejected(self):
        input_file = self.source / self.name; original = self.root / "original"; input_file.rename(original)
        input_file.symlink_to(original); self.rejected(); input_file.unlink()
        input_file.hardlink_to(original); self.rejected()

    def test_existing_output_is_preserved(self):
        self.output.mkdir(); (self.output / "keep").write_text("existing work")
        self.profile_file.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run") as execute:
            with self.assertRaisesRegex(ValueError, "Output must be new"):
                converter.convert(self.source, self.profile_file, self.helper, converter.sha256(self.helper), self.output)
            execute.assert_not_called()
        self.assertEqual((self.output / "keep").read_text(), "existing work")

    def test_native_failure_leaves_failed_manifest(self):
        self.profile_file.write_text(json.dumps(self.profile))
        with patch.object(converter.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="entry before mismatch")):
            with self.assertRaises(RuntimeError):
                converter.convert(self.source, self.profile_file, self.helper, converter.sha256(self.helper), self.output)
        record = json.loads((self.output / "conversion.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertFalse(record["untouched_entries_verified"])

    def test_success_records_independent_snapshots_and_exact_rule_hex(self):
        self.profile_file.write_text(json.dumps(self.profile))
        def fake_native(command, **kwargs):
            root = Path(command[1]); tags = root / "tags"; tags.mkdir()
            (tags / self.name).write_bytes(b"synthetic converted output")
            return SimpleNamespace(returncode=0, stdout="reparsed and preserved", stderr="")
        with patch.object(converter.subprocess, "run", side_effect=fake_native):
            record = converter.convert(self.source, self.profile_file, self.helper, converter.sha256(self.helper), self.output)
        self.assertEqual(record["status"], "converted")
        self.assertIn("pending", record["runtime_acceptance"])
        snapshot = self.output / "source-snapshots" / self.name
        self.assertEqual(snapshot.read_bytes(), (self.source / self.name).read_bytes())
        self.assertEqual(snapshot.stat().st_nlink, 1)
        self.assertEqual((self.output / "unicode-strings.tsv").read_text(), converter.action_tsv(self.profile))


if __name__ == "__main__":
    unittest.main()
