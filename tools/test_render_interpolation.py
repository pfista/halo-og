#!/usr/bin/env python3
"""Exercise production interpolation against a deterministic 30 Hz world.

The entire production translation unit is compiled with its game/header
dependencies replaced by a small source-only fixture. The real tick snapshot,
frame policy, camera, object, first-person and shader-time functions all run.
C long is normalized to the guest's 32-bit ABI; this is a CPU fixture, not an
actual ILP32 executable or a cinematic/gameplay/GPU parity test.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/game/render_interpolation.c"

PREFIX = r'''
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte, boolean;
typedef float real;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
typedef struct real_matrix4x3 {
    real scale;
    real_vector3d forward,left,up;
    real_point3d position;
} real_matrix4x3;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MAXIMUM_OBJECTS_PER_MAP 4
#define MAXIMUM_LOCAL_PLAYERS 2
#define TICKS_PER_SECOND 30
#define DATUM_INDEX_TO_ABSOLUTE_INDEX(index) ((index)&0xffff)
struct observer_result {
    real_point3d position;
    real_vector3d forward,up;
    real field_of_view;
};
struct render_camera { real_point3d position; real_vector3d forward,up; };
struct object_datum {
    struct {
        struct { short size; } node_matrices;
        long parent_object_index,first_child_object_index,next_object_index;
    } object;
};
struct object_iterator { long index; boolean visited; };
enum { _object_mask_all=0xffff, _director_perspective_first_person=0,
       _director_perspective_scripted=2 };
static boolean enabled=TRUE, object_present=TRUE, direct_enabled;
static boolean cinematic;
static real clock_fraction;
static unsigned long world_tick;
static struct object_datum fixture_object;
static real_matrix4x3 raw_nodes[2];
static const real_vector3d zero_vector;
static const real_vector3d *global_zero_vector3d=&zero_vector;
static int halo_interpolation_enabled(void) { return enabled; }
static real game_time_get_tick_fraction(void) { return clock_fraction; }
static int config_boolean(const char *name) {
    assert(!strcmp(name,"display.direct_camera")); return direct_enabled;
}
unsigned long config_changes(void) { return direct_enabled; }
static int director_get_perspective(short index) {
    assert(index==0); return cinematic ? _director_perspective_scripted : _director_perspective_first_person;
}
static boolean director_inhibited_facing(short index) { assert(index==0); return FALSE; }
static boolean cinematic_in_progress(void) { return cinematic; }
static long player_control_get_unit_index(short index) { (void)index; return 0; }
static void player_control_get_facing_direction(short index,real_vector3d *forward) {
    assert(index==0); *forward=(real_vector3d){0,1,0};
}
static void observer_up_from_forward(const real_vector3d *forward,real_vector3d *up) {
    (void)forward; *up=(real_vector3d){0,0,1};
}
static struct object_datum *object_get(long index) { assert(index==0); return &fixture_object; }
static void *object_header_block_get(long index,const void *header) {
    assert(index==0 && header==&fixture_object.object.node_matrices); return raw_nodes;
}
static void object_iterator_new(struct object_iterator *iterator,int mask,int flags) {
    assert(mask==_object_mask_all && !flags); iterator->index=0; iterator->visited=FALSE;
}
static void *object_iterator_next(struct object_iterator *iterator) {
    if(iterator->visited || !object_present) return NULL;
    iterator->visited=TRUE; return &fixture_object;
}
static real_vector3d transform(const real_matrix4x3 *m,real_vector3d p) {
    return (real_vector3d){
        m->scale*(m->forward.i*p.i+m->left.i*p.j+m->up.i*p.k),
        m->scale*(m->forward.j*p.i+m->left.j*p.j+m->up.j*p.k),
        m->scale*(m->forward.k*p.i+m->left.k*p.j+m->up.k*p.k)};
}
static void matrix4x3_from_point_and_vectors(real_matrix4x3 *m,const real_point3d *p,
    const real_vector3d *forward,const real_vector3d *up) {
    *m=(real_matrix4x3){.scale=1,.forward=*forward,.up=*up,.position=*p};
    m->left=(real_vector3d){up->j*forward->k-up->k*forward->j,
        up->k*forward->i-up->i*forward->k,up->i*forward->j-up->j*forward->i};
}
static void matrix4x3_inverse(const real_matrix4x3 *m,real_matrix4x3 *out) {
    real_matrix4x3 r={.scale=1/m->scale,
        .forward={m->forward.i,m->left.i,m->up.i},
        .left={m->forward.j,m->left.j,m->up.j},
        .up={m->forward.k,m->left.k,m->up.k}};
    real_vector3d p=transform(&r,(real_vector3d){-m->position.x,-m->position.y,-m->position.z});
    r.position=(real_point3d){p.i,p.j,p.k}; *out=r;
}
static void matrix4x3_inverse_transform_point(const real_matrix4x3 *m,const real_point3d *point,real_point3d *out) {
    real_matrix4x3 inverse; matrix4x3_inverse(m,&inverse);
    real_vector3d p=transform(&inverse,(real_vector3d){point->x,point->y,point->z});
    *out=(real_point3d){p.i+inverse.position.x,p.j+inverse.position.y,p.k+inverse.position.z};
}
static void matrix4x3_multiply(const real_matrix4x3 *a,const real_matrix4x3 *b,real_matrix4x3 *out) {
    real_matrix4x3 r={.scale=a->scale*b->scale};
    real_matrix4x3 basis=*a; basis.scale=1;
    r.forward=transform(&basis,b->forward); r.left=transform(&basis,b->left); r.up=transform(&basis,b->up);
    real_vector3d p=transform(a,(real_vector3d){b->position.x,b->position.y,b->position.z});
    r.position=(real_point3d){p.i+a->position.x,p.j+a->position.y,p.k+a->position.z}; *out=r;
}
void render_interpolation_reset(void);
real_matrix4x3 *render_interpolation_object_node_matrices(long index);
real_matrix4x3 *object_get_node_matrices(long index);
/* PRODUCTION TRANSLATION UNIT */
/* PRODUCTION OBJECT ACCESSOR */
'''

CASES = r'''
#define REQUIRE(condition,message) do { if(!(condition)) { \
    fprintf(stderr,"%s at line %d\n",message,__LINE__); exit(1); } } while(0)
static boolean close(real a,real b) { return fabsf(a-b)<0.00002f; }
static real previous_draw_time;
static unsigned draw_count;
static real_matrix4x3 identity_at(real x) {
    return (real_matrix4x3){.scale=1,.forward={1,0,0},.left={0,1,0},.up={0,0,1},.position={x,0,0}};
}
static struct observer_result observer_at(real x) {
    return (struct observer_result){.position={x,0,0},.forward={1,0,0},.up={0,0,1},.field_of_view=1};
}
static void update_raw(void) {
    raw_nodes[0]=identity_at((real)world_tick*.25f+8);
    raw_nodes[1]=identity_at((real)world_tick*.25f+9);
}
static void reset_fixture(unsigned long tick,boolean interpolation) {
    render_interpolation_frame_end();
    render_interpolation_reset();
    if(interpolated_objects) {
        for(unsigned i=0;i<MAXIMUM_INTERPOLATED_OBJECTS;i++) {
            free(interpolated_objects[i].nodes); free(interpolated_objects[i].rotations);
        }
        free(interpolated_objects); interpolated_objects=NULL;
    }
    interpolation_tick=tick; interpolation_frame=0;
    world_tick=tick; enabled=interpolation; object_present=TRUE; cinematic=TRUE;
    fixture_object.object.node_matrices.size=sizeof(raw_nodes);
    fixture_object.object.parent_object_index=NONE;
    fixture_object.object.first_child_object_index=NONE;
    fixture_object.object.next_object_index=NONE;
    previous_draw_time=-1; draw_count=0; update_raw();
}
static void advance(unsigned ticks) {
    for(unsigned i=0;i<ticks;i++) {
        world_tick++; update_raw(); render_interpolation_tick();
    }
}
static real tracking_draw(real alpha,boolean check_fraction,real expected_fraction) {
    struct observer_result observer=observer_at((real)world_tick*.25f);
    clock_fraction=alpha;
    render_interpolation_frame_begin();
    if(check_fraction)
        REQUIRE(close(render_interpolation_fraction(),expected_fraction),"unexpected shared fraction");
    const struct observer_result *camera=render_interpolation_camera(0,&observer);
    real_matrix4x3 *nodes=object_get_node_matrices(0);
    REQUIRE(close(nodes[0].position.x-camera->position.x,8),"camera and world drift");
    REQUIRE(close(nodes[1].position.x-camera->position.x,9),"second node and camera drift");
    real time=render_interpolation_game_time_sec((long)world_tick);
    REQUIRE(time>=previous_draw_time-.000002f,"rendered time rewound");
    if(enabled) {
        real pose_tick=interpolation_fraction==1 ? (real)world_tick
            : (real)world_tick-1+interpolation_fraction;
        REQUIRE(close(time,pose_tick/TICKS_PER_SECOND),"shader time disagrees with shared pose time");
    } else REQUIRE(close(time,(real)world_tick/TICKS_PER_SECOND),"disabled shader time changed");
    previous_draw_time=time; draw_count++;
    struct render_camera render_camera={.position=camera->position,.forward=camera->forward,.up=camera->up};
    real_matrix4x3 weapon=identity_at(camera->position.x+2+(real)world_tick*.125f);
    render_interpolation_first_person(0,&weapon,1,&render_camera);
    real pose_tick=enabled && interpolated_first_person[0].has_previous
        ? (real)world_tick-1+interpolation_fraction : (real)world_tick;
    REQUIRE(close(weapon.position.x-camera->position.x,2+pose_tick*.125f),"first-person pose clock differs");
    render_interpolation_frame_end();
    REQUIRE(render_interpolation_fraction()==1,"fraction leaked outside rendering");
    REQUIRE(!render_interpolation_object_node_matrices(0),"object interpolation leaked into simulation");
    REQUIRE(render_interpolation_camera(0,&observer)==&observer,"camera interpolation leaked outside rendering");
    REQUIRE(close(render_interpolation_game_time_sec((long)world_tick),(real)world_tick/TICKS_PER_SECOND),
        "shader interpolation leaked outside rendering");
    return time;
}
static void catch_up_tracking(void) {
    reset_fixture(10,TRUE); tracking_draw(1,FALSE,0);
    const unsigned gaps[]={1,2,1,3,1};
    for(unsigned i=0;i<sizeof(gaps)/sizeof(gaps[0]);i++) {
        advance(gaps[i]); tracking_draw(.1f,FALSE,0);
        if(gaps[i]>1) {
            real held=previous_draw_time;
            tracking_draw(1,FALSE,0); tracking_draw(.1f,FALSE,0); tracking_draw(.9f,FALSE,0);
            REQUIRE(close(previous_draw_time,held),"catch-up zero-tick frames did not hold current time");
        } else tracking_draw(.9f,FALSE,0);
    }
    REQUIRE(draw_count==15,"tracking fixture did not exercise all expected frames");
}
static void first_frame_and_resume(void) {
    reset_fixture(10,TRUE);
    tracking_draw(.1f,TRUE,1); tracking_draw(1,TRUE,1); tracking_draw(.1f,TRUE,1);
    REQUIRE(interpolated_objects[0].tick==interpolation_tick,"first frame did not seed current object nodes");
    REQUIRE(!interpolated_objects[0].has_previous,"first frame fabricated an object pair");
    REQUIRE(interpolation_tick==10 && world_tick==10,"first frame advanced simulation");
    advance(1); tracking_draw(.1f,TRUE,.1f); tracking_draw(.9f,TRUE,.9f);
    REQUIRE(interpolated_objects[0].has_previous,"next tick lacks a seeded object pair");
    advance(1); tracking_draw(.1f,TRUE,.1f);
    /* Tick zero is also the zero-initialized first-person snapshot stamp. */
    reset_fixture(0,TRUE); tracking_draw(.1f,TRUE,1); tracking_draw(.9f,TRUE,1);
    REQUIRE(interpolation_tick==0 && world_tick==0,"initial frame advanced tick zero");
    advance(1); tracking_draw(.1f,TRUE,.1f); tracking_draw(.9f,TRUE,.9f);
}
static void ordinary_zero_one_ticks(void) {
    reset_fixture(10,TRUE); tracking_draw(.3f,TRUE,1);
    for(unsigned i=0;i<5;i++) {
        advance(1); tracking_draw(.1f,TRUE,.1f); tracking_draw(.5f,TRUE,.5f); tracking_draw(.9f,TRUE,.9f);
    }
    REQUIRE(interpolation_tick==15 && world_tick==15,"renders changed simulation cadence");
}
static void fallback_camera_holds(void) {
    reset_fixture(10,TRUE); tracking_draw(.1f,TRUE,1);
    advance(2); tracking_draw(.1f,TRUE,1);
    struct observer_result observer=observer_at((real)world_tick*.25f+.125f);
    clock_fraction=.2f; render_interpolation_frame_begin();
    const struct observer_result *camera=render_interpolation_camera(0,&observer);
    REQUIRE(close(camera->position.x,(real)world_tick*.25f),"fallback resampled per-frame camera");
    REQUIRE(close(object_get_node_matrices(0)[0].position.x-camera->position.x,8),"held camera separated from nodes");
    render_interpolation_frame_end();
    advance(1); tracking_draw(.1f,TRUE,.1f);
}
static void map_reset(void) {
    reset_fixture(10,TRUE); tracking_draw(.1f,TRUE,1);
    advance(1); tracking_draw(.8f,TRUE,.8f);
    render_interpolation_reset();
    /* New map takes the same datum index and moves less than the snap threshold. */
    world_tick=2; update_raw(); previous_draw_time=-1;
    tracking_draw(.1f,TRUE,1); tracking_draw(1,TRUE,1); tracking_draw(.1f,TRUE,1);
    advance(1); tracking_draw(.1f,TRUE,.1f);
}
static void disabled_and_toggled(void) {
    reset_fixture(10,FALSE); tracking_draw(.1f,TRUE,1);
    REQUIRE(!interpolated_objects,"disabled rendering allocated interpolation snapshots");
    advance(2); tracking_draw(.1f,TRUE,1);
    REQUIRE(!interpolated_objects,"disabled ticks allocated interpolation snapshots");
    enabled=TRUE; tracking_draw(.1f,TRUE,1); tracking_draw(.8f,TRUE,1);
    advance(1); tracking_draw(.1f,TRUE,.1f);
    enabled=FALSE; tracking_draw(.1f,TRUE,1);
    enabled=TRUE; tracking_draw(.1f,TRUE,1);
    advance(1); tracking_draw(.1f,TRUE,.1f);
    /* Disable while no disabled frame is drawn; ticks must invalidate history. */
    enabled=FALSE; advance(2); enabled=TRUE;
    tracking_draw(.1f,TRUE,1); advance(1); tracking_draw(.1f,TRUE,.1f);
}
static void ordinary_cuts(void) {
    reset_fixture(10,TRUE); tracking_draw(.1f,TRUE,1);
    advance(1); clock_fraction=.1f; render_interpolation_frame_begin();
    struct observer_result observer=observer_at(100);
    REQUIRE(render_interpolation_camera(0,&observer)==&observer,"ordinary position cut stopped snapping");
    render_interpolation_frame_end();
    advance(1); render_interpolation_frame_begin(); observer.forward=(real_vector3d){-1,0,0};
    REQUIRE(render_interpolation_camera(0,&observer)==&observer,"ordinary rotation cut stopped snapping");
    render_interpolation_frame_end();
    /* An object's own teleport still snaps during normal fractional rendering. */
    raw_nodes[0]=identity_at(100); raw_nodes[1]=identity_at(101);
    render_interpolation_tick(); clock_fraction=.1f; render_interpolation_frame_begin();
    REQUIRE(close(object_get_node_matrices(0)[0].position.x,100),"object teleport stopped snapping");
    render_interpolation_frame_end();
}
static void wrapping_tick_clock(void) {
    reset_fixture(UINT32_MAX-1,TRUE);
    /* The interpolation clock wraps independently of the small game-time fixture. */
    world_tick=10; update_raw(); tracking_draw(.1f,TRUE,1);
    advance(1); tracking_draw(.1f,TRUE,.1f);
    REQUIRE(interpolation_tick==UINT32_MAX,"tick clock did not reach boundary");
    advance(1); tracking_draw(.1f,TRUE,.1f);
    REQUIRE(interpolation_tick==0,"unsigned tick did not wrap safely");
    advance(2); tracking_draw(.1f,TRUE,1); tracking_draw(.1f,TRUE,1);
    advance(1); tracking_draw(.1f,TRUE,.1f);
}
static void corrected_tracking(void) {
    reset_fixture(10,TRUE); tracking_draw(.1f,TRUE,1);
    advance(2); tracking_draw(.1f,TRUE,1);
    real_vector3d offset={.5f,0,0};
    render_interpolation_correct_object(0,&offset);
    tracking_draw(.1f,TRUE,1); tracking_draw(.9f,TRUE,1);
    advance(1); tracking_draw(.1f,TRUE,.1f); tracking_draw(.9f,TRUE,.9f);
}
static void direct_camera_override(void) {
    reset_fixture(10,TRUE); cinematic=FALSE;
    struct observer_result observer=observer_at(2.5f);
    clock_fraction=.1f; render_interpolation_frame_begin();
    const struct observer_result *camera=render_interpolation_camera(0,&observer);
    REQUIRE(close(camera->forward.j,1) && close(camera->position.x,2.5f),"direct facing override changed");
    render_interpolation_frame_end();
    enabled=FALSE; render_interpolation_frame_begin(); camera=render_interpolation_camera(0,&observer);
    REQUIRE(close(camera->forward.j,1),"disabled interpolation changed existing direct facing override");
    render_interpolation_frame_end();
}
static void rotated_root_pose(void) {
    reset_fixture(10,TRUE);
    raw_nodes[0]=identity_at(0); raw_nodes[1]=identity_at(2);
    render_interpolation_frame_begin(); render_interpolation_frame_end();
    raw_nodes[0]=identity_at(.1f);
    raw_nodes[0].forward=(real_vector3d){0,1,0}; raw_nodes[0].left=(real_vector3d){-1,0,0};
    raw_nodes[1]=raw_nodes[0]; raw_nodes[1].position=(real_point3d){.1f,2,0};
    world_tick++; render_interpolation_tick(); clock_fraction=.5f;
    render_interpolation_frame_begin();
    real_matrix4x3 *nodes=object_get_node_matrices(0);
    REQUIRE(close(nodes[0].position.x,.05f),"rigid root rotation caused a false pose snap");
    REQUIRE(close(nodes[1].position.x,1.05f) && close(nodes[1].position.y,1),"child node failed to blend rigid rotation");
    render_interpolation_frame_end();
    raw_nodes[0].position.x=.2f; raw_nodes[1].position=(real_point3d){.2f,3,0};
    world_tick++; render_interpolation_tick(); clock_fraction=.5f;
    render_interpolation_frame_begin(); nodes=object_get_node_matrices(0);
    REQUIRE(close(nodes[0].position.x,.2f) && close(nodes[1].position.y,3),"different local pose failed to snap");
    render_interpolation_frame_end();
}
int main(int argc,char **argv) {
    REQUIRE(argc==2,"one fixture case required");
    direct_enabled=!strcmp(argv[1],"direct-camera");
    if(!strcmp(argv[1],"tracking")) catch_up_tracking();
    else if(!strcmp(argv[1],"first-frame")) first_frame_and_resume();
    else if(!strcmp(argv[1],"ordinary")) ordinary_zero_one_ticks();
    else if(!strcmp(argv[1],"held-camera")) fallback_camera_holds();
    else if(!strcmp(argv[1],"map-reset")) map_reset();
    else if(!strcmp(argv[1],"toggles")) disabled_and_toggled();
    else if(!strcmp(argv[1],"cuts")) ordinary_cuts();
    else if(!strcmp(argv[1],"wrapping")) wrapping_tick_clock();
    else if(!strcmp(argv[1],"corrections")) corrected_tracking();
    else if(!strcmp(argv[1],"direct-camera")) direct_camera_override();
    else if(!strcmp(argv[1],"rotated-root")) rotated_root_pose();
    else REQUIRE(FALSE,"unknown fixture case");
    reset_fixture(0,FALSE);
    return 0;
}
'''


class RenderInterpolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A C compiler is required for production interpolation tests")
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-render-interpolation-")
        cls.addClassCleanup(cls.directory.cleanup)
        production = re.sub(r'^#include "[^"\n]+"\s*\n', '', SOURCE.read_text(), flags=re.M)
        accessor = block((ROOT / "source/objects/objects.c").read_text(),
                         "real_matrix4x3 *object_get_node_matrices(\n")
        cls.executables = {}
        for name, code in (("current", production), ("without-fallback", production.replace(
                "if (interpolation_current_tick)", "if (FALSE)"))):
            text = PREFIX.replace("/* PRODUCTION TRANSLATION UNIT */", code)
            text = text.replace("/* PRODUCTION OBJECT ACCESSOR */", accessor) + CASES
            text = re.sub(r"\blong\b", "int32_t", text).replace("unsigned int32_t", "uint32_t")
            source = Path(cls.directory.name) / f"{name}.c"
            source.write_text(text)
            executable = source.with_suffix(".exe" if os.name == "nt" else "")
            flags = ["-std=c11", "-O1", "-Wall", "-Wextra", "-Werror"]
            if os.name != "nt":
                flags += ["-fsanitize=address,undefined"]
            result = subprocess.run([compiler, *flags, str(source), "-o", str(executable)],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.executables[name] = executable

    def run_case(self, case, version="current"):
        return subprocess.run([str(self.executables[version]), case], capture_output=True,
                              text=True, timeout=10)

    def assert_case(self, case):
        result = self.run_case(case)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tracking_camera_and_two_world_nodes_remain_coherent_after_catch_up(self):
        self.assert_case("tracking")

    def test_regression_control_detects_camera_world_oscillation(self):
        result = self.run_case("tracking", "without-fallback")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("camera and world drift", result.stderr)

    def test_first_frame_seeds_without_a_tick_and_resumes_on_the_next_tick(self):
        self.assert_case("first-frame")

    def test_normal_zero_and_one_tick_frames_keep_existing_fractional_motion(self):
        self.assert_case("ordinary")

    def test_fallback_camera_stays_captured_during_zero_tick_frames(self):
        self.assert_case("held-camera")

    def test_map_reset_discards_old_datum_history_and_seeds_current_nodes(self):
        self.assert_case("map-reset")

    def test_disabled_and_reenabled_rendering_preserve_raw_gameplay_and_seed_history(self):
        self.assert_case("toggles")

    def test_normal_camera_cuts_and_object_teleports_still_snap(self):
        self.assert_case("cuts")

    def test_tick_wrap_uses_unsigned_differences_without_signed_overflow(self):
        self.assert_case("wrapping")

    def test_direct_facing_override_is_preserved_during_fallback_and_disabled_rendering(self):
        self.assert_case("direct-camera")

    def test_camera_and_object_network_correction_glide_stay_coherent_during_fallback(self):
        self.assert_case("corrections")

    def test_root_rotation_preserves_rigid_nodes_but_changed_pose_snaps(self):
        self.assert_case("rotated-root")


if __name__ == "__main__":
    unittest.main()
