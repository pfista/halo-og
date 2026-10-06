"""Exercise cloned Xbox Rules menus with real variant helpers and rule callbacks."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.test_performance_ui import fixture_source
from tools.test_runtime_ui_tags import c_block

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
struct event_record { short controller_index; };
static void error(int level,const char *message,...) { (void)level;(void)message;assert(0); }
static unsigned pops;
static void ui_widgets_pop_stack(short controller) { (void)controller; pops++; }
static boolean ui_widget_event_handler_function_invoke(struct widget_instance *,struct event_record *,word,boolean *);
static void widget_instance_set_visibility_recursive(struct widget_instance *w,boolean visible) {
 w->visible=visible; for(struct widget_instance *c=w->child;c;c=c->next) widget_instance_set_visibility_recursive(c,visible);
}
#include "interface/teammate_view_menu.inc"
#define TEST_FLAG(value,bit) (((value)&(1u<<(bit)))!=0)
enum { _widget_pass_unhandled_events_to_children_bit=0 };
/* NAVIGATION */
/* CALLBACKS */
static boolean ui_widget_event_handler_function_invoke(struct widget_instance *w,struct event_record *e,word function,boolean *deleted) {
 switch(function) {
 case 52:return playlist_profile_initialize_ctf_rules(w,e,deleted);
 case 53:return playlist_profile_initialize_koth_rules(w,e,deleted);
 case 54:return playlist_profile_initialize_slayer_rules(w,e,deleted);
 case 55:return playlist_profile_initialize_oddball_rules(w,e,deleted);
 case 56:return playlist_profile_initialize_racing_rules(w,e,deleted);
 case 42:return playlist_profile_change_ctf_rules(w,e,deleted);
 case 43:return playlist_profile_change_koth_rules(w,e,deleted);
 case 44:return playlist_profile_change_slayer_rules(w,e,deleted);
 case 45:return playlist_profile_change_oddball_rules(w,e,deleted);
 case 46:return playlist_profile_change_racing_rules(w,e,deleted);
 default:assert(0);return FALSE;
 }
}
enum { SCREEN,MENU,ROW,LABEL,SPINNER,HELP,OTHER,ROW_BASE,SPINNER_BASE=ROW_BASE+8,
 WIDGET_COUNT=SPINNER_BASE+8,DESCRIPTIONS=WIDGET_COUNT,VALUES,ORIGINAL_VALUES,TAG_COUNT=ORIGINAL_VALUES+8 };
static char names[TAG_COUNT][256];
static struct cache_file_tag_instance tags[TAG_COUNT];
static struct cache_file_tag_header header={TAG_COUNT,0x71717171};
static struct {
 struct ui_widget_definition defs[WIDGET_COUNT];
 struct ui_widget_child_reference screen[3],menu[8],row[2],rules[8][2];
 struct ui_widget_event_handler_reference events[3];
 struct ui_widget_game_data_input_reference input;
 struct string_list descriptions,values,original_values[8];
 struct string_list_entry descriptions_entries[64],value_entries[16];
 wchar_t help[64][8];
} authored,original;
static short const option_counts[5][8]={{2,6,2,2,5},{2,5,2},{2,2,2,5,2},{4,4,3,3,2,16,5,2},{3,3,6,2}};
static long id(unsigned i) { return 0x34560000|i; }
static struct tag_reference ref(unsigned i) { return pb_editor_reference(i<WIDGET_COUNT ? 'DeLa':'ustr',id(i)); }
static void setup(short mode) {
 if(cache_file_globals.tags_loaded) scenario_tags_unload();
 memset(&authored,0,sizeof(authored));memset(tags,0,sizeof(tags));memset(names,0,sizeof(names));
 register_calls=fail_registration=pops=0; editing=TRUE;
 for(unsigned i=0;i<TAG_COUNT;i++) {
  snprintf(names[i],sizeof(names[i]),"fixture\\%u",i);
  tags[i]=(struct cache_file_tag_instance){i<WIDGET_COUNT ? 'DeLa':'ustr',{NONE,NONE},id(i),names[i],NULL,{0,0}};
  if(i<WIDGET_COUNT) {
   struct ui_widget_definition *d=&authored.defs[i];tags[i].base_address=d;
   d->controller_index=4;d->bounds=(rectangle2d){0,0,480,640};
   d->background_bitmap.index=d->text_label_string_list.index=d->extended_description_widget.index=NONE;
   d->text_font.index=0x99990001;d->list_header_bitmap.index=d->list_footer_bitmap.index=NONE;
  }
 }
 const char *prefix="ui\\shell\\main_menu\\settings_select\\multiplayer_setup\\playlist_edit\\";
 snprintf(names[SCREEN],sizeof(names[SCREEN]),"%s%s_edit\\%s_options_screen",prefix,team_view_rule_names[mode],team_view_rule_names[mode]);
 snprintf(names[MENU],sizeof(names[MENU]),"%s%s_edit\\%s_options_menu",prefix,team_view_rule_names[mode],team_view_rule_names[mode]);
 snprintf(names[ROW],sizeof(names[ROW]),"%sslayer_edit\\op_team_play",prefix);
 snprintf(names[LABEL],sizeof(names[LABEL]),"%sslayer_edit\\team_play_label",prefix);
 snprintf(names[SPINNER],sizeof(names[SPINNER]),"%sslayer_edit\\team_play_spinner",prefix);
 authored.screen[0].widget_tag=authored.screen[2].widget_tag=ref(OTHER);authored.screen[1].widget_tag=ref(MENU);
 authored.defs[SCREEN].child_widgets=(struct tag_block){3,authored.screen,NULL};
 authored.defs[MENU].type=3;authored.defs[MENU].flags=9;
 authored.defs[MENU].child_widgets=(struct tag_block){team_view_rule_rows[mode],authored.menu,NULL};
 authored.defs[MENU].event_handlers=(struct tag_block){3,authored.events,NULL};
 authored.defs[MENU].extended_description_widget=ref(HELP);
 authored.input.function=17;authored.defs[MENU].game_data_inputs=(struct tag_block){1,&authored.input,NULL};
 for(unsigned i=0;i<3;i++) authored.events[i]=(struct ui_widget_event_handler_reference){.flags=i ? 0x280:0x80,.event_type=i==0 ? 24:i==1 ? 0:12,.function=(i ? 42:52)+mode};
 authored.row[0].widget_tag=ref(LABEL);authored.row[1].widget_tag=ref(SPINNER);
 authored.row[1].horizontal_offset=366;authored.row[1].vertical_offset=1;
 authored.defs[ROW].child_widgets=(struct tag_block){2,authored.row,NULL};
 authored.defs[LABEL].type=1;authored.defs[LABEL].bounds=(rectangle2d){0,0,22,320};
 authored.defs[SPINNER].type=2;authored.defs[SPINNER].flags=0x41;authored.defs[SPINNER].list_flags=2;
 authored.defs[SPINNER].text_label_string_list=ref(VALUES);
 tags[VALUES].base_address=&authored.values;authored.values.strings=(struct tag_block){2,authored.value_entries,NULL};
 long help_count=0;
 for(short i=0;i<team_view_rule_rows[mode];i++) {
  authored.menu[i].widget_tag=ref(ROW_BASE+i);authored.menu[i].vertical_offset=73+30*i;authored.menu[i].horizontal_offset=54;
  authored.rules[i][0].widget_tag=ref(LABEL);authored.rules[i][1].widget_tag=ref(SPINNER_BASE+i);
  authored.defs[ROW_BASE+i].child_widgets=(struct tag_block){2,authored.rules[i],NULL};
  authored.defs[SPINNER_BASE+i]=authored.defs[SPINNER];authored.defs[SPINNER_BASE+i].text_label_string_list=ref(ORIGINAL_VALUES+i);
  authored.original_values[i].strings=(struct tag_block){option_counts[mode][i],authored.value_entries,NULL};
  tags[ORIGINAL_VALUES+i].base_address=&authored.original_values[i];help_count+=option_counts[mode][i];
 }
 for(short i=0;i<help_count;i++) {authored.help[i][0]='A'+i%26;authored.descriptions_entries[i].string.address=authored.help[i];authored.descriptions_entries[i].string.size=sizeof(authored.help[i]);}
 authored.descriptions.strings=(struct tag_block){help_count,authored.descriptions_entries,NULL};tags[DESCRIPTIONS].base_address=&authored.descriptions;
 authored.defs[HELP].type=1;authored.defs[HELP].text_label_string_list=ref(DESCRIPTIONS);
 cache_file_globals.tags_loaded=TRUE;cache_file_globals.tag_header=&header;global_tag_instances=tags;original=authored;
 memset(&edited,0,sizeof(edited));edited.game_engine_index=mode==0 ? 1:mode==1 ? 4:mode==2 ? 2:mode==3 ? 3:5;
 edited.universal_variant.teams=TRUE;edited.universal_variant.flags=0x2D;edited.universal_variant.health=1;
 edited.universal_variant.score_to_win=5;
}
static struct widget_instance *make_widget(long tag,struct widget_instance *parent) {
 struct ui_widget_definition *d=ui_widget_definition_get(tag);struct widget_instance *w=calloc(1,sizeof(*w)),*last=NULL;
 w->definition_tag_index=tag;w->type=d->type;w->parent=parent;w->visible=TRUE;
 for(long i=0;i<d->child_widgets.count;i++) {
  struct ui_widget_child_reference *r=(struct ui_widget_child_reference *)d->child_widgets.address+i;
  struct widget_instance *c=make_widget(r->widget_tag.index,w);c->previous=last;
  if(last) last->next=c;else w->child=c;last=c;
 }
 w->focused_child=w->child;
 if(w->type==2 && d->text_label_string_list.index!=NONE) w->parameters.list.number_of_items=unicode_string_list_definition_get(d->text_label_string_list.index)->strings.count;
 if(d->extended_description_widget.index!=NONE) w->parameters.list.extended_description=make_widget(d->extended_description_widget.index,NULL);
 return w;
}
static void free_widget(struct widget_instance *w) {
 for(struct widget_instance *c=w->child;c;) {struct widget_instance *next=c->next;free_widget(c);c=next;}
 if(w->type==3 && w->parameters.list.extended_description) free_widget(w->parameters.list.extended_description);free(w);
}
static void exercise(short mode) {
 setup(mode);assert(sizeof(struct game_variant)==104);
 long mapped=teammate_view_menu_remap_tag(id(SCREEN));assert(mapped!=id(SCREEN));
 assert(memcmp(&authored,&original,sizeof(authored))==0);
 assert(team_view_menus[mode].menu.child_widgets.count==team_view_rule_rows[mode]+1);
 assert(team_view_menus[mode].spinner.text_font.index==authored.defs[SPINNER].text_font.index);
 struct widget_instance *root=make_widget(mapped,NULL),*menu=root->child->next;
 boolean deleted=FALSE;struct event_record event={0};
 struct game_variant before=edited;
 assert(teammate_view_menu_event(menu,&event,_team_view_menu_initialize,&deleted));
 assert(memcmp(&before,&edited,sizeof(edited))==0 && pops==0);
 struct widget_instance *spinner=widget_instance_find_by_tag_index_recursive(menu,team_view_menus[mode].spinner_tag),*row=spinner->parent;
 assert(spinner->parameters.list.selected_index==0 && row->visible);
 spinner->parameters.list.selected_index=1;menu->focused_child=row;
 game_options_menu_update_text_desc(menu);
 assert(menu->parameters.list.extended_description->parameters.text_box.string_list_index==team_view_menus[mode].descriptions.strings.count-1);
 assert(memcmp(&before,&edited,sizeof(edited))==0); /* Cancel discards the draft. */
 free_widget(root);root=make_widget(mapped,NULL);menu=root->child->next;
 assert(teammate_view_menu_event(menu,&event,_team_view_menu_initialize,&deleted));
 spinner=widget_instance_find_by_tag_index_recursive(menu,team_view_menus[mode].spinner_tag);assert(spinner->parameters.list.selected_index==0);
 spinner->parameters.list.selected_index=1;
 assert(teammate_view_menu_event(menu,&event,_team_view_menu_accept,&deleted));
 assert(pops==1 && teammate_view_variant_enabled(&edited) && (edited.universal_variant.flags&255)==0x2D);
 struct game_variant copied=edited;assert(teammate_view_variant_enabled(&copied));
 assert(teammate_view_menu_event(menu,&event,_team_view_menu_initialize,&deleted));
 assert(spinner->parameters.list.selected_index==1);
 if(mode!=0) {
  row=spinner->parent;struct widget_instance *teams=row->previous;
  teammate_view_rule_spinner(teams)->parameters.list.selected_index=1;menu->focused_child=row;
  teammate_view_menu_update(menu);assert(!row->visible && row->disabled && teammate_view_menu_hidden_row(row) && menu->focused_child==teams);
  widget_instance_tab_to_next_valid_widget(menu);assert(menu->focused_child==menu->child);
  widget_instance_tab_to_previous_valid_widget(menu);assert(menu->focused_child==teams);
  teammate_view_rule_spinner(teams)->parameters.list.selected_index=0;
  teammate_view_menu_update(menu);widget_instance_tab_to_next_valid_widget(menu);assert(menu->focused_child==row);
  teammate_view_rule_spinner(teams)->parameters.list.selected_index=1;teammate_view_menu_update(menu);
  assert(memcmp(&copied,&edited,sizeof(edited))==0);
  assert(teammate_view_menu_event(menu,&event,_team_view_menu_accept,&deleted));
  assert(!edited.universal_variant.teams && !teammate_view_variant_enabled(&edited) && (edited.universal_variant.flags&255)==0x2D);
 }
 free_widget(root);
 setup(mode);fail_registration=1;assert(teammate_view_menu_remap_tag(id(SCREEN))==id(SCREEN));
 assert(memcmp(&authored,&original,sizeof(authored))==0);
}
int main(void) { for(short i=0;i<5;i++) exercise(i);puts("teammate view menu tests passed");return 0; }
'''


def menu_fixture():
    source = fixture_source().split('#define EDIT_PREFIX "ui', 1)[0]
    engine = (ROOT / "source/game/game_engine.h").read_text()
    variants = "\n".join(c_block(engine, signature) + ";" for signature in (
        "struct universal_variant\n", "struct ctf_variant\n", "struct slayer_variant\n",
        "struct king_variant\n", "struct oddball_variant\n", "struct race_variant\n",
        "union game_engine_variant\n", "struct game_variant\n"))
    variants = re.sub(r"\bunsigned long\b", "uint32_t", variants)
    variants = re.sub(r"\blong\b", "int32_t", variants)
    variants = re.sub(r"\bboolean\b", "uint8_t", variants)
    variants = variants.replace("wchar_t human_readable_game_description", "uint16_t human_readable_game_description")
    source = source.replace("struct game_variant { unsigned flags; };", "#include <stdint.h>\n#define __GAME_ENGINE_H\n" + variants)
    handlers = (ROOT / "source/interface/ui_widget_event_handler_functions.c").read_text()
    handlers = handlers[handlers.index("/* ---------- private code */"):]
    callbacks = "\n".join(c_block(handlers, f"static boolean playlist_profile_{kind}_{mode}_rules(\n")
                          for mode in ("ctf", "koth", "slayer", "oddball", "racing")
                          for kind in ("initialize", "change"))
    callbacks = re.sub(r"\blong\b", "int32_t", callbacks).replace("->data3C.selected_index", "->parameters.list.selected_index")
    widgets = (ROOT / "source/interface/ui_widget.c").read_text()
    navigation = "\n".join(c_block(widgets, signature) for signature in (
        "static __inline struct widget_instance *widget_instance_get_tail_child_widget(\n\tstruct widget_instance *widget)\n{",
        "static void widget_instance_tab_to_next_valid_widget(\n\tstruct widget_instance *widget)\n{",
        "static void widget_instance_tab_to_previous_valid_widget(\n\tstruct widget_instance *widget)\n{"))
    return source + HARNESS.replace("/* CALLBACKS */", callbacks).replace("/* NAVIGATION */", navigation)


class TeammateViewMenuTests(unittest.TestCase):
    def test_real_rule_callbacks_staging_visibility_and_reload(self):
        with tempfile.TemporaryDirectory(prefix="halo-team-view-menu-") as temporary:
            folder = Path(temporary)
            (folder / "fixture.c").write_text(menu_fixture())
            subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-multichar",
                            "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unused-parameter", "-Wno-format",
                            "-I", str(ROOT / "source"), str(folder / "fixture.c"), "-o", str(folder / "fixture")], check=True)
            result = subprocess.run([str(folder / "fixture")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "teammate view menu tests passed")


if __name__ == "__main__":
    unittest.main()
