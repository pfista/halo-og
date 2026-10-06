"""Exercise the production map-caption callback without game data or rendering.

Only widget lookup, allocation and visible-row selection are stubbed. The real
callback, caption formatter and map identity helpers determine displayed content.
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
#define match_vassert(file,line,condition,message) assert(condition)
enum { _ui_widget_type_text_box=1, _ui_widget_type_spinner_list=2, _ui_widget_type_bitmap=4 };
enum { LIST, ITEM, NAME, BITMAP, DESCRIPTION, DEFINITION_COUNT };
struct ui_widget_definition { int type, child_count; };
struct widget_instance {
    long definition_tag_index;
    struct widget_instance *child, *next;
    struct {
        struct { wchar_t *text; short string_list_index; } text_box;
        struct { char **list_items; short selected_index, number_of_items; } list;
    } parameters;
    struct { short current_frame_index; } animation;
};
static struct ui_widget_definition definitions[DEFINITION_COUNT] = {
    {2,3}, {0,3}, {1,0}, {4,0}, {1,0}
};
static struct widget_instance list, rows[3], names[3], bitmaps[3], descriptions[3];
static long visible[3];
static struct ui_widget_definition *ui_widget_definition_get(long index) {
    assert(index>=0 && index<DEFINITION_COUNT); return &definitions[index];
}
static struct widget_instance *widget_instance_get_nth_child(struct widget_instance *parent, long index) {
    struct widget_instance *child=parent->child;
    while(index-- && child) child=child->next;
    assert(child); return child;
}
static void spinner_list_3wide_determine_displayed_item_indices(struct widget_instance *widget, long *out) {
    assert(widget==&list);
    for(unsigned i=0;i<3;i++) {
        assert(visible[i]==NONE || (visible[i]>=0 && visible[i]<widget->parameters.list.number_of_items));
        out[i]=visible[i];
    }
}
static void *ui_widget_realloc(void *pointer, size_t size, const char *file, long line) {
    (void)file; (void)line; void *result=realloc(pointer,size); assert(result); return result;
}
/* Platform case-insensitive string comparison, not a replacement classifier. */
static int fixture_stricmp(const char *a, const char *b) {
    while(*a && tolower((unsigned char)*a)==tolower((unsigned char)*b)) {a++;b++;}
    return tolower((unsigned char)*a)-tolower((unsigned char)*b);
}
#define _stricmp fixture_stricmp
/* CE discovery is a controlled dependency; the production level-index adapter
keeps its display namespace distinct from indices into the filtered list. */
#define FIRST_DISPLAY_INDEX 0x4000
static struct custom_edition_maps_globals { short xbox_level_count, map_count; } custom_edition_maps_globals;
static short custom_edition_map_display_index(char const *map) {
    return !strncmp(map,"custom_maps\\",12) ? FIRST_DISPLAY_INDEX : NONE;
}
/* CE INDEX ADAPTER */
/* PRODUCTION */
static void setup(void) {
    memset(&list,0,sizeof(list)); memset(rows,0,sizeof(rows));
    memset(names,0,sizeof(names)); memset(bitmaps,0,sizeof(bitmaps)); memset(descriptions,0,sizeof(descriptions));
    list.definition_tag_index=LIST; list.child=rows;
    for(unsigned i=0;i<3;i++) {
        rows[i].definition_tag_index=ITEM; rows[i].child=&names[i]; rows[i].next=i<2 ? &rows[i+1]:NULL;
        names[i].definition_tag_index=NAME; names[i].next=&bitmaps[i];
        bitmaps[i].definition_tag_index=BITMAP; bitmaps[i].next=&descriptions[i];
        descriptions[i].definition_tag_index=DESCRIPTION;
        names[i].parameters.text_box.string_list_index=-99;
        descriptions[i].parameters.text_box.string_list_index=-99;
        bitmaps[i].animation.current_frame_index=-99;
    }
}
static void cleanup(void) {
    for(unsigned i=0;i<3;i++) { free(names[i].parameters.text_box.text); free(descriptions[i].parameters.text_box.text); }
}
static void render(char **maps, short count, short selected, long a, long b, long c) {
    char *before[HALO_CUSTOM_MAP_LIMIT];
    assert(count>0 && count<=HALO_CUSTOM_MAP_LIMIT && selected>=0 && selected<count);
    memcpy(before,maps,count*sizeof(*maps));
    list.parameters.list.list_items=maps;
    list.parameters.list.number_of_items=count; list.parameters.list.selected_index=selected;
    custom_edition_maps_globals.xbox_level_count=count;
    custom_edition_maps_globals.map_count=0;
    for(short i=0;i<count;i++) if(custom_edition_map_display_index(maps[i])!=NONE) {
        custom_edition_maps_globals.xbox_level_count=i;
        custom_edition_maps_globals.map_count=count-i; break;
    }
    char *selected_id=maps[selected];
    visible[0]=a;visible[1]=b;visible[2]=c;
    mp_level_select_list_update_displayed_items(&list);
    /* Formatting a filtered list must never change which cache gets selected. */
    assert(list.parameters.list.list_items==maps && list.parameters.list.number_of_items==count);
    assert(list.parameters.list.selected_index==selected && maps[selected]==selected_id);
    assert(!memcmp(before,maps,count*sizeof(*maps)));
}
static void stock_row(unsigned row, short index) {
    assert(names[row].parameters.text_box.string_list_index==index);
    assert(descriptions[row].parameters.text_box.string_list_index==index);
    assert(bitmaps[row].animation.current_frame_index==index);
}
static int caption_equals(const wchar_t *actual, const char *expected) {
    if(!actual) return FALSE;
    while(*actual && *expected && *actual==(unsigned char)*expected) {actual++;expected++;}
    return !*actual && !*expected;
}
static void custom_row(unsigned row, const char *caption) {
    assert(names[row].parameters.text_box.string_list_index==HALO_CUSTOM_MAP_TEXT);
    assert(caption_equals(names[row].parameters.text_box.text,caption));
    assert(descriptions[row].parameters.text_box.string_list_index==HALO_CUSTOM_MAP_TEXT);
    assert(caption_equals(descriptions[row].parameters.text_box.text,"Community Map"));
    assert(bitmaps[row].animation.current_frame_index==13);
}
static void stock_captions(void) {
    char *maps[13]; assert(NUMBEROF(stock_names)==NUMBEROF(maps));
    for(unsigned i=0;i<NUMBEROF(maps);i++) maps[i]=(char *)stock_names[i];
    for(unsigned i=0;i<NUMBEROF(maps);i++) {
        assert(!native_map_is_custom(maps[i]));
        char path[128]; snprintf(path,sizeof(path),"levels\\test\\fixture\\%s",stock_names[i]);
        assert(!native_map_is_custom(path));
        render(maps,13,(short)i,i,NONE,NONE); stock_row(0,(short)i);
    }
    assert(!native_map_is_custom("levels/test/CHILLOUT/CHILLOUT"));
}
static void community_only_captions(void) {
    char *maps[14]; for(unsigned i=0;i<NUMBEROF(maps);i++) maps[i]="community_map";
    maps[0]="chillout_digsite"; maps[6]="levels\\dig\\chillout\\chillout_digsite"; maps[13]="h1pb_chillout";
    render(maps,14,6,0,6,13);
    custom_row(0,"Chillout Digsite"); custom_row(1,"Chillout Digsite"); custom_row(2,"H1pb Chillout");
}
static void mixed_captions(void) {
    char *maps[14]; for(unsigned i=0;i<NUMBEROF(stock_names);i++) maps[i]=(char *)stock_names[i];
    maps[13]="chillout_digsite";
    render(maps,14,13,12,13,NONE); stock_row(0,12); custom_row(1,"Chillout Digsite");
    assert(names[2].parameters.text_box.string_list_index==-99 && bitmaps[2].animation.current_frame_index==-99);
}
static void reused_rows(void) {
    char *community[]={"chillout_digsite"}, *stock[13];
    render(community,1,0,0,NONE,NONE); custom_row(0,"Chillout Digsite");
    for(unsigned i=0;i<NUMBEROF(stock_names);i++) stock[i]=(char *)stock_names[i];
    render(stock,13,0,0,1,2);
    for(unsigned i=0;i<3;i++) stock_row(i,(short)i);
}
static void ce_captions(void) {
    char *maps[]={"bloodgulch","chillout_digsite","custom_maps\\bloodgulch"};
    render(maps,3,2,1,2,NONE);
    custom_row(0,"Chillout Digsite"); stock_row(1,FIRST_DISPLAY_INDEX);
    assert(names[1].parameters.text_box.text==NULL);
    assert(list.parameters.list.selected_index==2);
}
int main(int argc, char **argv) {
    assert(argc==2); setup();
    if(!strcmp(argv[1],"stock")) stock_captions();
    else if(!strcmp(argv[1],"community")) community_only_captions();
    else if(!strcmp(argv[1],"mixed")) mixed_captions();
    else if(!strcmp(argv[1],"reuse")) reused_rows();
    else if(!strcmp(argv[1],"ce")) ce_captions();
    else assert(!"unknown test case");
    cleanup(); return 0;
}
'''


def fixture_source():
    widgets = (ROOT / "source/interface/ui_widget_game_data_input_functions.c").read_text()
    maps = (ROOT / "port/linux/game/custom_maps.c").read_text()
    # Include the exact retail name table and both production identity helpers.
    identities = maps[maps.index("static char const *stock_names[]"):
                      maps.index("static unsigned long little_u32")]
    callback = "static void mp_level_select_list_update_displayed_items("
    production = "\n".join((identities,
                            c_block(widgets, "static void custom_map_text("),
                            c_block(widgets[widgets.rindex(callback):], callback)))
    ce = (ROOT / "port/linux/game/custom_edition_maps.c").read_text()
    return PREFIX.replace("/* PRODUCTION */", production).replace("/* CE INDEX ADAPTER */",
        c_block(ce,"short custom_edition_maps_level_display_index(\n"))


class CustomMapCaptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang")
        if not compiler:
            raise unittest.SkipTest("clang required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-map-captions-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        source = folder / "fixture.c"
        source.write_text(fixture_source())
        cls.executable = folder / ("fixture.exe" if sys.platform == "win32" else "fixture")
        command = [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-fshort-wchar",
                   "-iquote", str(ROOT / "port/linux/include")]
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

    def test_all_stock_maps_keep_retail_strings_and_art(self):
        self.run_case("stock")

    def test_community_only_list_uses_actual_map_ids_at_zero_six_and_thirteen(self):
        self.run_case("community")

    def test_mixed_list_keeps_stock_and_custom_content_distinct(self):
        self.run_case("mixed")

    def test_reused_custom_row_restores_stock_strings_and_art(self):
        self.run_case("reuse")

    def test_ce_display_id_keeps_original_list_index_and_community_caption(self):
        self.run_case("ce")


if __name__ == "__main__":
    unittest.main()
