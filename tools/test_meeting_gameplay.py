"""Exercise the production host admission and player-addition gates."""
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
