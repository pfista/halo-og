"""Execute production target/clear/raster/input/pacing functions with a CPU queue.

These checks cover native frontend wiring, not GPU pixels or achieved frame rate.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import ROOT, SOURCE, HARNESS, function

EXTRA = r'''
#include <limits.h>
#include <time.h>
#include <errno.h>
#include "port/linux/src/halo_frame_pacing.h"
#include "port/linux/src/metal_render_scale.h"
#ifndef TIMER_ABSTIME
#define TIMER_ABSTIME 1
#endif
typedef struct { int x1,y1,x2,y2; } D3DRECT;
#define D3DCLEAR_TARGET_R 1
#define D3DCLEAR_TARGET_G 2
#define D3DCLEAR_TARGET_B 4
#define D3DCLEAR_TARGET_A 8
#define D3DCLEAR_ZBUFFER 16
#define D3DCLEAR_STENCIL 32
static long ui_offset;
#define UI_OFFSET ui_offset
static struct halo_frame_pacing frame_pacing;
static BOOL render_settings_initialized=TRUE;
#define preset render_height
static int ww=1280,wh=960,pw=2560,ph=1920;
static unsigned drawable_queries;
static int require_video_before_drawable;
static void platform_video_window_size(int *w,int *h) { *w=ww;*h=wh; }
static void platform_video_drawable_size(int *w,int *h) {
    if(require_video_before_drawable) assert(video_calls==1);
    drawable_queries++;*w=pw;*h=ph;
}
static void *native_packet_storage;
static unsigned native_window_initializations;
static uint32_t native_initialize_flags,native_initialize_capabilities;
static uint32_t available_capabilities=UINT32_MAX;
static unsigned int platform_video_native_window(void) { assert(video_calls==1);return 7; }
static int halo_metal_guest_setup(void *t,void *storage,uint32_t bytes) {
    assert(t==&transport && storage && bytes==HALO_METAL_MAX_PACKET);
    native_packet_storage=storage;return 0;
}
static int halo_metal_guest_initialize(void *t,uint32_t window,uint32_t flags,uint32_t capabilities) {
    assert(t==&transport && window==7 && video_calls==1);
    assert((capabilities&HALO_METAL_CAP_TARGETS) && (capabilities&HALO_METAL_CAP_DRAW));
    assert(flags==(!strcmp(anti_aliasing,"fxaa") ? HALO_METAL_ENABLE_FXAA:0));
    native_initialize_flags=flags;native_initialize_capabilities=capabilities;
    native_window_initializations++;transport.reply.capabilities=available_capabilities;
    return capabilities&~available_capabilities ? HALO_METAL_UNSUPPORTED:0;
}
static void memory_watch_initialize(void) {}
static struct halo_metal_create_ex creation;
static struct halo_metal_clear_channels clearing;
static struct halo_metal_clear allocation_clear;
static void packet_begin(uint32_t bytes,const void *payload,unsigned n) { (void)bytes;assert(!payload && !n); }
static void command_append(const void *data,uint32_t size) {
    const struct halo_metal_command *c=data;
    if(c->opcode==HALO_METAL_CREATE_TEXTURE_EX) { assert(size==sizeof(creation));memcpy(&creation,data,size); }
    else if(c->opcode==HALO_METAL_CLEAR_CHANNELS) { assert(size==sizeof(clearing));memcpy(&clearing,data,size); }
    else { assert(c->opcode==HALO_METAL_CLEAR && size==sizeof(allocation_clear));memcpy(&allocation_clear,data,size); }
}
static void packet_finish(void) {}
static void color_to_vec4(D3DCOLOR color,float out[4]) { (void)color;out[0]=out[1]=out[2]=out[3]=0.5f; }
static uint64_t fake_now=1000000000;
static int clock_status,sleep_status,interrupted,sleeps;
static uint64_t slept_deadline;
static int test_clock_gettime(int clock,struct timespec *out) {
    assert(clock==CLOCK_MONOTONIC);out->tv_sec=fake_now/1000000000;out->tv_nsec=fake_now%1000000000;return clock_status;
}
static int test_clock_nanosleep(int clock,int flags,const struct timespec *until,void *remaining) {
    assert(clock==CLOCK_MONOTONIC && flags==TIMER_ABSTIME && !remaining);sleeps++;
    uint64_t deadline=(uint64_t)until->tv_sec*1000000000+until->tv_nsec;
    if(interrupted) { assert(deadline==slept_deadline);interrupted=0;return 0; }
    slept_deadline=deadline;if(sleep_status==EINTR) { interrupted=1;return EINTR; }
    return sleep_status;
}
#define clock_gettime test_clock_gettime
#define clock_nanosleep test_clock_nanosleep
/* PRODUCTION */
static void test_targets(void) {
    screen_width=640;D3DSurface s={0,100,0,D3DFMT_LIN_A8R8G8B8,(480u<<16)|640u};
    const uint32_t heights[]={480,720,1080,1440,2160};
    for(unsigned i=0;i<5;i++) {
        preset=heights[i];struct native_resource *r=target_get(&s);
        assert(r->description.width==640 && r->description.height==480);
        assert(r->storage_width==preset*4/3 && r->storage_height==preset);
        assert(creation.width==r->storage_width && creation.height==r->storage_height);
        assert(allocation_clear.width==creation.width && allocation_clear.height==creation.height);
        assert(target_get(&s)==r);
    }
    s.Size=(240u<<16)|320u;s.Data=200;
    struct native_resource *off=target_get(&s);assert(off->storage_width==320 && off->storage_height==240);
    struct native_resource authored={0};authored.description.width=127;authored.description.height=31;
    authored.description.depth=authored.description.levels=1;authored.format=HALO_METAL_BGRA8;
    resource_create(&authored);assert(creation.width==127 && creation.height==31);
}
static void test_raster_clear_pointer(void) {
    screen_width=738;preset=1080;
    D3DSurface s={0,300,0,D3DFMT_LIN_A8R8G8B8,(480u<<16)|738u};
    struct native_resource *r=target_get(&s);
    struct halo_metal_draw_state state={0};state.depth_bias=0.25f;state.color_write_mask=15;
    state.viewport[0]=369;state.viewport[1]=240;state.viewport[2]=369;state.viewport[3]=240;
    state.viewport[4]=0.125f;state.viewport[5]=0.875f;
    state.scissor[0]=369;state.scissor[1]=240;state.scissor[2]=369;state.scissor[3]=240;
    native_raster_scale(r,&state);
    assert(state.viewport[0]==830 && state.viewport[1]==540 && state.viewport[2]==831 && state.viewport[3]==540);
    assert(state.scissor[0]==830 && state.scissor[2]==831);
    assert(state.depth_bias==0.25f && state.color_write_mask==15 && state.viewport[4]==0.125f && state.viewport[5]==0.875f);
    device.ready=device.created=1;device.render_target=&s;device.depth_stencil=NULL;
    device.viewport=(D3DVIEWPORT8){0,0,738,480,0,1};ui_offset=49;
    D3DRECT rect={320,0,689,240};
    D3DDevice_Clear(1,&rect,15,0,0.5f,7);
    assert(clearing.clear.x==830 && clearing.clear.width==831 && clearing.clear.height==540);
    assert(clearing.color_write_mask==15 && clearing.clear.planes==HALO_METAL_COLOR);
    assert(clearing.clear.depth==0.5f && clearing.clear.stencil==7);
    device.back_buffer=s;ww=1280;wh=720;pw=2560;ph=1440;
    short x,y;ui_point_from_window(640,360,&x,&y);assert(x==320 && y==240);
    ui_point_from_window(1000000000,360,&x,&y);assert(x==-1 && y==-1);
}
static void test_wait(void) {
    render_cap=60;interpolation=1;
    native_frame_wait();assert(sleeps==1 && slept_deadline==1016666667);
    fake_now=slept_deadline;sleep_status=EINTR;interrupted=0;
    /* EINTR once, then success at the identical absolute deadline. */
    native_frame_wait();assert(sleeps==3 && slept_deadline==1033333334);
    fake_now=slept_deadline;sleep_status=EINVAL;
    native_frame_wait();assert(sleeps==4 && slept_deadline==1050000000);
    assert(!frame_pacing.frame_limit && !frame_pacing.deadline_ns &&
        !frame_pacing.previous_now_ns && !frame_pacing.fraction);
    /* A hard sleep failure starts a fresh period on the next frame. */
    sleep_status=0;native_frame_wait();assert(sleeps==5 && slept_deadline==1050000001);
    clock_status=1;native_frame_wait();assert(frame_pacing.frame_limit==0 && sleeps==5);
    clock_status=0;interpolation=0;native_frame_wait();assert(sleeps==5);
    interpolation=1;render_cap=0;native_frame_wait();assert(sleeps==5);
}
static void test_native_startup(void) {
    requested_render_height=0;requested_screen_width=0;render_settings_initialized=FALSE;
    screen_width=738;pw=3600;ph=2338;require_video_before_drawable=1;
    /* Choosing native before the window exists must neither read its pixels
       nor silently cache480. The actual CreateDevice then creates the window
       before invoking the production native storage initialization. */
    assert(!native_render_height() && render_settings_initialized && !drawable_queries);
    D3DPRESENT_PARAMETERS parameters={0};parameters.BackBufferWidth=738;parameters.BackBufferHeight=480;
    parameters.SwapEffect=D3DSWAPEFFECT_DISCARD;
    D3DDevice *returned=NULL;assert(Direct3D_CreateDevice(0,0,NULL,0,&parameters,&returned)==S_OK);
    assert(returned==device_pointer() && video_calls==1 && drawable_queries==1 && native_window_initializations==1);
    for(unsigned i=0;i<16;i++) assert(device.attributes[i][3]==1.0f);
    assert(native_storage_width==3600 && native_storage_height==2338 && !native_render_height());
    DWORD original_data=device.back_buffer.Data,original_size=device.back_buffer.Size;
    struct native_resource *r=target_get(&device.back_buffer);
    assert(r->description.width==738 && r->description.height==480 && r->scale_mode==1);
    assert(creation.width==3600 && creation.height==2338 && allocation_clear.width==3600 && allocation_clear.height==2338);
    struct halo_metal_draw_state state={0};state.viewport[0]=369;state.viewport[1]=240;
    state.viewport[2]=369;state.viewport[3]=240;state.viewport[5]=1;
    state.scissor[0]=369;state.scissor[1]=240;state.scissor[2]=369;state.scissor[3]=240;
    native_raster_scale(r,&state);
    assert(state.viewport[0]==1800 && state.viewport[1]==1169 && state.viewport[2]==1800 && state.viewport[3]==1169);
    assert(state.scissor[0]==1800 && state.scissor[1]==1169 && state.scissor[2]==1800 && state.scissor[3]==1169);
    ui_offset=49;D3DRECT rect={320,240,689,480};device.depth_stencil=NULL;
    D3DDevice_Clear(1,&rect,15,0,1,0);
    assert(clearing.clear.x==1800 && clearing.clear.y==1169 && clearing.clear.width==1800 && clearing.clear.height==1169);
    ww=1800;wh=1169;short x,y;ui_point_from_window(900,584.5f,&x,&y);assert(x==320 && y==240);
    /* Moving/resizing the window later keeps attachment storage for this
       launch. Input follows the resulting host presentation box instead. */
    unsigned reads=drawable_queries;pw=2000;ph=2000;native_storage_initialize();
    assert(drawable_queries==reads && native_storage_width==3600 && native_storage_height==2338);
    assert(target_get(&device.back_buffer)==r && device.back_buffer.Data==original_data && device.back_buffer.Size==original_size);
    ww=1000;wh=1000;ui_point_from_window(500,500,&x,&y);assert(x==320 && y==240);
    D3DSurface off={0,400,0,D3DFMT_LIN_A8R8G8B8,(240u<<16)|320u};
    struct native_resource *small=target_get(&off);assert(small->storage_width==320 && small->storage_height==240 && !small->scale_mode);
}
static void test_native_invalid_and_requested_aspect(void) {
    preset=0;screen_width=738;
    D3DSurface s={0,500,0,D3DFMT_LIN_A8R8G8B8,(480u<<16)|738u};
    failure_expected=1;
    if(!setjmp(failure_jump)) { target_get(&s);assert(0); }
    assert(failure_status==HALO_METAL_INVALID && !native_storage_width && !native_storage_height);
    const int widths[]={0,-1,8193,3600};const int heights[]={2338,2338,2338,0};
    for(unsigned i=0;i<4;i++) {
        pw=widths[i];ph=heights[i];
        if(!setjmp(failure_jump)) { native_storage_initialize();assert(0); }
        assert(failure_status==HALO_METAL_INVALID && !native_storage_width && !native_storage_height);
    }
    failure_expected=0;requested_screen_width=640;screen_width=640;pw=3600;ph=2338;
    native_storage_initialize();assert(native_storage_width==3117 && native_storage_height==2338);
    /* Explicit Xbox aspect fits rather than being expanded to the display. */
    s.Data=600;s.Size=(480u<<16)|640u;
    struct native_resource *r=target_get(&s);assert(r->storage_width==3117 && r->storage_height==2338);
}
static void test_antialias_startup(void) {
    const uint32_t base_capabilities=HALO_METAL_CAP_TARGETS | HALO_METAL_CAP_UPLOAD |
        HALO_METAL_CAP_CLEAR | HALO_METAL_CAP_DRAW | HALO_METAL_CAP_READBACK | HALO_METAL_CAP_VISIBILITY;
    video_calls=1;require_video_before_drawable=1;screen_width=738;preset=0;
    pw=3600;ph=2338;
    const char *settings[]={"off","fxaa"};
    for(unsigned i=0;i<2;i++) {
        anti_aliasing=settings[i];device.ready=FALSE;
        native_storage_width=native_storage_height=0;
        available_capabilities=base_capabilities | HALO_METAL_CAP_FXAA;
        native_initialize();assert(device.ready && drawable_queries==i+1);
        assert(native_initialize_flags==(i ? HALO_METAL_ENABLE_FXAA:0));
        assert(native_initialize_capabilities==(base_capabilities | (i ? HALO_METAL_CAP_FXAA:0)));
        assert(native_storage_width==3600 && native_storage_height==2338);
        free(native_packet_storage);native_packet_storage=NULL;
    }
    /* The option must fail before drawable/storage setup when the host cannot
       provide its requested capability. Off remains compatible with that host. */
    available_capabilities=base_capabilities;anti_aliasing="fxaa";device.ready=FALSE;
    native_storage_width=native_storage_height=0;failure_expected=1;
    if(!setjmp(failure_jump)) { native_initialize();assert(0); }
    failure_expected=0;
    assert(failure_status==HALO_METAL_UNSUPPORTED && !device.ready && drawable_queries==2);
    assert(!native_storage_width && !native_storage_height);
    free(native_packet_storage);native_packet_storage=NULL;
    anti_aliasing="off";native_initialize();
    assert(device.ready && drawable_queries==3 && !native_initialize_flags);
    assert(native_initialize_capabilities==base_capabilities && native_window_initializations==4);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"targets"))test_targets();
    else if(!strcmp(argv[1],"raster"))test_raster_clear_pointer();
    else if(!strcmp(argv[1],"native"))test_native_startup();
    else if(!strcmp(argv[1],"native_invalid"))test_native_invalid_and_requested_aspect();
    else if(!strcmp(argv[1],"antialias_startup"))test_antialias_startup();
    else test_wait();
    while(resources) { struct native_resource *next=resources->next;free(resources);resources=next; }
    free(native_packet_storage);
    return 0;
}
'''


class DisplayFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-display-frontend-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        prefix = HARNESS.split('struct target_record', 1)[0]
        prefix = prefix.replace('typedef uint32_t DWORD, UINT, ULONG;', 'typedef uint32_t DWORD, UINT, ULONG, D3DCOLOR;')
        prefix = prefix.replace('static int halo_interpolation_enabled(void) { return 1; }',
                                'static int interpolation=1; static int halo_interpolation_enabled(void) { return interpolation; }')
        prefix = prefix.replace('static long config_integer(',
                                'static long render_cap,requested_render_height=480,requested_screen_width;\nstatic long config_integer(')
        prefix = prefix.replace('return !strcmp(key,"debug.screenshot_every") ? screenshot_every:0;',
                                'return !strcmp(key,"display.frame_limit") ? render_cap:'
                                '!strcmp(key,"display.render_height") ? requested_render_height:'
                                '!strcmp(key,"display.screen_width") ? requested_screen_width:0;')
        prefix = prefix.replace(function(prefix, 'native_initialize'), '')
        prefix = prefix.replace(function(prefix, 'config_string'),
                                'static const char *anti_aliasing="off";\n'
                                'static const char *config_string(const char *key) {\n'
                                ' if(!strcmp(key,"display.anti_aliasing")) return anti_aliasing;\n'
                                ' assert(!strcmp(key,"debug.screenshot_directory")); return screenshot_directory;\n'
                                '}')
        prefix = prefix.replace('D3DMATRIX transforms[D3DTS_MAX]; BOOL ready,created;',
                                'D3DMATRIX transforms[D3DTS_MAX]; float attributes[16][4]; BOOL ready,created;')
        # Existing history harness has stubs; this harness executes their real functions.
        for name in ('native_frame_wait', 'native_frame_statistics'):
            if ('static void ' + name + '(') in prefix:
                prefix = prefix.replace(function(prefix, name), '')
        source = SOURCE.read_text()
        names = ('native_render_height', 'native_storage_initialize', 'surface_dimensions',
                 'native_initialize',
                 'backbuffer_presentation_supported', 'backbuffer_surfaces_initialize', 'Direct3D_CreateDevice',
                 'resource_dimensions', 'native_raster_scale',
                 'resource_create', 'target_get', 'rendered_serial_next', 'D3DDevice_Clear',
                 'ui_point_from_window', 'native_frame_wait')
        production = '\n\n'.join(function(source, name) for name in names)
        c = folder / 'frontend.c'
        c.write_text(prefix + EXTRA.replace('/* PRODUCTION */', production))
        cls.binary = folder / 'frontend'
        result = subprocess.run(['clang', '-std=c11', '-O1', '-g', '-DHALO_MACOS_NATIVE_METAL=1',
                                 '-fsanitize=address,undefined,float-cast-overflow', '-I', str(ROOT),
                                 str(c), str(ROOT/'port/linux/src/metal_render_scale.c'),
                                 str(ROOT/'port/linux/src/halo_frame_pacing.c'), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_original_headers_and_authored_targets_with_all_native_presets(self):
        self.run_case('targets')

    def test_fractional_raster_clear_and_retina_pointer_wiring(self):
        self.run_case('raster')

    def test_real_present_wait_preserves_original_throttle_and_clock_failures(self):
        self.run_case('wait')

    def test_native_startup_order_exact_retina_storage_and_cached_backing(self):
        self.run_case('native')

    def test_native_invalid_drawables_fail_and_explicit_xbox_aspect_fits(self):
        self.run_case('native_invalid')

    def test_antialias_initialization_requests_only_opt_in_capability(self):
        self.run_case('antialias_startup')


if __name__ == '__main__':
    unittest.main()
