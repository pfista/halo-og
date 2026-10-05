"""CPU execution of the production indexed-buffer frontend with a mock GPU queue.

The C functions are extracted unchanged from d3d8_metal.c. Allocation and native
transport are mocked; command layouts come from the real Metal ABI. These tests
prove frontend ownership/order/copy extents, not GPU or physical Xbox parity.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/d3d8_metal.c"


def function(source, name):
    """Read one complete C definition, ignoring braces in strings/comments."""
    import re
    match = re.search(r"(?m)^[^\n;{}]*\b" + re.escape(name) + r"\s*\(", source)
    if not match:
        raise AssertionError(f"Production function {name} is missing")
    opening = source.find("{", match.start())
    if opening < 0 or ";" in source[match.start():opening]:
        raise AssertionError(f"Production definition {name} is missing")
    depth, state, index = 0, "code", opening
    while index < len(source):
        char = source[index]
        following = source[index:index + 2]
        if state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if following == "*/":
                state = "code"
                index += 1
        elif state in ('"', "'"):
            if char == "\\":
                index += 1
            elif char == state:
                state = "code"
        elif following == "//":
            state = "line"
            index += 1
        elif following == "/*":
            state = "block"
            index += 1
        elif char in ('"', "'"):
            state = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if not depth:
                return source[match.start():index + 1]
        index += 1
    raise AssertionError(f"Unterminated production function {name}")


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include "port/macos/include/halo_metal_abi.h"
#define WINAPI
#define TRUE 1
#define FALSE 0
#define S_OK 0
#define E_FAIL (-9)
#define SCREEN_HEIGHT 480
#define SCREEN_MAXIMUM_WIDTH 1920
#define D3DMULTISAMPLE_NONE 0x11
#define D3DBACKBUFFER_TYPE_MONO 0
#define D3DSWAPEFFECT_DISCARD 1
#define D3DCOMMON_D3DCREATED 0x01000000u
#define D3DCOMMON_REFCOUNT_MASK 0xffffu
typedef uint32_t DWORD, UINT, ULONG;
typedef int BOOL, INT, HRESULT, D3DDEVTYPE, D3DFORMAT, D3DBACKBUFFER_TYPE;
typedef struct { uint32_t Common, Data, Lock, Format, Size; } D3DSurface;
typedef D3DSurface D3DBaseTexture;
typedef D3DSurface D3DPalette;
typedef struct { int unused; } D3DDevice;
typedef struct { int left, top, right, bottom; } RECT;
typedef struct { UINT BackBufferWidth, BackBufferHeight, BackBufferCount;
    int BackBufferFormat, SwapEffect; DWORD MultiSampleType; } D3DPRESENT_PARAMETERS;
typedef struct { float _11,_12,_13,_14,_21,_22,_23,_24,_31,_32,_33,_34,_41,_42,_43,_44; } D3DMATRIX;
typedef struct { UINT X,Y,Width,Height; float MinZ,MaxZ; } D3DVIEWPORT8;
enum { D3DFMT_LIN_A8R8G8B8=1, D3DFMT_LIN_D24S8=2,
    D3DFMT_D24S8=3,D3DFMT_F24S8=4,D3DFMT_D16=5,D3DFMT_F16=6,
    D3DFMT_LIN_F24S8=7,D3DFMT_LIN_D16=8,D3DFMT_LIN_F16=9,D3DTS_MAX=3,
    D3DRS_ZENABLE=0,D3DRS_ZWRITEENABLE,D3DRS_ZFUNC,D3DRS_COLORWRITEENABLE,
    D3DRS_SRCBLEND,D3DRS_DESTBLEND,D3DRS_BLENDOP,D3DRS_CULLMODE,D3DRS_FRONTFACE,
    D3DRS_FILLMODE,D3DRS_ALPHAFUNC,D3DRS_STENCILFUNC,D3DRS_STENCILMASK,
    D3DRS_STENCILWRITEMASK,D3DRS_STENCILFAIL,D3DRS_STENCILZFAIL,D3DRS_STENCILPASS,
    D3DRS_MAX=32,D3DCMP_LESSEQUAL=1,D3DCMP_ALWAYS=2,D3DCOLORWRITEENABLE_ALL=15,
    D3DBLEND_ONE=1,D3DBLEND_ZERO=0,D3DBLENDOP_ADD=1,D3DCULL_CCW=1,
    D3DFRONT_CW=1,D3DFILL_SOLID=1,D3DSTENCILOP_KEEP=1,D3DTSS_MAXSTAGES=4,
    D3DTSS_ADDRESSU=0,D3DTSS_ADDRESSV,D3DTSS_ADDRESSW,D3DTSS_MAGFILTER,
    D3DTSS_MINFILTER,D3DTSS_MAXANISOTROPY,D3DTSS_MAX=8,
    D3DTADDRESS_WRAP=1,D3DTEXF_POINT=1 };
struct xgpu_texture_description { unsigned long width,height,depth,levels;
    DWORD format; BOOL cube_map,linear; };
struct native_resource { struct native_resource *next; struct halo_metal_ref ref;
    DWORD data,format_word,size_word; struct xgpu_texture_description description;
    unsigned long generation,palette_hash; uint64_t last_rendered; uint32_t format,usage;
    BOOL mip_composite,volume; };
static struct { D3DPRESENT_PARAMETERS presentation;
    D3DSurface back_buffer,history_buffer,depth_buffer;
    D3DSurface *render_target,*depth_stencil; D3DVIEWPORT8 viewport;
    D3DMATRIX transforms[D3DTS_MAX]; BOOL ready,created;
    unsigned long next_vertex_shader_id,frame,draws; uint64_t resource_serial; } device;
static struct { struct halo_metal_reply reply; } transport;
static struct native_resource *resources;
static DWORD D3D__RenderState[D3DRS_MAX],D3D__TextureState[D3DTSS_MAXSTAGES][D3DTSS_MAX];
static uint32_t next_resource_id=1,next_program_id=1;
static uint64_t submitted_batches,submitted_commands,submitted_bytes,submit_wall_ns;
static uint64_t statistics_batches,statistics_commands,statistics_bytes,statistics_wall_ns;
static uint32_t largest_statistics_batch;
static long screen_width;
static float screen_scale[2]={1,1};
static unsigned flip_count,pending_flips;
static int vertical_blank_lock,vertical_blank_condition;
static unsigned allocations,viewport_updates,video_calls;
static long requested_width=640;
static long screenshot_every;
static const char *screenshot_directory="";
static int vsync;
static jmp_buf failure_jump;
static int failure_expected,failure_status;
static _Noreturn void native_fail(const char *operation,int status) {
    failure_status=status;
    if (failure_expected) longjmp(failure_jump,1);
    fprintf(stderr,"Unexpected failure: %s (%d)\n",operation,status); abort();
}
static void require_status(const char *operation,int status) { if(status) native_fail(operation,status); }
static void platform_log(const char *format,...) { (void)format; }
static D3DDevice *device_pointer(void) { return (D3DDevice *)&device; }
static void viewport_update_constants(void) { viewport_updates++; }
static int platform_video_initialize(unsigned long w,unsigned long h) { assert(w && h); video_calls++; return 1; }
static void native_initialize(void) { device.ready=TRUE; transport.reply.capabilities=HALO_METAL_CAP_COPY_SUBRESOURCE; }
static int config_boolean(const char *key) { return !strcmp(key,"display.vsync") ? vsync:0; }
static long config_integer(const char *key) { return !strcmp(key,"debug.screenshot_every") ? screenshot_every:0; }
static const char *config_string(const char *key) { assert(!strcmp(key,"debug.screenshot_directory")); return screenshot_directory; }
static void platform_pump_events(void) {}
static void vertical_blank_start(void) {}
static int halo_interpolation_enabled(void) { return 1; }
static int pthread_mutex_lock(int *p) { (void)p; return 0; }
static int pthread_mutex_unlock(int *p) { (void)p; return 0; }
static int pthread_cond_wait(int *p,int *q) { (void)p;(void)q;assert(0);return 0; }
static long halo_screen_width(void) { return screen_width ? screen_width:640; }
static void screen_mode_choose(long *width,float scale[2]) { *width=requested_width;scale[0]=scale[1]=1; }
static void d3d8_surface_resize(D3DSurface *s,D3DFORMAT f,unsigned long w,unsigned long h) {
    assert(w && h && w<=SCREEN_MAXIMUM_WIDTH && h<=SCREEN_HEIGHT);
    s->Format=(DWORD)f; s->Size=(DWORD)(h<<16)| (DWORD)w;
}
static void d3d8_surface_initialize(D3DSurface *s,D3DFORMAT f,unsigned long w,unsigned long h) {
    memset(s,0,sizeof(*s));s->Common=0x00010001u;s->Data=++allocations*4096;
    d3d8_surface_resize(s,f,w,h);
}
static void xgpu_texture_describe(DWORD format,DWORD size,struct xgpu_texture_description *out) {
    memset(out,0,sizeof(*out));out->width=size&0xffffu;out->height=size>>16;
    out->depth=out->levels=1;out->format=format;
}
struct target_record { struct native_resource native; uint32_t *pixels; };
static struct target_record targets[32];
static unsigned target_count;
enum { FLUSH_EVENT=100,READBACK_EVENT=101,MOCK_WRITE=1000 };
struct event { unsigned kind,size; unsigned char command[96]; };
static struct event events[2048];
static unsigned event_count,applied_event,copy_count,present_count,readback_count;
static struct target_record *record(struct halo_metal_ref ref) {
    for(unsigned i=0;i<target_count;i++) if(targets[i].native.ref.id==ref.id && targets[i].native.ref.generation==ref.generation) return &targets[i];
    assert(0);return NULL;
}
static void packet_begin(uint32_t bytes,const void *payload,unsigned size) { assert(bytes<=96 && !payload && !size); }
static void command_append(const void *command,uint32_t size) {
    assert(event_count<2048 && size<=96);struct event *e=&events[event_count++];
    e->kind=((const struct halo_metal_command *)command)->opcode;e->size=size;memcpy(e->command,command,size);
}
static void packet_finish(void) {}
static void packet_flush(void) {
    while(applied_event<event_count) {
        struct event *e=&events[applied_event++];
        if(e->kind==HALO_METAL_COPY_SUBRESOURCE) {
            struct halo_metal_copy_subresource c;memcpy(&c,e->command,sizeof(c));
            struct target_record *s=record(c.source),*d=record(c.destination);
            assert(s!=d && c.planes==HALO_METAL_COLOR && !c.reserved);
            assert(!c.source_mip && !c.destination_mip && !c.source_slice && !c.destination_slice);
            assert(c.source_x+c.width<=s->native.description.width && c.source_y+c.height<=s->native.description.height);
            assert(c.destination_x+c.width<=d->native.description.width && c.destination_y+c.height<=d->native.description.height);
            for(unsigned y=0;y<c.height;y++) memcpy(d->pixels+(y+c.destination_y)*d->native.description.width+c.destination_x,
                s->pixels+(y+c.source_y)*s->native.description.width+c.source_x,c.width*sizeof(uint32_t));
            copy_count++;
        } else if(e->kind==HALO_METAL_CLEAR) {
            struct halo_metal_clear c;memcpy(&c,e->command,sizeof(c));assert(c.planes==HALO_METAL_COLOR);
            struct target_record *d=record(c.color);
            assert(!c.x && !c.y && c.width==d->native.description.width && c.height==d->native.description.height);
            assert(c.rgba[0]==0 && c.rgba[1]==0 && c.rgba[2]==0 && c.rgba[3]==0);
            memset(d->pixels,0,c.width*c.height*sizeof(uint32_t));
        } else if(e->kind==HALO_METAL_PRESENT_SCALED) {
            struct halo_metal_present_scaled c;memcpy(&c,e->command,sizeof(c));
            assert(record(c.source)->native.data==device.back_buffer.Data);assert(!c.reserved);
            assert(c.display_flags==(vsync ? HALO_METAL_DISPLAY_VSYNC:0));present_count++;
        } else if(e->kind==MOCK_WRITE) {
            uint32_t id,seed;memcpy(&id,e->command+8,4);memcpy(&seed,e->command+12,4);
            struct target_record *d=record((struct halo_metal_ref){id,1});
            for(unsigned y=0;y<d->native.description.height;y++) for(unsigned x=0;x<d->native.description.width;x++)
                d->pixels[y*d->native.description.width+x]=0xff000000u|(seed<<20)|(y<<10)|x;
        }
    }
    assert(event_count<2048);events[event_count++].kind=FLUSH_EVENT;applied_event=event_count;
}
static struct native_resource *target_get(const D3DSurface *surface) {
    assert(surface && surface->Data);
    for(unsigned i=0;i<target_count;i++) if(targets[i].native.data==surface->Data && targets[i].native.format_word==surface->Format && targets[i].native.size_word==surface->Size) return &targets[i].native;
    assert(target_count<32);struct target_record *entry=&targets[target_count++];
    entry->native.ref=(struct halo_metal_ref){next_resource_id++,1};entry->native.data=surface->Data;
    entry->native.format_word=surface->Format;entry->native.size_word=surface->Size;
    xgpu_texture_describe(surface->Format,surface->Size,&entry->native.description);
    entry->native.format=HALO_METAL_BGRA8;entry->native.usage=HALO_METAL_SHADER_READ|HALO_METAL_RENDER_TARGET;
    entry->pixels=malloc(entry->native.description.width*entry->native.description.height*sizeof(uint32_t));assert(entry->pixels);
    memset(entry->pixels,0x99,entry->native.description.width*entry->native.description.height*sizeof(uint32_t));
    entry->native.next=resources;resources=&entry->native;
    struct halo_metal_clear c={0};c.command.opcode=HALO_METAL_CLEAR;c.color=entry->native.ref;c.planes=HALO_METAL_COLOR;
    c.width=entry->native.description.width;c.height=entry->native.description.height;
    packet_begin(sizeof(c),NULL,0);command_append(&c,sizeof(c));packet_finish();return &entry->native;
}
static int halo_metal_guest_readback(void *t,struct halo_metal_ref ref,uint32_t plane,void *out,uint32_t bytes) {
    assert(t==&transport && plane==HALO_METAL_COLOR);struct target_record *r=record(ref);
    assert(bytes==r->native.description.width*r->native.description.height*4);
    memcpy(out,r->pixels,bytes);events[event_count++].kind=READBACK_EVENT;readback_count++;return 0;
}
static struct native_resource *rendered_mip_composite(DWORD data,const struct xgpu_texture_description *description) {
    (void)data;(void)description;assert(0);return NULL;
}
/* PRODUCTION */
static D3DPRESENT_PARAMETERS presentation(unsigned width) {
    D3DPRESENT_PARAMETERS p={0};p.BackBufferWidth=width;p.BackBufferHeight=480;p.SwapEffect=D3DSWAPEFFECT_DISCARD;return p;
}
static void create(unsigned width) {
    D3DPRESENT_PARAMETERS p=presentation(width);D3DDevice *out=NULL;
    assert(Direct3D_CreateDevice(0,0,NULL,0,&p,&out)==S_OK && out==device_pointer());
}
static uint32_t pattern(unsigned x,unsigned y,unsigned seed) { return 0xff000000u | (seed<<20) | (y<<10) | x; }
static void fill(struct native_resource *resource,unsigned seed) {
    struct target_record *r=record(resource->ref);
    for(unsigned y=0;y<r->native.description.height;y++) for(unsigned x=0;x<r->native.description.width;x++) r->pixels[y*r->native.description.width+x]=pattern(x,y,seed);
}
static void assert_pattern(struct native_resource *resource,unsigned overlap,unsigned seed) {
    struct target_record *r=record(resource->ref);
    for(unsigned y=0;y<r->native.description.height;y++) for(unsigned x=0;x<r->native.description.width;x++)
        assert(r->pixels[y*r->native.description.width+x]==(x<overlap ? pattern(x,y,seed):0));
}
static void expect_get_failure(INT index,D3DBACKBUFFER_TYPE type,D3DSurface **out,int status) {
    failure_expected=1;if(!setjmp(failure_jump)) { D3DDevice_GetBackBuffer(index,type,out);assert(0); }
    failure_expected=0;assert(failure_status==status);
}
static void test_create(void) {
    D3DPRESENT_PARAMETERS p=presentation(0);assert(backbuffer_presentation_supported(&p));
    assert(!backbuffer_presentation_supported(NULL));
    for(unsigned mode=0;mode<5;mode++) {
        D3DPRESENT_PARAMETERS invalid=p;D3DDevice *out=(D3DDevice *)(uintptr_t)123;
        if(mode==0) invalid.BackBufferCount=1;
        else if(mode==1) invalid.SwapEffect=2;
        else if(mode==2) invalid.SwapEffect=3;
        else if(mode==3) invalid.MultiSampleType=2;
        else invalid.BackBufferCount=UINT32_MAX;
        assert(!backbuffer_presentation_supported(&invalid));
        assert(Direct3D_CreateDevice(0,0,NULL,0,&invalid,&out)==E_FAIL);
        assert(!device.created && !allocations && out==(D3DDevice *)(uintptr_t)123);
    }
    p.MultiSampleType=D3DMULTISAMPLE_NONE;assert(backbuffer_presentation_supported(&p));
    create(0);assert(allocations==3 && video_calls==1 && viewport_updates==1);
    assert(device.back_buffer.Data && device.history_buffer.Data && device.depth_buffer.Data);
    assert(device.back_buffer.Data!=device.history_buffer.Data && device.back_buffer.Data!=device.depth_buffer.Data && device.history_buffer.Data!=device.depth_buffer.Data);
    assert(!(device.back_buffer.Common&D3DCOMMON_D3DCREATED) && !(device.history_buffer.Common&D3DCOMMON_D3DCREATED));
    assert((device.back_buffer.Common&D3DCOMMON_REFCOUNT_MASK)==1 && (device.history_buffer.Common&D3DCOMMON_REFCOUNT_MASK)==1);
    assert(device.back_buffer.Size==((480u<<16)|640u) && device.history_buffer.Size==device.back_buffer.Size);
    assert(device.render_target==&device.back_buffer && device.depth_stencil==&device.depth_buffer);
    assert(device.viewport.Width==640 && device.viewport.Height==480 && device.viewport.MaxZ==1);
    DWORD data=device.back_buffer.Data;create(960);assert(allocations==3 && device.back_buffer.Data==data);
}
static void test_get(void) {
    create(640);D3DSurface *zero=NULL,*minus=NULL;
    DWORD z=device.back_buffer.Common,h=device.history_buffer.Common;
    D3DDevice_GetBackBuffer(0,0,&zero);D3DDevice_GetBackBuffer(-1,0,&minus);
    assert(zero==&device.back_buffer && minus==&device.history_buffer && zero!=minus);
    assert(zero->Common==z+1 && minus->Common==h+1);
    DWORD stable_z=zero->Common,stable_h=minus->Common;D3DSurface *sentinel=zero;
    expect_get_failure(1,0,&sentinel,HALO_METAL_UNSUPPORTED);
    expect_get_failure(-2,0,&sentinel,HALO_METAL_UNSUPPORTED);
    expect_get_failure(INT32_MIN,0,&sentinel,HALO_METAL_UNSUPPORTED);
    expect_get_failure(0,1,&sentinel,HALO_METAL_UNSUPPORTED);
    expect_get_failure(-1,UINT32_MAX,&sentinel,HALO_METAL_UNSUPPORTED);
    expect_get_failure(0,0,NULL,HALO_METAL_INVALID);
    assert(sentinel==zero && zero->Common==stable_z && minus->Common==stable_h && !event_count);
}
static void test_present(void) {
    create(960);DWORD zero=device.back_buffer.Data,history=device.history_buffer.Data;
    struct native_resource *back=target_get(&device.back_buffer);packet_flush();fill(back,1);
    uint64_t serial=0;
    for(unsigned iteration=0;iteration<3;iteration++) {
        unsigned start=event_count;vsync=iteration&1;
        D3DDevice_Present(NULL,NULL,NULL,NULL);
        struct native_resource *past=target_get(&device.history_buffer);
        assert_pattern(past,960,1);
        assert(past->last_rendered>serial);serial=past->last_rendered;
        unsigned copy=UINT32_MAX,present=UINT32_MAX;
        for(unsigned i=start;i<event_count;i++) {
            if(events[i].kind==HALO_METAL_COPY_SUBRESOURCE) { assert(copy==UINT32_MAX);copy=i;
                struct halo_metal_copy_subresource c;memcpy(&c,events[i].command,sizeof(c));
                assert(c.source.id==back->ref.id && c.destination.id==past->ref.id && c.width==960 && c.height==480);
                assert(!c.source_x && !c.source_y && !c.destination_x && !c.destination_y);
            }
            if(events[i].kind==HALO_METAL_PRESENT_SCALED) { assert(present==UINT32_MAX);present=i; }
        }
        assert(copy!=UINT32_MAX && copy<present && events[event_count-1].kind==FLUSH_EVENT);
        assert(copy_count==iteration+1 && present_count==iteration+1 && device.frame==iteration+1);
        assert(device.back_buffer.Data==zero && device.history_buffer.Data==history);
    }
    device.ready=FALSE;unsigned before=event_count;D3DDevice_Present(NULL,NULL,NULL,NULL);assert(event_count==before && copy_count==3);
}
static void test_copy(void) {
    create(960);struct native_resource *back=target_get(&device.back_buffer),*past=target_get(&device.history_buffer);
    packet_flush();fill(back,2);backbuffer_color_copy(back,past,640,480);packet_flush();
    assert_pattern(past,640,2);assert(past->last_rendered==1 && device.resource_serial==1 && copy_count==1);
    struct halo_metal_copy_subresource c;int found=0;
    for(unsigned i=0;i<event_count;i++) if(events[i].kind==HALO_METAL_COPY_SUBRESOURCE) { memcpy(&c,events[i].command,sizeof(c));found++; }
    assert(found==1 && c.command.opcode==20 && c.planes==HALO_METAL_COLOR && !c.reserved);
    assert(!c.source_mip && !c.destination_mip && !c.source_slice && !c.destination_slice);
    assert(!c.source_x && !c.source_y && !c.destination_x && !c.destination_y && c.width==640 && c.height==480);
    transport.reply.capabilities=0;unsigned before=event_count;uint64_t serial=past->last_rendered;
    failure_expected=1;if(!setjmp(failure_jump)) { backbuffer_color_copy(back,past,640,480);assert(0); }
    failure_expected=0;assert(failure_status==HALO_METAL_UNSUPPORTED && event_count==before && past->last_rendered==serial);
    transport.reply.capabilities=HALO_METAL_CAP_COPY_SUBRESOURCE;
    for(unsigned invalid=0;invalid<7;invalid++) {
        struct native_resource *s=back,*d=past;uint32_t width=640,height=480;
        if(invalid==0) s=NULL;
        else if(invalid==1) d=NULL;
        else if(invalid==2) d=back;
        else if(invalid==3) width=0;
        else if(invalid==4) width=961;
        else if(invalid==5) height=481;
        else d->format=HALO_METAL_RGBA8;
        failure_expected=1;if(!setjmp(failure_jump)) { backbuffer_color_copy(s,d,width,height);assert(0); }
        failure_expected=0;assert(failure_status==HALO_METAL_INVALID && event_count==before && past->last_rendered==serial);
        past->format=HALO_METAL_BGRA8;
    }
}
static void test_first_history_use(void) {
    create(640);struct native_resource *back=target_get(&device.back_buffer);packet_flush();fill(back,7);
    unsigned count=target_count;D3DBaseTexture alias=device.history_buffer;
    struct native_resource *past=texture_get(&alias,NULL,0);packet_flush();
    assert(target_count==count+1 && past->ref.id!=back->ref.id && past->data==device.history_buffer.Data);
    assert(!past->last_rendered && !device.resource_serial && !copy_count && !present_count);
    struct target_record *r=record(past->ref);for(unsigned p=0;p<640*480;p++) assert(!r->pixels[p]);
    fill(back,8);unsigned before=event_count;assert(texture_get(&alias,NULL,3)==past && event_count==before);
    for(unsigned p=0;p<640*480;p++) assert(!r->pixels[p]);
    assert(!past->last_rendered && !device.resource_serial && !copy_count && !present_count);
}
static void test_snapshot(const char *directory) {
    create(640);struct native_resource *back=target_get(&device.back_buffer);packet_flush();fill(back,3);
    D3DDevice_Present(NULL,NULL,NULL,NULL);struct native_resource *past=target_get(&device.history_buffer);
    uint64_t serial=past->last_rendered;unsigned copies=copy_count,presents=present_count;DWORD zero=device.back_buffer.Data;
    fill(back,4);screenshot_directory=directory;write_screenshot(back);
    assert(readback_count==1 && copy_count==copies && present_count==presents && past->last_rendered==serial && device.back_buffer.Data==zero);
    assert_pattern(past,640,3);
    char path[1024];snprintf(path,sizeof(path),"%s/frame00001.bmp",directory);FILE *f=fopen(path,"rb");assert(f);
    unsigned char header[54];assert(fread(header,1,54,f)==54 && header[0]=='B' && header[1]=='M');
    uint32_t pixel;assert(fread(&pixel,1,4,f)==4 && pixel==pattern(0,0,4));fclose(f);
    screenshot_every=1;D3DDevice_Present(NULL,NULL,NULL,NULL);
    assert(readback_count==2 && copy_count==copies+1 && present_count==presents+1);assert_pattern(past,640,4);
}
static void test_resize(void) {
    create(640);screen_width=640;DWORD zero=device.back_buffer.Data,history=device.history_buffer.Data;
    D3DBaseTexture aliases[2]={{0},{0}};aliases[0].Data=aliases[1].Data=zero;
    struct native_resource *back=target_get(&device.back_buffer);packet_flush();fill(back,5);D3DDevice_Present(NULL,NULL,NULL,NULL);
    struct native_resource *old_history=target_get(&device.history_buffer);
    uint64_t serial=old_history->last_rendered;
    struct { struct halo_metal_command command;uint32_t resource,seed; } pending={{MOCK_WRITE,16},old_history->ref.id,6};
    command_append(&pending,sizeof(pending)); /* Simulate an already queued original history write. */
    for(unsigned i=0;i<3;i++) {
        requested_width=i==1 ? 640:960;unsigned start=event_count;assert(halo_screen_commit()==requested_width);packet_flush();
        struct native_resource *past=target_get(&device.history_buffer);assert_pattern(past,640,6);
        assert(past->last_rendered==serial+2 && rendered_alias(history)==past);serial=past->last_rendered;
        assert(device.back_buffer.Data==zero && device.history_buffer.Data==history && allocations==3);
        assert(aliases[0].Data==zero && aliases[1].Data==zero && device.history_buffer.Size==device.back_buffer.Size);
        unsigned clears=0,copies=0,clear_at=0,copy_at=0;
        for(unsigned n=start;n<event_count;n++) {
            if(events[n].kind==HALO_METAL_CLEAR) { struct halo_metal_clear c;memcpy(&c,events[n].command,sizeof(c));
                if(c.color.id==past->ref.id) { clears++;clear_at=n; }
            }
            if(events[n].kind==HALO_METAL_COPY_SUBRESOURCE) { struct halo_metal_copy_subresource c;memcpy(&c,events[n].command,sizeof(c));
                assert(c.destination.id==past->ref.id && c.width==640 && c.height==480);copies++;copy_at=n;
            }
        }
        assert(clears>=1 && copies==1 && clear_at<copy_at);
        if(i==0) { /* Dirty cached 960-wide storage must not leak on later regrowth. */
            struct target_record *r=record(past->ref);for(unsigned y=0;y<480;y++) for(unsigned x=640;x<960;x++) r->pixels[y*960+x]=0xabcdef01;
        }
    }
    unsigned before=event_count;assert(halo_screen_commit()==960);assert(event_count==before);
}
int main(int argc,char **argv) {
    assert(argc>=2);
    if(!strcmp(argv[1],"create")) test_create();
    else if(!strcmp(argv[1],"get")) test_get();
    else if(!strcmp(argv[1],"present")) test_present();
    else if(!strcmp(argv[1],"copy")) test_copy();
    else if(!strcmp(argv[1],"first_history_use")) test_first_history_use();
    else if(!strcmp(argv[1],"snapshot")) { assert(argc==3);test_snapshot(argv[2]); }
    else if(!strcmp(argv[1],"resize")) test_resize();
    else assert(0);
    for(unsigned i=0;i<target_count;i++) free(targets[i].pixels);
    printf("%s: production frontend CPU checks passed\n",argv[1]);return 0;
}
'''


class BackbufferHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-metal-history-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        source = SOURCE.read_text()
        names = ("surface_dimensions", "backbuffer_presentation_supported", "backbuffer_surfaces_initialize",
                 "Direct3D_CreateDevice", "D3DDevice_GetBackBuffer", "rendered_serial_next",
                 "backbuffer_color_copy", "backbuffer_history_advance", "backbuffer_surfaces_resize",
                 "write_screenshot", "D3DDevice_Present", "halo_screen_commit", "rendered_alias")
        production = "\n\n".join(function(source, name) for name in names)
        # Compile the actual rendered-history route. The authored-texture path
        # is outside this harness; reaching it fails instead of supplying a mock
        # return that could conceal a missing history resolution branch.
        texture = function(source, "texture_get").split("    for (entry=resources;entry;entry=entry->next)", 1)[0]
        production += "\n\n" + texture + '\n    (void)palette;(void)stage;native_fail("unexpected authored texture path",HALO_METAL_INVALID);\n}\n'
        probe = cls.directory / "history.c"
        probe.write_text(HARNESS.replace("/* PRODUCTION */", production))
        cls.executable = cls.directory / "history"
        compiled = subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                   "-I", str(ROOT), str(probe), "-o", str(cls.executable)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.executable), name, *([str(self.directory)] if name == "snapshot" else [])],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("production frontend CPU checks passed", result.stdout)

    def test_original_presentation_modes_and_distinct_owned_storage(self):
        self.run_case("create")

    def test_index_refcounts_and_unsupported_requests_fail_closed(self):
        self.run_case("get")

    def test_every_present_copies_before_display_and_flush(self):
        self.run_case("present")

    def test_real_op20_extents_serial_and_required_capability(self):
        self.run_case("copy")

    def test_actual_screenshot_readback_does_not_advance_history(self):
        self.run_case("snapshot")

    def test_original_texture_alias_resolves_history_before_first_present(self):
        self.run_case("first_history_use")

    def test_resize_overlap_zero_regrowth_and_stable_aliases(self):
        self.run_case("resize")


if __name__ == "__main__":
    unittest.main()
