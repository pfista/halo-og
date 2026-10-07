"""Exercise production UI ownership and the gameplay input gate without a game.

The active-widget query, frame capture, inhibit query, input clear, and input-blob
decision before device sampling are production code. Downstream device mapping
uses one deterministic sampler so this focused fixture requires no units, tags,
aim assist, graphics, controllers, or game assets. It verifies which seats reach
that sampler, neutral menu input, raw-state preservation, and frame-close capture;
it does not establish interactive controller-to-game behavior or Xbox parity.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef unsigned char byte, boolean;
typedef unsigned short word;
typedef float real;
typedef struct { real i,j; } real_vector2d;
typedef struct { real yaw,pitch; } real_euler_angles2d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MAXIMUM_NUMBER_OF_LOCAL_PLAYERS 4
#define FLAG(i) (1U << (i))
#define TEST_FLAG(v,i) (((v) & FLAG(i)) != 0)
#define SET_FLAG(v,i,state) ((v) = (state) ? ((v) | FLAG(i)) : ((v) & ~FLAG(i)))
#define csmemset memset
#define match_vassert(f,l,c,message) assert(c)
/* DECLARATIONS */
struct widget { short local_player_index; };
static struct {
    boolean initialized;
    struct widget *active_widgets[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
} widget_globals;
static word ui_widget_player_input_capture_mask;
static struct widget widgets[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
struct player_control { real look_acceleration_time; };
struct player_datum { short local_player_index; };
static struct player_control controls[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static struct player_datum players[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static long local_players[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static short debug_input_target;
static unsigned samples[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static struct input_blob raw_inputs[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static long local_player_get_player_index(short seat) { return local_players[seat]; }
static struct player_control *player_control_get(short seat) { return &controls[seat]; }
static struct player_datum *player_get(long player) { return &players[player]; }
static void fixture_device_sample(short seat,short gamepad,boolean primary,real delta,struct input_blob *input) {
    (void)primary;(void)delta;
    assert(gamepad>=0 && gamepad<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS);
    ++samples[seat];*input=raw_inputs[gamepad];
}
/* FUNCTIONS */
'''

HARNESS = r'''
static void reset(void) {
    memset(&widget_globals,0,sizeof(widget_globals));widget_globals.initialized=TRUE;
    ui_widget_player_input_capture_mask=0;
    memset(samples,0,sizeof(samples));memset(raw_inputs,0,sizeof(raw_inputs));
    for(short seat=0;seat<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;seat++) {
        local_players[seat]=seat;players[seat].local_player_index=seat;
        controls[seat].look_acceleration_time=.8f+seat;
        widgets[seat].local_player_index=seat;
        raw_inputs[seat].throttle=(real_vector2d){1.f,-.5f};
        raw_inputs[seat].facing_delta=(real_euler_angles2d){.1f,.2f};
        raw_inputs[seat].primary_trigger=1.f;
        raw_inputs[seat].unit_control_flags=0xFFFF;
        raw_inputs[seat].player_control_flags=0xFFFF;
        raw_inputs[seat].accept=raw_inputs[seat].back=TRUE;
    }
}
static void neutral(short seat) {
    struct input_blob input,zero={0};memset(&input,0xFA,sizeof(input));
    get_local_player_input_blob(seat,1.f/60.f,&input);
    assert(!memcmp(&input,&zero,sizeof(input)) && !samples[seat]);
    assert(controls[seat].look_acceleration_time==0.f);
}
static void sampled(short seat) {
    struct input_blob input;unsigned before=samples[seat];
    get_local_player_input_blob(seat,1.f/60.f,&input);
    assert(samples[seat]==before+1);
    assert(!memcmp(&input,&raw_inputs[players[local_players[seat]].local_player_index],sizeof(input)));
}
static void owner(void) {
    reset();
    /* A stack slot and its controller owner need not have the same index. */
    widget_globals.active_widgets[0]=&widgets[3];
    struct input_blob raw_before[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
    memcpy(raw_before,raw_inputs,sizeof(raw_before));
    for(short seat=0;seat<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;seat++)
        assert(ui_widgets_active_for_local_player(seat)==(seat==3));
    neutral(3);sampled(1);
    assert(controls[1].look_acceleration_time==1.8f);
    assert(!memcmp(raw_before,raw_inputs,sizeof(raw_before)));
    /* More than one menu preserves each controller's ownership. */
    widget_globals.active_widgets[2]=&widgets[1];
    assert(ui_widgets_active_for_local_player(1) && ui_widgets_active_for_local_player(3));
    assert(!ui_widgets_active_for_local_player(0) && !ui_widgets_active_for_local_player(2));
}
static void global(void) {
    reset();widgets[2].local_player_index=NONE;
    widget_globals.active_widgets[1]=&widgets[2];
    for(short seat=0;seat<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;seat++) {
        assert(ui_widgets_active_for_local_player(seat));neutral(seat);
    }
    widget_globals.initialized=FALSE;ui_widget_player_input_capture_mask=0xFFFF;
    for(short seat=0;seat<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;seat++) {
        assert(!ui_widgets_active_for_local_player(seat));
        assert(!ui_widgets_inhibit_player_input(seat));sampled(seat);
    }
}
static void close_frame(void) {
    reset();widget_globals.active_widgets[0]=&widgets[3];
    ui_widgets_capture_player_input();widget_globals.active_widgets[0]=NULL;
    assert(!ui_widgets_active_for_local_player(3));
    assert(ui_widgets_inhibit_player_input(3));
    neutral(3);sampled(1);
    ui_widgets_capture_player_input();
    assert(!ui_widgets_inhibit_player_input(3));sampled(3);
    /* A shared UI captures all seats for its closing frame, then releases. */
    reset();widgets[0].local_player_index=NONE;
    widget_globals.active_widgets[3]=&widgets[0];
    ui_widgets_capture_player_input();widget_globals.active_widgets[3]=NULL;
    for(short seat=0;seat<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;seat++)neutral(seat);
    ui_widgets_capture_player_input();
    for(short seat=0;seat<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;seat++)sampled(seat);
}
static void open_frame(void) {
    reset();ui_widgets_capture_player_input();
    widget_globals.active_widgets[2]=&widgets[1];
    /* Opening after the capture step still blocks via current ownership. */
    assert(!TEST_FLAG(ui_widget_player_input_capture_mask,1));
    neutral(1);sampled(2);
}
static void missing_player(void) {
    reset();local_players[2]=NONE;
    struct input_blob input,zero={0};memset(&input,0xFA,sizeof(input));
    get_local_player_input_blob(2,1.f/60.f,&input);
    assert(!memcmp(&input,&zero,sizeof(input)) && !samples[2]);
    /* Device routing follows the player rather than a widget stack slot. */
    players[1].local_player_index=3;sampled(1);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"owner"))owner();
    else if(!strcmp(argv[1],"global"))global();
    else if(!strcmp(argv[1],"close"))close_frame();
    else if(!strcmp(argv[1],"open"))open_frame();
    else if(!strcmp(argv[1],"missing"))missing_player();
    else assert(0);
    return 0;
}
'''


def fixture():
    controls = (ROOT / "source/game/player_control.c").read_text()
    widgets = (ROOT / "source/interface/ui_widget.c").read_text()
    functions = [block(widgets, signature) for signature in (
        "boolean ui_widgets_active_for_local_player(\n",
        "boolean ui_widgets_inhibit_player_input(\n",
        "static void ui_widgets_capture_player_input(void)\n{",
    )]
    functions.append(block(controls, "static void player_action_clear(\n\tstruct input_blob *input)\n{"))
    input_function = block(controls, "static void get_local_player_input_blob(\n\tshort local_player_index,\n\treal time_delta_sec,\n\tstruct input_blob *input)\n{")
    # Retain production ownership, input-clear, and early-return statements.
    # Replace the remaining device mapping with an observable fixture sampler.
    sampling = "\t\tif (gamepad_index != NONE && input_has_gamepad(gamepad_index))"
    decision = input_function[:input_function.index(sampling)]
    decision += "\t\tfixture_device_sample(local_player_index,gamepad_index,is_primary_player,time_delta_sec,input);\n\t}\n}\n"
    functions.append(decision)
    result = PREFIX.replace("/* DECLARATIONS */", block(controls, "struct input_blob\n") + ";")
    result = result.replace("/* FUNCTIONS */", "\n\n".join(functions)) + HARNESS
    result = re.sub(r"\bunsigned\s+long\b", "uint32_t", result)
    return re.sub(r"\blong\b", "int32_t", result)


class MenuGameplayInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-menu-gameplay-input-")
        source = Path(cls.temporary.name) / "fixture.c"
        source.write_text(fixture())
        cls.binary = source.with_name("fixture.exe" if sys.platform == "win32" else "fixture")
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A native C compiler is required")
        result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                                 "-Wno-unused-function", str(source), "-o", str(cls.binary)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_menu_blocks_only_its_owner_and_preserves_raw_controller_state(self):
        self.run_case("owner")

    def test_shared_menu_blocks_all_seats_and_uninitialized_ui_does_not_block(self):
        self.run_case("global")

    def test_menu_closing_frame_stays_neutral_then_allows_fresh_input(self):
        self.run_case("close")

    def test_menu_opened_after_frame_capture_blocks_immediately(self):
        self.run_case("open")

    def test_absent_player_clears_input_and_present_player_keeps_device_routing(self):
        self.run_case("missing")


if __name__ == "__main__":
    unittest.main()
