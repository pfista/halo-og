"""Detail Distance: the multiplier follows the picture and never changes 480 lines."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/game/detail_distance.c"

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <string.h>
static long setting;
static float lines_per_line;
static unsigned lookups;
long config_integer(const char *name) { assert(!strcmp(name,"display.detail_distance"));lookups++;return setting; }
float halo_screen_pixel_scale(void) { return lines_per_line; }
void halo_detail_distance_refresh(void);
float halo_detail_distance(void);
static float with(long chosen,float scale) {
    setting=chosen;lines_per_line=scale;halo_detail_distance_refresh();return halo_detail_distance();
}
int main(void) {
    /* Before any frame the Xbox's distances apply. */
    assert(halo_detail_distance()==1.0f && !lookups);
    /* Auto follows the lines drawn for each of the Xbox's 480, up to three times. */
    assert(with(0,1.0f)==1.0f);            /* 480 lines: exactly the Xbox's */
    assert(with(0,1.5f)==1.5f);            /* 720 */
    assert(with(0,2.25f)==2.25f);          /* 1080 */
    assert(with(0,3.0f)==3.0f);            /* 1440 */
    assert(with(0,4.5f)==3.0f);            /* 2160 */
    assert(with(0,0.5f)==1.0f && with(0,0.0f)==1.0f && with(0,-2.0f)==1.0f && with(0,NAN)==1.0f);
    /* Fixed choices ignore the resolution. */
    assert(with(1,4.5f)==1.0f && with(2,1.0f)==2.0f && with(3,1.0f)==3.0f);
    /* Anything else is Auto. */
    assert(with(4,2.0f)==2.0f && with(-1,2.0f)==2.0f);
    /* The setting is read when a frame begins, not for every object and particle. */
    lookups=0;halo_detail_distance_refresh();
    for(int i=0;i<1000;i++) (void)halo_detail_distance();
    assert(lookups==1);
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class DetailDistanceTests(unittest.TestCase):
    def test_multiplier_follows_resolution_and_keeps_480_lines_original(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-detail-distance-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(HARNESS)
            executable = Path(folder) / "detail"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror",
                                       str(harness), str(SOURCE), "-lm", "-o", str(executable)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
