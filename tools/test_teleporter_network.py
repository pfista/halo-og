"""Exercise production teleport and reconciliation functions with authored flags.

These native fixtures cover packet ordering and the original destination latch;
they do not prove retail parity or socket transport. No map/game assets are used.
The guest's C long is 32 bits, so extracted functions use int32_t on LP64 hosts.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
typedef unsigned char byte, boolean;
typedef unsigned short word;
typedef float real;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 4
#define MAXIMUM_TRACKED_PLAYERS 4
#define MAXIMUM_LOCAL_PLAYERS 2
#define OWN_POSITION_TICKS 64
#define NUMBER_OF_PLAYER_POWERUPS 2
#define PREDICTION_ECHO_TICKS 3
#define NO_PLAYER 255
#define LOCAL_CORRECTION_TOLERANCE 3.0f
#define UNIT_WORLD_BOUND 4096.0f
#define DISTRIBUTED_UNIT_SCALE 32767.0f
#define DISTRIBUTED_VELOCITY_SCALE 1024.0f
#define FLAG(bit) (1U<<(bit))
#define TEST_FLAG(value,bit) ((value)&FLAG(bit))
#define SET_FLAG(value,bit,set) ((value)=(set)?((value)|FLAG(bit)):((value)&~FLAG(bit)))
#define csmemset memset
#define csmemcpy memcpy
#define DATUM_INDEX_TO_ABSOLUTE_INDEX(index) ((index)&0xFFFF)
#define DATUM_INDEX_NEW(index,identifier) (((uint32_t)(identifier)<<16)|((index)&0xFFFF))
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->address)[i])
enum { _game_connection_local, _game_connection_network_client, _game_connection_network_server };
enum { _netgame_flag_teleporter_source=6, _netgame_flag_teleporter_target=7 };
/* UNIT_FLAGS */
enum { _distributed_unit_camouflaged_bit=0,_distributed_unit_super_camouflaged_bit=1,
       _unit_active_camouflaged_bit=0,_unit_super_camouflaged_bit=1,
       _object_mask_unit=3,_multiplayer_sound_teleporter_activate=27 };
struct scenario_netgame_flag { real_point3d position; real facing; short type,team_index; };
struct scenario { struct { int32_t count; void *address; } netgame_flags; };
struct player_datum { int32_t unit_index,teleporter_index; short local_player_index,identifier; boolean is_blocking_teleporter; int32_t telefrag_timeout; short powerup_durations[NUMBER_OF_PLAYER_POWERUPS]; };
struct object_data { real_point3d position; real_vector3d forward,up,translational_velocity; short type; int32_t parent_object_index; };
struct object_datum { struct object_data object; };
struct unit_datum { struct object_data object; struct { int32_t player_index; short parent_seat_index; real active_camouflage; byte flags; } unit; };
struct distributed_vector { short i,j,k; };
/* UNIT_STATE */
struct damage_network_state { boolean shield_depleted,shield_charging,shield_over_charging; real body_vitality,shield_vitality,current_body_damage,recent_body_damage,current_shield_damage,recent_shield_damage; };
struct collision_feature_list { byte unused; };
struct collision_plane { int32_t object_index; };
struct screen_flash_definition { int32_t fade_function,type,priority; real duration,max_intensity,zero_scale_factor; struct { real alpha,red,green,blue; } screen_flash_color; };
/* HISTORY */
/* SEQUENCES */
static struct { boolean valid; int32_t taken_host_time,taken_time; } distributed_predictions[MAXIMUM_TRACKED_PLAYERS];
static struct distributed_death { boolean valid,friendly_fire,killed_by_vehicle; int32_t killing_player_index; } distributed_deaths[MAXIMUM_TRACKED_PLAYERS];
static struct { boolean valid; } distributed_accepted[MAXIMUM_TRACKED_PLAYERS];
static struct { int32_t unit_index; } distributed_host_speeds[MAXIMUM_TRACKED_PLAYERS];
static struct { unsigned corrections; } distributed_statistics;
static real distributed_own_round_trip;
static struct player_datum player;
static struct unit_datum unit;
static struct scenario scenario;
static struct scenario_netgame_flag flags[4];
static int32_t now;
static short connection;
static unsigned teleports;
static unsigned input_delay_resets[MAXIMUM_LOCAL_PLAYERS];
static real_vector3d input_delay_reset_facings[MAXIMUM_LOCAL_PLAYERS];
static void update_queues_reset_local_input_delay(short local_player_index,real_vector3d const *new_facing) {
    if(local_player_index>=0 && local_player_index<MAXIMUM_LOCAL_PLAYERS) {
        input_delay_resets[local_player_index]++;
        assert(new_facing);input_delay_reset_facings[local_player_index]=*new_facing;
    }
}
static short game_connection(void) { return connection; }
static int32_t game_time_get(void) { return now; }
static struct player_datum *player_get(int32_t index) { assert(index==0); return &player; }
static struct player_datum *distributed_player(short index) { return index==0 ? &player : NULL; }
static int32_t distributed_living_unit(struct player_datum *p) { return p ? p->unit_index : NONE; }
static struct unit_datum *unit_get(int32_t index) { assert(index==1); return &unit; }
static struct object_datum *object_get(int32_t index) { assert(index==1); return (struct object_datum *)&unit; }
static struct scenario *global_scenario_get(void) { return &scenario; }
static real distance_squared3d(const real_point3d *a,const real_point3d *b) { real x=a->x-b->x,y=a->y-b->y,z=a->z-b->z; return x*x+y*y+z*z; }
static real arctangent(real j,real i) { return atan2f(j,i); }
static real cosine(real a) { return cosf(a); }
static real sine(real a) { return sinf(a); }
static void normalize3d(real_vector3d *v) { real length=sqrtf(v->i*v->i+v->j*v->j+v->k*v->k); assert(length>0); v->i/=length; v->j/=length; v->k/=length; }
static void object_set_position(int32_t index,const real_point3d *p,const real_vector3d *f,const real_vector3d *u) { assert(index==1); unit.object.position=*p; if(f)unit.object.forward=*f; if(u)unit.object.up=*u; }
static void biped_get_physics_pill(int32_t i,real_point3d *p,real *h,real *r) { assert(i==1); *p=unit.object.position; *h=0.5f; *r=0.1f; }
static boolean collision_get_features_in_sphere(int32_t f,const real_point3d *p,real s,real h,real r,int32_t i,struct collision_feature_list *l) { (void)f;(void)p;(void)s;(void)h;(void)r;(void)i;(void)l; return FALSE; }
static boolean collision_features_test_point(const struct collision_feature_list *f,const real_point3d *p,struct collision_plane *r) { (void)f;(void)p;(void)r; assert(0); return FALSE; }
static int32_t tag_loaded(int32_t group,const char *path) { (void)group;(void)path; return NONE; }
static const wchar_t *unicode_string_list_get_string(int32_t i,short s) { (void)i;(void)s; return L""; }
static short unit_get_local_player_index(int32_t i) { assert(i==1); return player.local_player_index; }
static void hud_print_message(short i,const wchar_t *m) { (void)i;(void)m; }
static void game_engine_play_multiplayer_sound(short s) { assert(s==27); teleports++; }
static void player_effect_screen_flash(int32_t i,const struct screen_flash_definition *s,real a) { (void)i;(void)s;(void)a; }
static void player_control_set_facing(short i,const real_vector3d *f) { (void)i;(void)f; }
static void console_printf(boolean b,const char *f,...) { (void)b;(void)f; assert(0); }
static void distributed_vector_unpack(const struct distributed_vector *p,real scale,real_vector3d *v) { v->i=p->i/scale; v->j=p->j/scale; v->k=p->k/scale; }
static void distributed_vector_pack(const real_vector3d *v,real scale,struct distributed_vector *p) { p->i=(short)(v->i*scale);p->j=(short)(v->j*scale);p->k=(short)(v->k*scale); }
static word distributed_vitality_pack(real v) { return (word)(v*16384); }
static void damage_get_network_state(int32_t i,struct damage_network_state *damage) { assert(i==1); memset(damage,0,sizeof(*damage));damage->body_vitality=damage->shield_vitality=1; }
static boolean distributed_point_valid(const real_point3d *p,real bound) { return isfinite(p->x)&&isfinite(p->y)&&isfinite(p->z)&&fabsf(p->x)<=bound&&fabsf(p->y)<=bound&&fabsf(p->z)<=bound; }
static boolean distributed_axes_make_valid(real_vector3d *f,real_vector3d *u) { (void)f;(void)u; return TRUE; }
static boolean network_objects_reconcile(int32_t i,const real_point3d *p,const real_vector3d *f,const real_vector3d *u,const real_vector3d *v,const real_vector3d *a,real blend) { (void)v;(void)a; assert(blend==0); object_set_position(i,p,f,u); return TRUE; }
/* FUNCTIONS */
'''

HARNESS = r'''
static void reset(void) {
    memset(&player,0,sizeof(player)); memset(&unit,0,sizeof(unit));
    memset(distributed_own_positions,0,sizeof(distributed_own_positions));
    memset(distributed_own_teleport_sequences,0,sizeof(distributed_own_teleport_sequences));
    memset(distributed_predictions,0,sizeof(distributed_predictions));
    memset(distributed_accepted,0,sizeof(distributed_accepted));
    memset(distributed_host_speeds,0,sizeof(distributed_host_speeds));
    scenario.netgame_flags.count=4; scenario.netgame_flags.address=flags;
    flags[0]=(struct scenario_netgame_flag){{0,0,0},0,6,0};
    flags[1]=(struct scenario_netgame_flag){{10,0,0},0,7,0};
    flags[2]=(struct scenario_netgame_flag){{10,0,0},0,6,1};
    flags[3]=(struct scenario_netgame_flag){{0,0,0},0,7,1};
    player.unit_index=1; player.local_player_index=0; player.teleporter_index=NONE;
    unit.object.forward.i=1; unit.object.up.k=1; unit.unit.player_index=0;
    unit.object.parent_object_index=NONE;unit.unit.parent_seat_index=NONE;
    now=100; connection=_game_connection_network_client; teleports=0;
    memset(input_delay_resets,0,sizeof(input_delay_resets));
    memset(input_delay_reset_facings,0,sizeof(input_delay_reset_facings));
    for(short i=0;i<OWN_POSITION_TICKS;i++)distributed_own_positions[0][i].unit_index=NONE;
}
static struct distributed_unit_state state(real x,short predicted) {
    struct distributed_unit_state s={0}; s.unit_index=1; s.position.x=x;
    s.forward.i=32767; s.up.k=32767;
    if(predicted!=NONE){s.flags=FLAG(_distributed_unit_predicted_bit);s.predicted_time=predicted;}
    return s;
}
static void record(int32_t time,real x) {
    struct distributed_own_position *own=&distributed_own_positions[0][time&(OWN_POSITION_TICKS-1)];
    own->time=time;own->unit_index=1;own->position=(real_point3d){x,0,0};
    own->teleport_sequence=distributed_own_teleport_sequences[0];
}
static void predicted_teleport(void) {
    reset(); record(98,0); game_engine_update_teleporter(0);
    assert(unit.object.position.x==10 && player.teleporter_index==2);
    assert(input_delay_resets[0]==1 && input_delay_resets[1]==0);
    struct distributed_unit_state old=state(0,98);
    distributed_correct_own_unit(&player,1,&old);
    assert(unit.object.position.x==10); /* An old prediction echo must not undo the local jump. */
    struct distributed_unit_state destination=state(10,98);
    distributed_correct_own_unit(&player,1,&destination);
    printf("predicted teleport reconciliation: x=%g, latch=%d\n",unit.object.position.x,player.teleporter_index);
    assert(unit.object.position.x==10); /* Before the fix this adds 10 twice and produces x=20. */
    game_engine_update_teleporter(0);
    assert(unit.object.position.x==10 && teleports==1);
    destination=state(10,NONE); distributed_correct_own_unit(&player,1,&destination);
    for(int i=0;i<10;i++) {
        distributed_correct_own_unit(&player,1,&destination);game_engine_update_teleporter(0);
        assert(unit.object.position.x==10 && teleports==1);
    }
}
static void authoritative_teleport(void) {
    reset(); record(98,0); /* Host traversed first; the client has not yet predicted it. */
    struct distributed_unit_state destination=state(10,NONE);
    distributed_correct_own_unit(&player,1,&destination);
    assert(input_delay_resets[0]==1 && input_delay_resets[1]==0);
    game_engine_update_teleporter(0);
    printf("authoritative teleport reconciliation: x=%g, latch=%d\n",unit.object.position.x,player.teleporter_index);
    assert(unit.object.position.x==10 && player.teleporter_index==2 && teleports==0);
    destination=state(10,98); distributed_correct_own_unit(&player,1,&destination);
    assert(unit.object.position.x==10); /* The host-first jump also ends old history. */
}
static void original_latch(void) {
    reset(); connection=_game_connection_local; game_engine_update_teleporter(0);
    assert(unit.object.position.x==10 && player.teleporter_index==2 && teleports==1);
    for(int i=0;i<10;i++)game_engine_update_teleporter(0);
    assert(unit.object.position.x==10 && teleports==1);
    unit.object.position.x=11.0f; game_engine_update_teleporter(0);
    assert(player.teleporter_index==2); /* Original comparison is >1.0, not >=1.0. */
    unit.object.position.x=11.01f; game_engine_update_teleporter(0); assert(player.teleporter_index==NONE);
    unit.object.position.x=10.51f; game_engine_update_teleporter(0); assert(teleports==1);
    unit.object.position.x=10.5f; game_engine_update_teleporter(0);
    assert(unit.object.position.x==0 && teleports==2 && player.teleporter_index==0);
}
static void host_reset(void) {
    reset(); connection=_game_connection_network_server;
    distributed_predictions[0].valid=TRUE; distributed_predictions[0].taken_host_time=99;
    distributed_predictions[0].taken_time=97;
    distributed_accepted[0].valid=TRUE; distributed_host_speeds[0].unit_index=1;
    struct distributed_unit_state packed;
    distributed_state_from_player(0,&packed);
    assert(TEST_FLAG(packed.flags,_distributed_unit_predicted_bit) && packed.predicted_time==98);
    game_engine_update_teleporter(0);
    assert(distributed_predictions[0].taken_host_time==NONE);
    assert(!distributed_predictions[0].valid && !distributed_accepted[0].valid);
    assert(distributed_host_speeds[0].unit_index==NONE);
    assert(input_delay_resets[0]==1 && input_delay_resets[1]==0);
    distributed_state_from_player(0,&packed);
    assert(!TEST_FLAG(packed.flags,_distributed_unit_predicted_bit));
    assert(packed.position.x==10 && packed.unit_index==1);
}
static void ordinary_correction(void) {
    reset(); record(98,100); record(99,101); unit.object.position.x=102;
    struct distributed_unit_state s=state(104,98);
    distributed_correct_own_unit(&player,1,&s);
    assert(unit.object.position.x==106); /* Keep the two units moved since the echo's tick. */
    assert(distributed_own_positions[0][98&(OWN_POSITION_TICKS-1)].position.x==104);
    assert(distributed_own_positions[0][99&(OWN_POSITION_TICKS-1)].position.x==105);
    assert(player.teleporter_index==NONE);
}
static void unrelated_relocation(void) {
    reset();
    /* There is a source at 10, but source 0's target is now at 30. */
    flags[1].position.x=30;
    struct distributed_unit_state s=state(10,NONE);
    distributed_correct_own_unit(&player,1,&s);
    assert(unit.object.position.x==10 && player.teleporter_index==NONE);
}
static void history_segments(void) {
    reset(); record(98,0); game_engine_update_teleporter(0); record(99,10);
    unit.object.position.x=11;
    struct distributed_unit_state s=state(14,99);
    distributed_correct_own_unit(&player,1,&s);
    assert(unit.object.position.x==15);
    assert(distributed_own_positions[0][99&(OWN_POSITION_TICKS-1)].position.x==14);
    assert(distributed_own_positions[0][98&(OWN_POSITION_TICKS-1)].position.x==0);
}
static void delayed_source_echo(void) {
    reset(); record(60,-4); game_engine_update_teleporter(0); record(99,10);
    struct distributed_unit_state old=state(0,60);
    distributed_correct_own_unit(&player,1,&old);
    assert(unit.object.position.x==10 && player.teleporter_index==2);
    game_engine_update_teleporter(0); assert(unit.object.position.x==10 && teleports==1);
    struct distributed_unit_state current=state(14,99);
    distributed_correct_own_unit(&player,1,&current);
    assert(unit.object.position.x==14); /* Fresh prediction echoes still correct. */
}
static void authoritative_rollback(void) {
    reset(); record(60,-4); game_engine_update_teleporter(0); record(99,10);
    struct distributed_unit_state rollback=state(0,NONE);
    distributed_correct_own_unit(&player,1,&rollback);
    assert(unit.object.position.x==0 && player.teleporter_index==0);
    game_engine_update_teleporter(0); assert(unit.object.position.x==0 && teleports==1);
    struct distributed_unit_state old=state(0,99);
    distributed_correct_own_unit(&player,1,&old);
    assert(unit.object.position.x==0); /* An old B-segment echo cannot move past A. */
    rollback=state(-4,NONE); distributed_correct_own_unit(&player,1,&rollback);
    assert(unit.object.position.x==-4); /* General authoritative corrections remain enabled. */
}
static void targeted_input_delay_reset(void) {
    for(short role=_game_connection_local; role<=_game_connection_network_server; role++) {
        reset(); connection=role; player.local_player_index=1;
        unit.object.forward=(real_vector3d){0,1,0};
        network_distributed_player_teleported(0);
        assert(input_delay_resets[0]==0 && input_delay_resets[1]==1);
        assert(input_delay_reset_facings[1].i==0 && input_delay_reset_facings[1].j==1);
        player.local_player_index=NONE;
        network_distributed_player_teleported(0);
        assert(input_delay_resets[0]==0 && input_delay_resets[1]==1);
    }
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"predicted"))predicted_teleport();
    else if(!strcmp(argv[1],"authoritative"))authoritative_teleport();
    else if(!strcmp(argv[1],"latch"))original_latch();
    else if(!strcmp(argv[1],"host"))host_reset();
    else if(!strcmp(argv[1],"ordinary"))ordinary_correction();
    else if(!strcmp(argv[1],"unrelated"))unrelated_relocation();
    else if(!strcmp(argv[1],"history"))history_segments();
    else if(!strcmp(argv[1],"delayed"))delayed_source_echo();
    else if(!strcmp(argv[1],"rollback"))authoritative_rollback();
    else if(!strcmp(argv[1],"input-delay-reset"))targeted_input_delay_reset();
    else assert(0);
    return 0;
}
'''


def fixture(engine, network):
    history = block(network, "static struct distributed_own_position\n")
    history += " distributed_own_positions[MAXIMUM_LOCAL_PLAYERS][OWN_POSITION_TICKS];"
    if "teleport_sequence;" not in history:
        history = history.replace("real_point3d position;", "real_point3d position; unsigned long teleport_sequence;")
    sequences = "static unsigned long distributed_own_teleport_sequences[MAXIMUM_LOCAL_PLAYERS];"
    hook = "void network_distributed_player_teleported(long player_index) { (void)player_index; }"
    if "void network_distributed_player_teleported(" in network:
        hook = block(network, "void network_distributed_player_teleported(")
    latch = ""
    if "static void distributed_restore_teleporter_latch(" in network:
        latch = block(network, "static void distributed_restore_teleporter_latch(")
    functions = [block(engine, "long find_netgame_flags("), block(engine, "long find_netgame_flag("),
                 hook, latch, block(network, "static boolean distributed_apply_state("),
                 block(network, "static void distributed_correct_own_unit("),
                 block(engine, "static void game_engine_update_teleporter(\n\tlong player_index)\n{")]
    # Strip only guest-width primitive spellings, never control flow.
    functions.insert(2, block(network,"static void distributed_state_from_player("))
    unit_flags = block(network,"enum\n{\n\t/* the player has a unit that is alive */") + ";"
    unit_state = block(network,"struct distributed_unit_state\n") + ";"
    result = PREFIX.replace("/* HISTORY */", history).replace("/* SEQUENCES */", sequences)
    result = result.replace("/* UNIT_FLAGS */",unit_flags).replace("/* UNIT_STATE */",unit_state)
    result = result.replace("/* FUNCTIONS */", "\n\n".join(functions)) + HARNESS
    result = re.sub(r"\bunsigned\s+long\b", "uint32_t", result)
    return re.sub(r"\blong\b", "int32_t", result)


class TeleporterNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-teleporter-")
        work = Path(cls.temporary.name)
        c = work / "fixture.c"
        c.write_text(fixture((ROOT / "source/game/game_engine.c").read_text(),
                             (ROOT / "port/linux/game/network_distributed.c").read_text()))
        cls.binary = work / ("fixture.exe" if sys.platform == "win32" else "fixture")
        compiler=shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A native C compiler is required")
        math_library=[] if sys.platform=="win32" else ["-lm"]
        compiled=subprocess.run([compiler, "-std=c11", "-Werror=implicit-function-declaration", "-Wno-multichar",
                                 str(c), *math_library, "-o", str(cls.binary)], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout+compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_prediction_echo_does_not_repeat_teleport(self):
        self.run_case("predicted")

    def test_host_relocation_sets_original_destination_latch(self):
        self.run_case("authoritative")

    def test_original_exit_and_trigger_radii(self):
        self.run_case("latch")

    def test_host_discards_pre_teleport_echo_and_anchor(self):
        self.run_case("host")

    def test_ordinary_prediction_keeps_motion_since_echo(self):
        self.run_case("ordinary")

    def test_unrelated_relocation_does_not_block_nearby_source(self):
        self.run_case("unrelated")

    def test_corrections_do_not_translate_history_across_teleport(self):
        self.run_case("history")

    def test_nonzero_delayed_source_echo_does_not_undo_teleport(self):
        self.run_case("delayed")

    def test_authoritative_rollback_remains_enabled(self):
        self.run_case("rollback")

    def test_teleport_resets_only_the_affected_local_controller_in_every_role(self):
        self.run_case("input-delay-reset")


if __name__ == "__main__":
    unittest.main()
