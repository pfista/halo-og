#!/usr/bin/env python3
"""Exercise native HUD RGBA mip reduction without a game or graphics context."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MetalHudMipmapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang"):
            raise unittest.SkipTest("clang required")
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-hud-mip-")
        folder = Path(cls.directory.name)
        source = folder / "fixture.c"
        source.write_text(
            '#include "metal_hud_mipmap.h"\n'
            'void reduce(unsigned char *p, uint32_t w, uint32_t h) {\n'
            '    metal_hud_mip_reduce_rgba(p, w, h);\n'
            '}\n'
        )
        library = folder / "fixture.dylib"
        subprocess.run([
            "clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-shared", "-fPIC", "-I", str(ROOT / "port/linux/src"),
            str(source), "-o", str(library),
        ], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.reduce.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32, ctypes.c_uint32]
        cls.library.reduce.restype = None

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def reduce(self, pixels, width, height):
        storage = (ctypes.c_ubyte * len(pixels))(*pixels)
        self.library.reduce(storage, width, height)
        size = max(1, width // 2) * max(1, height // 2) * 4
        return list(storage[:size])

    def test_coverage_and_alpha_are_independent_channels(self):
        # Green is meter coverage, blue/alpha encode fill; never premultiply
        # one into the other during mip generation.
        pixels = [0, 0, 40, 255, 80, 255, 0, 0,
                  160, 255, 120, 0, 240, 0, 240, 255]
        self.assertEqual(self.reduce(pixels, 2, 2), [120, 128, 100, 128])

    def test_rectangular_chain_can_reduce_in_place(self):
        pixels = sum(([value, value, value, value] for value in
                      [0, 4, 8, 12, 16, 20, 24, 28]), [])
        first = self.reduce(pixels, 4, 2)
        self.assertEqual(first, [10] * 4 + [18] * 4)
        self.assertEqual(self.reduce(first, 2, 1), [14] * 4)

    def test_single_texel_axes_do_not_sample_past_the_image(self):
        pixels = [20, 40, 80, 160, 40, 80, 160, 240]
        expected = [30, 60, 120, 200]
        self.assertEqual(self.reduce(pixels, 1, 2), expected)
        self.assertEqual(self.reduce(pixels, 2, 1), expected)
        self.assertEqual(self.reduce(expected, 1, 1), expected)


if __name__ == "__main__":
    unittest.main()
