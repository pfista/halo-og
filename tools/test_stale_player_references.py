"""Exercise full production kill/statistics functions with retained player datums.

The datum generation check, game_statistics_record_kill and
game_engine_player_killed are extracted from production source. Object lookup,
transport, score rendering and team relationships are deterministic fixtures.
This verifies safe invalid-reference handling and unchanged valid credit; it does
not certify transport identity turnover, slot reuse, or retail Xbox behavior.
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

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte;
typedef float real;
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define REAL_MIN (-3.402823466e+38F)
#define MAXIMUM_ATTACKERS_PER_UNIT 4
#define match_assert(f,l,c) assert(c)
enum { _object_type_biped, _object_type_vehicle,
    _game_engine_message_killed_by_unknown=10, _game_engine_message_killed_by_biped,
    _game_engine_message_killed_by_vehicle, _game_engine_message_killed_by_self,
    _game_engine_message_killed_by_player, _game_engine_message_killed_by_friendly_fire,
    _game_engine_message_quit, _game_engine_message_killed_friendly,
    _game_engine_message_multi_kill, _game_engine_message_triple_kill,
    _game_engine_message_double_kill, _game_engine_message_five_kills_in_row,
    _game_engine_message_killed_enemy, _game_engine_message_ten_kills_in_a_row };
struct datum_header { short identifier; };
struct player_statistics {
    int32_t suicides,deaths,kills_in_a_row,last_kill_time,multiple_kills;
    int32_t kills[1],assists[1],friendly_fire_kills;
};
struct player_datum {
    short identifier;
    short team_index;
    int32_t unit_index,quit_out_of_game_time,death_time,respawn_timer,respawn_penalty;
    boolean quit_out_of_game;
    struct player_statistics statistics;
};
struct data_array {
    boolean valid,identifier_zero_invalid;
    short maximum_count,count;
    size_t size;
    void *data;
};
static struct player_datum players[4];
static struct data_array data={TRUE,TRUE,4,4,sizeof(players[0]),players};
static struct data_array *player_data=&data;
/* DATUM_LOOKUP */
static struct player_datum *player_try_and_get(int32_t index) {
    return datum_try_and_get(player_data,index);
}
static struct player_datum *player_get(int32_t index) {
    struct player_datum *player=player_try_and_get(index);
    assert(player); /* Any strict lookup of a stale datum fails the fixture. */
    return player;
}
struct unit_attacker { int32_t player_index; uint32_t game_time_stamp; real damage_inflicted; };
struct unit_datum { struct { struct unit_attacker attackers[4]; } unit; };
static struct unit_datum victim_unit;
static struct unit_datum *unit_get(int32_t index) { assert(index==42); return &victim_unit; }
static int32_t player_index_from_unit_index(int32_t index) {
    assert(index==42); return 0x10000;
}
struct object_datum { struct { int type; } object; };
static struct object_datum object={{_object_type_biped}};
static struct object_datum *object_get(int32_t index) { assert(index==42); return &object; }
static void *unit_try_and_get(int32_t index) { (void)index; return &victim_unit; }
static int32_t now=1000;
static int32_t game_time_get(void) { return now; }
static boolean game_team_is_enemy(short victim,short other) { return victim!=other; }
static boolean network_game_distributed_client(void) { return FALSE; }
static boolean resolve_killer;
static int32_t resolved_killer;
static void network_distributed_player_killed(int32_t *killer,int32_t *object_index,
    int32_t dead,boolean *friendly) {
    (void)object_index; (void)friendly; assert(dead==0x10000);
    if(resolve_killer) *killer=resolved_killer;
}
static struct { struct { int32_t respawn_time,respawn_time_growth,suicide_penalty; } universal_variant; }
    global_variant={{30,10,15}};
static unsigned callbacks,score_messages;
static int32_t callback_killer,callback_object,callback_dead;
static boolean callback_friendly;
static void killed_player(int32_t killer,int32_t object_index,int32_t dead,boolean friendly) {
    callbacks++; callback_killer=killer; callback_object=object_index;
    callback_dead=dead; callback_friendly=friendly;
}
struct game_engine_fixture { void (*player_killed_player)(int32_t,int32_t,int32_t,boolean); };
static struct game_engine_fixture engine={killed_player},*game_engine=&engine;
static void game_show_score_extended(int32_t target,int32_t message,int32_t other) {
    (void)message; player_get(target); if(other!=NONE) player_get(other); score_messages++;
}
static void multiplayer_message(int32_t target,int32_t message,int32_t other) {
    (void)message; player_get(target); if(other!=NONE) player_get(other); score_messages++;
}
struct data_iterator { int32_t datum_index; };
static void data_iterator_new(struct data_iterator *iterator,struct data_array *array) {
    (void)array; iterator->datum_index=NONE;
}
static void *data_iterator_next(struct data_iterator *iterator) { (void)iterator; return NULL; }
static boolean game_statistics_active=TRUE;
/* KILL_FUNCTIONS */
'''

HARNESS = r'''
#define VICTIM ((int32_t)0x10000)
#define KILLER ((int32_t)0x10001)
#define ASSISTER ((int32_t)0x10002)
#define STALE ((int32_t)0x10003)
static void reset(void) {
    memset(players,0,sizeof(players)); memset(&victim_unit,0,sizeof(victim_unit));
    callbacks=score_messages=0; callback_killer=callback_object=callback_dead=NONE;
    resolve_killer=FALSE; callback_friendly=FALSE;
    for(int i=0;i<4;i++) {
        players[i].identifier=1; players[i].team_index=(short)i;
        players[i].quit_out_of_game_time=NONE;
        players[i].statistics.last_kill_time=NONE;
        victim_unit.unit.attackers[i].player_index=NONE;
    }
    players[0].unit_index=42; players[1].team_index=players[2].team_index=1;
    players[1].respawn_penalty=20;
}
static void attack(int entry,int32_t player,real damage) {
    victim_unit.unit.attackers[entry].player_index=player;
    victim_unit.unit.attackers[entry].game_time_stamp=(uint32_t)now;
    victim_unit.unit.attackers[entry].damage_inflicted=damage;
}
static void victim_recorded(void) {
    assert(players[0].statistics.deaths==1 && callbacks==1 && callback_dead==VICTIM);
}
int main(int argc,char **argv) {
    assert(argc==2); reset();
    if(!strcmp(argv[1],"valid_stats")) {
        attack(0,KILLER,100); attack(1,ASSISTER,50);
        game_statistics_record_kill(42,KILLER,NONE,1); victim_recorded();
        assert(players[1].statistics.kills[0]==1 && players[1].statistics.kills_in_a_row==1);
        assert(players[1].statistics.multiple_kills==1 && players[1].statistics.last_kill_time==now);
        assert(players[2].statistics.assists[0]==1 && callback_killer==KILLER && !callback_friendly);
        assert(players[1].respawn_penalty==10 && players[0].respawn_timer==90);
    } else if(!strcmp(argv[1],"valid_betrayal")) {
        players[1].team_index=0; attack(0,KILLER,100);
        game_statistics_record_kill(42,KILLER,NONE,0); victim_recorded();
        assert(players[1].statistics.friendly_fire_kills==1 && callback_friendly);
        assert(callback_killer==KILLER && players[1].statistics.kills[0]==0);
    } else if(!strcmp(argv[1],"none_killer")) {
        game_statistics_record_kill(42,NONE,NONE,0); victim_recorded();
        assert(callback_killer==NONE && players[1].statistics.kills[0]==0);
    } else if(!strcmp(argv[1],"stale_killer") || !strcmp(argv[1],"missing_killer")) {
        players[3].identifier=!strcmp(argv[1],"stale_killer")?2:0;
        game_statistics_record_kill(42,STALE,NONE,3); victim_recorded();
        assert(callback_killer==NONE && players[3].statistics.kills[0]==0);
    } else if(!strcmp(argv[1],"stale_best")) {
        /* A newer datum occupies the chosen attacker's absolute slot.
           The valid friendly killer remains the original fallback. */
        players[3].identifier=2; players[1].team_index=0;
        attack(0,KILLER,10); attack(1,STALE,100);
        game_statistics_record_kill(42,KILLER,NONE,0); victim_recorded();
        assert(callback_killer==KILLER && players[1].statistics.friendly_fire_kills==1);
        assert(players[3].statistics.kills[0]==0 && players[3].statistics.assists[0]==0);
    } else if(!strcmp(argv[1],"stale_assist") || !strcmp(argv[1],"missing_assist")) {
        players[2].identifier=!strcmp(argv[1],"stale_assist")?2:0;
        attack(0,KILLER,100); attack(1,ASSISTER,50);
        game_statistics_record_kill(42,KILLER,NONE,1); victim_recorded();
        assert(players[1].statistics.kills[0]==1 && players[2].statistics.assists[0]==0);
        assert(callback_killer==KILLER);
    } else if(!strcmp(argv[1],"valid_engine")) {
        game_engine_player_killed(KILLER,NONE,VICTIM,FALSE);
        assert(callbacks==1 && callback_killer==KILLER && callback_object==NONE);
        assert(players[1].respawn_penalty==10 && players[0].respawn_timer==90);
    } else if(!strcmp(argv[1],"stale_engine") || !strcmp(argv[1],"resolved_stale_engine")) {
        players[3].identifier=2;
        resolve_killer=!strcmp(argv[1],"resolved_stale_engine"); resolved_killer=STALE;
        game_engine_player_killed(resolve_killer?KILLER:STALE,NONE,VICTIM,FALSE);
        assert(callbacks==1 && callback_killer==NONE && players[3].respawn_penalty==0);
        assert(players[0].respawn_timer==90);
    } else assert(0);
    assert(score_messages>0); puts("PASS"); return 0;
}
'''


def fixture():
    datum = block((ROOT / "source/memory/data.c").read_text(), "void *datum_try_and_get(")
    engine = block((ROOT / "source/game/game_engine.c").read_text(), "void game_engine_player_killed(")
    statistics = block((ROOT / "source/game/game_statistics.c").read_text(), "void game_statistics_record_kill(")
    code = PREFIX.replace("/* DATUM_LOOKUP */", datum).replace(
        "/* KILL_FUNCTIONS */", engine + "\n" + statistics) + HARNESS
    # The guest ABI uses 32-bit long even when the fixture compiler is LP64.
    return re.sub(r"\blong\b", "int32_t", re.sub(r"\bunsigned long\b", "uint32_t", code))


class StalePlayerReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        path = Path(cls.directory.name) / "stale_player_references.c"
        path.write_text(fixture())
        cls.executable = path.with_suffix(".exe" if os.name == "nt" else "")
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            cls.directory.cleanup()
            raise RuntimeError("The stale player fixture requires a C compiler (clang or cc)")
        try:
            subprocess.run([compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                            str(path), "-o", str(cls.executable)], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            cls.directory.cleanup()
            raise RuntimeError(exc.stderr) from exc

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, scenario):
        result = subprocess.run([str(self.executable), scenario], check=True, capture_output=True, text=True)
        self.assertIn("PASS", result.stdout)

    def test_valid_killer_and_assist_keep_credit(self): self.run_case("valid_stats")
    def test_valid_betrayal_keeps_credit(self): self.run_case("valid_betrayal")
    def test_no_killer_stays_none(self): self.run_case("none_killer")
    def test_stale_killer_generation_is_not_credited(self): self.run_case("stale_killer")
    def test_deleted_killer_is_not_dereferenced(self): self.run_case("missing_killer")
    def test_stale_best_attacker_keeps_valid_fallback(self): self.run_case("stale_best")
    def test_stale_assister_generation_is_not_credited(self): self.run_case("stale_assist")
    def test_deleted_assister_is_not_dereferenced(self): self.run_case("missing_assist")
    def test_valid_engine_killer_preserves_penalty_and_message(self): self.run_case("valid_engine")
    def test_engine_drops_stale_killer_before_scoring(self): self.run_case("stale_engine")
    def test_engine_checks_killer_after_network_resolution(self): self.run_case("resolved_stale_engine")


if __name__ == "__main__":
    unittest.main()
