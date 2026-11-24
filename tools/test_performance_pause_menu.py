"""Exercise the production native pause definitions and staged host controls.

The fixture supplies map tags, widget allocation, and the authority setter. It
checks the actual runtime tag construction and option callbacks, including
split-screen isolation and map reloads; real rendering/input remain app checks.
"""
from pathlib import Path
import ast
import re
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte, boolean;
typedef unsigned short word;
typedef struct { short x,y; } point2d;
typedef struct { short y0,x0,y1,x1; } rectangle2d;
typedef struct { float alpha,red,green,blue; } real_argb_color;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MAXIMUM_NUMBER_OF_LOCAL_PLAYERS 4
#define FLAG(n) (1L << (n))
#define TEST_FLAG(value,n) (((value) & FLAG(n)) != 0)
#define csmemset memset
#define csmemcpy memcpy
#define csstrcmp strcmp
enum { _gamepad_analog_button_a=0, _gamepad_analog_button_b=1,
 _gamepad_binary_button_dpad_up=8, _gamepad_binary_button_dpad_down,
 _gamepad_binary_button_dpad_left, _gamepad_binary_button_dpad_right,
 _gamepad_binary_button_start, _gamepad_binary_button_back, NUMBER_OF_GAMEPAD_BUTTONS=16 };
enum { UNICODE_STRING_LIST_TAG='ustr' };
#define NUMBEROF(a) (sizeof(a)/sizeof((a)[0]))
/* PERFORMANCE DECLARATIONS */
struct tag_block { long count; void *address; void *definition; };
struct tag_reference { unsigned long group_tag; char *name; long name_length,index; };
struct tag_data { long size; unsigned long pad; long file_offset; void *address,*definition; };
struct string_list { struct tag_block strings; };
struct string_list_entry { struct tag_data string; };
struct widget_instance {
 long definition_tag_index; short local_player_index,type; boolean disabled;
 struct widget_instance *parent,*child,*next,*focused_child;
 union { struct { short selected_index; unsigned number_of_items; } list;
 struct { short string_list_index; } text_box; } parameters;
};
struct event_record { int unused; };
static size_t ustrlen(const wchar_t *s) { size_t n=0; while(s[n]) ++n; return n; }
/* EXTRACTED NATIVE DEFINITIONS */
'''

STUBS = r'''
static struct ui_widget_definition originals[6], legend, row_styles[3], list_buttons[2][2];
static boolean locked;
static void *game_engine_get_variant(void) { return &locked; }
static boolean playlist_profile_variant_is_locked(void *variant) { assert(variant==&locked); return locked; }
/* The production kit supplies every size; only the map's tags are stubs. */
struct tag_iterator { int unused; };
static long tag_loaded(long group,const char *name);
static void *tag_get(long group,long index);
#define ui_widget_definition_get(i) ((struct ui_widget_definition *)tag_get(UI_WIDGET_DEFINITION_TAG,(i)))
static long cache_files_register_runtime_ui_tag(long group,const char *name,void *definition);
static boolean tag_index_is_group(long tag,long group) { return group=='bitm' && tag>=8 && tag<=12; }
static void tag_iterator_new(struct tag_iterator *iterator,long group) { (void)iterator; (void)group; }
static long tag_iterator_next(struct tag_iterator *iterator) { (void)iterator; return NONE; }
static const char *tag_get_name(long tag) { (void)tag; return NULL; }
/* PRODUCTION PAUSE KIT */
static boolean native_multiplayer_pause_build(void) { return TRUE; }
static struct ui_widget_definition const *native_multiplayer_pause_button_style(short style) { return &row_styles[style]; }
static struct ui_widget_definition const *native_multiplayer_pause_root(short layout) { return &originals[layout]; }
static long native_multiplayer_pause_resume_tag(short style) { return style==_native_pause_wide ? 5 : 15; }
static long native_multiplayer_pause_leave_tag(short style) { return style==_native_pause_wide ? 6 : 16; }
static struct ui_widget_child_reference root_children[3][3], list_children[2];
static const char *original_names[6]={
 "ui\\shell\\multiplayer_game\\pause_game\\1p_pause_game",
 "ui\\shell\\multiplayer_game\\pause_game\\2p_pause_game",
 "ui\\shell\\multiplayer_game\\pause_game\\4p_pause_game",
 "ui\\shell\\multiplayer_game\\pause_game\\mp_pause_list", "resume", "quit"};
static struct { long group,id; const char *name; void *definition; } registry[96];
static unsigned registry_count,generation,set_calls,host_flags;
static boolean host=TRUE,refuse;
static long tag_loaded(long group,const char *name) {
 static const char *const bitmaps[]={"ui\\shell\\bitmaps\\menu_bkds","","ui\\shell\\bitmaps\\pausebox2_left",
  "ui\\shell\\bitmaps\\pausebox2_center","ui\\shell\\bitmaps\\pausebox2_right"};
 if(group==FONT_GROUP_TAG) return !strcmp(name,"ui\\small_ui") ? 7 : !strcmp(name,"ui\\large_ui") ? 9 : NONE;
 if(group=='bitm') { for(unsigned i=0;i<5;i++) if(!strcmp(name,bitmaps[i])) return 8+i; return NONE; }
 if(group==UI_WIDGET_DEFINITION_TAG && !strcmp(name,"ui\\shell\\main_menu\\button_key_sm")) return 9002;
 for(unsigned i=0;i<6;i++) if(group==UI_WIDGET_DEFINITION_TAG && !strcmp(name,original_names[i])) return i+1;
 for(unsigned i=0;i<registry_count;i++) if(group==registry[i].group && !strcmp(name,registry[i].name)) return registry[i].id;
 return NONE;
}
static void *tag_get(long group,long index) {
 (void)group;
 if(index==9002) return &legend;
 if(index==5 || index==6) return &list_buttons[0][index-5];
 if(index==15 || index==16) return &list_buttons[1][index-15];
 if(index>=1 && index<=4) return &originals[index-1];
 for(unsigned i=0;i<registry_count;i++) if(index==registry[i].id) return registry[i].definition;
 assert(!"invalid tag"); return NULL;
}
static long cache_files_register_runtime_ui_tag(long group,const char *name,void *definition) {
 for(unsigned i=0;i<registry_count;i++) if(!strcmp(name,registry[i].name)) {
   assert(group==registry[i].group && definition==registry[i].definition); return registry[i].id;
 }
 assert(registry_count<96); unsigned i=registry_count++;
 registry[i].group=group; registry[i].name=name; registry[i].definition=definition;
 return registry[i].id=100+generation*100+i;
}
static void *global_network_game_server_get(void) { return host ? &host : NULL; }
static unsigned long performance_options_get_flags(void) { return host_flags; }
static boolean performance_options_set_host_flags(unsigned long flags) {
 assert(host); ++set_calls; if(refuse) return FALSE; host_flags=flags; return TRUE;
}
static struct widget_instance *widget_instance_find_by_tag_index_recursive(struct widget_instance *w,long tag) {
 if(w->definition_tag_index==tag) return w;
 for(struct widget_instance *c=w->child;c;c=c->next) {
   struct widget_instance *result=widget_instance_find_by_tag_index_recursive(c,tag);
   if(result) return result;
 }
 return NULL;
}
static boolean widget_event_function_list_widget_goto_next_item(struct widget_instance *w,struct event_record *e,boolean *d) {
 (void)e; (void)d; w->parameters.list.selected_index=(w->parameters.list.selected_index+1)%w->parameters.list.number_of_items; return TRUE;
}
/* PRODUCTION NATIVE MENU */
'''

HARNESS = r'''
static long game_settings_pause_tag(short layout) { return 900 + layout; }
static struct widget_instance *make_widget(long tag,struct widget_instance *parent,short local) {
 struct widget_instance *w=calloc(1,sizeof(*w)); assert(w);
 struct ui_widget_definition *def=ui_widget_definition_get(tag);
 w->parent=parent; w->local_player_index=local; w->definition_tag_index=tag; w->type=def->type;
 if(def->type==_ui_widget_type_spinner_list)
   w->parameters.list.number_of_items=((struct string_list *)tag_get(UNICODE_STRING_LIST_TAG,def->text_label_string_list.index))->strings.count;
 struct widget_instance **tail=&w->child;
 for(long i=0;i<def->child_widgets.count;i++) {
   struct ui_widget_child_reference *c=(struct ui_widget_child_reference *)def->child_widgets.address+i;
   *tail=make_widget(c->widget_tag.index,w,local); tail=&(*tail)->next;
 }
 w->focused_child=w->child;
 if(w->child && TEST_FLAG(ui_widget_definition_get(w->child->definition_tag_index)->flags,_widget_native_pause_frame_bit))
   w->focused_child=w->child->next;
 return w;
}
static void free_widget(struct widget_instance *w) {
 struct widget_instance *next;
 for(struct widget_instance *c=w->child;c;c=next) { next=c->next; free_widget(c); }
 free(w);
}
static struct widget_instance *control(struct widget_instance *root,int i) {
 struct widget_instance *w=performance_pause_control(root,i); assert(w); return w;
}
static struct widget_instance *open_options(int layout,int local) {
 struct widget_instance *root=make_widget(performance_pause_tags[_pp_options_1p+layout],NULL,local);
 assert(performance_pause_event(root,_performance_pause_created)); return root;
}
static void setup(void) {
 memset(originals,0,sizeof(originals));
 originals[3].type=_ui_widget_type_column_list;
 originals[3].child_widgets.count=2; originals[3].child_widgets.address=list_children;
 list_children[0].widget_tag.index=5; list_children[1].widget_tag.index=6;
 for(int i=0;i<NUMBER_OF_NATIVE_PAUSE_STYLES;i++) assert(native_pause_row_definition(&row_styles[i],i,NONE));
 for(int i=0;i<2;i++) for(int j=0;j<2;j++) list_buttons[i][j]=row_styles[i ? _native_pause_split_menu : _native_pause_wide];
 legend.bounds=(rectangle2d){0,0,24,168};
 for(int i=0;i<3;i++) {
   originals[i].bounds.x1=i==2 ? 320 : 640; originals[i].bounds.y1=i ? 240 : 480;
   originals[i].child_widgets.count=3; originals[i].child_widgets.address=root_children[i];
   root_children[i][0].widget_tag.index=5; root_children[i][1].widget_tag.index=4; root_children[i][2].widget_tag.index=6;
   root_children[i][1].horizontal_offset=i==2 ? 58 : 218;
   root_children[i][1].vertical_offset=i ? 95 : 207;
 }
}
/* A page: its frame first, then rows that share one font and size, never
 * reach each other, and end above the legend's divider. */
static void check_page(struct ui_widget_definition *root,struct ui_widget_child_reference *children,
   struct ui_widget_definition *column,long font,short width,short height) {
 struct ui_widget_definition *page_frame=ui_widget_definition_get(children[0].widget_tag.index);
 struct ui_widget_child_reference *rows=column->child_widgets.address;
 assert(TEST_FLAG(page_frame->flags,_widget_native_pause_frame_bit));
 assert(page_frame->bounds.x1==width+2*NATIVE_PAUSE_FRAME_MARGIN);
 assert(children[0].horizontal_offset==children[1].horizontal_offset-NATIVE_PAUSE_FRAME_MARGIN);
 /* Centred, and whole in its viewport. */
 assert(children[0].horizontal_offset*2+page_frame->bounds.x1==root->bounds.x1);
 assert(children[0].vertical_offset>=0 && children[0].vertical_offset+page_frame->bounds.y1<=root->bounds.y1);
 assert(column->bounds.x1==width);
 for(long i=0;i<column->child_widgets.count;i++) {
   struct ui_widget_definition *row=ui_widget_definition_get(rows[i].widget_tag.index);
   assert(row->text_font.index==font && row->bounds.x1==width && row->bounds.y1==height && !rows[i].horizontal_offset);
   assert(TEST_FLAG(row->flags,_widget_native_pause_row_bit) && row->background_bitmap.index==8);
   assert(row->vertical_offset==native_pause_styles[font==9 ? _native_pause_wide : _native_pause_split_options].text_y);
   if(i) assert(rows[i].vertical_offset>=rows[i-1].vertical_offset+height);
   assert(rows[i].vertical_offset+height<=column->bounds.y1);
 }
 assert(children[1].vertical_offset+column->bounds.y1<children[0].vertical_offset+page_frame->bounds.y1-NATIVE_PAUSE_FOOTER);
}
int main(void) {
 setup(); struct ui_widget_definition before[6]; memcpy(before,originals,sizeof(before));
 assert(performance_pause_remap_tag(5)==5 && performance_pause_remap_tag(NONE)==NONE);
 /* Seven string lists, the widgets and one frame for each of four page sizes. */
 assert(performance_pause_remap_tag(1)!=1 && registry_count==7+_pp_widget_count+4);
 assert(!memcmp(before,originals,sizeof(before)));
 for(int i=0;i<3;i++) {
   struct ui_widget_definition *pause=&performance_pause_definitions[_pp_pause_1p+i];
   struct ui_widget_definition *list=&performance_pause_definitions[_pp_list_1p+i];
   struct ui_widget_definition *options=&performance_pause_definitions[_pp_options_1p+i];
   int split=i ? PERFORMANCE_PAUSE_SPLIT : 0;
   assert(performance_pause_remap_tag(i+1)==performance_pause_tags[_pp_pause_1p+i]);
   /* The Pause list: four rows of the original size, in one font, wide
    * enough for PERFORMANCE OPTIONS in it. */
   assert(performance_pause_list_children[i][0].widget_tag.index==(i ? 15:5));
   assert(performance_pause_list_children[i][1].widget_tag.index==performance_pause_tags[_pp_entry_1p+i]);
   assert(performance_pause_list_children[i][2].widget_tag.index==performance_pause_tags[_pp_settings_1p+i]);
   assert(performance_pause_list_children[i][3].widget_tag.index==(i ? 16:6));
   assert(list->child_widgets.count==4 && pause->child_widgets.count==3);
   check_page(pause,performance_pause_children[i],list,9,i ? 250:284,27);
   assert(performance_pause_children[i][1].widget_tag.index==performance_pause_tags[_pp_list_1p+i]);
   assert(performance_pause_children[i][2].widget_tag.index==9002);
   assert(performance_pause_settings_events[i][0].widget_tag.index==900+i);
   assert(performance_pause_entry_events[i][0].widget_tag.index==performance_pause_tags[_pp_options_1p+i]);
   assert(options->controller_index==_widget_controller_any);
   /* Performance Options: a title and seven rows, APPLY apart from the six settings. */
   struct ui_widget_child_reference *children=performance_pause_option_children[i];
   struct ui_widget_definition *column=&performance_pause_definitions[_pp_column+split];
   struct ui_widget_definition *title=&performance_pause_definitions[_pp_title+split];
   struct ui_widget_definition *page_frame=ui_widget_definition_get(children[0].widget_tag.index);
   const struct native_pause_style *style=&native_pause_styles[i ? _native_pause_split_options : _native_pause_wide];
   assert(children[1].widget_tag.index==performance_pause_tags[_pp_column+split]);
   assert(children[2].widget_tag.index==performance_pause_tags[_pp_title+split]);
   assert(column->child_widgets.count==7 && column->child_widgets.address==performance_pause_column_children[i!=0]);
   check_page(options,children,column,i ? 7:9,i ? 250:284,i ? 21:27);
   struct ui_widget_child_reference *rows=column->child_widgets.address;
   for(int row=0;row<7;row++) {
     assert(rows[row].widget_tag.index==performance_pause_tags[_pp_preset+split+row]);
     assert(rows[row].vertical_offset==row*style->row_height+(row==6 ? style->action_gap:0));
     /* A setting's name starts at the left inset and its value ends at the
      * right one; APPLY is centred. */
     assert(ui_widget_definition_get(rows[row].widget_tag.index)->horizontal_offset==(row<6 ? style->text_inset:style->text_trail));
     struct widget_instance candidate={.definition_tag_index=rows[row].widget_tag.index};
     assert(performance_pause_is_spinner(&candidate)==(row<6));
   }
   /* The title is the page's own font in white, with the same space above
    * it and below it on every page. */
   assert(title->text_font.index==(i ? 7:9) && title->background_bitmap.index==NONE && !title->flags);
   assert(title->text_color.red==1 && title->text_color.green==1 && title->text_color.blue==1);
   assert(title->string_list_index==13 && title->bounds.x1==column->bounds.x1 && title->bounds.y1==style->row_height);
   assert(children[2].horizontal_offset==children[1].horizontal_offset);
   assert(children[2].vertical_offset==children[0].vertical_offset+style->top);
   assert(children[1].vertical_offset==children[2].vertical_offset+style->row_height+style->title_gap);
   assert(children[1].vertical_offset+column->bounds.y1+style->bottom==
       children[0].vertical_offset+page_frame->bounds.y1-NATIVE_PAUSE_FOOTER);
   /* The legend sits in the frame's footer, centred. */
   assert(children[3].widget_tag.index==9002);
   assert(children[3].vertical_offset==children[0].vertical_offset+page_frame->bounds.y1-NATIVE_PAUSE_LEGEND_Y);
   assert((children[3].horizontal_offset-children[0].horizontal_offset)*2+168==page_frame->bounds.x1);
   assert(options->child_widgets.count==(i ? 4:5));
   if(!i) {
     /* Help for the focused row, under the frame and inside the screen. */
     struct ui_widget_definition *footer=&performance_pause_definitions[_pp_footer];
     assert(children[4].widget_tag.index==performance_pause_tags[_pp_footer] && footer->text_font.index==7);
     assert(children[4].vertical_offset>=children[0].vertical_offset+page_frame->bounds.y1);
     assert(children[4].vertical_offset+footer->bounds.y1<=originals[i].bounds.y1);
     assert(children[4].horizontal_offset*2+footer->bounds.x1==originals[i].bounds.x1 && !footer->flags);
   }
 }
 /* One player's panel: 284-pixel rows at the original 27-pixel pitch. */
 assert(performance_pause_children[0][1].horizontal_offset==178 && performance_pause_children[0][0].horizontal_offset==166);
 assert(performance_pause_list_children[0][3].vertical_offset==81 && performance_pause_column_children[0][6].vertical_offset==175);
 assert(!performance_pause_is_spinner(NULL));
 for(int text=3;text<=4;text++) {
   boolean line_break=FALSE;
   for(unsigned i=0;performance_pause_text[text][i];i++)
     if(performance_pause_text[text][i]==L'\r') line_break=TRUE;
 assert(!line_break);
 }
 /* Every value of a setting is "name<tab>< value >", with the same spaces around every arrow. */
 for(int list=1;list<7;list++) {
   struct string_list *values=tag_get(UNICODE_STRING_LIST_TAG,performance_pause_string_tags[list]);
   const wchar_t *first=((struct string_list_entry *)values->strings.address)[0].string.address;
   size_t name=0; while(first[name] && first[name]!=L'\t') name++;
   for(long i=0;i<values->strings.count;i++) {
     const wchar_t *text=((struct string_list_entry *)values->strings.address)[i].string.address;
     size_t length=ustrlen(text);
     assert(!memcmp(text,first,(name+1)*sizeof(wchar_t)) && text[name]==L'\t');
     assert(text[name+1]==L'<' && text[name+2]==L' ' && text[length-2]==L' ' && text[length-1]==L'>');
   }
 }
 assert(performance_pause_definitions[_pp_entry_1p].string_list_index==0);
 assert(performance_pause_definitions[_pp_settings_1p].string_list_index==16);
 assert(ustrlen(performance_pause_text[0])==19 && ustrlen(performance_pause_text[13])==19);
 assert(performance_pause_root_events[1].flags==FLAG(_event_handler_go_back_to_previous_widget_bit));
 assert(performance_pause_apply_events[0].flags==(FLAG(_event_handler_run_function_bit)|FLAG(_event_handler_go_back_to_previous_widget_bit)));
 for(unsigned flags=0;flags<=PERFORMANCE_OPTIONS_MASK;flags++) {
   if(!performance_variant_flags_valid(flags)) continue;
   host_flags=flags;
   struct widget_instance *w=open_options(flags%3,flags%MAXIMUM_NUMBER_OF_LOCAL_PLAYERS);
   assert(performance_pause_drafts[flags%MAXIMUM_NUMBER_OF_LOCAL_PLAYERS].flags==flags);
   assert(control(w,_pp_preset)->parameters.list.selected_index==performance_variant_preset(flags));
   assert(control(w,_pp_movement)->parameters.list.selected_index==performance_variant_sound_mode(flags,8,4096));
   assert(control(w,_pp_weapon)->parameters.list.selected_index==performance_variant_sound_mode(flags,16,8192));
   assert(performance_pause_event(control(w,_pp_apply),_performance_pause_apply) && host_flags==flags);
   free_widget(w);
 }
 set_calls=0;
 host_flags=2; struct widget_instance *root=open_options(0,0);
 assert(control(root,_pp_preset)->parameters.list.selected_index==3);
 assert(control(root,_pp_markers)->parameters.list.selected_index==1);
 control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
 assert(host_flags==2 && set_calls==0 && control(root,_pp_timer)->parameters.list.selected_index==1 && control(root,_pp_audio)->parameters.list.selected_index==1);
 control(root,_pp_markers)->parameters.list.selected_index=0; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==5 && control(root,_pp_preset)->parameters.list.selected_index==3);
 free_widget(root); root=open_options(0,0); /* Cancel and reopen discard the draft. */
 assert(performance_pause_drafts[0].flags==2 && host_flags==2 && set_calls==0);
 struct widget_instance *other=open_options(2,1);
 control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
 assert(performance_pause_drafts[1].flags==2); /* Independent local-player drafts. */
 refuse=TRUE; assert(!performance_pause_event(control(root,_pp_apply),_performance_pause_apply));
 assert(host_flags==2 && performance_pause_drafts[0].flags==7 && set_calls==1);
 refuse=FALSE; assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply));
 assert(host_flags==7 && set_calls==2);
 control(root,_pp_movement)->parameters.list.selected_index=2; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==15 && host_flags==7 && set_calls==2);
 control(root,_pp_weapon)->parameters.list.selected_index=2; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==31 && control(root,_pp_preset)->parameters.list.selected_index==3 && host_flags==7);
 control(root,_pp_column)->focused_child=control(root,_pp_movement); performance_pause_update(root);
 assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_movement+2);
 control(root,_pp_column)->focused_child=control(root,_pp_weapon); performance_pause_update(root);
 assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_weapon+2);
 control(root,_pp_column)->focused_child=control(root,_pp_markers); performance_pause_update(root);
 assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_markers);
 control(root,_pp_column)->focused_child=control(root,_pp_audio); performance_pause_update(root);
 assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_audio);
 control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==7 && !control(root,_pp_movement)->parameters.list.selected_index && !control(root,_pp_weapon)->parameters.list.selected_index);
 control(root,_pp_movement)->parameters.list.selected_index=2; performance_pause_update(root);
 control(root,_pp_preset)->parameters.list.selected_index=0; performance_pause_update(root);
 assert(!performance_pause_drafts[0].flags && !control(root,_pp_movement)->parameters.list.selected_index && !control(root,_pp_weapon)->parameters.list.selected_index);
 free_widget(root); root=open_options(0,0); /* Cancel restores live host defaults. */
 assert(performance_pause_drafts[0].flags==7 && !control(root,_pp_movement)->parameters.list.selected_index && !control(root,_pp_weapon)->parameters.list.selected_index);
 assert(performance_pause_event(control(root,_pp_movement),_performance_pause_next));
 assert(performance_pause_event(control(root,_pp_weapon),_performance_pause_next));
 assert(performance_pause_drafts[0].flags==(7|4096|8192) && host_flags==7 && set_calls==2);
 assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==(7|4096|8192) && set_calls==3);
 host=FALSE; performance_pause_update(other);
 assert(control(other,_pp_preset)->disabled && performance_pause_drafts[1].flags==(7|4096|8192));
 assert(control(other,_pp_movement)->disabled && control(other,_pp_weapon)->disabled);
 assert(!widget_instance_find_by_tag_index_recursive(other,performance_pause_tags[_pp_footer]));
 control(other,_pp_timer)->parameters.list.selected_index=0; performance_pause_update(other);
 control(other,_pp_movement)->parameters.list.selected_index=0; performance_pause_update(other);
 control(other,_pp_weapon)->parameters.list.selected_index=0; performance_pause_update(other);
 assert(control(other,_pp_timer)->parameters.list.selected_index==1 && host_flags==(7|4096|8192));
 assert(control(other,_pp_movement)->parameters.list.selected_index==1 && control(other,_pp_weapon)->parameters.list.selected_index==1);
 assert(!performance_pause_event(control(other,_pp_timer),_performance_pause_next));
 assert(!performance_pause_event(control(other,_pp_movement),_performance_pause_next));
 assert(!performance_pause_event(control(other,_pp_weapon),_performance_pause_next));
 assert(performance_pause_event(control(other,_pp_apply),_performance_pause_apply) && set_calls==3);
 host_flags=1; performance_pause_update(other); assert(performance_pause_drafts[1].flags==1);
 free_widget(root); free_widget(other);
 /* Pause exposes only the six existing controls; every edit preserves the
  * host's match-start delay, including either practice-aid preset. */
 host=TRUE; host_flags=40; root=open_options(0,0);
 control(root,_pp_preset)->parameters.list.selected_index=0; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==32 && control(root,_pp_preset)->parameters.list.selected_index==0);
 control(root,_pp_timer)->parameters.list.selected_index=1; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==33);
 control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==39);
 assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==39);
 control(root,_pp_preset)->parameters.list.selected_index=0; performance_pause_update(root);
 assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==32);
 free_widget(root);
 /* Hardcore remains a pregame rule when either aid preset changes or a
  * host applies live aid edits, with and without the action delay. */
 for(unsigned timing=0;timing<=32;timing+=32) {
   host_flags=64|timing|8; root=open_options(0,0);
   control(root,_pp_preset)->parameters.list.selected_index=0; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(64|timing));
   control(root,_pp_timer)->parameters.list.selected_index=1; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(64|timing|1));
   control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(64|timing|7));
   assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==(64|timing|7));
   free_widget(root);
 }
 /* Hardcore Camo survives every live aid edit, independent of other
  * match rules. Its appearance is chosen in the pregame editor. */
 for(unsigned extras=0;extras<=224;extras+=32) {
   host_flags=256|extras|8; root=open_options(0,0);
   control(root,_pp_preset)->parameters.list.selected_index=0; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(256|extras));
   control(root,_pp_timer)->parameters.list.selected_index=1; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(256|extras|1));
   control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(256|extras|7));
   assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==(256|extras|7));
   free_widget(root);
 }
 /* Each sound can independently cycle through Normal / Just Me / Silent,
  * and Apply retains host/capability enforcement for listener-only settings. */
 host=TRUE; host_flags=0; root=open_options(0,0);
 for(short m=0;m<3;m++) for(short w=0;w<3;w++) {
   control(root,_pp_movement)->parameters.list.selected_index=m;
   control(root,_pp_weapon)->parameters.list.selected_index=w;
   performance_pause_update(root);
   unsigned expected=performance_variant_sound_flags(m,8,4096)|performance_variant_sound_flags(w,16,8192);
   assert(performance_pause_drafts[0].flags==expected && host_flags==0);
   control(root,_pp_column)->focused_child=control(root,_pp_movement); performance_pause_update(root);
   assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_movement+m);
   control(root,_pp_column)->focused_child=control(root,_pp_weapon); performance_pause_update(root);
   assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_weapon+w);
 }
 control(root,_pp_movement)->parameters.list.selected_index=1;
 control(root,_pp_weapon)->parameters.list.selected_index=1; performance_pause_update(root);
 refuse=TRUE; assert(!performance_pause_event(control(root,_pp_apply),_performance_pause_apply));
 assert(host_flags==0 && performance_pause_drafts[0].flags==(4096|8192));
 refuse=FALSE; assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply));
 assert(host_flags==(4096|8192));
 free_widget(root); root=open_options(0,0);
 assert(control(root,_pp_movement)->parameters.list.selected_index==1 && control(root,_pp_weapon)->parameters.list.selected_index==1);
 control(root,_pp_preset)->parameters.list.selected_index=2; performance_pause_update(root);
 assert(performance_pause_drafts[0].flags==(PERFORMANCE_PRO_FLAGS&~PERFORMANCE_MATCH_RULE_FLAGS));
 assert(control(root,_pp_preset)->parameters.list.selected_index==3);
 free_widget(root);
 host_flags=PERFORMANCE_PRO_FLAGS; locked=TRUE; root=open_options(0,0);
 assert(control(root,_pp_movement)->disabled && control(root,_pp_weapon)->disabled);
 assert(control(root,_pp_footer)->parameters.text_box.string_list_index==_pp_help_locked);
 unsigned previous_set_calls=set_calls;
 control(root,_pp_movement)->parameters.list.selected_index=2; performance_pause_update(root);
 assert(control(root,_pp_movement)->parameters.list.selected_index==1 && performance_pause_drafts[0].flags==PERFORMANCE_PRO_FLAGS);
 assert(!performance_pause_event(control(root,_pp_weapon),_performance_pause_next));
 assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && set_calls==previous_set_calls);
 free_widget(root); locked=FALSE;
 long old=performance_pause_tags[_pp_pause_1p];
 for(unsigned extras=0;extras<=96;extras+=32) {
   host_flags=128|extras; root=open_options(0,0);
   assert(control(root,_pp_preset)->parameters.list.selected_index==0);
   control(root,_pp_preset)->parameters.list.selected_index=1; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(128|extras|7));
   assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==(128|extras|7));
   control(root,_pp_preset)->parameters.list.selected_index=0; performance_pause_update(root);
   assert(performance_pause_drafts[0].flags==(128|extras));
   assert(performance_pause_event(control(root,_pp_apply),_performance_pause_apply) && host_flags==(128|extras));
   free_widget(root);
 }
 registry_count=0; generation++; assert(performance_pause_remap_tag(1)!=old && registry_count==7+_pp_widget_count+4);
 assert(!performance_pause_drafts[0].root && !performance_pause_drafts[1].root);
 return 0;
}
'''


class PerformancePauseMenuTest(unittest.TestCase):
    def test_sound_values_and_help_fit_stock_fonts(self):
        from tools.primary_checkout import PRIMARY
        from tools.verify_performance_sound_samples import Cache
        paths = [next((root / f"assets/maps/{name}.map" for root in (ROOT, PRIMARY)
                       if (root / f"assets/maps/{name}.map").exists()), None) for name in ("ui", "bloodgulch")]
        paths = [path for path in paths if path is not None]
        if not paths:
            self.skipTest("owned Xbox cache assets required for font metrics")
        source = (ROOT / "source/interface/performance_pause_menu.inc").read_text()
        array = source.split("static wchar_t performance_pause_text[][64] =", 1)[1].split("};", 1)[0]
        texts = [ast.literal_eval(value[1:]) for value in re.findall(r'L"(?:\\.|[^"\\])*"', array)]
        # Row widths and insets come from the kit: one player's rows are in the
        # large font, split screen's settings in the small one.
        kit = (ROOT / "source/interface/native_pause_frame.inc").read_text()
        styles = [(small == "TRUE", int(width), int(inset), int(trail)) for small, width, inset, trail in
                  re.findall(r"\{(TRUE|FALSE), (\d+), \d+, \d+, (\d+), (\d+), \d+, \d+, \d+, \d+\}", kit)]
        self.assertEqual(len(styles), 3)
        wide, split = styles[0], styles[2]
        self.assertFalse(wide[0])
        self.assertTrue(split[0])
        settings = [index for index, text in enumerate(texts) if "\t" in text]
        self.assertEqual(len(settings), 16)
        checks = [(r"ui\large_ui", settings, wide[1] - 2 * wide[2] + wide[3]),
                  (r"ui\small_ui", settings, split[1] - 2 * split[2] + split[3]),
                  (r"ui\large_ui", [0, 1, 2, 13, 16], wide[1] - wide[3]), (r"ui\small_ui", [1, 2, 13], split[1] - split[3]),
                  (r"ui\large_ui", [0, 16], styles[1][1] - styles[1][3]),
                  (r"ui\small_ui", range(23, len(texts)), 284), (r"ui\small_ui", [3, 4], 284)]
        for path in paths:
            cache = Cache(path)
            for font_path, indices, limit in checks:
                font = cache.by_path[font_path]
                count, address, _ = cache.unpack("<3I", font["address"] + 0x7C)
                glyphs = {}
                for index in range(count):
                    code, advance, width, _, origin_x = cache.unpack("<H4h", address + index * 0x14)
                    glyphs[chr(code)] = (advance, width, origin_x)
                for index in indices:
                    self.assertLess(len(texts[index]), 64)
                    # A setting needs its name, at least two spaces and its value.
                    for line in texts[index].replace("\t", "  ").splitlines():
                        with self.subTest(map=path.stem, font=font_path, text=line):
                            cursor = ink_right = 0
                            for character in line:
                                advance, width, origin_x = glyphs[character]
                                ink_right = max(ink_right, cursor + origin_x + width)
                                cursor += advance
                            self.assertLessEqual(max(cursor, ink_right), limit)

    def test_native_layout_staging_authority_and_reload(self):
        source = (ROOT / "source/interface/ui_widget.c").read_text()
        declarations = []
        for name in ("ui_widget_event_handler_reference", "ui_widget_child_reference", "ui_widget_definition"):
            declarations.append(block(source, f"struct {name}\n{{") + ";")
        for member in ("_ui_widget_type_container", "UI_WIDGET_DEFINITION_TAG =", "_widget_controller0", "_widget_pass_unhandled_events_to_children_bit =", "_event_handler_close_current_widget_bit", "_list_items_generated_in_code", "_text_justification_left", "_widget_event_b_button ="):
            start = source.rfind("enum\n{", 0, source.index(member))
            declarations.append(block(source[start:], "enum\n{") + ";")
        variant_header = (ROOT / "source/game/performance_variant.h").read_text()
        enum_end = variant_header.index("static inline short performance_variant_sound_mode")
        performance_declarations = variant_header[variant_header.index("enum\n{"):enum_end]
        for signature in ("static inline short performance_variant_sound_mode(",
                          "static inline unsigned performance_variant_sound_flags(",
                          "static inline boolean performance_variant_flags_valid(",
                          "static inline short performance_variant_preset("):
            performance_declarations += block(variant_header, signature) + "\n"
        kit = (ROOT / "source/interface/native_pause_frame.inc").read_text()
        fixture = PREFIX.replace("/* PERFORMANCE DECLARATIONS */", performance_declarations) + "\n".join(declarations)
        fixture += STUBS.replace("/* PRODUCTION PAUSE KIT */", kit)
        fixture += (ROOT / "source/interface/performance_pause_menu.inc").read_text() + HARNESS
        with tempfile.TemporaryDirectory(prefix="halo-native-pause-") as tmp:
            path = Path(tmp) / "test.c"
            path.write_text(fixture)
            binary = Path(tmp) / "test"
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-multichar", "-Wno-unused-function", "-fshort-wchar", str(path), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
