"""Synthetic asset-wrapper trust, lookup, preservation and report boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.map_pipeline import assets
from tools.map_pipeline import profiles
from tools.map_pipeline.backend import ConversionError
from tools.community_maps import digest


SOURCE_FORMATS = {"audio": "ogg_vorbis", "bitmaps": "bc7", "mips": "dxt5", "packing": "a8r8g8b8",
                  "extensions": "mcc_anniversary_hud_remaps"}


def audit(name, kind="audio", status="convertible"):
    result = {"tag": name, "status": status,
              "source_formats": [SOURCE_FORMATS[kind]]}
    if status == "unsupported":
        result["reason"] = "Synthetic unsupported encoding"
    return result


def measurement(name, kind="audio"):
    result = {"tag": name, "status": "converted",
              "source_formats": [SOURCE_FORMATS[kind]],
              "target_format": assets.KINDS[kind][2]}
    if kind == "audio":
        result.update(metadata={"channels": 1, "sample_rate": 22050, "pitch_ranges": 1,
                                "permutations": 1, "permutations_to_convert": 1},
                      input_bytes=32, output_bytes=36, converted_permutations=1,
                      preserved_adpcm_permutations=0, padding_frames_total=0,
                      authored_metadata_preserved=True,
                      permutations=[{"pitch_range": 0, "permutation": 0, "source_format": "ogg_vorbis",
                                     "decoded_bits_per_sample": 24, "frames": 64, "padding_frames": 0,
                                     "padding_ms": 0, "encoded_bytes": 36, "snr_db": 35.0,
                                     "signal_is_silent": False, "waveform_exact": False,
                                     "rms_error_normalized": 0.01, "peak_error_normalized": 0.03}])
    elif kind == "bitmaps":
        result.update(images_converted=1, images=[{"index": 0, "width": 4, "height": 4, "depth": 1,
                                                  "type": "2d", "faces": 1, "mips": 1,
                                                  "pixel_bytes": 16, "pixel_offset": 0}],
                      sizes={"tag_before": 32, "tag_after": 32, "pixel_before": 16, "pixel_after": 16},
                      pixel_quality={"comparison": "decoded_bc7_vs_decoded_dxt5", "pixels": 16,
                                     "rgb_rmse": 1.0, "alpha_rmse": 0.0,
                                     "rgb_max_error": 2, "alpha_max_error": 0,
                                     "visual_validation": "pending"},
                      metadata_preserved=True, unselected_pixels_preserved=True)
    elif kind == "mips":
        result.update(images_selected=1,
                      images=[{"index": 0, "type": "2d", "format": "dxt5", "faces": 1,
                               "native_limit": {"width": 2048, "height": 2048, "depth": 1},
                               "before": {"width": 4096, "height": 2048, "depth": 1, "mips": 3},
                               "after": {"width": 2048, "height": 1024, "depth": 1, "mips": 2},
                               "mips_removed": 1, "bytes_removed": 8388608, "retained_bytes": 2621440,
                               "registration_point_preserved": True}],
                      sizes={"tag_before": 11010448, "tag_after": 2621840,
                             "pixel_before": 11010048, "pixel_after": 2621440},
                      retained_mip_bytes_exact=True, metadata_preserved_except_dimensions=True,
                      unselected_pixels_preserved=True, authored_mip_generation_setting_preserved=True,
                      visual_validation="pending")
    elif kind == "packing":
        result.update(images_packed=1,
                      images=[{"index": 0, "width": 4, "height": 4, "depth": 1, "type": "2d",
                               "faces": 1, "mips": 1, "source_format": "a8r8g8b8", "target_format": "r5g6b5",
                               "bytes_before": 64, "bytes_after": 32, "decoded_pixels_exact": True}],
                      sizes={"tag_before": 104, "tag_after": 72, "pixel_before": 64, "pixel_after": 32},
                      decoded_pixels_exact=True, native_gpu_pixels_exact=True, software_pixels_exact=True,
                      metadata_preserved=True, unselected_pixels_preserved=True,
                      visual_validation="pending")
    else:
        result.update(fields=["anniversary_hud_remaps"], counts_before={"anniversary_hud_remaps": 14},
                      counts_after={"anniversary_hud_remaps": 0}, authored_metadata_preserved=True,
                      target_capability="xbox_v5_no_anniversary_hud_remaps", input_bytes=460, output_bytes=208,
                      reason="Original Xbox v5 does not use MCC anniversary HUD remaps")
    return result


class FakeAssets:
    def __init__(self, inventories=None, reports=None, mutation=None):
        self.inventories = inventories or {}
        self.reports, self.mutation = reports, mutation
        self.calls = []

    def run(self, kind, mode, root, shader_only=None):
        self.calls.append((kind, mode, root))
        if shader_only is not None:
            self.shader_proof = shader_only
        if mode == "--audit":
            return copy.deepcopy(self.inventories.get(root, []))
        names = (root / "asset-paths.txt").read_text().splitlines()
        for name in names:
            (root / "tags" / name).write_bytes(b"synthetic converted bytes")
        if self.mutation:
            self.mutation(root)
        if self.reports is not None:
            return copy.deepcopy(self.reports)
        reports = [measurement(name, kind) for name in names]
        if kind == "audio":
            for report in reports:
                report["input_bytes"] = (root / "source-snapshots" / report["tag"]).stat().st_size
                report["output_bytes"] = (root / "tags" / report["tag"]).stat().st_size
        return reports

    def provenance(self):
        return {"manifest_sha256": "0" * 64, "invader_commit": "synthetic", "binaries": {}}


class AssetWrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.upper = self.root / "upper"
        self.lower = self.root / "lower"
        self.upper.mkdir(); self.lower.mkdir()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.steps, self.repairs = [], []

    def tag(self, root, name, content=b"authored input"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def convert(self, tool, required, kind="audio", workspace=None):
        return assets.convert_assets(tool, kind, [self.upper, self.lower], set(required),
                                     workspace or self.workspace, self.steps, self.repairs)

    def test_format_selection_accepts_arbitrary_authored_names(self):
        names = ("my-original-map/new-weapon/custom-shot.sound", "unlisted-author/ambience/sunset.sound")
        originals = {name: self.tag(self.upper, name) for name in names}
        hashes = {name: digest(path) for name, path in originals.items()}
        tool = FakeAssets({self.upper: [audit(name) for name in names]})
        overlay = self.convert(tool, names)
        self.assertEqual({record["tag"] for record in self.repairs}, set(names))
        self.assertEqual({name: digest(path) for name, path in originals.items()}, hashes)
        self.assertTrue(all((overlay / name).read_bytes() == b"synthetic converted bytes" for name in names))

    def test_upper_native_tag_without_audit_entry_shadows_unsupported_lower(self):
        name = "authored/upper-wins.sound"
        path = self.tag(self.upper, name, b"native Xbox ADPCM")
        self.tag(self.lower, name, b"unsupported lower encoding")
        tool = FakeAssets({self.upper: [], self.lower: [audit(name, status="unsupported")]})
        self.assertIsNone(self.convert(tool, [name]))
        self.assertEqual(path.read_bytes(), b"native Xbox ADPCM")
        self.assertEqual(self.steps[-1]["selected_tags"], 0)
        self.assertEqual(self.steps[-1]["blockers"], [])
        self.assertFalse(any(mode == "--convert" for _kind, mode, _root in tool.calls))

    def test_winning_convertible_tag_uses_upper_bytes_and_ignores_lower_blocker(self):
        name = "authored/preferred.sound"
        self.tag(self.upper, name, b"upper original")
        self.tag(self.lower, name, b"lower different original")
        tool = FakeAssets({self.upper: [audit(name)], self.lower: [audit(name, status="unsupported")]})
        overlay = self.convert(tool, [name])
        self.assertEqual((overlay.parent / "source-snapshots" / name).read_bytes(), b"upper original")
        self.assertEqual(self.steps[-1]["blockers"], [])

    def test_unreachable_unsupported_tag_does_not_block_conversion(self):
        required, unused = "required/shot.sound", "unused/incompatible.sound"
        self.tag(self.upper, required); self.tag(self.upper, unused)
        tool = FakeAssets({self.upper: [audit(required), audit(unused, status="unsupported")]})
        overlay = self.convert(tool, [required])
        self.assertTrue((overlay / required).is_file())
        self.assertFalse((overlay / unused).exists())
        self.assertEqual(self.steps[-1]["blockers"], [])

    def test_bitmap_report_preserves_metadata_and_records_quality_as_pending(self):
        name = "unlisted-author/sunset.bitmap"
        self.tag(self.upper, name)
        tool = FakeAssets({self.upper: [audit(name, "bitmaps")]})
        overlay = self.convert(tool, [name], kind="bitmaps")
        self.assertTrue((overlay / name).is_file())
        self.assertEqual(self.repairs[0]["measurements"]["pixel_quality"]["visual_validation"], "pending")
        self.assertTrue(self.repairs[0]["measurements"]["metadata_preserved"])

    def test_mip_stage_records_existing_bytes_selection_without_codec_change(self):
        name = "new-author/oversized-authored.bitmap"
        original = self.tag(self.upper, name)
        original_hash = digest(original)
        tool = FakeAssets({self.upper: [audit(name, "mips")]})
        overlay = self.convert(tool, [name], kind="mips")
        self.assertTrue((overlay / name).is_file())
        self.assertEqual(digest(original), original_hash)
        repair = self.repairs[0]
        self.assertEqual(repair["operation"], "asset_mips")
        self.assertEqual(repair["target"], "existing_authored_mips")
        self.assertEqual(repair["source_formats"], ["dxt5"])
        report = repair["measurements"]
        self.assertTrue(report["retained_mip_bytes_exact"])
        self.assertTrue(report["metadata_preserved_except_dimensions"])
        self.assertTrue(report["authored_mip_generation_setting_preserved"])
        self.assertEqual(report["images"][0]["after"]["width"], 2048)
        self.assertEqual(report["visual_validation"], "pending")
        receipt = json.loads((self.workspace / "asset-mips/conversion.json").read_text())
        self.assertEqual(receipt["status"], "converted")
        self.assertTrue(receipt["source_unchanged"])

    def test_lossless_packing_records_exact_decoded_pixels_and_preserved_source(self):
        name = "unlisted-author/exact-native-colors.bitmap"
        original = self.tag(self.upper, name)
        before = digest(original)
        tool = FakeAssets({self.upper: [audit(name, "packing")]})
        overlay = self.convert(tool, [name], kind="packing")
        self.assertTrue((overlay / name).is_file())
        self.assertEqual(digest(original), before)
        record = self.repairs[0]["measurements"]
        self.assertEqual(record["target_format"], "lossless_native_pixels")
        self.assertEqual(record["source_formats"], ["a8r8g8b8"])
        self.assertTrue(record["decoded_pixels_exact"])
        self.assertTrue(record["native_gpu_pixels_exact"])
        self.assertTrue(record["software_pixels_exact"])
        self.assertTrue(record["metadata_preserved"])
        self.assertTrue(record["unselected_pixels_preserved"])
        self.assertEqual(record["visual_validation"], "pending")
        self.assertLess(record["sizes"]["pixel_after"], record["sizes"]["pixel_before"])
        self.assertEqual(json.loads((self.workspace / "asset-packing/conversion.json").read_text())["status"], "converted")

    def test_mcc_extension_omission_is_specific_capability_record_and_preserves_original(self):
        name = "new-author/custom-user-interface.hud_globals"
        original = self.tag(self.upper, name)
        before = digest(original)
        tool = FakeAssets({self.upper: [audit(name, "extensions")]})
        overlay = self.convert(tool, [name], kind="extensions")
        self.assertTrue((overlay / name).is_file())
        self.assertEqual(digest(original), before)
        report = self.repairs[0]["measurements"]
        self.assertEqual(report["target_format"], "native_xbox_fields")
        self.assertEqual(report["fields"], ["anniversary_hud_remaps"])
        self.assertEqual(report["counts_before"], {"anniversary_hud_remaps": 14})
        self.assertEqual(report["counts_after"], {"anniversary_hud_remaps": 0})
        self.assertTrue(report["authored_metadata_preserved"])
        self.assertEqual(report["target_capability"], "xbox_v5_no_anniversary_hud_remaps")
        self.assertTrue(report["reason"])
        receipt = json.loads((self.workspace / "asset-extensions/conversion.json").read_text())
        self.assertEqual(receipt["status"], "converted")
        self.assertTrue(receipt["source_unchanged"])

    def test_incomplete_or_unreviewed_mcc_extension_omissions_are_rejected(self):
        name = "authored/interface.hud_globals"
        self.tag(self.upper, name)
        complete = measurement(name, "extensions")
        cases = []
        for field in ("fields", "counts_before", "counts_after", "authored_metadata_preserved",
                      "target_capability", "input_bytes", "output_bytes", "reason"):
            value = copy.deepcopy(complete); value.pop(field); cases.append(value)
        for field, invalid in (("fields", ["player_hud"]),
                               ("counts_before", {"anniversary_hud_remaps": 0}),
                               ("counts_after", {"anniversary_hud_remaps": 1}),
                               ("authored_metadata_preserved", False), ("target_capability", "strip_all_extensions"),
                               ("input_bytes", True), ("output_bytes", 0), ("reason", "")):
            value = copy.deepcopy(complete); value[field] = invalid; cases.append(value)
        for index, report in enumerate(cases):
            with self.subTest(case=index):
                workspace = self.root / ("extensions-invalid-" + str(index)); workspace.mkdir()
                tool = FakeAssets({self.upper: [audit(name, "extensions")]}, reports=[report])
                with self.assertRaises((ValueError, ConversionError)):
                    self.convert(tool, [name], kind="extensions", workspace=workspace)
                self.assertEqual(json.loads((workspace / "asset-extensions/conversion.json").read_text())["status"], "failed")
                self.assertEqual(self.repairs, [])

    def test_incomplete_or_lossy_packing_reports_are_rejected(self):
        name = "authored/exact-packed.bitmap"
        self.tag(self.upper, name)
        complete = measurement(name, "packing")
        cases = []
        for field in ("images_packed", "images", "sizes", "decoded_pixels_exact",
                      "native_gpu_pixels_exact", "software_pixels_exact",
                      "metadata_preserved", "unselected_pixels_preserved", "visual_validation"):
            value = copy.deepcopy(complete); value.pop(field); cases.append(value)
        for field, invalid in (("images_packed", 0), ("images_packed", True), ("images_packed", 2),
                               ("images", []), ("decoded_pixels_exact", False),
                               ("native_gpu_pixels_exact", False), ("software_pixels_exact", False),
                               ("metadata_preserved", False), ("unselected_pixels_preserved", False),
                               ("visual_validation", "passed"), ("target_format", "dxt5")):
            value = copy.deepcopy(complete); value[field] = invalid; cases.append(value)
        value = copy.deepcopy(complete); value["sizes"].pop("pixel_after"); cases.append(value)
        value = copy.deepcopy(complete); value["sizes"]["pixel_after"] = 64; cases.append(value)
        for index, report in enumerate(cases):
            with self.subTest(case=index):
                workspace = self.root / ("packing-invalid-" + str(index)); workspace.mkdir()
                tool = FakeAssets({self.upper: [audit(name, "packing")]}, reports=[report])
                with self.assertRaises((ValueError, ConversionError)):
                    self.convert(tool, [name], kind="packing", workspace=workspace)
                self.assertEqual(json.loads((workspace / "asset-packing/conversion.json").read_text())["status"], "failed")
                self.assertEqual(self.repairs, [])

    def test_native_upper_bitmap_shadows_lower_oversized_mip_input(self):
        name = "authored/preferred-size.bitmap"
        self.tag(self.upper, name, b"native dimension authored image")
        self.tag(self.lower, name, b"oversized lower image")
        tool = FakeAssets({self.upper: [], self.lower: [audit(name, "mips")]})
        self.assertIsNone(self.convert(tool, [name], kind="mips"))
        self.assertEqual(self.steps[-1]["selected_tags"], 0)
        self.assertEqual(self.repairs, [])

    def test_mip_selection_incomplete_preservation_reports_are_rejected(self):
        name = "authored/large.bitmap"
        self.tag(self.upper, name)
        complete = measurement(name, "mips")
        cases = []
        for field in ("retained_mip_bytes_exact", "metadata_preserved_except_dimensions",
                      "images_selected", "images", "sizes"):
            value = copy.deepcopy(complete); value.pop(field); cases.append(value)
        for field, invalid in (("retained_mip_bytes_exact", False),
                               ("metadata_preserved_except_dimensions", False),
                               ("images_selected", True), ("images_selected", 0),
                               ("images", []), ("target_format", "dxt5"),
                               ("source_formats", ["bc7"])):
            value = copy.deepcopy(complete); value[field] = invalid; cases.append(value)
        for field, invalid in (("mips_removed", 99), ("registration_point_preserved", False),
                               ("bytes_removed", -1), ("retained_bytes", 0)):
            value = copy.deepcopy(complete); value["images"][0][field] = invalid; cases.append(value)
        value = copy.deepcopy(complete); value["images"][0]["after"]["width"] = 1024; cases.append(value)
        value = copy.deepcopy(complete); value["images"][0]["after"]["mips"] = 3; cases.append(value)
        value = copy.deepcopy(complete); value["images"][0].pop("native_limit"); cases.append(value)
        value = copy.deepcopy(complete); value["sizes"]["pixel_after"] += 1; cases.append(value)
        value = copy.deepcopy(complete); value["images_selected"] = 2; cases.append(value)
        value = copy.deepcopy(complete); value["images"].append(copy.deepcopy(value["images"][0])); value["images_selected"] = 2; cases.append(value)
        for field, invalid in (("unselected_pixels_preserved", False),
                               ("authored_mip_generation_setting_preserved", False),
                               ("visual_validation", "passed")):
            value = copy.deepcopy(complete); value[field] = invalid; cases.append(value)
        for index, report in enumerate(cases):
            with self.subTest(case=index):
                workspace = self.root / ("mips-invalid-" + str(index)); workspace.mkdir()
                tool = FakeAssets({self.upper: [audit(name, "mips")]}, reports=[report])
                with self.assertRaises((ValueError, ConversionError)):
                    self.convert(tool, [name], kind="mips", workspace=workspace)
                self.assertEqual(json.loads((workspace / "asset-mips/conversion.json").read_text())["status"], "failed")
                self.assertEqual(self.repairs, [])

    def test_conversion_mutation_of_original_or_snapshot_is_rejected(self):
        name = "required/immutable.sound"
        original = self.tag(self.upper, name)
        for index, which in enumerate(("original", "snapshot")):
            with self.subTest(which=which):
                original.write_bytes(b"authored input")
                workspace = self.root / ("mutation-" + str(index)); workspace.mkdir()
                def mutate(folder, selected=which):
                    at = original if selected == "original" else folder / "source-snapshots" / name
                    at.write_bytes(b"unexpected mutation")
                tool = FakeAssets({self.upper: [audit(name)]}, mutation=mutate)
                with self.assertRaises(ConversionError) as failure:
                    self.convert(tool, [name], workspace=workspace)
                self.assertEqual(failure.exception.code, "input_changed")
                report = json.loads((workspace / "asset-audio/conversion.json").read_text())
                self.assertEqual(report["status"], "failed")
        self.assertEqual(self.repairs, [])

    def test_malformed_conversion_tag_coverage_fails(self):
        name = "required/shot.sound"
        self.tag(self.upper, name)
        cases = ([], [measurement(name), measurement(name)], [measurement("unexpected/other.sound")], [{}])
        for index, reports in enumerate(cases):
            with self.subTest(reports=reports):
                workspace = self.root / ("coverage-" + str(index)); workspace.mkdir()
                tool = FakeAssets({self.upper: [audit(name)]}, reports=reports)
                with self.assertRaises((ValueError, ConversionError)):
                    self.convert(tool, [name], workspace=workspace)
                self.assertEqual(json.loads((workspace / "asset-audio/conversion.json").read_text())["status"], "failed")
        self.assertEqual(self.repairs, [])

    def test_incomplete_or_untruthful_conversion_measurements_fail_before_repairs(self):
        for kind in ("audio", "bitmaps"):
            suffix = assets.KINDS[kind][0]
            name = "required/asset" + suffix
            self.tag(self.upper, name)
            complete = measurement(name, kind)
            cases = [{"tag": name}]
            for field in ("status", "target_format", "source_formats",
                          "permutations" if kind == "audio" else "pixel_quality"):
                report = copy.deepcopy(complete); report.pop(field); cases.append(report)
            for field, value in (("status", "unsupported"), ("target_format", "unselected_format"),
                                 ("authored_metadata_preserved" if kind == "audio" else "metadata_preserved", False)):
                report = copy.deepcopy(complete); report[field] = value; cases.append(report)
            for index, report in enumerate(cases):
                with self.subTest(kind=kind, case=index):
                    workspace = self.root / (kind + "-invalid-" + str(index)); workspace.mkdir()
                    tool = FakeAssets({self.upper: [audit(name, kind)]}, reports=[report])
                    repair_count = len(self.repairs)
                    with self.assertRaises((ValueError, ConversionError)):
                        self.convert(tool, [name], kind=kind, workspace=workspace)
                    self.assertEqual(len(self.repairs), repair_count)
                    self.assertEqual(json.loads((workspace / ("asset-" + kind) / "conversion.json").read_text())["status"], "failed")

    def test_required_blocker_retains_completed_repairs_and_conversion_receipt(self):
        good, blocked = "required/good.sound", "required/blocked.sound"
        self.tag(self.upper, good); self.tag(self.upper, blocked)
        tool = FakeAssets({self.upper: [audit(good), audit(blocked, status="unsupported")]})
        with self.assertRaises(ConversionError) as failure:
            self.convert(tool, [good, blocked])
        self.assertEqual(failure.exception.code, "needs_profile")
        self.assertEqual(failure.exception.details["asset_blockers"][0]["tag"], blocked)
        self.assertEqual([record["tag"] for record in self.repairs], [good])
        self.assertEqual(self.steps[-1]["status"], "converted")
        self.assertEqual(self.steps[-1]["blockers"][0]["tag"], blocked)
        report = json.loads((self.workspace / "asset-audio/conversion.json").read_text())
        self.assertEqual(report["status"], "converted")
        self.assertTrue(report["source_unchanged"])


class AssetToolManifestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.logs = self.root / "logs"; self.logs.mkdir()
        self.commands = []
        pins = json.loads((assets.ROOT / "tools/community-toolchain/pins.json").read_text())
        self.receipt = {"schema": 1, "invader_commit": pins["invader_commit"],
                        "riat_commit": pins["riat_commit"], "binaries": {}}
        for kind, (_suffix, filename, _target) in assets.KINDS.items():
            source = self.root / "tools/map_conversion" / filename
            source.parent.mkdir(parents=True, exist_ok=True); source.write_bytes(b"synthetic helper source")
            binary = self.root / ("convert-" + kind); binary.write_bytes(b"synthetic helper binary")
            self.receipt["binaries"][kind] = {"file": binary.name, "sha256": digest(binary), "source_sha256": digest(source)}
        pins_file = self.root / "tools/community-toolchain/pins.json"
        pins_file.parent.mkdir(parents=True); pins_file.write_text(json.dumps(pins))
        self.manifest = self.root / "asset-tools.json"; self.write_manifest()
        patcher = patch.object(assets, "ROOT", self.root)
        patcher.start(); self.addCleanup(patcher.stop)

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.receipt))

    def test_builder_schema_and_source_bound_binary_are_accepted(self):
        tool = assets.AssetTools(self.manifest, self.logs, self.commands)
        self.assertEqual(tool.binary("audio"), self.root / "convert-audio")
        self.assertEqual(tool.provenance()["manifest_sha256"], digest(self.manifest))

    def test_revision_schema_binary_source_and_manifest_mutations_are_rejected(self):
        for field, value in (("schema", 2), ("invader_commit", "0" * 40), ("riat_commit", "0" * 40)):
            with self.subTest(field=field):
                retained = self.receipt[field]; self.receipt[field] = value; self.write_manifest()
                with self.assertRaises(ValueError):
                    assets.AssetTools(self.manifest, self.logs, self.commands)
                self.receipt[field] = retained
        self.write_manifest()
        for path in (self.root / "convert-audio", self.root / "tools/map_conversion/convert_audio.cpp", self.manifest):
            with self.subTest(path=path):
                original = path.read_bytes()
                tool = assets.AssetTools(self.manifest, self.logs, self.commands)
                path.write_bytes(original + b"\n")
                with self.assertRaises(ValueError):
                    tool.binary("audio")
                path.write_bytes(original)

    def test_native_json_lines_malformed_or_nonobject_reports_fail(self):
        tool = assets.AssetTools(self.manifest, self.logs, self.commands)
        for stdout in ("not json", "[]", "null", "42"):
            with self.subTest(stdout=stdout), patch.object(assets.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, "")):
                with self.assertRaises(ConversionError) as failure:
                    tool.run("audio", "--audit", self.root)
                self.assertEqual(failure.exception.code, "invalid_asset_report")

    def test_shader_usage_argument_is_limited_to_mip_auditing(self):
        tool = assets.AssetTools(self.manifest, self.logs, self.commands)
        proof = self.root / "shader-only.txt"; proof.write_text("custom/high.bitmap\n")
        with patch.object(assets.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertEqual(tool.run("mips", "--audit", self.root, shader_only=proof), [])
        self.assertEqual(run.call_args.args[0][-2:], ["--shader-only", str(proof)])
        for kind, mode in (("audio", "--audit"), ("mips", "--convert"), ("packing", "--audit")):
            with self.subTest(kind=kind, mode=mode):
                with self.assertRaises(ValueError):
                    tool.run(kind, mode, self.root, shader_only=proof)


class BitmapUsageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.upper, self.lower = self.root / "upper", self.root / "lower"
        self.upper.mkdir(); self.lower.mkdir()
        self.workspace = self.root / "workspace"; self.workspace.mkdir()
        self.steps = []
        self.bitmaps = {"custom/high.bitmap", "custom/mixed.bitmap", "custom/unreferenced.bitmap"}
        self.required = self.bitmaps | {"shaders/model.shader_model", "shaders/world.shader_environment",
                                        "ui/hud.weapon_hud_interface", "levels/custom/custom.scenario"}
        for name in self.required:
            path = self.upper / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("synthetic authored " + name).encode())
        path = self.lower / "custom/high.bitmap"; path.parent.mkdir(parents=True)
        path.write_bytes(b"shadowed lower bitmap")

    def consumer(self, name, class_name, field="base_map"):
        return {"tag": name, "class": class_name, "field": field}

    def classification(self, name, consumers, shader_only):
        return {"tag": name, "status": "classified", "shader_only": shader_only,
                "consumers": consumers, "metadata": {"consumer_count": len(consumers),
                                                       "usage_scope": "required_reachable_tags"}}

    def classifications(self):
        model = self.consumer("shaders/model.shader_model", "shader_model")
        world = self.consumer("shaders/world.shader_environment", "shader_environment", "detail_map")
        hud = self.consumer("ui/hud.weapon_hud_interface", "weapon_hud_interface", "crosshairs.bitmap")
        return [self.classification("custom/high.bitmap", [model, world], True),
                self.classification("custom/mixed.bitmap", [model, hud], False),
                self.classification("custom/unreferenced.bitmap", [], False)]

    def proof(self, entries, mutation=None, workspace=None):
        fixture = self
        class UsageTool:
            def run(self, kind, mode, folder):
                fixture.assertEqual((kind, mode), ("mips", "--usage"))
                fixture.assertEqual((folder / "roots.txt").read_text().splitlines(), [str(fixture.upper), str(fixture.lower)])
                fixture.assertEqual((folder / "required-tags.txt").read_text().splitlines(), sorted(fixture.required))
                if mutation:
                    mutation(folder)
                return copy.deepcopy(entries)
        return assets.bitmap_usage_proof(UsageTool(), [self.upper, self.lower], self.required,
                                         workspace or self.workspace, self.steps)

    def test_complete_proof_selects_shader_only_and_hashes_winning_inputs(self):
        hashes = {name: digest(self.upper / name) for name in self.required}
        selected = self.proof(self.classifications())
        self.assertEqual(selected.read_text(), "custom/high.bitmap\n")
        report = json.loads((selected.parent / "usage.json").read_text())
        self.assertEqual(report["input_sha256"], hashes)
        self.assertTrue(report["source_unchanged"])
        self.assertEqual(self.steps[0]["required_bitmaps"], 3)
        self.assertEqual(self.steps[0]["shader_only_bitmaps"], 1)
        self.assertEqual(self.steps[0]["manifest_sha256"], digest(selected.parent / "usage.json"))

    def test_mixed_hud_and_unreferenced_bitmaps_are_not_shader_only(self):
        selected = self.proof(self.classifications())
        self.assertNotIn("custom/mixed.bitmap", selected.read_text())
        self.assertNotIn("custom/unreferenced.bitmap", selected.read_text())

    def test_claimed_shader_only_with_unsupported_classes_or_no_consumers_fails(self):
        for index, consumers in enumerate(([], [self.consumer("ui/hud.weapon_hud_interface", "weapon_hud_interface")],
                                          [self.consumer("shaders/model.shader_model", "shader_transparent_chicago")])):
            with self.subTest(case=index):
                entries = self.classifications(); entries[0] = self.classification("custom/high.bitmap", consumers, True)
                workspace = self.root / ("unsupported-" + str(index)); workspace.mkdir()
                with self.assertRaises(ConversionError) as failure:
                    self.proof(entries, workspace=workspace)
                self.assertEqual(failure.exception.code, "invalid_asset_report")
                self.assertFalse((workspace / "bitmap-usage/usage.json").exists())

    def test_missing_consumer_duplicate_bitmap_and_partial_coverage_fail(self):
        complete = self.classifications()
        missing_consumer = copy.deepcopy(complete)
        missing_consumer[0]["consumers"][0]["tag"] = "missing/unreachable.shader_model"
        cases = [missing_consumer, complete + [copy.deepcopy(complete[0])], complete[:-1]]
        bad_count = copy.deepcopy(complete); bad_count[0]["metadata"]["consumer_count"] = 1; cases.append(bad_count)
        for index, entries in enumerate(cases):
            with self.subTest(case=index):
                workspace = self.root / ("coverage-" + str(index)); workspace.mkdir()
                with self.assertRaises(ConversionError) as failure:
                    self.proof(entries, workspace=workspace)
                self.assertEqual(failure.exception.code, "invalid_asset_report")
        self.assertEqual(self.steps, [])

    def test_usage_audit_mutating_bitmap_or_consumer_fails(self):
        for index, name in enumerate(("custom/high.bitmap", "shaders/model.shader_model")):
            with self.subTest(name=name):
                path = self.upper / name; original = path.read_bytes()
                workspace = self.root / ("mutation-" + str(index)); workspace.mkdir()
                with self.assertRaises(ConversionError) as failure:
                    self.proof(self.classifications(), mutation=lambda _folder, at=path: at.write_bytes(b"unexpected mutation"), workspace=workspace)
                self.assertEqual(failure.exception.code, "input_changed")
                self.assertFalse((workspace / "bitmap-usage/usage.json").exists())
                path.write_bytes(original)
        self.assertEqual(self.steps, [])

    def test_mip_overlay_carries_verified_shader_usage_list_and_hash(self):
        selected = self.proof(self.classifications())
        tool = FakeAssets({self.upper: [audit("custom/high.bitmap", "mips")]})
        repairs = []
        overlay = assets.convert_assets(tool, "mips", [self.upper, self.lower], self.required,
                                        self.workspace, self.steps, repairs, shader_only=selected)
        self.assertEqual(tool.shader_proof, selected)
        self.assertEqual((overlay.parent / "shader-only.txt").read_bytes(), selected.read_bytes())
        receipt = json.loads((overlay.parent / "conversion.json").read_text())
        self.assertEqual(receipt["shader_usage_proof_sha256"], digest(selected))


class DimensionProfileTests(unittest.TestCase):
    def source_profile(self):
        return json.loads((profiles.PROFILE_ROOT / "authored-xbox-v5.json").read_text())

    def test_profile_accepts_512_mib_cache_ceiling_and_rejects_larger_values(self):
        source = self.source_profile()
        source["target"]["max_cache_bytes"] = 512 * 1024 * 1024
        normalized = profiles.validate_profile(source)
        self.assertEqual(normalized["target"]["max_cache_bytes"], 536870912)
        self.assertEqual(normalized["target"]["max_tag_bytes"], 22 * 1024 * 1024)
        for limit in (512 * 1024 * 1024 + 1, 1024 * 1024 * 1024, True):
            with self.subTest(limit=limit):
                source["target"]["max_cache_bytes"] = limit
                with self.assertRaises(ValueError):
                    profiles.validate_profile(source)
        source["target"]["max_cache_bytes"] = 128 * 1024 * 1024
        self.assertEqual(profiles.validate_profile(source)["target"]["max_cache_bytes"], 134217728)
        source["target"]["max_tag_bytes"] = 22 * 1024 * 1024 + 1
        with self.assertRaises(ValueError):
            profiles.validate_profile(source)

    def test_generic_profiles_use_512_mib_but_reviewed_pb3_keeps_128_mib(self):
        for name in ("authored-xbox-v5", "og-multiplayer-v5"):
            with self.subTest(profile=name):
                self.assertEqual(profiles.load_profile(name)["target"]["max_cache_bytes"], 512 * 1024 * 1024)
        self.assertEqual(profiles.load_profile("og-multiplayer-v5")["version"], "1.12.0")
        self.assertEqual(profiles.load_profile("jukkis-pb3")["target"]["max_cache_bytes"], 128 * 1024 * 1024)

    def test_default_and_legacy_profiles_preserve_dimensions_without_mutating_input(self):
        source = self.source_profile()
        source.pop("asset_policy", None)
        before = copy.deepcopy(source)
        default = profiles.validate_profile(source)
        self.assertEqual(default["asset_policy"], {"audio": "preserve", "bitmaps": "preserve",
                                                    "dimensions": "preserve", "packing": "preserve",
                                                    "extensions": "preserve"})
        self.assertEqual(source, before)
        legacy = copy.deepcopy(source)
        legacy["asset_policy"] = {"audio": "xbox-adpcm", "bitmaps": "bc7-to-dxt5"}
        normalized = profiles.validate_profile(legacy)
        self.assertEqual(normalized["asset_policy"]["dimensions"], "preserve")
        self.assertEqual(normalized["asset_policy"]["packing"], "preserve")
        self.assertEqual(normalized["asset_policy"]["extensions"], "preserve")
        self.assertNotIn("dimensions", legacy["asset_policy"])
        self.assertNotIn("packing", legacy["asset_policy"])
        self.assertNotIn("extensions", legacy["asset_policy"])
        explicit = copy.deepcopy(legacy)
        explicit["asset_policy"]["dimensions"] = "preserve"
        self.assertEqual(profiles.validate_profile(explicit)["sha256"], normalized["sha256"])

    def test_legacy_dimensions_policy_defaults_to_preserve_packing_and_lossless_is_explicit(self):
        source = self.source_profile()
        source["asset_policy"] = {"audio": "xbox-adpcm", "bitmaps": "bc7-to-dxt5", "dimensions": "existing-mip"}
        normalized = profiles.validate_profile(source)
        self.assertEqual(normalized["asset_policy"]["packing"], "preserve")
        self.assertNotIn("packing", source["asset_policy"])
        source["asset_policy"]["packing"] = "preserve"
        self.assertEqual(profiles.validate_profile(source)["sha256"], normalized["sha256"])
        source["asset_policy"]["packing"] = "lossless"
        self.assertEqual(profiles.validate_profile(source)["asset_policy"]["packing"], "lossless")
        for choice in ("lossy", "dxt1", "quantize", None, True):
            with self.subTest(choice=choice):
                source["asset_policy"]["packing"] = choice
                with self.assertRaises(ValueError):
                    profiles.validate_profile(source)

    def test_dimension_selection_is_explicit_and_other_resize_policies_are_rejected(self):
        source = self.source_profile()
        source["asset_policy"] = {"audio": "preserve", "bitmaps": "preserve", "dimensions": "existing-mip"}
        selected = profiles.validate_profile(source)
        self.assertEqual(selected["asset_policy"]["dimensions"], "existing-mip")
        for choice in ("resize", "regenerate", "discard", None, True):
            with self.subTest(choice=choice):
                source["asset_policy"]["dimensions"] = choice
                with self.assertRaises(ValueError):
                    profiles.validate_profile(source)

    def test_legacy_asset_policy_preserves_extensions_and_mcc_omission_is_explicit(self):
        source = self.source_profile()
        source["asset_policy"] = {"audio": "preserve", "bitmaps": "preserve", "dimensions": "preserve", "packing": "lossless"}
        normalized = profiles.validate_profile(source)
        self.assertEqual(normalized["asset_policy"]["extensions"], "preserve")
        self.assertNotIn("extensions", source["asset_policy"])
        source["asset_policy"]["extensions"] = "preserve"
        self.assertEqual(profiles.validate_profile(source)["sha256"], normalized["sha256"])
        source["asset_policy"]["extensions"] = "omit-mcc"
        self.assertEqual(profiles.validate_profile(source)["asset_policy"]["extensions"], "omit-mcc")
        for choice in ("strip-all", "remove-unused", "lossless", None, True):
            with self.subTest(choice=choice):
                source["asset_policy"]["extensions"] = choice
                with self.assertRaises(ValueError):
                    profiles.validate_profile(source)


if __name__ == "__main__":
    unittest.main()
