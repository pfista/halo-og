"""Run production selection callbacks against staged arsenal availability.

The fixture checks that unavailable content and rejected host changes preserve
the prior lobby, remembered choices, player profile and physical cache context.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.test_performance_ui import c_block

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
typedef uint8_t byte, boolean;
typedef uint16_t word;
typedef float real;
#define TRUE 1
#define FALSE 0
#define NONE -1
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define match_vassert(file,line,condition,message) assert(condition)
#define _stricmp strcasecmp
static unsigned errors;
#define error(...) (++errors)
enum { game_engine_ctf=1, game_engine_slayer, game_engine_oddball, game_engine_king, game_engine_race };
/* VARIANTS */
#define __GAME_ENGINE_H
#include "game/starting_equipment.h"
#include "game/weapon_sets.h"
#include "halo_expanded_cache.h"
struct widget_instance {
    long definition_tag_index;
    short type;
    struct widget_instance *child;
    struct { short selected_index; } data3C;
    void *generated_list;
    word generated_count;
};
struct event_record { short controller_index; };
struct ui_widget_definition { short type; long child_count; };
struct network_game { struct { char name[128]; } map; struct game_variant variant; };
static struct network_game live_game;
static struct game_variant player_variant, profile, stage_variant, automated_variant, prepared_variant;
static struct native_map_cache_selection active_cache;
static struct ui_widget_definition definitions[3];
static struct widget_instance wrapper, screen, list;
static struct event_record event;
static long profile_indices[1];
static char *map_names[1];
static char current_map[128], stage_map[128], prepared_map[128], order[64];
static char const *map_automation, *variant_automation;
static unsigned prepare_calls, select_calls, server_changes, main_changes, override_changes;
static unsigned player_changes, map_history, variant_history, pauses, denied_sounds;
static int has_server, has_game, player_specified, arsenal_ready, host_accepts, region_allowed;
static int profile_available, stage_available;
static void record(char value) { unsigned n=(unsigned)strlen(order); assert(n+1<sizeof(order));order[n]=value;order[n+1]=0; }
static void *global_network_game_server_get(void) { return has_server ? &live_game:NULL; }
static struct network_game *network_game_get_game(void) { return has_game ? &live_game:NULL; }
static struct ui_widget_definition *ui_widget_definition_get(long index) { assert(index>=0 && index<3);return &definitions[index]; }
static boolean player_ui_game_variant_specified(struct game_variant *variant) {
    if(player_specified) *variant=player_variant;
    return player_specified;
}
static boolean game_engine_get_current_stage(struct game_variant *variant,char *map) {
    if(stage_available) {*variant=stage_variant;strcpy(map,stage_map);}
    return stage_available;
}
static char *main_get_multiplayer_map_name(void) { return current_map; }
static boolean expanded(struct game_variant const *variant) {
    return starting_equipment_get(variant)==_starting_equipment_fiesta && game_variant_uses_expanded_weapon_set(variant);
}
int native_map_cache_prepare(char const *map,struct game_variant const *variant,
    struct native_map_cache_selection *selection,int show_error) {
    prepare_calls++;assert(map && variant);
    strcpy(prepared_map,map);prepared_variant=*variant;
    if(expanded(variant) && !arsenal_ready) {if(show_error)errors++;return FALSE;}
    memset(selection,0,sizeof(*selection));
    strcpy(selection->logical_name,map);selection->expanded=expanded(variant);
    snprintf(selection->physical_name,sizeof(selection->physical_name),"%s%s",selection->expanded ? "_fiesta_":"",map);
    selection->generation=selection->expanded;
    return TRUE;
}
void native_map_cache_select(struct native_map_cache_selection const *selection) {
    active_cache=*selection;select_calls++;record('S');
}
static boolean network_game_is_splitscreen_local(void) {return FALSE;}
static boolean cache_files_map_plays_multiplayer(char const *map,char *build) {(void)map;strcpy(build,"01.10.12.2276");return region_allowed;}
static void cache_files_show_multiplayer_unavailable(char const *map,char const *build) {(void)map;(void)build;errors++;}
static void network_game_server_change_map_name(void *server,char const *map) {
    struct native_map_cache_selection selection;
    assert(server==&live_game);server_changes++;record('C');
    if(host_accepts && native_map_cache_prepare(map,&live_game.variant,&selection,TRUE)) {
        native_map_cache_select(&selection);strcpy(live_game.map.name,map);
    }
}
static void main_set_multiplayer_map_name(char const *map) {
    assert(!strcmp(active_cache.logical_name,map));strcpy(current_map,map);main_changes++;record('M');
}
static void game_engine_override_map_name(char const *map) {(void)map;override_changes++;record('O');}
static void saved_game_file_remember_last_used_multiplayer_map(char const *map) {(void)map;map_history++;record('H');}
static boolean playlist_profile_get(long index,struct game_variant *variant) {
    assert((unsigned long)index==0x80000001u);if(profile_available)*variant=profile;return profile_available;
}
static boolean saved_game_file_get_path_to_enclosing_directory(long index,char *path) {(void)index;strcpy(path,"saved-game");return TRUE;}
static void saved_game_file_remember_last_used_multiplayer_variant_directory(char const *path) {(void)path;variant_history++;record('H');}
static void network_game_server_change_game_variant(void *server,struct game_variant *variant) {
    struct native_map_cache_selection selection;
    assert(server==&live_game);server_changes++;record('V');
    if(host_accepts && native_map_cache_prepare(live_game.map.name,variant,&selection,TRUE)) {
        native_map_cache_select(&selection);live_game.variant=*variant;
    }
}
static void player_ui_set_game_variant(struct game_variant *variant) {player_variant=*variant;player_specified=TRUE;player_changes++;record('P');}
static void network_game_server_pause_countdown(void *server,boolean paused) {assert(server==&live_game && !paused);pauses++;}
static void ui_play_audio_feedback_sound(short sound) {assert(sound==4);denied_sounds++;}
static void display_error_deferred(short code,short player,boolean modal,boolean pause) {(void)code;(void)player;(void)modal;(void)pause;errors++;}
static struct game_variant *game_engine_get_variant_by_name(struct game_variant *temporary,char const *name) {
    assert(!strcmp(name,"arsenal"));*temporary=automated_variant;return temporary;
}
static FILE *automation_file(char const *path,char const *mode) {
    char const *text=strstr(path,"variant_") ? variant_automation:map_automation;
    assert(!strcmp(mode,"r"));if(!text)return NULL;
    FILE *file=tmpfile();assert(file);fputs(text,file);rewind(file);return file;
}
#define fopen automation_file
/* CALLBACKS */
static void setup(void) {
    memset(&live_game,0,sizeof(live_game));memset(&player_variant,0,sizeof(player_variant));
    memset(&profile,0,sizeof(profile));memset(&stage_variant,0,sizeof(stage_variant));
    memset(&automated_variant,0,sizeof(automated_variant));memset(&active_cache,0,sizeof(active_cache));
    memset(&wrapper,0,sizeof(wrapper));memset(&screen,0,sizeof(screen));memset(&list,0,sizeof(list));
    definitions[0]=(struct ui_widget_definition){0,1};definitions[1]=(struct ui_widget_definition){0,3};
    definitions[2]=(struct ui_widget_definition){2,3};
    wrapper.definition_tag_index=0;wrapper.child=&screen;screen.definition_tag_index=1;screen.child=&list;
    list.definition_tag_index=2;list.generated_count=1;list.data3C.selected_index=0;
    map_names[0]="prisoner";profile_indices[0]=(long)0x80000001u;
    strcpy(live_game.map.name,"bloodgulch");strcpy(current_map,"bloodgulch");strcpy(stage_map,"prisoner");
    strcpy(active_cache.logical_name,"bloodgulch");strcpy(active_cache.physical_name,"bloodgulch");
    profile.game_engine_index=game_engine_slayer;live_game.variant=profile;player_variant=profile;stage_variant=profile;
    has_server=has_game=player_specified=host_accepts=region_allowed=profile_available=stage_available=TRUE;
    arsenal_ready=FALSE;map_automation=variant_automation=NULL;
    prepare_calls=select_calls=server_changes=main_changes=override_changes=player_changes=0;
    map_history=variant_history=pauses=denied_sounds=errors=0;order[0]=0;
}
static void set_fiesta(struct game_variant *variant,short set) {
    variant->universal_variant.weapon_set=set;assert(starting_equipment_set(variant,_starting_equipment_fiesta));
}
static void assert_no_selection_changes(void) {
    assert(!select_calls && !main_changes && !override_changes && !player_changes && !map_history && !variant_history && !pauses);
    assert(!strcmp(current_map,"bloodgulch") && !strcmp(active_cache.physical_name,"bloodgulch"));
}
static void map_cases(void) {
    for(short set=GAME_WEAPON_SET_UNCUT;set<=GAME_WEAPON_SET_ALL;set++) {
        setup();list.generated_list=map_names;set_fiesta(&live_game.variant,set);
        struct network_game before=live_game;
        assert(!multiplayer_level_select(&wrapper,&event,NULL));assert_no_selection_changes();
        assert(!server_changes && errors==1 && !memcmp(&before,&live_game,sizeof(before)));
        /* The lobby variant wins over a stale original player-profile selection. */
        assert(starting_equipment_get(&prepared_variant)==_starting_equipment_fiesta);
        arsenal_ready=TRUE;assert(multiplayer_level_select(&wrapper,&event,NULL));
        assert(!strcmp(order,"CSMOH") && !strcmp(current_map,"prisoner") && active_cache.expanded);
    }
    setup();list.generated_list=map_names;set_fiesta(&live_game.variant,GAME_WEAPON_SET_ALL);
    arsenal_ready=TRUE;host_accepts=FALSE;
    assert(!multiplayer_level_select(&wrapper,&event,NULL));assert_no_selection_changes();assert(server_changes==1);
    setup();list.generated_list=map_names;region_allowed=FALSE;
    assert(!multiplayer_level_select(&wrapper,&event,NULL));assert_no_selection_changes();assert(!server_changes && errors==1);
    /* Expanded sets without Fiesta retain ordinary map-local availability. */
    for(short set=GAME_WEAPON_SET_UNCUT;set<=GAME_WEAPON_SET_ALL;set++) {
        setup();has_server=has_game=FALSE;list.generated_list=map_names;player_variant.universal_variant.weapon_set=set;
        assert(multiplayer_level_select(&wrapper,&event,NULL));assert(!strcmp(order,"SMOH") && !active_cache.expanded && !errors);
    }
    setup();has_server=has_game=FALSE;list.generated_list=map_names;set_fiesta(&player_variant,GAME_WEAPON_SET_UNCUT);
    assert(!multiplayer_level_select(&wrapper,&event,NULL));assert_no_selection_changes();
    setup();has_server=has_game=player_specified=FALSE;list.generated_list=map_names;set_fiesta(&stage_variant,GAME_WEAPON_SET_ALL);
    assert(!multiplayer_level_select(&wrapper,&event,NULL));assert_no_selection_changes();
    setup();list.generated_list=map_names;map_names[0]="wizard";map_automation="prisoner\n";
    set_fiesta(&live_game.variant,GAME_WEAPON_SET_ALL);
    assert(!multiplayer_level_select(&wrapper,&event,NULL));assert(!strcmp(prepared_map,"prisoner"));assert_no_selection_changes();
}
static void profile_cases(void) {
    for(short set=GAME_WEAPON_SET_UNCUT;set<=GAME_WEAPON_SET_ALL;set++) {
        setup();list.generated_list=profile_indices;set_fiesta(&profile,set);
        struct network_game before=live_game;struct game_variant player_before=player_variant;
        assert(!multiplayer_profile_set_for_game(&wrapper,&event,NULL));assert_no_selection_changes();
        assert(!server_changes && !memcmp(&before,&live_game,sizeof(before)) && !memcmp(&player_before,&player_variant,sizeof(player_before)));
        arsenal_ready=TRUE;assert(multiplayer_profile_set_for_game(&wrapper,&event,NULL));
        assert(!strcmp(order,"VSPH") && active_cache.expanded && !memcmp(&profile,&player_variant,sizeof(profile)));
    }
    setup();list.generated_list=profile_indices;set_fiesta(&profile,GAME_WEAPON_SET_ALL);
    arsenal_ready=TRUE;host_accepts=FALSE;
    assert(!multiplayer_profile_set_for_game(&wrapper,&event,NULL));assert_no_selection_changes();assert(server_changes==1);
    /* A missing local map falls back to the stage map without replacing the proposed variant. */
    setup();has_server=has_game=FALSE;current_map[0]=0;list.generated_list=profile_indices;set_fiesta(&profile,GAME_WEAPON_SET_ALL);
    assert(!multiplayer_profile_set_for_game(&wrapper,&event,NULL));assert(!strcmp(prepared_map,"prisoner"));
    assert(expanded(&prepared_variant) && !select_calls && !player_changes && !variant_history);
    setup();list.generated_list=profile_indices;variant_automation="arsenal\n";automated_variant=profile;
    set_fiesta(&automated_variant,GAME_WEAPON_SET_ALL);
    assert(!multiplayer_profile_set_for_game(&wrapper,&event,NULL));assert_no_selection_changes();assert(expanded(&prepared_variant));
    setup();has_server=has_game=FALSE;list.generated_list=profile_indices;profile.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    assert(multiplayer_profile_set_for_game(&wrapper,&event,NULL));assert(!strcmp(order,"SPH") && !active_cache.expanded && !errors);
    setup();list.generated_list=profile_indices;profile_available=FALSE;
    assert(!multiplayer_profile_set_for_game(&wrapper,&event,NULL));assert_no_selection_changes();assert(!prepare_calls);
}
static void start_cases(void) {
    setup();set_fiesta(&live_game.variant,GAME_WEAPON_SET_ALL);
    assert(!network_game_server_allow_game_start(&wrapper,&event,NULL));assert_no_selection_changes();assert(!errors);
    arsenal_ready=TRUE;assert(network_game_server_allow_game_start(&wrapper,&event,NULL));assert(pauses==1 && !select_calls);
    setup();live_game.variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    assert(network_game_server_allow_game_start(&wrapper,&event,NULL));assert(pauses==1 && !errors);
    setup();has_server=FALSE;assert(network_game_server_allow_game_start(&wrapper,&event,NULL));assert(!pauses && !prepare_calls);
}
int main(void) {
    assert(sizeof(struct game_variant)==104);map_cases();profile_cases();start_cases();
    puts("Fiesta menu preflight tests passed");return 0;
}
'''


class FiestaMenuPreflightTests(unittest.TestCase):
    def test_production_selection_and_start_callbacks(self):
        engine = (ROOT / "source/game/game_engine.h").read_text()
        handlers = (ROOT / "source/interface/ui_widget_event_handler_functions.c").read_text()
        variants = "\n".join(c_block(engine, signature) + ";" for signature in (
            "struct universal_variant\n", "struct ctf_variant\n", "struct slayer_variant\n",
            "struct king_variant\n", "struct oddball_variant\n", "struct race_variant\n",
            "union game_engine_variant\n", "struct game_variant\n"))
        private = handlers[handlers.index("/* ---------- private code */"):]
        # The retail/native map-list branches each open the same for-loop;
        # keep preprocessing intact rather than counting both sets of braces.
        map_start = private.index("static boolean multiplayer_level_select(\n")
        map_end = private.index("\nboolean playlist_profile_get(\n", map_start)
        callbacks = "\n".join((
            c_block(private, "static boolean multiplayer_prepare_cache_selection(\n"),
            private[map_start:map_end],
            c_block(private, "static boolean multiplayer_profile_set_for_game(\n"),
            c_block(private, "static boolean network_game_server_allow_game_start(\n")))
        source = HARNESS.replace("/* VARIANTS */", variants).replace("/* CALLBACKS */", callbacks)
        source = re.sub(r"\bunsigned long\b", "uint32_t", source)
        source = re.sub(r"\blong\b", "int32_t", source)
        with tempfile.TemporaryDirectory(prefix="halo-fiesta-menu-preflight-") as temporary:
            folder = Path(temporary)
            (folder / "fixture.c").write_text(source)
            subprocess.run(["clang", "-std=c99", "-fshort-wchar", "-Wall", "-Wextra", "-Werror",
                            "-Wno-multichar", "-Wno-unused-parameter", "-Wno-format", "-Wno-sign-compare",
                            "-I", str(ROOT / "source"), "-iquote", str(ROOT / "port/linux/include"),
                            str(folder / "fixture.c"), "-o", str(folder / "fixture")], check=True)
            result = subprocess.run([str(folder / "fixture")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "Fiesta menu preflight tests passed")


if __name__ == "__main__":
    unittest.main()
