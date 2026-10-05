"""Exercise the production network map transition with deterministic dependencies.

The accessor, options setup/validation, game loader and network object creation
are extracted from production C. Cleanup/cache/player dependencies are stubs that
record ownership and ordering; this does not validate real texture-cache release
or a complete multiplayer load. C long is normalized to the 32-bit guest ABI.
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

FIXTURE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char boolean;
typedef float real;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define NETWORK_GAME_PLAYER_SLOTS 4
#define NUMBER_OF_GAME_DIFFICULTY_LEVELS 4
#define VALID_INDEX(index,count) ((index)>=0 && (index)<(count))
#define csmemset memset
#define csmemcpy memcpy
#define csstrncpy strncpy
#define match_assert(file,line,condition) assert(condition)
enum { _game_difficulty_level_normal=1, _game_connection_network_client=2,
       _game_connection_network_server=3, _game_connection_film_playback=4 };
/* PRODUCTION STRUCTURES */
struct game_variant { int game_engine_index; };
struct network_player { boolean valid; char player_list_index; };
struct network_game {
    struct { char name[256]; } map;
    short difficulty;
    uint32_t random_seed;
    struct game_variant variant;
    struct { boolean game_objects_loaded; } local_data;
    struct network_player players[NETWORK_GAME_PLAYER_SLOTS];
};
static struct game_runtime_globals_prefix runtime;
static struct game_runtime_globals_prefix *game_globals=&runtime;
static struct network_game network;
static int connection;
static boolean clock_running, load_succeeds;
static int failed_spawn;
static unsigned disposals, unloads, initializations, spawns, errors, variants;
static unsigned debug_log_starts;
static char trace[512];
static void event(const char *name) {
    if(trace[0]) strcat(trace,"> ");
    assert(strlen(trace)+strlen(name)<sizeof(trace));
    strcat(trace,name);
}
static int game_connection(void) { return connection; }
static boolean game_in_progress(void) { return clock_running; }
static uint32_t network_game_get_random_seed(void) { return 0x12345678; }
static void game_precache_new_map(const char *name,boolean blocking) {
    assert(blocking && !strcmp(name,network.map.name)); event("precache");
}
static void main_menu_unload(void) { event("menu"); }
static void game_dispose_from_old_map(void) {
    assert(runtime.map_loaded || clock_running);
    disposals++; event("dispose"); runtime.active=FALSE; clock_running=FALSE;
}
static void game_unload(void) {
    assert(disposals==unloads+1 && !runtime.active && !clock_running);
    unloads++; event("unload"); runtime.map_loaded=FALSE;
}
static void game_set_game_variant(struct game_variant *variant) {
    assert(variant==&network.variant && variant->game_engine_index);
    variants++; event("variant");
}
static void random_seed_debug_log(boolean enabled) {
    assert(enabled); debug_log_starts++; event("load");
}
static boolean scenario_load(const char *name) {
    assert(!strcmp(name,network.map.name)); return load_succeeds;
}
static void game_initialize_for_new_map(void) {
    assert(runtime.map_loaded && !runtime.active && !clock_running);
    initializations++; event("initialize"); runtime.active=TRUE; clock_running=TRUE;
}
static boolean network_player_is_valid(struct network_player *player) { return player->valid; }
static boolean network_game_spawn_player(struct network_player *player) {
    int index=(int)(player-network.players);
    char name[20];
    assert(index>=0 && index<NETWORK_GAME_PLAYER_SLOTS);
    assert(player->valid && player->player_list_index==index);
    assert(runtime.map_loaded && runtime.active && clock_running);
    spawns++; snprintf(name,sizeof(name),"spawn%d",index); event(name);
    return index!=failed_spawn;
}
static void error(int level,const char *message) {
    assert(level==0 && !strcmp(message,"game_load() failed.")); errors++; event("error");
}
/* PRODUCTION FUNCTIONS */
static void reset(boolean loaded,boolean running) {
    memset(&runtime,0,sizeof(runtime)); memset(&network,0,sizeof(network));
    runtime.map_loaded=loaded; runtime.active=running; clock_running=running;
    load_succeeds=TRUE; failed_spawn=NONE; connection=_game_connection_network_client;
    strcpy(network.map.name,"chillout"); network.difficulty=2;
    network.random_seed=0x87654321; network.variant.game_engine_index=1;
    network.players[1].valid=TRUE; network.players[3].valid=TRUE;
    for(int i=0;i<NETWORK_GAME_PLAYER_SLOTS;i++) network.players[i].player_list_index=NONE;
    disposals=unloads=initializations=spawns=errors=variants=debug_log_starts=0; trace[0]=0;
}
static void verify_loaded_options(uint32_t seed) {
    assert(!strcmp(runtime.options.map_name,network.map.name));
    assert(runtime.options.difficulty==network.difficulty && runtime.options.random_seed==seed);
}
static void accessor(void) {
    reset(FALSE,FALSE); assert(!game_map_loaded());
    clock_running=TRUE; runtime.active=TRUE; assert(!game_map_loaded());
    runtime.map_loaded=TRUE; assert(game_map_loaded());
    clock_running=FALSE; runtime.active=FALSE; assert(game_map_loaded());
}
static void stopped_menu(void) {
    reset(TRUE,FALSE);
    assert(network_game_create_game_objects(&network));
    assert(disposals==1 && unloads==1 && initializations==1 && spawns==2 && !errors);
    assert(!strcmp(trace,"precache> menu> dispose> unload> variant> load> initialize> spawn1> spawn3"));
    assert(runtime.map_loaded && runtime.active && clock_running);
    assert(network.players[0].player_list_index==NONE && network.players[2].player_list_index==NONE);
    verify_loaded_options(0x12345678);
}
static void active_map(void) {
    reset(TRUE,TRUE); connection=_game_connection_network_server;
    assert(network_game_create_game_objects(&network));
    assert(disposals==1 && unloads==1 && initializations==1 && spawns==2 && !errors);
    assert(!strcmp(trace,"precache> menu> dispose> unload> variant> load> initialize> spawn1> spawn3"));
    verify_loaded_options(0x12345678);
}
static void cold_start(void) {
    reset(FALSE,FALSE); connection=_game_connection_film_playback;
    network.variant.game_engine_index=0;
    assert(network_game_create_game_objects(&network));
    assert(!disposals && !unloads && !variants && initializations==1 && spawns==2 && !errors);
    assert(!strcmp(trace,"precache> menu> load> initialize> spawn1> spawn3"));
    verify_loaded_options(network.random_seed);
}
static void clock_guard_preserved(void) {
    reset(FALSE,TRUE);
    assert(network_game_create_game_objects(&network));
    assert(disposals==1 && unloads==1 && initializations==1 && spawns==2 && !errors);
}
static void load_failure(void) {
    for(int old_map=0;old_map<2;old_map++) {
        reset(old_map,FALSE); load_succeeds=FALSE;
        assert(!network_game_create_game_objects(&network));
        assert(disposals==(unsigned)old_map && unloads==(unsigned)old_map);
        assert(!initializations && !spawns && errors==1 && debug_log_starts==1);
        assert(!runtime.map_loaded && !runtime.active && !clock_running);
        assert(!strcmp(trace,old_map
            ? "precache> menu> dispose> unload> variant> load> error"
            : "precache> menu> variant> load> error"));
    }
}
static void spawn_failure(void) {
    reset(TRUE,FALSE); failed_spawn=1;
    assert(!network_game_create_game_objects(&network));
    assert(disposals==1 && unloads==1 && initializations==1 && spawns==1 && !errors);
    assert(network.players[3].player_list_index==NONE);
    assert(!strcmp(trace,"precache> menu> dispose> unload> variant> load> initialize> spawn1"));
    /* The guard does not add cleanup of the newly loaded map on a spawn failure. */
    assert(runtime.map_loaded && runtime.active && clock_running);
}
static void next_transition(void) {
    reset(TRUE,FALSE); assert(network_game_create_game_objects(&network));
    strcpy(network.map.name,"bloodgulch"); trace[0]=0;
    assert(network_game_create_game_objects(&network));
    assert(disposals==2 && unloads==2 && initializations==2 && spawns==4 && !errors);
    assert(!strcmp(trace,"precache> menu> dispose> unload> variant> load> initialize> spawn1> spawn3"));
    verify_loaded_options(0x12345678);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"accessor")) accessor();
    else if(!strcmp(argv[1],"stopped-menu")) stopped_menu();
    else if(!strcmp(argv[1],"active-map")) active_map();
    else if(!strcmp(argv[1],"cold-start")) cold_start();
    else if(!strcmp(argv[1],"clock-guard")) clock_guard_preserved();
    else if(!strcmp(argv[1],"load-failure")) load_failure();
    else if(!strcmp(argv[1],"spawn-failure")) spawn_failure();
    else if(!strcmp(argv[1],"next-transition")) next_transition();
    else assert(0);
    return 0;
}
'''


class MapLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A C compiler (clang or cc) is required for the map lifecycle fixture")
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-map-lifecycle-")
        cls.addClassCleanup(cls.directory.cleanup)
        game = (ROOT / "source/game/game.c").read_text()
        manager = (ROOT / "source/networking/network_game_manager.c").read_text()
        structures = "\n".join(block(game, f"struct {name}\n") + ";" for name in (
            "game_options", "game_runtime_globals_prefix"))
        functions = "\n".join(block(game, signature) for signature in (
            "void game_options_new(\n", "boolean game_options_verify(\n",
            "boolean game_map_loaded(\n", "boolean game_load(\n"))
        transition = block(manager, "boolean network_game_create_game_objects(\n")
        cls.executables = {}
        for name, transition_code in (
            ("current", transition),
            ("old-guard", transition.replace(
                "game_in_progress() || game_map_loaded()", "game_in_progress()")),
        ):
            source = FIXTURE.replace("/* PRODUCTION STRUCTURES */", structures)
            source = source.replace("/* PRODUCTION FUNCTIONS */", functions + "\n" + transition_code)
            source = re.sub(r"\blong\b", "int32_t", source).replace("unsigned int32_t", "uint32_t")
            path = Path(cls.directory.name) / f"{name}.c"
            path.write_text(source)
            executable = path.with_suffix(".exe" if os.name == "nt" else "")
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
            if os.name != "nt":
                flags.append("-fsanitize=address,undefined")
            result = subprocess.run([
                compiler, *flags,
                str(path), "-o", str(executable),
            ], capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.executables[name] = executable

    def run_case(self, case, executable="current"):
        return subprocess.run(
            [str(self.executables[executable]), case], capture_output=True, text=True, timeout=10)

    def assert_case(self, case):
        result = self.run_case(case)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_accessor_reads_map_ownership_independently_of_clock(self):
        self.assert_case("accessor")

    def test_stopped_menu_map_disposes_and_unloads_before_next_load(self):
        self.assert_case("stopped-menu")

    def test_old_clock_only_guard_reproduces_loader_ownership_assertion(self):
        result = self.run_case("stopped-menu", "old-guard")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("!game_globals->map_loaded", result.stderr)

    def test_active_map_cleanup_still_runs_once(self):
        self.assert_case("active-map")

    def test_cold_map_has_no_cleanup_and_preserves_playback_seed(self):
        self.assert_case("cold-start")

    def test_existing_clock_guard_is_preserved(self):
        self.assert_case("clock-guard")

    def test_load_failure_cleans_only_the_previous_map(self):
        self.assert_case("load-failure")

    def test_spawn_failure_keeps_existing_failure_behavior(self):
        self.assert_case("spawn-failure")

    def test_consecutive_transitions_each_cleanup_once(self):
        self.assert_case("next-transition")


if __name__ == "__main__":
    unittest.main()
