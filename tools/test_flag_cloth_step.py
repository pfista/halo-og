"""The flag's cloth is stepped once a game tick with the time since its last step, at any frame rate.

`flags_step_time` and `flag_drawn_offset` come from production `flags.c`.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ROOT / "source/objects/widgets/flags.c"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <string.h>
typedef unsigned char boolean;
typedef float real;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define long int   /* the game's long is 32 bits */
struct tag_block { long count;void *address; };
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->address)[i])
struct object_marker { struct { real_point3d position; } matrix; };
struct flag_datum_prefix { long object_index;real_point3d first_attachment; };
struct flag_attachment_point { short height_to_next_attachment;short pad2;long unused[4];char marker_name[32]; };
struct flag_definition { struct tag_block attachment_points; };
static long tick;
static long game_time_get(void) { return tick; }
static short markers_found;
static real_point3d drawn_marker;
static short object_get_marker_by_name(long object_index,const char *name,struct object_marker *marker,short maximum) {
    assert(object_index==7 && !strcmp(name,"flag top") && maximum==1);
    if (markers_found) marker->matrix.position=drawn_marker;
    return markers_found;
}
static real flags_pending_time;
static long flags_last_tick=NONE;
'''

HARNESS = r'''
#undef long
int main(void) {
    /* 240 frames a second: one step a tick, with a tick's time. */
    {
        int steps=0;
        double stepped=0.0;

        tick=10;
        for (int frame=0;frame<240;frame++) {
            real time;
            if (frame%8==0) tick++;
            time=flags_step_time(1.0f/240.0f);
            if (time!=0.0f) {
                steps++;stepped+=time;
                if (steps>1) assert(fabsf(time-1.0f/30.0f)<1e-5f);
            }
        }
        assert(steps==30 && fabs(stepped-(1.0-7.0/240.0))<1e-4);
    }
    /* One frame a tick is stepped every frame with that frame's time, as before. */
    flags_pending_time=0.0f;
    for (int frame=0;frame<10;frame++) { tick++;assert(flags_step_time(1.0f/30.0f)==1.0f/30.0f); }
    /* A frame that ran two ticks steps once, with both ticks' time. */
    tick+=2;assert(fabsf(flags_step_time(2.0f/30.0f)-2.0f/30.0f)<1e-6f);
    /* A paused game passes no time and no tick: the cloth is left alone. */
    for (int frame=0;frame<20;frame++) assert(flags_step_time(0.0f)==0.0f);
    tick++;assert(flags_step_time(1.0f/120.0f)==1.0f/120.0f);

    /* The drawn cloth moves by as much as its first marker has moved since the step. */
    {
        struct flag_attachment_point points[2];
        struct flag_definition definition={{2,points}};
        struct flag_datum_prefix flag={7,{10.0f,20.0f,30.0f}};
        real_vector3d offset;

        memset(points,0,sizeof(points));
        strcpy(points[0].marker_name,"flag top");strcpy(points[1].marker_name,"flag bottom");
        markers_found=1;drawn_marker=flag.first_attachment;
        flag_drawn_offset(&flag,&definition,&offset);
        assert(offset.i==0.0f && offset.j==0.0f && offset.k==0.0f);
        drawn_marker.x=10.25f;drawn_marker.y=19.5f;drawn_marker.z=30.125f;
        flag_drawn_offset(&flag,&definition,&offset);
        assert(offset.i==0.25f && offset.j==-0.5f && offset.k==0.125f);
        /* No marker, or no attachment points: it is drawn where it was stepped. */
        markers_found=0;
        flag_drawn_offset(&flag,&definition,&offset);
        assert(offset.i==0.0f && offset.j==0.0f && offset.k==0.0f);
        definition.attachment_points.count=0;markers_found=1;
        offset.i=9.0f;flag_drawn_offset(&flag,&definition,&offset);
        assert(offset.i==0.0f && offset.j==0.0f && offset.k==0.0f);
    }
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class FlagClothStepTests(unittest.TestCase):
    def test_the_cloth_steps_once_a_tick_and_follows_its_pole(self):
        source = FLAGS.read_text()
        production = "\n".join(function(source, signature) for signature in (
            "static real flags_step_time(",
            "static void flag_drawn_offset(",
        ))
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-flag-cloth-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "flag"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=undefined", str(harness), "-lm", "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_update_and_the_draw_use_them(self):
        source = FLAGS.read_text()
        update = function(source, "void flags_update(")
        self.assertIn("delta = flags_step_time(delta);", update)
        self.assertLess(update.index("flags_step_time"), update.index("updates_since_last_render++"))
        draw = function(source, "void flag_render_proper(")
        self.assertIn("flag_drawn_offset(flag, definition, &drawn_offset);", draw)
        self.assertIn("point->position.x + drawn_offset.i", draw)
        self.assertIn("centroid.x += drawn_offset.i;", draw)
        self.assertIn("flags_last_tick = NONE;", function(source, "void flags_initialize_for_new_map("))


if __name__ == "__main__":
    unittest.main()
