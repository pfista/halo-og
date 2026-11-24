"""Exercise the production Pause kit: panel sizes, frame and selection-box slices.

The kit, the frame and box renderers and the bitmap submission come directly
from production. Only tag lookup, bitmap loading and GPU submission are
replaced. This checks placement, UVs, clipping and stock draw behavior, not
final pixels.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r"""
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
typedef float real;
typedef unsigned char byte,boolean;
typedef uint32_t pixel32;
typedef struct {short x,y;} point2d;
typedef struct {short y0,x0,y1,x1;} rectangle2d;
typedef struct {real x,y;} real_point2d;
typedef struct {real i,j;} real_vector2d;
typedef struct {real red,green,blue;} real_rgb_color;
typedef struct {real alpha,red,green,blue;} real_argb_color;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define NUMBER_OF_POINTS_PER_RECTANGLE 4
#define MAX(a,b) ((a)>(b)?(a):(b))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define FLAG(bit) (1L<<(bit))
#define TEST_FLAG(value,bit) (((value)&FLAG(bit))!=0)
#define csmemset memset
#define csstrcmp strcmp
#define ustrlen wcslen
enum {UI_WIDGET_DEFINITION_TAG='DeLa',UNICODE_STRING_LIST_TAG='ustr',FONT_GROUP_TAG='font',
      _ui_widget_type_container=1000,_ui_widget_type_text_box,_widget_controller_any=4,
      _text_justification_center=2,_interface_bitmap_iface_map3=3};
struct tag_reference {long group_tag,index;};
struct tag_block {long count;void *address;};
struct tag_data {long size;void *address;};
struct string_list {struct tag_block strings;};
struct string_list_entry {struct tag_data string;};
struct ui_widget_definition {
 short type,controller_index; rectangle2d bounds; long flags;
 struct tag_reference background_bitmap,text_label_string_list,text_font,list_header_bitmap,
  list_footer_bitmap,extended_description_widget;
 real_argb_color text_color; short justification,horizontal_offset,vertical_offset;
};
struct bitmap_data {short width,height;};
struct bitmap_group {struct tag_block bitmaps;};
struct tag_iterator {int unused;};
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->address)[i])
/* RASTERIZER DECLARATIONS */
/* The frame's three textures, the plasma map and the 256 by 32 selection box. */
static struct bitmap_data bitmaps[5]={{16,256},{4,256},{16,256},{64,64},{256,32}};
static struct bitmap_group plasma={{1,&bitmaps[3]}};
static struct {long tag;const char *name;void *definition;} registry[32];
static unsigned registry_count,generation,quad_count;
static short missing_bitmap=NONE;
static struct {
 struct dynamic_screen_vertex vertices[4];
 struct bitmap_data *bitmap; boolean plasma; real alpha;
} quads[32];
static real_argb_color ui_plasma_effect_color={0.25f,0.05f,0.05f,0.05f};
static long tag_loaded(long group,const char *name) {
 static const char *const names[]={"ui\\shell\\bitmaps\\pausebox2_left",
  "ui\\shell\\bitmaps\\pausebox2_center","ui\\shell\\bitmaps\\pausebox2_right","ui\\shell\\bitmaps\\menu_bkds"};
 if(group=='bitm')for(short i=0;i<4;i++)if(!strcmp(name,names[i]))return missing_bitmap==i?NONE:10+i;
 if(group==FONT_GROUP_TAG)return !strcmp(name,"ui\\large_ui")?20:!strcmp(name,"ui\\small_ui")?21:NONE;
 if(group==UI_WIDGET_DEFINITION_TAG)for(unsigned i=0;i<registry_count;i++)
  if(!strcmp(name,registry[i].name))return registry[i].tag;
 return NONE;
}
static boolean tag_index_is_group(long tag,long group) {return group=='bitm' && tag>=10 && tag<=13;}
static void tag_iterator_new(struct tag_iterator *iterator,long group) {(void)iterator;(void)group;}
static long tag_iterator_next(struct tag_iterator *iterator) {(void)iterator;return NONE;}
static const char *tag_get_name(long tag) {(void)tag;return NULL;}
static long cache_files_register_runtime_ui_tag(long group,const char *name,void *definition) {
 for(unsigned i=0;i<registry_count;i++)if(!strcmp(name,registry[i].name)) {
  assert(definition==registry[i].definition);return registry[i].tag;
 }
 assert(registry_count<32);unsigned i=registry_count++;
 registry[i].tag=1000+generation*100+i;registry[i].name=name;registry[i].definition=definition;
 (void)group;return registry[i].tag;
}
static struct ui_widget_definition *ui_widget_definition_get(long tag) {
 for(unsigned i=0;i<registry_count;i++)if(registry[i].tag==tag)return registry[i].definition;
 assert(!"unknown widget");return NULL;
}
static struct bitmap_data *bitmap_group_get_bitmap_from_sequence(long tag,short sequence,short frame) {
 assert(sequence==0 && frame==0 && tag>=10 && tag<=12);return &bitmaps[tag-10];
}
static long interface_get_tag_index(short index) {assert(index==3);return 3;}
static struct bitmap_group *bitmap_group_get(long tag) {assert(tag==3);return &plasma;}
static long system_milliseconds(void) {return 1000;}
static pixel32 modulate_pixel32_by_real_alpha(pixel32 color,real alpha) {
 return (color&0xFFFFFF)|((pixel32)(alpha*255)<<24);
}
static void rasterizer_psuedo_dynamic_screen_quad_draw(
 struct rasterizer_dynamic_screen_geometry_parameters *parameters,struct dynamic_screen_vertex *vertices) {
 assert(quad_count<32);unsigned q=quad_count++;
 memcpy(quads[q].vertices,vertices,sizeof(quads[q].vertices));
 quads[q].plasma=parameters->doing_plasma_effect;
 quads[q].bitmap=parameters->map[parameters->doing_plasma_effect?2:0];
 quads[q].alpha=parameters->plasma_fade.alpha;
 assert(!parameters->point_sampled && parameters->framebuffer_blend_function==0);
}
"""


HARNESS = r"""
static void near(real actual,real expected) {assert(fabsf(actual-expected)<0.00001f);}
static void vertex(unsigned quad,unsigned index,real x,real y,real u,real v) {
 struct dynamic_screen_vertex *p=&quads[quad].vertices[index];
 near(p->position.x,x);near(p->position.y,y);near(p->texture_coordinates.x,u);near(p->texture_coordinates.y,v);
}
/* One player's whole screen, and the two split-screen viewports. */
static const rectangle2d viewports[]={{0,0,480,640},{0,0,240,640},{0,0,240,320}};
static void panels_follow_their_content(void) {
 for(unsigned view=0;view<3;view++)for(short options=0;options<2;options++) {
  short index=native_pause_style_for(&viewports[view],options);
  assert(index==(view==0 ? _native_pause_wide:options ? _native_pause_split_options:_native_pause_split_menu));
  const struct native_pause_style *style=&native_pause_styles[index];
  /* Split screen's lists keep the original rows; four of them fit. */
  short most=index==_native_pause_split_menu ? 4:NATIVE_PAUSE_MAXIMUM_ROWS;
  for(short rows=1;rows<=most;rows++)for(short title=0;title<2;title++)for(short action=0;action<2;action++) {
   struct native_pause_panel panel;
   registry_count=0;native_pause_frame_count=0; /* each size in turn; a map uses a dozen */
   assert(native_pause_panel_place(&panel,index,&viewports[view],rows,title,action));
   struct ui_widget_definition *frame=ui_widget_definition_get(panel.frame_tag);
   assert(frame->bounds.x1==style->row_width+2*NATIVE_PAUSE_FRAME_MARGIN && frame->bounds.y1==panel.height);
   /* The whole frame is on screen and centred across it. */
   short left=panel.x-NATIVE_PAUSE_FRAME_MARGIN;
   assert(left>=0 && panel.y>=0 && panel.y+panel.height<=viewports[view].y1);
   assert(left+frame->bounds.x1<=viewports[view].x1 && left==viewports[view].x1-(left+frame->bounds.x1));
   /* The same padding on every page: above the title, between the title and
    * the rows, and between the last row and the legend's divider. */
   if(title) assert(panel.title_y==style->top && panel.rows_y==style->top+style->row_height+style->title_gap);
   assert(panel.height==panel.rows_y+panel.rows_height+style->bottom+NATIVE_PAUSE_FOOTER);
   /* No row reaches the next one, and the action stands apart from the settings. */
   for(short row=0;row<rows;row++) {
    short y=native_pause_row_y(index,row,rows,action);
    assert(y+style->row_height<=panel.rows_height);
    if(row) assert(y-native_pause_row_y(index,row-1,rows,action)==
        style->row_height+(action && row==rows-1 ? style->action_gap:0));
   }
   assert(style->action_gap>0 && style->row_height>=NATIVE_PAUSE_BOX_CAP*2);
  }
  /* More rows than a page may show is a sub-page's job. */
  struct native_pause_panel refused;
  assert(!native_pause_panel_place(&refused,index,&viewports[view],NATIVE_PAUSE_MAXIMUM_ROWS+1,TRUE,TRUE));
  assert(!native_pause_panel_place(&refused,index,&viewports[view],0,TRUE,FALSE));
 }
 /* The wide panel holds the widest setting in the large font; a quarter screen cannot hold it. */
 assert(native_pause_styles[_native_pause_wide].row_width>=268);
 struct native_pause_panel panel;
 assert(!native_pause_panel_place(&panel,_native_pause_wide,&viewports[2],4,TRUE,FALSE) || panel.x>=NATIVE_PAUSE_FRAME_MARGIN);
}
static void rows_and_titles(void) {
 for(short index=0;index<NUMBER_OF_NATIVE_PAUSE_STYLES;index++) {
  struct ui_widget_definition row,title;
  missing_bitmap=3;assert(!native_pause_row_definition(&row,index,NONE));
  assert(native_pause_row_definition(&row,index,12) && row.background_bitmap.index==12);
  missing_bitmap=NONE;assert(native_pause_row_definition(&row,index,NONE));
  const struct native_pause_style *style=&native_pause_styles[index];
  /* One font for every row of a page. */
  assert(row.text_font.index==(style->small_font ? 21:20) && row.background_bitmap.index==13);
  assert(row.type==_ui_widget_type_text_box && TEST_FLAG(row.flags,_widget_native_pause_row_bit));
  assert(row.bounds.x0==0 && row.bounds.y0==0 && row.bounds.x1==style->row_width && row.bounds.y1==style->row_height);
  assert(row.justification==_text_justification_center && row.vertical_offset==style->text_y && !row.horizontal_offset);
  native_pause_title_definition(&title,&row);
  assert(!title.flags && title.background_bitmap.index==NONE && title.text_font.index==row.text_font.index);
  assert(title.text_color.red==1 && title.text_color.green==1 && title.text_color.blue==1 && title.text_color.alpha==1);
  assert(!memcmp(&title.bounds,&row.bounds,sizeof(row.bounds)) && title.vertical_offset==row.vertical_offset);
  assert(native_pause_legend_x(index)*2+168==style->row_width);
 }
 /* The stock button's text sits three lines below its top. */
 assert(native_pause_styles[_native_pause_wide].text_y==3 && native_pause_styles[_native_pause_wide].row_height==27);
}
static void tag_lifecycle(void) {
 registry_count=0;native_pause_frame_count=0;
 assert(native_pause_frame_tag(226,46)==NONE && native_pause_frame_tag(31,159)==NONE && !registry_count);
 missing_bitmap=1;assert(native_pause_frame_tag(226,213)==NONE && !registry_count);
 missing_bitmap=NONE;long first=native_pause_frame_tag(226,159);assert(first==1000+generation*100 && registry_count==1);
 /* Pages of one size share a frame; another size gets its own. */
 assert(native_pause_frame_tag(226,159)==first && registry_count==1);
 long wide=native_pause_frame_tag(308,159),tall=native_pause_frame_tag(226,240);
 assert(wide!=first && tall!=first && wide!=tall && registry_count==3);
 const short sizes[3][2]={{226,159},{308,159},{226,240}};
 for(unsigned i=0;i<3;i++) {
  struct ui_widget_definition *definition=ui_widget_definition_get(native_pause_frame_tag(sizes[i][0],sizes[i][1]));
  assert(definition->bounds.x0==0 && definition->bounds.x1==sizes[i][0]);
  assert(definition->bounds.y0==0 && definition->bounds.y1==sizes[i][1]);
  assert(definition->background_bitmap.index==NONE && definition->text_font.index==NONE);
  assert(definition->type==_ui_widget_type_container && definition->controller_index==_widget_controller_any);
  assert(definition->flags==FLAG(_widget_native_pause_frame_bit));
 }
 assert(registry_count==3);
 /* A full pool refuses a new size and still serves the sizes it has. */
 for(short height=100;registry_count<NATIVE_PAUSE_MAXIMUM_FRAMES;height++) assert(native_pause_frame_tag(226,height)!=NONE);
 assert(native_pause_frame_tag(226,99)==NONE && native_pause_frame_tag(308,159)==wide);
 /* Another map: the old registrations are gone and the pool starts again. */
 registry_count=0;generation++;long replacement=native_pause_frame_tag(226,213);
 assert(replacement==1000+generation*100 && replacement!=first && registry_count==1 && native_pause_frame_count==1);
}
static void authored_caps_and_viewports(void) {
 const point2d origins[]={{166,99},{183,2},{23,2}};
 const short sizes[][2]={{226,159},{308,282},{308,157},{274,236}};
 for(unsigned layout=0;layout<3;layout++)for(unsigned size=0;size<4;size++) {
  short width=sizes[size][0],height=sizes[size][1];
  if(layout==2 && width>274) continue;
  if(layout && height>240) continue;
  struct ui_widget_definition *definition=ui_widget_definition_get(native_pause_frame_tag(width,height));
  rectangle2d clip=viewports[layout];point2d origin=origins[layout];quad_count=0;
  native_pause_frame_render(definition,&clip,origin,0.5f);assert(quad_count==9);
  for(unsigned piece=0;piece<3;piece++) {
   unsigned top=piece*3,middle=top+1,bottom=top+2;
   real x0=origin.x+(piece==0?0:piece==1?16:width-16),wide=piece==1?width-32:16;
   vertex(top,0,x0,origin.y,0,0);vertex(top,2,x0+wide,origin.y+16,1,16.0f/256);
   vertex(middle,0,x0,origin.y+16,0,16.0f/256);
   vertex(middle,2,x0+wide,origin.y+height-31,1,128.0f/256);
   vertex(bottom,0,x0,origin.y+height-31,0,128.0f/256);
   vertex(bottom,2,x0+wide,origin.y+height,1,159.0f/256);
   assert(quads[top].bitmap==&bitmaps[piece] && quads[middle].bitmap==&bitmaps[piece] && quads[bottom].bitmap==&bitmaps[piece]);
   for(unsigned band=0;band<3;band++) {
    unsigned q=top+band;assert(quads[q].plasma && quads[q].alpha==0.25f);
    for(unsigned v=0;v<4;v++) {
     assert(quads[q].vertices[v].color==0x7FFFFFFF);
     assert(quads[q].vertices[v].position.x>=clip.x0 && quads[q].vertices[v].position.x<=clip.x1);
     assert(quads[q].vertices[v].position.y>=clip.y0 && quads[q].vertices[v].position.y<=clip.y1);
    }
   }
  }
 }
 /* A stock widget must not enter this rendering path. */
 struct ui_widget_definition stock={.bounds={0,0,159,226},.flags=FLAG(_widget_native_pause_row_bit)|0x7FFF};
 quad_count=0;native_pause_frame_render(&stock,NULL,(point2d){0,0},1);assert(!quad_count);
}
static void selection_box_keeps_its_ends(void) {
 /* At the authored 202 by 27 the nine pieces are the stock crop: every
  * corner's texture coordinate is its place in the box. */
 const rectangle2d rows[]={{50,100,77,302},{50,100,77,384},{50,100,71,350},{10,0,37,202}};
 for(unsigned r=0;r<4;r++) {
  rectangle2d row=rows[r];quad_count=0;
  native_pause_box_render(&bitmaps[4],&row,NULL,0xFFFFFFFF);
  short width=row.x1-row.x0,height=row.y1-row.y0;
  short cap=height>=20 ? 10:height/2;
  /* A 21-line row has a one-line middle; all nine pieces still draw. */
  assert(quad_count==9);
  const real x[4]={row.x0,row.x0+16,row.x1-16,row.x1},u[4]={0,16,186,202};
  const real y[4]={row.y0,row.y0+cap,row.y1-cap,row.y1},v[4]={0,10,17,27};
  for(unsigned piece=0;piece<3;piece++)for(unsigned band=0;band<3;band++) {
   unsigned q=piece*3+band;assert(quads[q].bitmap==&bitmaps[4] && quads[q].plasma);
   vertex(q,0,x[piece],y[band],u[piece]/256,v[band]/32);
   vertex(q,2,x[piece+1],y[band+1],u[piece+1]/256,v[band+1]/32);
   if(width==202 && height==27) {
    near(quads[q].vertices[0].texture_coordinates.x,(quads[q].vertices[0].position.x-row.x0)/256);
    near(quads[q].vertices[2].texture_coordinates.y,(quads[q].vertices[2].position.y-row.y0)/32);
   }
  }
 }
 /* A viewport edge cuts the box without moving its pieces. */
 rectangle2d row={50,100,77,384},clip={0,0,240,320};quad_count=0;
 native_pause_box_render(&bitmaps[4],&row,&clip,0xFFFFFFFF);assert(quad_count==6);
 for(unsigned q=0;q<6;q++)for(unsigned v=0;v<4;v++) assert(quads[q].vertices[v].position.x<=320);
 vertex(3,2,320,60,(16+170.0f*204/252)/256,10.0f/32);
}
static void clipped_source_alignment(void) {
 rectangle2d destination={50,10,150,210},source={128,3,159,15},clip={75,60,125,160};
 rectangle2d before_destination=destination,before_source=source,before_clip=clip;
 quad_count=0;draw_bitmap_region_in_rect(&bitmaps[0],&destination,&source,&clip,0xAACCDDFF,NULL,TRUE,&source);
 assert(quad_count==1 && !quads[0].plasma);
 vertex(0,0,60,75,6.0f/16,135.75f/256);vertex(0,2,160,125,12.0f/16,151.25f/256);
 assert(quads[0].vertices[0].color==0xAACCDDFF);
 assert(!memcmp(&before_destination,&destination,sizeof(destination)));
 assert(!memcmp(&before_source,&source,sizeof(source)) && !memcmp(&before_clip,&clip,sizeof(clip)));
 /* Fully outside, empty destination and a clip merely touching an edge draw nothing. */
 const rectangle2d outside[]={{0,0,40,300},{160,0,200,300},{0,220,200,300},{0,-30,200,0},
                             {0,0,50,300},{0,0,200,10},{50,10,50,210}};
 for(unsigned i=0;i<sizeof(outside)/sizeof(outside[0]);i++) {
  rectangle2d c=outside[i];quad_count=0;
  draw_bitmap_region_in_rect(&bitmaps[0],&destination,&source,&c,0,NULL,TRUE,&source);assert(!quad_count);
 }
 rectangle2d empty={50,10,50,210};quad_count=0;
 draw_bitmap_region_in_rect(&bitmaps[0],&empty,&source,NULL,0,NULL,TRUE,&source);assert(!quad_count);
 /* The full panel clips into a small viewport without moving/stretching caps. */
 struct ui_widget_definition *definition=ui_widget_definition_get(native_pause_frame_tag(226,240));
 clip=(rectangle2d){30,110,200,320};quad_count=0;
 native_pause_frame_render(definition,&clip,(point2d){104,24},1);assert(quad_count==6);
 vertex(0,0,110,30,6.0f/16,6.0f/256);vertex(0,2,120,40,1,16.0f/256);
 vertex(5,0,314,40,0,16.0f/256);
 vertex(5,2,320,200,6.0f/16,(16.0f+160.0f*112.0f/193.0f)/256);
}
static void stock_bitmap_regression(void) {
 /* Authored widgets retain their previous UV behavior, including source
  * extents from bounds and clipping without source-coordinate adjustment. */
 rectangle2d destination={30,20,270,220},clip={90,60,210,200};quad_count=0;
 draw_bitmap_in_rect(&bitmaps[0],&destination,&destination,&clip,0xFFFFFFFF,NULL,TRUE);
 assert(quad_count==1 && !quads[0].plasma);
 vertex(0,0,60,90,0,0);vertex(0,2,200,210,1,240.0f/256);
 rectangle2d bitmap_rect={7,5,166,9};quad_count=0;
 draw_bitmap_in_rect(&bitmaps[0],&destination,&bitmap_rect,&clip,0xFFFFFFFF,NULL,FALSE);
 assert(quad_count==1 && quads[0].plasma && quads[0].bitmap==&bitmaps[0]);
 vertex(0,0,60,90,0,0);vertex(0,2,200,210,4.0f/16,159.0f/256);
 quad_count=0;draw_bitmap_in_rect(&bitmaps[0],&destination,NULL,NULL,0xFFFFFFFF,NULL,TRUE);
 vertex(0,0,20,30,0,0);vertex(0,2,220,270,1,1);
 quad_count=0;draw_bitmap_in_rect(NULL,&destination,NULL,NULL,0,NULL,TRUE);assert(!quad_count);
 draw_bitmap_in_rect(&bitmaps[0],NULL,NULL,NULL,0,NULL,TRUE);assert(!quad_count);
}
int main(void) {
 panels_follow_their_content();rows_and_titles();tag_lifecycle();authored_caps_and_viewports();
 selection_box_keeps_its_ends();clipped_source_alignment();stock_bitmap_regression();
 puts("Pause panel sizes, frame and selection-box slices, UV clipping and stock bitmap behavior passed");
 return 0;
}
"""


class NativePauseFrameTests(unittest.TestCase):
    def test_production_panel_frame_and_box_geometry(self):
        widget = (ROOT / "source/interface/ui_widget.c").read_text()
        rasterizer = (ROOT / "source/rasterizer/rasterizer.h").read_text()
        declarations = "\n".join(block(rasterizer, signature) + ";" for signature in (
            "struct dynamic_screen_vertex\n{", "struct rasterizer_dynamic_screen_geometry_parameters\n{"))
        source = PREFIX.replace("/* RASTERIZER DECLARATIONS */", declarations)
        source += (ROOT / "source/interface/native_pause_frame.inc").read_text() + "\n"
        for signature in ("static __inline real compute_offset_coordinate(",
                          "static void draw_bitmap_region_in_rect(", "void draw_bitmap_in_rect(",
                          "static void native_pause_frame_render(", "static void native_pause_box_render("):
            source += function(widget, signature) + "\n"
        source += HARNESS
        with tempfile.TemporaryDirectory(prefix="halo-pause-frame-") as temporary:
            directory = Path(temporary)
            (directory / "test.c").write_text(source)
            subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-parameter", "-Wno-unused-function", "-Wno-multichar",
                            "-fsanitize=address,undefined",
                            str(directory / "test.c"), "-o", str(directory / "test")], check=True)
            subprocess.run([str(directory / "test")], check=True)


if __name__ == "__main__":
    unittest.main()
