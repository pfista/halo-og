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
static uint32_t preset=480;
static uint32_t native_render_height(void) { return preset; }
static int ww=1280,wh=960,pw=2560,ph=1920;
static void platform_video_window_size(int *w,int *h) { *w=ww;*h=wh; }
static void platform_video_drawable_size(int *w,int *h) { *w=pw;*h=ph; }
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
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"targets"))test_targets();
    else if(!strcmp(argv[1],"raster"))test_raster_clear_pointer();
    else test_wait();
    while(resources) { struct native_resource *next=resources->next;free(resources);resources=next; }
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
        prefix = prefix.replace('static long config_integer(', 'static long render_cap;\nstatic long config_integer(')
        prefix = prefix.replace('return !strcmp(key,"debug.screenshot_every") ? screenshot_every:0;',
                                'return !strcmp(key,"display.frame_limit") ? render_cap:0;')
        # Existing history harness has stubs; this harness executes their real functions.
        for name in ('native_frame_wait', 'native_frame_statistics'):
            if ('static void ' + name + '(') in prefix:
                prefix = prefix.replace(function(prefix, name), '')
        source = SOURCE.read_text()
        names = ('surface_dimensions', 'resource_dimensions', 'native_raster_scale',
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


if __name__ == '__main__':
    unittest.main()
