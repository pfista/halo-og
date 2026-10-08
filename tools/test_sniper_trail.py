"""Cold/warm contrail rendering through production streaming and weapon hooks.

The fixture compiles the actual bitmap readiness, contrail draw, weapon creation,
ready and prefetch functions. Disk completion and GPU submission are controlled
dependencies: this proves the skipped cold draw and early nonblocking requests,
not physical visual parity or a guaranteed completion time on a player's disk.
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
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int boolean;
typedef float real;
typedef unsigned char byte;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
typedef struct { real x,y; } real_point2d;
typedef struct { real i,j; } real_vector2d;
typedef struct { real red,green,blue; } real_rgb_color;
typedef struct { real alpha,red,green,blue; } real_argb_color;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define TICKS_PER_SECOND 30
#define FLAG(n) (1u << (n))
#define TEST_FLAG(f,n) (((unsigned)(f) & FLAG(n)) != 0)
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->address)[i])
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define PIN(v,a,b) MIN(MAX(v,a),b)
#define match_assert(file,line,condition) assert(condition)
#define error(...) ((void)0)
#define console_warning(...) ((void)0)
#define terminal_printf(...) ((void)0)
#define lruv_debug_to_file(...) ((void)0)
enum { CONTRAIL_DEFINITION_TAG='cont', _bitmap_cached_bit=0,
       _terminal_message_chatter=0, _error_silent=0, _error_log=1,
       _rasterizer_lock_none=0, _rasterizer_lock_contrail=1,
       _contrail_state_color_bit=5, _contrail_state_width_bit=4,
       _contrail_point_transitioning_bit=1, _contrail_texture_repeats_u_bit=6,
       _contrail_texture_repeats_v_bit=7, _contrail_first_point_unfaded_bit=0,
       _contrail_last_point_unfaded_bit=1, _contrail_render_type_vertical=0,
       _contrail_render_type_horizontal=1, _contrail_render_type_media=2,
       _contrail_render_type_ground=3, _contrail_render_type_viewer=4,
       _weapon_state_idle=0, _weapon_state_ready=8,
       _first_person_weapon_message_ready=12, _first_person_weapon_animation_ready=10,
       _performance_sound_weapon_ready=1 };
struct tag_block { int count; void *address; };
struct tag_reference { long group_tag,index; };
struct bitmap_data { unsigned flags; long cache_block_index,tag_index,pixels_size; void *hardware_format; int fixture_index; };
struct bitmap_group { struct tag_block bitmaps; };
struct shader { int unused; };
struct contrail_shader { struct shader shader; short framebuffer_fade_mode; };
struct contrail_point_state { unsigned scale_flags; real width; real_argb_color color_lower_bound,color_upper_bound; };
struct contrail_definition {
    struct tag_reference bitmap; short first_sequence_index,sequence_count,render_type;
    unsigned flags,scale_flags; real texture_repeats_u,texture_repeats_v;
    struct contrail_shader shader; struct tag_block states;
};
struct contrail_datum {
    short sequence_index,frame_index,contrail_point_counts[4],attachment_index;
    long object_index,first_contrail_point_indices[4];
    real texture_offset_u,texture_offset_v,density;
};
struct contrail_point_datum {
    short state_index; unsigned flags; real density,time,width;
    real_point3d position; long next_contrail_point_index;
};
struct contrail_vertex { real_point3d point; real_point2d texture; uint32_t color; };
struct object_attachment_definition { struct tag_reference type; short change_color_reference; };
struct object_definition { struct { struct tag_block attachments; } object; };
struct object_datum { long definition_index; struct { real_rgb_color outgoing_change_colors[4]; } object; };
struct projectile_definition { struct { struct tag_block attachments; } object; };
struct weapon_trigger_definition { struct tag_reference projectile; };
struct weapon_magazine_definition { short rounds_total_initial,rounds_loaded_maximum; };
struct weapon_definition { struct { struct tag_block triggers,magazines; struct tag_reference ready_effect; } weapon; };
struct weapon_trigger { long charging_effect_index; short idle_ticks; };
struct weapon_magazine { short rounds_loaded,rounds_total; };
struct weapon_datum { long definition_index; struct { long parent_object_index; } object; struct { short state,state_timer; long overheated_effect_index;
    struct weapon_trigger triggers[2]; struct weapon_magazine magazines[1]; } weapon; };
struct xbox_texture_cache_texture { boolean loaded,used; int hardware_format; short read_request_handle; };
static struct xbox_texture_cache_texture textures[2];
static int texture_pool,point_pool;
static struct { void *textures,*cache; } xbox_texture_cache_globals={&texture_pool,NULL};
static void *contrail_point_data=&point_pool;
static int requests,draws,yields,touches,ready_effects,prefetch_errors;
static boolean cache_open,debug_texture_cache;
static unsigned long texture_cache_last_failure_time;
static struct { int current_lock_operation; } rasterizer_globals;
static struct { struct { real_point3d position; } camera; } render;
static real_point3d origin={0,0,0};
static real_point3d *global_origin3d=&origin;
static real_vector3d up={0,0,1},*global_up3d=&up;
static struct bitmap_data bitmaps[2];
static struct bitmap_group bitmap_group={{2,bitmaps}};
static struct contrail_point_state state={0,0.1f,{1,1,1,1},{1,1,1,1}};
static struct contrail_definition trail={
    {0,20},0,1,_contrail_render_type_viewer,3,0,1,1,{{0},0},{1,&state}
};
static struct contrail_datum contrail={0,0,{2,0,0,0},0,NONE,{0,NONE,NONE,NONE},0,0,1};
static struct contrail_point_datum points[2]={
    {0,0,1,0,0.1f,{5,0,0},1},{0,0,1,0,0.1f,{0,0,0},NONE}
};
static struct contrail_vertex vertices[16];
static short triangles[24];
static struct object_attachment_definition attachments[2]={{{CONTRAIL_DEFINITION_TAG,13},0},{{'effe',99},0}};
static struct projectile_definition projectile={{{2,attachments}}};
static struct weapon_trigger_definition triggers[2]={{{'proj',7}},{{'proj',NONE}}};
static struct weapon_magazine_definition magazine={12,4};
static struct weapon_definition weapon_definition={{{2,triggers},{1,&magazine},{0,99}}};
static struct weapon_datum weapons[2];
static void *datum_get(void *pool,long index) {
    if (pool==&texture_pool) { assert(index>=0 && index<2); return &textures[index]; }
    assert(pool==&point_pool && index>=0 && index<2); return &points[index];
}
static boolean texture_cache_start_loading_bitmap(struct bitmap_data *bitmap,boolean block) {
    assert(cache_open && !block); requests++;
    bitmap->cache_block_index=bitmap->fixture_index;
    textures[bitmap->fixture_index].loaded=FALSE;
    textures[bitmap->fixture_index].hardware_format=800+bitmap->fixture_index;
    return TRUE;
}
static void lruv_block_touch(void *cache,long index) { (void)cache; (void)index; touches++; }
static unsigned long system_milliseconds(void) { return 0; }
static unsigned long sound_render_time(void) { return 0; }
static void sound_idle(void) { assert(0); }
static void SwitchToThread(void) { yields++; }
static void cache_file_promote_read(short index) { (void)index; assert(0); }
static boolean terminal_shows(int category) { (void)category; return FALSE; }
static char const *tag_get_name(long index) { (void)index; return "synthetic trail"; }
static void *rasterizer_get_bitmap_default_hardware_format(struct bitmap_data *bitmap) { (void)bitmap; assert(0); return NULL; }
static struct weapon_definition *weapon_definition_get(long index) { assert(index==3); return &weapon_definition; }
static struct projectile_definition *projectile_definition_get(long index) { assert(index==7); return &projectile; }
static struct contrail_definition *contrail_definition_get(long index) { assert(index==13); return &trail; }
static struct bitmap_group *bitmap_group_get(long index) { assert(index==20); return &bitmap_group; }
static struct bitmap_data *bitmap_group_get_bitmap_from_sequence(long index,short sequence,short frame) {
    assert(index==20 && sequence==0 && frame>=0 && frame<2); return &bitmaps[frame];
}
static struct object_datum *object_get(long index) { (void)index; assert(0); return NULL; }
static struct object_definition *object_definition_get(long index) { (void)index; assert(0); return NULL; }
static long rasterizer_dynamic_triangles_new(short count) { assert(count==2); return 0; }
static long rasterizer_dynamic_vertices_new(short type,short count) { assert(type==6 && count==4); return 0; }
static short *rasterizer_dynamic_triangles_lock(long index) { assert(index==0); return triangles; }
static struct contrail_vertex *rasterizer_dynamic_vertices_lock(long index) { assert(index==0); return vertices; }
static void rasterizer_dynamic_triangles_unlock(long index) { assert(index==0); }
static void rasterizer_dynamic_vertices_unlock(long index) { assert(index==0); }
static void rasterizer_dynamic_triangles_delete(long index) { assert(index==0); }
static void rasterizer_dynamic_vertices_delete(long index) { assert(index==0); }
static void rasterizer_dynamic_unlit_geometry_draw(struct shader const *shader,struct bitmap_data *bitmap,
    int unused,long ti,long vi,short count,real_point3d const *average,int unused2) {
    (void)shader;(void)unused;(void)unused2;
    assert(bitmap==&bitmaps[contrail.frame_index] && ti==0 && vi==0 && count==2 && average->x==2.5f); draws++;
}
static real normalize2d(real_vector2d *v) {
    real n=sqrtf(v->i*v->i+v->j*v->j); if(n){v->i/=n;v->j/=n;} return n;
}
static real normalize3d(real_vector3d *v) {
    real n=sqrtf(v->i*v->i+v->j*v->j+v->k*v->k); if(n){v->i/=n;v->j/=n;v->k/=n;} return n;
}
static uint32_t real_argb_color_to_pixel32(real_argb_color const *color) { return (uint32_t)(color->alpha*255)<<24; }
static real contrail_fade(struct contrail_definition *definition,short mode,real_point3d const *position,real_vector3d const *orientation) {
    (void)definition;(void)mode;(void)position;(void)orientation; return 1;
}
static struct weapon_datum *weapon_get(long index) { assert(index>=0 && index<2); return &weapons[index]; }
static struct weapon_magazine *weapon_magazine_get(struct weapon_datum *weapon,short index) { assert(index==0); return &weapon->weapon.magazines[index]; }
static struct weapon_trigger *weapon_trigger_get(struct weapon_datum *weapon,short index) { assert(index>=0 && index<2); return &weapon->weapon.triggers[index]; }
static void weapon_reset(long index) { assert(index>=0 && index<2); }
static void weapon_set_state(long index,short state,boolean immediate) { assert(immediate); weapons[index].weapon.state=state; }
static void first_person_weapon_message_from_weapon(long index,short message) { assert(index>=0 && index<2 && message==12); }
struct performance_sound_scope { unsigned role; long player_index; };
static long player_index_from_unit_index(long index) { assert(index==10); return 20; }
static struct performance_sound_scope performance_sound_push(unsigned role,long player) { assert(role==1 && player==20); return (struct performance_sound_scope){0,NONE}; }
static void performance_sound_pop(struct performance_sound_scope previous) { assert(previous.role==0 && previous.player_index==NONE); }
static void weapon_effect_new(long index,long definition,real scale,real error) { assert(index>=0 && index<2 && definition==99 && scale==0 && error==0); ready_effects++; }
static short weapon_get_first_person_animation_time(long index,short slot,short animation,short type) { assert(index>=0 && index<2 && slot==0 && animation==10 && type==NONE); return 8; }
/* PRODUCTION */
'''

HARNESS = r'''
static void cold_cache(void) {
    memset(textures,0,sizeof(textures));
    for(int i=0;i<2;i++) bitmaps[i]=(struct bitmap_data){FLAG(_bitmap_cached_bit),NONE,20,64,NULL,i};
    requests=draws=yields=touches=ready_effects=0;
    render.camera.position=(real_point3d){0,2,0}; cache_open=TRUE;
    weapons[0].definition_index=weapons[1].definition_index=3;
    weapons[0].object.parent_object_index=weapons[1].object.parent_object_index=10;
    contrail.frame_index=0;
}
static void complete_reads(void) {
    for(int i=0;i<2;i++) if(bitmaps[i].cache_block_index!=NONE) textures[i].loaded=TRUE;
}
static void draw_trail(void) { render_contrail(&contrail,&trail,0); assert(rasterizer_globals.current_lock_operation==_rasterizer_lock_none); }
int main(void) {
    cold_cache();
    /* Original cold path: the production renderer skips submission while
       the production cache reports a pending nonblocking bitmap read. */
    draw_trail(); assert(draws==0 && requests==1);
    draw_trail(); assert(draws==0 && requests==1);
    complete_reads(); draw_trail(); assert(draws==1 && requests==1);
    /* Starting the same async read during weapon creation gives it time
       to complete before the first shot, including replicated weapons. */
    cold_cache(); assert(weapon_new(0)); assert(weapon_new(1));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(requests==2); complete_reads(); draw_trail(); assert(draws==1);
    contrail.frame_index=1; draw_trail(); assert(draws==2 && requests==2);
    assert(weapons[0].weapon.magazines[0].rounds_loaded==4 && weapons[0].weapon.magazines[0].rounds_total==8);
    assert(weapons[1].weapon.triggers[0].charging_effect_index==NONE && weapons[1].weapon.triggers[0].idle_ticks==127);
    /* Re-equipping also repairs readiness after cache eviction. A pending
       prewarm stays nonblocking and does not duplicate a queued read. */
    cold_cache(); weapon_ready(1); assert(requests==2 && ready_effects==1);
    assert(weapons[1].weapon.state==_weapon_state_ready && weapons[1].weapon.state_timer==8);
    weapon_ready(1); assert(requests==2 && ready_effects==2);
    draw_trail(); assert(draws==0); complete_reads(); draw_trail(); assert(draws==1);
    cold_cache(); weapon_precache_projectile_trails(NONE); assert(requests==0);
    int trigger_count=weapon_definition.weapon.triggers.count;
    weapon_definition.weapon.triggers.count=0; assert(weapon_new(0)); assert(requests==0);
    weapon_definition.weapon.triggers.count=trigger_count;
    triggers[0].projectile.index=NONE; weapon_ready(0); assert(requests==0); triggers[0].projectile.index=7;
    int attachment_count=projectile.object.attachments.count;
    projectile.object.attachments.count=0; weapon_ready(0); assert(requests==0);
    projectile.object.attachments.count=attachment_count;
    attachments[0].type.index=NONE; weapon_ready(0); assert(requests==0); attachments[0].type.index=13;
    attachments[0].type.group_tag='effe'; weapon_ready(0); assert(requests==0); attachments[0].type.group_tag=CONTRAIL_DEFINITION_TAG;
    trail.bitmap.index=NONE; weapon_ready(0); assert(requests==0); trail.bitmap.index=20;
    bitmap_group.bitmaps.count=0; weapon_ready(0); assert(requests==0); bitmap_group.bitmaps.count=2;
    puts("native cold/warm trail and nonblocking weapon prefetch passed");
#else
    /* The recovered Xbox creation/ready path gains no prefetch calls. */
    assert(requests==0); weapon_ready(1); assert(requests==0 && ready_effects==1);
    draw_trail(); assert(draws==0 && requests==1);
    puts("retail weapon path unchanged");
#endif
    return 0;
}
'''


class SniperTrailTests(unittest.TestCase):
    def test_production_cold_warm_and_weapon_hooks(self):
        weapons = (ROOT / "source/items/weapons.c").read_text()
        cache = (ROOT / "source/cache/xbox_texture_cache.c").read_text()
        renderer = (ROOT / "source/render/render_contrails.c").read_text()
        functions = [
            c_block(cache, "void *_texture_cache_bitmap_get_hardware_format(\n"),
            "#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS\n" + c_block(
                weapons, "static void weapon_precache_projectile_trails(\n") + "\n#endif",
            c_block(weapons, "void weapon_ready(\n\tlong weapon_index)\n{"),
            c_block(weapons, "boolean weapon_new(\n\tlong weapon_index)\n{"),
            c_block(renderer, "static void render_contrail(\n\tstruct contrail_datum *contrail,\n"
                              "\tstruct contrail_definition *definition,\n\tshort instance_index)\n{"),
        ]
        source = PREFIX.replace("/* PRODUCTION */", "\n".join(functions)) + HARNESS
        with tempfile.TemporaryDirectory(prefix="halo-sniper-trail-") as temporary:
            directory = Path(temporary)
            (directory / "fixture.c").write_text(source)
            for native in (False, True):
                with self.subTest(native=native):
                    compiler = shutil.which("clang") or shutil.which("cc")
                    if not compiler:
                        self.fail("A C compiler (clang or cc) is required")
                    suffix = ".exe" if sys.platform == "win32" else ""
                    output = directory / (("native" if native else "retail") + suffix)
                    command = [compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                               "-Wno-unused-function", "-Wno-unused-variable", "-Wno-multichar"]
                    # Windows runners use MinGW Clang, which has no ASan runtime.
                    if sys.platform != "win32":
                        command.append("-fsanitize=address,undefined")
                    if native:
                        command.append("-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=128")
                    math_library = [] if sys.platform == "win32" else ["-lm"]
                    command += [str(directory / "fixture.c"), *math_library, "-o", str(output)]
                    subprocess.run(command, check=True, capture_output=True, text=True)
                    result = subprocess.run([str(output)], check=True, capture_output=True, text=True)
                    self.assertIn("passed" if native else "unchanged", result.stdout)


if __name__ == "__main__":
    unittest.main()
