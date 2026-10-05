"""Exercise production map-list initialization, display, selection and navigation.

Widget tag lookup, persisted settings and game/network side effects are fixtures;
all four menu callbacks, the visible-row helper and map identity helpers are the
real production C functions. Optional owned-cache checks use original font/tag
metrics to verify empty-state text fits the retail map cards.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_runtime_ui_tags import c_block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "halo_custom_maps.h"
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define NUMBEROF(a) (sizeof(a) / sizeof((a)[0]))
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define match_assert(file,line,condition) assert(condition)
#define match_vassert(file,line,condition,message) assert(condition)
#define TEST_FLAG(value,bit) ((value) & (1u << (bit)))
#define selected_list_item_index selected_index
#define generated_list parameters.list.list_items
#define generated_count parameters.list.number_of_items
#define data3C parameters.list
#define _error_silent 0
typedef int boolean;
enum { _ui_widget_type_column_list=3, _ui_widget_type_spinner_list=2,
       _ui_widget_type_text_box=1, _ui_widget_type_bitmap=4 };
enum { _list_items_generated_in_code, _list_items_generated_from_string_list_tag };
enum { LIST, ITEM, NAME, BITMAP, DESCRIPTION, WRAPPER, SCREEN, DEFINITION_COUNT };
struct event_record { short controller_index; };
struct ui_widget_definition {
    int type, child_count;
    struct { int count; } child_widgets;
    unsigned list_flags;
};
struct widget_instance {
    long definition_tag_index;
    short type, local_player_index;
    boolean visible;
    struct widget_instance *child, *next, *previous, *parent, *focused_child;
    struct {
        struct { wchar_t *text; short string_list_index; } text_box;
        struct {
            char **list_items;
            short selected_index, number_of_items, last_list_tab_direction;
        } list;
    } parameters;
    struct { short current_frame_index; } animation;
};
static struct ui_widget_definition definitions[DEFINITION_COUNT] = {
    {2,3,{3},1u << _list_items_generated_in_code}, {0,3,{3},0},
    {1,0,{0},0}, {4,0,{0},0}, {1,0,{0},0}, {0,1,{1},0}, {0,3,{3},0}
};
static struct widget_instance list, rows[3], names[3], bitmaps[3], descriptions[3], wrapper, screen;
static char **filtered_maps;
static short filtered_count;
static char const *last_used;
static unsigned persisted_reads, committed, overridden, remembered, feedback, focus_changes;
static char selected_map[128];
static struct ui_widget_definition *ui_widget_definition_get(long index) {
    assert(index>=0 && index<DEFINITION_COUNT); return &definitions[index];
}
static struct widget_instance *widget_instance_get_nth_child(struct widget_instance *parent, long index) {
    struct widget_instance *child=parent->child;
    while(index-- && child) child=child->next;
    assert(child); return child;
}
static void *ui_widget_realloc(void *pointer, size_t size, const char *file, long line) {
    (void)file; (void)line; void *result=realloc(pointer,size); assert(result); return result;
}
static int fixture_stricmp(const char *a, const char *b) {
    while(*a && tolower((unsigned char)*a)==tolower((unsigned char)*b)) {a++;b++;}
    return tolower((unsigned char)*a)-tolower((unsigned char)*b);
}
#define _stricmp fixture_stricmp
static char **native_multiplayer_map_list_fixture(char **stock, short stock_count, short *count) {
    assert(stock && stock_count==13); *count=filtered_count; return filtered_maps;
}
#define native_multiplayer_map_list native_multiplayer_map_list_fixture
static boolean saved_game_file_retrieve_last_used_multiplayer_map(char *out) {
    persisted_reads++;
    if(!last_used) return FALSE;
    strcpy(out,last_used); return TRUE;
}
static void ui_play_audio_feedback_sound(short sound) { assert(sound==4); feedback++; }
static void main_set_multiplayer_map_name(char *map) { committed++; strcpy(selected_map,map); }
static void game_engine_override_map_name(char *map) { overridden++; assert(!strcmp(map,selected_map)); }
static void *global_network_game_server_get(void) { return NULL; }
static boolean network_game_is_splitscreen_local(void) { return TRUE; }
static boolean cache_files_map_plays_multiplayer(char *map, char *build) {
    (void)map; (void)build; return TRUE;
}
static void cache_files_show_multiplayer_unavailable(char *map, char *build) { (void)map; (void)build; assert(FALSE); }
static void network_game_server_change_map_name(void *server, char *map) { (void)server; (void)map; assert(FALSE); }
static void saved_game_file_remember_last_used_multiplayer_map(char *map) {
    remembered++; assert(!strcmp(map,selected_map));
}
static void widget_instance_give_focus_directly(struct widget_instance *parent, struct widget_instance *child) {
    assert(parent==&list); parent->focused_child=child; focus_changes++;
}
static void widget_instance_give_focus_by_tag(struct widget_instance *widget, long index, short player) {
    (void)widget; (void)index; (void)player; assert(FALSE);
}
static void error(int severity, char const *message, ...) { (void)severity; (void)message; assert(FALSE); }
/* PRODUCTION */
static void setup(void) {
    memset(&list,0,sizeof(list)); memset(rows,0,sizeof(rows));
    memset(names,0,sizeof(names)); memset(bitmaps,0,sizeof(bitmaps)); memset(descriptions,0,sizeof(descriptions));
    memset(&wrapper,0,sizeof(wrapper)); memset(&screen,0,sizeof(screen));
    list.definition_tag_index=LIST; list.type=_ui_widget_type_spinner_list; list.child=rows;
    list.focused_child=&rows[0];
    wrapper.definition_tag_index=WRAPPER; wrapper.child=&screen;
    screen.definition_tag_index=SCREEN; screen.child=&list;
    for(unsigned i=0;i<3;i++) {
        rows[i].definition_tag_index=ITEM; rows[i].child=&names[i];
        rows[i].next=i<2 ? &rows[i+1]:NULL; rows[i].previous=i ? &rows[i-1]:NULL;
        names[i].definition_tag_index=NAME; names[i].next=&bitmaps[i];
        bitmaps[i].definition_tag_index=BITMAP; bitmaps[i].next=&descriptions[i];
        descriptions[i].definition_tag_index=DESCRIPTION;
        rows[i].visible=names[i].visible=bitmaps[i].visible=descriptions[i].visible=TRUE;
    }
    for(unsigned i=0;i<NUMBEROF(stock_names);i++)
        event_handler_functions.multiplayer_levels[i]=(char *)stock_names[i];
}
static void cleanup(void) {
    for(unsigned i=0;i<3;i++) { free(names[i].parameters.text_box.text); free(descriptions[i].parameters.text_box.text); }
}
static void initialize(char **maps, short count) {
    boolean deleted=FALSE; struct event_record event={0};
    filtered_maps=maps; filtered_count=count;
    assert(multiplayer_level_list_initialize(&list,&event,&deleted));
    assert(!deleted && list.generated_list==maps && list.generated_count==count);
}
static boolean select_map(void) {
    boolean deleted=FALSE; struct event_record event={0};
    boolean result=multiplayer_level_select(&wrapper,&event,&deleted);
    assert(!deleted); return result;
}
static int caption_equals(const wchar_t *actual, const char *expected) {
    if(!actual) return FALSE;
    while(*actual && *expected && *actual==(unsigned char)*expected) {actual++;expected++;}
    return !*actual && !*expected;
}
static void empty_state(void) {
    char *custom[]={"chillout_digsite"};
    initialize(custom,1); mp_level_select_list_update_displayed_items(&list);
    for(unsigned i=0;i<3;i++) assert(rows[i].visible && bitmaps[i].visible);
    list.data3C.selected_index=12;
    initialize(custom,0);
    assert(list.data3C.selected_index==NONE && persisted_reads==1);
    mp_level_select_list_update_displayed_items(&list);
    assert(rows[0].visible && !rows[1].visible && !rows[2].visible);
    for(unsigned i=0;i<3;i++) assert(!bitmaps[i].visible);
    assert(names[0].parameters.text_box.string_list_index==HALO_CUSTOM_MAP_TEXT);
    assert(caption_equals(names[0].parameters.text_box.text,"No Maps"));
    assert(caption_equals(descriptions[0].parameters.text_box.text,"Enable Map Groups\rIn Settings Or\rInstall Maps."));
    assert(!select_map());
    assert(!committed && !overridden && !remembered && feedback==1);
    initialize(NULL,0); mp_level_select_list_update_displayed_items(&list);
    assert(rows[0].visible && !rows[1].visible && !rows[2].visible);
    assert(!select_map() && feedback==2);
}
static void restored_stock(void) {
    char *custom[]={"chillout_digsite"}, *stock[13];
    initialize(custom,1); mp_level_select_list_update_displayed_items(&list);
    initialize(NULL,0); mp_level_select_list_update_displayed_items(&list);
    for(unsigned i=0;i<NUMBEROF(stock_names);i++) stock[i]=(char *)stock_names[i];
    list.data3C.selected_index=12;
    initialize(stock,13);
    assert(list.data3C.selected_index==0);
    list.focused_child=&rows[1];
    mp_level_select_list_update_displayed_items(&list);
    short expected[]={12,0,1};
    for(unsigned i=0;i<3;i++) {
        assert(rows[i].visible && bitmaps[i].visible);
        assert(names[i].parameters.text_box.string_list_index==expected[i]);
        assert(descriptions[i].parameters.text_box.string_list_index==expected[i]);
        assert(bitmaps[i].animation.current_frame_index==expected[i]);
    }
    assert(select_map());
    assert(committed==1 && overridden==1 && remembered==1 && !feedback);
    assert(!strcmp(selected_map,"beavercreek"));
}
static void restored_custom(void) {
    char *maps[]={"chillout_digsite"};
    initialize(NULL,0); mp_level_select_list_update_displayed_items(&list);
    initialize(maps,1); list.focused_child=&rows[2];
    mp_level_select_list_update_displayed_items(&list);
    for(unsigned i=0;i<3;i++) {
        assert(rows[i].visible && bitmaps[i].visible);
        assert(caption_equals(names[i].parameters.text_box.text,"Chillout Digsite"));
        assert(caption_equals(descriptions[i].parameters.text_box.text,"Community Map"));
        assert(bitmaps[i].animation.current_frame_index==13);
    }
    assert(select_map() && !strcmp(selected_map,"chillout_digsite"));
    assert(committed==1 && overridden==1 && remembered==1 && !feedback);
}
static void saved_selection(void) {
    char *maps[]={"chillout_digsite","authored_map"};
    last_used="missing_map"; list.data3C.selected_index=12;
    initialize(maps,2); assert(list.data3C.selected_index==0);
    last_used="authored_map";
    initialize(maps,2); assert(list.data3C.selected_index==1);
    assert(select_map());
    assert(committed==1 && overridden==1 && remembered==1);
    assert(!strcmp(selected_map,"authored_map"));
    initialize(maps,0); assert(list.data3C.selected_index==NONE && persisted_reads==2);
}
static void invalid_selection(void) {
    char *maps[]={"chillout_digsite"};
    initialize(maps,1);
    short invalid[]={NONE,-2,1,12};
    for(unsigned i=0;i<NUMBEROF(invalid);i++) {
        list.data3C.selected_index=invalid[i]; assert(!select_map());
    }
    list.data3C.selected_index=0; list.generated_list=NULL; assert(!select_map());
    assert(!committed && !overridden && !remembered && feedback==5);
}
static void empty_navigation(void) {
    char *stale[]={"chillout_digsite"};
    boolean deleted=FALSE; struct event_record event={0};
    for(unsigned pointer=0;pointer<2;pointer++) {
        initialize(pointer ? stale:NULL,0);
        for(unsigned focus=0;focus<3;focus++) {
            list.focused_child=&rows[focus];
            for(unsigned repeat=0;repeat<100;repeat++) {
                assert(widget_event_function_list_widget_goto_next_item(&list,&event,&deleted));
                assert(widget_event_function_list_widget_goto_previous_item(&list,&event,&deleted));
            }
            assert(list.data3C.selected_index==NONE && list.focused_child==&rows[focus]);
            assert(!list.parameters.list.last_list_tab_direction && !deleted);
        }
    }
    assert(!focus_changes);
}
static void populated_navigation(void) {
    char *stock[13]; boolean deleted=FALSE; struct event_record event={0};
    for(unsigned i=0;i<NUMBEROF(stock_names);i++) stock[i]=(char *)stock_names[i];
    initialize(stock,13);
    assert(widget_event_function_list_widget_goto_next_item(&list,&event,&deleted));
    assert(list.data3C.selected_index==1 && list.focused_child==&rows[1]);
    assert(list.parameters.list.last_list_tab_direction==15);
    assert(widget_event_function_list_widget_goto_previous_item(&list,&event,&deleted));
    assert(list.data3C.selected_index==0 && list.focused_child==&rows[0]);
    assert(widget_event_function_list_widget_goto_previous_item(&list,&event,&deleted));
    assert(list.data3C.selected_index==12 && list.focused_child==&rows[0]);
    assert(list.parameters.list.last_list_tab_direction==-15);
    assert(!deleted);
}
static void empty_captions(void) {
    initialize(NULL,0); mp_level_select_list_update_displayed_items(&list);
    const wchar_t *captions[]={names[0].parameters.text_box.text,descriptions[0].parameters.text_box.text};
    for(unsigned i=0;i<NUMBEROF(captions);i++) {
        assert(captions[i]);
        for(unsigned j=0;captions[i][j];j++) printf("%u ",(unsigned)captions[i][j]);
        puts("");
    }
}
int main(int argc, char **argv) {
    assert(argc==2); setup();
    if(!strcmp(argv[1],"empty")) empty_state();
    else if(!strcmp(argv[1],"restore")) restored_stock();
    else if(!strcmp(argv[1],"restore-custom")) restored_custom();
    else if(!strcmp(argv[1],"saved")) saved_selection();
    else if(!strcmp(argv[1],"invalid")) invalid_selection();
    else if(!strcmp(argv[1],"empty-navigation")) empty_navigation();
    else if(!strcmp(argv[1],"navigation")) populated_navigation();
    else if(!strcmp(argv[1],"empty-captions")) empty_captions();
    else assert(!"unknown test case");
    cleanup(); return 0;
}
'''


def fixture_source():
    handlers = (ROOT / "source/interface/ui_widget_event_handler_functions.c").read_text()
    inputs = (ROOT / "source/interface/ui_widget_game_data_input_functions.c").read_text()
    widgets = (ROOT / "source/interface/ui_widget.c").read_text()
    maps = (ROOT / "port/linux/game/custom_maps.c").read_text()
    production = [c_block(maps, "static char const *stock_names[]") + ";",
                  c_block(maps, "char const *native_map_basename("),
                  c_block(maps, "int native_map_is_custom("),
                  "static struct { char *multiplayer_levels[13]; } event_handler_functions;"]
    for source, signature in ((inputs, "static void custom_map_text("),
                              (inputs, "static void spinner_list_3wide_determine_displayed_item_indices("),
                              (inputs, "static void mp_level_select_list_update_displayed_items("),
                              (handlers, "static boolean multiplayer_level_list_initialize("),
                              (handlers, "static boolean multiplayer_level_select("),
                              (widgets, "boolean widget_event_function_list_widget_goto_next_item("),
                              (widgets, "boolean widget_event_function_list_widget_goto_previous_item(")):
        if signature == "static boolean multiplayer_level_select(":
            # Retail/native branches each open the final remember-map loop.
            # Extract this complete function through the next declaration so
            # clang resolves the preprocessor branches before checking braces.
            start = source.rindex(signature)
            production.append(source[start:source.index("boolean playlist_profile_get(", start)])
        else:
            production.append(c_block(source[source.rindex(signature):], signature))
    return PREFIX.replace("/* PRODUCTION */", "\n".join(production))


class MultiplayerMapSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang")
        if not compiler:
            raise unittest.SkipTest("clang required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-map-selection-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        source = folder / "fixture.c"
        source.write_text(fixture_source())
        cls.executable = folder / ("fixture.exe" if sys.platform == "win32" else "fixture")
        command = [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                   "-fshort-wchar", "-iquote", str(ROOT / "port/linux/include")]
        if sys.platform != "win32":
            command += ["-fsanitize=undefined"]
        compiled = subprocess.run([*command, str(source), "-o", str(cls.executable)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + compiled.stderr)

    def run_case(self, case):
        result = subprocess.run([str(self.executable), case],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_list_hides_previous_maps_and_refuses_selection(self):
        self.run_case("empty")

    def test_reenabled_stock_maps_restore_retail_art_text_and_selection(self):
        self.run_case("restore")

    def test_reenabled_custom_map_restores_caption_art_and_selection(self):
        self.run_case("restore-custom")

    def test_saved_hidden_map_falls_back_to_first_available_map(self):
        self.run_case("saved")

    def test_invalid_or_stale_selection_has_no_game_or_saved_map_side_effects(self):
        self.run_case("invalid")

    def test_empty_generated_spinner_navigation_is_safe_with_every_focused_row(self):
        self.run_case("empty-navigation")

    def test_populated_spinner_retains_retail_navigation_and_wraparound(self):
        self.run_case("navigation")

    def test_empty_captions_fit_all_three_original_map_cards(self):
        from tools.verify_performance_sound_samples import Cache
        path = next((root / "assets/maps/ui.map" for root in (ROOT, ROOT.parent / "pfista-halo-macos")
                     if (root / "assets/maps/ui.map").exists()), None)
        if path is None:
            self.skipTest("owned Xbox UI cache required for font metrics")
        result = subprocess.run([str(self.executable), "empty-captions"],
                                capture_output=True, text=True, check=True, timeout=10)
        captions = ["".join(chr(int(code)) for code in line.split()) for line in result.stdout.splitlines()]
        self.assertEqual(len(captions), 2)
        cache = Cache(path)
        prefix = r"ui\shell\main_menu\multiplayer_type_select\mp_map_select\mp_map_"
        for position in ("left", "center", "right"):
            for part, caption in zip(("name", "data"), captions):
                with self.subTest(position=position, part=part, caption=caption):
                    widget = cache.by_path[prefix + position + "_" + part]
                    self.assertEqual(widget["group"], "DeLa")
                    address = widget["address"]
                    y0, x0, y1, x1 = cache.unpack("<4h", address + 0x24)
                    offset_x, offset_y = cache.unpack("<2h", address + 0x130)
                    width, height = x1 - x0 - offset_x, y1 - y0 - offset_y
                    font = cache.tags[cache.unpack("<I", address + 0x108)[0]]
                    self.assertEqual(font["group"], "font")
                    ascending, descending, leading, inset = cache.unpack("<4h", font["address"] + 4)
                    line_height = ascending + descending + leading
                    count, characters, _ = cache.unpack("<3I", font["address"] + 0x7C)
                    glyphs = {}
                    for index in range(count):
                        code, advance, ink_width, ink_height, origin_x, origin_y = cache.unpack(
                            "<H5h", characters + index * 0x14)
                        glyphs[chr(code)] = advance, ink_width, ink_height, origin_x, origin_y
                    lines = caption.split("\r")
                    self.assertLessEqual(len(lines) * line_height, height)
                    for row, line in enumerate(lines):
                        cursor = inset
                        baseline = ascending + row * line_height
                        ink_right = cursor
                        for character in line:
                            self.assertIn(character, glyphs)
                            advance, ink_width, ink_height, origin_x, origin_y = glyphs[character]
                            if ink_width and ink_height:
                                self.assertGreaterEqual(cursor - origin_x, 0)
                                self.assertGreaterEqual(baseline - origin_y, 0)
                                # The rasterizer also draws a one-pixel drop shadow.
                                self.assertLessEqual(baseline - origin_y + ink_height + 1, height)
                                ink_right = max(ink_right, cursor - origin_x + ink_width)
                            cursor += advance
                        self.assertLessEqual(max(cursor, ink_right) + 1, width)


if __name__ == "__main__":
    unittest.main()
