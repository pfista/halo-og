"""Compile the prototype's actual variant and target-selection functions.

Check that teammate presentation never changes controller/player ownership,
only accepts current teammates, and leaves existing rule/save bytes intact.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define TEST_FLAG(flags,bit) ((flags) & (1u << (bit)))
#define PIN(value,low,high) ((value)<(low)?(low):((value)>(high)?(high):(value)))
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define __GAME_ENGINE_H
struct game_variant { struct { boolean teams; uint32_t flags; uint8_t pfo[6]; } universal_variant; };
#include "game/teammate_view_variant.h"
enum { _game_connection_local, _game_connection_network_client, _game_connection_network_server,
       _game_connection_film_playback, _object_dead_bit=2, MAXIMUM_WINDOWS=4 };
struct player_datum { int team_index, local_player_index, unit_index; boolean quit_out_of_game; };
struct unit_datum { struct { unsigned damage_flags; int parent_object_index; } object; };
struct data_iterator { int datum_index; };
static struct game_variant variant;
static struct player_datum players[4];
static struct unit_datum units[4];
static boolean present[4];
static int connection, local_count, self_index, forced_single, cinematic, in_progress, running;
static void *player_data;
static int game_in_progress(void) { return in_progress; }
static int game_engine_running(void) { return running; }
static int local_player_count(void) { return local_count; }
static int game_connection(void) { return connection; }
static int game_engine_force_single_screen(void) { return forced_single; }
static int cinematic_in_progress(void) { return cinematic; }
static struct game_variant *game_engine_get_variant(void) { return &variant; }
static int local_player_get_next(int index) { return index == NONE && local_count ? 0 : NONE; }
static int local_player_get_player_index(int index) { return index == 0 ? self_index : NONE; }
static struct player_datum *player_try_and_get(int index) {
    return index>=0 && index<4 && present[index] ? &players[index] : NULL;
}
#define player_get player_try_and_get
static struct unit_datum *unit_try_and_get(int index) {
    return index>=0 && index<4 ? &units[index] : NULL;
}
static void data_iterator_new(struct data_iterator *iterator, void *data) {
    (void)data; iterator->datum_index=NONE;
}
static void *data_iterator_next(struct data_iterator *iterator) {
    while (++iterator->datum_index<4) if(present[iterator->datum_index]) return &players[iterator->datum_index];
    return NULL;
}
static int teammate_view_player_index=NONE;
'''

CASES = r'''
static void variant_cases(void) {
    struct game_variant before;
    memset(&variant,0,sizeof(variant));
    assert(!teammate_view_variant_enabled(NULL));
    assert(!teammate_view_variant_set_enabled(NULL,TRUE));
    before=variant;
    assert(!teammate_view_variant_set_enabled(&variant,TRUE));
    assert(!memcmp(&before,&variant,sizeof(variant)));
    variant.universal_variant.teams=TRUE;
    for(unsigned flags=0;flags<256;flags++) {
        variant.universal_variant.flags=flags;
        memset(variant.universal_variant.pfo,0xA5,sizeof(variant.universal_variant.pfo));
        before=variant;
        assert(teammate_view_variant_set_enabled(&variant,TRUE));
        assert(teammate_view_variant_enabled(&variant));
        assert(variant.universal_variant.flags==(TEAMMATE_VIEW_VARIANT_MARKER|flags));
        assert(!memcmp(before.universal_variant.pfo,variant.universal_variant.pfo,6));
        variant.universal_variant.teams=FALSE;
        assert(!teammate_view_variant_enabled(&variant));
        variant.universal_variant.teams=TRUE;
        assert(teammate_view_variant_set_enabled(&variant,FALSE));
        assert(!memcmp(&before,&variant,sizeof(variant)));
    }
    variant.universal_variant.flags=0xABCD0023;
    before=variant;
    assert(!teammate_view_variant_set_enabled(&variant,TRUE));
    assert(!teammate_view_variant_set_enabled(&variant,FALSE));
    assert(!teammate_view_variant_enabled(&variant));
    assert(!memcmp(&before,&variant,sizeof(variant)));
    for(unsigned bit=8;bit<32;bit++) {
        variant.universal_variant.flags=TEAMMATE_VIEW_VARIANT_MARKER^(1u<<bit);
        assert(!teammate_view_variant_enabled(&variant));
    }
}
static void reset(void) {
    memset(&variant,0,sizeof(variant));variant.universal_variant.teams=TRUE;
    assert(teammate_view_variant_set_enabled(&variant,TRUE));
    connection=_game_connection_network_client;local_count=1;self_index=0;
    forced_single=cinematic=0;in_progress=running=1;
    teammate_view_player_index=NONE;
    for(int i=0;i<4;i++) {
        present[i]=TRUE;
        players[i]=(struct player_datum){i/2,i==0?0:NONE,i,FALSE};
        units[i]=(struct unit_datum){{0,NONE}};
    }
}
int main(void) {
    variant_cases();reset();
    struct player_datum original_players[4];struct unit_datum original_units[4];
    memcpy(original_players,players,sizeof(players));memcpy(original_units,units,sizeof(units));
    for(int i=0;i<20;i++) {
        assert(teammate_view_find_player()==1);
        teammate_view_player_index=teammate_view_find_player();
        assert(main_get_window_count()==2);
        assert(teammate_view_hud_player_count()==2);
        assert(teammate_view_get_player_index(0)==NONE);
        assert(teammate_view_get_player_index(1)==1);
        assert(teammate_view_get_player_index(2)==NONE);
        assert(teammate_view_get_first_person_unit_index(1)==1);
    }
    assert(!memcmp(original_players,players,sizeof(players)));
    assert(!memcmp(original_units,units,sizeof(units)));
    players[1].team_index=1;assert(teammate_view_get_player_index(1)==NONE);
    assert(teammate_view_find_player()==NONE && main_get_window_count()==1);
    reset();players[1].quit_out_of_game=TRUE;assert(teammate_view_find_player()==NONE);
    reset();players[1].unit_index=NONE;assert(teammate_view_find_player()==NONE);
    reset();units[1].object.damage_flags=1u<<_object_dead_bit;assert(teammate_view_find_player()==NONE);
    reset();units[1].object.parent_object_index=99;assert(teammate_view_find_player()==NONE);
    reset();present[1]=FALSE;assert(teammate_view_find_player()==NONE);
    reset();players[1].local_player_index=1;assert(teammate_view_find_player()==NONE);
    reset();players[0].team_index=1;assert(teammate_view_find_player()==2);
    reset();players[0].team_index=NONE;assert(teammate_view_find_player()==NONE);
    reset();players[0].quit_out_of_game=TRUE;assert(teammate_view_find_player()==NONE);
    reset();self_index=NONE;assert(teammate_view_find_player()==NONE);
    reset();local_count=2;assert(teammate_view_find_player()==NONE && main_get_window_count()==2);
    assert(teammate_view_hud_player_count()==2);
    reset();local_count=4;assert(main_get_window_count()==4);
    assert(teammate_view_hud_player_count()==4);
    reset();forced_single=1;assert(main_get_window_count()==1 && teammate_view_hud_player_count()==1);
    local_count=4;assert(main_get_window_count()==1 && teammate_view_hud_player_count()==4);
    reset();cinematic=1;assert(main_get_window_count()==1 && teammate_view_hud_player_count()==1);
    local_count=4;assert(main_get_window_count()==1 && teammate_view_hud_player_count()==4);
    reset();in_progress=0;assert(teammate_view_find_player()==NONE);
    reset();running=0;assert(teammate_view_find_player()==NONE);
    reset();connection=_game_connection_local;assert(main_get_window_count()==1);
    reset();connection=_game_connection_film_playback;assert(main_get_window_count()==1);
    reset();connection=_game_connection_network_server;assert(main_get_window_count()==2);
    reset();assert(teammate_view_variant_set_enabled(&variant,FALSE));assert(main_get_window_count()==1);
    assert(teammate_view_hud_player_count()==1);
    reset();variant.universal_variant.teams=FALSE;assert(main_get_window_count()==1);
    assert(teammate_view_hud_player_count()==1);
    return 0;
}
'''


class TeammateViewTests(unittest.TestCase):
    def test_compiled_variant_and_target_selection(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(compiler, "A C compiler (clang or cc) is required")
        helper = (ROOT / "source/main/teammate_view.inc").read_text()
        functions = "\n".join(block(helper, signature) for signature in (
            "static boolean teammate_view_available(", "static boolean teammate_view_valid_player(",
            "static long teammate_view_find_player(", "long teammate_view_get_player_index(",
            "long teammate_view_get_first_person_unit_index(", "short teammate_view_hud_player_count("))
        window_count = block((ROOT / "source/main/main.c").read_text(), "short main_get_window_count(")
        with tempfile.TemporaryDirectory(prefix="halo-team-view-") as folder:
            folder = Path(folder)
            source = folder / "fixture.c"
            source.write_text(PREFIX + functions + "\n" + window_count + "\n" + CASES)
            binary = folder / ("fixture.exe" if sys.platform == "win32" else "fixture")
            subprocess.run([compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "source"),
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
