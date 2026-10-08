"""Offline batch contracts with synthetic caches and a controlled compiler adapter."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.convert_maps import main
from tools.map_pipeline import pipeline, profiles
from tools.map_pipeline.backend import ConversionError


def cache_bytes(version=5, name="arena", build=None, scenario_type=1):
    data = bytearray(0x900)
    if version == 6:
        data[0x2C0:0x2C4], data[0x5F0:0x5F4] = b"dehE", b"tofG"
        offsets = (0x588, 0x5E8, 0x5EC, 0x2C4, 0x58C, 0x2C8, 2)
    else:
        data[:4], data[0x7FC:0x800] = b"daeh", b"toof"
        offsets = (4, 8, 16, 20, 32, 64, 96)
    for offset, value in zip(offsets[:4], (version, len(data), 0x840, 0x40)):
        struct.pack_into("<I", data, offset, value)
    build = build or (profiles.TARGET_BUILD if version == 5 else "01.00.00.0564")
    for offset, text in zip(offsets[4:6], (name, build)):
        encoded = text.encode("ascii")
        data[offset:offset + 32] = encoded + bytes(32 - len(encoded))
    struct.pack_into("<H", data, offsets[6], scenario_type)
    return data


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "source"
        self.input.mkdir()
        self.output = self.root / "package"
        self.addCleanup(patch.stopall)
        patch.object(pipeline, "ROOT", self.root).start()

    def source(self, name="arena", version=5, filename=None, **kwargs):
        path = self.input / (filename or name + ".map")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cache_bytes(version, name, **kwargs))
        return path

    def convert(self, **kwargs):
        return pipeline.convert_directory(self.input, self.output, **kwargs)

    def compiler(self, source, header, workspace, profile, binary, manifest, stock, resources):
        workspace.mkdir(parents=True)
        output = workspace / (profile["output_id"] + ".map")
        output.write_bytes(cache_bytes(5, profile["output_id"]))
        return {"output": output, "steps": [{"operation": "compile"}],
                "repairs": [{"tag": "test.model", "operation": "model_layout"}],
                "omissions": [{"tag": "unused.bitmap", "reason": "unreachable"}],
                "toolchain": {"commands": [{"stage": "compile", "stdout": "WARNING: Example warning", "stderr": ""}]},
                "provenance": {"dependency_policy": profile["dependency_policy"]}}

    def authoring(self, **kwargs):
        return self.convert(invader_bin=self.root / "fake-tools", invader_manifest=self.root / "fake-manifest.json",
                            backend=self.compiler, **kwargs)

    def test_native_v5_is_packaged_unchanged_with_distinct_metadata_identity(self):
        source = self.source()
        original = source.read_bytes()
        result = self.convert()
        self.assertEqual(result["counts"], {"converted": 1})
        self.assertEqual((self.output / "maps/arena.map").read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        metadata = json.loads((self.output / "metadata/arena.json").read_text())
        expected = hashlib.sha256(original).hexdigest()
        self.assertEqual(metadata["cache"]["sha256"], expected)
        self.assertEqual(metadata["source"]["sha256"], expected)
        self.assertIsNone(metadata["creator_username"])
        self.assertIsNone(metadata["map_version"])
        self.assertEqual(metadata["gameplay_validation"], "pending")
        record = result["maps"][0]
        self.assertNotEqual(record["outputs"]["metadata"]["sha256"], expected)
        self.assertTrue((self.output / record["report_files"]["markdown"]).is_file())

    def test_inspection_routes_all_formats_and_resources_without_running_backend(self):
        for version in (5, 6, 7, 609, 13):
            self.source("test_" + str(version), version)
        resource = self.input / "bitmaps.map"
        resource.write_bytes(struct.pack("<4I", 1, 16, 16, 0))
        backend = Mock(side_effect=AssertionError("inventory must not compile"))
        result = self.convert(inspect_only=True, backend=backend)
        self.assertEqual(result["counts"], {"inventoried": 5, "resource": 1})
        self.assertEqual({r["source"]["version"] for r in result["maps"] if r["status"] == "inventoried"}, {5, 6, 7, 609, 13})
        self.assertFalse((self.output / "maps").exists())
        backend.assert_not_called()

    def test_native_v5_original_weapon_policy_rebuilds_instead_of_copying(self):
        self.source()
        profile = profiles.load_profile()
        profile.pop("sha256")
        profile["weapon_policy"] = "bungie-originals"
        path = self.root / "original-weapons.json"
        path.write_text(json.dumps(profile))
        compiler = Mock(side_effect=self.compiler)
        result = self.convert(profile_selection=path, invader_bin=self.root,
                              invader_manifest=self.root / "manifest", backend=compiler)
        self.assertEqual(result["counts"], {"converted": 1})
        compiler.assert_called_once()
        self.assertEqual(compiler.call_args.args[3]["weapon_policy"], "bungie-originals")
        record = result["maps"][0]
        self.assertEqual(record["conversion"]["steps"], [{"operation": "compile"}])

    def test_native_v5_native_presentation_rebuilds_even_with_preserved_weapons_and_codecs(self):
        source = self.source()
        original = source.read_bytes()
        profile = profiles.load_profile()
        profile.pop("sha256")
        profile["presentation_policy"] = "native-xbox"
        path = self.root / "native-presentation.json"
        path.write_text(json.dumps(profile))
        compiler = Mock(side_effect=self.compiler)
        result = self.convert(profile_selection=path, invader_bin=self.root,
                              invader_manifest=self.root / "manifest", backend=compiler)
        self.assertEqual(result["counts"], {"converted": 1})
        compiler.assert_called_once()
        self.assertEqual(compiler.call_args.args[3]["presentation_policy"], "native-xbox")
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(result["maps"][0]["conversion"]["steps"], [{"operation": "compile"}])

    def test_native_v5_authored_weapon_placements_rebuild_with_the_explicit_policy(self):
        source = self.source()
        original = source.read_bytes()
        profile = profiles.load_profile()
        profile.pop("sha256")
        profile.update(weapon_policy="bungie-originals", presentation_policy="native-xbox",
                       weapon_placement_policy="authored-default")
        path = self.root / "authored-placements.json"
        path.write_text(json.dumps(profile))
        compiler = Mock(side_effect=self.compiler)
        result = self.convert(profile_selection=path, invader_bin=self.root,
                              invader_manifest=self.root / "manifest", backend=compiler)
        self.assertEqual(result["counts"], {"converted": 1})
        compiler.assert_called_once()
        self.assertEqual(compiler.call_args.args[3]["weapon_placement_policy"], "authored-default")
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(result["maps"][0]["conversion"]["steps"], [{"operation": "compile"}])

    def test_malformed_inputs_and_symlinks_do_not_stop_valid_siblings(self):
        good = self.source()
        (self.input / "broken.map").write_bytes(b"broken")
        (self.input / "linked.map").symlink_to(good)
        result = self.convert()
        self.assertEqual(result["counts"], {"converted": 1, "unsupported": 2})
        self.assertEqual(len(list((self.output / "reports").glob("*.json"))), 3)
        self.assertTrue((self.output / "maps/arena.map").exists())

    def test_recursive_link_directory_gets_report_without_being_followed(self):
        self.source()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "hidden.map").write_bytes(cache_bytes(5, "hidden"))
        (self.input / "alias").symlink_to(outside, target_is_directory=True)
        result = self.convert(recursive=True)
        self.assertEqual(result["counts"], {"converted": 1, "unsupported": 1})
        self.assertFalse((self.output / "maps/hidden.map").exists())

    def test_identical_copies_reject_both_and_have_independent_reports(self):
        self.source()
        self.source(filename="copy.map")
        result = self.convert()
        self.assertEqual(result["counts"], {"failed": 2})
        self.assertEqual(len(list((self.output / "reports").glob("*.json"))), 2)
        self.assertEqual(len({r["report_files"]["json"] for r in result["maps"]}), 2)
        self.assertFalse((self.output / "maps").exists())
        self.assertTrue(all(r["diagnostics"][0]["code"] == "duplicate_map_identity" for r in result["maps"]))

    def test_missing_tools_needs_profile_while_native_map_still_packages(self):
        self.source()
        self.source("mcc_map", 13)
        result = self.convert()
        self.assertEqual(result["counts"], {"converted": 1, "needs_profile": 1})
        blocked = next(r for r in result["maps"] if r["id"] == "mcc_map")
        self.assertEqual(blocked["diagnostics"][0]["code"], "toolchain_required")

    def test_supported_foreign_formats_use_adapter_and_preserve_sources(self):
        originals = {}
        for version in (6, 7, 609, 13):
            path = self.source("map_" + str(version), version)
            originals[path] = path.read_bytes()
        result = self.authoring()
        self.assertEqual(result["counts"], {"converted": 4})
        for record in result["maps"]:
            self.assertEqual(record["repairs"][0]["tag"], "test.model")
            self.assertEqual(record["omissions"][0]["tag"], "unused.bitmap")
            self.assertIn("tool_warning", {d["code"] for d in record["diagnostics"]})
        self.assertTrue(all(path.read_bytes() == value for path, value in originals.items()))

    def test_partial_original_completion_reports_builder_fields_without_claiming_validation(self):
        self.source(version=13)
        def compiler(*args):
            result = self.compiler(*args)
            result["steps"].append({"operation": "canonical_weapons", "authored_original_completions": {
                "weapons/gravity rifle/gravity rifle.weapon": {
                    "stock_weapon": "weapons/gravity rifle/gravity rifle.weapon",
                    "remaining_missing_fields": ["hud_interface"],
                    "diagnostic": "Original completion retained; remaining player-interface gaps require review",
                }}})
            return result
        result = self.convert(invader_bin=self.root, invader_manifest=self.root / "manifest", backend=compiler)
        record = result["maps"][0]
        warning = next(d for d in record["diagnostics"] if d["code"] == "original_completion_incomplete")
        self.assertEqual(record["status"], "converted")
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["value"]["remaining_missing_fields"], ["hud_interface"])
        self.assertEqual(record["gameplay_validation"], "pending")

    def test_community_exception_report_is_distinct_from_original_completion(self):
        self.source(version=13)
        approval = {"kind": "user-decision", "date": "2026-10-08",
                    "reference": "thread://01a116b1-1414-7ea2-ad25-7cdf34ebce54",
                    "statement": "Retain this reviewed community revolver as an explicit exception"}
        community = "weapons/magnum/magnum.weapon"
        original = "weapons/gravity rifle/gravity rifle.weapon"
        def compiler(*args):
            result = self.compiler(*args)
            result["steps"].append({"operation": "canonical_weapons",
                "authored_original_completions": {original: {
                    "stock_weapon": original, "remaining_missing_fields": [],
                    "diagnostic": "Original completion retained; behavior validation is pending"}},
                "authored_community_exceptions": {community: {
                    "classification": "approved_community_weapon",
                    "reviewed_lineage": {"outcome": "approved-community", "ancestor": None,
                                         "approval": approval}}}})
            return result
        result = self.convert(invader_bin=self.root, invader_manifest=self.root / "manifest", backend=compiler)
        record = result["maps"][0]
        self.assertEqual(record["status"], "converted")
        retained = next(item for item in record["diagnostics"] if item["code"] == "approved_community_weapon_retained")
        self.assertEqual((retained["tag"], retained["tag_type"], retained["severity"]), (community, "weapon", "info"))
        self.assertEqual(retained["value"], {"outcome": "approved-community", "approval": approval,
                                            "gameplay_validation": "pending"})
        self.assertIn("no original Halo 1 ancestry is claimed", retained["message"])
        originals = [item for item in record["diagnostics"] if item["code"] == "original_completion_retained"]
        self.assertEqual([item["tag"] for item in originals], [original])
        report = json.loads((self.output / record["report_files"]["json"]).read_text())
        published = next(item for item in report["diagnostics"] if item["code"] == retained["code"])
        self.assertEqual(published["value"]["approval"], approval)
        rendered = (self.output / record["report_files"]["markdown"]).read_text()
        self.assertIn("approved_community_weapon_retained", rendered)
        self.assertIn("no original Halo 1 ancestry is claimed", rendered)
        metadata = json.loads((self.output / record["outputs"]["metadata"]["file"]).read_text())
        self.assertEqual(metadata["gameplay_validation"], "pending")

    def test_source_hash_recipe_is_passed_to_adapter_independent_of_scenario_name(self):
        source = self.source("cache_header_name", 13)
        value = profiles.load_profile()
        value.pop("sha256")
        spec = {"id": "reviewed_alias", "scenario": "levels/other_scenario", "source_sha256": pipeline.sha256(source)}
        value["maps"] = [spec]
        path = self.root / "profile.json"
        path.write_text(json.dumps(value))
        def backend(*args):
            self.assertEqual(args[3]["selected_map"], spec)
            self.assertEqual(args[3]["output_id"], "reviewed_alias")
            return self.compiler(*args)
        result = self.convert(profile_selection=path, invader_bin=self.root, invader_manifest=self.root / "manifest", backend=backend)
        self.assertEqual(result["counts"], {"converted": 1})
        self.assertTrue((self.output / "maps/reviewed_alias.map").is_file())

    def test_tool_failure_has_tag_and_fix_and_keeps_successful_sibling(self):
        self.source()
        self.source("broken_scripts", 7)
        def rejected(*args):
            raise ConversionError("needs_profile", "compile", "Compiler rejected required content",
                                  {"output": 'ERROR: Failed to find weapons/custom.weapon\n...in levels/arena.scenario',
                                   "workspace": "/Users/private/build/map-work", "script_source": "SECRET ASSET TEXT"})
        result = self.convert(invader_bin=self.root, invader_manifest=self.root, backend=rejected)
        self.assertEqual(result["counts"], {"converted": 1, "needs_profile": 1})
        record = next(r for r in result["maps"] if r["id"] == "broken_scripts")
        missing = next(d for d in record["diagnostics"] if d["code"] == "missing_tag")
        self.assertEqual(missing["tag"], "levels/arena.scenario")
        self.assertIn("reviewed", missing["suggested_fix"])
        text = (self.output / record["report_files"]["json"]).read_text()
        self.assertNotIn("/Users/private", text)
        self.assertNotIn("SECRET ASSET TEXT", text)
        self.assertFalse((self.output / "maps/broken_scripts.map").exists())

    def test_source_mutation_cannot_leave_playable_output(self):
        source = self.source(version=7)
        def mutating(*args):
            result = self.compiler(*args)
            source.write_bytes(source.read_bytes() + b"changed")
            return result
        result = self.convert(invader_bin=self.root, invader_manifest=self.root, backend=mutating)
        self.assertEqual(result["counts"], {"failed": 1})
        self.assertFalse((self.output / "maps/arena.map").exists())

    def test_known_backend_tag_context_is_in_shareable_builder_report(self):
        self.source(version=7)
        def rejected(*args):
            raise ConversionError("missing_dependency", "dependencies", "A required dependency is unresolved",
                                  {"tag": "weapons/author/custom.weapon", "field": "item_collection.item"})
        result = self.convert(invader_bin=self.root, invader_manifest=self.root, backend=rejected)
        record = result["maps"][0]
        self.assertEqual(record["diagnostics"][0]["tag"], "weapons/author/custom.weapon")
        report = (self.output / record["report_files"]["markdown"]).read_text()
        self.assertIn("weapons/author/custom.weapon", report)
        self.assertIn("item_collection.item", report)

    def test_wrong_output_build_identity_or_target_bound_is_rejected(self):
        self.source(version=7)
        for change in ({"name": "wrong_id"}, {"build": "PAL"}, {"version": 7}, {"scenario_type": 0}):
            with self.subTest(change=change):
                self.output = self.root / ("package_" + str(len(list(self.root.glob("package_*")))))
                def wrong(*args):
                    result = self.compiler(*args)
                    result["output"].write_bytes(cache_bytes(**{"version": 5, "name": "arena", **change}))
                    return result
                result = self.convert(invader_bin=self.root, invader_manifest=self.root, backend=wrong)
                self.assertEqual(result["counts"], {"failed": 1})
                self.assertFalse((self.output / "maps/arena.map").exists())

    def test_native_v5_identity_cannot_be_changed_by_filename_or_capitalization(self):
        self.source("arena", filename="renamed.map")
        self.source("UPPER")
        self.source("bloodgulch")
        result = self.convert()
        self.assertEqual(result["counts"], {"failed": 3})
        self.assertFalse((self.output / "maps").exists())

    def test_native_v5_does_not_bypass_requested_transformative_profile(self):
        self.source()
        value = profiles.load_profile()
        value.pop("sha256")
        value["script_policy"] = "none"
        path = self.root / "profile.json"
        path.write_text(json.dumps(value))
        result = self.convert(profile_selection=path)
        self.assertEqual(result["counts"], {"needs_profile": 1})
        self.assertEqual(result["maps"][0]["diagnostics"][0]["code"], "v5_recipe_requires_rebuild")

    def test_general_omission_routes_arbitrary_maps_including_v5_through_backend(self):
        for version in (5, 6, 7, 609, 13):
            self.source("unlisted_" + str(version), version)
        adapter = Mock(side_effect=self.compiler)
        result = self.convert(profile_selection="og-multiplayer-v5", invader_bin=self.root,
                              invader_manifest=self.root / "manifest", backend=adapter)
        self.assertEqual(result["counts"], {"converted": 5})
        self.assertEqual(adapter.call_count, 5)
        for call in adapter.call_args_list:
            self.assertEqual(call.args[3]["script_policy"], "omit")
            self.assertIsNone(call.args[3]["selected_map"])

    def test_completed_omission_is_reported_when_later_asset_fails(self):
        self.source(version=13)
        omission = {"kind": "script_omission", "status": "omitted", "counts_after": {"scripts": 0}}
        def rejected(*args):
            raise ConversionError("needs_profile", "compile", "Unsupported sound codec",
                                  {"omissions": [omission], "steps": [{"operation": "omit_scripts"}]})
        result = self.convert(invader_bin=self.root, invader_manifest=self.root, backend=rejected)
        record = result["maps"][0]
        self.assertEqual(record["omissions"], [omission])
        self.assertEqual(record["conversion"]["steps"][0]["operation"], "omit_scripts")
        self.assertEqual(record["outputs"], {})

    def test_campaign_is_explicitly_gated(self):
        self.source("campaign", scenario_type=0)
        backend = Mock()
        result = self.convert(backend=backend)
        self.assertEqual(result["counts"], {"needs_profile": 1})
        self.assertEqual(result["maps"][0]["diagnostics"][0]["code"], "scenario_type_needs_profile")
        backend.assert_not_called()

    def editorial(self, **changes):
        folder = self.root / "editorial"
        folder.mkdir(exist_ok=True)
        value = {"schema_version": 1, "display_name": "Test Arena", "creator_username": "author",
                 "map_version": "1.2", "description": "Watch your step. 2-4 players.",
                 "recommended_players": {"min": 2, "max": 4}, **changes}
        (folder / "arena.json").write_text(json.dumps(value))
        return folder

    def test_authored_metadata_and_checksum_bound_preview_are_packaged(self):
        self.source()
        image = b"\x89PNG\r\n\x1a\n" + b"synthetic image header; not rendered"
        preview = {"file": "photo.png", "sha256": hashlib.sha256(image).hexdigest(), "origin": "author"}
        folder = self.editorial(preview=preview)
        (folder / "photo.png").write_bytes(image)
        result = self.convert(metadata_dir=folder)
        self.assertEqual(result["counts"], {"converted": 1})
        metadata = json.loads((self.output / "metadata/arena.json").read_text())
        self.assertEqual(metadata["creator_username"], "author")
        self.assertEqual(metadata["map_version"], "1.2")
        self.assertEqual(metadata["recommended_players"], {"min": 2, "max": 4})
        self.assertEqual(metadata["preview"]["file"], "previews/arena.png")
        self.assertEqual((self.output / metadata["preview"]["file"]).read_bytes(), image)

    def test_metadata_failure_rolls_back_map_and_keeps_other_maps(self):
        self.source()
        self.source("other")
        folder = self.editorial(creator="misspelled")
        result = self.convert(metadata_dir=folder)
        self.assertEqual(result["counts"], {"converted": 1, "failed": 1})
        rejected = next(r for r in result["maps"] if r["id"] == "arena")
        self.assertEqual(rejected["diagnostics"][0]["code"], "invalid_metadata")
        self.assertEqual(rejected["diagnostics"][0]["stage"], "metadata")
        self.assertFalse((self.output / "maps/arena.map").exists())
        self.assertTrue((self.output / "maps/other.map").exists())

    def test_preview_wrong_hash_signature_or_link_cannot_leave_map(self):
        self.source()
        for reason in ("hash", "signature", "symlink"):
            with self.subTest(reason=reason):
                self.output = self.root / ("package_" + reason)
                image = b"\x89PNG\r\n\x1a\n" if reason != "signature" else b"not an image"
                value = hashlib.sha256(image).hexdigest() if reason != "hash" else "0" * 64
                folder = self.editorial(preview={"file": "photo.png", "sha256": value, "origin": "author"})
                path = folder / "photo.png"
                if path.exists() or path.is_symlink():
                    path.unlink()
                if reason == "symlink":
                    elsewhere = self.root / "photo.png"
                    elsewhere.write_bytes(image)
                    path.symlink_to(elsewhere)
                else:
                    path.write_bytes(image)
                result = self.convert(metadata_dir=folder)
                self.assertEqual(result["counts"], {"failed": 1})
                self.assertFalse((self.output / "maps/arena.map").exists())
                self.assertFalse((self.output / "metadata/arena.json").exists())

    def test_existing_output_empty_input_or_nested_destination_do_not_mutate_sources(self):
        with self.assertRaisesRegex(ValueError, "No .map"):
            self.convert()
        source = self.source()
        original = source.read_bytes()
        self.output.mkdir()
        (self.output / "prior").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual((self.output / "prior").read_bytes(), b"keep")
        with self.assertRaisesRegex(ValueError, "outside"):
            pipeline.convert_directory(self.input, self.input / "output")
        self.assertEqual(source.read_bytes(), original)

    def test_publication_race_refuses_existing_destination_and_removes_partial_stage(self):
        self.source()
        def race(staged, destination):
            destination.mkdir()
            (destination / "prior").write_bytes(b"keep")
            pipeline.publish_directory_original(staged, destination)
        with patch.object(pipeline, "publish_directory_original", pipeline.publish_directory, create=True), \
                patch.object(pipeline, "publish_directory", race):
            with self.assertRaises(OSError):
                self.convert()
        self.assertEqual((self.output / "prior").read_bytes(), b"keep")
        self.assertFalse(list(self.root.glob(".package-*.partial")))

    def test_cli_exit_codes_distinguish_partial_failure_and_inventory(self):
        self.source(version=7)
        with patch("builtins.print"):
            self.assertEqual(main([str(self.input), "--output", str(self.output)]), 1)
            self.assertEqual(main([str(self.input), "--inspect", "--output", str(self.root / "inventory")]), 0)
            with self.assertRaises(SystemExit) as error:
                main([str(self.input), "--output", str(self.output)])
            self.assertEqual(error.exception.code, 2)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.value = profiles.load_profile()
        self.value.pop("sha256")

    def test_canonical_profile_identity_is_order_independent_but_policy_sensitive(self):
        original = profiles.validate_profile(self.value)["sha256"]
        self.assertEqual(profiles.validate_profile(dict(reversed(list(self.value.items()))))["sha256"], original)
        self.value["script_policy"] = "none"
        self.assertNotEqual(profiles.validate_profile(self.value)["sha256"], original)

    def test_legacy_weapon_placements_default_to_engine_native_without_mutating_input(self):
        self.value.pop("weapon_placement_policy", None)
        before = copy.deepcopy(self.value)
        normalized = profiles.validate_profile(self.value)
        self.assertEqual(normalized["weapon_placement_policy"], "engine-native")
        self.assertEqual(self.value, before)
        explicit = {**self.value, "weapon_placement_policy": "engine-native"}
        self.assertEqual(profiles.validate_profile(explicit)["sha256"], normalized["sha256"])
        for name in ("authored-xbox-v5", "jukkis-pb3"):
            with self.subTest(profile=name):
                self.assertEqual(profiles.load_profile(name)["weapon_placement_policy"], "engine-native")

    def test_authored_weapon_placement_policy_is_explicit_and_binds_profile_identity(self):
        native = {**self.value, "weapon_policy": "bungie-originals", "presentation_policy": "native-xbox",
                  "weapon_placement_policy": "engine-native"}
        authored = {**native, "weapon_placement_policy": "authored-default"}
        normalized = profiles.validate_profile(authored)
        self.assertEqual(normalized["weapon_placement_policy"], "authored-default")
        self.assertNotEqual(normalized["sha256"], profiles.validate_profile(native)["sha256"])
        og = profiles.load_profile("og-multiplayer-v5")
        self.assertEqual(og["weapon_placement_policy"], "authored-default")
        self.assertEqual(og["version"], "1.12.0")
        for changes in ({"weapon_policy": "preserve"}, {"presentation_policy": "preserve"},
                        {"dependency_policy": "stock-first"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "Authored weapon placements"):
                profiles.validate_profile({**authored, **changes})
        for choice in ("preserve", "all", "flamethrower", None, True, [], {}):
            with self.subTest(choice=choice), self.assertRaisesRegex(ValueError, "Weapon placement policy"):
                profiles.validate_profile({**native, "weapon_placement_policy": choice})

    def test_profiles_reject_implicit_unbounded_or_unknown_decisions(self):
        cases = ({"schema_version": True}, {"supported_formats": [9]}, {"supported_formats": [7, 7]},
                 {"arbitrary_command": "run"}, {"script_policy": "delete"},
                 {"target": {**self.value["target"], "max_tag_bytes": 23 * 1024 * 1024}})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                profiles.validate_profile({**self.value, **changes})

    def test_reviewed_recipes_require_exact_hashes_safe_paths_and_supported_fields(self):
        base = {"id": "example", "scenario": "levels/example", "source_sha256": "a" * 64}
        for spec in ({"id": "example", "scenario": "levels/example"},
                     {**base, "scenario": "../example"}, {**base, "scenario": "levels//example"},
                     {**base, "scenario": "levels/example.scenario"}, {**base, "source_sha256": "bad"},
                     {**base, "ignored_tags": ["weapons/*"]}, {**base, "optional_scripts": ["delete_me"]}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                profiles.validate_profile({**self.value, "maps": [spec]})

    def test_pb3_recipe_fingerprint_binds_checked_in_source_decisions(self):
        profile = profiles.reviewed_pb3_profile()
        self.assertEqual(profile["dependency_policy"], "stock-first")
        self.assertTrue(profile["maps"])
        changed = copy.deepcopy(profile)
        changed.pop("sha256")
        changed["maps"][0]["scenario_sha256"] = "0" * 64
        self.assertNotEqual(profiles.validate_profile(changed)["sha256"], profile["sha256"])

    def test_general_omission_needs_a_policy_reason_but_no_map_whitelist(self):
        profile = profiles.load_profile("og-multiplayer-v5")
        self.assertEqual(profile["maps"], [])
        self.assertEqual(profile["script_policy"], "omit")
        value = {**self.value, "script_policy": "omit"}
        with self.assertRaisesRegex(ValueError, "reason"):
            profiles.validate_profile(value)
        value["script_omission_reason"] = "Use engine-native multiplayer rules."
        self.assertEqual(profiles.validate_profile(value)["maps"], [])


if __name__ == "__main__":
    unittest.main()
