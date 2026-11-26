"""A lightning bolt keeps one shape for a whole game tick in each window, however many frames are drawn.

The seed bookkeeping comes from production `lightning.c`.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
LIGHTNING = ROOT / "source/objects/widgets/lightning.c"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <string.h>
typedef unsigned char boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define long int   /* the game's long is 32 bits */
#define csmemset memset
#define DATUM_INDEX_TO_ABSOLUTE_INDEX(index) ((long)((index)&0xFFFF))
static struct { short window_index; } render;
static unsigned long local_seed;
static long tick;
static unsigned long *get_global_local_random_seed_address(void) { return &local_seed; }
static long game_time_get(void) { return tick; }
enum { MAXIMUM_LIGHTNINGS=256,MAXIMUM_LIGHTNING_WINDOWS=4 };
'''

HARNESS = r'''
/* Draws a bolt: takes three numbers from the seed, as a bolt's points do, and returns their sum as its shape. */
static unsigned long draw(long lightning_index) {
    unsigned long found,shape=0;
    boolean redraw=lightning_tick_seed_begin(lightning_index,&found);

    for (int i=0;i<3;i++) { local_seed=local_seed*1664525u+1013904223u;shape+=local_seed>>8; }
    if (redraw) local_seed=found;
    return shape;
}
int main(void) {
    const long bolt=0x00010005,reused=0x00020005,other=0x00010006;
    unsigned long first,second,seed_after;

    lightning_tick_seeds_forget(NONE);
    local_seed=12345;tick=100;render.window_index=0;

    /* Frames of one tick draw the same bolt, and the later ones leave the seed as they found it. */
    first=draw(bolt);
    seed_after=local_seed;
    local_seed=777;                       /* other effects drew numbers in between */
    assert(draw(bolt)==first && local_seed==777);
    local_seed=4242;
    assert(draw(bolt)==first && local_seed==4242);
    (void)seed_after;

    /* The next tick is a new shape. */
    tick=101;local_seed=999;
    second=draw(bolt);
    assert(second!=first);
    assert(draw(bolt)==second);

    /* Each window has its own bolt, held the same way. */
    render.window_index=1;local_seed=31337;
    {
        unsigned long window_one=draw(bolt);
        assert(window_one!=second);
        local_seed=5;assert(draw(bolt)==window_one);
        render.window_index=0;local_seed=6;assert(draw(bolt)==second);
    }

    /* Another lightning is separate. */
    local_seed=2024;
    assert(draw(other)!=second);

    /* A new lightning in a slot used before starts with its own shape, in the same tick too. */
    lightning_tick_seeds_forget(reused);
    local_seed=8080;
    assert(draw(reused)!=second);
    /* Without the forget, the slot's old record still belongs to the old lightning and is not replayed. */
    local_seed=9090;
    {
        unsigned long fresh=draw(bolt);   /* the record is now `reused`'s */
        local_seed=1;assert(draw(bolt)==fresh);
    }

    /* A new map forgets everything. */
    lightning_tick_seeds_forget(NONE);
    local_seed=55;
    {
        unsigned long after_map=draw(bolt);
        local_seed=56;assert(draw(bolt)==after_map);
    }

    /* A window or a slot outside the table is drawn fresh each frame and never written. */
    render.window_index=7;local_seed=10;
    {
        unsigned long a=draw(bolt);
        assert(draw(bolt)!=a);
    }
    render.window_index=-1;local_seed=10;(void)draw(bolt);
    render.window_index=0;local_seed=10;(void)draw(0x00010000|300);
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class LightningTickShapeTests(unittest.TestCase):
    def test_a_bolt_keeps_its_shape_for_a_tick(self):
        source = LIGHTNING.read_text()
        production = block(source[source.index("struct lightning_tick_seed\n"):], "struct lightning_tick_seed\n") + ";\n"
        production += "static struct lightning_tick_seed lightning_tick_seeds[MAXIMUM_LIGHTNINGS][MAXIMUM_LIGHTNING_WINDOWS];\n"
        production += "\n".join(function(source, signature) for signature in (
            "static void lightning_tick_seeds_forget(",
            "static boolean lightning_tick_seed_begin(",
        ))
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-lightning-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "lightning"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=undefined", str(harness), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_draw_restores_the_seed_and_slots_are_forgotten(self):
        source = LIGHTNING.read_text()
        submit = function(source, "void lightning_submit(")
        self.assertIn("lightning_tick_seed_begin(widget_index, &found_seed)", submit)
        self.assertIn("*get_global_local_random_seed_address() = found_seed;", submit)
        self.assertIn("lightning_tick_seeds_forget(lightning_index);", function(source, "long lightning_new("))
        self.assertIn("lightning_tick_seeds_forget(NONE);", function(source, "void lightnings_initialize_for_new_map("))


if __name__ == "__main__":
    unittest.main()
