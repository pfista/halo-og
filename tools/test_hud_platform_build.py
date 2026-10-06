"""Verify every supported native target embeds and links the shared Upres assets.

Exercise the real Ninja generators without downloads, compilation, SDKs or
repository writes. This checks build inclusion; GPU/device behavior is tested
separately by the renderer fixtures and native playtests.
"""
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import android_build, linux_build, windows_build
from tools.ninja_syntax import Writer, serialize_paths

ROOT = Path(__file__).resolve().parents[1]


class RecordingWriter(Writer):
    def __init__(self):
        super().__init__(io.StringIO())
        self.edges = []

    def build(self, outputs, rule, inputs=None, **options):
        def paths(value):
            return [path.replace("\\", "/") for path in serialize_paths(value)]
        self.edges.append({
            "outputs": paths(outputs), "rule": rule,
            "inputs": paths(inputs), "implicit": paths(options.get("implicit")),
        })
        return super().build(outputs, rule, inputs, **options)


class HudPlatformBuildTests(unittest.TestCase):
    def graph(self, target):
        writer = RecordingWriter()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="halo-hud-platform-graph-") as directory:
            dependencies = Path(directory)
            for name in ("llvm-ar", "ld.lld", "GLES3/gl32.h", "GLES2/gl2ext.h", "KHR/khrplatform.h"):
                path = dependencies / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            settings = SimpleNamespace(build_dir=Path("build"), linux_cc="clang",
                port_pgo="off", port_lto="off", port_portable=True,
                android_ndk=dependencies, android_guest_only=target != "android",
                android_guest_llvm_bin=dependencies, android_guest_gl_include=dependencies,
                android_guest_cc="clang", macos=target.startswith("macos"),
                ios=target == "ios", macos_renderer="metal" if target == "macos-metal" else "angle")
            try:
                os.chdir(ROOT)
                if target == "linux":
                    linux_build.generate_linux_build(writer, settings)
                elif target == "windows":
                    with patch.object(windows_build.sys, "platform", "win32"), \
                            patch.object(windows_build, "fetch_sdl"), \
                            patch.object(windows_build, "inline_export_wrapper", side_effect=lambda source: source):
                        windows_build.generate_windows_build(writer, settings)
                else:
                    with patch.object(android_build, "fetch_third_party"):
                        android_build.generate_android_build(writer, settings)
            finally:
                os.chdir(previous)
        return writer.edges

    def test_each_target_embeds_all_authored_sheets_fonts_and_links_shared_renderers(self):
        assets = json.loads((ROOT / "port/assets/hud/layout.json").read_text())["assets"]
        titles = json.loads((ROOT / "port/assets/titles/titles.json").read_text())["assets"]
        expected_inputs = {"tools/embed_assets.py", "port/assets/hud/layout.json",
            "port/assets/titles/titles.json", "port/assets/fonts/fonts.json",
            *("port/assets/hud/" + asset["name"] + ".png" for asset in assets),
            *("port/assets/titles/" + asset["name"] + ".png" for asset in titles),
            "port/assets/fonts/Overpass-750.ttf", "port/assets/fonts/Overpass-900.ttf"}
        self.assertEqual(len(assets), 69)
        self.assertEqual(len(titles), 34)
        for target in ("linux", "windows", "android", "ios", "macos-angle", "macos-metal"):
            with self.subTest(target=target):
                edges = self.graph(target)
                embed = [edge for edge in edges if edge["rule"].endswith("_embed_assets")]
                self.assertEqual(len(embed), 1)
                self.assertEqual(set(embed[0]["implicit"]), expected_inputs)
                generated = embed[0]["outputs"][0]
                compiled = {edge["inputs"][0]: edge["outputs"][0] for edge in edges
                    if edge["rule"] in ("linux_cc", "windows_cc", "android_guest_cc")}
                link = next(edge for edge in edges if edge["rule"] in
                    ("linux_link", "windows_link", "android_guest_link"))
                sources = (generated, "source/interface/ui_widget.c", "port/linux/game/device_settings.c",
                    "port/linux/game/hud_hires_tags.c", "port/linux/src/port_config.c", "port/linux/src/hud_hires.c",
                    "port/linux/src/text_hires.c",
                    "port/linux/src/d3d8_metal.c" if target == "macos-metal" else "port/linux/src/d3d8_gl.c")
                for source in sources:
                    self.assertIn(source, compiled)
                    self.assertIn(compiled[source], link["inputs"])
                if target == "android":
                    staged = next(edge for edge in edges if edge["rule"] == "android_copy" and
                        edge["inputs"] == link["outputs"])
                    apk = next(edge for edge in edges if edge["rule"] == "android_gradle")
                    self.assertIn(staged["outputs"][0], apk["inputs"])
                    for notice in ("Overpass-OFL.txt", "OpenCE-OFL.txt", "Newtown-LICENSE.txt",
                                   "fonts-README.md", "stb-LICENSE.txt"):
                        output = "build/android/assets/Licenses/" + notice
                        self.assertIn(output, apk["inputs"])
                        copied = next(edge for edge in edges if edge["outputs"] == [output])
                        self.assertEqual(copied["rule"], "android_copy")
                        self.assertTrue((ROOT / copied["inputs"][0]).is_file())

    def test_asset_manifest_changes_reconfigure_each_platform_graph(self):
        previous = Path.cwd()
        try:
            os.chdir(ROOT)
            for generator in (linux_build.linux_configure_inputs, windows_build.windows_configure_inputs,
                              android_build.android_configure_inputs):
                with self.subTest(generator=generator.__name__):
                    inputs = generator()
                    self.assertIn(Path("port/assets/hud"), inputs)
                    self.assertIn(Path("port/assets/hud/layout.json"), inputs)
                    self.assertIn(Path("port/assets/titles"), inputs)
                    self.assertIn(Path("port/assets/titles/titles.json"), inputs)
                    self.assertIn(Path("port/assets/fonts"), inputs)
                    self.assertIn(Path("port/assets/fonts/fonts.json"), inputs)
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
