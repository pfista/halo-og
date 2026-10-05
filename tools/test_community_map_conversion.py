#!/usr/bin/env python3
"""Conversion boundaries: immutable originals, explicit overrides, reviewed HUD inputs."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import community_map_conversion as conversion
from map_conversion import append_netgame_flags as markers


class ConversionBoundaryTests(unittest.TestCase):
    def setUp(self):
        (conversion.ROOT / "build").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="conversion-test-", dir=conversion.ROOT / "build")
        self.folder = Path(self.temporary.name)
        for name in ("source-tags", "stock-tags", "tags", "logs"):
            (self.folder / name).mkdir()
        self.source = self.folder / "input.map"
        self.source.write_bytes(b"unchanged source cache")
        (self.folder / "source-tags/shared.bitmap").write_bytes(b"authored art")
        (self.folder / "tags/shared.bitmap").write_bytes(b"authored art")
        (self.folder / "stock-tags/shared.bitmap").write_bytes(b"stock art")
        (self.folder / "stock-tags/stock.bitmap").write_bytes(b"stock only")
        self.record = {"schema_version": 1, "content_origin": "digsite-restoration",
                       "source_map": {"path": str(self.source), "sha256": conversion.digest(self.source)},
                       "source_tags": conversion.tree(self.folder / "source-tags"),
                       "stock_tags": conversion.tree(self.folder / "stock-tags"), "steps": []}
        conversion.save(self.folder / "conversion.json", self.record)

    def tearDown(self):
        self.temporary.cleanup()

    def test_changed_source_rejected(self):
        (self.folder / "source-tags/shared.bitmap").write_bytes(b"modified original")
        with self.assertRaisesRegex(ValueError, "source tags changed"):
            conversion.load_workspace(self.folder)

    def test_marker_overlay_requires_exact_profile_snapshots_actions_and_output(self):
        overlay = self.folder / "markers"
        tags = overlay / "tags"; tags.mkdir(parents=True)
        (tags / "target.scenario").write_bytes(b"synthetic marker output")
        for label in ("source", "target"):
            snapshot = overlay / "source-snapshots" / label / (label + ".scenario")
            snapshot.parent.mkdir(parents=True); snapshot.write_bytes(b"synthetic " + label.encode())
        source_cpp = overlay / "converter-source.cpp"; source_cpp.write_text("// synthetic helper source")
        profile = {
            "schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
            "conversion": markers.CONVERSION, "origin": "reviewed synthetic stock course",
            "converter_source_sha256": conversion.digest(source_cpp),
            "source": {"tag": "source.scenario", "sha256": conversion.digest(overlay / "source-snapshots/source/source.scenario"), "expected_selected_type_count": 1},
            "target": {"tag": "target.scenario", "sha256": conversion.digest(overlay / "source-snapshots/target/target.scenario"), "expected_flag_count": 0, "expected_selected_type_count": 0},
            "selection": {"type": "race_track", "usage_ids": [0]},
        }
        profile_file = overlay / "reviewed-profile.json"; conversion.save(profile_file, profile)
        actions = overlay / "netgame-flags.tsv"; actions.write_text(markers.action_tsv(profile))
        record = {"schema_version": 1, "conversion": markers.CONVERSION, "status": "converted", "returncode": 0,
                  "source_unchanged": True, "snapshots_unchanged": True,
                  "converter_source_snapshot_unchanged": True, "profile_snapshot_unchanged": True,
                  "profile_sha256": conversion.digest(profile_file),
                  "input_sha256": {label: {profile[label]["tag"]: profile[label]["sha256"]} for label in ("source", "target")},
                  "output_sha256": conversion.tree(tags),
                  **{field: profile[field] for field in ("origin", "source", "target", "selection", "converter_source_sha256")}}
        manifest = overlay / "conversion.json"; conversion.save(manifest, record)
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])
        for field, value in (("status", "pending"), ("returncode", 1), ("source_unchanged", False),
                             ("snapshots_unchanged", False), ("profile_snapshot_unchanged", False)):
            modified = {**record, field: value}; conversion.save(manifest, modified)
            with self.assertRaisesRegex(ValueError, "Incomplete or failed marker"):
                conversion.overlay_roots([overlay])
        conversion.save(manifest, {**record, "selection": {"type": "race_track", "usage_ids": [1]}})
        with self.assertRaisesRegex(ValueError, "actions differ"):
            conversion.overlay_roots([overlay])
        conversion.save(manifest, record)
        for path, message in ((profile_file, "snapshot changed"), (source_cpp, "snapshot changed"),
                              (actions, "actions differ"),
                              (overlay / "source-snapshots/source/source.scenario", "source snapshots changed"),
                              (tags / "target.scenario", "tags changed")):
            original = path.read_bytes(); path.write_bytes(b"changed after conversion")
            with self.assertRaisesRegex(ValueError, message):
                conversion.overlay_roots([overlay])
            path.write_bytes(original)
        (tags / "unexpected.scenario").write_bytes(b"unexpected output")
        with self.assertRaisesRegex(ValueError, "tags changed"):
            conversion.overlay_roots([overlay])

    def test_changed_stock_baseline_rejected(self):
        (self.folder / "stock-tags/stock.bitmap").write_bytes(b"community replacement")
        with self.assertRaisesRegex(ValueError, "Stock baseline changed"):
            conversion.load_workspace(self.folder)

    def test_provenance_distinguishes_authored_stock_and_overlay(self):
        (self.folder / "tags/stock.bitmap").write_bytes(b"stock only")
        args = argparse.Namespace(workspace=self.folder, overlay=[])
        conversion.provenance(args)
        report = json.loads((self.folder / "provenance.json").read_text())["tags"]
        self.assertEqual(report["shared.bitmap"]["origin"], "digsite-restoration")
        self.assertEqual(report["stock.bitmap"]["origin"], "stock-xbox")
        self.assertEqual(report["stock.bitmap"]["tree"], str(self.folder / "tags"))
        overlay = self.folder / "revision"
        (overlay / "tags").mkdir(parents=True)
        (overlay / "tags/shared.bitmap").write_bytes(b"normalized authored artwork")
        args.overlay = [overlay]
        conversion.provenance(args)
        report = json.loads((self.folder / "provenance.json").read_text())["tags"]
        self.assertEqual(report["shared.bitmap"]["origin"], "community-conversion")
        self.assertEqual(report["shared.bitmap"]["sha256"], conversion.digest(overlay / "tags/shared.bitmap"))

    def test_missing_overlay_and_symlink_inputs_rejected(self):
        missing = self.folder / "empty-overlay"
        missing.mkdir()
        with self.assertRaisesRegex(ValueError, "tags directory"):
            conversion.overlay_roots([missing])
        (self.folder / "tags/outside.bitmap").symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            conversion.tree(self.folder / "tags")
        linked = self.folder / "linked-overlay"
        linked.mkdir()
        (linked / "tags").symlink_to(self.folder / "tags", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            conversion.overlay_roots([linked])

    def test_unknown_managed_overlay_discriminator_rejected(self):
        overlay = self.folder / "unknown-overlay"
        tags = overlay / "tags"
        tags.mkdir(parents=True)
        (tags / "shared.bitmap").write_bytes(b"unvalidated output")
        for field in ("operation", "conversion"):
            conversion.save(overlay / "conversion.json", {
                field: "typo-conversion", "status": "failed", "returncode": 1,
                "source_unchanged": False})
            with self.assertRaisesRegex(ValueError, "Unknown overlay conversion"):
                conversion.overlay_roots([overlay])
        conversion.save(overlay / "conversion.json", {"schema_version": 1, "steps": []})
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])

    def test_failed_or_changed_recorded_hud_overlay_rejected(self):
        overlay = self.folder / "hud-overlay"
        tags = overlay / "tags"
        tags.mkdir(parents=True)
        tag = tags / "shared.bitmap"
        tag.write_bytes(b"normalized authored artwork")
        record = {"operation": "hud-overlay", "exit_code": 1, "source_unchanged": True,
                  "profile": {"tags": self.record["source_tags"]},
                  "changes": [{"tag": "shared.bitmap", "before": self.record["source_tags"]["shared.bitmap"],
                               "after": conversion.digest(tag)}]}
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "Failed HUD overlays"):
            conversion.overlay_roots([overlay])
        record["exit_code"] = 0
        conversion.save(overlay / "conversion.json", record)
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])
        tag.write_bytes(b"changed after validation")
        with self.assertRaisesRegex(ValueError, "changed after recorded"):
            conversion.overlay_roots([overlay])

    def test_stale_hud_profile_rejected_before_output_or_execution(self):
        converter = self.folder / "never-execute"
        converter.write_bytes(b"not an executable")
        profile = self.folder / "profile.json"
        conversion.save(profile, {"schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
                                 "source_tree": "source-tags", "tags": {"shared.bitmap": "0" * 64},
                                 "field_rules": [], "bitmap_resamples": []})
        output = self.folder / "rejected-output"
        args = argparse.Namespace(workspace=self.folder, profile=profile, converter=converter,
                                  converter_sha256=conversion.digest(converter), output=output)
        with self.assertRaisesRegex(ValueError, "source differs"):
            conversion.hud_overlay(args)
        self.assertFalse(output.exists())
        conversion.save(profile, {"schema_version": 1, "target_engine": "xbox", "write_policy": "fresh_overlay",
                                 "source_tree": "source-tags", "tags": self.record["source_tags"],
                                 "field_rules": [{"tag": "shared.bitmap", "field": "bitmap_data[0].width",
                                                  "before": 1, "after": float("nan"), "reason": "invalid test input"}],
                                 "bitmap_resamples": []})
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            conversion.hud_overlay(args)
        self.assertFalse(output.exists())

    def test_pending_failed_or_changed_recorded_sound_overlay_rejected(self):
        overlay = self.folder / "sound-overlay"
        tags = overlay / "tags"
        tags.mkdir(parents=True)
        tag = tags / "ready.sound"
        tag.write_bytes(b"converted sound")
        snapshots = overlay / "source-snapshots"
        snapshots.mkdir()
        snapshot = snapshots / "ready.sound"
        snapshot.write_bytes(b"authored PCM")
        record = {"schema_version": 1, "conversion": "16_bit_pcm_to_xbox_adpcm", "status": "pending",
                  "returncode": 0, "source_unchanged": True,
                  "input_sha256": conversion.tree(snapshots),
                  "output_sha256": conversion.tree(tags)}
        for status, returncode, unchanged in (("pending", 0, True), ("failed", 1, True),
                                            ("converted", 0, False)):
            record.update(status=status, returncode=returncode, source_unchanged=unchanged)
            conversion.save(overlay / "conversion.json", record)
            with self.assertRaisesRegex(ValueError, "Incomplete or failed sound overlays"):
                conversion.overlay_roots([overlay])
        record.update(status="converted", returncode=0, source_unchanged=True)
        conversion.save(overlay / "conversion.json", record)
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])
        record["schema_version"] = 2
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "input and output identities"):
            conversion.overlay_roots([overlay])
        record["schema_version"] = 1
        record["output_sha256"]["unexpected.sound"] = "0" * 64
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "input and output identities"):
            conversion.overlay_roots([overlay])
        del record["output_sha256"]["unexpected.sound"]
        conversion.save(overlay / "conversion.json", record)
        snapshot.write_bytes(b"changed original snapshot")
        with self.assertRaisesRegex(ValueError, "source snapshots changed"):
            conversion.overlay_roots([overlay])
        snapshot.write_bytes(b"authored PCM")
        tag.write_bytes(b"changed after conversion")
        with self.assertRaisesRegex(ValueError, "changed after recorded"):
            conversion.overlay_roots([overlay])

    def test_compile_retry_preserves_unrecorded_build(self):
        orphan = self.folder / "builds/001/maps/partial.map"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"preserved incomplete diagnostic artifact")
        binary = self.folder / "bin"
        binary.mkdir()
        (binary / "invader-build").write_bytes(b"reviewed compiler placeholder")
        tool = SimpleNamespace(binary=binary, commit="reviewed-test-commit")
        args = argparse.Namespace(workspace=self.folder, scenario="levels/test/test",
                                  overlay=[], data=None, reviewed_build_manifest=None)
        failed = SimpleNamespace(returncode=1, stdout="", stderr="expected test compiler failure")
        with patch.object(conversion, "tool_for", return_value=(tool, self.folder / "logs")), \
                patch.object(conversion.subprocess, "run", return_value=failed) as compiler:
            with self.assertRaisesRegex(RuntimeError, "Compilation or native cache checks failed"):
                conversion.compile_map(args)
        self.assertEqual(orphan.read_bytes(), b"preserved incomplete diagnostic artifact")
        command = compiler.call_args.args[0]
        self.assertEqual(Path(command[command.index("-m") + 1]), self.folder / "builds/002/maps")
        record = json.loads((self.folder / "conversion.json").read_text())
        self.assertEqual(record["steps"][-1]["exit_code"], 1)
        self.assertEqual(record["steps"][-1]["status"], "compile failed")

    def test_mip_overlay_requires_preserved_bytes_and_reviewed_selection(self):
        overlay = self.folder / "mip-overlay"
        snapshots, tags = overlay / "source-snapshots", overlay / "tags"
        snapshots.mkdir(parents=True)
        tags.mkdir()
        name = "skin.bitmap"
        (snapshots / name).write_bytes(b"all original authored mips")
        (tags / name).write_bytes(b"original lower authored mips")
        record = {"schema_version": 1, "conversion": "select_existing_lower_bitmap_mip", "status": "converted",
                  "returncode": 0, "source_unchanged": True, "snapshots_unchanged": True,
                  "lower_mip_bytes_preserved": True,
                  "actions": [{"tag": name, "bitmap_index": 0, "drop_top_mips": 1}],
                  "input_sha256": conversion.tree(snapshots), "output_sha256": conversion.tree(tags)}
        conversion.save(overlay / "conversion.json", record)
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])
        record["lower_mip_bytes_preserved"] = False
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "Incomplete or failed mip"):
            conversion.overlay_roots([overlay])
        record["lower_mip_bytes_preserved"] = True
        record["actions"][0]["drop_top_mips"] = 2
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "single-image top-mip selection"):
            conversion.overlay_roots([overlay])
        record["actions"][0]["drop_top_mips"] = 1
        conversion.save(overlay / "conversion.json", record)
        (snapshots / name).write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "source snapshots changed"):
            conversion.overlay_roots([overlay])
        (snapshots / name).write_bytes(b"all original authored mips")
        (tags / name).write_bytes(b"changed converted tag")
        with self.assertRaisesRegex(ValueError, "Mip overlay tags changed"):
            conversion.overlay_roots([overlay])

    def test_weapon_alias_overlay_preserves_weapon_bytes_and_stock_globals(self):
        overlay = self.folder / "alias-overlay"
        snapshots, tags = overlay / "source-snapshots", overlay / "tags"
        snapshots.mkdir(parents=True)
        tags.mkdir()
        weapon, alias, globals_tag, owner = "original.weapon", "community.weapon", "globals.globals", "fiesta.item_collection"
        for name in (weapon, globals_tag, owner):
            (snapshots / name).write_bytes(b"original " + name.encode())
        (tags / alias).write_bytes((snapshots / weapon).read_bytes())
        (tags / owner).write_bytes(b"one reviewed alias reference")
        record = {"schema_version": 1, "conversion": "map_local_weapon_alias", "status": "converted",
                  "returncode": 0, "source_unchanged": True, "snapshots_unchanged": True,
                  "alias_bytes_identical": True, "globals_unchanged": True,
                  "alias": {"source_weapon": weapon, "alias_weapon": alias, "globals_tag": globals_tag, "reserved_slot": 1},
                  "reference_rules": [{"tag": owner, "expected_replacements": 1}],
                  "input_sha256": conversion.tree(snapshots), "output_sha256": conversion.tree(tags)}
        conversion.save(overlay / "conversion.json", record)
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])
        record["globals_unchanged"] = False
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "Incomplete or failed weapon alias"):
            conversion.overlay_roots([overlay])
        record["globals_unchanged"] = True
        record["output_sha256"][globals_tag] = record["input_sha256"][globals_tag]
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "exclude stock globals"):
            conversion.overlay_roots([overlay])
        del record["output_sha256"][globals_tag]
        record["output_sha256"][alias] = "0" * 64
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "preserve weapon bytes"):
            conversion.overlay_roots([overlay])
        record["output_sha256"][alias] = record["input_sha256"][weapon]
        conversion.save(overlay / "conversion.json", record)
        (snapshots / weapon).write_bytes(b"changed source weapon")
        with self.assertRaisesRegex(ValueError, "source snapshots changed"):
            conversion.overlay_roots([overlay])

    def test_shader_overlay_requires_completed_conversion_and_preserved_provenance(self):
        overlay = self.folder / "shader-overlay"
        snapshots, tags = overlay / "source-snapshots", overlay / "tags"
        snapshots.mkdir(parents=True)
        tags.mkdir()
        parent, child = "numbers.shader_transparent_chicago", "duplicate.shader_transparent_chicago"
        for name in (parent, child, "digits.bitmap"):
            (snapshots / name).write_bytes(b"reviewed original " + name.encode())
        (tags / parent).write_bytes(b"converted parent shader")
        record = {"schema_version": 1, "conversion": "remove_proven_duplicate_chicago_extra_layer",
                  "status": "pending", "returncode": 0, "source_unchanged": True,
                  "snapshots_unchanged": True, "actions": [{"parent": parent, "duplicate_layer": child}],
                  "input_sha256": conversion.tree(snapshots), "output_sha256": conversion.tree(tags)}
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "Incomplete or failed shader overlays"):
            conversion.overlay_roots([overlay])
        record["status"] = "converted"
        conversion.save(overlay / "conversion.json", record)
        self.assertEqual(conversion.overlay_roots([overlay]), [tags])
        record["output_sha256"][child] = "0" * 64
        conversion.save(overlay / "conversion.json", record)
        with self.assertRaisesRegex(ValueError, "reviewed parent identities"):
            conversion.overlay_roots([overlay])
        del record["output_sha256"][child]
        conversion.save(overlay / "conversion.json", record)
        (snapshots / child).write_bytes(b"changed layer")
        with self.assertRaisesRegex(ValueError, "source snapshots changed"):
            conversion.overlay_roots([overlay])
        (snapshots / child).write_bytes(b"reviewed original " + child.encode())
        (tags / parent).write_bytes(b"changed shader")
        with self.assertRaisesRegex(ValueError, "tags changed after recorded"):
            conversion.overlay_roots([overlay])


if __name__ == "__main__":
    unittest.main()
