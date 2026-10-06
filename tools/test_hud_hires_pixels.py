"""Check the shared HUD decoder with bundled zlib on any host.

Pillow is an independent oracle for the 69 embedded PNGs. No system zlib,
DLL exports, game data or graphics context is needed by this fixture.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#define __HALO_LINUX_PLATFORM_H
#define HALO_MACOS_NATIVE_METAL 1
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char Byte;
static int enabled = 1, lookups;
void platform_log(const char *format, ...) { (void)format; }
int config_boolean(const char *name) {
    assert(!strcmp(name, "display.high_res_hud")); return enabled;
}
long hud_hires_asset_at(unsigned long address, long width, long height) {
    (void)address; (void)width; (void)height; lookups++; return 0;
}
#include "hud_hires.c"
int main(int argc, char **argv) {
    assert(argc == 3);
    if (!strcmp(argv[1], "decode")) {
        for (long asset = 0; asset < hud_hires_asset_count(); asset++) {
            unsigned long width, height;
            unsigned char *pixels = hud_hires_override_pixels(asset, &width, &height);
            assert(pixels);
            char path[4096];
            assert(snprintf(path, sizeof(path), "%s/%ld.rgba", argv[2], asset) > 0);
            FILE *file = fopen(path, "wb"); assert(file);
            assert(fwrite(pixels, 1, width * height * 4, file) == width * height * 4);
            assert(!fclose(file)); free(pixels);
            printf("%ld %lu %lu\n", asset, width, height);
        }
    } else if (!strcmp(argv[1], "invalid")) {
        const long invalid[] = {-1, (long)hud_hires_embedded_count, 1L << 30};
        for (unsigned i = 0; i < sizeof(invalid)/sizeof(invalid[0]); i++) {
            unsigned long width = 123, height = 456;
            assert(!hud_hires_override_pixels(invalid[i], &width, &height));
            assert(!width && !height);
        }
        unsigned long dimension = 123;
        assert(!hud_hires_override_pixels(0, NULL, &dimension) && !dimension);
        dimension = 123;
        assert(!hud_hires_override_pixels(0, &dimension, NULL) && !dimension);
    } else {
        assert(!strcmp(argv[1], "original") || !strcmp(argv[1], "modified"));
        enabled = !strcmp(argv[1], "modified");
        /* An empty modified level has CRC zero, unlike the authored bitmap.
         * Avoid pointer-to-32-bit-long conversion on Windows hosts. */
        assert(hud_hires_embedded[0].crc != 0);
        assert(hud_hires_override_find(0, 128, 128, 0) == -1);
        assert(lookups == enabled);
    }
    return 0;
}
'''


@unittest.skipUnless(Image and shutil.which("clang"), "Pillow and clang required")
class HudHiresPixelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-hud-pixels-")
        folder = Path(cls.directory.name)
        embedded = folder / "embedded.c"
        subprocess.run([sys.executable, str(ROOT / "tools/embed_assets.py"), str(embedded)], check=True)
        wrapper = folder / "decoder.c"
        wrapper.write_text(HARNESS)
        # Only the game's allocator boundary is supplied by the host. Inflate,
        # PNG filters and checksums all remain production implementations.
        shim = folder / "cseries.h"
        shim.write_text('#ifndef HUD_TEST_CSERIES_H\n#define HUD_TEST_CSERIES_H\n'
                        '#include <stdlib.h>\ntypedef unsigned char Byte;\n#define TRUE 1\n'
                        '#define debug_malloc(size,clear,file,line) calloc(1,size)\n'
                        '#define debug_free(ptr,file,line) free(ptr)\n#endif\n')
        cls.executable = folder / ("decoder.exe" if sys.platform == "win32" else "decoder")
        # Exercise the game's old inflate and its exact Z_BUF_ERROR behavior.
        sources = [ROOT / "source/memory/zlib" / (name + ".c") for name in (
            "uncompr", "inflate", "infblock", "infcodes", "inffast", "inftrees",
            "infutil", "adler32", "crc32", "zutil")]
        command = ["clang", "-std=c11", "-O2", "-Wno-deprecated-non-prototype",
                   "-include", str(shim), "-I", str(folder),
                   "-I", str(ROOT / "port/linux/src"), "-I", str(ROOT / "source"),
                   str(wrapper), str(embedded), *map(str, sources), "-o", str(cls.executable)]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.assets = json.loads((ROOT / "port/assets/hud/layout.json").read_text())["assets"]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_fixture(self, mode):
        result = subprocess.run([str(self.executable), mode, self.directory.name],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_all_embedded_redraws_decode_to_exact_rgba(self):
        decoded = [tuple(map(int, line.split())) for line in self.run_fixture("decode").splitlines()]
        self.assertEqual(len(decoded), len(self.assets))
        for index, width, height in decoded:
            asset = self.assets[index]
            with self.subTest(asset=asset["name"]):
                with Image.open(ROOT / "port/assets/hud" / (asset["name"] + ".png")) as image:
                    self.assertEqual((width, height), image.size)
                    self.assertEqual((Path(self.directory.name) / f"{index}.rgba").read_bytes(),
                                     image.convert("RGBA").tobytes())

    def test_invalid_asset_and_missing_dimensions_are_rejected(self):
        self.run_fixture("invalid")

    def test_modified_bitmap_does_not_select_redraw(self):
        self.run_fixture("modified")

    def test_original_mode_does_not_look_up_replacements(self):
        self.run_fixture("original")


if __name__ == "__main__":
    unittest.main()
