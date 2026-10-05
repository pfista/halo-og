"""Exercise the production firing cone and shared host admission gate."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


def run_fixture(text):
    with tempfile.TemporaryDirectory(prefix="halo-meeting-gameplay-") as temporary:
        source = Path(temporary) / "fixture.c"
        binary = source.with_suffix("")
        source.write_text(text)
        subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", "-I", str(ROOT / "source"),
                        str(source), "-lm", "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


class MeetingGameplayTests(unittest.TestCase):
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
