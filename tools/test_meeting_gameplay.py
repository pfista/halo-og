"""Exercise the production firing cone, pistol reticle and host admission gate."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


def run_fixture(text):
    with tempfile.TemporaryDirectory(prefix="halo-meeting-gameplay-") as temporary:
        source = Path(temporary) / "fixture.c"
        binary = source.with_suffix(".exe" if sys.platform == "win32" else "")
        source.write_text(text)
        math_library = [] if sys.platform == "win32" else ["-lm"]
        subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", "-I", str(ROOT / "source"),
                        str(source), *math_library, "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


class MeetingGameplayTests(unittest.TestCase):
    def test_precision_pistol_reticle_draws_without_mutating_map_tags(self):
        source = (ROOT / "source/interface/hud_weapon.c").read_text()
        functions = "\n".join(block(source, signature) for signature in (
            "static boolean performance_pistol_reticle_tag_matches(\n",
            "static void performance_pistol_reticle_placement(\n",
            "static void crosshairs_draw(\n\tstruct player_datum *player,\n"
            "\tlong weapon_index,\n\tlong hud_index,\n"
            "\tstruct weapon_interface_state *weapon_state)\n{",
        ))
        # Extract the whole draw function so passing the copied placement to
        # either bitmap path, preserving zoom overlays and split-screen scaling
        # are covered as well as the optional helper's identity checks.
        fixture = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define csstrcasecmp _stricmp
#else
#include <strings.h>
#define csstrcasecmp strcasecmp
#endif
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define STACK_BUFFER_LENGTH 4
#define MAXIMUM_WEAPON_HUD_DEFINITION_DEPTH 4
#define NUMBER_OF_UNIT_GRENADE_TYPES 2
#define TICKS_PER_SECOND 30
#define TEST_FLAG(v,b) (((v)&(1u<<(b)))!=0)
#define SET_FLAG(v,b,on) ((v)=(on)?((v)|(1u<<(b))):((v)&~(1u<<(b))))
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->address)[i])
#define csmemset memset
#define csstrlen strlen
#define csstrncmp strncmp
#define csprintf sprintf
/* Keep assertion failure nonreturning for every host compiler. */
#define match_vassert(file,line,c,message) do { if (!(c)) { assert(c); abort(); } } while (0)
#define match_assert_stack_frame(file,line) ((void)return_eip)
typedef int boolean;
typedef float real;
typedef unsigned pixel32;
typedef struct { real x0,y0,x1,y1; } real_rectangle2d;
enum { _performance_option_hardcore=64, _hud_crosshair_show_bit=0,
       _scenario_type_main_menu=0, _hud_anchor_center=0,
       _hud_crosshair_runtime_invalid_bit=0, _hud_crosshair_not_on_default_zoom_bit,
       _hud_crosshair_only_on_default_zoom_bit, _hud_crosshair_not_a_sprite_bit,
       _hud_crosshair_flashes_bit, _hud_crosshair_one_zoom_level_bit,
       _hud_crosshair_hide_outside_area_bit, _hud_dont_scale_size_bit=0,
       _unit_control_weapon_primary_trigger_bit=0, _unit_control_throw_grenade_bit,
       _bitmap_group_type_interface_bitmaps=0, _error_silent=0 };
enum { _crosshair_state_aim, _crosshair_state_zoom, _crosshair_state_fired_with_no_ammo,
       _crosshair_state_threw_with_no_grenade, _crosshair_state_fired_secondary_with_no_ammo,
       _crosshair_state_flash_fired_battery_depleted, _crosshair_state_charge,
       _crosshair_state_flash_ammo, _crosshair_state_flash_heat,
       _crosshair_state_flash_total_ammo, _crosshair_state_flash_total_battery,
       _crosshair_state_reload, _crosshair_state_flash_ammo_none_for_reload,
       _crosshair_state_flash_secondary_ammo, _crosshair_state_flash_secondary_total_ammo,
       _crosshair_state_secondary_reload, _crosshair_state_flash_secondary_ammo_none_for_reload,
       _crosshair_state_primary_trigger_ready, _crosshair_state_secondary_trigger_ready };
struct tag_block { long count; void *address; };
struct tag_reference { long index; };
struct hud_placement_definition { struct { short x,y; } offset;
    struct { real i,j; } scale; unsigned multiplayer_scaling_flags; };
struct hud_absolute_placement_definition { int anchor; };
struct hud_color_definition { pixel32 color; };
struct weapon_hud_crosshair_item { unsigned flags; struct hud_placement_definition placement;
    short sequence_index; struct hud_color_definition colors; int frame_rate; };
struct weapon_hud_crosshairs_element { short crosshair_type,use_on_map_type;
    struct { struct tag_block items; struct tag_reference bitmap; } crosshairs; };
struct weapon_hud_interface_definition { struct tag_reference parent_hud; struct tag_block crosshairs; };
struct crosshair_state { struct { long reference_data; } value; };
struct crosshair_hud_state { unsigned render_flags; struct crosshair_state states[19]; };
struct player_datum { long unit_index; short local_player_index; };
struct unit_datum { struct { unsigned control_flags; short grenade_counts[2]; int grenade_throw_state; } unit; };
struct weapon_interface_state { real age; struct { short rounds_loaded,rounds_remaining; } magazines[2]; };
struct weapon { long definition_index; };
struct weapon_definition { int unused; };
struct bitmap_group_sprite { short bitmap_index; real_rectangle2d bounds; };
struct bitmap_group_sequence { struct tag_block sprites; };
struct bitmap_data { short width,height; };
struct bitmap_group { int type; struct tag_block sequences,bitmaps; };
static struct { unsigned script_flags; } hud_globals={1}, *weapon_hud_globals=&hud_globals;
static struct { int type; } scenario={1};
static struct { struct { real_rectangle2d viewport_bounds; } camera; } render={{{0,0,640,480}}};
static struct crosshair_hud_state crosshair;
static struct unit_datum unit;
static struct weapon weapon={4};
static struct weapon_definition weapon_definition;
static struct weapon_hud_crosshair_item items[2];
static struct weapon_hud_crosshairs_element elements[2];
static struct weapon_hud_interface_definition hud;
/* Original Xbox pistol sequence 8: 28px crop, aim artwork at local (13,13). */
static struct bitmap_group_sprite sprite={0,{66,0,94,28}};
static struct bitmap_group_sequence sequences[9];
static struct bitmap_data bitmap={128,128};
static struct bitmap_group bitmap_group={0,{9,sequences},{1,&bitmap}};
static unsigned flags;
static int multiplayer=1,players=1,draw_count,clipped;
static char const *hud_name="weapons\\pistol\\pistol";
static char const *bitmap_name="ui\\hud\\bitmaps\\combined\\hud_reticles";
static struct hud_placement_definition drawn[4];
static real drawn_scale[4];
static int drawn_multiplayer[4];
static long get_return_eip(void) { return 0; }
static struct crosshair_hud_state *get_crosshair_state(short i) { assert(i==0);return &crosshair; }
static struct weapon_hud_interface_definition *weapon_hud_interface_definition_get(long i) { assert(i==100);return &hud; }
#define global_scenario_get() (&scenario)
static short teammate_view_hud_player_count(void) { return players; }
static struct unit_datum *unit_get(long i) { assert(i==20);return &unit; }
static struct weapon *weapon_get(long i) { assert(i==10);return &weapon; }
static struct weapon_definition *weapon_definition_get(long i) { (void)i;return &weapon_definition; }
static long weapon_definition_index_to_list_index(long i) { return i; }
static int game_engine_running(void) { return multiplayer; }
static unsigned performance_variant_get_flags(void *variant) { (void)variant;return flags; }
static void *game_engine_get_variant(void) { return NULL; }
static char const *tag_get_name(long i) { assert(i==100 || i==200);return i==100?hud_name:bitmap_name; }
static long verify_tag_reference(struct tag_reference *r) { return r->index; }
static struct bitmap_group *bitmap_group_get(long i) { assert(i==200);return &bitmap_group; }
static pixel32 get_flash_color(struct hud_color_definition *c,long tick) { (void)tick;return c->color; }
static int get_flash_duration(struct hud_color_definition *c) { (void)c;return 1; }
static long game_time_get(void) { return 30; }
static void error(int level,char const *message) { (void)level;(void)message;assert(0); }
static char *strip_path_name(char const *path) { return (char *)path; }
static int _texture_cache_bitmap_get_hardware_format(struct bitmap_data *b,int a,int c) { (void)b;(void)a;(void)c;return TRUE; }
static void hud_draw_bitmap(struct bitmap_data *b,struct hud_absolute_placement_definition *a,
    struct hud_placement_definition *p,real_rectangle2d *clip,real scale,real rotation,
    pixel32 color,boolean in_multiplayer,boolean interface_bitmap,boolean final) {
    (void)rotation;(void)color;assert(b==&bitmap && a->anchor==_hud_anchor_center);
    assert(interface_bitmap && final && draw_count<4 && clip);
    drawn[draw_count]=*p;drawn_scale[draw_count]=scale;drawn_multiplayer[draw_count]=in_multiplayer;
    if(clipped) assert(clip->x0!=sprite.bounds.x0); else assert(!memcmp(clip,&sprite.bounds,sizeof(*clip)));
    draw_count++;
}
/* The original draw function has locals used only by the guest stack macros. */
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wunused-variable"
#pragma clang diagnostic ignored "-Wsign-compare"
/* PRODUCTION */
#pragma clang diagnostic pop
static void reset(void) {
    memset(items,0,sizeof(items));memset(elements,0,sizeof(elements));memset(&crosshair,0,sizeof(crosshair));
    flags=64;multiplayer=1;players=1;weapon.definition_index=4;
    hud_name="weapons\\pistol\\pistol";bitmap_name="ui\\hud\\bitmaps\\combined\\hud_reticles";
    hud.parent_hud.index=NONE;hud.crosshairs=(struct tag_block){1,elements};
    crosshair.render_flags=1u<<_crosshair_state_aim;
    items[0].sequence_index=8;items[0].placement.scale.i=1.f;items[0].placement.scale.j=1.f;
    elements[0].crosshair_type=_crosshair_state_aim;elements[0].use_on_map_type=0;
    elements[0].crosshairs.items=(struct tag_block){1,items};elements[0].crosshairs.bitmap.index=200;
    for(int i=0;i<9;i++) sequences[i].sprites=(struct tag_block){1,&sprite};
}
static void draw(long index,int x,int y) {
    struct weapon_hud_crosshair_item original[2];memcpy(original,items,sizeof(items));
    struct player_datum player={20,0};struct weapon_interface_state state={0};
    draw_count=0;crosshairs_draw(&player,index,100,&state);
    if(draw_count!=1 || drawn[0].offset.x!=x || drawn[0].offset.y!=y)
        fprintf(stderr,"reticle: weapon=%ld slot=%ld flags=%u mp=%d state=%d count=%d expected=(%d,%d) actual=(%d,%d)\n",
            index,weapon.definition_index,flags,multiplayer,elements[0].crosshair_type,draw_count,x,y,
            drawn[0].offset.x,drawn[0].offset.y);
    assert(draw_count==1 && drawn[0].offset.x==x && drawn[0].offset.y==y);
    assert(drawn[0].scale.i==items[0].placement.scale.i && drawn[0].scale.j==items[0].placement.scale.j);
    assert(drawn_scale[0]==(players>1 && !items[0].placement.multiplayer_scaling_flags?.5f:1.f));
    assert(drawn_multiplayer[0]==(players>1));
    assert(!memcmp(original,items,sizeof(items))); /* Shared map tags stay immutable. */
}
int main(void) {
    for(clipped=0;clipped<=1;clipped++) {
        reset();items[0].flags=clipped?(1u<<_hud_crosshair_hide_outside_area_bit):0;
        draw(10,1,1);draw(10,1,1); /* Per-frame placement cannot accumulate. */
        assert(drawn[0].offset.x+13-(sprite.bounds.x1-sprite.bounds.x0)*.5f==0);
        assert(drawn[0].offset.y+13-(sprite.bounds.y1-sprite.bounds.y0)*.5f==0);
        flags=0;draw(10,0,0);flags=64;
        multiplayer=0;draw(10,0,0);multiplayer=1;
        for(int slot=0;slot<16;slot++) if(slot!=4) { weapon.definition_index=slot;draw(10,0,0); }
        weapon.definition_index=4;draw(NONE,0,0);
        items[0].placement.offset.x=1;items[0].placement.offset.y=1;draw(10,1,1);
        items[0].placement.offset.x=-2;items[0].placement.offset.y=3;draw(10,-2,3);
        items[0].placement.offset.x=0;items[0].placement.offset.y=1;draw(10,0,1);
        items[0].placement.offset.x=0;items[0].placement.offset.y=0;
        players=2;draw(10,1,1);players=4;draw(10,1,1);
        items[0].placement.multiplayer_scaling_flags=1u<<_hud_dont_scale_size_bit;draw(10,0,0);
        items[0].placement.multiplayer_scaling_flags=0;players=1;
        items[0].placement.scale.i=.25f;items[0].placement.scale.j=.25f;draw(10,0,0); /* MCC-sized atlas. */
        items[0].placement.scale.i=1.f;draw(10,0,0);items[0].placement.scale.j=1.f;
        items[0].sequence_index=7;draw(10,0,0);items[0].sequence_index=8;
        crosshair.render_flags=1u<<_crosshair_state_zoom;crosshair.states[_crosshair_state_zoom].value.reference_data=1;
        items[0].flags|=1u<<_hud_crosshair_one_zoom_level_bit;
        elements[0].crosshair_type=_crosshair_state_zoom;draw(10,0,0);
    }
    clipped=0;
    char const *hud_names[]={"weapons\\pistol\\pistol", "WEAPONS\\PISTOL\\PISTOL",
        "__native_weapons\\og\\0123456789abcdef\\weapons\\pistol\\pistol",
        "__native_hud\\stock\\fedcba9876543210\\weapons\\pistol\\pistol"};
    char const *bitmap_names[]={"ui\\hud\\bitmaps\\combined\\hud_reticles",
        "UI\\HUD\\BITMAPS\\COMBINED\\HUD_RETICLES",
        "__native_weapons\\og\\0123456789abcdef\\ui\\hud\\bitmaps\\combined\\hud_reticles",
        "__native_hud\\stock\\fedcba9876543210\\ui\\hud\\bitmaps\\combined\\hud_reticles"};
    for(int h=0;h<4;h++) for(int b=0;b<4;b++) { reset();hud_name=hud_names[h];bitmap_name=bitmap_names[b];draw(10,1,1); }
    char const *invalid_huds[]={NULL,"", "maps\\custom\\pistol", "weapons\\pistol\\pistol_extra",
        "__native_hud\\stock\\0\\weapons\\pistol\\pistol",
        "__native_hud\\stock\\0123456789abcdeg\\weapons\\pistol\\pistol",
        "__native_hud\\stock\\0123456789abcdef0\\weapons\\pistol\\pistol",
        "__native_hud\\stock\\0123456789abcdef\\custom\\pistol"};
    for(size_t i=0;i<sizeof(invalid_huds)/sizeof(invalid_huds[0]);i++) { reset();hud_name=invalid_huds[i];draw(10,0,0); }
    char const *invalid_bitmaps[]={NULL,"", "custom\\hud_reticles", "ui\\hud\\bitmaps\\combined\\hud_reticles_extra",
        "__native_weapons\\og\\0123456789abcdeg\\ui\\hud\\bitmaps\\combined\\hud_reticles"};
    for(size_t i=0;i<sizeof(invalid_bitmaps)/sizeof(invalid_bitmaps[0]);i++) { reset();bitmap_name=invalid_bitmaps[i];draw(10,0,0); }
    reset(); /* Aim overlay zero shifts, later overlays keep their authored position. */
    items[1]=items[0];elements[0].crosshairs.items.count=2;
    struct player_datum player={20,0};struct weapon_interface_state state={0};
    draw_count=0;crosshairs_draw(&player,10,100,&state);
    assert(draw_count==2 && drawn[0].offset.x==1 && drawn[0].offset.y==1);
    assert(drawn[1].offset.x==0 && drawn[1].offset.y==0);
    assert(items[0].placement.offset.x==0 && items[1].placement.offset.x==0);
    reset(); /* A later aim crosshair is also independent of the stock overlay. */
    items[1]=items[0];elements[1]=elements[0];elements[1].crosshairs.items.address=&items[1];hud.crosshairs.count=2;
    draw_count=0;crosshairs_draw(&player,10,100,&state);
    assert(draw_count==2 && drawn[0].offset.x==1 && drawn[1].offset.x==0);
    return 0;
}
'''
        run_fixture(fixture.replace("/* PRODUCTION */", functions))

    def test_firing_cone_preserves_buildup_rng_and_stock(self):
        source = (ROOT / "source/items/weapons.c").read_text()
        firing = block(source, "static void trigger_create_projectiles(\n\tlong weapon_index,\n\tshort trigger_index)\n{")
        bounds = firing[firing.index("real initial_error ="):firing.index("object_placement_data_new(", firing.index("real initial_error ="))]
        cone = firing[firing.index("if (error==0.0f)"):firing.index("if (projectile_index==0)")]
        # The native-only bounds declaration starts after its opening directive.
        fixture = r'''
#include <assert.h>
#include <math.h>
#include "items/performance_precision.h"
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define NONE (-1)
#define TEST_FLAG(v,b) ((v)&(1u<<(b)))
typedef float real;
enum { _performance_option_hardcore=64, _weapon_trigger_analog_rate_of_fire_bit=0,
       _weapon_trigger_use_error_when_unzoomed_bit=1, _weapon_control_zoomed_bit=0 };
struct definition { unsigned flags; float projectile_error_angle_lower_bound,
    projectile_error_angle_upper_bound, projectile_error_inner_cone_angle; };
struct trigger { float error; };
struct weapon { long definition_index; struct { unsigned control_flags; float primary_trigger; } weapon; };
static unsigned flags;
static int multiplayer, calls;
static float sampled_inner, sampled_outer;
static unsigned performance_variant_get_flags(void *v) { (void)v;return flags; }
static void *game_engine_get_variant(void) { return 0; }
static int game_engine_running(void) { return multiplayer; }
static long weapon_definition_index_to_list_index(long i) { return i; }
static void random_vector_in_cone3d(float *in,float inner,float outer,float *out) {
    (void)in;(void)out;calls++;sampled_inner=inner;sampled_outer=outer;
}
static float fire(long slot,int controlled,short trigger_index,int zoomed,float fraction,
                  unsigned trigger_flags,float original_error) {
    struct definition definition={trigger_flags,.25f,2.0f,.1f},*trigger_definition=&definition;
    struct trigger t={fraction},*trigger=&t;
    struct weapon w={slot,{zoomed,fraction}},*weapon=&w;
    struct { float forward; } data={0};
    int precision_player=controlled;
    float error=original_error;
    calls=0;sampled_inner=sampled_outer=-1;
    /* BOUNDS */
    /* CONE */
    return error;
}
static void close_to(float a,float b) { assert(fabsf(a-b)<.000001f); }
int main(void) {
    multiplayer=1;flags=0;
    for(int slot=0;slot<16;slot++) for(int step=0;step<=4;step++) {
        float f=step*.25f;
        close_to(fire(slot,1,0,0,f,0,0),(1-f)*.25f+f*2);
        assert(calls==1);close_to(sampled_inner,.1f);
    }
    flags=64;
    for(int step=0;step<=4;step++) for(int slot=4;slot<=9;slot+=5) {
        float f=step*.25f;
        close_to(fire(slot,1,0,0,f,0,0),f*2);
        assert(calls==1);close_to(sampled_inner,0);close_to(sampled_outer,f*2);
        close_to(fire(slot,1,0,0,f,1,0),f*2);assert(calls==1);
    }
    for(int slot=0;slot<16;slot++) if(slot!=4 && slot!=9) {
        close_to(fire(slot,1,0,0,0,0,0),.25f);close_to(sampled_inner,.1f);
    }
    close_to(fire(4,1,0,1,0,0,0),0);assert(calls==1); /* pistol zoom retains rule */
    close_to(fire(9,1,0,1,0,2,0),.25f);assert(calls==0); /* scoped sniper unchanged */
    close_to(fire(4,0,0,0,0,0,0),.25f);close_to(sampled_inner,.1f); /* AI */
    close_to(fire(4,1,1,0,0,0,0),.25f);close_to(sampled_inner,.1f); /* secondary */
    close_to(fire(NONE,1,0,0,0,0,0),.25f); /* missing globals role */
    multiplayer=0;
    close_to(fire(4,1,0,0,0,0,0),.25f);close_to(sampled_inner,.1f); /* campaign */
    multiplayer=1;
    close_to(fire(4,0,0,0,0,0,.75f),.75f); /* existing actor aim error */
    return 0;
}
'''
        # This closing #endif belongs to the opening native directive in weapons.c.
        bounds = "#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS\n" + bounds
        run_fixture(fixture.replace("/* BOUNDS */", bounds).replace("/* CONE */", cone))

    def test_host_preference_gates_late_joins_but_preserves_lobby(self):
        source = (ROOT / "source/networking/network_server_manager.c").read_text()
        functions = "\n".join(block(source, signature) for signature in (
            "boolean network_game_server_game_is_open(\n",
            "boolean network_game_server_accepts_late_joins(\n"))
        fixture = r'''
#include <assert.h>
#include <string.h>
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define TRUE 1
#define FALSE 0
#define TEST_FLAG(v,b) (((v)&(1u<<(b)))!=0)
#define match_assert(f,l,c) assert(c)
#define NETWORK_SERVER_MANAGER_FILE "fixture"
typedef int boolean;
enum { _network_game_server_game_open_bit=0, _network_game_server_state_pregame=1,
       _network_game_server_state_ingame=2, _network_game_server_state_postgame=3 };
struct network_game_server { unsigned flags; int state,sent_start_game_message; struct { int free; } game; };
static int allow=1;
static int config_boolean(const char *key) { assert(!strcmp(key,"network.join_in_progress"));return allow; }
static int network_game_has_free_player_slot(const void *g) { return ((const int *)g)[0]; }
/* PRODUCTION */
int main(void) {
    struct network_game_server server={1,1,0,{1}};
    for(allow=0;allow<=1;allow++) {
        server.state=1;server.sent_start_game_message=0;
        assert(network_game_server_game_is_open(&server));
        assert(!network_game_server_accepts_late_joins(&server));
        server.sent_start_game_message=1;
        assert(!network_game_server_game_is_open(&server));
        server.state=2;server.sent_start_game_message=0;
        assert(network_game_server_game_is_open(&server)==allow);
        assert(network_game_server_accepts_late_joins(&server)==allow);
        server.game.free=0;assert(!network_game_server_accepts_late_joins(&server));server.game.free=1;
        server.flags=0;assert(!network_game_server_game_is_open(&server));
        assert(!network_game_server_accepts_late_joins(&server));server.flags=1;
        server.state=3;assert(!network_game_server_game_is_open(&server));
        assert(!network_game_server_accepts_late_joins(&server));
    }
    return 0;
}
'''
        run_fixture(fixture.replace("/* PRODUCTION */", functions))

    def test_queued_and_extra_seat_additions_recheck_preference(self):
        source = (ROOT / "source/networking/network_server_manager.c").read_text()
        function = block(source, "static boolean network_game_server_machine_may_add_player_ingame(\n")
        fixture = r'''
#include <assert.h>
#include <string.h>
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define TRUE 1
#define FALSE 0
#define MAXIMUM_NETWORK_MACHINE_COUNT 4
#define MAXIMUM_INGAME_ADDITIONS_PER_ADDRESS 16
#define VALID_INDEX(i,n) ((i)>=0 && (i)<(n))
#define network_event(...) ((void)0)
typedef int boolean;
enum { _network_game_server_state_ingame=2 };
struct machine { int local; };
struct network_game_server { int state; struct machine client_machines[4]; };
static unsigned long network_game_server_client_machine_addresses[4];
static short additions;
static int allow=1;
static int config_boolean(const char *key) { assert(!strcmp(key,"network.join_in_progress"));return allow; }
static int network_game_server_client_machine_is_local(struct network_game_server *s,struct machine *m) { (void)s;return m->local; }
static short *network_game_server_ingame_addition_count(unsigned long address,int create) { (void)address;(void)create;return &additions; }
/* PRODUCTION */
int main(void) {
    struct network_game_server server={2,{{1},{0},{0},{0}}};
    assert(network_game_server_machine_may_add_player_ingame(&server,0));
    assert(network_game_server_machine_may_add_player_ingame(&server,1));
    allow=0;
    assert(!network_game_server_machine_may_add_player_ingame(&server,0));
    assert(!network_game_server_machine_may_add_player_ingame(&server,1));
    /* In-flight queues use this guard at consumption, not their enqueue time. */
    allow=1;
    assert(network_game_server_machine_may_add_player_ingame(&server,1));
    additions=16;
    assert(!network_game_server_machine_may_add_player_ingame(&server,1));
    assert(network_game_server_machine_may_add_player_ingame(&server,0));
    allow=0;server.state=1;additions=0;
    assert(network_game_server_machine_may_add_player_ingame(&server,1));
    return 0;
}
'''
        run_fixture(fixture.replace("/* PRODUCTION */", function))


if __name__ == "__main__":
    unittest.main()
