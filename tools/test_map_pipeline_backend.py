"""Offline pipeline boundaries with controlled authoring helpers, no game runs."""
import json
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from tools.map_pipeline import backend
except ModuleNotFoundError:
    from map_pipeline import backend


def cache(path, version=5, name="sample", declared=4096, tags=256, offset=2048):
    data = bytearray(4096)
    data[:4], data[2044:2048] = b"daeh", b"toof"
    struct.pack_into("<I", data, 4, version)
    struct.pack_into("<I", data, 8, declared)
    struct.pack_into("<I", data, 16, offset)
    struct.pack_into("<I", data, 20, tags)
    data[32:32 + len(name)] = name.encode()
    data[64:64 + len(backend.legacy.NTSC_BUILD)] = backend.legacy.NTSC_BUILD.encode()
    struct.pack_into("<H", data, 96, 1)
    path.write_bytes(data)


class FakeInvader:
    scripts = 2
    fail_build = False
    bad_output = False
    calls = []
    retain_omitted_scripts = False
    child_scenarios = 0

    def __init__(self, binary, manifest, logs):
        self.binary, self.logs = Path(binary), logs
        self.stage, self.commit, self.provenance, self.commands = "toolchain", "reviewed", {}, []
        self.tool_paths = {}
        self.source_patches = json.loads(manifest.read_text()).get("source_patches", [])
        self.cleared_scripts = set()

    def run(self, tool, *args):
        args = list(map(str, args))
        self.calls.append((tool, args))
        record = {"stage": self.stage, "tool": tool, "command": [tool, *args],
                  "stdout": "", "stderr": "", "exit_code": 0}
        self.commands.append(record)
        if tool == "extract":
            tags = Path(args[args.index("-t") + 1])
            scenario = tags / ("levels/sample/" + Path(args[-1]).stem + ".scenario")
            scenario.parent.mkdir(parents=True, exist_ok=True)
            scenario.write_bytes(b"embedded recovered MCC HSC; unchanged authored scenario")
            (tags / "reachable.bitmap").write_bytes(b"authored art")
            (tags / "unused.bitmap").write_bytes(b"unreachable art")
        if tool == "edit" and "-C" in args:
            field = args[args.index("-C") + 1]
            tags = Path(args[args.index("-t") + 1])
            if tags / args[-1] in self.cleared_scripts:
                return "0"
            return str({"scripts": self.scripts, "globals": int(self.scripts > 0), "source_files": int(self.scripts > 0),
                        "child_scenarios": self.child_scenarios, "references": 0,
                        "netgame_equipment": 0, "starting_equipment": 0, "weapons": 0, "weapon_palette": 0, "weapon_list": 0}[field])
        if tool == "edit" and "-E" in args and not self.retain_omitted_scripts:
            tags = Path(args[args.index("-t") + 1])
            scenario = tags / args[-1]
            scenario.write_bytes(b"reviewed working scenario with no scripts, globals, or source files")
            self.cleared_scripts.add(scenario)
        if tool == "build":
            if self.fail_build:
                record.update(exit_code=1, stderr="MCC function game_is_authoritative is unsupported on Xbox")
                raise backend.ConversionError("needs_profile", "compile", "Rejected MCC API", record)
            maps = Path(args[args.index("-m") + 1])
            name = Path(args[-1]).name
            cache(maps / (name + ".map"), name=name,
                  declared=backend.legacy.MAX_CACHE_BYTES + 1 if self.bad_output else 4096)
        if tool == "dependency":
            return "reachable.bitmap"
        return ""

    def count(self, tags, tag, field):
        return int(self.run("edit", "-t", tags, "-C", field, tag))

    def get(self, tags, tag, field):
        return self.run("edit", "-t", tags, "-G", field, tag)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "sample.map"
        self.source.write_bytes(b"immutable MCC source")
        self.manifest = self.root / "source-manifest.json"
        self.manifest.write_text(json.dumps({"source_patches": [{"sha256": backend.STARTING_PROFILE_PATCH_SHA256}]}))
        self.header = {"name": "sample", "version": 13, "sha256": backend.legacy.digest(self.source)}
        self.profile = {"id": "preserve", "version": 1, "schema_version": 1,
                        "supported_formats": [5, 6, 7, 609, 13], "dependency_policy": "authored-first",
                        "script_policy": "preserve", "maps": [],
                        "target": {"engine": "xbox-ntsc", "build": backend.legacy.NTSC_BUILD,
                                   "max_cache_bytes": backend.legacy.MAX_CACHE_BYTES,
                                   "max_tag_bytes": backend.legacy.TAG_ARENA_BYTES}}
        FakeInvader.calls = []
        FakeInvader.scripts = 2
        FakeInvader.fail_build = False
        FakeInvader.bad_output = False
        FakeInvader.retain_omitted_scripts = False
        FakeInvader.child_scenarios = 0
        self.fake = patch.object(backend, "ApprovedInvader", FakeInvader)
        self.fake.start()

    def tearDown(self):
        self.fake.stop()
        self.temp.cleanup()

    def test_native_presentation_requires_stock_for_digits_on_every_source_version(self):
        self.profile["presentation_policy"] = "native-xbox"
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual(caught.exception.stage, "presentation")
        self.assertIn("canonical Xbox stock", caught.exception.message)
        self.assertEqual(FakeInvader.calls, [])
        self.header["version"] = 5
        with patch("tools.map_pipeline.presentation.canonical_shell_overlay") as shell:
            with self.assertRaises(backend.ConversionError) as caught:
                self.convert()
        shell.assert_not_called()
        self.assertEqual(caught.exception.stage, "presentation")
        self.assertEqual(FakeInvader.calls, [])

    def test_native_digits_stage_runs_for_non_mcc_without_mcc_geometry_or_asset_helpers(self):
        stock_maps = self.root / "stock-maps"
        stock_maps.mkdir()
        for name in ("bloodgulch", "a10", "ui"):
            (stock_maps / (name + ".map")).write_bytes(b"canonical input")
        alias = "__native_hud/stock/1234567890abcdef/ui/hud/counter.hud_number"
        atlas = "__native_hud/stock/1234567890abcdef/ui/hud/bitmaps/combined/hud_counter_numbers.bitmap"
        self.profile.update(presentation_policy="native-xbox")

        def stock_extract(tool, inputs, output, **kwargs):
            output.mkdir()
            (output / "globals").mkdir()
            (output / "globals/globals.globals").write_bytes(b"canonical stock interface provider")
            return {"inputs": {}, "compatibility_patches": []}

        def digits(tool, stock, roots, workspace, steps, repairs, protected):
            self.assertFalse((roots[0] / alias).exists())
            overlay = workspace / "digits/tags"
            for name in ("globals/globals.globals", alias, atlas):
                path = overlay / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"controlled native provider")
            steps.append({"operation": "canonical_hud_digits", "native_hud_tags": [alias]})
            return overlay

        class ProviderInvader(FakeInvader):
            def run(self, tool, *args):
                result = super().run(tool, *args)
                if tool == "dependency" and args[-1] == "globals/globals.globals":
                    return "\n".join([alias, atlas])
                return result

        with patch.object(backend, "ApprovedInvader", ProviderInvader), \
                patch.object(backend, "_extract_stock", side_effect=stock_extract), \
                patch("tools.map_pipeline.hud_digits.canonical_hud_digits_overlay", side_effect=digits) as select, \
                patch("tools.map_pipeline.presentation.canonical_shell_overlay") as shell, \
                patch("tools.map_pipeline.hud.normalize_mcc_hud") as mcc, \
                patch("tools.map_pipeline.assets.AssetTools") as assets:
            for version in (5, 6, 7, 609):
                with self.subTest(version=version):
                    self.header["version"] = version
                    result = self.convert(stock_maps=stock_maps)
                    self.assertEqual(result["header"]["version"], 5)
                    self.assertIn(alias, result["provenance"]["reachable_tags"])
                    self.assertIn(atlas, result["provenance"]["reachable_tags"])
                    stages = [step["operation"] for step in result["steps"]]
                    self.assertLess(stages.index("canonical_hud_digits"), stages.index("asset_dependencies"))
                    import shutil
                    shutil.rmtree(self.root / "workspace")
        self.assertEqual(select.call_count, 4)
        shell.assert_not_called()
        mcc.assert_not_called()
        assets.assert_not_called()

    def test_preserve_presentation_does_not_select_native_digits(self):
        with patch("tools.map_pipeline.hud_digits.canonical_hud_digits_overlay") as select:
            self.convert()
        select.assert_not_called()

    def test_native_digits_follow_weapon_registry_stage_and_union_mcc_native_markers(self):
        stock_maps = self.root / "stock-maps"
        stock_maps.mkdir()
        for name in ("bloodgulch", "a10", "ui"):
            (stock_maps / (name + ".map")).write_bytes(b"canonical input")
        asset_manifest = self.root / "asset-tools.json"
        asset_manifest.write_text("{}")
        helper_paths = {}
        for kind in ("hud", "mips"):
            helper_paths[kind] = self.root / ("convert-" + kind)
            helper_paths[kind].write_bytes(b"controlled helper")
        self.profile.update(presentation_policy="native-xbox", weapon_policy="bungie-originals",
                            asset_manifest=str(asset_manifest))
        weapon_hud = "__native_weapons/og/1234567890abcdef/weapons/original.weapon_hud_interface"
        weapon_counter = "__native_weapons/og/1234567890abcdef/ui/hud/weapon_counter.hud_number"
        digits_hud = "__native_hud/stock/1234567890abcdef/ui/hud/counter.hud_number"
        order = []

        def write_overlay(workspace, name, tags):
            overlay = workspace / name / "tags"
            for tag in tags:
                path = overlay / tag
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"controlled native field payload")
            return overlay

        def stock_extract(tool, inputs, output, **kwargs):
            output.mkdir()
            (output / "globals").mkdir()
            (output / "globals/globals.globals").write_bytes(b"canonical stock interface provider")
            return {"inputs": {}, "compatibility_patches": []}

        def shell(tool, stock, roots, workspace, steps, repairs, protected):
            order.append("shell")
            return write_overlay(workspace, "shell", ["ui/ui_tags_loaded_multiplayer_scenario_type.tag_collection"])

        def weapons(tool, stock, roots, required, scenario, workspace, steps, repairs, protected):
            order.append("weapons")
            overlay = write_overlay(workspace, "weapons", [weapon_hud, weapon_counter, "globals/globals.globals"])
            (overlay / "globals/globals.globals").write_bytes(b"canonical registry retained")
            steps.append({"operation": "canonical_weapons", "native_hud_tags": [weapon_hud, weapon_counter]})
            return overlay

        def digits(tool, stock, roots, workspace, steps, repairs, protected):
            order.append("digits")
            self.assertEqual((roots[0] / "globals/globals.globals").read_bytes(), b"canonical registry retained")
            overlay = write_overlay(workspace, "digits", [digits_hud, "globals/globals.globals"])
            steps.append({"operation": "canonical_hud_digits", "native_hud_tags": [digits_hud]})
            return overlay

        def normalize(*args, native_tags):
            order.append("geometry")
            self.assertEqual(native_tags, {weapon_hud, weapon_counter, digits_hud})
            self.assertIn(digits_hud, args[4])
            return None

        class NativeInvader(FakeInvader):
            def run(self, tool, *args):
                result = super().run(tool, *args)
                if tool == "dependency" and args[-1] == "globals/globals.globals":
                    root_args = [Path(args[i + 1]) for i, value in enumerate(args) if value == "-t"]
                    return "\n".join(name for name in (weapon_hud, weapon_counter, digits_hud)
                                     if any((root / name).is_file() for root in root_args))
                return result

        class NativeAssets:
            def __init__(self, manifest, logs, commands):
                self.manifest, self.manifest_hash = manifest, backend.legacy.digest(manifest)

            def provenance(self):
                return {"binaries": {kind: {"sha256": backend.legacy.digest(path)} for kind, path in helper_paths.items()}}

            def binary(self, kind):
                return helper_paths[kind]

        with patch.object(backend, "ApprovedInvader", NativeInvader), \
                patch.object(backend, "_extract_stock", side_effect=stock_extract), \
                patch("tools.map_pipeline.assets.AssetTools", NativeAssets), \
                patch("tools.map_pipeline.presentation.canonical_shell_overlay", side_effect=shell), \
                patch("tools.map_pipeline.stock_weapons.canonical_weapon_overlay", side_effect=weapons), \
                patch("tools.map_pipeline.hud_digits.canonical_hud_digits_overlay", side_effect=digits), \
                patch("tools.map_pipeline.hud_anchors.normalize_weapon_hud_anchors", return_value=None) as anchors, \
                patch("tools.map_pipeline.hud.normalize_mcc_hud", side_effect=normalize):
            result = self.convert(stock_maps=stock_maps)
        self.assertEqual(order, ["shell", "weapons", "digits", "geometry"])
        self.assertEqual(anchors.call_args.kwargs["native_tags"], {weapon_hud, weapon_counter, digits_hud})
        self.assertIn(digits_hud, result["provenance"]["reachable_tags"])

    def convert(self, **kwargs):
        return backend.convert_cache(self.source, self.header, self.root / "workspace", self.profile,
                                     self.root / "bin", self.manifest, kwargs.pop("stock_maps", None), **kwargs)

    def omission_profile(self):
        source = b"embedded recovered MCC HSC; unchanged authored scenario"
        reason = "Native Xbox rules replace the source engine's map script workarounds"
        self.profile.update(script_policy="omit", maps=[], script_omission_reason=reason, output_id="community_sample")
        return {"source_sha256": self.header["sha256"], "scenario_sha256": hashlib.sha256(source).hexdigest(),
                "script_omission_reason": reason}

    def test_omission_clears_only_working_compiled_scenario_and_records_evidence(self):
        spec = self.omission_profile()
        self.manifest.write_text("{}")
        result = self.convert()
        omission = next(item for item in result["omissions"] if item["kind"] == "script_omission")
        self.assertEqual(omission["counts_before"], {"scripts": 2, "globals": 1, "source_files": 1})
        self.assertEqual(omission["counts_after"], {"scripts": 0, "globals": 0, "source_files": 0})
        self.assertEqual(omission["status"], "omitted")
        self.assertEqual(omission["reason"], spec["script_omission_reason"])
        self.assertEqual(omission["source_sha256"], spec["source_sha256"])
        self.assertEqual(omission["original_scenario_sha256"], spec["scenario_sha256"])
        self.assertEqual(self.profile["maps"], [])
        self.assertNotEqual(omission["sha256_before"], omission["sha256_after"])
        for root in ("source-tags", "tags"):
            original = self.root / "workspace" / root / "levels/sample/sample.scenario"
            self.assertEqual(backend.legacy.digest(original), spec["scenario_sha256"])
        edits = [args for tool, args in FakeInvader.calls if tool == "edit" and "-E" in args]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0][-1], "levels/sample/community_sample.scenario")
        self.assertEqual([edits[0][i + 1] for i, value in enumerate(edits[0]) if value == "-E"],
                         ["scripts[*]", "globals[*]", "source_files[*]", "references[*]"])
        self.assertEqual(self.source.read_bytes(), b"immutable MCC source")

    def test_omission_requires_explicit_reason(self):
        for reason in (None, "", "  ", 1):
            with self.subTest(reason=reason):
                self.omission_profile()
                self.profile["script_omission_reason"] = reason
                with self.assertRaises(backend.ConversionError) as caught:
                    self.convert()
                self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
                self.assertEqual(FakeInvader.calls, [])

    def test_omission_still_honors_independently_selected_scenario_hash(self):
        spec = self.omission_profile()
        spec.update(id="community_sample", scenario="levels/sample/sample", scenario_sha256="a" * 64)
        self.profile.update(maps=[spec], selected_map=spec)
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "profile"))
        self.assertFalse(any(tool == "edit" and "-E" in args for tool, args in FakeInvader.calls))

    def test_omission_must_verify_empty_fields(self):
        self.omission_profile()
        FakeInvader.retain_omitted_scripts = True
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertEqual(caught.exception.details["omissions"][0]["status"], "verification_failed")
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_omission_rejects_child_scenarios_before_editing(self):
        self.omission_profile()
        FakeInvader.child_scenarios = 1
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertEqual(caught.exception.details["child_scenarios"], 1)
        self.assertFalse(any(tool == "edit" and "-E" in args for tool, args in FakeInvader.calls))
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_omission_supports_existing_v5_without_whitelist(self):
        self.omission_profile()
        self.header["version"] = 5
        result = self.convert()
        self.assertEqual(result["header"]["version"], 5)
        self.assertEqual(result["omissions"][0]["policy"], "omit")

    def test_later_compile_failure_retains_serializable_omission_evidence(self):
        self.omission_profile()
        FakeInvader.fail_build = True
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        error = caught.exception
        self.assertEqual((error.code, error.stage), ("needs_profile", "compile"))
        self.assertEqual(error.details["omissions"][0]["status"], "omitted")
        self.assertEqual(error.details["omissions"][0]["counts_after"]["source_files"], 0)
        self.assertTrue(any(step["operation"] == "omit_scripts" for step in error.details["steps"]))
        self.assertIn("game_is_authoritative", json.dumps(error.details))

    def test_omission_rejects_scenario_shadowing_overlay(self):
        self.omission_profile()
        overlay = self.root / "overlay"
        scenario = overlay / "tags/levels/sample/community_sample.scenario"
        scenario.parent.mkdir(parents=True)
        scenario.write_bytes(b"scenario overlay could reintroduce scripts")
        self.profile["overlays"] = [str(overlay)]
        with patch.object(backend, "_checked_overlays", return_value=[overlay / "tags"]):
            with self.assertRaises(backend.ConversionError) as caught:
                self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "overlays"))
        self.assertEqual(caught.exception.details["omissions"][0]["status"], "omitted")
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_preserve_recompiles_embedded_hsc_and_tracks_reachable_tags(self):
        source = self.source.read_bytes()
        result = self.convert()
        build = next(args for tool, args in FakeInvader.calls if tool == "build")
        self.assertEqual(build[build.index("-S") + 1], "tags")
        self.assertFalse(any(tool == "edit" and "-E" in args for tool, args in FakeInvader.calls))
        self.assertEqual(result["header"]["version"], 5)
        self.assertEqual(self.source.read_bytes(), source)
        self.assertEqual(result["provenance"]["unused_extracted_tags"], ["unused.bitmap"])
        self.assertEqual(result["provenance"]["reachable_tags"]["reachable.bitmap"]["origin"], "authored-or-converted")
        script_step = next(step for step in result["steps"] if step["operation"] == "scripts")
        self.assertEqual(script_step["counts"]["scripts"], 2)
        self.assertEqual(script_step["removed"], [])

    def test_resource_directory_is_explicit_and_hashed(self):
        resources = self.root / "resources"
        resources.mkdir()
        (resources / "sounds.map").write_bytes(b"correct sound resource")
        result = self.convert(resources=resources)
        extract = next(args for tool, args in FakeInvader.calls if tool == "extract")
        self.assertEqual(extract[extract.index("-m") + 1], str(resources.resolve()))
        step = next(step for step in result["steps"] if step["operation"] == "extract")
        self.assertEqual(step["resources"]["sha256"]["sounds.map"], backend.legacy.digest(resources / "sounds.map"))

    def test_none_does_not_silently_discard_scripted_content(self):
        self.profile["script_policy"] = "none"
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))
        self.assertEqual(self.source.read_bytes(), b"immutable MCC source")

    def test_none_accepts_actually_unscripted_map(self):
        self.profile["script_policy"] = "none"
        FakeInvader.scripts = 0
        self.assertEqual(self.convert()["header"]["version"], 5)

    def test_scripted_conversion_requires_reviewed_compiler_patch(self):
        self.manifest.write_text("{}")
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertEqual(caught.exception.details["required_source_patch_sha256"], backend.STARTING_PROFILE_PATCH_SHA256)
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))
        self.assertEqual(self.source.read_bytes(), b"immutable MCC source")

    def test_unscripted_conversion_does_not_require_compiler_patch(self):
        self.manifest.write_text("{}")
        FakeInvader.scripts = 0
        self.assertEqual(self.convert()["header"]["version"], 5)

    def test_source_only_hsc_requires_reviewed_compiler_patch(self):
        self.manifest.write_text("{}")

        def count(tool, tags, tag, field):
            return int(field == "source_files")

        with patch.object(FakeInvader, "count", count):
            with self.assertRaises(backend.ConversionError) as caught:
                self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertEqual(caught.exception.details["counts"], {"scripts": 0, "globals": 0, "source_files": 1})
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_none_rejects_source_only_hsc(self):
        self.profile["script_policy"] = "none"

        def count(tool, tags, tag, field):
            return int(field == "source_files")

        with patch.object(FakeInvader, "count", count):
            with self.assertRaises(backend.ConversionError) as caught:
                self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertIn("exact reviewed behavior recipe", caught.exception.message)
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_source_only_hsc_compiles_with_reviewed_patch(self):
        def count(tool, tags, tag, field):
            return int(field == "source_files")

        with patch.object(FakeInvader, "count", count):
            result = self.convert()
        build = next(args for tool, args in FakeInvader.calls if tool == "build")
        self.assertEqual(build[build.index("-S") + 1], "tags")
        self.assertEqual(result["header"]["version"], 5)

    def test_scenario_overlay_cannot_bypass_compiler_patch_gate(self):
        self.manifest.write_text("{}")
        FakeInvader.scripts = 0
        overlay = self.root / "reviewed-overlay"
        tags = overlay / "tags"
        scenario = tags / "levels/sample/sample.scenario"
        scenario.parent.mkdir(parents=True)
        scenario.write_bytes(b"reviewed scenario with HSC")
        (overlay / "conversion.json").write_text(json.dumps({"operation": "hud-overlay", "changes": []}))
        self.profile["overlays"] = [str(overlay)]
        original_count = FakeInvader.count

        def count(tool, root, tag, field):
            return 2 if root == tags else original_count(tool, root, tag, field)

        # This test isolates the effective-scenario policy gate; manifest and
        # snapshot validation are tested separately by the overlay helpers.
        with patch.object(backend, "_checked_overlays", return_value=[tags]), patch.object(FakeInvader, "count", count):
            with self.assertRaises(backend.ConversionError) as caught:
                self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "scripts"))
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_compiler_rejection_is_structured_and_does_not_modify_source(self):
        FakeInvader.fail_build = True
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        error = caught.exception
        self.assertEqual((error.code, error.stage), ("needs_profile", "compile"))
        self.assertIn("game_is_authoritative", error.details["stderr"])
        self.assertTrue(error.details["commands"])
        self.assertEqual(self.source.read_bytes(), b"immutable MCC source")
        self.assertFalse(list((self.root / "workspace/maps").glob("*.map")))

    def test_output_above_native_bound_is_not_success(self):
        FakeInvader.bad_output = True
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "verify"))

    def test_output_identity_alias_preserves_original_scenario(self):
        self.profile["output_id"] = "community_sample"
        result = self.convert()
        self.assertEqual(result["header"]["name"], "community_sample")
        tags = self.root / "workspace/source-tags/levels/sample/sample.scenario"
        alias = self.root / "workspace/tags/levels/sample/community_sample.scenario"
        self.assertEqual(tags.read_bytes(), alias.read_bytes())

    def test_authored_scenario_punctuation_keeps_source_and_uses_safe_output_alias(self):
        tags = self.root / "punctuated-tags"
        authored = "levels/[custom]/bigassv2,104"
        source = tags / (authored + ".scenario")
        source.parent.mkdir(parents=True)
        source.write_bytes(b"original authored scenario")
        original, compiled = backend._scenario(tags, {"name": "bigassv2,104"}, None, "bigassv2_104")
        self.assertEqual(original, authored)
        self.assertEqual(compiled, "levels/[custom]/bigassv2_104")
        self.assertEqual(source.read_bytes(), b"original authored scenario")
        self.assertEqual((tags / (compiled + ".scenario")).read_bytes(), source.read_bytes())


    def test_authored_scenario_punctuation_does_not_allow_unsafe_paths(self):
        for scenario in ("../map,1", "levels/[custom]/../map,1", "/map,1", "C:/map,1",
                         "levels/map,1\n", "levels/map,1:stream"):
            with self.subTest(scenario=scenario):
                with self.assertRaisesRegex(backend.ConversionError, "unsafe"):
                    backend._scenario(self.root, {"name": "sample"}, {"scenario": scenario}, "safe_map")


    def test_exact_cache_hash_selects_recipe_independent_of_name(self):
        spec = {"source_sha256": self.header["sha256"], "source_name": "historic-source-name",
                "scenario": "levels/sample/sample", "id": "reviewed_sample"}
        self.header["name"] = "different-cache-name"
        self.profile.update(maps=[spec], selected_map=spec, output_id="reviewed_sample")
        self.assertEqual(self.convert()["header"]["name"], "reviewed_sample")

    def test_reviewed_script_removal_requires_pinned_pb3_recipe(self):
        self.profile.update(dependency_policy="stock-first", script_policy="reviewed", source_tags=str(self.root))
        self.profile["maps"] = [{"source_name": "sample", "scenario": "levels/sample/sample", "id": "sample",
                                 "scenario_sha256": "a" * 64, "optional_scripts": ["anything"]}]
        with self.assertRaises(backend.ConversionError) as caught:
            backend.convert_cache(self.source, self.header, self.root / "workspace", self.profile,
                                  self.root / "bin", self.manifest, self.root)
        self.assertIn("PB3 recipe", caught.exception.message)
        self.assertEqual(FakeInvader.calls, [])

    def test_changed_source_since_scan_is_rejected_before_extraction(self):
        self.source.write_bytes(b"different map")
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual(caught.exception.code, "input_changed")
        self.assertEqual(FakeInvader.calls, [])

    def test_unknown_format_is_rejected_before_tools(self):
        self.header["version"] = 99
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual(caught.exception.code, "unsupported_format")
        self.assertEqual(FakeInvader.calls, [])

    def test_unreviewed_overlay_is_not_a_compile_input(self):
        overlay = self.root / "overlay"
        (overlay / "tags").mkdir(parents=True)
        (overlay / "tags/weapon.weapon").write_bytes(b"arbitrary edited gameplay")
        self.profile["overlays"] = [str(overlay)]
        with self.assertRaises(backend.ConversionError) as caught:
            self.convert()
        self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "overlays"))
        self.assertFalse(any(tool == "build" for tool, _ in FakeInvader.calls))

    def test_output_tag_span_must_fit_declared_cache(self):
        path = self.root / "sample-output.map"
        cache(path, name="sample-output", offset=4000, tags=256)
        with self.assertRaises(backend.ConversionError) as caught:
            backend._target_header(path, self.profile["target"], "sample-output")
        self.assertEqual((caught.exception.code, caught.exception.stage), ("invalid_output", "verify"))

    def test_verified_pb3_recipe_uses_exact_source_tags_and_keeps_inputs(self):
        self.manifest.write_text("{}")
        spec = json.loads(backend.legacy.POLICY.read_text())["maps"][0]
        self.header["name"] = Path(spec["scenario"]).name
        source_tags = self.root / "source-package/tags"
        scenario = source_tags / (spec["scenario"] + ".scenario")
        scenario.parent.mkdir(parents=True)
        scenario.write_bytes(b"reviewed synthetic scenario")
        self.profile.update(dependency_policy="stock-first", script_policy="reviewed",
                            source_tags=str(source_tags), maps=[spec], selected_map=spec)
        # The checked-in profile hash is enforced by build_map. Mock that
        # operation only, so this test exercises the selected-recipe boundary
        # without pretending synthetic tags are the actual reviewed assets.
        stock_maps = self.root / "stock"
        stock_maps.mkdir()
        for name in ("bloodgulch", "a10", "ui"):
            cache(stock_maps / f"{name}.map", name=name)

        def stock(tool, maps, destination):
            destination.mkdir()
            return {"inputs": {}, "compatibility_patches": []}

        def build(tool, chosen, package, stock, output):
            self.assertEqual(chosen["scenario_sha256"], spec["scenario_sha256"])
            self.assertEqual(chosen["optional_scripts"], spec["optional_scripts"])
            self.assertEqual((package / "tags" / (spec["scenario"] + ".scenario")).read_bytes(), scenario.read_bytes())
            maps = output / chosen["id"] / "maps"
            maps.mkdir(parents=True)
            result = maps / f"{chosen['id']}.map"
            cache(result, name=chosen["id"])
            return {"output": str(result), "removed_optional_scripts": chosen["optional_scripts"]}

        with patch.object(backend.legacy, "prepare_stock", side_effect=stock), \
                patch.object(backend.legacy, "build_map", side_effect=build) as approved:
            result = backend.convert_cache(self.source, self.header, self.root / "workspace", self.profile,
                                           self.root / "bin", self.manifest, stock_maps)
        self.assertEqual(approved.call_count, 1)
        self.assertEqual(result["header"]["name"], spec["id"])
        self.assertEqual(scenario.read_bytes(), b"reviewed synthetic scenario")
        self.assertFalse(any(tool == "extract" for tool, _ in FakeInvader.calls))

    def test_helper_failure_still_checks_immutable_sources(self):
        original_run = FakeInvader.run

        def mutate(tool, name, *args):
            if name == "build":
                self.source.write_bytes(b"externally changed while tool ran")
                raise backend.ConversionError("needs_profile", "compile", "rejected API")
            return original_run(tool, name, *args)

        with patch.object(FakeInvader, "run", mutate):
            with self.assertRaises(backend.ConversionError) as caught:
                self.convert()
        self.assertEqual(caught.exception.code, "input_changed")
        self.assertEqual(caught.exception.details["original_error"]["code"], "needs_profile")


class ApprovedToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def tool(self, suffix=""):
        binaries = {}
        for name in backend.AUTHORING_TOOLS:
            binary = self.root / ("invader-" + name + suffix)
            binary.write_bytes(("controlled " + name).encode())
            binaries[name] = {"sha256": backend.legacy.digest(binary)}
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"invader_commit": json.loads(backend.legacy.POLICY.read_text())["invader_commit"],
                                        "binaries": binaries}))
        tool = backend.ApprovedInvader(self.root, manifest, self.root)
        tool.stage = "compile"
        return tool

    def test_exe_names_are_verified_and_used(self):
        tool = self.tool(suffix=".exe")
        result = subprocess.CompletedProcess(["invader-build.exe"], 0, "compiled", "")
        with patch.object(backend.subprocess, "run", return_value=result) as run:
            self.assertEqual(tool.run("build"), "compiled")
        self.assertEqual(run.call_args.args[0][0], str((self.root / "invader-build.exe").resolve()))

    def test_changed_binary_is_rejected(self):
        tool = self.tool()
        tool.tool_paths["build"].write_bytes(b"unapproved build")
        with self.assertRaisesRegex(ValueError, "binary differs"):
            backend.ApprovedInvader(self.root, self.root / "manifest.json", self.root)

    def test_changed_binary_is_not_executed_after_verification(self):
        tool = self.tool()
        tool.tool_paths["build"].write_bytes(b"changed after approval")
        with patch.object(backend.subprocess, "run") as run:
            with self.assertRaises(backend.ConversionError) as caught:
                tool.run("build")
        self.assertEqual(caught.exception.code, "toolchain_invalid")
        run.assert_not_called()

    def test_rejection_retains_stdout_stderr_and_log(self):
        tool = self.tool()
        result = subprocess.CompletedProcess(["invader-build"], 1, "compile progress", "unsupported parameter")
        with patch.object(backend.subprocess, "run", return_value=result) as run:
            with self.assertRaises(backend.ConversionError) as caught:
                tool.run("build", "-S", "tags")
        self.assertEqual(caught.exception.code, "needs_profile")
        self.assertEqual(caught.exception.details["stderr"], "unsupported parameter")
        self.assertEqual(Path(caught.exception.details["log"]).read_text(), "compile progressunsupported parameter")
        self.assertEqual(run.call_args.kwargs["timeout"], backend.TOOL_TIMEOUT_SECONDS)

    def test_timeout_is_distinct_and_preserves_partial_diagnostics(self):
        tool = self.tool()
        timeout = subprocess.TimeoutExpired(["invader-build"], 300, output=b"partial", stderr=b"last diagnostic")
        with patch.object(backend.subprocess, "run", side_effect=timeout):
            with self.assertRaises(backend.ConversionError) as caught:
                tool.run("build")
        self.assertEqual(caught.exception.code, "tool_timeout")
        self.assertTrue(caught.exception.details["timed_out"])
        self.assertEqual(caught.exception.details["stdout"], "partial")
        self.assertEqual(caught.exception.details["stderr"], "last diagnostic")


class StockLibraryTests(unittest.TestCase):
    def test_campaign_library_is_optional_and_rejects_non_original_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            maps = root / "maps"
            maps.mkdir()
            for name in ("bloodgulch", "a10", "ui"):
                cache(maps / f"{name}.map", name=name)
            tool = Mock()
            record = backend._extract_stock(tool, maps, root / "without-c40", include_campaign_weapons=True)
            self.assertEqual(list(record["inputs"]), ["bloodgulch", "a10", "ui"])

            cache(maps / "c40.map", name="c40")
            record = backend._extract_stock(tool, maps, root / "with-c40", include_campaign_weapons=True)
            self.assertEqual(list(record["inputs"]), ["bloodgulch", "a10", "ui", "c40"])
            self.assertEqual(record["inputs"]["c40"]["sha256"], backend.legacy.digest(maps / "c40.map"))

            cache(maps / "c40.map", version=13, name="c40")
            tool.reset_mock()
            with self.assertRaises(backend.ConversionError) as caught:
                backend._extract_stock(tool, maps, root / "invalid-c40", include_campaign_weapons=True)
            self.assertEqual((caught.exception.code, caught.exception.stage), ("needs_profile", "stock"))
            self.assertFalse(any(str(call.args[-1]).endswith("c40.map") for call in tool.run.call_args_list))


if __name__ == "__main__":
    unittest.main()
