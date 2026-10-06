"""Exercise production client frame handling across lobby and disconnect transitions.

The start/end-frame, disposal, abort and local-queue restoration functions are
extracted from the game source. Client transport and queue allocation are controlled
stubs; this does not exercise sockets, the full main loop or retail-Xbox behavior.
Guest C long is fixed to int32_t for execution on LP64 hosts.
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
SOURCE = ROOT / "source/networking/network_game_globals.c"
MAIN_SOURCE = ROOT / "source/main/main.c"

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char byte, boolean;
typedef uint16_t word, message_header;
#define TRUE 1
#define FALSE 0
#define csmemcpy memcpy
#define GET_MESSAGE_SIZE(header) (sizeof(message_header) + (header))
enum { MAXIMUM_LOCAL_PLAYERS=4, _game_connection_local=0,
    _game_connection_network_client=1, _game_connection_network_server=2,
    _network_game_client_state_searching=1, _network_game_client_state_joining=2,
    _network_game_client_state_pregame=3, _network_game_client_state_ingame=4,
    _network_game_client_state_postgame=5, _message_client_game_update=6 };
struct player_action { byte data[32]; };
struct network_game { int identity; };
struct network_connection { int identity; };
struct network_game_client {
    struct network_game game;
    struct network_connection connection;
    short state,error;
};
struct network_game_server { struct network_game game; };
struct transport_address { int unused; };
/* DECLARATIONS */
static struct network_game_globals bss_004566dc;
#define global_network_game_client bss_004566dc.client
#define global_network_game_server bss_004566dc.server
static struct { short previous_client_state; } player_action_collection_definition;
static struct { short connection; } main_globals;
static struct network_game_client client;
static struct network_game_server server;
static unsigned queue_deletes,queue_creates,queue_starts,client_disposals,server_disposals;
static unsigned idle_calls,error_calls,state_calls,events,menu_calls,load_calls;
static unsigned update_builds,encodes,writes;
static boolean idle_result=TRUE,write_result=TRUE,encode_result=TRUE,host_started=TRUE;
static boolean queues_exist,queues_running;
static unsigned long clock_time;
static char operations[128];
static unsigned operation_count;
static struct network_game *loaded_game;
static struct client_game_update_message encoded_update;
static message_header encoded_header;
static void record(char operation) {
    assert(operation_count+1<sizeof(operations));
    operations[operation_count++]=operation; operations[operation_count]=0;
}
static void update_server_delete(void) {
    queue_deletes++; queues_exist=queues_running=FALSE; record('D');
}
static void update_server_new(void) {
    assert(!queues_exist); queue_creates++; queues_exist=TRUE; record('N');
}
static void update_server_start(void) {
    assert(queues_exist); queue_starts++; queues_running=TRUE; record('Q');
}
static void network_game_client_dispose(struct network_game_client *value) {
    assert(value==&client); client_disposals++; record('C');
}
static void network_game_server_dispose(struct network_game_server *value) {
    assert(value==&server); server_disposals++; record('S');
}
static struct network_game *network_game_server_get_game(struct network_game_server *value) {
    assert(value==&server); return &value->game;
}
static struct network_game *network_game_client_get_game(struct network_game_client *value) {
    assert(value==&client); return &value->game;
}
static void network_game_end_and_load_ui(struct network_game *game) {
    assert(main_globals.connection==_game_connection_local); load_calls++; loaded_game=game; record('L');
}
static void main_goto_main_menu(void) { menu_calls++; record('M'); }
static boolean network_game_client_idle(struct network_game_client *value) {
    assert(value==&client); idle_calls++; return idle_result;
}
static short network_game_client_get_error(struct network_game_client *value) {
    assert(value==&client); error_calls++; return value->error;
}
static short network_game_client_get_state(struct network_game_client *value,short *data) {
    assert(value==&client); state_calls++; if(data) *data=0; return value->state;
}
#define network_event(...) (events++)
static void display_assert(const char *message,const char *file,int line,boolean condition) {
    (void)message;(void)file;(void)line;(void)condition; assert(0);
}
static void system_exit(int status) { (void)status; assert(0); }
static unsigned long system_milliseconds(void) { return clock_time; }
static boolean network_game_client_server_has_started_game(struct network_game_client *value) {
    assert(value==&client); return host_started;
}
static void update_client_build_client_update(struct player_action_collection *update) {
    memset(update,0x5a,sizeof(*update)); update_builds++;
}
static long network_game_client_get_next_update_number(struct network_game_client *value) {
    assert(value==&client); return (long)0x80000007U;
}
static short local_player_count(void) { return 2; }
static message_header *create_network_game_message(int kind,const void *message,size_t size) {
    assert(kind==_message_client_game_update && size==sizeof(encoded_update));
    encodes++; memcpy(&encoded_update,message,size); encoded_header=(message_header)size;
    return encode_result ? &encoded_header : NULL;
}
static struct network_connection *network_game_client_get_connection(struct network_game_client *value) {
    assert(value==&client); return &value->connection;
}
static boolean network_game_client_write(struct network_connection *connection,message_header *message,
    word size,struct transport_address *address,boolean reliable) {
    assert(connection==&client.connection && message==&encoded_header);
    assert(size==sizeof(encoded_header)+sizeof(encoded_update) && !address && !reliable);
    writes++; return write_result;
}
/* FUNCTIONS */
'''

HARNESS = r'''
static void reset(void) {
    memset(&bss_004566dc,0,sizeof(bss_004566dc)); memset(&client,0,sizeof(client));
    memset(&server,0,sizeof(server)); memset(&encoded_update,0,sizeof(encoded_update));
    memset(&player_action_collection_definition,0,sizeof(player_action_collection_definition));
    queue_deletes=queue_creates=queue_starts=client_disposals=server_disposals=0;
    idle_calls=error_calls=state_calls=events=menu_calls=load_calls=0;
    update_builds=encodes=writes=operation_count=0; operations[0]=0; loaded_game=NULL;
    idle_result=write_result=encode_result=host_started=TRUE;
    queues_exist=queues_running=FALSE; clock_time=100;
    main_globals.connection=_game_connection_network_client;
    client.state=_network_game_client_state_ingame; client.game.identity=11; server.game.identity=22;
}
static void assert_local_queues(void) {
    assert(main_globals.connection==_game_connection_local && queues_exist && queues_running);
    assert(queue_deletes==1 && queue_creates==1 && queue_starts==1 && !strcmp(operations,"DNQ"));
    assert(!idle_calls && !error_calls && !state_calls && !events);
    assert(!update_builds && !encodes && !writes && !load_calls && !menu_calls);
}
static void null_start(void) {
    reset(); queues_exist=TRUE;
    bss_004566dc.last_client_update_time=17;
    assert(network_game_client_start_frame()); assert_local_queues();
    assert(!client_disposals && !server_disposals && !bss_004566dc.client_started);
    assert(bss_004566dc.last_client_update_time==17);
}
static void menu_dispose(void) {
    reset(); global_network_game_client=&client; queues_exist=TRUE;
    dispose_global_network_game_client();
    assert(!global_network_game_client && client_disposals==1);
    assert(main_globals.connection==_game_connection_network_client && !bss_004566dc.client_started);
    operation_count=0; operations[0]=0;
    assert(network_game_client_start_frame()); assert_local_queues();
}
static void valid_states(void) {
    for(short state=_network_game_client_state_searching;state<=_network_game_client_state_postgame;state++) {
        reset(); global_network_game_client=&client; client.state=state;
        assert(network_game_client_start_frame());
        assert(idle_calls==1 && error_calls==1 && state_calls==1 && events==1);
        assert(player_action_collection_definition.previous_client_state==state);
        assert(network_game_client_start_frame());
        assert(idle_calls==2 && state_calls==2 && events==1);
        assert(main_globals.connection==_game_connection_network_client);
        assert(!queue_deletes && !client_disposals && !load_calls && !menu_calls);
    }
}
static void valid_end(void) {
    reset(); global_network_game_client=&client;
    assert(network_game_client_start_frame() && network_game_client_end_frame());
    assert(update_builds==1 && encodes==1 && writes==1 && bss_004566dc.last_client_update_time==100);
    assert(encoded_update.update_number==7 && encoded_update.local_player_count==2);
    for(unsigned i=0;i<sizeof(encoded_update.update);i++) assert(encoded_update.update[i]==0x5a);
    clock_time=199; assert(network_game_client_end_frame()); assert(writes==1);
    clock_time=200; assert(network_game_client_end_frame()); assert(writes==2);
    assert(main_globals.connection==_game_connection_network_client && !queue_deletes && !client_disposals);
}
static void non_ingame_end(void) {
    reset(); global_network_game_client=&client; client.state=_network_game_client_state_pregame;
    assert(network_game_client_end_frame());
    assert(state_calls==1 && !update_builds && !encodes && !writes && !queue_deletes);
    assert(main_globals.connection==_game_connection_network_client);
}
static void kick(void) {
    reset(); global_network_game_client=&client; global_network_game_server=&server;
    bss_004566dc.quickstart_local=TRUE;
    network_game_abort(); assert(bss_004566dc.client_started);
    assert(network_game_client_start_frame());
    assert(main_globals.connection==_game_connection_local && loaded_game==&server.game);
    assert(!global_network_game_client && !global_network_game_server && !bss_004566dc.client_started);
    assert(!bss_004566dc.quickstart_local && client_disposals==1 && server_disposals==1);
    assert(load_calls==1 && menu_calls==1 && !strcmp(operations,"LCSM"));
    assert(!idle_calls && !queue_deletes);
}
static void abort_without_client(void) {
    reset(); global_network_game_server=&server; bss_004566dc.quickstart_local=TRUE;
    network_game_client_all_local_players_have_quit();
    assert(network_game_client_start_frame());
    assert(loaded_game==&server.game && server_disposals==1 && !client_disposals);
    assert(!global_network_game_server && !bss_004566dc.client_started && !bss_004566dc.quickstart_local);
    assert(load_calls==1 && menu_calls==1 && !queue_deletes && !strcmp(operations,"LSM"));
}
static void disconnect_after_start(void) {
    reset(); global_network_game_client=&client;
    assert(network_game_client_start_frame()); dispose_global_network_game_client();
    operation_count=0; operations[0]=0; idle_calls=error_calls=state_calls=events=0;
    assert(network_game_client_end_frame()); assert_local_queues();
    assert(!global_network_game_client && client_disposals==1);
}
static void idle_failure(void) {
    reset(); global_network_game_client=&client; idle_result=FALSE;
    assert(!network_game_client_start_frame());
    assert(idle_calls==1 && !error_calls && !state_calls && events==1);
    assert(global_network_game_client==&client && main_globals.connection==_game_connection_network_client);
    assert(!queue_deletes && !client_disposals);
}
static void client_error(void) {
    reset(); global_network_game_client=&client; client.error=9;
    assert(!network_game_client_start_frame());
    assert(idle_calls==1 && error_calls==1 && !state_calls && events==1);
    assert(global_network_game_client==&client && !queue_deletes && !client_disposals);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"null")) null_start();
    else if(!strcmp(argv[1],"menu")) menu_dispose();
    else if(!strcmp(argv[1],"states")) valid_states();
    else if(!strcmp(argv[1],"end")) valid_end();
    else if(!strcmp(argv[1],"pregame")) non_ingame_end();
    else if(!strcmp(argv[1],"kick")) kick();
    else if(!strcmp(argv[1],"abort_null")) abort_without_client();
    else if(!strcmp(argv[1],"disconnect")) disconnect_after_start();
    else if(!strcmp(argv[1],"idle_fail")) idle_failure();
    else if(!strcmp(argv[1],"error")) client_error();
    else assert(0);
    puts("network client lifecycle fixture passed"); return 0;
}
'''


def fixture(source, main_source):
    declarations = "\n".join(block(source, signature) + ";" for signature in (
        "struct network_game_globals\n", "struct player_action_collection\n",
        "struct client_game_update_message\n"))
    functions = [block(main_source, signature) for signature in (
        "void game_connection_set(", "void main_menu_ensure_player_queues_exist(")]
    functions.extend(block(source, signature) for signature in (
        "void dispose_global_network_game_client(", "void network_game_abort(",
        "void network_game_client_all_local_players_have_quit(",
        "boolean network_game_client_start_frame(", "boolean network_game_client_end_frame("))
    text = PREFIX.replace("/* DECLARATIONS */", declarations).replace(
        "/* FUNCTIONS */", "\n".join(functions)) + HARNESS
    text = re.sub(r"\bunsigned long\b", "uint32_t", text)
    return re.sub(r"\blong\b", "int32_t", text)


def compile_fixture(source, main_source, directory):
    path = Path(directory) / "network_client_lifecycle.c"
    path.write_text(fixture(source, main_source))
    executable = path.with_suffix(".exe" if os.name == "nt" else "")
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise RuntimeError("The network client lifecycle fixture requires clang or cc")
    subprocess.run([compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                    str(path), "-o", str(executable)], check=True, capture_output=True, text=True)
    return executable


class NetworkClientLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        try:
            cls.executable = compile_fixture(SOURCE.read_text(), MAIN_SOURCE.read_text(), cls.directory.name)
        except subprocess.CalledProcessError as exc:
            cls.directory.cleanup()
            raise RuntimeError(exc.stderr) from exc

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, scenario):
        subprocess.run([str(self.executable), scenario], check=True, capture_output=True, text=True)

    def test_null_client_restores_connection_and_running_queues(self): self.run_case("null")
    def test_lobby_disposal_recovers_on_next_menu_frame(self): self.run_case("menu")
    def test_valid_client_states_preserve_idle_and_event_behavior(self): self.run_case("states")
    def test_valid_ingame_client_preserves_heartbeat_and_cadence(self): self.run_case("end")
    def test_pregame_client_does_not_send_ingame_update(self): self.run_case("pregame")
    def test_abort_keeps_server_game_and_disposal_order(self): self.run_case("kick")
    def test_abort_precedes_missing_client_recovery(self): self.run_case("abort_null")
    def test_dispose_between_frame_callbacks_keeps_existing_recovery(self): self.run_case("disconnect")
    def test_idle_failure_still_reports_failure(self): self.run_case("idle_fail")
    def test_client_error_still_reports_failure(self): self.run_case("error")

    def test_original_null_dereference_negative_control(self):
        source = SOURCE.read_text()
        start = block(source, "boolean network_game_client_start_frame(")
        guard = block(start, "else if (!global_network_game_client)")
        unguarded = source.replace(start, start.replace(guard, "", 1), 1)
        with tempfile.TemporaryDirectory() as directory:
            executable = compile_fixture(unguarded, MAIN_SOURCE.read_text(), directory)
            result = subprocess.run([str(executable), "null"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, "The original null-client path must fail this fixture")


if __name__ == "__main__":
    unittest.main()
