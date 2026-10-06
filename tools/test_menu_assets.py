"""Validate the optional title/font imports without game maps or image tools."""
import ast
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools import ci_build

ROOT = Path(__file__).resolve().parents[1]


class MenuAssetManifestTests(unittest.TestCase):
    def test_title_manifest_preserves_the_authored_english_words_and_original_bitmap_sizes(self):
        # Read only the literal title inventory: rebuilding pictures would need
        # an original UI map and optional Pillow/NumPy/SciPy dependencies.
        tree = ast.parse((ROOT / "tools/title_assets.py").read_text())
        inventory = [node for node in tree.body if isinstance(node, ast.Assign) and
            any(isinstance(target, ast.Name) and target.id in ("MENU", "TEXTS") for target in node.targets)]
        namespace = {}
        exec(compile(ast.Module(body=inventory, type_ignores=[]), "title inventory", "exec"), namespace)
        expected = {(tag, index): text for tag, texts in namespace["TEXTS"].items()
                    for index, text in enumerate(texts)}
        manifest = json.loads((ROOT / "port/assets/titles/titles.json").read_text())
        assets = manifest["assets"]
        self.assertEqual(len(assets), 34)
        self.assertEqual(manifest["font"], "OpenCE-Regular.ttf")
        self.assertEqual({(asset["tag"], asset["bitmap"]): asset["text"] for asset in assets}, expected)
        self.assertEqual(len({asset["name"] for asset in assets}), 34)
        self.assertEqual(Counter((asset["width"], asset["height"]) for asset in assets),
                         {(512, 64): 25, (256, 64): 8, (1024, 64): 1})
        self.assertEqual(Counter(asset["scale"] for asset in assets), {4: 33, 2: 1})
        for asset in assets:
            with self.subTest(asset=asset["name"]):
                self.assertGreater(asset["crc"], 0)
                self.assertLessEqual(asset["crc"], 0xffffffff)
                self.assertNotIn("postgame", asset["tag"])
                self.assertEqual(len(asset["lefts"]), len(asset["text"].replace(" ", "")))
                self.assertTrue((ROOT / "port/assets/titles" / (asset["name"] + ".png")).is_file())
                self.assertLessEqual(max(asset["width"], asset["height"]) * asset["scale"], 2048)
        self.assertIn("SYSTEM LINK GAMES", expected.values())
        self.assertIn("CAMPAIGN", expected.values())
        self.assertNotIn("OPEN CE", expected.values())

    def test_font_manifest_uses_the_reviewed_overpass_weights_only(self):
        fonts = json.loads((ROOT / "port/assets/fonts/fonts.json").read_text())["fonts"]
        self.assertEqual({font["tag"]: font["file"] for font in fonts}, {
            "ui\\large_ui": "Overpass-900.ttf", "ui\\interstate": "Overpass-900.ttf",
            "ui\\small_ui": "Overpass-750.ttf"})
        for font in fonts:
            self.assertTrue((ROOT / "port/assets/fonts" / font["file"]).is_file())

    def test_local_xbox_ui_map_matches_every_title_bitmap_crc_and_dimensions(self):
        map_path = ROOT / "assets/maps/ui.map"
        if not map_path.is_file():
            self.skipTest("An original English Xbox UI map is needed for the source bitmap oracle")
        try:
            from tools.hud_assets import FORMATS, XboxMap, level0_size
        except ImportError:
            self.skipTest("Pillow and NumPy are needed to read the source Xbox map")
        xbox_map = XboxMap(map_path)
        assets = json.loads((ROOT / "port/assets/titles/titles.json").read_text())["assets"]
        for asset in assets:
            with self.subTest(asset=asset["name"]):
                bitmap = xbox_map.bitmap_group(asset["tag"])["bitmaps"][asset["bitmap"]]
                self.assertEqual((bitmap["width"], bitmap["height"], FORMATS[bitmap["format"]]),
                                 (asset["width"], asset["height"], asset["format"]))
                self.assertEqual(zlib.crc32(bitmap["pixels"][:level0_size(bitmap)]), asset["crc"])

    def test_ci_distribution_carries_the_font_licenses_and_provenance(self):
        notices = {
            "port/assets/fonts/Overpass-OFL.txt": "Overpass-OFL.txt",
            "port/assets/fonts/OpenCE-OFL.txt": "OpenCE-OFL.txt",
            "port/assets/fonts/Newtown-LICENSE.txt": "Newtown-LICENSE.txt",
            "port/assets/fonts/README.md": "fonts-README.md",
            "port/third_party/stb/LICENSE": "stb-LICENSE.txt",
        }
        with tempfile.TemporaryDirectory(prefix="halo-menu-license-package-") as directory:
            fixture = Path(directory)
            for source in (*notices, "build/linux/halo", "build/windows/halo.exe", "build/windows/SDL3.dll",
                           ci_build.APKS["debug"], "port/third_party/extract-xiso/LICENSE.TXT",
                           "port/third_party/miniupnpc/LICENSE", "port/third_party/mbedtls/LICENSE",
                           "port/third_party/expat/COPYING", "port/assets/network/brokers.txt",
                           "build/windows/halo.pdb"):
                path = fixture / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / source).read_bytes() if source in notices else b"fixture")
            for platform in ("linux", "windows", "android"):
                with self.subTest(platform=platform):
                    with patch.object(ci_build, "ROOT", fixture), patch.object(ci_build, "run"), \
                            patch.object(ci_build.release_discovery, "required_ci_source_identity", return_value=None), \
                            patch.object(ci_build.sys, "argv", ["ci_build.py", platform, "debug"]), \
                            patch.dict(ci_build.os.environ):
                        self.assertEqual(ci_build.main(), 0)
                    dist = fixture / f"dist/halo-{platform}-debug"
                    for source, name in notices.items():
                        with self.subTest(notice=name):
                            self.assertEqual((dist / name).read_bytes(), (ROOT / source).read_bytes())


if __name__ == "__main__":
    unittest.main()
