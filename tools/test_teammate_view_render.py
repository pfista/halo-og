"""Exercise production pane dispatch, local-state guards and body exclusion.

The original render functions run against instrumented CPU dependencies for
GLES, Native Metal and the retail define set. This checks presentation routing
and isolation; it does not establish GPU appearance or multiplayer timing.
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
#include <stdio.h>
#include <string.h>
typedef int boolean;
typedef float real;
typedef unsigned short word;
typedef struct { short x,y; } point2d;
typedef struct { short x0,x1,y0,y1; } rectangle2d;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
typedef struct { real x0,x1,y0,y1; } real_rectangle2d;
typedef struct { real r,g,b; } real_rgb_color;
typedef struct { real i,j,k,d; } real_plane3d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define RASTERIZER_TARGET_RENDER_PRIMARY_WIDTH 640
#define RASTERIZER_TARGET_RENDER_PRIMARY_HEIGHT 480
#define match_assert(file,line,condition) assert(condition)
/* STRUCTURES */
struct render_frustum { int unused; };
struct render_mirror { short cluster_index; };
struct bitmap_data { int unused; };
struct render_screen_flash { short type; };
struct rasterizer_window_begin_parameters {
    struct render_camera camera;
    struct render_frustum frustum;
    short rasterizer_target,window_index;
    boolean has_mirror;
    struct render_fog fog;
    struct render_screen_flash screen_flash;
};
struct rasterizer_frame_begin_parameters { real game_time_sec; };
struct object_render_data { boolean shadow; };
struct player_datum { long unit_index; };
static struct {
    int frame_index,scene_index,window_index,local_player_index;
    int rendered_cluster_count,visible_sky_index,cluster_index;
    real time_delta_since_tick_sec;
    struct render_camera camera;
    struct render_frustum frustum;
    struct render_fog fog;
} render;
static struct { boolean draw_first_person_weapon_first; } rasterizer_debug_options;
static struct { short cluster_index; } rendered_cluster;
static struct player_datum local_player={500};
static boolean render_invalid_fog_warning_displayed;
static short global_screenshot_count,global_screenshot_size=1;
enum { _director_perspective_first_person,_director_perspective_third_person };
enum { _render_target_primary,_render_target_secondary };
enum { _decal_layer_light,_decal_layer_alpha_tested,_decal_layer_primary,_decal_layer_water };
enum { _render_planar_fog_mode_fully_fogged=2 };
static long target_player=202,target_first_person_unit=600;
static int target_window=1,perspective=_director_perspective_first_person;
static int world[5],callbacks[5],labels[5],nonplayer[5],fp_draws[5],debug[5],aa[5];
static int fog_reads[5],planar_reads[5],local_lookups;
static boolean debug_objects=TRUE;
static int object_debug[5];
static void object_type_render_debug(long object_index) { object_debug[render.window_index]++; }
static long teammate_view_get_player_index(short window) {
    return window==target_window ? target_player:NONE;
}
static long teammate_view_get_first_person_unit_index(short window) {
    return teammate_view_get_player_index(window)!=NONE ? target_first_person_unit:NONE;
}
static void teammate_view_draw_label(short window) {
    assert(window==target_window && render.local_player_index==NONE); labels[window]++;
}
static long local_player_get_player_index(short index) {
    local_lookups++; assert(index==NONE || index==0); return index==NONE ? NONE:101;
}
static struct player_datum *player_get(long index) { assert(index==101); return &local_player; }
static int director_get_perspective(short index) { assert(index==0); return perspective; }
static boolean scripted_camera_object_is_first_person_camera(long index) { return index==999; }
static void local_callback(void) {
    assert(render.local_player_index==0); callbacks[render.window_index]++;
}
static void player_effect_get_screen_flash(short index,struct render_screen_flash *flash) {
    assert(index==0); flash->type=7; local_callback();
}
static void rasterizer_window_begin(const struct rasterizer_window_begin_parameters *parameters) {
    assert(parameters->window_index==render.window_index);
    if(render.local_player_index==NONE) assert(parameters->screen_flash.type==0);
}
static void render_sky(void) { world[render.window_index]++; }
static void render_debug(void) { assert(render.local_player_index==0); debug[render.window_index]++; }
static void halo_metal_antialias_before_hud(long x0,long y0,long x1,long y1) {
    assert(x0<x1 && y0<y1); aa[render.window_index]++;
}
static void first_person_weapon_draw(void) {
    assert(render.local_player_index==0 || render.local_player_index==NONE);
    fp_draws[render.window_index]++;
}
static void scenario_get_atmospheric_fog(short index,word sky,real_point3d *position,struct render_fog *fog) {
    assert(index==0); fog_reads[render.window_index]++; memset(fog,0,sizeof(*fog));
    fog->atmospheric_color.r=.5f;
}
static void structure_get_planar_fog(short cluster,struct render_fog *fog) {
    planar_reads[render.window_index]++; fog->planar_color.g=.25f;
}
static void render_camera_build_frustum_bounds(const struct render_camera *camera,real_rectangle2d *bounds) {
    *bounds=(real_rectangle2d){-1,1,-1,1};
}
static void render_camera_build_frustum(const struct render_camera *camera,const real_rectangle2d *bounds,
    struct render_frustum *frustum,boolean build) { memset(frustum,0,sizeof(*frustum)); }
static int main_get_window_count(void) { return 2; }
static boolean structure_visibility_find_mirror(const struct render_camera *camera,
    const struct render_frustum *frustum,struct render_mirror *mirror) { return FALSE; }
static void render_camera_mirror(const struct render_camera *camera,const struct render_mirror *mirror,
    struct render_camera *out) { *out=*camera; }
static void error(int level,const char *message) { assert(!"unexpected fog error"); }
static void render_nonplayer_frame(const struct render_window *window,long type) { nonplayer[render.window_index]++; }
static real render_interpolation_game_time_sec(int tick) { return (real)tick/30; }
static int game_time_get(void) { return 1; }
static boolean bink_playback_in_progress(void) { return FALSE; }
static void *rendered_cluster_get(short index) { return &rendered_cluster; }
static void process_rendered_objects(struct object_render_data *data) { assert(!data->shadow); }
/* DEPENDENCIES */
/* PRODUCTION */
'''

NO_OPS = """
profile_render_window_start profile_render_window_end structure_visibility_compute
build_sprite_prepare_for_window lights_preprocess_scene structure_render_preprocess
structure_render_lightmaps rasterizer_lens_flares_submit_occlusion_tests render_object_shadows
lights_render_diffuse rasterizer_decals_begin rasterizer_decals_draw rasterizer_decals_end
structure_render_diffuse_texture lights_render_specular structure_render_specular_lightmaps
structure_render_reflection_lightmap_masks structure_render_reflection_mirrors
structure_render_reflections structure_render_transparent_geometry structure_render_fog
render_particles particle_systems_render render_contrails_normal rasterizer_transparent_geometry_draw
rasterizer_transparent_geometry_stop structure_render_detail_objects structure_render_fog_screen
rasterizer_lens_flares_draw bink_playback_render render_camera_debug_frustum editor_render
rasterizer_debug_draw rasterizer_window_end halo_screen_ui_offset rasterizer_frame_begin
rasterizer_windows_begin rasterizer_windows_end rasterizer_frame_end progress_bar_eachframe
structure_visibility_find_camera rasterizer_profile_enable profile_enter profile_exit
rasterizer_models_begin rasterizer_models_end find_rendered_objects
""".split()

LOCAL_CALLBACKS = """
first_person_weapon_render_update game_engine_post_rasterize_objects weather_particle_systems_render
interface_draw_screen rasterizer_screen_flash render_ui_widgets
""".split()

HARNESS = r'''
static void reset(void) {
    memset(world,0,sizeof(world)); memset(callbacks,0,sizeof(callbacks));
    memset(labels,0,sizeof(labels)); memset(nonplayer,0,sizeof(nonplayer));
    memset(fp_draws,0,sizeof(fp_draws)); memset(debug,0,sizeof(debug));
    memset(fog_reads,0,sizeof(fog_reads)); memset(planar_reads,0,sizeof(planar_reads));
    memset(aa,0,sizeof(aa)); memset(&render,0,sizeof(render));
    memset(object_debug,0,sizeof(object_debug));
    local_lookups=0;
    target_player=202; target_first_person_unit=600; target_window=1;
}
static struct render_window window(short local,boolean console) {
    struct render_window result={0}; result.local_player_index=local; result.console_window=console;
    result.render_camera.viewport_bounds=(rectangle2d){0,640,0,240};
    result.render_camera.window_bounds=result.render_camera.viewport_bounds;
    result.render_camera.z_near=.1f; result.render_camera.z_far=100;
    result.rasterizer_camera=result.render_camera; return result;
}
int main(void) {
    struct render_window windows[3]={window(0,FALSE),window(NONE,FALSE),window(NONE,TRUE)};
    reset(); render_frame(windows,3,NULL,NULL,NULL,.01f);
    assert(world[0]==1 && callbacks[0]==7 && fp_draws[0]==1 && debug[0]==1);
    assert(fog_reads[0]==1 && planar_reads[0]==1 && nonplayer[2]==1);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(world[1]==1 && labels[1]==1 && nonplayer[1]==0 && planar_reads[1]==1);
    assert(callbacks[1]==0 && fp_draws[1]==0 && debug[1]==0 && fog_reads[1]==0);
    assert(render.fog.atmospheric_color.r==0 && render.fog.planar_color.g==.25f);
#if defined(HALO_MACOS_NATIVE_METAL) && HALO_MACOS_NATIVE_METAL
    assert(aa[0]==1 && aa[1]==1);
#else
    assert(aa[0]==0 && aa[1]==0);
#endif
    /* A stale/dead/left/team-changed target cannot render a remote world. */
    reset(); target_player=NONE; render_frame(windows,3,NULL,NULL,NULL,.01f);
    assert(world[1]==0 && labels[1]==0 && nonplayer[1]==1);
    /* Console dispatch takes precedence even if a sidecar slot is stale. */
    reset(); target_window=2; render_frame(windows,3,NULL,NULL,NULL,.01f);
    assert(world[2]==0 && labels[2]==0 && nonplayer[2]==1);
    /* A real local slot retains its normal rendering despite a stale sidecar. */
    reset(); target_window=0; render_frame(windows,3,NULL,NULL,NULL,.01f);
    assert(world[0]==1 && callbacks[0]==7 && labels[0]==0 && fog_reads[0]==1);
    reset(); render.window_index=1; render.local_player_index=NONE;
    fixture_object_debug(700); assert(object_debug[1]==0);
    assert(object_is_first_person_camera(600));
    assert(!object_is_first_person_camera(500));
    assert(!object_is_first_person_camera(700)); assert(local_lookups==0);
    /* A vehicle third-person view retains its teammate's visible body. */
    target_first_person_unit=NONE; assert(!object_is_first_person_camera(600));
    assert(local_lookups==0);
#else
    assert(world[1]==0 && labels[1]==0 && nonplayer[1]==1);
#endif
    /* NONE windows outside the optional teammate view retain the original
       first-person callback (which itself handles NONE as a no-op). */
    reset(); render.local_player_index=NONE; render.window_index=1; target_player=NONE;
    render_objects(); assert(fp_draws[1]==1);
    fixture_object_debug(700); assert(object_debug[1]==1);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    target_player=202; fp_draws[1]=0; render_objects(); assert(fp_draws[1]==0);
#endif
    render.local_player_index=0; render.window_index=0; perspective=_director_perspective_first_person;
    fixture_object_debug(700); assert(object_debug[0]==1);
    local_lookups=0;
    assert(object_is_first_person_camera(500)); assert(!object_is_first_person_camera(600));
    perspective=_director_perspective_third_person; assert(!object_is_first_person_camera(500));
    assert(object_is_first_person_camera(999));
    /* Every define set retains real local-player lookup for the local pane. */
    assert(local_lookups>0);
    puts("teammate render passed"); return 0;
}
'''


def definition(source, signature):
    """Skip the forward declaration and extract the actual production body."""
    return c_block(source[source.rindex(signature):], signature)


class TeammateViewRenderTests(unittest.TestCase):
    def test_dispatch_local_state_isolation_fog_and_body_exclusion(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(compiler, "A C compiler (clang or cc) is required")
        cameras = (ROOT / "source/render/render_cameras.h").read_text()
        structures = "\n".join(c_block(cameras, "struct " + name + "\n{") + ";"
                               for name in ("render_camera", "render_window", "render_fog"))
        renderer = (ROOT / "source/render/render.c").read_text()
        objects = (ROOT / "source/render/render_objects.c").read_text()
        functions = "\n".join((
            definition(objects, "static boolean object_is_first_person_camera(\n"),
            definition(objects, "void render_objects(\n"),
            definition(renderer, "static void render_window(\n"),
            definition(renderer, "static void render_player_frame(\n"),
            definition(renderer, "void render_frame(\n"),
        ))
        # This callback is nested in a large model-drawing function. Compile its
        # actual guard and body so debug flags cannot expose a NONE local slot.
        functions += ("\nstatic void fixture_object_debug(long object_index) {\n"
                      + c_block(objects, "if (debug_objects\n") + "\n}\n")
        dependencies = "\n".join("#define " + name + "(...) ((void)0)" for name in NO_OPS)
        dependencies += "\n" + "\n".join("#define " + name + "(...) local_callback()"
                                          for name in LOCAL_CALLBACKS)
        source = (PREFIX.replace("/* STRUCTURES */", structures)
                  .replace("/* DEPENDENCIES */", dependencies).replace("/* PRODUCTION */", functions)
                  + HARNESS)
        variants = (("gles", ("HALO_PORT_MAXIMUM_NETWORK_PLAYERS=128",)),
                    ("metal", ("HALO_PORT_MAXIMUM_NETWORK_PLAYERS=128", "HALO_MACOS_NATIVE_METAL=1")),
                    ("retail", ()))
        with tempfile.TemporaryDirectory(prefix="halo-teammate-render-") as temporary:
            directory = Path(temporary)
            fixture = directory / "fixture.c"
            fixture.write_text(source)
            for name, defines in variants:
                with self.subTest(renderer=name):
                    output = directory / (name + (".exe" if sys.platform == "win32" else ""))
                    command = [compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                               "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unused-parameter"]
                    if sys.platform != "win32":
                        command += ["-fsanitize=address,undefined"]
                    command += ["-D" + define for define in defines]
                    command += [str(fixture), "-o", str(output)]
                    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    tested = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(tested.returncode, 0, tested.stderr)
                    self.assertIn("teammate render passed", tested.stdout)


if __name__ == "__main__":
    unittest.main()
