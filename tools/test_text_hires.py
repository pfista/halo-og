#!/usr/bin/env python3
"""Portable checks of the real font core, parser and rasterizer adapters.

Only the engine's tag/bitmap/GPU boundaries are mocked. The production parser,
preflight wrappers, glyph rasterizer, clipping and shadow submission are compiled
unchanged, with the committed fonts. No GL/Metal runtime or game data is needed.
"""
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"


def declaration(source, start):
    begin = source.index(start)
    opening = source.index("{", begin)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[begin:end] + (";" if source[end:end + 1] == ";" else "")


def function(source, name):
    match = re.search(r"(?m)^(?:static\s+)?[A-Za-z_][A-Za-z_\s*]*\b" +
                      re.escape(name) + r"\s*\([^;{}]*\)\s*\{", source)
    if not match:
        raise ValueError(name)
    return declaration(source, source[match.start():match.end()])


def embedded_fonts():
    """Use the production 32-bit word ABI, without unrelated PNG tables."""
    fonts = json.loads((ROOT / "port/assets/fonts/fonts.json").read_text())["fonts"]
    files = sorted({font["file"] for font in fonts})
    lines = ['#include "text_hires.h"']
    for index, name in enumerate(files):
        data = (ROOT / "port/assets/fonts" / name).read_bytes()
        data += b"\0" * (-len(data) % 4)
        words = struct.unpack(f"<{len(data) // 4}I", data)
        lines.append(f"static const unsigned int font{index}[] = {{")
        for start in range(0, len(words), 8):
            lines.append(",".join(f"0x{word:08x}u" for word in words[start:start + 8]) + ",")
        lines.append("};")
    lines.append("const struct text_hires_embedded text_hires_embedded[] = {")
    for font in fonts:
        tag = json.dumps(font["tag"])
        name = json.dumps(font["file"])
        size = (ROOT / "port/assets/fonts" / font["file"]).stat().st_size
        lines.append(f"{{{tag},{name},font{files.index(font['file'])},{size}}},")
    lines += ["};", f"const unsigned int text_hires_embedded_count = {len(fonts)};"]
    return "\n".join(lines) + "\n"


CORE_PREFIX = r'''
#include <assert.h>
#include <ctype.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "text_hires.h"
static int enabled = 1, allocation_calls, fail_allocation, fail_at_allocation;
static float pixel_scale = 2.0f;
int asset_quality_upres(void) { return enabled; }
float halo_screen_pixel_scale(void) { return pixel_scale; }
static void *fixture_malloc(size_t size) {
    allocation_calls++;
    if (fail_allocation || allocation_calls==fail_at_allocation) return NULL;
    return malloc(size);
}
#define malloc fixture_malloc
#include "text_hires.c"
#undef malloc
static unsigned long placeholder[5] = {0,0x123400,0,0,0};
static void register_atlas(void) { text_hires_register_atlas(placeholder,256,256); }
static void near_value(float a,float b) { assert(fabsf(a-b)<0.0001f); }
static void core_tests(const char *mode) {
    struct text_hires_glyph glyph,again;
    struct text_hires_atlas_pixels view,other;
    long font;
    if (!strcmp(mode,"original")) {
        enabled=0;
        assert(text_hires_font("ui\\large_ui",12)==-1);
        register_atlas(); assert(!text_hires_batch_begin(0));
        assert(!text_hires_atlas_pixels(placeholder[1],&view));
        assert(!view.rgba && !view.width && !view.height && !view.revision);
        assert(allocation_calls==0); return;
    }
    register_atlas();
    font=text_hires_font("ui\\large_ui",12); assert(font>=0);
    assert(text_hires_font("UI\\LARGE_UI",12)==font);
    if (!strcmp(mode,"invalid")) {
        assert(text_hires_font("ui\\unknown",12)==-1);
        assert(text_hires_font("ui\\large_ui",NAN)==-1);
        assert(text_hires_font("ui\\large_ui",INFINITY)==-1);
        assert(text_hires_font(NULL,12)==-1);
        assert(text_hires_font("ui\\large_ui",0)==-1);
        assert(text_hires_font("ui\\large_ui",1e30f)==-1);
        assert(!text_hires_covers(font,0x65e5));
        assert(!text_hires_covers(font,0xd800));
        assert(!text_hires_covers(font,0x110000));
        assert(!text_hires_glyph(font,'H',&glyph));
        pixel_scale=NAN; assert(!text_hires_batch_begin(0));
        pixel_scale=0; assert(!text_hires_batch_begin(0));
        pixel_scale=65; assert(!text_hires_batch_begin(0));
        assert(!text_hires_atlas_pixels(placeholder[1],NULL)); return;
    }
    if (!strcmp(mode,"allocation")) {
        fail_allocation=1; assert(!text_hires_batch_begin(0));
        fail_allocation=0; assert(text_hires_batch_begin(0));
        assert(text_hires_atlas_pixels(placeholder[1],&view));
        fail_allocation=1; assert(!text_hires_glyph(font,'H',&glyph));
        fail_allocation=0; assert(text_hires_atlas_pixels(placeholder[1],&other));
        assert(view.revision==other.revision);
        /* First allocation succeeds, then stb's shape/scratch allocation fails.
         * Its void bitmap API must still make the whole draw fall back. */
        fail_at_allocation=allocation_calls+2;
        assert(!text_hires_glyph(font,'H',&glyph));
        fail_at_allocation=0;
        assert(text_hires_atlas_pixels(placeholder[1],&other));
        assert(view.revision==other.revision && !text_hires_batch_full());
        assert(text_hires_glyph(font,'H',&glyph)); text_hires_batch_end(); return;
    }
    assert(text_hires_batch_begin(0));
    assert(!text_hires_batch_begin(1));
    assert(text_hires_glyph(font,'H',&glyph));
    assert(text_hires_atlas_pixels(placeholder[1],&view));
    assert(view.width==2048 && view.height==2048 && view.dirty_top==0 && view.dirty_bottom==2048);
    assert(!text_hires_atlas_pixels(placeholder[1]+1,&other));
    assert(text_hires_glyph(font,'H',&again));
    assert(!memcmp(&glyph,&again,sizeof(glyph)));
    assert(text_hires_atlas_pixels_since(placeholder[1],view.revision,&other));
    assert(other.revision==view.revision && other.dirty_top==2048 && other.dirty_bottom==0);
    if (!strcmp(mode,"rgba")) {
        int ink=0,antialias=0;
        for (size_t i=0;i<(size_t)view.width*view.height;i++) {
            assert(view.rgba[i*4]==255 && view.rgba[i*4+1]==255 && view.rgba[i*4+2]==255);
            ink+=view.rgba[i*4+3]!=0;
            antialias+=view.rgba[i*4+3]>0 && view.rgba[i*4+3]<255;
        }
        assert(ink>0 && antialias>0);
        int x0=(int)(glyph.u0*8),y0=(int)(glyph.v0*8);
        int x1=(int)(glyph.u1*8),y1=(int)(glyph.v1*8);
        assert(y1-y0==24); near_value(glyph.top,-12); near_value(glyph.bottom,0);
        for (int y=y0-2;y<y1+2;y++) for(int x=x0-2;x<x1+2;x++)
            if(x<x0 || x>=x1 || y<y0 || y>=y1) assert(view.rgba[((size_t)y*view.width+x)*4+3]==0);
    } else if (!strcmp(mode,"dirty")) {
        assert(text_hires_glyph(font,'W',&again));
        assert(text_hires_atlas_pixels_since(placeholder[1],view.revision,&other));
        assert(other.revision>view.revision && other.dirty_top<other.dirty_bottom && other.dirty_bottom<2048);
        struct text_hires_atlas_pixels independent;
        assert(text_hires_atlas_pixels_since(placeholder[1],view.revision,&independent));
        assert(!memcmp(&independent,&other,sizeof(other)));
        assert(text_hires_atlas_pixels_since(placeholder[1],0,&independent));
        assert(independent.dirty_top==0 && independent.dirty_bottom==2048);
        assert(text_hires_glyph(font,' ',&again) && again.left==again.right);
        assert(text_hires_glyph(font,'\r',&again) && again.top==again.bottom);
        assert(text_hires_atlas_pixels(placeholder[1],&independent));
        assert(independent.revision==other.revision);
    } else if (!strcmp(mode,"scale")) {
        float advance=glyph.advance;
        text_hires_batch_end(); pixel_scale=3;
        assert(text_hires_batch_begin(0)); assert(text_hires_glyph(font,'H',&again));
        near_value(again.advance,advance); near_value(again.top,-12);
        near_value((again.v1-again.v0)*8,36);
        assert(text_hires_atlas_pixels_since(placeholder[1],view.revision,&other));
        assert(other.dirty_top==0 && other.dirty_bottom==2048);
        text_hires_batch_end(); pixel_scale=1.5f;
        assert(text_hires_batch_begin(0)); assert(text_hires_glyph(font,'H',&again));
        near_value((again.v1-again.v0)*8,18); near_value(again.advance,advance);
        long taller=text_hires_font("ui\\large_ui",24); assert(taller>=0 && taller!=font);
        assert(text_hires_glyph(taller,'H',&again)); near_value(again.top,-24);
    } else if (!strcmp(mode,"capacity")) {
        text_hires_batch_end(); pixel_scale=4;
        long huge=text_hires_font("ui\\large_ui",500); assert(huge>=0);
        assert(text_hires_batch_begin(1)); assert(text_hires_glyph(huge,'H',&glyph));
        assert(text_hires_atlas_pixels(placeholder[1],&view));
        int failed=0;
        for(unsigned long code='A';code<='Z';code++) if(!text_hires_glyph(huge,code,&again)) {failed=1;break;}
        assert(failed);
        assert(text_hires_glyph(huge,'H',&again)); assert(!memcmp(&glyph,&again,sizeof(glyph)));
        assert(text_hires_atlas_pixels_since(placeholder[1],view.revision,&other));
        assert(other.dirty_bottom<2048 || other.dirty_top>0); /* never silently repacked */
    } else assert(!strcmp(mode,"dispose"));
    text_hires_batch_end();
    uint64_t previous=atlas_revision;
    text_hires_dispose(); assert(!text_hires_atlas_pixels(placeholder[1],&view));
    register_atlas(); assert(text_hires_batch_begin(0));
    assert(text_hires_atlas_pixels(placeholder[1],&view)); assert(view.revision>previous);
    text_hires_batch_end();
}
'''


ENGINE_PREFIX = r'''
typedef unsigned char byte;
typedef unsigned short word;
typedef unsigned long pixel32;
typedef int boolean;
typedef float real;
typedef struct { short x,y; } point2d;
typedef struct { short y0,x0,y1,x1; } rectangle2d;
typedef struct { float alpha,red,green,blue; } real_argb_color;
typedef struct { float x,y; } real_point2d;
typedef struct { float i,j; } real_vector2d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define SHORT_MIN (-32768)
#define SHORT_MAX 32767
#define MAX(a,b) ((a)>(b)?(a):(b))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define FLOOR MAX
#define TEST_FLAG(value,bit) (((value) & (1UL << (bit))) != 0)
#define match_assert(file,line,condition) assert(condition)
#define match_vassert(file,line,condition,...) assert(condition)
#define display_assert(...) assert(0)
#define system_exit exit
#define NUMBER_OF_VERTICES_PER_QUADRILATERAL 4
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
struct bitmap_data { short width,height; unsigned long *hardware_format; };
struct dynamic_screen_vertex { real_point2d position,texture_coordinates; pixel32 color; };
struct rasterizer_dynamic_screen_geometry_parameters {
    void *meter_parameters;
    struct bitmap_data *map[3]; real_vector2d map_scale[3],map_texture_scale[3];
    short framebuffer_blend_function; boolean point_sampled;
};
struct font_header {
    short ascending_height,descending_height,leading_height,leading_width;
    struct { long index; } style_fonts[4];
    struct { long size; void *address; } pixels;
};
struct parse_string_state;
struct font_character;
typedef void (*draw_character_proc)(struct parse_string_state *,struct font_header *,
    struct font_character *,pixel32,short,short,short,short,short,short);
static struct font_header fixture_fonts[3];
#define font_definition_get(index) (&fixture_fonts[index])
static short rectangle2d_width(const rectangle2d *r) { return r->x1-r->x0; }
static rectangle2d *set_rectangle2d(rectangle2d *r,short x0,short y0,short x1,short y1) {
    r->x0=x0;r->y0=y0;r->x1=x1;r->y1=y1;return r;
}
static void offset_rectangle2d(rectangle2d *r,short x,short y) { r->x0+=x;r->x1+=x;r->y0+=y;r->y1+=y; }
static char *string_list_get_string(long index,short entry) {
    (void)index; return entry==4 ? " " : "";
}
static char *tag_get_name(long index) {
    return index==0 ? "ui\\large_ui" : index==1 ? "ui\\small_ui" : "custom\\unmapped_font";
}
'''


ENGINE_BOUNDARIES = r'''
static struct font_drawing_globals font_drawing_globals;
static short global_language_code;
static struct font_character fixture_characters[3][128],unicode_character;
static unsigned char original_ink[3][144];
static struct font_character *font_get_character_by_ascii_code(struct font_header *font,word code) {
    int index=(int)(font-fixture_fonts);
    if(code>=32 && code<128) return &fixture_characters[index][code];
    if(code==0x65e5 || code==0xffff) { unicode_character.character=code; return &unicode_character; }
    return NULL;
}
static void fixture_fonts_initialize(void) {
    memset(&font_drawing_globals,0,sizeof(font_drawing_globals));
    font_drawing_globals.current_font_index=0; font_drawing_globals.current_style=_text_style_plain;
    font_drawing_globals.current_color=(real_argb_color){.5f,.2f,.4f,.8f};
    for(int index=0;index<3;index++) {
        int h=index==1 ? 9 : 12;
        memset(original_ink[index],255,sizeof(original_ink[index]));
        fixture_fonts[index].pixels.address=original_ink[index]; fixture_fonts[index].pixels.size=sizeof(original_ink[index]);
        fixture_fonts[index].ascending_height=h; fixture_fonts[index].descending_height=3;
        fixture_fonts[index].leading_height=2; fixture_fonts[index].leading_width=1;
        for(int style=0;style<4;style++) fixture_fonts[index].style_fonts[style].index=NONE;
        for(int code=32;code<128;code++) fixture_characters[index][code]=(struct font_character){
            (word)code,(short)(index==1?6:8),(short)(code==' '?0:8),(short)(code==' '?0:h),1,(short)h,NONE,0,0};
    }
    fixture_fonts[0].style_fonts[_text_style_bold].index=1;
    fixture_fonts[0].style_fonts[_text_style_italic].index=2;
    unicode_character=(struct font_character){0,12,8,12,1,12,NONE,0,0};
}
static struct bitmap_data original_bitmap={128,128,NULL};
static int bitmap_allocations,begin_count,end_count,original_draws,quad_count;
static struct bitmap_data *bound_bitmap;
static struct dynamic_screen_vertex quads[1024][4];
static struct { int draw_dynamic_screen_geometry; } rasterizer_debug_options={1};
static struct { int rasterizer_target; } global_window_parameters;
static struct { struct { rectangle2d window_bounds,viewport_bounds; } camera; } render={{{0,0,480,640},{0,0,480,640}}};
static int magic_number;
static pixel32 global_shadow_color;
static struct bitmap_data *hires_text_atlas;
static boolean hires_preflight_ok;
static struct { struct font_header *header; long font; } hires_batch_fonts[16];
static short hires_batch_font_count;
static struct { real scale,anchor_x,anchor_y; } rasterizer_text_transform={1,0,0};
enum { _bitmap_format_a4r4g4b4=9,_rasterizer_target_render_primary=0,_shader_framebuffer_blend_function_alpha_blend=0 };
static struct bitmap_data *hardware_character_cache_get_bitmap(void) { return &original_bitmap; }
static struct bitmap_data *bitmap_2d_new(short width,short height,short levels,short format) {
    (void)levels;(void)format;bitmap_allocations++;
    struct bitmap_data *bitmap=calloc(1,sizeof(*bitmap));
    bitmap->width=width;bitmap->height=height;bitmap->hardware_format=placeholder;return bitmap;
}
static int rasterizer_bitmap_new(struct bitmap_data *bitmap) { return bitmap!=NULL; }
static void bitmap_delete(struct bitmap_data *bitmap) { free(bitmap); }
static void rasterizer_text_begin(struct rasterizer_dynamic_screen_geometry_parameters *p) {
    begin_count++;bound_bitmap=p->map[0];
    assert(p->map_texture_scale[0].i==1.0f/p->map[0]->width);
    assert(p->framebuffer_blend_function==0 && !p->point_sampled);
}
static void rasterizer_text_end(void) { end_count++; }
static void rasterizer_text_draw_character(struct dynamic_screen_vertex *vertices) {
    assert(quad_count<1024);memcpy(quads[quad_count++],vertices,sizeof(quads[0]));
}
static void rasterizer_draw_character(struct parse_string_state *state,struct font_header *font,
    struct font_character *character,pixel32 color,short x0,short y0,short x,short y,short dx,short dy) {
    (void)state;(void)font;(void)character;(void)color;(void)x0;(void)y0;(void)x;(void)y;(void)dx;(void)dy;original_draws++;
}
static void rasterizer_draw_character_with_dropshadow(struct parse_string_state *state,struct font_header *font,
    struct font_character *character,pixel32 color,short x0,short y0,short x,short y,short dx,short dy) {
    rasterizer_draw_character(state,font,character,color,x0,y0,x,y,dx,dy);
}
static long ustrlen(const wchar_t *s) { return (long)wcslen(s); }
void draw_string(draw_character_proc,const rectangle2d *,point2d *,const rectangle2d *,short,const char *);
void draw_unicode_string(draw_character_proc,const rectangle2d *,point2d *,const rectangle2d *,short,const wchar_t *);
'''


ENGINE_TESTS = r'''
struct trace { long font;word code;pixel32 color;short x0,y0,x,y,dx,dy; };
static struct trace traces[2][256];
static int trace_index,trace_counts[2];
static void capture(struct parse_string_state *state,struct font_header *font,struct font_character *character,
    pixel32 color,short x0,short y0,short x,short y,short dx,short dy) {
    (void)state;assert(trace_counts[trace_index]<256);
    traces[trace_index][trace_counts[trace_index]++]=(struct trace){font-fixture_fonts,character->character,color,x0,y0,x,y,dx,dy};
}
static void engine_tests(const char *mode) {
    fixture_fonts_initialize();
    rectangle2d bounds={0,0,70,160},clip={0,0,70,160};point2d cursor={0,0};
    if(!strcmp(mode,"preflight")) {
        const char *texts[]={"HALO","A|bB|pC|nD","A\tB\rC","A B C D E F G","|rA|lB","|cA B"};
        for(int justify=0;justify<3;justify++) for(int i=0;i<6;i++) {
            trace_counts[0]=trace_counts[1]=0;memset(traces,0,sizeof(traces));
            font_drawing_globals.highlight_start_index=0;font_drawing_globals.highlight_stop_index=3;
            font_drawing_globals.current_justification=justify;font_drawing_globals.current_flags=1;
            font_drawing_globals.tab_stop_count=1;font_drawing_globals.tab_stops[0]=80;
            point2d a={9,11},b=a;trace_index=0;
            draw_string_preflight(capture,&bounds,&a,&clip,1,texts[i]);
            assert(font_drawing_globals.highlight_stop_index==3);
            trace_index=1;draw_string(capture,&bounds,&b,&clip,1,texts[i]);
            assert(!memcmp(&a,&b,sizeof(a)) && trace_counts[0]==trace_counts[1]);
            assert(!memcmp(traces[0],traces[1],sizeof(traces[0])));
            assert(font_drawing_globals.highlight_start_index==0 && font_drawing_globals.highlight_stop_index==0);
        }
        const wchar_t *texts_w[]={L"HALO",L"A|nB",L"A\tB\rC",L"A B C"};
        for(int i=0;i<4;i++) {
            trace_counts[0]=trace_counts[1]=0;memset(traces,0,sizeof(traces));
            font_drawing_globals.highlight_start_index=1;font_drawing_globals.highlight_stop_index=3;
            point2d a={9,11},b=a;trace_index=0;draw_unicode_string_preflight(capture,&bounds,&a,&clip,0,texts_w[i]);
            assert(font_drawing_globals.highlight_start_index==1 && font_drawing_globals.highlight_stop_index==3);
            trace_index=1;draw_unicode_string(capture,&bounds,&b,&clip,0,texts_w[i]);
            assert(!memcmp(&a,&b,sizeof(a)) && trace_counts[0]==trace_counts[1]);
            assert(!memcmp(traces[0],traces[1],sizeof(traces[0])));
        }
        assert(draw_string_get_font_index(&fixture_fonts[0])==0);
        assert(draw_string_get_font_index(&fixture_fonts[1])==1);
        assert(draw_string_get_font_index(&fixture_fonts[2])==2);return;
    }
    if(!strcmp(mode,"original-wrapper")) enabled=0;
    if(!strcmp(mode,"fallback-font")) font_drawing_globals.current_style=_text_style_italic;
    if(!strcmp(mode,"fallback-capacity")) {
        pixel_scale=64;fixture_characters[0]['H'].bitmap_height=100;
        fixture_fonts[0].pixels.size=800;fixture_fonts[0].pixels.address=calloc(800,1);memset(fixture_fonts[0].pixels.address,255,800);
    }
    const char *text=!strcmp(mode,"fallback-style") ? "A|iB|pC" : "AB";
    font_drawing_globals.highlight_start_index=0;font_drawing_globals.highlight_stop_index=1;
    if(!strcmp(mode,"fallback-unicode")) rasterizer_draw_unicode_string(&bounds,&clip,&cursor,0,L"A\u65e5B");
    else rasterizer_draw_string(&bounds,&clip,&cursor,0,text);
    assert(begin_count==1 && end_count==1);
    if(!strcmp(mode,"original-wrapper")) {
        assert(original_draws==2 && !quad_count && !bitmap_allocations && !allocation_calls);
        assert(bound_bitmap==&original_bitmap);return;
    }
    if(!strncmp(mode,"fallback",8) && strcmp(mode,"fallback-no-reset")) {
        assert(original_draws>0 && !quad_count && bound_bitmap==&original_bitmap);
        assert(!batch_active);return;
    }
    assert(!original_draws && quad_count==4 && bound_bitmap==hires_text_atlas);
    assert(!batch_active && bitmap_allocations==1);
    pixel32 packed=(127UL<<24)|(51UL<<16)|(102UL<<8)|204UL;
    assert(quads[0][0].color==(packed&0xff000000UL));
    assert(quads[1][0].color==(packed^0xffffffUL));
    assert(quads[3][0].color==packed);
    for(int vertex=0;vertex<4;vertex++) {
        near_value(quads[0][vertex].position.x,quads[1][vertex].position.x+1);
        near_value(quads[0][vertex].position.y,quads[1][vertex].position.y+1);
        near_value(quads[0][vertex].texture_coordinates.x,quads[1][vertex].texture_coordinates.x);
    }
    assert(cursor.x==17 && cursor.y==12);
    if(!strcmp(mode,"clipping")) {
        quad_count=0;global_shadow_color=0x80203040;clip=(rectangle2d){3,3,9,7};
        rasterizer_draw_string(&bounds,&clip,NULL,0,"A");assert(quad_count==2);
        assert(quads[0][0].color==global_shadow_color);
        for(int v=0;v<4;v++) {
            assert(quads[1][v].position.x>=3 && quads[1][v].position.x<=7);
            assert(quads[1][v].position.y>=3 && quads[1][v].position.y<=9);
        }
        assert(quads[1][0].texture_coordinates.x>0 && quads[1][1].texture_coordinates.x>quads[1][0].texture_coordinates.x);
    } else if(!strcmp(mode,"transform")) {
        struct dynamic_screen_vertex before[4];memcpy(before,quads[1],sizeof(before));quad_count=0;
        rasterizer_text_transform.scale=.75f;rasterizer_text_transform.anchor_x=5;rasterizer_text_transform.anchor_y=8;
        rasterizer_draw_string(&bounds,&clip,NULL,0,"AB");assert(quad_count==4);
        for(int v=0;v<4;v++) {
            near_value(quads[1][v].position.x,5+(before[v].position.x-5)*.75f);
            near_value(quads[1][v].position.y,8+(before[v].position.y-8)*.75f);
        }
    } else if(!strcmp(mode,"segments")) {
        quad_count=0;fixture_characters[0]['/'].character_width=6;
        fixture_characters[0]['/'].bitmap_width=6;
        fixture_characters[0]['/'].bitmap_origin_x=0;
        font_drawing_globals.initial_indent=13;
        rasterizer_draw_string(&bounds,&clip,NULL,0,"/");assert(quad_count==2);
        assert(quads[1][0].position.x>=13);
        quad_count=0;font_drawing_globals.initial_indent=0;
        font_drawing_globals.tab_stop_count=2;font_drawing_globals.tab_stops[0]=13;font_drawing_globals.tab_stops[1]=21;
        rasterizer_draw_string(&bounds,&clip,NULL,0,"A\t/");assert(quad_count==4);
        for(int v=0;v<4;v++) assert(quads[3][v].position.x>=13 && quads[3][v].position.x<=21);
    } else if(!strcmp(mode,"fallback-no-reset")) {
        struct text_hires_atlas_pixels before,after;
        assert(text_hires_atlas_pixels(placeholder[1],&before));
        quad_count=0;rasterizer_draw_string(&bounds,&clip,NULL,0,"A|iB|pC");
        assert(original_draws==3 && !quad_count && bound_bitmap==&original_bitmap);
        assert(text_hires_atlas_pixels_since(placeholder[1],before.revision,&after));
        assert(after.revision==before.revision && after.dirty_top==2048 && after.dirty_bottom==0);
    } else if(!strcmp(mode,"styled")) {
        quad_count=0;rasterizer_draw_string(&bounds,&clip,&cursor,0,"A|bB|pC");
        assert(quad_count==6 && cursor.x==23 && bound_bitmap==hires_text_atlas);
    } else assert(!strcmp(mode,"wrapper"));
}
'''


GL_BOUNDARIES = r'''
typedef unsigned int GLuint,GLenum;
typedef int GLint,GLsizei;
#define GL_TEXTURE_2D 0x0de1
#define GL_TEXTURE_BASE_LEVEL 0x813c
#define GL_TEXTURE_MAX_LEVEL 0x813d
#define GL_RGBA8 0x8058
#define GL_RGBA 0x1908
#define GL_UNSIGNED_BYTE 0x1401
#define GL_UNPACK_ALIGNMENT 0x0cf5
static GLuint text_atlas_gl_texture,gl_bound,gl_next=1;
static uint64_t text_atlas_uploaded_revision;
static int gl_generations,gl_deletions,gl_allocations,gl_uploads,gl_invalidations;
static unsigned long gl_y,gl_rows;
static unsigned char *gl_pixels;
static void glGenTextures(GLsizei count,GLuint *texture) { assert(count==1);*texture=gl_next++;gl_generations++; }
static void glDeleteTextures(GLsizei count,const GLuint *texture) {
    assert(count==1 && *texture==gl_bound);free(gl_pixels);gl_pixels=NULL;gl_deletions++;
}
static void glBindTexture(GLenum target,GLuint texture) { assert(target==GL_TEXTURE_2D);gl_bound=texture; }
static void glTexParameteri(GLenum target,GLenum pname,GLint param) {
    assert(target==GL_TEXTURE_2D && (pname==GL_TEXTURE_BASE_LEVEL || pname==GL_TEXTURE_MAX_LEVEL) && param==0);
}
static void glTexImage2D(GLenum target,GLint level,GLint internal,GLsizei width,GLsizei height,
    GLint border,GLenum format,GLenum type,const void *pixels) {
    assert(target==GL_TEXTURE_2D && level==0 && internal==GL_RGBA8 && width==2048 && height==2048);
    assert(border==0 && format==GL_RGBA && type==GL_UNSIGNED_BYTE && !pixels);
    gl_pixels=calloc((size_t)width*height,4);assert(gl_pixels);gl_allocations++;
}
static void glPixelStorei(GLenum pname,GLint value) { assert(pname==GL_UNPACK_ALIGNMENT && value==1); }
static void glTexSubImage2D(GLenum target,GLint level,GLint x,GLint y,GLsizei width,GLsizei height,
    GLenum format,GLenum type,const void *pixels) {
    assert(target==GL_TEXTURE_2D && !level && !x && y>=0 && y+height<=2048 && width==2048);
    assert(format==GL_RGBA && type==GL_UNSIGNED_BYTE && pixels);
    memcpy(gl_pixels+(size_t)y*2048*4,pixels,(size_t)height*2048*4);
    gl_y=(unsigned long)y;gl_rows=(unsigned long)height;gl_uploads++;
}
static void xgpu_gl_state_invalidate(void) { gl_invalidations++; }
static void platform_log(const char *format,...) { (void)format; }
'''


GL_TESTS = r'''
static void gl_tests(const char *mode) {
    register_atlas();long font=text_hires_font("ui\\large_ui",12);
    struct text_hires_glyph glyph;struct text_hires_atlas_pixels pixels;
    assert(text_hires_batch_begin(0) && text_hires_glyph(font,'H',&glyph));text_hires_batch_end();
    assert(text_hires_atlas_pixels(placeholder[1],&pixels));
    assert(!text_atlas_texture(placeholder[1]+1));assert(!gl_generations);
    GLuint first=text_atlas_texture(placeholder[1]);assert(first && gl_generations==1 && gl_allocations==1 && gl_uploads==1);
    assert(gl_y==0 && gl_rows==2048 && !memcmp(gl_pixels,pixels.rgba,2048*2048*4));
    assert(text_atlas_texture(placeholder[1])==first && gl_uploads==1);
    assert(text_hires_batch_begin(0) && text_hires_glyph(font,'W',&glyph));text_hires_batch_end();
    assert(text_atlas_texture(placeholder[1])==first && gl_uploads==2);
    assert(gl_rows>0 && gl_rows<2048 && !memcmp(gl_pixels,pixels.rgba,2048*2048*4));
    if(!strcmp(mode,"gl-disposal")) {
        text_hires_dispose();assert(gl_deletions==1 && !text_atlas_gl_texture && !text_atlas_uploaded_revision);
        assert(!text_atlas_texture(placeholder[1]));assert(gl_generations==1);
        placeholder[1]+=4096;register_atlas();font=text_hires_font("ui\\large_ui",12);
        assert(text_hires_batch_begin(0) && text_hires_glyph(font,'A',&glyph));text_hires_batch_end();
        GLuint second=text_atlas_texture(placeholder[1]);assert(second && second!=first);
        assert(gl_generations==2 && gl_allocations==2 && gl_uploads==3 && gl_rows==2048);
        assert(text_hires_atlas_pixels(placeholder[1],&pixels));assert(!memcmp(gl_pixels,pixels.rgba,2048*2048*4));
        text_hires_dispose();assert(gl_deletions==2);
        text_hires_dispose();assert(gl_deletions==2);
    } else { assert(!strcmp(mode,"gl-rows"));text_hires_dispose();assert(gl_deletions==1); }
}
'''


def fixture_source():
    draw = (ROOT / "source/text/draw_string.c").read_text()
    raster = (ROOT / "source/rasterizer/rasterizer_text.c").read_text()
    international = (ROOT / "source/text/international_strings.c").read_text()
    language = (ROOT / "source/text/international_strings.h").read_text()
    styles = (ROOT / "source/text/text_group.h").read_text()
    source = CORE_PREFIX + ENGINE_PREFIX
    source += draw[draw.index("enum\n{", draw.index("/* ---------- constants */")):
                   draw.index("/* ---------- structures */")]
    source += declaration(styles, "enum\n{\n\t_text_style_plain") + "\n"
    source += declaration(language, "enum\n{\n\t_language_roman") + "\n"
    for name in ("font_drawing_globals", "font_character", "parse_string_state"):
        source += declaration(draw, "struct " + name + "\n") + "\n"
    source += ENGINE_BOUNDARIES
    for name in ("double_byte_character", "get_next_character", "character_in_pattern"):
        source += function(international, name) + "\n"
    for name in ("styled_font_get", "draw_string_get_font_index", "draw_string_get_character_clip", "parse_string_new", "parse_string",
                 "parse_unicode_string", "draw_string_partial", "draw_unicode_string_partial",
                 "draw_string", "draw_unicode_string", "draw_string_preflight", "draw_unicode_string_preflight"):
        source += function(draw, name) + "\n"
    for name in ("rasterizer_text_submit_character", "hires_text_font_get", "rasterizer_preflight_hires_character",
                 "hires_text_prepare", "rasterizer_draw_hires_character_quad", "rasterizer_draw_hires_character",
                 "rasterizer_draw_hires_character_with_dropshadow", "rasterizer_draw_string",
                 "rasterizer_draw_unicode_string"):
        source += function(raster, name) + "\n"
    source += ENGINE_TESTS
    source += GL_BOUNDARIES
    textures = (PORT / "xbox_textures.c").read_text()
    for name in ("text_atlas_dispose", "text_atlas_texture"):
        source += function(textures, name) + "\n"
    source += GL_TESTS
    source += r'''
int main(int argc,char **argv) {
    assert(argc>=2);
    if(!strcmp(argv[1],"dump")) {
        assert(argc==6);register_atlas();pixel_scale=(float)atof(argv[3]);
        long font=text_hires_font("ui\\large_ui",(float)atof(argv[4]));struct text_hires_glyph glyph;
        assert(font>=0 && text_hires_batch_begin(0) && text_hires_glyph(font,strtoul(argv[5],NULL,0),&glyph));
        struct text_hires_atlas_pixels pixels;assert(text_hires_atlas_pixels(placeholder[1],&pixels));
        FILE *f=fopen(argv[2],"wb");assert(f);assert(fwrite(pixels.rgba,1,pixels.width*pixels.height*4,f)==pixels.width*pixels.height*4);assert(!fclose(f));
        printf("{\"width\":%lu,\"height\":%lu,\"glyph\":[%g,%g,%g,%g,%g,%g,%g,%g,%g]}\n",
            pixels.width,pixels.height,glyph.left,glyph.top,glyph.right,glyph.bottom,glyph.u0,glyph.v0,glyph.u1,glyph.v1,glyph.advance);
    } else if(!strncmp(argv[1],"core-",5)) core_tests(argv[1]+5);
    else if(!strncmp(argv[1],"gl-",3)) gl_tests(argv[1]);
    else engine_tests(argv[1]);
    return 0;
}
'''
    return source


def build_fixture(directory):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    source, embedded = folder / "text-fixture.c", folder / "fonts.c"
    source.write_text(fixture_source())
    embedded.write_text(embedded_fonts())
    executable = folder / ("text-fixture.exe" if sys.platform == "win32" else "text-fixture")
    command = ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
               "-Wno-unused-function", "-Wno-unused-parameter", "-Wno-unused-but-set-variable",
               "-Wno-logical-op-parentheses", "-Wno-sign-compare", "-I", str(PORT), str(source), str(embedded), "-o", str(executable)]
    if sys.platform == "win32":
        # The fixture's bounded dump uses the standard portable C API. Keep
        # warnings fatal without treating Windows' fopen_s preference as one.
        command += ["-D_CRT_SECURE_NO_WARNINGS"]
    else:
        command += ["-lm"]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return executable


def real_glyph(directory, scale=2, cap_height=12, code=ord("H")):
    """Reusable committed-font RGBA/reference fixture for renderer GPU checks."""
    executable = build_fixture(directory)
    output = Path(directory) / "glyph.rgba"
    result = subprocess.run([str(executable), "dump", str(output), str(scale), str(cap_height), str(code)],
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout), output.read_bytes()


@unittest.skipUnless(shutil.which("clang"), "clang required")
class TextHiresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-text-")
        cls.executable = build_fixture(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, mode):
        result = subprocess.run([str(self.executable), mode], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, mode + "\n" + result.stdout + result.stderr)

    def test_original_has_no_atlas_allocation(self):
        self.run_case("core-original")
        self.run_case("original-wrapper")

    def test_rgba_coverage_and_clear_padding(self):
        self.run_case("core-rgba")

    def test_cap_height_scales_without_changing_advance(self):
        self.run_case("core-scale")

    def test_each_renderer_gets_its_own_dirty_rows(self):
        self.run_case("core-dirty")

    def test_unknown_glyphs_fonts_and_invalid_scales(self):
        self.run_case("core-invalid")

    def test_allocation_failure_is_recoverable(self):
        self.run_case("core-allocation")

    def test_full_atlas_never_replaces_pending_glyph_uvs(self):
        self.run_case("core-capacity")

    def test_dispose_keeps_revisions_monotonic(self):
        self.run_case("core-dispose")

    def test_preflight_retains_styles_highlights_and_layout(self):
        self.run_case("preflight")

    def test_original_layout_colors_and_shadow(self):
        self.run_case("wrapper")

    def test_styles_resolve_their_actual_font_tags(self):
        self.run_case("styled")

    def test_unsupported_font_and_glyph_fall_back_for_whole_string(self):
        for mode in ("fallback-font", "fallback-style", "fallback-unicode", "fallback-capacity"):
            with self.subTest(mode=mode):
                self.run_case(mode)

    def test_clipping_and_shadow_color(self):
        self.run_case("clipping")

    def test_existing_scaled_text_transform_is_preserved(self):
        self.run_case("transform")

    def test_parser_tab_and_paragraph_clips_are_preserved(self):
        self.run_case("segments")

    def test_unsupported_string_does_not_clear_existing_atlas(self):
        self.run_case("fallback-no-reset")

    def test_gl_adapter_uploads_only_changed_rows(self):
        self.run_case("gl-rows")

    def test_gl_adapter_recreates_texture_after_map_disposal(self):
        self.run_case("gl-disposal")

    def test_real_glyph_gpu_controls_have_transparent_ink_and_filtered_edges(self):
        try:
            from .text_glyph_fixtures import real_text_fixtures
        except ImportError:
            from text_glyph_fixtures import real_text_fixtures
        cases = list(real_text_fixtures(Path(self.directory.name) / "gpu-controls"))
        self.assertEqual(len(cases), 24)
        self.assertEqual(len({f["name"] for _, f in cases}), 24)
        self.assertEqual({f["real_glyph"] for _, f in cases},
                         {"transparent", "opaque", "antialias", "filtered"})
        self.assertTrue(all(key.coverage_alpha == 0 for key, _ in cases))
        self.assertTrue(all(f["coverage"] == 0 for _, f in cases if f["real_glyph"] == "transparent"))
        self.assertTrue(all(f["coverage"] == 1 for _, f in cases if f["real_glyph"] == "opaque"))
        self.assertTrue(all(0 < f["coverage"] < 1 for _, f in cases if f["real_glyph"] in ("antialias", "filtered")))


if __name__ == "__main__":
    unittest.main()
