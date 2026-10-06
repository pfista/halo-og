"""Exercise Xbox stick response, native input handoff and optional yaw acceleration."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"
SDL = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))

ENGINE_PREFIX = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define TRUE 1
#define FALSE 0
#define SHORT_MAX 32767
#define SHORT_MIN (-32768)
enum { GAMEPAD_STICK_DEAD_RANGE=9000, _gamepad_stick_left=0, _gamepad_stick_right=1 };
typedef struct { short sThumbLX,sThumbLY,sThumbRX,sThumbRY; } XINPUT_GAMEPAD;
struct gamepad_state { struct { short x,y; } sticks[2]; };
struct game_input_preferences { short joystick_controls; };
static long left_deadzone=9000,right_deadzone=9000;
static short joystick_controls;
#ifndef CONTROLLER_BACKEND_FIXTURE
static unsigned physical_axes=15u;
unsigned halo_controller_physical_axes(short index) {
    assert(index>=0 && index<4);return physical_axes;
}
#endif
long config_integer(const char *name) {
    assert(!strcmp(name,"input.left_stick_deadzone") || !strcmp(name,"input.right_stick_deadzone"));
    return !strcmp(name,"input.left_stick_deadzone") ? left_deadzone : right_deadzone;
}
static void input_abstraction_get_local_player_preferences(short index,struct game_input_preferences *p) {
    assert(index>=0 && index<4);p->joystick_controls=joystick_controls;
}
'''


def compile_and_run(source, *, flags=(), inputs=(), sdl=False):
    with tempfile.TemporaryDirectory(prefix="halo-controller-settings-") as temporary:
        directory = Path(temporary)
        # The helper must also work with consumers' small port_config stubs.
        (directory / "port_config.h").write_text(
            "long config_integer(const char *name); int config_boolean(const char *name);\n")
        path = directory / "fixture.c"
        path.write_text(source)
        executable = directory / ("fixture.exe" if sys.platform == "win32" else "fixture")
        command = ["clang", "-std=gnu89", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-function", "-Wno-unused-variable",
                   "-I", str(directory), "-iquote", str(ROOT / "port/linux/include"),
                   "-I", str(PORT), *flags]
        if sys.platform != "win32":
            command += ["-fsanitize=undefined"]
        if sdl:
            command += ["-I", str(SDL / "include"), "-pthread"]
        command += [str(path), *map(str, inputs), "-o", str(executable)]
        if sys.platform != "win32":
            command += ["-lm"]
        compiled = subprocess.run(command, text=True, capture_output=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        tested = subprocess.run([str(executable)], text=True, capture_output=True, timeout=10)
        if tested.returncode:
            raise AssertionError(tested.stderr)


class ControllerSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang"):
            raise unittest.SkipTest("clang required")
        source = (ROOT / "source/input/input_xbox.c").read_text()
        cls.fix = block(source, "short fix_dead_zone(")
        cls.update = block(source, "static void input_update_gamepad_sticks(")
        cls.look = "\n".join(block(source, signature) for signature in (
            "static int controller_look_axis_active(", "int halo_controller_look_active("))

    def test_native_ranges_default_equivalence_and_live_per_stick_settings(self):
        harness = r'''
static int reference(int value,int deadzone) {
    /* Evaluate the signed Xbox axial formula independently in wide integers. */
    if(value>deadzone) return (int)(((int64_t)value-deadzone)*32767/(32767-deadzone));
    if(value<-deadzone) return (int)(((int64_t)value+deadzone)*-32768/(-32768+deadzone));
    return 0;
}
int main(void) {
    static const int presets[]={0,3277,6553,9000,9830,13107,16000};
    struct gamepad_state state;
    XINPUT_GAMEPAD raw;
    unsigned p;
    int v,previous;
    assert(halo_controller_deadzone(-1)==9000);
    assert(halo_controller_deadzone(16001)==9000);
    assert(halo_controller_deadzone(LONG_MIN)==9000 && halo_controller_deadzone(LONG_MAX)==9000);
    for(p=0;p<sizeof(presets)/sizeof(presets[0]);p++) {
        left_deadzone=right_deadzone=presets[p];previous=-32768;
        for(v=-32768;v<=32767;v++) {
            int processed=fix_dead_zone((short)v,(short)presets[p]);
            assert(processed==reference(v,presets[p]) && processed>=previous);
            previous=processed;
            raw.sThumbLX=raw.sThumbLY=raw.sThumbRX=raw.sThumbRY=(short)v;
            input_update_gamepad_sticks(0,&state,&raw);
            assert(state.sticks[0].x==processed && state.sticks[0].y==processed);
            assert(state.sticks[1].x==processed && state.sticks[1].y==processed);
            assert(raw.sThumbLX==v && raw.sThumbLY==v && raw.sThumbRX==v && raw.sThumbRY==v);
        }
        assert(fix_dead_zone(-32768,(short)presets[p])==-32768);
        assert(fix_dead_zone(32767,(short)presets[p])==32767);
        assert(!fix_dead_zone((short)presets[p],(short)presets[p]));
        assert(!fix_dead_zone((short)-presets[p],(short)presets[p]));
    }
    raw.sThumbLX=raw.sThumbRX=7000;raw.sThumbLY=raw.sThumbRY=-7000;
    left_deadzone=3277;right_deadzone=9000;input_update_gamepad_sticks(0,&state,&raw);
    assert(state.sticks[0].x>0 && state.sticks[0].y<0 && !state.sticks[1].x && !state.sticks[1].y);
    left_deadzone=16000;right_deadzone=0;input_update_gamepad_sticks(0,&state,&raw);
    assert(!state.sticks[0].x && !state.sticks[0].y && state.sticks[1].x==7000 && state.sticks[1].y==-7000);
    left_deadzone=-100;right_deadzone=100000;input_update_gamepad_sticks(0,&state,&raw);
    assert(!state.sticks[0].x && !state.sticks[1].x);
    return 0;
}
'''
        compile_and_run(ENGINE_PREFIX + '#include "controller_settings.h"\n' +
                        self.fix + self.update + harness, flags=("-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16",))

    def test_retail_path_keeps_fixed_xbox_deadzone(self):
        harness = r'''
int main(void) {
    XINPUT_GAMEPAD raw={8000,-9000,16000,-32768};
    struct gamepad_state state;
    left_deadzone=right_deadzone=0;
    input_update_gamepad_sticks(0,&state,&raw);
    assert(!state.sticks[0].x && !state.sticks[0].y);
    assert(state.sticks[1].x==fix_dead_zone(16000,9000) && state.sticks[1].y==-32768);
    return 0;
}
'''
        compile_and_run(ENGINE_PREFIX + self.fix + self.update + harness)

    def test_mouse_handoff_uses_each_profiles_actual_look_axes(self):
        harness = r'''
int main(void) {
    static const int looks[4][4]={{0,0,1,1},{1,1,0,0},{1,0,0,1},{0,1,1,0}};
    short values[4];int layout,axis,sign;
    left_deadzone=3277;right_deadzone=6553;
    for(layout=0;layout<4;layout++) for(axis=0;axis<4;axis++) for(sign=-1;sign<=1;sign+=2) {
        joystick_controls=(short)layout;memset(values,0,sizeof(values));
        values[axis]=(short)(sign*(axis<2 ? 3278 : 6554));
        assert(halo_controller_look_active(0,values[0],values[1],values[2],values[3])==looks[layout][axis]);
        values[axis]=(short)(sign*(axis<2 ? 3277 : 6553));
        assert(!halo_controller_look_active(0,values[0],values[1],values[2],values[3]));
    }
    joystick_controls=0;right_deadzone=9000;
    assert(!halo_controller_look_active(0,0,0,8000,-8000));
    assert(halo_controller_look_active(0,0,0,8001,0)); /* Existing default handoff. */
    right_deadzone=16000;
    assert(!halo_controller_look_active(0,0,0,10000,0));
    assert(halo_controller_look_active(0,0,0,16001,0));
    right_deadzone=0;
    assert(!halo_controller_look_active(0,0,0,0,0));
    assert(halo_controller_look_active(0,0,0,1,0));
    assert(halo_controller_look_active(0,0,0,-32768,32767));
    joystick_controls=99;assert(!halo_controller_look_active(0,32767,32767,32767,32767));
    return 0;
}
'''
        compile_and_run(ENGINE_PREFIX + '#include "controller_settings.h"\n' + self.fix + self.look + harness)

    @unittest.skipUnless((SDL / "include/SDL3/SDL.h").exists(), "SDL3 headers required")
    def test_production_backend_keeps_synthetics_out_of_mouse_arbitration(self):
        source = (PORT / "xinput_sdl.c").read_text()
        constants = "\n".join(re.findall(r"^#define XINPUT_GAMEPAD_.*$",
                              (ROOT / "port/include/xdk/xdk_xbox.h").read_text(), re.M))
        functions = "\n".join(block(source, signature) for signature in (
            "static BYTE analog(", "static void keyboard_gamepad(",
            "static void keyboard_navigation_gamepad(",
            "int halo_linux_mouse_aiming(", "static void mouse_poll(",
            "static unsigned controller_physical_axis_mask(",
            "static SHORT stick(", "static inline void merge_gamepad_state(",
            "static void merge_button(", "static void sdl_gamepad_state(",
            "static int controller_port(", "unsigned halo_controller_physical_axes(",
            "int halo_menu_navigation_read(",
            "DWORD WINAPI XInputGetState("))
        # Use the actual look-axis hook and transform in the backend fixture too.
        prefix = ENGINE_PREFIX.replace(
            "typedef struct { short sThumbLX,sThumbLY,sThumbRX,sThumbRY; } XINPUT_GAMEPAD;", "")
        harness = r'''
#include <stdlib.h>
#include <pthread.h>
#include <SDL3/SDL.h>
typedef int BOOL;
typedef unsigned char BYTE;
typedef char CHAR;
typedef unsigned short WORD;
typedef short SHORT;
typedef unsigned long DWORD;
typedef void *HANDLE;
#include "sdl_platform.h"
#include "input_bindings.h"
#include "controller_settings.h"
#define WINAPI
#define ERROR_SUCCESS 0
#define ERROR_DEVICE_NOT_CONNECTED 1167
#define PORT_COUNT 4
typedef struct { WORD wButtons;BYTE bAnalogButtons[8];SHORT sThumbLX,sThumbLY,sThumbRX,sThumbRY; } XINPUT_GAMEPAD;
typedef struct { DWORD dwPacketNumber;XINPUT_GAMEPAD Gamepad; } XINPUT_STATE,*PXINPUT_STATE;
struct controller { BOOL open;DWORD packet_number;XINPUT_GAMEPAD previous; };
static struct controller controllers[4];
static unsigned controller_physical_axis_flags[4];
static struct halo_menu_navigation_state menu_navigation_states[4];
static BOOL menu_navigation_valid[4];
static pthread_mutex_t mouse_lock=PTHREAD_MUTEX_INITIALIZER;
static Uint64 ticks=100,mouse_aimed_ms,stick_aimed_ms,wheel_moved_ms,wheel_press_until_ms;
static float mouse_pending_x,mouse_pending_y,mouse_wheel_accumulated;
static unsigned long mouse_polls_unconsumed;
static struct platform_input_state input;
static Sint16 axes[SDL_GAMEPAD_AXIS_COUNT];
static bool buttons[SDL_GAMEPAD_BUTTON_COUNT];
static int physical_count,synthetic_look;
Uint64 SDL_GetTicks(void) { return ticks; }
bool SDL_GetGamepadButton(SDL_Gamepad *pad,SDL_GamepadButton button) { (void)pad;return buttons[button]; }
Sint16 SDL_GetGamepadAxis(SDL_Gamepad *pad,SDL_GamepadAxis axis) { (void)pad;return axes[axis]; }
static int sdl_gamepads(SDL_Gamepad *pads[4]) { int i;for(i=0;i<4;i++)pads[i]=(SDL_Gamepad *)1;return physical_count; }
static unsigned char console_is_active(void) { return 0; }
void platform_pump_events(void) {}
void platform_input_read(struct platform_input_state *out,BOOL consume) { (void)consume;*out=input; }
static void wheel_update(void) {}
static unsigned test_input_gamepad(XINPUT_GAMEPAD *pad) {
    if(synthetic_look){pad->sThumbRX=32767;return 4u;}return 0;
}
int config_boolean(const char *name) { (void)name;return 0; }
void platform_log(const char *format,...) { (void)format; }
const char *config_string(const char *name) {
#define BINDING(action,mac,other,comment) if(!strcmp(name,"bindings." #action))return mac;
#include "input_bindings.def"
#undef BINDING
    return "";
}
/* CONSTANTS */
/* BINDINGS */
/* PRODUCTION */
static XINPUT_GAMEPAD poll(void) {
    XINPUT_STATE state;assert(!XInputGetState(&controllers[0],&state));return state.Gamepad;
}
static void aim_mouse(void) {
    input.mouse_dx=1;ticks++;poll();input.mouse_dx=0;assert(halo_linux_mouse_aiming(0));
}
int main(void) {
    XINPUT_GAMEPAD pad;
    struct halo_menu_navigation_state navigation;
    struct gamepad_state processed;
    XINPUT_STATE second;
    int baseline,range;
    controllers[0].open=TRUE;controllers[1].open=TRUE;
    left_deadzone=right_deadzone=0;joystick_controls=1;
    input.keys[SDL_SCANCODE_W]=1;aim_mouse();ticks++;
    pad=poll();assert(pad.sThumbLY==32767 && halo_linux_mouse_aiming(0));
    assert(halo_menu_navigation_read(0,&navigation) && !navigation.left_y);
    assert(!halo_menu_navigation_read(-1,&navigation) && !halo_menu_navigation_read(4,&navigation));
    synthetic_look=1;ticks++;pad=poll();
    assert(pad.sThumbRX==32767 && halo_linux_mouse_aiming(0));synthetic_look=0;
    physical_count=1;ticks++;pad=poll();
    assert(pad.sThumbLY==32767 && !pad.sThumbRY && halo_linux_mouse_aiming(0));
    memset(input.keys,0,sizeof(input.keys));
    left_deadzone=right_deadzone=1000;axes[SDL_GAMEPAD_AXIS_LEFTX]=2000;
    joystick_controls=0;aim_mouse();ticks++;poll();assert(halo_linux_mouse_aiming(0));
    joystick_controls=1;ticks++;poll();assert(!halo_linux_mouse_aiming(0));
    axes[SDL_GAMEPAD_AXIS_LEFTX]=0;axes[SDL_GAMEPAD_AXIS_RIGHTX]=2000;
    joystick_controls=0;aim_mouse();ticks++;pad=poll();
    assert(pad.sThumbRX==2000 && !halo_linux_mouse_aiming(0)); /* No SDL dead-zone filter. */
    right_deadzone=16000;aim_mouse();ticks++;poll();assert(halo_linux_mouse_aiming(0));
    right_deadzone=9000;axes[SDL_GAMEPAD_AXIS_RIGHTX]=8001;
    aim_mouse();ticks++;poll();assert(!halo_linux_mouse_aiming(0));
    memset(axes,0,sizeof(axes));left_deadzone=right_deadzone=0;
    aim_mouse();ticks++;pad=poll();assert(!pad.sThumbLY && !pad.sThumbRY && halo_linux_mouse_aiming(0));
    assert(stick(-32768,TRUE)==32767 && stick(32767,TRUE)==-32768 && !stick(0,TRUE));
    axes[SDL_GAMEPAD_AXIS_RIGHTX]=-32768;ticks++;poll();assert(!halo_linux_mouse_aiming(0));
    assert(!halo_linux_mouse_aiming(1));
    /* Keyboard movement wins a weaker physical stick; buttons still combine. */
    input.keys[SDL_SCANCODE_D]=1;axes[SDL_GAMEPAD_AXIS_LEFTX]=12345;
    buttons[SDL_GAMEPAD_BUTTON_LEFT_SHOULDER]=true;pad=poll();
    assert(pad.sThumbLX==32767 && pad.bAnalogButtons[XINPUT_GAMEPAD_BLACK]==255);
    assert(halo_menu_navigation_read(0,&navigation) && navigation.left_x==12345 &&
        (navigation.physical_axes & HALO_CONTROLLER_AXIS_LEFT_X));
    input.keys[SDL_SCANCODE_LEFT]=1;buttons[SDL_GAMEPAD_BUTTON_DPAD_UP]=true;pad=poll();
    assert((pad.wButtons & (XINPUT_GAMEPAD_DPAD_LEFT | XINPUT_GAMEPAD_DPAD_UP))==
        (XINPUT_GAMEPAD_DPAD_LEFT | XINPUT_GAMEPAD_DPAD_UP));
    assert(halo_menu_navigation_read(0,&navigation) && navigation.dpad==XINPUT_GAMEPAD_DPAD_UP);
    input.keys[SDL_SCANCODE_LEFT]=0;buttons[SDL_GAMEPAD_BUTTON_DPAD_UP]=false;
    /* Controller settings cannot alter W+D's established keyboard diagonal. */
    memset(axes,0,sizeof(axes));memset(input.keys,0,sizeof(input.keys));
    input.keys[SDL_SCANCODE_W]=input.keys[SDL_SCANCODE_D]=1;
    pad=poll();baseline=fix_dead_zone(pad.sThumbLX,9000);
    for(range=0;range<=16000;range+=16000) {
        left_deadzone=right_deadzone=range;pad=poll();
        assert(!halo_controller_physical_axes(0));
        input_update_gamepad_sticks(0,&processed,&pad);
        assert(processed.sticks[0].x==baseline && processed.sticks[0].y==baseline);
        /* Select the stronger raw physical X; keep keyboard Y at stock response. */
        axes[SDL_GAMEPAD_AXIS_LEFTX]=30000;pad=poll();
        assert(halo_controller_physical_axes(0)==HALO_CONTROLLER_AXIS_LEFT_X);
        input_update_gamepad_sticks(0,&processed,&pad);
        assert(pad.sThumbLX==30000 && processed.sticks[0].x==fix_dead_zone(30000,(short)range));
        assert(processed.sticks[0].y==baseline);
        axes[SDL_GAMEPAD_AXIS_LEFTX]=(Sint16)-pad.sThumbLY;pad=poll();
        assert(!halo_controller_physical_axes(0) && pad.sThumbLX==pad.sThumbLY); /* Tie keeps keyboard. */
        axes[SDL_GAMEPAD_AXIS_LEFTX]=0;
    }
    /* Script overrides retain baseline even when writing the physical value. */
    memset(input.keys,0,sizeof(input.keys));right_deadzone=16000;
    axes[SDL_GAMEPAD_AXIS_RIGHTX]=32767;synthetic_look=1;aim_mouse();ticks++;pad=poll();
    assert(!(halo_controller_physical_axes(0)&HALO_CONTROLLER_AXIS_RIGHT_X));
    assert(halo_linux_mouse_aiming(0));synthetic_look=0;
    assert(!halo_controller_physical_axes(-1) && !halo_controller_physical_axes(4));
    physical_count=2;axes[SDL_GAMEPAD_AXIS_RIGHTX]=20000;
    assert(!XInputGetState(&controllers[1],&second) && halo_controller_physical_axes(1)==15u);
    input_update_gamepad_sticks(1,&processed,&second.Gamepad);
    assert(processed.sticks[1].x==fix_dead_zone(20000,16000));
    physical_count=0;pad=poll();assert(!halo_controller_physical_axes(0));
    puts("Controller backend handoff passed");return 0;
}
'''
        bindings = (PORT / "input_bindings.c").read_text().replace('#include "platform.h"', "")
        harness = prefix + harness.replace("/* CONSTANTS */", constants).replace("/* BINDINGS */", bindings).replace(
            "/* PRODUCTION */", self.fix + self.update + self.look + functions)
        compile_and_run(harness, flags=("-DHALO_MACOS=1", "-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16",
                                      "-DCONTROLLER_BACKEND_FIXTURE=1"), sdl=True)


ACCELERATION_PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <string.h>
typedef float real;
typedef int boolean;
typedef struct { real yaw,pitch; } real_euler_angles2d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define TICKS_PER_SECOND 30
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define PIN(v,a,b) MIN(MAX(v,a),b)
static int acceleration_enabled=1,assertion_calls,config_reads;
#define match_assert(file,line,condition) do { assertion_calls++;assert(condition); } while(0)
struct player_control { real look_acceleration_time;short zoom_level; };
struct game_globals_player_control {
    real look_acceleration_time,look_acceleration_scale,look_pegging_threshold;
    struct { short count;real *address; } look_function;
};
int config_boolean(const char *name) {
    assert(!strcmp(name,"input.look_acceleration"));config_reads++;return acceleration_enabled;
}
'''

# Snapshot of the original yaw-only Xbox block, before the preference wrapper.
ORIGINAL_ACCELERATION = r'''
static void original_acceleration(struct player_control *control,
    struct game_globals_player_control const *constants,real clamped_yaw,
    real time_delta_sec,real_euler_angles2d *look_delta) {
    match_assert("c:\\halo\\SOURCE\\game\\player_control.c",0x1E3,
        constants->look_acceleration_time>0.0f);
    if(fabs(clamped_yaw)>=constants->look_pegging_threshold) {
        real acceleration=PIN(control->look_acceleration_time/constants->look_acceleration_time,0.f,1.f);
        look_delta->yaw*=(constants->look_acceleration_scale-1.f)*acceleration+1.f;
        control->look_acceleration_time+=time_delta_sec;
    } else control->look_acceleration_time=0.f;
}
'''


class ControllerAccelerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang"):
            raise unittest.SkipTest("clang required")
        cls.source = (ROOT / "source/game/player_control.c").read_text()
        cls.helper = block(cls.source, "static void player_control_apply_look_acceleration(")

    def test_xbox_bit_exact_ramp_and_live_off_on_reset(self):
        harness = r'''
int main(void) {
    static const real thresholds[]={-.1f,0.f,.5f,.95f,1.f,1.1f};
    static const real scales[]={0.f,.35f,1.f,2.f,4.f};
    static const real durations[]={.05f,.25f,.8f,1.f};
    static const real steps[]={.016666667f,.033333335f,.1f};
    unsigned h,s,d,t;int frame,sign;
    struct game_globals_player_control constants={0};
    struct player_control actual,reference;
    real_euler_angles2d a,b;
    for(h=0;h<sizeof(thresholds)/sizeof(thresholds[0]);h++)
    for(s=0;s<sizeof(scales)/sizeof(scales[0]);s++)
    for(d=0;d<sizeof(durations)/sizeof(durations[0]);d++)
    for(t=0;t<sizeof(steps)/sizeof(steps[0]);t++)
    for(sign=-1;sign<=1;sign+=2) {
        constants.look_pegging_threshold=thresholds[h];constants.look_acceleration_scale=scales[s];
        constants.look_acceleration_time=durations[d];actual.look_acceleration_time=reference.look_acceleration_time=-.1f;
        for(frame=0;frame<200;frame++) {
            real yaw=(frame%13==0 ? thresholds[h]-.00001f : frame%13==1 ? thresholds[h] :
                      frame%13==2 ? thresholds[h]+.00001f : 1.f)*sign;
            a.yaw=b.yaw=sign*.1234567f;a.pitch=b.pitch=-.7654321f;
            player_control_apply_look_acceleration(&actual,&constants,yaw,steps[t],&a);
            original_acceleration(&reference,&constants,yaw,steps[t],&b);
            assert(!memcmp(&a,&b,sizeof(a)));
            assert(!memcmp(&actual.look_acceleration_time,&reference.look_acceleration_time,sizeof(real)));
        }
    }
    constants.look_pegging_threshold=.95f;constants.look_acceleration_scale=3.f;constants.look_acceleration_time=.25f;
    actual.look_acceleration_time=10.f;acceleration_enabled=0;a.yaw=5.f;a.pitch=7.f;
    assertion_calls=0;player_control_apply_look_acceleration(&actual,&constants,1.f,.1f,&a);
    assert(actual.look_acceleration_time==0.f && a.yaw==5.f && a.pitch==7.f && !assertion_calls);
    acceleration_enabled=1;player_control_apply_look_acceleration(&actual,&constants,1.f,.1f,&a);
    assert(actual.look_acceleration_time==.1f && a.yaw==5.f && a.pitch==7.f && assertion_calls==1);
    player_control_apply_look_acceleration(&actual,&constants,1.f,.1f,&a);
    assert(a.yaw>5.f && a.pitch==7.f);
    player_control_apply_look_acceleration(&actual,&constants,.94f,.1f,&a);
    assert(actual.look_acceleration_time==0.f);
    /* Off also clears accrued time without touching a zero/negative yaw or pitch. */
    acceleration_enabled=0;constants.look_acceleration_time=0.f;actual.look_acceleration_time=2.f;
    a.yaw=-0.f;a.pitch=-2.f;b=a;
    player_control_apply_look_acceleration(&actual,&constants,-1.f,.1f,&a);
    assert(!memcmp(&a,&b,sizeof(a)) && actual.look_acceleration_time==0.f);
    assert(config_reads>0);
    return 0;
}
'''
        compile_and_run(ACCELERATION_PREFIX + self.helper + ORIGINAL_ACCELERATION + harness,
                        flags=("-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16", "-O2"))

    def test_retail_ramp_does_not_read_native_preference(self):
        harness = r'''
int main(void) {
    struct game_globals_player_control constants={.25f,3.f,.95f,{0,0}};
    struct player_control control={1.f,0};real_euler_angles2d look={2.f,3.f};
    acceleration_enabled=0;
    player_control_apply_look_acceleration(&control,&constants,1.f,.1f,&look);
    assert(look.yaw==6.f && look.pitch==3.f && control.look_acceleration_time==1.1f);
    assert(assertion_calls==1 && config_reads==0);return 0;
}
'''
        compile_and_run(ACCELERATION_PREFIX + self.helper + harness)

    def test_production_curve_zoom_stun_and_mouse_pipeline(self):
        input_blob = block(self.source, "static void get_local_player_input_blob(\n\tshort local_player_index,\n"
                          "\treal time_delta_sec,\n\tstruct input_blob *input)\n{")
        start = input_blob.index("look_delta.yaw = evaluate_piecewise_linear_function(")
        end = input_blob.index("real_euler_angles2d target_angular_position;", start)
        # Stop before the surrounding aim-assist block opens.
        pipeline = input_blob[start:end].rsplit("{", 1)[0]
        start = input_blob.index("real facing_scale = time_delta_sec * TICKS_PER_SECOND;")
        facing = input_blob[start:input_blob.index("}", start)]
        mouse = block(input_blob, "if (halo_linux_mouse_look(gamepad_index, &mouse_yaw, &mouse_pitch))")
        curve = block(self.source, "real evaluate_piecewise_linear_function(")
        harness = r'''
struct player_datum { long unit_index; };
struct unit_datum { struct { real body_stun; } unit; };
struct game_globals_player_information { real stun_turning_penalty; };
struct input_blob { real_euler_angles2d facing_delta; };
static struct unit_datum owned_unit={{.2f}};
static struct game_globals_player_information information={.4f};
static real magnification=2.f;
static int mouse_moved;
#define TAG_BLOCK_GET_ELEMENT(block,index,type) ((type *)&information)
static struct unit_datum *unit_get(long index) { assert(index==0);return &owned_unit; }
static real unit_get_zoom_magnification(long index,short zoom) { assert(index==0 && zoom==0);return magnification; }
static int halo_linux_mouse_look(short index,real *yaw,real *pitch) {
    assert(index==0);*yaw=.2f;*pitch=.3f;return mouse_moved;
}
/* CURVE */
/* HELPER */
static struct input_blob run(int enabled,int mouse,short zoom,real initial_time) {
    real values[]={0.f,.1f,1.f};
    struct game_globals_player_control c={.25f,2.f,.95f,{3,values}},*constants=&c;
    struct player_control ctl={initial_time,zoom},*control=&ctl;
    struct player_datum p={0},*player=&p;
    struct input_blob out={0},*input=&out;
    real clamped_yaw=1.f,clamped_pitch=.5f,time_delta_sec=.033333335f;
    real yaw_spin_scale=2.f,pitch_spin_scale=1.f,look_yaw_rate=.1f,look_pitch_rate=.2f;
    short gamepad_index=0;real mouse_yaw,mouse_pitch;
    real_euler_angles2d look_delta;
    acceleration_enabled=enabled;mouse_moved=mouse;
    assertion_calls=config_reads=0;
    /* PIPELINE */
    { /* FACING */ }
    /* MOUSE */
    if(!enabled)assert(control->look_acceleration_time==0.f);
    assert(config_reads==1 && assertion_calls==2+(enabled!=0));
    return out;
}
int main(void) {
    struct input_blob off=run(0,0,0,1.f),xbox=run(1,0,0,1.f);
    struct input_blob off_mouse=run(0,1,0,1.f),xbox_mouse=run(1,1,0,1.f);
    struct input_blob unzoomed=run(0,0,NONE,1.f);
    assert(xbox.facing_delta.yaw==off.facing_delta.yaw*2.f);
    assert(!memcmp(&xbox.facing_delta.pitch,&off.facing_delta.pitch,sizeof(real)));
    assert(fabs(off_mouse.facing_delta.yaw-off.facing_delta.yaw-.1f)<.000001f);
    assert(fabs(xbox_mouse.facing_delta.yaw-xbox.facing_delta.yaw-.1f)<.000001f);
    assert(fabs(off_mouse.facing_delta.pitch-off.facing_delta.pitch-.15f)<.000001f);
    assert(!memcmp(&off_mouse.facing_delta.pitch,&xbox_mouse.facing_delta.pitch,sizeof(real)));
    assert(unzoomed.facing_delta.yaw==off.facing_delta.yaw*2.f);
    assert(unzoomed.facing_delta.pitch==off.facing_delta.pitch*2.f);
    return 0;
}
'''
        harness = harness.replace("/* CURVE */", curve).replace("/* HELPER */", self.helper)
        harness = harness.replace("/* PIPELINE */", pipeline).replace("/* FACING */", facing).replace("/* MOUSE */", mouse)
        compile_and_run(ACCELERATION_PREFIX + harness, flags=("-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16",))


if __name__ == "__main__":
    unittest.main()
