"""A new particle is first drawn a tick old, as on the Xbox, however small the steps it is moved by.

`particle_drawn` comes from production `particles.c`.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
PARTICLES = ROOT / "source/effects/particles.c"
RENDER = ROOT / "source/render/render_particles.c"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <math.h>
typedef unsigned char boolean;
typedef float real;
#define TRUE 1
#define FALSE 0
#define long int   /* the game's long is 32 bits */
#define TICKS_PER_SECOND 30
#define FLAG(n) (1u<<(n))
#define TEST_FLAG(f,n) (((f)&FLAG(n))!=0)
enum { _particle_definition_animate_once_per_frame_bit=3 };
struct particle_datum { long definition_index;real age,frame_time; };
struct particle_definition { unsigned long flags; };
static struct particle_datum particles[4];
static struct particle_definition definitions[2]={{0},{FLAG(_particle_definition_animate_once_per_frame_bit)}};
#define particle_get(index) (&particles[index])
#define particle_definition_get(index) (&definitions[index])
static boolean double_speed;
static boolean game_players_are_double_speed(void) { return double_speed; }
static real particles_last_step=1.0f/TICKS_PER_SECOND;
'''

HARNESS = r'''
#undef long
static const real tick=1.0f/30.0f;
static boolean drawn(real step,real age,int definition,real frame_time) {
    particles_last_step=step;
    particles[0].definition_index=definition;particles[0].age=age;particles[0].frame_time=frame_time;
    return particle_drawn(0);
}
int main(void) {
    /* One frame a tick: everything is drawn, as on the Xbox, whatever its age. */
    assert(drawn(tick,0.0f,0,-1.0f) && drawn(tick,tick,0,0.0f) && drawn(tick,5.0f,0,0.0f));
    assert(drawn(tick,0.0f,1,-1.0f) && drawn(tick,tick,1,0.0f));
    assert(drawn(tick*1.0005f,tick*1.0005f,0,0.0f) && drawn(tick*0.9995f,0.0f,0,-1.0f));

    /* Eight frames a tick: hidden until a tick old, so one that dies within its tick is never drawn. */
    {
        real step=tick/8.0f,age=0.0f;
        int first=0;
        for (int frame=1;frame<=16;frame++) {
            age+=step;
            if (drawn(step,age,0,0.0f) && !first) first=frame;
        }
        assert(first==8);
        assert(!drawn(step,0.0f,0,-1.0f) && !drawn(step,tick*0.99f,0,0.0f));
        assert(drawn(step,tick*0.9995f,0,0.0f) && drawn(step,tick,0,0.0f) && drawn(step,3.0f,0,0.0f));
    }
    /* A frame that ran two ticks: a particle made in them is two ticks old and drawn. */
    assert(drawn(2.0f*tick,2.0f*tick,0,0.0f) && !drawn(2.0f*tick,0.0f,0,-1.0f));

    /* A particle that animates once a frame is drawn from its first step, not by its age. */
    assert(!drawn(tick/4.0f,tick*0.75f,1,-1.0f) && !drawn(tick/4.0f,3.0f,1,-1.0f));
    assert(drawn(tick/4.0f,tick*0.25f,1,0.0f) && drawn(tick/4.0f,3.0f,1,0.0f));

    /* Players at double speed: a tick of the particles' time is half as long. */
    double_speed=TRUE;
    assert(drawn(tick*0.5f,0.0f,0,-1.0f) && drawn(tick*0.5f,tick*0.5f,0,0.0f));
    assert(!drawn(tick/8.0f,tick*0.4f,0,0.0f) && drawn(tick/8.0f,tick*0.5f,0,0.0f));
    /* (a whole tick's step is then two of theirs: not the Xbox's frame) */
    assert(!drawn(tick,0.0f,0,-1.0f) && drawn(tick,tick,0,0.0f));
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class ParticleFirstDrawnTests(unittest.TestCase):
    def test_a_particle_is_first_drawn_a_tick_old(self):
        production = function(PARTICLES.read_text(), "boolean particle_drawn(")
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-particle-drawn-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "particle"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=undefined", str(harness), "-lm", "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_update_keeps_its_step_and_the_draw_asks(self):
        particles = PARTICLES.read_text()
        update = function(particles, "void particles_update(")
        self.assertIn("if (dt != 0.0f)\n\t\tparticles_last_step = dt;", update)
        draw = function(RENDER.read_text(), "void render_particles(")
        self.assertLess(draw.index("particle_drawn(particle_index)"), draw.index("render_location_visible(&particle->location)"))


if __name__ == "__main__":
    unittest.main()
