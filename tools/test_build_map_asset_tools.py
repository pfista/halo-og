"""Synthetic, network-free checks for preserved-input asset helper builds."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import build_map_asset_tools as builder


class AssetToolBuilderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.toolchain = self.root / "toolchain"
        self.helpers = self.root / "helpers"
        self.helpers.mkdir()
        self.pins = self.root / "pins.json"
        self.pins.write_text(json.dumps({"invader_commit": "a" * 40, "riat_commit": "b" * 40,
                                         "invader_repository": "https://example.invalid/invader"}))
        self.compiler = self.root / "compiler"
        self.compiler.write_bytes(b"synthetic compiler")
        for name in builder.SOURCES.values():
            (self.helpers / name).write_bytes(b"// synthetic helper\n")
        for name in ("invader", "riat") + builder.STATIC_DEPENDENCIES:
            relative = ("build/libinvader.a" if name == "invader" else
                        "riat-build/release/libriatc.a" if name == "riat" else
                        "prefix/lib/lib" + name + ".a")
            path = self.toolchain / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        for name in ("invader/include/example.hpp", "prefix/include/example.h", "build/generated.hpp"):
            path = self.toolchain / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"// preserved header\n")
        self.manifest = self.toolchain / "source-manifest.json"
        self.manifest.write_bytes(self.pins.read_bytes())  # Legacy manifest needs no schema field.
        self.output = self.root / "new helpers"
        self.patchers = [patch.object(builder, "PINS", self.pins), patch.object(builder, "HELPERS", self.helpers),
                         patch.object(builder.sys, "platform", "darwin"),
                         patch.object(builder.shutil, "which", return_value=str(self.compiler)),
                         patch.object(builder.subprocess, "check_output", return_value="synthetic compiler 1\n")]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_compile(self, command, **_kwargs):
        Path(command[-1]).write_bytes(b"synthetic compiled helper")
        return subprocess.CompletedProcess(command, 0)

    def test_legacy_manifest_all_helpers_and_unchanged_receipt(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_compile) as run:
            receipt = builder.build(self.toolchain, self.manifest, self.output)
        self.assertEqual(run.call_count, 6)
        self.assertEqual(set(receipt["binaries"]), {"audio", "bitmaps", "mips", "packing", "extensions", "hud"})
        self.assertTrue(receipt["inputs_unchanged"])
        self.assertEqual(receipt["source_manifest_sha256"], builder.sha256(self.manifest))
        self.assertEqual(receipt["binaries"]["audio"]["source_sha256"], builder.sha256(self.helpers / "convert_audio.cpp"))
        self.assertEqual(receipt["system_linker_libraries"], ["z"])
        command = receipt["build_commands"]["audio"]
        self.assertIn(str(self.output / "convert-audio"), command)
        self.assertIn(str(self.toolchain / "prefix/lib/libFLAC.a"), command)
        self.assertNotIn("-lFLAC", command)
        self.assertEqual(json.loads((self.output / "asset-tools.json").read_text()), receipt)

    def test_existing_mip_selector_can_be_built_alone(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_compile) as run:
            receipt = builder.build(self.toolchain, self.manifest, self.output, tools="mips")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(set(receipt["binaries"]), {"mips"})
        self.assertEqual(receipt["binaries"]["mips"]["file"], "convert-mips")
        self.assertEqual(receipt["binaries"]["mips"]["source_sha256"], builder.sha256(self.helpers / "select_native_mips.cpp"))

    def test_lossless_pixel_packer_can_be_built_alone(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_compile) as run:
            receipt = builder.build(self.toolchain, self.manifest, self.output, tools="packing")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(set(receipt["binaries"]), {"packing"})
        self.assertEqual(receipt["binaries"]["packing"]["file"], "convert-packing")
        self.assertEqual(receipt["binaries"]["packing"]["source_sha256"], builder.sha256(self.helpers / "pack_lossless_bitmaps.cpp"))

    def test_mcc_extension_omitter_can_be_built_alone(self):
        with patch.object(builder.subprocess, "run", side_effect=self.fake_compile) as run:
            receipt = builder.build(self.toolchain, self.manifest, self.output, tools="extensions")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(set(receipt["binaries"]), {"extensions"})
        self.assertEqual(receipt["binaries"]["extensions"]["file"], "convert-extensions")
        self.assertEqual(receipt["binaries"]["extensions"]["source_sha256"], builder.sha256(self.helpers / "omit_mcc_extensions.cpp"))

    def test_fresh_source_layout_and_static_zlib_are_selected(self):
        sources = self.toolchain / "sources"
        sources.mkdir()
        (self.toolchain / "invader").rename(sources / "invader")
        (self.toolchain / "prefix/lib/libz.a").write_bytes(b"static zlib")
        with patch.object(builder.subprocess, "run", side_effect=self.fake_compile):
            receipt = builder.build(self.toolchain, self.manifest, self.output, tools="audio")
        self.assertEqual(set(receipt["binaries"]), {"audio"})
        self.assertEqual(receipt["system_linker_libraries"], [])
        self.assertIn(str(self.toolchain / "prefix/lib/libz.a"), receipt["build_commands"]["audio"])

    def test_changed_commit_or_ambiguous_library_fails_before_output(self):
        value = json.loads(self.manifest.read_text())
        value["riat_commit"] = "c" * 40
        self.manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "reviewed riat_commit"):
            builder.build(self.toolchain, self.manifest, self.output)
        self.assertFalse(self.output.exists())
        self.manifest.write_bytes(self.pins.read_bytes())
        extra = self.toolchain / "riat-build/second/release/libriatc.a"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"ambiguous")
        with self.assertRaisesRegex(ValueError, "unique release"):
            builder.build(self.toolchain, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_and_nested_output_are_preserved(self):
        self.output.mkdir()
        retained = self.output / "keep"
        retained.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            builder.build(self.toolchain, self.manifest, self.output)
        self.assertEqual(retained.read_bytes(), b"existing")
        with self.assertRaisesRegex(ValueError, "outside the preserved"):
            builder.build(self.toolchain, self.manifest, self.toolchain / "new-build")
        self.assertFalse((self.toolchain / "new-build").exists())

    def test_input_mutation_or_compile_failure_does_not_publish_manifest(self):
        header = self.toolchain / "prefix/include/example.h"
        def changing_compile(command, **kwargs):
            header.write_bytes(b"unexpected compiler mutation")
            return self.fake_compile(command, **kwargs)
        with patch.object(builder.subprocess, "run", side_effect=changing_compile):
            with self.assertRaisesRegex(RuntimeError, "inputs changed"):
                builder.build(self.toolchain, self.manifest, self.output, tools="audio")
        self.assertFalse((self.output / "asset-tools.json").exists())
        failed_output = self.root / "failed helpers"
        with patch.object(builder.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, "compilation failed"):
                builder.build(self.toolchain, self.manifest, failed_output, tools="audio")
        self.assertTrue((failed_output / "audio-compile.log").exists())
        self.assertFalse((failed_output / "asset-tools.json").exists())

    def test_tree_fingerprint_captures_names_bytes_and_header_only_scope(self):
        build = self.toolchain / "build"
        before = builder.tree_fingerprint(build, headers_only=True)
        (build / "unrelated.log").write_bytes(b"mutable log")
        self.assertEqual(builder.tree_fingerprint(build, headers_only=True), before)
        (build / "generated.hpp").rename(build / "different.hpp")
        self.assertNotEqual(builder.tree_fingerprint(build, headers_only=True), before)


if __name__ == "__main__":
    unittest.main()
