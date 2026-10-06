"""Run shared rule helpers with stock20 and isolated Halo OG weapon IDs.

These native C fixtures cover host rule interpretation. They do not certify
mixed-client transport, maps, or the feel of a live OpenCE match.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
COMPILER = shutil.which("clang") or shutil.which("cc")


@unittest.skipUnless(COMPILER, "a C11 compiler is required")
class OpenCEGameplayTests(unittest.TestCase):
    def compile_and_run(self, fixture):
        with tempfile.TemporaryDirectory(prefix="opence-gameplay-") as temporary:
            path = Path(temporary) / "fixture.c"
            path.write_text(fixture)
            binary = Path(temporary) / ("fixture.exe" if sys.platform == "win32" else "fixture")
            flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else ["-fsanitize=address,undefined"]
            result = subprocess.run([COMPILER, "-std=c11", "-Wall", "-Wextra", "-Werror",
                                     *flags, str(path), "-o", str(binary)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_original_coop_score_hud_without_multiplayer_engine(self):
        engine = (ROOT / "source/game/game_engine.c").read_text()
        function = block(engine, "static void game_engine_rasterize_campaign_score(\n")
        self.compile_and_run(r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <wchar.h>
typedef unsigned char boolean;
typedef float real;
typedef struct { float alpha,red,green,blue; } real_argb_color;
#define FALSE 0
struct player_datum { boolean quit_out_of_game; wchar_t name[16]; };
struct data_iterator { long datum_index, next; };
static struct player_datum players[128];
static void *player_data=players;
static long count, rows, selected;
static void data_iterator_new(struct data_iterator *iterator,void *data) {
    assert(data==players); iterator->next=0;
}
static struct player_datum *data_iterator_next(struct data_iterator *iterator) {
    if(iterator->next==count) return NULL;
    iterator->datum_index=iterator->next++; return &players[iterator->datum_index];
}
static void usprintf(wchar_t *out,wchar_t const *format,wchar_t const *name) {
    (void)format; wcscpy(out,name);
}
static void rasterize_in_game_score_draw_line(wchar_t *text,boolean current,real_argb_color *color,long row) {
    assert(color->alpha==0.5f && color->red==0.7f);
    if(!row) { assert(!wcscmp(text,L"Co-op")); assert(!current); return; }
    assert(row==rows+2 && row<8 && text[0]); rows++;
    if(current) selected++;
}
/* FUNCTION */
int main(void) {
    game_engine_rasterize_campaign_score(0,0.5f); assert(!rows);
    count=128;
    for(long i=0;i<count;i++) wcscpy(players[i].name,L"player");
    players[0].quit_out_of_game=1;
    game_engine_rasterize_campaign_score(2,0.5f); assert(rows==6 && selected==1);
    rows=selected=0;
    for(long i=0;i<count;i++) players[i].quit_out_of_game=1;
    game_engine_rasterize_campaign_score(2,0.5f); assert(!rows && !selected);
    return 0;
}
'''.replace("/* FUNCTION */", function))

    def test_ce_level_list_retains_all_original_and_community_maps(self):
        source = (ROOT / "port/linux/game/custom_edition_maps.c").read_text()
        header = (ROOT / "port/linux/game/custom_edition_maps.h").read_text()
        constants = "\n".join(re.search(rf"^#define {name} .+$", content,re.M)[0] for name,content in (
            ("MAXIMUM_XBOX_LEVELS",source), ("FIRST_DISPLAY_INDEX",source),
            ("CUSTOM_EDITION_MAPS_MAXIMUM",header)))
        functions = "\n".join(block(source, signature) for signature in (
            "char **custom_edition_maps_level_list(\n", "short custom_edition_maps_level_display_index(\n"))
        self.compile_and_run(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define MIN(a,b) ((a)<(b)?(a):(b))
/* CONSTANTS */
static struct custom_edition_maps_globals {
    short xbox_level_count, map_count;
    int looked_for;
    struct { char level_name[64]; } maps[CUSTOM_EDITION_MAPS_MAXIMUM];
    char *levels[MAXIMUM_XBOX_LEVELS+CUSTOM_EDITION_MAPS_MAXIMUM];
} custom_edition_maps_globals;
static void custom_edition_maps_look_for(void) { custom_edition_maps_globals.looked_for=1; }
/* FUNCTIONS */
int main(void) {
    char names[128][32], *original[128]; short count;
    assert(MAXIMUM_XBOX_LEVELS>=128);
    for(short i=0;i<128;i++) { snprintf(names[i],sizeof(names[i]),"community_%d",i); original[i]=names[i]; }
    custom_edition_maps_globals.map_count=CUSTOM_EDITION_MAPS_MAXIMUM;
    for(short i=0;i<CUSTOM_EDITION_MAPS_MAXIMUM;i++) snprintf(custom_edition_maps_globals.maps[i].level_name,64,"custom_maps\\ce_%d",i);
    char **levels=custom_edition_maps_level_list(original,128,&count);
    assert(count==128+CUSTOM_EDITION_MAPS_MAXIMUM);
    for(short i=0;i<128;i++) { assert(levels[i]==original[i]); assert(custom_edition_maps_level_display_index(i)==i); }
    assert(custom_edition_maps_level_display_index(128)==FIRST_DISPLAY_INDEX);
    assert(custom_edition_maps_level_display_index(count-1)==FIRST_DISPLAY_INDEX+CUSTOM_EDITION_MAPS_MAXIMUM-1);
    assert(!strcmp(levels[count-1],"custom_maps\\ce_8191"));
    return 0;
}
'''.replace("/* CONSTANTS */", constants).replace("/* FUNCTIONS */", functions))
    def test_original_menu_selection_resets_host_options(self):
        engine = (ROOT / "source/game/game_engine.h").read_text()
        declarations = "\n".join(block(engine, signature) + ";" for signature in (
            "struct universal_variant\n", "struct ctf_variant\n", "struct slayer_variant\n",
            "struct king_variant\n", "struct oddball_variant\n", "struct race_variant\n",
            "union game_engine_variant\n", "struct game_variant\n"))
        declarations += "\n" + block(engine,
            "enum\n{\n\t_game_variant_draw_object_in_motion_sensor_bit") + ";"
        player_ui = (ROOT / "source/interface/player_ui.c").read_text()
        functions = "\n".join(block(player_ui, signature) for signature in (
            "void player_ui_set_game_variant(\n", "void player_ui_set_game_variant_options(\n",
            "struct game_variant_options const *player_ui_get_game_variant_options(\n",
            "boolean player_ui_game_variant_specified(\n"))
        server = (ROOT / "source/networking/network_server_manager.c").read_text()
        functions += "\n" + block(server,
            "static void network_game_server_variant_options(\n\tstruct game_variant const *variant,\n"
            "\tstruct game_variant_options *options)\n{")
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef unsigned char byte, boolean;
typedef uint16_t word;
typedef uint16_t game_wchar_t;
typedef float real;
#define TRUE 1
#define TEST_FLAG(value,bit) (((value)&(1u<<(bit)))!=0)
#define csmemcpy memcpy
#define csmemcmp memcmp
#define csmemset memset
#define match_assert(file,line,condition) assert(condition)
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
/* DECLARATIONS */
/* OPTIONS */
static struct { struct game_variant multiplayer_variant; boolean multiplayer_variant_specified; } player_ui_globals;
static struct game_variant_options player_ui_multiplayer_options;
/* FUNCTIONS */
int main(void) {
    struct game_variant chosen={0}, different={0};
    struct game_variant_options defaults, host, custom;
    assert(sizeof(chosen)==104 && sizeof(host)==28);
    chosen.universal_variant.vehicle_set=3;
    chosen.universal_variant.flags=1u<<_game_variant_draw_object_in_motion_sensor_bit;
    memset(&player_ui_multiplayer_options,0xff,sizeof(player_ui_multiplayer_options));
    player_ui_set_game_variant(&chosen);
    game_variant_options_default(&chosen,&defaults);
    assert(!game_variant_options_unsupported(&chosen,&defaults));
    assert(!memcmp(player_ui_get_game_variant_options(),&defaults,sizeof(defaults)));
    network_game_server_variant_options(&chosen,&host);
    assert(!memcmp(&host,&defaults,sizeof(host)));
    custom=defaults;
    custom.radar_players=_radar_players_friends;
    custom.loadout=_loadout_custom;
    custom.primary_weapon=_loadout_weapon_none;
    custom.secondary_weapon=_loadout_weapon_none;
    custom.no_map_weapons=TRUE;
    custom.time_limit=12;
    player_ui_set_game_variant_options(&custom);
    network_game_server_variant_options(&chosen,&host);
    assert(!memcmp(&host,&custom,sizeof(host)));
    different=chosen;
    different.universal_variant.vehicle_set=1;
    different.universal_variant.flags=0;
    game_variant_options_default(&different,&defaults);
    network_game_server_variant_options(&different,&host);
    assert(!memcmp(&host,&defaults,sizeof(host)));
    /* Original authored menus choose another gametype without a PC-options call. */
    player_ui_set_game_variant(&different);
    network_game_server_variant_options(&different,&host);
    assert(!memcmp(&host,&defaults,sizeof(host)));
    assert(host.radar_players==_radar_players_none && host.loadout==_loadout_category);
    assert(host.vehicle_set[0]==1 && host.vehicle_set[1]==1 && !host.no_map_weapons);
    player_ui_globals.multiplayer_variant_specified=0;
    player_ui_multiplayer_options=custom;
    network_game_server_variant_options(&different,&host);
    assert(!memcmp(&host,&defaults,sizeof(host)));
    return 0;
}
'''
        fixture = fixture.replace("/* DECLARATIONS */", declarations)
        fixture = fixture.replace("/* OPTIONS */", (ROOT / "source/game/game_variant_options.h").read_text())
        fixture = fixture.replace("/* FUNCTIONS */", functions)
        fixture = re.sub(r"\bunsigned long\b", "uint32_t", fixture)
        fixture = re.sub(r"\blong\b", "int32_t", fixture)
        fixture = re.sub(r"\bwchar_t\b", "game_wchar_t", fixture)
        self.compile_and_run(fixture)

    def test_shared_rule_interpretation_and_extension_ids(self):
        source = (ROOT / "source/game/game_engine.c").read_text()
        sets = (ROOT / "source/game/weapon_sets.h").read_text()
        fixture = r'''
#include <assert.h>
#include <string.h>
#define NONE (-1)
#define TRUE 1
#define FALSE 0
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define TEST_FLAG(value,bit) (((value)&(1u<<(bit)))!=0)
#define csmemset memset
typedef unsigned char byte;
typedef unsigned char boolean;
struct game_variant {
    struct { unsigned flags; int weapon_set, vehicle_set; boolean teams; } universal_variant;
};
/* FLAGS */
/* OPTIONS */
/* WEAPON SETS */
/* WEAPON ENUM */
static struct game_variant global_variant;
static struct game_variant_options options;
static void *game_engine;
static struct { int team_index; } viewer;
struct fixture_object { struct { short owner_team_index; } object; };
static struct fixture_object target;
#define player_datum fixture_player_datum
struct fixture_player_datum { int team_index; };
static struct game_variant_options const *game_variant_options_get(void) { return &options; }
static long local_player_get_player_index(short local) { return local==0 ? 1 : NONE; }
static struct fixture_player_datum *player_try_and_get(long index) {
    return index==1 ? (struct fixture_player_datum *)&viewer : 0;
}
static struct fixture_object *object_get(long index) { assert(index==2); return &target; }
static short game_engine_motion_sensor_local_player=NONE;
/* FUNCTIONS */
int main(void) {
    struct game_variant variant={0};
    variant.universal_variant.flags=1u<<_game_variant_draw_object_in_motion_sensor_bit;
    variant.universal_variant.vehicle_set=3;
    game_variant_options_default(&variant,&options);
    assert(sizeof(options)==28 && options.friendly_fire==_friendly_fire_on);
    assert(options.loadout==_loadout_category && !options.no_map_weapons);
    assert(!options.auto_team_balance && !options.time_limit && !options.vehicle_respawn_time);
    assert(options.radar_players==_radar_players_all && options.vehicle_set[0]==3 && options.vehicle_set[1]==3);
    assert(!game_variant_options_unsupported(&variant,&options));
    variant.universal_variant.flags=0;
    game_variant_options_default(&variant,&options);
    assert(options.radar_players==_radar_players_none);
    assert(_game_engine_weapons_covenant==11);
    assert(_game_engine_weapons_classic==12);
    assert(_game_engine_weapons_heavy==13);
    assert(GAME_WEAPON_SET_UNCUT==14 && GAME_WEAPON_SET_ALL==15);
    for(int set=0;set<=15;set++) {
        variant.universal_variant.weapon_set=set;
        assert(game_variant_uses_expanded_weapon_set(&variant)==(set==14 || set==15));
    }
    global_variant.universal_variant.flags=1u<<_game_variant_infinite_grenades_bit;
    assert(game_engine_infinite_grenades_internal());
    global_variant.universal_variant.flags=0;
    assert(!game_engine_infinite_grenades_internal());
    game_engine=&global_variant;
    global_variant.universal_variant.flags=1u<<_game_variant_draw_object_in_motion_sensor_bit;
    global_variant.universal_variant.teams=TRUE;
    options.radar_players=_radar_players_friends;
    viewer.team_index=0;
    game_engine_motion_sensor_viewer(0);
    target.object.owner_team_index=0;
    assert(game_engine_draw_object_in_motion_sensor(2));
    target.object.owner_team_index=1;
    assert(!game_engine_draw_object_in_motion_sensor(2));
    game_engine_motion_sensor_viewer(NONE);
    assert(game_engine_draw_object_in_motion_sensor(2));
    game_engine_motion_sensor_viewer(0);
    options.radar_players=_radar_players_all;
    assert(game_engine_draw_object_in_motion_sensor(2));
    global_variant.universal_variant.flags=0;
    assert(!game_engine_draw_object_in_motion_sensor(2));
    game_engine=0;
    assert(game_engine_draw_object_in_motion_sensor(2));
    return 0;
}
'''
        options_header = (ROOT / "source/game/game_variant_options.h").read_text()
        engine = (ROOT / "source/game/game_engine.h").read_text()
        fixture = fixture.replace("/* FLAGS */", block(engine,
            "enum\n{\n\t_game_variant_draw_object_in_motion_sensor_bit") + ";")
        fixture = fixture.replace("/* OPTIONS */", options_header)
        fixture = fixture.replace("/* WEAPON SETS */", "\n".join(
            line for line in sets.splitlines() if not line.startswith("#include")))
        fixture = fixture.replace("/* WEAPON ENUM */", block(source, "enum game_engine_weapons") + ";")
        fixture = fixture.replace("/* FUNCTIONS */", "\n".join(block(source, signature) for signature in (
            "static boolean game_engine_infinite_grenades_internal(\n\tvoid)\n{",
            "void game_engine_motion_sensor_viewer(",
            "boolean game_engine_draw_object_in_motion_sensor(")))
        self.compile_and_run(fixture)


if __name__ == "__main__":
    unittest.main()
