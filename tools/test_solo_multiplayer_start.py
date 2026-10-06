"""Exercise production solo lobby readiness, request authorization and countdowns.

Production playlist setup, timer, pregame idle and start-message functions run
against controlled connections, precache state and message encoding. This checks
the host's actual start transition without sockets, game assets or retail parity.
Guest C long is fixed to int32_t for execution on LP64 hosts.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import block, constant

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
typedef unsigned char boolean, byte;
typedef uint16_t word;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define VALID_INDEX(i,n) ((i)>=0 && (i)<(n))
#define FLAG(n) (1U<<(n))
#define TEST_FLAG(flags,bit) (((flags)&FLAG(bit))!=0)
#define csmemset memset
#define csmemcpy memcpy
#define ustrncpy wcsncpy
#define NETWORK_SERVER_MANAGER_FILE "fixture"
#define match_assert(file,line,condition) assert(condition)
#define network_event(...) ((void)0)
#define error(...) ((void)0)
#define MAXIMUM_NETWORK_MACHINE_COUNT 4
#define MAXIMUM_NETWORK_PLAYER_COUNT 16
#define NUMBER_OF_MULTIPLAYER_TEAMS 2
#define MAXIMUM_MACHINE_NAME_LENGTH 32
#define NETWORK_GAME_NAME_LENGTH 16
#define MILLISECONDS_PER_SECOND 1000
#define NETWORK_GAME_SERVER_PLAYERLESS_MACHINE_TIMEOUT 15000
#define NETWORK_GAME_SERVER_MAXIMUM_WAIT_TIME_FOR_LEVEL_LOADING 60000
#define NETWORK_GAME_MESSAGE_VERSION 1
enum { _network_client_machine_connected_bit=0, _network_client_machine_level_loaded_bit=2,
    _network_client_machine_precached_bit=3, _message_server_begin_game=10,
    _message_server_pregame_countdown=11, _message_server_pregame_keep_alive=12,
    _message_client_game_start_request=13, _network_game_packet_class_client_pregame=14,
    _rejection_code_game_is_closed=15, _rejection_code_game_is_full=16 };
/* DECLARATIONS */
struct network_connection { boolean active; };
struct game_variant { struct { boolean teams; } universal_variant; };
struct network_player { short machine_index, team_index; boolean valid; };
struct network_game {
    struct game_variant variant;
    struct { int unused; } variant_options;
    struct { char name[128]; int version; } map;
    wchar_t name[16];
    short player_count, minimum_players, maximum_players, maximum_teams;
    struct network_player players[MAXIMUM_NETWORK_PLAYER_COUNT];
};
struct network_game_server_client_machine {
    struct network_connection *connection;
    short machine_index;
    word flags;
    boolean joined, local;
};
struct network_game_server {
    struct network_game game;
    struct network_game_server_client_machine client_machines[MAXIMUM_NETWORK_MACHINE_COUNT];
    struct network_game_server_countdown_state countdown_state;
    short state;
    boolean sent_start_game_message;
    int32_t next_update_number, time_of_last_keep_alive;
    uint32_t time_of_first_client_loading_completion;
};
struct network_message { short kind; };
static struct network_game_server server;
static struct network_connection connections[MAXIMUM_NETWORK_MACHINE_COUNT];
static struct game_variant playlist_variant;
static struct network_player network_game_server_start_players[MAXIMUM_NETWORK_PLAYER_COUNT];
static boolean network_game_server_started_with_five_players;
static boolean network_game_server_countdown_slowed[MAXIMUM_NETWORK_MACHINE_COUNT];
static uint32_t network_game_server_client_machine_join_times[MAXIMUM_NETWORK_MACHINE_COUNT];
static boolean split_screen, decode_ok, map_precached;
static uint32_t now;
static unsigned opened, settings_sends, begin_sends, countdown_sends, flushes;
static short last_countdown;
static boolean network_game_is_splitscreen_local(void) { return split_screen; }
static boolean network_game_should_accept_remote_connections(void) { return !split_screen; }
static uint32_t system_milliseconds(void) { return now; }
static boolean network_player_is_valid(struct network_player const *p) { return p->valid; }
static boolean network_game_server_client_machine_is_joined_to_game(
    struct network_game_server *s, struct network_game_server_client_machine *m) { (void)s; return m->joined; }
static boolean network_game_server_client_machine_is_local(
    struct network_game_server *s, struct network_game_server_client_machine *m) { (void)s; return m->local; }
static short network_game_server_get_state(struct network_game_server *s, short *data) { assert(!data); return s->state; }
static boolean decode_network_game_message(void *record, word *message, short *size,
    short *type, short *version, short packet_class) {
    assert(*size==sizeof(word) && *type==_message_client_game_start_request &&
        *version==NETWORK_GAME_MESSAGE_VERSION && packet_class==_network_game_packet_class_client_pregame);
    if (!decode_ok) return FALSE;
    /* The codec writes only the wire short into countdown_time. */
    ((struct message_client_game_start_request *)record)->countdown_time=(int32_t)(0x12340000U|*message);
    return TRUE;
}
static unsigned performance_variant_get_flags(struct game_variant const *v) { (void)v; return 0; }
static boolean network_game_server_performance_peers_support(struct network_game_server *s,unsigned flags) {
    (void)s; assert(!flags); return TRUE;
}
static boolean network_game_server_original_grenade_peers_support(struct network_game_server *s,
    struct game_variant *v,short count) { (void)s; (void)v; (void)count; return TRUE; }
static void performance_options_apply_host_flags(unsigned flags) { assert(!flags); }
static boolean game_engine_get_current_stage(struct game_variant *v,char *map) {
    *v=playlist_variant; strcpy(map,"levels\\test\\bloodgulch\\bloodgulch"); return TRUE;
}
static void network_game_generate_local_machine_name(wchar_t *name) { wcscpy(name,L"fixture"); }
static void game_variant_options_default(struct game_variant *v,void *options) { (void)v; (void)options; }
static void network_game_server_open_game(struct network_game_server *s) { assert(s==&server); opened++; }
static boolean network_game_server_send_game_settings_to_all_machines(struct network_game_server *s,void *g,unsigned size) {
    assert(s==&server && g==&s->game && size==sizeof(s->game)); settings_sends++; return TRUE;
}
static struct network_message *create_network_game_message(short kind,void *record,unsigned size) {
    static struct network_message message;
    if (kind==_message_server_begin_game) assert(size==sizeof(struct message_server_begin_game));
    else if (kind==_message_server_pregame_countdown) {
        assert(size==sizeof(struct message_server_pregame_countdown));
        last_countdown=((struct message_server_pregame_countdown *)record)->seconds_to_start;
    } else assert(kind==_message_server_pregame_keep_alive);
    message.kind=kind; return &message;
}
static boolean network_game_server_send_message_to_all_machines(struct network_game_server *s,struct network_message *m) {
    assert(s==&server && m);
    if(m->kind==_message_server_begin_game) begin_sends++;
    else if(m->kind==_message_server_pregame_countdown) countdown_sends++;
    return TRUE;
}
static void network_game_server_flush_game_data_pregame(struct network_game_server *s) { assert(s==&server); flushes++; }
static boolean network_connection_active(struct network_connection *c) { return c->active; }
static boolean network_game_server_remove_client_machine_from_game(struct network_game_server *s,
    struct network_game_server_client_machine *m) { (void)s; (void)m; assert(0); return FALSE; }
static boolean network_game_has_free_player_slot(struct network_game *g) { return g->player_count<MAXIMUM_NETWORK_PLAYER_COUNT; }
static void network_game_server_refuse_late_joiner(struct network_game_server *s,
    struct network_game_server_client_machine *m,short rejection) { (void)s; (void)m; (void)rejection; assert(0); }
static boolean cache_files_precache_map_loaded(char const *name) { assert(name); return map_precached; }
static char const *main_get_multiplayer_map_name(void) { return "bloodgulch"; }
static void network_game_server_all_machines_have_loaded(struct network_game_server *s) { (void)s; assert(0); }
/* FUNCTIONS */
'''

HARNESS = r'''
static void machine(short index,boolean local) {
    connections[index].active=TRUE;
    server.client_machines[index]=(struct network_game_server_client_machine){
        &connections[index],index,FLAG(_network_client_machine_connected_bit)|FLAG(_network_client_machine_precached_bit),TRUE,local};
}
static void player(short index,short machine_index,short team) {
    assert(!server.game.players[index].valid);
    server.game.players[index]=(struct network_player){machine_index,team,TRUE};
    server.game.player_count++;
}
static void reset(boolean split,boolean teams) {
    memset(&server,0,sizeof(server)); memset(connections,0,sizeof(connections));
    memset(network_game_server_countdown_slowed,0,sizeof(network_game_server_countdown_slowed));
    memset(network_game_server_client_machine_join_times,0,sizeof(network_game_server_client_machine_join_times));
    memset(network_game_server_start_players,0,sizeof(network_game_server_start_players));
    now=100; split_screen=split; decode_ok=map_precached=TRUE;
    opened=settings_sends=begin_sends=countdown_sends=flushes=0; last_countdown=NONE;
    network_game_server_started_with_five_players=FALSE;
    playlist_variant.universal_variant.teams=teams;
    assert(network_game_server_setup_game_from_playlist(&server));
    assert(opened==1 && server.game.maximum_players==MAXIMUM_NETWORK_PLAYER_COUNT);
    assert(server.game.maximum_teams==(teams?2:1));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(server.game.minimum_players==1);
#else
    assert(server.game.minimum_players==2);
#endif
    machine(0,TRUE);
}
static void request(short machine_index,short event) {
    word message[]={0,(word)event};
    assert(network_game_server_handle_message_client_game_start_request(&server,
        &server.client_machines[machine_index],message,sizeof(message)));
}
static void tick(uint32_t elapsed) {
    now+=elapsed; assert(network_game_server_idle_pregame_tasks(&server));
    /* Every fixture lobby has fewer than five players when it starts. */
    if (server.sent_start_game_message) assert(!network_game_server_started_with_five_players);
}
static void ready(void) {
    assert(server_has_enough_machines(&server));
    assert(server_has_a_player_on_each_machine(&server));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(server.game.player_count==1 || !server_needs_more_teams(&server));
#else
    assert(!server_needs_more_teams(&server));
#endif
    assert(server_ok_to_countdown(&server));
    assert(network_game_server_game_can_start(&server));
}
static void solo_manual(void) {
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    for(unsigned split=0;split<2;split++) for(unsigned teams=0;teams<2;teams++) {
        reset(split,teams); player(0,0,0); ready();
        network_game_server_update_countdown(&server,_network_game_server_countdown_event_player_joined);
        assert(!server.countdown_state.active); /* Automatic first-player join waits. */
        request(1,_network_game_server_countdown_event_player_joined);
        assert(!server.countdown_state.active); /* Remote faster cannot start solo. */
        request(0,_network_game_server_countdown_event_player_joined);
        assert(server.countdown_state.active);
        int32_t duration=split?NETWORK_GAME_SPLITSCREEN_COUNTDOWN_TIME:NETWORK_GAME_COUNTDOWN_TIME;
        assert(countdown_timer_get_time_remaining(&server.countdown_state.timer)==duration);
        tick(1001); assert(last_countdown==(duration-1001)/MILLISECONDS_PER_SECOND && !begin_sends);
        request(0,_network_game_server_countdown_event_player_joined);
        int32_t faster=duration-1001-NETWORK_GAME_COUNTDOWN_ADJUSTMENT;
        assert(countdown_timer_get_time_remaining(&server.countdown_state.timer)==faster);
        request(0,_network_game_server_countdown_event_player_joined);
        assert(countdown_timer_get_time_remaining(&server.countdown_state.timer)==faster); /* Once per tick. */
        tick(faster); assert(server.sent_start_game_message && begin_sends==1 && settings_sends==1);
        assert(server.game.player_count==1 && network_game_server_start_players[0].valid);
        tick(1000); assert(begin_sends==1 && settings_sends==1);
    }
#else
    for(unsigned split=0;split<2;split++) for(unsigned teams=0;teams<2;teams++) {
        reset(split,teams); player(0,0,0);
        assert(!server_ok_to_countdown(&server) && !network_game_server_game_can_start(&server));
        request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
        request(0,_network_game_server_countdown_event_start_immediately); assert(!server.countdown_state.active);
    }
#endif
}
static void ordinary_lobbies(void) {
    reset(TRUE,FALSE); player(0,0,0); player(1,0,1); ready();
    network_game_server_update_countdown(&server,_network_game_server_countdown_event_player_joined);
    assert(server.countdown_state.active && server.countdown_state.timer.time_remaining==NETWORK_GAME_SPLITSCREEN_COUNTDOWN_TIME);
    reset(FALSE,FALSE); player(0,0,0); player(1,0,1);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    ready();
#else
    assert(!server_ok_to_countdown(&server));
#endif
    network_game_server_update_countdown(&server,_network_game_server_countdown_event_player_joined);
    assert(!server.countdown_state.active); /* Existing automatic System Link machine gate. */
    reset(FALSE,TRUE); player(0,0,0); machine(1,FALSE); player(1,1,1); ready();
    network_game_server_update_countdown(&server,_network_game_server_countdown_event_player_joined);
    assert(server.countdown_state.active && server.countdown_state.timer.time_remaining==NETWORK_GAME_COUNTDOWN_TIME);
    reset(TRUE,TRUE); player(0,0,0); player(1,0,0);
    assert(server_needs_more_teams(&server) && !server_ok_to_countdown(&server));
    request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
    server.game.players[1].team_index=1; ready();
    request(0,_network_game_server_countdown_event_player_joined); assert(server.countdown_state.active);
}
static void incomplete_lobbies(void) {
    for(unsigned split=0;split<2;split++) {
        reset(split,FALSE); assert(!server_ok_to_countdown(&server) && !network_game_server_game_can_start(&server));
        request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
        request(0,_network_game_server_countdown_event_start_immediately); assert(!server.countdown_state.active);
        player(0,0,0); machine(1,FALSE);
        assert(!server_has_a_player_on_each_machine(&server) && !server_ok_to_countdown(&server));
        request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
        request(0,_network_game_server_countdown_event_start_immediately); assert(!server.countdown_state.active);
        server.client_machines[1].joined=FALSE; /* Unjoined connections do not hold the lobby. */
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        ready(); request(0,_network_game_server_countdown_event_player_joined); assert(server.countdown_state.active);
        server.game.players[0].valid=FALSE; server.game.player_count=0;
        tick(1001); assert(!server.countdown_state.active && !begin_sends && last_countdown==NONE);
#endif
    }
}
static void authorization(void) {
    reset(FALSE,FALSE); player(0,0,0);
    for(short requester=0;requester<2;requester++) {
        request(requester,4); assert(!server.countdown_state.active); /* Internal event is never accepted on the wire. */
        request(requester,-1); assert(!server.countdown_state.active);
    }
    request(1,_network_game_server_countdown_event_start_immediately); assert(!server.countdown_state.active);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    request(0,_network_game_server_countdown_event_player_joined); assert(server.countdown_state.active);
    request(1,_network_game_server_countdown_event_stop); assert(server.countdown_state.active);
    request(1,_network_game_server_countdown_event_start_immediately); assert(server.countdown_state.timer.time_remaining==NETWORK_GAME_COUNTDOWN_TIME);
    request(0,_network_game_server_countdown_event_stop); assert(!server.countdown_state.active);
    decode_ok=FALSE; request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
    decode_ok=TRUE; server.state=_network_game_server_state_ingame;
    assert(!network_game_server_game_can_start(&server));
    request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
#endif
}
static void pause_and_precache(void) {
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    reset(TRUE,TRUE); player(0,0,0);
    request(0,_network_game_server_countdown_event_player_joined); assert(server.countdown_state.active);
    network_game_server_pause_countdown(&server,TRUE);
    assert(!server.countdown_state.active && server.countdown_state.paused);
    request(0,_network_game_server_countdown_event_player_joined); assert(!server.countdown_state.active);
    request(0,_network_game_server_countdown_event_start_immediately); assert(!server.countdown_state.active);
    network_game_server_pause_countdown(&server,FALSE);
    request(0,_network_game_server_countdown_event_start_immediately);
    assert(server.countdown_state.active && server.countdown_state.timer.time_remaining==0);
    server.client_machines[0].flags&=~FLAG(_network_client_machine_precached_bit);
    map_precached=FALSE; tick(1001); assert(!server.sent_start_game_message && !begin_sends);
    map_precached=TRUE; server.client_machines[0].flags|=FLAG(_network_client_machine_precached_bit);
    tick(1); assert(server.sent_start_game_message && begin_sends==1);
    reset(TRUE,FALSE); player(0,0,0); request(0,_network_game_server_countdown_event_player_joined);
    tick(NETWORK_GAME_SPLITSCREEN_COUNTDOWN_TIME-1200);
    request(0,_network_game_server_countdown_event_player_joined);
    assert(server.countdown_state.timer.time_remaining==NETWORK_GAME_MINIMUM_COUNTDOWN_TIME);
    tick(NETWORK_GAME_MINIMUM_COUNTDOWN_TIME-1); assert(!begin_sends);
    tick(1); assert(begin_sends==1);
#endif
}
static void readiness_changes(void) {
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    reset(FALSE,TRUE); player(0,0,0); request(0,_network_game_server_countdown_event_player_joined);
    machine(1,FALSE); tick(1001);
    assert(!server.countdown_state.active && !begin_sends); /* Join waits for its profile. */
    player(1,1,0); request(0,_network_game_server_countdown_event_player_joined);
    assert(!server.countdown_state.active); /* Both teams required once there are two players. */
    server.game.players[1].team_index=1; ready();
    request(0,_network_game_server_countdown_event_player_joined); assert(server.countdown_state.active);
    server.game.players[1].valid=FALSE; server.game.player_count=1; server.client_machines[1].joined=FALSE;
    ready(); tick(NETWORK_GAME_COUNTDOWN_TIME); assert(begin_sends==1); /* Host remains ready after peer leaves. */
#endif
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"solo")) solo_manual();
    else if(!strcmp(argv[1],"ordinary")) ordinary_lobbies();
    else if(!strcmp(argv[1],"incomplete")) incomplete_lobbies();
    else if(!strcmp(argv[1],"authorization")) authorization();
    else if(!strcmp(argv[1],"pause")) pause_and_precache();
    else if(!strcmp(argv[1],"readiness")) readiness_changes();
    else assert(0);
    return 0;
}
'''


def production_fixture():
    manager = (ROOT / "source/networking/network_server_manager.c").read_text()
    handler = (ROOT / "source/networking/network_server_message_handler.c").read_text()
    declarations = "enum {\n" + "\n".join(constant(manager, name) for name in (
        "NETWORK_GAME_COUNTDOWN_TIME", "NETWORK_GAME_SPLITSCREEN_COUNTDOWN_TIME",
        "NETWORK_GAME_COUNTDOWN_ADJUSTMENT", "NETWORK_GAME_MINIMUM_COUNTDOWN_TIME")) + "\n};\n"
    for event in ("_network_game_server_countdown_event_player_left", "_network_game_server_state_pregame"):
        start = manager.index("enum\n{\n\t" + event)
        declarations += block(manager[start:], "enum\n") + ";\n"
    for name in ("countdown_timer", "network_game_server_countdown_state", "message_server_begin_game",
                 "message_server_pregame_countdown", "message_server_pregame_keep_alive"):
        declarations += block(manager, f"struct {name}\n") + ";\n"
    declarations += block(handler, "struct message_client_game_start_request\n") + ";\n"
    # These signatures also appear in forward declarations. The last occurrence
    # is the definition; extract its complete body without rewriting behavior.
    functions = "\n".join(block(manager[manager.rindex(signature):], signature) for signature in (
        "void countdown_timer_update(", "long countdown_timer_get_time_remaining(",
        "void countdown_timer_increment(", "void countdown_timer_decrement(",
        "void countdown_timer_set_time_remaining(", "static void network_game_server_countdown_started(\n",
        "boolean server_needs_more_teams(", "boolean server_has_a_player_on_each_machine(",
        "boolean server_has_enough_machines(", "boolean server_ok_to_countdown(",
        "boolean network_game_server_game_can_start(", "void network_game_server_pause_countdown(",
        "static short network_game_server_get_client_machine_count(",
        "void network_game_server_update_countdown(", "boolean network_game_server_client_machine_may_slow_countdown(",
        "static boolean network_game_server_setup_game_from_playlist(", "boolean network_game_server_start_network_game(",
        "static boolean network_game_server_machine_has_players(",
        "static boolean network_game_server_have_all_machines_have_precached(",
        "static boolean network_game_server_idle_pregame_tasks("))
    signature = "static boolean network_game_server_handle_message_client_game_start_request("
    functions += "\n" + block(handler[handler.rindex(signature):], signature)
    source = PREFIX.replace("/* DECLARATIONS */", declarations).replace("/* FUNCTIONS */", functions) + HARNESS
    source = re.sub(r"\bunsigned long\b", "uint32_t", source)
    return re.sub(r"\blong\b", "int32_t", source)


class SoloMultiplayerStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A C compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-solo-start-")
        directory = Path(cls.temporary.name)
        source = directory / "fixture.c"
        source.write_text(production_fixture())
        cls.executables = {}
        platform_flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
        for mode, flags in (("native", ["-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16"]), ("legacy", [])):
            executable = directory / mode
            subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                            "-Wno-unused-variable", *platform_flags, *flags, str(source), "-o", str(executable)], check=True)
            cls.executables[mode] = executable

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case):
        for mode, executable in self.executables.items():
            with self.subTest(mode=mode):
                subprocess.run([str(executable), case], check=True)

    def test_solo_split_screen_and_system_link_manual_countdown(self):
        self.run_case("solo")

    def test_multiplayer_auto_countdown_and_both_teams(self):
        self.run_case("ordinary")

    def test_zero_players_and_joined_machine_without_profile(self):
        self.run_case("incomplete")

    def test_host_only_start_stop_and_internal_event_rejection(self):
        self.run_case("authorization")

    def test_pause_immediate_start_and_precache(self):
        self.run_case("pause")

    def test_readiness_after_player_and_machine_changes(self):
        self.run_case("readiness")


if __name__ == "__main__":
    unittest.main()
