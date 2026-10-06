"""Exercise Fiesta's authored Item Options clones and real editor callbacks.

The fixtures use production widget/cache declarations, variant helpers and
callbacks. Platform rendering and multiplayer play remain native app checks.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.test_performance_ui import fixture_source
from tools.test_runtime_ui_tags import c_block

ROOT = Path(__file__).resolve().parents[1]

CLONE_HARNESS = r'''
#include "interface/fiesta_item_options_menu.inc"
#define ITEM_PREFIX "ui\\shell\\main_menu\\settings_select\\multiplayer_setup\\item_options_edit\\"
enum { ITEM_SCREEN,ITEM_MENU,ITEM_ROW,ITEM_SPINNER,ITEM_HELP,ITEM_LABEL,
 ITEM_ROW0,ITEM_ROW1,ITEM_ROW2,ITEM_SPINNER0,ITEM_SPINNER1,ITEM_SPINNER2,ITEM_OTHER,
 ITEM_WIDGET_COUNT,ITEM_VALUES=ITEM_WIDGET_COUNT,ITEM_DESCRIPTIONS,ITEM_STRINGS0,ITEM_STRINGS1,ITEM_STRINGS2,ITEM_COUNT };
static const char *item_names[ITEM_COUNT]={
 ITEM_PREFIX "item_options_screen",ITEM_PREFIX "item_options_menu",ITEM_PREFIX "op_starting_equipment",
 ITEM_PREFIX "item_options_starting_equipment_spinner",ITEM_PREFIX "item_options_help",
 ITEM_PREFIX "item_options_starting_equipment_label","fixture\\row0","fixture\\row1",ITEM_PREFIX "op_weapon_set",
 "fixture\\spinner0","fixture\\spinner1",ITEM_PREFIX "item_options_weapon_set_spinner","fixture\\other",
 ITEM_PREFIX "var_starting_equipment",ITEM_PREFIX "cap_item_options","fixture\\strings0","fixture\\strings1","fixture\\strings2"};
static struct {
 struct ui_widget_definition defs[ITEM_WIDGET_COUNT];
 struct ui_widget_child_reference screen[3],menu[4],rows[4][2];
 struct ui_widget_event_handler_reference events[3];
 struct ui_widget_game_data_input_reference input;
 struct string_list lists[5];
 struct string_list_entry values[2],descriptions[19],other_values[3][10];
 wchar_t custom[7],generic[8],help[19][20];
} authored,original;
static struct cache_file_tag_instance item_tags[ITEM_COUNT];
static struct cache_file_tag_header item_header={ITEM_COUNT,0x39393939};
static long item_id(unsigned index) { return 0x34560000|index; }
static struct tag_reference item_ref(unsigned index) {
 return pb_editor_reference(index>=ITEM_WIDGET_COUNT ? 'ustr':'DeLa',item_id(index));
}
static void setup_items(void) {
 if(cache_file_globals.tags_loaded) {
   unsigned previous_unloads=unload_calls;
   scenario_tags_unload();
   assert(unload_calls==previous_unloads+5);
 }
 memset(&authored,0,sizeof(authored)); memset(item_tags,0,sizeof(item_tags));
 register_calls=fail_registration=0;
 for(unsigned i=0;i<ITEM_WIDGET_COUNT;i++) {
   struct ui_widget_definition *d=&authored.defs[i];
   d->controller_index=4; d->bounds=(rectangle2d){0,0,480,640};
   d->background_bitmap.index=d->text_label_string_list.index=d->extended_description_widget.index=NONE;
   d->text_font.index=0x99990001; d->list_header_bitmap.index=d->list_footer_bitmap.index=NONE;
   item_tags[i]=(struct cache_file_tag_instance){'DeLa',{NONE,NONE},item_id(i),(char *)item_names[i],d,{0,0}};
 }
 for(unsigned i=0;i<5;i++) item_tags[ITEM_WIDGET_COUNT+i]=(struct cache_file_tag_instance){'ustr',{NONE,NONE},item_id(ITEM_WIDGET_COUNT+i),(char *)item_names[ITEM_WIDGET_COUNT+i],&authored.lists[i],{0,0}};
 authored.screen[0].widget_tag=authored.screen[2].widget_tag=item_ref(ITEM_OTHER);
 authored.screen[1].widget_tag=item_ref(ITEM_MENU);
 authored.defs[ITEM_SCREEN].child_widgets=(struct tag_block){3,authored.screen,NULL};
 authored.defs[ITEM_MENU].type=3; authored.defs[ITEM_MENU].flags=9;
 authored.defs[ITEM_MENU].child_widgets=(struct tag_block){4,authored.menu,NULL};
 authored.defs[ITEM_MENU].extended_description_widget=item_ref(ITEM_HELP);
 authored.defs[ITEM_MENU].event_handlers=(struct tag_block){3,authored.events,NULL};
 authored.input.function=17; authored.defs[ITEM_MENU].game_data_inputs=(struct tag_block){1,&authored.input,NULL};
 for(unsigned i=0;i<3;i++) authored.events[i]=(struct ui_widget_event_handler_reference){.flags=i ? 0x280:0x80,.event_type=i==0 ? 24:i==1 ? 0:12,.function=i ? 52:62};
 for(unsigned i=0;i<4;i++) {
   unsigned row=i==3 ? ITEM_ROW:ITEM_ROW0+i,spinner=i==3 ? ITEM_SPINNER:ITEM_SPINNER0+i;
   authored.menu[i].widget_tag=item_ref(row); authored.menu[i].vertical_offset=73+30*i; authored.menu[i].horizontal_offset=54;
   authored.rows[i][0].widget_tag=item_ref(ITEM_LABEL); authored.rows[i][1].widget_tag=item_ref(spinner);
   authored.rows[i][1].horizontal_offset=366; authored.rows[i][1].vertical_offset=1;
   authored.defs[row].child_widgets=(struct tag_block){2,authored.rows[i],NULL};
   authored.defs[spinner].type=2; authored.defs[spinner].flags=0x41; authored.defs[spinner].list_flags=2;
   authored.defs[spinner].bounds=(rectangle2d){2,0,22,106};
   authored.defs[spinner].list_footer_bounds=(rectangle2d){7,108,19,114};
   authored.defs[spinner].text_label_string_list=item_ref(i==3 ? ITEM_VALUES:ITEM_STRINGS0+i);
 }
 authored.defs[ITEM_HELP].type=1; authored.defs[ITEM_HELP].bounds=(rectangle2d){321,68,400,550};
 authored.defs[ITEM_HELP].text_label_string_list=item_ref(ITEM_DESCRIPTIONS);
 memcpy(authored.custom,L"CUSTOM",sizeof(authored.custom)); memcpy(authored.generic,L"GENERIC",sizeof(authored.generic));
 authored.values[0].string.address=authored.custom; authored.values[0].string.size=sizeof(authored.custom);
 authored.values[1].string.address=authored.generic; authored.values[1].string.size=sizeof(authored.generic);
 authored.lists[0].strings=(struct tag_block){2,authored.values,NULL};
 for(unsigned i=0;i<19;i++) {
   swprintf(authored.help[i],20,L"Original help %u",i);
   authored.descriptions[i].string.address=authored.help[i]; authored.descriptions[i].string.size=20*sizeof(wchar_t);
 }
 authored.lists[1].strings=(struct tag_block){19,authored.descriptions,NULL};
 authored.lists[2].strings=(struct tag_block){2,authored.other_values[0],NULL};
 authored.lists[3].strings=(struct tag_block){5,authored.other_values[1],NULL};
 authored.lists[4].strings=(struct tag_block){10,authored.other_values[2],NULL};
 cache_file_globals.tags_loaded=TRUE; cache_file_globals.tag_header=&item_header; global_tag_instances=item_tags;
 original=authored;
}
static struct widget_instance *item_widget(long tag,struct widget_instance *parent) {
 struct ui_widget_definition *d=ui_widget_definition_get(tag);
 struct widget_instance *w=calloc(1,sizeof(*w)),*last=NULL;
 w->definition_tag_index=tag; w->type=d->type; w->parent=parent;
 for(long i=0;i<d->child_widgets.count;i++) {
   struct ui_widget_child_reference *reference=(struct ui_widget_child_reference *)d->child_widgets.address+i;
   struct widget_instance *child=item_widget(reference->widget_tag.index,w);
   if(last) last->next=child; else w->child=child; child->previous=last; last=child;
 }
 w->focused_child=w->child;
 if(w->type==2 && d->text_label_string_list.index!=NONE)
   w->parameters.list.number_of_items=unicode_string_list_definition_get(d->text_label_string_list.index)->strings.count;
 if(d->extended_description_widget.index!=NONE) w->parameters.list.extended_description=item_widget(d->extended_description_widget.index,NULL);
 return w;
}
static void free_item(struct widget_instance *w) {
 struct widget_instance *child=w->child;
 while(child) {struct widget_instance *next=child->next;free_item(child);child=next;}
 if(w->type==3 && w->parameters.list.extended_description) free_item(w->parameters.list.extended_description);
 free(w);
}
static void clone_and_help(void) {
 mutation_calls=help_calls=0;
 setup_items(); long mapped=fiesta_item_options_remap_tag(item_id(ITEM_SCREEN));
 assert(mapped!=item_id(ITEM_SCREEN) && register_calls==10);
 assert(fiesta_item_options_remap_tag(item_id(ITEM_SCREEN))==mapped && register_calls==10);
 assert(fiesta_item_options_remap_tag(item_id(ITEM_MENU))==item_id(ITEM_MENU));
 assert(!memcmp(&authored,&original,sizeof(authored)));
 assert(fiesta_item_options.screen.child_widgets.count==3 && fiesta_item_options.menu.child_widgets.count==4);
 assert(fiesta_item_options.menu.event_handlers.address==authored.events);
 assert(fiesta_item_options.menu.game_data_inputs.address==&authored.input);
 assert(!memcmp(fiesta_item_options.menu_children,authored.menu,2*sizeof(authored.menu[0])));
 assert(fiesta_item_options.row_children[0].widget_tag.index==item_id(ITEM_LABEL));
 assert(fiesta_item_options.weapon_row_children[0].widget_tag.index==item_id(ITEM_LABEL));
 assert(!memcmp(&fiesta_item_options.spinner.bounds,&authored.defs[ITEM_SPINNER].bounds,sizeof(rectangle2d)));
 assert(fiesta_item_options.spinner.text_font.index==authored.defs[ITEM_SPINNER].text_font.index);
 assert(fiesta_item_options.values.strings.count==3 && fiesta_item_options.weapon_values.strings.count==12 && fiesta_item_options.descriptions.strings.count==22);
 assert(!memcmp(fiesta_item_options.value_entries,authored.values,sizeof(authored.values)));
 assert(!memcmp(fiesta_item_options.weapon_value_entries,authored.other_values[2],sizeof(authored.other_values[2])));
 assert(!memcmp(fiesta_item_options.description_entries,authored.descriptions,17*sizeof(authored.descriptions[0])));
 assert(!memcmp(&fiesta_item_options.description_entries[19],&authored.descriptions[17],2*sizeof(authored.descriptions[0])));
 assert(!wcscmp(fiesta_item_options.value_entries[2].string.address,L"FIESTA"));
 assert(fiesta_item_options.value_entries[2].string.size==7*sizeof(wchar_t));
 assert(!wcscmp(fiesta_item_options.weapon_value_entries[10].string.address,L"UNCUT"));
 assert(!wcscmp(fiesta_item_options.weapon_value_entries[11].string.address,L"ALL"));
 assert(!wcscmp(fiesta_item_options.description_entries[17].string.address,L"Fiesta uses all restored pre-release weapons,\r\neven those absent from the original map."));
 assert(!wcscmp(fiesta_item_options.description_entries[18].string.address,L"Pfiesta uses the full playable weapon arsenal.\r\nIncludes restored and community weapons."));
 assert(!wcscmp(fiesta_item_options.description_entries[21].string.address,L"Respawn with two random weapons from this set.\r\nA new pair is chosen each time you spawn."));
 struct widget_instance *menu=item_widget(tag_loaded('DeLa',"ui\\native_fiesta\\item_options_menu"),NULL),*row=menu->child;
 for(unsigned i=0;i<2;i++) row=row->next;
 menu->focused_child=row;
 for(short selection=0;selection<12;selection++) {
   row->child->next->parameters.list.selected_index=selection; game_options_menu_update_text_desc(menu);
   fiesta_item_options_update_name(menu);
   assert(!wcscmp(fiesta_item_options.value_entries[2].string.address,selection==11 ? L"PFIESTA":L"FIESTA"));
   assert(fiesta_item_options.value_entries[2].string.size==(selection==11 ? 8:7)*sizeof(wchar_t));
   assert(menu->parameters.list.extended_description->parameters.text_box.string_list_index==7+selection);
 }
 row->child->next->parameters.list.selected_index=10; fiesta_item_options_update_name(menu);
 assert(!wcscmp(fiesta_item_options.value_entries[2].string.address,L"FIESTA"));
 assert(!memcmp(&authored,&original,sizeof(authored)));
 row=row->next;
 menu->focused_child=row;
 for(short selection=0;selection<3;selection++) {
   row->child->next->parameters.list.selected_index=selection; game_options_menu_update_text_desc(menu);
   assert(menu->parameters.list.extended_description->parameters.text_box.string_list_index==19+selection);
 }
 free_item(menu);
 long old=mapped; scenario_tags_unload(); cache_file_globals.tags_loaded=TRUE; global_tag_instances=item_tags;
 assert(fiesta_item_options_remap_tag(item_id(ITEM_SCREEN))!=old && !tag_index_is_group(old,'DeLa'));
 for(unsigned fail=1;fail<=10;fail++) {
   setup_items(); fail_registration=fail;
   assert(fiesta_item_options_remap_tag(item_id(ITEM_SCREEN))==item_id(ITEM_SCREEN));
   assert(!memcmp(&authored,&original,sizeof(authored)));
   fail_registration=0; assert(fiesta_item_options_remap_tag(item_id(ITEM_SCREEN))!=item_id(ITEM_SCREEN));
 }
 setup_items(); authored.lists[0].strings.count=1;
 assert(fiesta_item_options_remap_tag(item_id(ITEM_SCREEN))==item_id(ITEM_SCREEN) && !register_calls);
 setup_items(); authored.lists[4].strings.count=11;
 assert(fiesta_item_options_remap_tag(item_id(ITEM_SCREEN))==item_id(ITEM_SCREEN) && !register_calls);
 /* Cloning tags and selecting help text must not apply playlist edits/events. */
 assert(mutation_calls==0 && help_calls==0);
}
int main(void) {clone_and_help();puts("Fiesta item clone tests passed");return 0;}
'''

CALLBACK_PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t byte,boolean;
typedef uint16_t word;
typedef float real;
#define TRUE 1
#define FALSE 0
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define match_vassert(file,line,condition,message) assert(condition)
static unsigned errors;
#define error(...) (++errors)
enum { game_engine_ctf=1,game_engine_slayer,game_engine_oddball,game_engine_king,game_engine_race };
/* VARIANTS */
#define __GAME_ENGINE_H
#include "game/starting_equipment.h"
#include "game/weapon_sets.h"
/* CALLBACK TYPES */
static struct game_variant edited;
static boolean editing=TRUE;
static void *player_ui_get_edit_playlist_profile(void) {return editing ? &edited:NULL;}
/* CALLBACKS */
static struct widget_instance menu,rows[4],spinners[4];
static void setup_callbacks(unsigned flags,short mode) {
 memset(&edited,0,sizeof(edited)); memset(&menu,0,sizeof(menu)); memset(rows,0,sizeof(rows));memset(spinners,0,sizeof(spinners));
 performance_variant_set_flags(&edited,flags); assert(starting_equipment_set(&edited,mode));
 edited.universal_variant.flags|=0x4004;edited.universal_variant.vehicle_set=3;edited.universal_variant.weapon_set=7;
 menu.type=3;menu.child=rows;errors=0;editing=TRUE;
 for(unsigned i=0;i<4;i++) {rows[i].child=&spinners[i];rows[i].next=i<3 ? &rows[i+1]:NULL;spinners[i].type=2;spinners[i].generated_count=i==3 ? 3:i==2 ? 12:11;}
}
int main(void) {
 assert(sizeof(struct game_variant)==104);
 for(unsigned flags=0;flags<=255;flags++) for(short initial=0;initial<3;initial++) {
   setup_callbacks(flags,initial);
   assert(playlist_profile_initialize_item_options(&menu,NULL,NULL));
   assert(spinners[0].data3C.selected_index==0 && spinners[1].data3C.selected_index==3 && spinners[2].data3C.selected_index==7);
   assert(spinners[3].data3C.selected_index==initial);
   struct game_variant before=edited;
   spinners[3].data3C.selected_index=(initial+1)%3;
   assert(!memcmp(&before,&edited,sizeof(edited))); /* Cancel never invokes Accept. */
   for(short selected=0;selected<3;selected++) {
     spinners[3].data3C.selected_index=selected;
     assert(playlist_profile_change_item_options(&menu,NULL,NULL));
     assert(starting_equipment_get(&edited)==selected && !errors);
     assert((performance_variant_get_flags(&edited)&127)==(flags&127));
     assert(edited.universal_variant.vehicle_set==3 && edited.universal_variant.weapon_set==7);
     assert((edited.universal_variant.flags&~0x20u)==0x4004u);
   }
 }
 /* UI order omits hidden Xbox No Grenades ID 10. Signed saves and network
  * variants retain the original 104-byte layout and appended IDs 11/12. */
 for(short mode=0;mode<3;mode++) for(short selection=0;selection<12;selection++) {
   setup_callbacks(7,mode);
   edited.universal_variant.weapon_set=selection<10 ? selection:selection==10 ? GAME_WEAPON_SET_UNCUT:GAME_WEAPON_SET_ALL;
   struct game_variant before=edited;
   assert(playlist_profile_initialize_item_options(&menu,NULL,NULL));
   assert(spinners[2].data3C.selected_index==selection && !memcmp(&before,&edited,sizeof(edited)));
   assert(playlist_profile_change_item_options(&menu,NULL,NULL) && !errors);
   assert(!memcmp(&before,&edited,sizeof(edited)));
   spinners[2].data3C.selected_index=(selection+1)%12;
   assert(playlist_profile_change_item_options(&menu,NULL,NULL) && !errors);
   short next=(selection+1)%12;
   assert(edited.universal_variant.weapon_set==(next<10 ? next:next==10 ? GAME_WEAPON_SET_UNCUT:GAME_WEAPON_SET_ALL));
   assert(starting_equipment_get(&edited)==mode && edited.universal_variant.vehicle_set==3);
 }
 setup_callbacks(7,2);edited.universal_variant.weapon_set=10;
 struct game_variant hidden_before=edited;
 assert(playlist_profile_initialize_item_options(&menu,NULL,NULL) && spinners[2].data3C.selected_index==0);
 assert(!memcmp(&hidden_before,&edited,sizeof(edited)));
 for(short saved=GAME_WEAPON_SET_UNCUT;saved<=GAME_WEAPON_SET_ALL;saved++) {
   setup_callbacks(7,2);edited.universal_variant.weapon_set=saved;spinners[2].generated_count=10;
   struct game_variant saved_before=edited;
   assert(playlist_profile_initialize_item_options(&menu,NULL,NULL) && spinners[2].data3C.selected_index==0);
   assert(!memcmp(&saved_before,&edited,sizeof(edited)));
 }
 setup_callbacks(128|64|7,2);assert(playlist_profile_initialize_item_options(&menu,NULL,NULL));
 struct game_variant before=edited;spinners[3].data3C.selected_index=3;
 assert(playlist_profile_change_item_options(&menu,NULL,NULL) && errors==1 && !memcmp(&before,&edited,sizeof(edited)));
 spinners[3].generated_count=2;
 assert(playlist_profile_initialize_item_options(&menu,NULL,NULL) && spinners[3].data3C.selected_index==1);
 editing=FALSE;assert(!playlist_profile_initialize_item_options(&menu,NULL,NULL));
 assert(!playlist_profile_change_item_options(&menu,NULL,NULL));
 puts("Fiesta editor callback tests passed");return 0;
}
'''


class FiestaUiTests(unittest.TestCase):
    def run_fixture(self, source, expected, *, short_wchar=False):
        with tempfile.TemporaryDirectory(prefix="halo-fiesta-ui-") as temporary:
            folder = Path(temporary)
            (folder / "fixture.c").write_text(source)
            command = ["clang", "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-multichar",
                       "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unused-parameter", "-Wno-format"]
            if short_wchar:
                command += ["-fshort-wchar"]
            command += ["-I", str(ROOT / "source"), str(folder / "fixture.c"), "-o", str(folder / "fixture")]
            subprocess.run(command, check=True)
            result = subprocess.run([str(folder / "fixture")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), expected)

    def test_cache_clones_help_and_reload(self):
        source = fixture_source().split('#define EDIT_PREFIX "ui', 1)[0] + CLONE_HARNESS
        self.run_fixture(source, "Fiesta item clone tests passed")

    def test_production_editor_callbacks(self):
        engine = (ROOT / "source/game/game_engine.h").read_text()
        handlers = (ROOT / "source/interface/ui_widget_event_handler_functions.c").read_text()
        variants = "\n".join(c_block(engine, signature) + ";" for signature in (
            "struct universal_variant\n", "struct ctf_variant\n", "struct slayer_variant\n",
            "struct king_variant\n", "struct oddball_variant\n", "struct race_variant\n",
            "union game_engine_variant\n", "struct game_variant\n"))
        private_handlers = handlers[handlers.index("/* ---------- private code */"):]
        callbacks = "\n".join(c_block(private_handlers, signature) for signature in (
            "static boolean playlist_profile_initialize_item_options(\n",
            "static boolean playlist_profile_change_item_options(\n"))
        types = "\n".join(c_block(handlers, signature) + ";" for signature in (
            "struct widget_instance\n", "struct event_record\n", "struct playlist_profile_item_options_prefix\n"))
        source = CALLBACK_PREFIX.replace("/* VARIANTS */", variants).replace("/* CALLBACK TYPES */", types).replace("/* CALLBACKS */", callbacks)
        source = re.sub(r"\bunsigned long\b", "uint32_t", source)
        source = re.sub(r"\blong\b", "int32_t", source)
        self.run_fixture(source, "Fiesta editor callback tests passed", short_wchar=True)

    def test_owned_font_metrics(self):
        from tools.verify_performance_sound_samples import Cache
        paths = [ROOT / f"assets/maps/{name}.map" for name in ("ui", "bloodgulch")]
        paths = [path for path in paths if path.exists()]
        if not paths:
            self.skipTest("owned Xbox cache assets required for font metrics")
        source = (ROOT / "source/interface/fiesta_item_options_menu.inc").read_text()
        self.assertIn('L"FIESTA"', source)
        for path in paths:
            cache = Cache(path)
            for name, texts, limit in (
                (r"ui\large_ui", ("FIESTA", "PFIESTA", "UNCUT", "ALL"), 106),
                (r"ui\large_ui", ("Respawn with two random weapons from this set.", "A new pair is chosen each time you spawn.",
                                     "Fiesta uses all restored pre-release weapons,", "even those absent from the original map.",
                                     "Pfiesta uses the full playable weapon arsenal.", "Includes restored and community weapons."), 482),
                (r"ui\small_ui", ("Starting Equipment: Fiesta", "Fiesta / Hardcore: On"), 183),
                (r"ui\small_ui", ("Equipment: Pfiesta", "Pfiesta/Hardcore: On"), 144),
            ):
                font = cache.by_path[name]
                _, _, _, inset = cache.unpack("<4h", font["address"] + 4)
                count, address, _ = cache.unpack("<3I", font["address"] + 0x7C)
                glyphs = {chr(code): (advance, width, origin_x) for index in range(count)
                          for code, advance, width, _, origin_x in [cache.unpack("<H4h", address + index * 0x14)]}
                for value in texts:
                    cursor = ink_right = inset
                    for character in value:
                        advance, width, origin_x = glyphs[character]
                        ink_right = max(ink_right, cursor - origin_x + width)
                        cursor += advance
                    self.assertLessEqual(max(cursor, ink_right), limit, f"{path.stem}: {value!r} clips")


if __name__ == "__main__":
    unittest.main()
