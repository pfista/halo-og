"""Compile the production direct-camera path for desktop and mobile defines.

The fixture uses the real observer result, camera selection and up-vector helper.
Interpolation is a controlled dependency: these tests establish that optional
current aim reaches the Mac camera without changing other camera state, not a
physical input-to-display latency measurement.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_runtime_ui_tags import c_block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef float real;
typedef unsigned short word;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
#define MAXIMUM_LOCAL_PLAYERS 4
#define NONE (-1)
#define TRUE 1
enum { _director_perspective_first_person, _director_perspective_third_person };
/* STRUCTURES */
struct object_datum { struct { long parent_object_index; } object; };
static struct object_datum unit;
static int enabled, config_reads, inhibited, cinematic, perspective;
static int facing_reads, blend_reads, bounds_reads;
static long unit_index;
static real_vector3d facing;
static int config_boolean(char const *key) {
    assert(!strcmp(key,"display.direct_camera")); config_reads++; return enabled;
}
static int director_get_perspective(short index) {
    assert(index>=0 && index<MAXIMUM_LOCAL_PLAYERS); return perspective;
}
static int director_inhibited_facing(short index) {
    assert(index>=0 && index<MAXIMUM_LOCAL_PLAYERS); return inhibited;
}
static int cinematic_in_progress(void) { return cinematic; }
static long player_control_get_unit_index(short index) {
    assert(index>=0 && index<MAXIMUM_LOCAL_PLAYERS); return unit_index;
}
static struct object_datum *object_get(long index) { assert(index==123); return &unit; }
static void player_control_get_facing_direction(short index,real_vector3d *out) {
    assert(index>=0 && index<MAXIMUM_LOCAL_PLAYERS); facing_reads++; *out=facing;
}
static void unit_clip_to_aiming_bounds(long index,real_vector3d *direction,int aiming) {
    assert(index==123 && aiming==TRUE);
    /* The fixture's facing vectors are already inside the unit's bounds. */
    assert(fabsf(direction->i*direction->i+direction->j*direction->j+direction->k*direction->k-1)<0.00001f);
    bounds_reads++;
}
static real normalize3d(real_vector3d *v) {
    real length=sqrtf(v->i*v->i+v->j*v->j+v->k*v->k);
    if(length) { v->i/=length; v->j/=length; v->k/=length; }
    return length;
}
static void cross_product3d(real_vector3d const *a,real_vector3d const *b,real_vector3d *out) {
    *out=(real_vector3d){a->j*b->k-a->k*b->j,a->k*b->i-a->i*b->k,a->i*b->j-a->j*b->i};
}
static struct observer_result const *render_interpolation_blended_camera(
    short index,struct observer_result const *observer) {
    assert(index>=0 && index<MAXIMUM_LOCAL_PLAYERS); blend_reads++; return observer;
}
/* PRODUCTION */
'''

HARNESS = r'''
static void reset_view(void) {
    inhibited=cinematic=0; perspective=_director_perspective_first_person;
    unit_index=123; unit.object.parent_object_index=NONE;
}
static void same_vector(real_vector3d const *a,real_vector3d const *b) {
    assert(fabsf(a->i-b->i)<0.00001f && fabsf(a->j-b->j)<0.00001f && fabsf(a->k-b->k)<0.00001f);
}
static void unchanged(struct observer_result const *camera) {
    int reads=facing_reads, clips=bounds_reads;
    assert(render_interpolation_camera(0,camera)==camera);
    assert(facing_reads==reads && bounds_reads==clips);
}
int main(int argc,char **argv) {
    assert(argc==3); enabled=atoi(argv[1]); int desktop=atoi(argv[2]);
    struct observer_result camera={0}, original;
    camera.position=(real_point3d){11,22,33}; camera.location.leaf_index=99;
    camera.location.cluster_index=7; camera.location.bonus=42;
    camera.velocity=(real_vector3d){1,2,3}; camera.forward=(real_vector3d){1,0,0};
    camera.up=(real_vector3d){0,0,1}; camera.field_of_view=1.2f;
    original=camera; reset_view(); facing=(real_vector3d){0,.6f,.8f};
    struct observer_result const *out=render_interpolation_camera(0,&camera);
    if(desktop && enabled) {
        assert(out!=&camera); same_vector(&out->forward,&facing);
        real_vector3d expected_up={0,-.8f,.6f}; same_vector(&out->up,&expected_up);
        assert(out->position.x==11 && out->position.y==22 && out->position.z==33);
        assert(out->location.leaf_index==99 && out->location.cluster_index==7 && out->location.bonus==42);
        same_vector(&out->velocity,&camera.velocity); assert(out->field_of_view==camera.field_of_view);
        /* Aim changes between ticks must be visible on the next camera call. */
        facing=(real_vector3d){0,1,0}; out=render_interpolation_camera(0,&camera);
        same_vector(&out->forward,&facing);
        expected_up=(real_vector3d){0,0,1}; same_vector(&out->up,&expected_up);
        assert(facing_reads==2 && bounds_reads==2);
    } else {
        assert(out==&camera && facing_reads==0 && bounds_reads==0);
    }
    assert(!memcmp(&camera,&original,sizeof(camera)));
    reset_view(); unit.object.parent_object_index=456; unchanged(&camera); /* vehicle */
    reset_view(); cinematic=1; unchanged(&camera);
    reset_view(); inhibited=1; unchanged(&camera);
    reset_view(); perspective=_director_perspective_third_person; unchanged(&camera);
    reset_view(); unit_index=NONE; unchanged(&camera);
    reset_view(); unchanged(NULL);
    int blends=blend_reads;
    assert(render_interpolation_camera(-1,&camera)==&camera);
    assert(render_interpolation_camera(MAXIMUM_LOCAL_PLAYERS,&camera)==&camera);
    assert(blend_reads==blends);
    assert(config_reads==(desktop ? 1 : 0));
    puts("direct camera passed");
    return 0;
}
'''


class DirectCameraTests(unittest.TestCase):
    def test_platform_selection_and_first_person_camera(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            self.fail("A C compiler (clang or cc) is required")
        interpolation = (ROOT / "port/linux/game/render_interpolation.c").read_text()
        start = interpolation.index("static struct observer_result direct_cameras[")
        end = interpolation.index("\nstatic struct observer_result const *render_interpolation_blended_camera(\n",
                                  interpolation.index("\nstruct observer_result const *render_interpolation_camera(\n", start))
        structures = "\n".join((
            c_block((ROOT / "source/objects/objects.h").read_text(), "struct location\n{") + ";",
            c_block((ROOT / "source/camera/observer.h").read_text(), "struct observer_result\n{") + ";",
        ))
        functions = (c_block((ROOT / "source/camera/observer.c").read_text(), "void observer_up_from_forward(\n")
                     + "\n" + interpolation[start:end])
        source = PREFIX.replace("/* STRUCTURES */", structures).replace("/* PRODUCTION */", functions) + HARNESS
        platforms = (
            ("linux", (), True),
            ("android", ("HALO_ANDROID",), False),
            ("macos", ("HALO_ANDROID", "HALO_MACOS"), True),
            ("ios", ("HALO_ANDROID", "HALO_MACOS", "HALO_IOS"), False),
        )
        with tempfile.TemporaryDirectory(prefix="halo-direct-camera-") as temporary:
            directory = Path(temporary)
            fixture = directory / "fixture.c"
            fixture.write_text(source)
            for name, defines, desktop in platforms:
                with self.subTest(platform=name):
                    output = directory / (name + (".exe" if sys.platform == "win32" else ""))
                    command = [compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                               "-Wno-unused-function", "-Wno-unused-variable"]
                    if sys.platform != "win32":
                        command.append("-fsanitize=address,undefined")
                    command += ["-D" + define for define in defines]
                    command += [str(fixture), "-o", str(output)]
                    if sys.platform != "win32":
                        command.append("-lm")
                    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    # Production caches this setting; each choice needs a fresh process.
                    for enabled in (False, True):
                        with self.subTest(enabled=enabled):
                            tested = subprocess.run([str(output), str(int(enabled)), str(int(desktop))],
                                                    capture_output=True, text=True, timeout=10)
                            self.assertEqual(tested.returncode, 0, tested.stderr)
                            self.assertIn("direct camera passed", tested.stdout)


if __name__ == "__main__":
    unittest.main()
