"""Execute the production pre-HUD AA frontend with a CPU command queue.

The guest function is extracted unchanged, rectangle planning uses the production
C helper, and wire records use the real ABI. These checks do not run a GPU or
claim visual fidelity, antialiasing quality, or achieved performance.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import function

ROOT = Path(__file__).resolve().parents[1]
GUEST = ROOT / "port/linux/src/d3d8_metal.c"
RENDER = ROOT / "source/render/render.c"

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include "port/macos/include/halo_metal_abi.h"
#include "port/linux/src/metal_render_scale.h"
typedef unsigned char byte;
typedef unsigned short word;
#include "source/math/integer_math.h"
struct native_resource {
    struct halo_metal_ref ref;
    struct { uint32_t width,height; } description;
    uint32_t storage_width,storage_height,scale_mode,format;
    uint64_t last_rendered;
};
struct mock_device {
    int ready,visibility_test_active,antialiasing_enabled;
    void *render_target,*depth_stencil;
    float viewport[6],constants[192][4],transforms[3][16];
    uint32_t render_state[144],texture_state[4][32];
    uint64_t antialias_passes,resource_serial;
};
static struct mock_device device;
static struct { struct halo_metal_reply reply; } transport;
static struct native_resource target;
static const char *pending_setting;
static unsigned config_reads;
static unsigned target_reads,begins,appends,finishes;
static struct halo_metal_fxaa command;
static uint32_t reserved_size;
static jmp_buf failure;
static int failed_status;
static const char *failed_operation;
const char *config_string(const char *name) {
    assert(!strcmp(name,"display.anti_aliasing"));config_reads++;return pending_setting;
}
static void native_fail(const char *operation,int status) {
    failed_operation=operation;failed_status=status;longjmp(failure,1);
}
static void require_status(const char *operation,int status) {
    if(status)native_fail(operation,status);
}
static struct native_resource *target_get(const void *surface) {
    assert(surface==device.render_target);target_reads++;return &target;
}
static struct halo_metal_render_dimensions resource_dimensions(const struct native_resource *r) {
    return (struct halo_metal_render_dimensions){r->description.width,r->description.height,
        r->storage_width,r->storage_height,r->scale_mode};
}
static void packet_begin(uint32_t size,const void *payload,unsigned count) {
    assert(!payload && !count && size==sizeof(command));reserved_size=size;begins++;
}
static void command_append(const void *record,uint32_t size) {
    assert(size==reserved_size && size==sizeof(command));memcpy(&command,record,size);appends++;
}
static void packet_finish(void) { assert(appends==begins);finishes++; }
/* PRODUCTION */
static void reset(void) {
    memset(&device,0,sizeof(device));memset(&transport,0,sizeof(transport));memset(&target,0,sizeof(target));
    memset(&command,0,sizeof(command));target_reads=begins=appends=finishes=0;
    failed_status=0;failed_operation=NULL;
    config_reads=0;pending_setting="fxaa";
    device.antialiasing_enabled=1;
    device.ready=1;device.render_target=&target;device.depth_stencil=(void *)(uintptr_t)16;
    device.antialias_passes=7;device.resource_serial=40;
    memset(device.viewport,0x29,sizeof(device.viewport));memset(device.constants,0x37,sizeof(device.constants));
    memset(device.transforms,0x47,sizeof(device.transforms));memset(device.render_state,0x57,sizeof(device.render_state));
    memset(device.texture_state,0x67,sizeof(device.texture_state));
    transport.reply.capabilities=HALO_METAL_CAP_FXAA;
    target.ref=(struct halo_metal_ref){29,3};target.format=HALO_METAL_BGRA8;
    target.description.width=738;target.description.height=480;
    target.storage_width=3600;target.storage_height=2338;target.scale_mode=HALO_METAL_RENDER_SCALE_NATIVE_AXES;
    target.last_rendered=17;
}
static struct mock_device original_device;
static struct native_resource original_target;
static void snapshot(void) { original_device=device;original_target=target; }
static void check_state(void) {
    struct mock_device after=device;
    after.antialias_passes=original_device.antialias_passes;
    after.resource_serial=original_device.resource_serial;
    assert(!memcmp(&after,&original_device,sizeof(after)));
    struct native_resource resource_after=target;
    resource_after.last_rendered=original_target.last_rendered;
    assert(!memcmp(&resource_after,&original_target,sizeof(resource_after)));
}
static int invoke(long left,long top,long right,long bottom) {
    failed_status=0;failed_operation=NULL;snapshot();
    if(!setjmp(failure))halo_metal_antialias_before_hud(left,top,right,bottom);
    check_state();return failed_status;
}
static void expected(uint32_t x,uint32_t y,uint32_t width,uint32_t height) {
    assert(command.command.opcode==HALO_METAL_FXAA && !command.command.byte_size);
    assert(command.source.id==29 && command.source.generation==3);
    assert(command.x==x && command.y==y && command.width==width && command.height==height);
    assert(begins==appends && appends==finishes);
}
static void unchanged_queue(void) {
    assert(!begins && !appends && !finishes);
    assert(device.antialias_passes==7 && device.resource_serial==40 && target.last_rendered==17);
}
int main(int argc,char **argv) {
    assert(argc==2);reset();
    if(!strcmp(argv[1],"native")) {
        assert(!invoke(0,0,738,480));expected(0,0,3600,2338);
        assert(device.antialias_passes==8 && device.resource_serial==41 && target.last_rendered==41);
    } else if(!strcmp(argv[1],"splits")) {
        assert(!invoke(0,0,369,240));expected(0,0,1800,1169);
        assert(!invoke(369,0,738,240));expected(1800,0,1800,1169);
        assert(!invoke(0,240,369,480));expected(0,1169,1800,1169);
        assert(!invoke(369,240,738,480));expected(1800,1169,1800,1169);
        assert(appends==4 && device.antialias_passes==11 && device.resource_serial==44);
    } else if(!strcmp(argv[1],"rounded")) {
        target.storage_width=1661;target.storage_height=1080;target.scale_mode=HALO_METAL_RENDER_SCALE_UNIFORM;
        assert(!invoke(0,0,369,240));expected(0,0,830,540);
        assert(!invoke(369,240,738,480));expected(830,540,831,540);
        assert(!invoke(1,1,2,2));expected(2,2,3,3);
    } else if(!strcmp(argv[1],"small")) {
        target.description.width=640;target.storage_width=1;target.storage_height=1;
        assert(!invoke(0,0,1,1));unchanged_queue();
    } else if(!strcmp(argv[1],"off")) {
        device.antialiasing_enabled=0;device.render_target=NULL;device.visibility_test_active=1;
        transport.reply.capabilities=0;assert(!invoke(-1,-2,9999,9999));unchanged_queue();assert(!target_reads);
        reset();device.ready=0;transport.reply.capabilities=0;assert(!invoke(0,0,738,480));
        unchanged_queue();assert(!target_reads);
    } else if(!strcmp(argv[1],"pending")) {
        /* Saving Off keeps this launch's initialized FXAA mode active. */
        pending_setting="off";
        assert(!invoke(0,0,738,480));expected(0,0,3600,2338);
        assert(!config_reads && device.antialiasing_enabled);
        /* Saving FXAA on an Off host cannot request its absent capability. */
        reset();device.antialiasing_enabled=0;transport.reply.capabilities=0;
        assert(!invoke(0,0,738,480));unchanged_queue();assert(!config_reads);
    } else if(!strcmp(argv[1],"empty")) {
        assert(!invoke(50,20,50,200));unchanged_queue();
        assert(!invoke(738,480,738,480));unchanged_queue();
    } else if(!strcmp(argv[1],"invalid")) {
        const long bounds[][4]={{-1,0,738,480},{0,-1,738,480},{2,0,1,480},
            {0,2,738,1},{0,0,739,480},{0,0,738,481}};
        for(unsigned i=0;i<sizeof(bounds)/sizeof(bounds[0]);i++) {
            reset();assert(invoke(bounds[i][0],bounds[i][1],bounds[i][2],bounds[i][3])==HALO_METAL_INVALID);
            assert(strstr(failed_operation,"viewport"));unchanged_queue();
        }
        reset();target.format=HALO_METAL_RGBA8;assert(invoke(0,0,738,480)==HALO_METAL_INVALID);unchanged_queue();
    } else if(!strcmp(argv[1],"capability")) {
        transport.reply.capabilities=0;assert(invoke(0,0,738,480)==HALO_METAL_UNSUPPORTED);
        unchanged_queue();assert(!target_reads);
    } else if(!strcmp(argv[1],"query")) {
        device.visibility_test_active=1;assert(invoke(0,0,738,480)==HALO_METAL_INVALID);
        unchanged_queue();assert(!target_reads);
        reset();device.render_target=NULL;assert(invoke(0,0,738,480)==HALO_METAL_INVALID);
        unchanged_queue();assert(!target_reads);
    } else if(!strcmp(argv[1],"overflow")) {
        device.antialias_passes=UINT64_MAX;assert(invoke(0,0,738,480)==HALO_METAL_MEMORY);
        assert(!begins && !appends && !finishes && device.resource_serial==40 && target.last_rendered==17);
        reset();device.resource_serial=UINT64_MAX;assert(invoke(0,0,738,480)==HALO_METAL_MEMORY);
        assert(!begins && !appends && !finishes && device.antialias_passes==7 && target.last_rendered==17);
    } else abort();
    return 0;
}
'''

GATE = r'''
#include <assert.h>
typedef unsigned char byte;
typedef unsigned short word;
#include "source/math/integer_math.h"
struct render_camera { rectangle2d viewport_bounds; };
enum { _render_target_primary=0,_render_target_secondary=1 };
static long call_count,edges[4];
void halo_metal_antialias_before_hud(long left,long top,long right,long bottom) {
    call_count++;edges[0]=left;edges[1]=top;edges[2]=right;edges[3]=bottom;
}
static void render_gate(short rasterizer_target,const struct render_camera *rasterizer_camera) {
    (void)rasterizer_target;(void)rasterizer_camera;
    /* GATE */
}
int main(void) {
    struct render_camera camera={.viewport_bounds={.x0=369,.y0=240,.x1=738,.y1=480}};
    render_gate(_render_target_secondary,&camera);assert(!call_count);
    render_gate(_render_target_primary,&camera);
#if defined(HALO_MACOS_NATIVE_METAL) && HALO_MACOS_NATIVE_METAL
    assert(call_count==1 && edges[0]==369 && edges[1]==240 && edges[2]==738 && edges[3]==480);
#else
    assert(!call_count);
#endif
    return 0;
}
'''


class WorldAntialiasHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-world-aa-cpu-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        production = GUEST.read_text()
        functions = "\n".join(function(production, name) for name in
                              ("rendered_serial_next", "halo_metal_antialias_before_hud"))
        source = cls.directory / "world_aa.c"
        source.write_text(HARNESS.replace("/* PRODUCTION */", functions))
        cls.binary = cls.directory / "world_aa"
        result = subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-DHALO_MACOS_NATIVE_METAL=1", "-I", str(ROOT), str(source),
                        str(ROOT / "port/linux/src/metal_render_scale.c"), "-o", str(cls.binary)],
                       capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_native_viewport_and_state_preservation(self):
        self.run_case("native")

    def test_four_views_keep_shared_edges_and_separate_commands(self):
        self.run_case("splits")

    def test_uniform_rounding_uses_absolute_edges(self):
        self.run_case("rounded")

    def test_subpixel_viewport_does_not_emit_empty_command(self):
        self.run_case("small")

    def test_disabled_and_uninitialized_skip_resource_and_capability_work(self):
        self.run_case("off")

    def test_empty_valid_viewports_skip_commands(self):
        self.run_case("empty")

    def test_pending_saved_mode_never_changes_startup_capability_or_filter(self):
        self.run_case("pending")

    def test_invalid_bounds_and_format_fail_before_commands(self):
        self.run_case("invalid")

    def test_missing_capability_fails_before_target_access(self):
        self.run_case("capability")

    def test_active_visibility_query_or_missing_target_rejects(self):
        self.run_case("query")

    def test_counter_overflow_fails_before_commands(self):
        self.run_case("overflow")

    def test_real_render_hook_skips_reflections_and_angle_builds(self):
        source = RENDER.read_text()
        start = source.rfind("static void render_window(")
        self.assertGreater(start, 0)
        window = function(source[start:], "render_window")
        gate = re.search(r"#if[^\n]*HALO_MACOS_NATIVE_METAL[^\n]*\n(?:(?!#endif).)*"
                         r"halo_metal_antialias_before_hud\((?:(?!#endif).)*#endif", window, re.S)
        self.assertIsNotNone(gate, "The native-only pre-HUD hook is missing")
        self.assertLess(window.index("rasterizer_lens_flares_draw();"), gate.start())
        self.assertLess(gate.end(), window.index("interface_draw_screen();"))
        self.assertLess(window.index("if (!bink_playback_in_progress())"), gate.start())
        self.assertLess(window.index("interface_draw_screen();"), window.index("rasterizer_screen_flash();"))
        path = self.directory / "render_gate.c"
        path.write_text(GATE.replace("/* GATE */", gate.group()))
        for native in (0, 1):
            binary = self.directory / f"render_gate_{native}"
            subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                            f"-DHALO_MACOS_NATIVE_METAL={native}", "-I", str(ROOT), str(path),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
