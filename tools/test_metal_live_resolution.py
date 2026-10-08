"""Execute production live-resolution transitions with a synchronous CPU GPU queue.

The frontend helpers and Present are extracted unchanged. The real Xbox header
decoder and render-scale planner run; transport commands operate on mock pixels.
The rendered-texture route is extracted through its early return, with authored
CPU fallback rejected. This verifies ownership, pixels and ordering, not Metal
execution, performance or retail Xbox parity.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import function
from tools.test_xgpu_texture_copy import harness_prefix

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/d3d8_metal.c"

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <pthread.h>
#include "port/linux/src/metal_render_scale.h"
#include "port/linux/src/metal_mip_composite.h"
#include "port/linux/src/xbox_textures.c"
/* FORMAT ENUM */
#define WINAPI
#define SCREEN_HEIGHT 480
typedef uint32_t UINT;
typedef struct { DWORD Common,Data,Lock,Format,Size; } D3DSurface;
typedef D3DSurface D3DBaseTexture;
typedef D3DSurface D3DPalette;
typedef struct { int left,top,right,bottom; } RECT;
typedef struct { UINT X,Y,Width,Height;float MinZ,MaxZ; } D3DVIEWPORT8;
/* RESOURCE */
/* FLUSH REASONS */
static struct {
    D3DSurface back_buffer,history_buffer,depth_buffer;
    D3DSurface *render_target,*depth_stencil;
    D3DVIEWPORT8 viewport;
    BOOL ready,created,immediate_active,visibility_test_active;
    uint64_t resource_serial;
    unsigned long frame,draws;
    struct halo_metal_ref query_slots[8];
    UINT query_results[8];BOOL query_pending[8];
    float constants[8][4],viewport_scale[4],viewport_offset[4];
} device;
static struct native_resource *resources,*history_sample_override;
static uint32_t next_resource_id=1,next_program_id=1;
static uint32_t render_height=480,native_storage_width,native_storage_height;
static BOOL render_settings_initialized=TRUE;
static long screen_width,ui_offset;
static float screen_scale[2]={1,1};
static long requested_height=480,requested_width;
static int drawable_width=1280,drawable_height=720;
static struct { struct { uint32_t capabilities; } reply; } transport;
static uint64_t submitted_batches,submitted_commands,submitted_bytes,submit_wall_ns;
static uint64_t statistics_batches,statistics_commands,statistics_bytes,statistics_wall_ns;
static uint32_t largest_statistics_batch;
static pthread_mutex_t vertical_blank_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t vertical_blank_condition=PTHREAD_COND_INITIALIZER;
static unsigned flip_count,pending_flips;
static long config_integer(const char *key) {
    if(!strcmp(key,"display.render_height"))return requested_height;
    if(!strcmp(key,"display.screen_width"))return requested_width;
    assert(!strcmp(key,"debug.screenshot_every"));return 0;
}
static BOOL config_boolean(const char *key) {
    assert(!strcmp(key,"debug.gpu_stats") || !strcmp(key,"display.vsync"));return FALSE;
}
static long halo_screen_width(void) { assert(screen_width);return screen_width; }
static void platform_video_drawable_size(int *width,int *height) { *width=drawable_width;*height=drawable_height; }
static _Noreturn void native_fail(const char *operation,int status) {
    fprintf(stderr,"%s: %d\n",operation,status);abort();
}
static void require_status(const char *operation,int status) { if(status)native_fail(operation,status); }
static void platform_log(const char *format,...) { assert(format); }
static int halo_interpolation_enabled(void) { return 1; }
static void native_frame_wait(void) {}
static void native_frame_statistics(void) {}
static void platform_pump_events(void) {}
static void vertical_blank_start(void) {}
static void native_flush_statistics_log(unsigned long first,unsigned long last) { (void)first;(void)last; }
static void write_screenshot(struct native_resource *entry) { (void)entry;assert(0); }
static struct native_resource *text_texture_get(DWORD data) { (void)data;return NULL; }
static struct native_resource *rendered_mip_composite(DWORD data,const struct xgpu_texture_description *d) {
    (void)data;(void)d;assert(0);return NULL;
}
struct host_texture {
    struct halo_metal_ref ref;
    uint32_t width,height,format,planes;
    uint32_t *pixels;
};
static struct host_texture host[32];
struct event { uint32_t opcode,id,width,height,planes;int reason;uint32_t active_height; };
static struct event events[8192];static unsigned event_count;
struct queued { uint32_t bytes;unsigned char command[128]; };
static struct queued queue[128];static unsigned queue_count;
static unsigned live_textures,maximum_live,completed_presents,display_settings;
static struct host_texture *host_find(struct halo_metal_ref ref) {
    for(unsigned i=0;i<32;i++)if(host[i].ref.id==ref.id && host[i].ref.generation==ref.generation)return &host[i];
    assert(0);return NULL;
}
static void event(uint32_t opcode,uint32_t id,uint32_t width,uint32_t height,uint32_t planes,int reason) {
    assert(event_count<8192);events[event_count++]=(struct event){opcode,id,width,height,planes,reason,render_height};
}
static void packet_begin(uint32_t bytes,const uint32_t *payloads,unsigned count) {
    assert(bytes<=sizeof(queue[0].command) && !payloads && !count);
}
static uint32_t command_append(const void *data,uint32_t bytes) {
    assert(queue_count<128 && bytes<=sizeof(queue[0].command));
    struct queued *q=&queue[queue_count++];q->bytes=bytes;memcpy(q->command,data,bytes);return 0;
}
static void packet_finish(void) {}
static void packet_flush(enum native_flush_reason reason) {
    for(unsigned i=0;i<queue_count;i++) {
        struct queued *q=&queue[i];struct halo_metal_command c;memcpy(&c,q->command,sizeof(c));
        if(c.opcode==HALO_METAL_CREATE_TEXTURE_EX) {
            struct halo_metal_create_ex create;memcpy(&create,q->command,sizeof(create));
            struct host_texture *t=NULL;
            for(unsigned n=0;n<32;n++) { assert(host[n].ref.id!=create.resource.id);if(!host[n].ref.id && !t)t=&host[n]; }
            assert(t && create.width && create.height && create.mip_levels);
            *t=(struct host_texture){create.resource,create.width,create.height,create.format,0,NULL};
            if(create.format!=HALO_METAL_DEPTH32_STENCIL8) {
                t->pixels=malloc((size_t)t->width*t->height*4);assert(t->pixels);
                memset(t->pixels,0xa7,(size_t)t->width*t->height*4);
            }
            live_textures++;if(live_textures>maximum_live)maximum_live=live_textures;
            event(c.opcode,t->ref.id,t->width,t->height,0,reason);
        } else if(c.opcode==HALO_METAL_DELETE_TEXTURE) {
            struct halo_metal_delete deletion;memcpy(&deletion,q->command,sizeof(deletion));
            struct host_texture *t=host_find(deletion.resource);event(c.opcode,t->ref.id,0,0,0,reason);
            free(t->pixels);memset(t,0,sizeof(*t));assert(live_textures);live_textures--;
        } else if(c.opcode==HALO_METAL_CLEAR) {
            struct halo_metal_clear clear;memcpy(&clear,q->command,sizeof(clear));
            struct host_texture *t=host_find(clear.color.id ? clear.color:clear.depth_stencil);
            assert(!clear.x && !clear.y && clear.width==t->width && clear.height==t->height);
            assert(!clear.rgba[0] && !clear.rgba[1] && !clear.rgba[2] && !clear.rgba[3] && !clear.depth && !clear.stencil);
            assert(clear.planes==(t->format==HALO_METAL_DEPTH32_STENCIL8 ? HALO_METAL_DEPTH|HALO_METAL_STENCIL:HALO_METAL_COLOR));
            if(t->pixels)memset(t->pixels,0,(size_t)t->width*t->height*4);
            t->planes=clear.planes;event(c.opcode,t->ref.id,t->width,t->height,t->planes,reason);
        } else if(c.opcode==HALO_METAL_COPY_SUBRESOURCE) {
            struct halo_metal_copy_subresource copy;memcpy(&copy,q->command,sizeof(copy));
            struct host_texture *from=host_find(copy.source),*to=host_find(copy.destination);
            assert(from!=to && from->pixels && to->pixels && from->planes==HALO_METAL_COLOR && to->planes==HALO_METAL_COLOR);
            assert(copy.width==from->width && copy.width==to->width && copy.height==from->height && copy.height==to->height);
            assert(copy.planes==HALO_METAL_COLOR && !copy.source_x && !copy.source_y && !copy.destination_x && !copy.destination_y);
            memcpy(to->pixels,from->pixels,(size_t)copy.width*copy.height*4);
            event(c.opcode,to->ref.id,copy.width,copy.height,copy.planes,reason);
        } else if(c.opcode==HALO_METAL_PRESENT_SCALED) {
            struct halo_metal_present_scaled present;memcpy(&present,q->command,sizeof(present));
            struct host_texture *t=host_find(present.source);assert(t->planes==HALO_METAL_COLOR);
            event(c.opcode,t->ref.id,t->width,t->height,0,reason);completed_presents++;
        } else if(c.opcode==HALO_METAL_DISPLAY_SETTINGS) { display_settings++;event(c.opcode,0,0,0,0,reason); }
        else assert(0);
    }
    queue_count=0;event(0,0,0,0,0,reason);
}
/* PRODUCTION */
static D3DSurface surface(uint32_t data,uint32_t width,uint32_t height,uint32_t format) {
    uint32_t pitch=(width*4+63u)&~63u;
    return (D3DSurface){1,data,0,(2u<<4)|(format<<8)|(1u<<16),
        (width-1)|((height-1)<<12)|((pitch/64-1)<<24)};
}
static struct native_resource *back,*depth,*primary_copy,*water[4],*composite,*text;
static unsigned base_live;
static void setup(uint32_t width) {
    screen_width=width;ui_offset=(width-640)/2;device.ready=device.created=TRUE;
    transport.reply.capabilities=HALO_METAL_CAP_COPY_SUBRESOURCE|HALO_METAL_CAP_PRESENT_SCALED;
    device.back_buffer=surface(0x10000,width,480,D3DFMT_LIN_A8R8G8B8);
    device.history_buffer=surface(0x20000,width,480,D3DFMT_LIN_A8R8G8B8);
    device.depth_buffer=surface(0x30000,width,480,D3DFMT_LIN_D24S8);
    device.render_target=&device.back_buffer;device.depth_stencil=&device.depth_buffer;
    device.viewport=(D3DVIEWPORT8){17,23,width-34,434,0.1f,0.9f};
    for(unsigned i=0;i<8;i++) { device.query_slots[i]=(struct halo_metal_ref){100+i,3};device.query_results[i]=1000+i;device.query_pending[i]=i&1; }
    memset(device.constants,0x4a,sizeof(device.constants));memset(device.viewport_scale,0x5a,sizeof(device.viewport_scale));
    memset(device.viewport_offset,0x6a,sizeof(device.viewport_offset));
    back=target_get(&device.back_buffer);depth=target_get(&device.depth_buffer);target_get(&device.history_buffer);
    D3DSurface copy=device.depth_buffer;copy.Format=device.back_buffer.Format;primary_copy=target_get(&copy);
    for(unsigned i=0;i<4;i++) {
        D3DSurface s=surface(0x40000+i*0x10000,128u>>i,128u>>i,D3DFMT_LIN_A8R8G8B8);
        water[i]=target_get(&s);water[i]->last_rendered=10+i;
    }
    composite=calloc(1,sizeof(*composite));assert(composite);composite->mip_composite=TRUE;
    composite->description=(struct xgpu_texture_description){.width=128,.height=128,.depth=1,.levels=4};
    composite->usage=HALO_METAL_SHADER_READ;composite->format=HALO_METAL_BGRA8;
    composite->mip_copy_cache=calloc(4,sizeof(*composite->mip_copy_cache));assert(composite->mip_copy_cache);
    memset(composite->mip_copy_cache,0x61,4*sizeof(*composite->mip_copy_cache));resource_create(composite);
    composite->next=resources;resources=composite;
    text=calloc(1,sizeof(*text));assert(text);text->description=back->description; /* Same dimensions alone must not retire sampled assets. */
    text->usage=HALO_METAL_SHADER_READ;text->format=HALO_METAL_RGBA8;text->text_atlas=TRUE;resource_create(text);
    text->next=resources;resources=text;packet_flush(NATIVE_FLUSH_EXIT);base_live=live_textures;
}
static unsigned resource_count(void) { unsigned n=0;for(struct native_resource *r=resources;r;r=r->next)n++;return n; }
static uint32_t pattern(unsigned x,unsigned y,unsigned seed) { return 0xff000000u|((x*13+y*8191+seed*99991)&0x00ffffffu); }
static void fill(struct native_resource *r,unsigned seed) {
    struct host_texture *t=host_find(r->ref);assert(t->pixels);
    for(unsigned y=0;y<t->height;y++)for(unsigned x=0;x<t->width;x++)t->pixels[y*t->width+x]=pattern(x,y,seed);
    r->last_rendered=rendered_serial_next();
}
static void pixels(struct halo_metal_ref ref,unsigned seed) {
    struct host_texture *t=host_find(ref);assert(t->pixels);
    for(unsigned y=0;y<t->height;y++)for(unsigned x=0;x<t->width;x++)assert(t->pixels[y*t->width+x]==pattern(x,y,seed));
}
static void zero(struct native_resource *r) {
    struct host_texture *t=host_find(r->ref);assert(t->planes==(r->format==HALO_METAL_DEPTH32_STENCIL8 ? 6u:1u));
    if(t->pixels)for(size_t i=0;i<(size_t)t->width*t->height;i++)assert(!t->pixels[i]);
}
static struct native_resource *sample_history(void) { D3DBaseTexture s=device.history_buffer;return texture_get(&s,NULL,0); }
static void present(void) { D3DDevice_Present(NULL,NULL,NULL,NULL);assert(!queue_count); }
static void request(long height) { requested_height=height;assert(halo_metal_apply_video_settings()); }
static void test_boundary(void) {
    setup(852);fill(back,1);present();struct native_resource *old=sample_history();struct halo_metal_ref old_ref=old->ref;
    D3DSurface before[3]={device.back_buffer,device.history_buffer,device.depth_buffer};
    D3DVIEWPORT8 viewport=device.viewport;struct halo_metal_ref queries[8];UINT results[8];BOOL pending[8];
    float constants[8][4],scale[4],offset[4];
    memcpy(queries,device.query_slots,sizeof(queries));memcpy(results,device.query_results,sizeof(results));memcpy(pending,device.query_pending,sizeof(pending));
    memcpy(constants,device.constants,sizeof(constants));memcpy(scale,device.viewport_scale,sizeof(scale));memcpy(offset,device.viewport_offset,sizeof(offset));
    uint32_t back_id=back->ref.id,depth_id=depth->ref.id,copy_id=primary_copy->ref.id;
    unsigned start=event_count;request(1080);
    assert(render_height==480 && screen_scale[1]==1 && back->ref.id==back_id && sample_history()==old && !history_sample_override);
    for(unsigned i=start;i<event_count;i++)assert(events[i].opcode!=HALO_METAL_DELETE_TEXTURE && events[i].opcode!=HALO_METAL_CREATE_TEXTURE_EX);
    fill(back,2);present();assert(completed_presents==2 && render_height==1080 && screen_scale[1]==2.25f);
    assert(back->storage_width==1917 && back->storage_height==1080 && back->ref.id!=back_id);
    assert(depth->ref.id!=depth_id && primary_copy->ref.id!=copy_id && primary_copy->data==depth->data);
    zero(back);zero(depth);zero(primary_copy);assert(sample_history()==old && history_sample_override==old);pixels(old_ref,2);
    assert(!memcmp(before,(D3DSurface[]){device.back_buffer,device.history_buffer,device.depth_buffer},sizeof(before)));
    assert(screen_width==852 && ui_offset==106 && !memcmp(&viewport,&device.viewport,sizeof(viewport)));
    assert(!memcmp(queries,device.query_slots,sizeof(queries)) && !memcmp(results,device.query_results,sizeof(results)) && !memcmp(pending,device.query_pending,sizeof(pending)));
    assert(!memcmp(constants,device.constants,sizeof(constants)) && !memcmp(scale,device.viewport_scale,sizeof(scale)) && !memcmp(offset,device.viewport_offset,sizeof(offset)));
    D3DBaseTexture s=device.back_buffer;assert(texture_get(&s,NULL,0)==back);s=device.depth_buffer;s.Format=device.back_buffer.Format;
    assert(texture_get(&s,NULL,1)==primary_copy && primary_copy!=depth);
    unsigned present_at=0,first_delete=0,resize_flush=0;
    for(unsigned i=start;i<event_count;i++) {
        if(events[i].opcode==HALO_METAL_PRESENT_SCALED) { present_at=i;assert(events[i].height==480); }
        if(events[i].opcode==HALO_METAL_DELETE_TEXTURE && !first_delete)first_delete=i;
        if(!events[i].opcode && events[i].reason==NATIVE_FLUSH_RESIZE) { resize_flush=i;assert(events[i].active_height==480); }
    }
    assert(present_at && present_at<first_delete && first_delete<resize_flush && !queue_count);
}
static void test_history(void) {
    setup(640);fill(back,3);request(720);present();struct native_resource *old=sample_history();struct halo_metal_ref old_ref=old->ref;pixels(old_ref,3);
    assert(history_sample_override==old && old->storage_height==480);fill(back,4);pixels(old_ref,3);
    unsigned start=event_count;present();assert(!history_sample_override);struct native_resource *now=sample_history();
    assert(now->ref.id!=old_ref.id && now->storage_height==720);pixels(now->ref,4);
    unsigned copied=0,displayed=0,deleted=0;
    for(unsigned i=start;i<event_count;i++) {
        if(events[i].opcode==HALO_METAL_COPY_SUBRESOURCE)copied=i;
        if(events[i].opcode==HALO_METAL_PRESENT_SCALED)displayed=i;
        if(events[i].opcode==HALO_METAL_DELETE_TEXTURE && events[i].id==old_ref.id)deleted=i;
    }
    assert(copied && copied<displayed && displayed<deleted && live_textures==base_live && resource_count()==base_live);
}
static void test_deferral(const char *reason) {
    setup(852);request(720);struct halo_metal_ref old=back->ref;
    if(!strcmp(reason,"visibility"))device.visibility_test_active=TRUE;
    else if(!strcmp(reason,"immediate"))device.immediate_active=TRUE;
    else { assert(!strcmp(reason,"unready"));device.ready=FALSE; }
    present();assert(render_height==480 && back->ref.id==old.id && !history_sample_override);
    device.visibility_test_active=device.immediate_active=FALSE;device.ready=TRUE;present();
    assert(render_height==720 && back->ref.id!=old.id && history_sample_override);
}
static void test_native(void) {
    setup(852);request(0);drawable_width=drawable_height=0;struct halo_metal_ref old=back->ref;
    present();assert(render_height==480 && screen_scale[1]==1 && back->ref.id==old.id && !history_sample_override);
    struct halo_metal_render_dimensions d={9,8,7,6,5},saved=d;
    assert(native_storage_dimensions(852,&d)==HALO_METAL_INVALID && !memcmp(&d,&saved,sizeof(d)));
    drawable_width=1280;drawable_height=720;present();
    assert(!render_height && native_storage_width==1280 && native_storage_height==720 && back->scale_mode==HALO_METAL_RENDER_SCALE_NATIVE_AXES);
    assert(back->storage_width==1280 && back->storage_height==720 && screen_scale[0]==1280.0f/852 && screen_scale[1]==1.5f);
    present();assert(!history_sample_override);unsigned before=event_count;present();
    for(unsigned i=before;i<event_count;i++)assert(events[i].opcode!=HALO_METAL_DELETE_TEXTURE && events[i].opcode!=HALO_METAL_CREATE_TEXTURE_EX);
    drawable_width=1920;drawable_height=1080;present();assert(back->storage_width==1920 && back->storage_height==1080 && history_sample_override);
}
static void test_aspect(void) {
    setup(640);requested_width=640;drawable_width=1920;drawable_height=1080;request(0);present();
    assert(screen_width==640 && back->storage_width==1440 && back->storage_height==1080);
    struct halo_metal_render_dimensions d={640,480,back->storage_width,back->storage_height,back->scale_mode};
    struct halo_metal_render_rectangle box;require_status("box",halo_metal_render_presentation_box(&d,1920,1080,&box));
    assert(box.x==240 && !box.y && box.width==1440 && box.height==1080);
    struct halo_metal_render_point p;require_status("point",halo_metal_render_window_point(&d,960,540,1920,1080,480,270,0,&p));
    assert(p.x==320 && p.y==240);
}
static void test_repeated(void) {
    setup(852);struct halo_metal_ref water_refs[4],composite_ref=composite->ref,text_ref=text->ref;
    struct halo_metal_mip_composite_copy signatures[4];memcpy(signatures,composite->mip_copy_cache,sizeof(signatures));
    for(unsigned i=0;i<4;i++)water_refs[i]=water[i]->ref;
    for(unsigned i=0;i<20;i++) {
        request(i&1 ? 720:1080);fill(back,i+1);present();assert(history_sample_override);
        assert(live_textures==base_live && resource_count()==base_live); /* New history is created on the next Present. */
        fill(back,i+31);present();assert(!history_sample_override && live_textures==base_live && resource_count()==base_live);
        assert(maximum_live<=base_live+1 && composite->ref.id==composite_ref.id && text->ref.id==text_ref.id);
        assert(!memcmp(signatures,composite->mip_copy_cache,sizeof(signatures)));
        for(unsigned mip=0;mip<4;mip++)assert(water[mip]->ref.id==water_refs[mip].id && water[mip]->storage_width==(128u>>mip) && water[mip]->last_rendered==10+mip);
    }
}
static void cleanup(void) {
    while(resources) { struct native_resource *next=resources->next;free(resources->mip_copy_cache);free(resources);resources=next; }
    for(unsigned i=0;i<32;i++)free(host[i].pixels);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"boundary"))test_boundary();
    else if(!strcmp(argv[1],"history"))test_history();
    else if(!strcmp(argv[1],"visibility") || !strcmp(argv[1],"immediate") || !strcmp(argv[1],"unready"))test_deferral(argv[1]);
    else if(!strcmp(argv[1],"native"))test_native();
    else if(!strcmp(argv[1],"aspect"))test_aspect();
    else if(!strcmp(argv[1],"repeated"))test_repeated();
    else assert(0);
    cleanup();printf("%s: production live-resolution CPU checks passed\n",argv[1]);return 0;
}
'''


class LiveResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-metal-live-resolution-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        source = SOURCE.read_text()
        names = ("native_render_height", "native_storage_dimensions", "surface_dimensions",
                 "resource_create", "resource_delete", "target_storage_initialize", "target_get",
                 "rendered_alias", "rendered_serial_next", "backbuffer_color_copy",
                 "backbuffer_history_advance", "native_history_sample_retire", "native_resolution_commit",
                 "halo_metal_apply_video_settings", "D3DDevice_Present")
        production = "\n\n".join(function(source, name) for name in names)
        texture = function(source, "texture_get").split("    for (entry=resources;entry;entry=entry->next)", 1)[0]
        production += "\n\n" + texture + '\n    (void)palette;(void)stage;native_fail("unexpected authored texture fallback",HALO_METAL_INVALID);\n}\n'
        resource = "struct native_resource {" + source.split("struct native_resource {", 1)[1].split("};", 1)[0] + "};"
        reasons = "enum native_flush_reason {" + source.split("enum native_flush_reason {", 1)[1].split("};", 1)[0] + "};"
        xdk = (ROOT / "port/include/xdk/xdk_pdb.h").read_text()
        format_enum = re.search(r"enum _D3DFORMAT\s*\{.*?\};", xdk, re.S)
        if not format_enum:
            raise AssertionError("Original Xbox format enum is missing")
        harness = HARNESS.replace("/* FORMAT ENUM */", format_enum.group()).replace("/* RESOURCE */", resource)
        harness = harness.replace("/* FLUSH REASONS */", reasons).replace("/* PRODUCTION */", production)
        probe = cls.directory / "live_resolution.c"
        probe.write_text(harness_prefix() + harness)
        cls.executable = cls.directory / "live_resolution"
        compiled = subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-pthread",
                                   "-DHALO_MACOS_NATIVE_METAL=1", "-I", str(ROOT), str(probe),
                                   str(ROOT / "port/linux/src/metal_render_scale.c"), "-o", str(cls.executable)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("production live-resolution CPU checks passed", result.stdout)

    def test_acceptance_waits_for_completed_present_and_preserves_logical_state(self):
        self.run_case("boundary")

    def test_old_history_pixels_survive_one_resized_frame_then_retire(self):
        self.run_case("history")

    def test_active_visibility_query_defers_transition(self):
        self.run_case("visibility")

    def test_active_immediate_primitive_defers_transition(self):
        self.run_case("immediate")

    def test_unready_device_defers_transition(self):
        self.run_case("unready")

    def test_native_minimized_drawable_defers_and_live_drawable_changes_apply(self):
        self.run_case("native")

    def test_native_explicit_aspect_keeps_camera_canvas_and_pointer_mapping(self):
        self.run_case("aspect")

    def test_repeated_switches_bound_gpu_storage_and_preserve_water_cache(self):
        self.run_case("repeated")


if __name__ == "__main__":
    unittest.main()
