"""Exercise production menu repeat timing with controlled event and clock fixtures.

The event queue and virtual-keyboard dispatcher are compiled from production
functions. The recursive widget's exact D-pad timing blocks are isolated from
its unrelated rendering/widget graph, and normal input hold counting is compiled
unchanged. These checks cover timing logic; they do not measure native UI latency.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    # Some production units put a prototype before the definition.
    return block(source[source.rindex(signature):], signature)


def repeat_macro(source, name):
    definition = source.index(f"#define {name} ")
    start = source.rfind("#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS", 0, definition)
    end = source.index("#endif", definition) + len("#endif")
    return source[start:end]


PREFIX = r'''
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char byte, boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define SHORT_MAX 32767
#define SHORT_MIN (-32768)
#define MAXIMUM_GAMEPADS 4
#define MAXIMUM_NUMBER_OF_LOCAL_PLAYERS 4
#define TICKS_PER_SECOND 30
#define UNSIGNED_CHAR_MAX 255
#define ABS(x) ((x)<0 ? -(x) : (x))
#define MIN(a,b) ((a)<(b) ? (a) : (b))
#define MAX(a,b) ((a)>(b) ? (a) : (b))
#define PIN(v,a,b) MIN(MAX(v,a),b)
#define csmemmove memmove
#define csmemset memset
#define match_assert(file,line,condition) assert(condition)
static unsigned long clock_ms;
static int fast_repeat, config_reads;
static unsigned long system_milliseconds(void) { return clock_ms; }
int config_boolean(const char *name) {
    assert(!strcmp(name,"input.fast_menu_repeat"));
    config_reads++;
    return fast_repeat;
}
long config_integer(const char *name) { (void)name;return 9000; }
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
#include "controller_settings.h"
#endif
struct event_record {
    short type, controller_index;
    union {
        struct { short x,y; } stick;
        struct { byte index,value; } button;
    } data;
};
/* DECLARATIONS */
static struct event_manager_globals event_manager_globals;
enum {
    _widget_event_dpad_up=_gamepad_binary_button_dpad_up,
    _widget_event_dpad_down=_gamepad_binary_button_dpad_down,
    _widget_event_dpad_left=_gamepad_binary_button_dpad_left,
    _widget_event_dpad_right=_gamepad_binary_button_dpad_right,
    NUMBER_OF_DPAD_DIRECTIONS=4
};
static unsigned long dpad_event_times[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS][NUMBER_OF_DPAD_DIRECTIONS];
static struct { unsigned long current_system_milliseconds; } widget_globals;
static struct {
    int row,column,last_event,last_key,buffer_size;
    boolean first_key_replaces_buffer;
    char *cursor,*text_buffer;
    unsigned long time_of_last_event;
} virtual_keyboard_globals;
static int virtual_keyboard_layout_table[5][11];
static unsigned tabs[4],selects,cancels;
static boolean virtual_keyboard_tab_left(void) { tabs[_event_tab_left]++;return TRUE; }
static boolean virtual_keyboard_tab_right(void) { tabs[_event_tab_right]++;return TRUE; }
static boolean virtual_keyboard_tab_up(void) { tabs[_event_tab_up]++;return TRUE; }
static boolean virtual_keyboard_tab_down(void) { tabs[_event_tab_down]++;return TRUE; }
static boolean virtual_keyboard_select(void) { selects++;return TRUE; }
static boolean virtual_keyboard_cancel(void) { cancels++;return TRUE; }
static void virtual_keyboard_backspace(void) {}
static void ui_play_audio_feedback_sound(int sound) { (void)sound; }
/* PRODUCTION */
static int expected_interval(void) {
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    return fast_repeat ? 100 : 250;
#else
    return 250;
#endif
}
static void reset_events(void) {
    memset(&event_manager_globals,0,sizeof(event_manager_globals));
    event_manager_globals.state.initialized=TRUE;
}
static int post_stick(int stick,short x,short y,unsigned long time) {
    struct event_record event,posted;
    memset(&event,0,sizeof(event));
    clock_ms=time;
    event.type=(short)(stick ? _event_type_right_stick : _event_type_left_stick);
    event.data.stick.x=x;event.data.stick.y=y;
    queue_event(&event,0);
    return get_next_event(&posted,0);
}
static int widget_button(int direction,int value,int controller,unsigned long time) {
    struct event_record storage,*event=&storage;
    memset(event,0,sizeof(*event));
    event->type=_event_type_button;event->controller_index=(short)controller;
    event->data.button.index=(byte)direction;event->data.button.value=(byte)value;
    widget_globals.current_system_milliseconds=time;
    /* WIDGET GATE */
    /* WIDGET TIMESTAMP */
    return event->data.button.value;
}
static void keyboard_button(int direction,int value,unsigned long time) {
    struct event_record event;
    memset(&event,0,sizeof(event));
    event.type=_event_type_button;event.data.button.index=(byte)direction;
    event.data.button.value=(byte)value;clock_ms=time;
    queue_event(&event,0);
    virtual_keyboard_process_internal();
}
static void check_stick_repeats(void) {
    int speed,stick;
    for(speed=0;speed<2;speed++) for(stick=0;stick<2;stick++) {
        unsigned long first=1000,interval;
        fast_repeat=speed;interval=(unsigned long)expected_interval();reset_events();
        assert(!post_stick(stick,STICK_EVENT_THRESHOLD-1,0,first));
        assert(post_stick(stick,SHORT_MAX,0,first));
        assert(!post_stick(stick,SHORT_MAX,0,first+interval-1));
        assert(post_stick(stick,SHORT_MAX,0,first+interval));
        assert(!post_stick(stick,SHORT_MAX,0,first+interval+1));
        /* A nonzero subthreshold event reaches queue_event and resets its
         * edge state. event_manager_update skips exact-zero sticks. */
        assert(!post_stick(stick,1,0,first+interval+2));
        assert(post_stick(stick,SHORT_MIN,0,first+interval+3));
        reset_events();fast_repeat=0;
        assert(post_stick(stick,0,SHORT_MAX,2000));
        fast_repeat=1;
        assert(post_stick(stick,0,SHORT_MAX,2000+expected_interval()));
        fast_repeat=0;
        assert(!post_stick(stick,0,SHORT_MAX,2000+expected_interval()));
        assert(post_stick(stick,0,SHORT_MAX,2250+(unsigned long)(
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
            100
#else
            250
#endif
        )));
    }
}
static void check_widget_repeats(void) {
    int speed,direction,controller;
    for(speed=0;speed<2;speed++) for(direction=_widget_event_dpad_up;direction<=_widget_event_dpad_right;direction++)
        for(controller=0;controller<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;controller++) {
        unsigned long first=4000,interval;
        fast_repeat=speed;interval=(unsigned long)expected_interval();
        memset(dpad_event_times,0,sizeof(dpad_event_times));
        assert(widget_button(direction,1,controller,first)==1);
        assert(widget_button(direction,2,controller,first+1)==2);
        assert(widget_button(direction,2,controller,first+interval-1)==2);
        assert(widget_button(direction,2,controller,first+interval)==1);
        assert(widget_button(direction,2,controller,first+interval+1)==2);
        assert(widget_button(direction,1,controller,first+interval+2)==1);
    }
    fast_repeat=0;memset(dpad_event_times,0,sizeof(dpad_event_times));
    assert(widget_button(_widget_event_dpad_up,1,0,6000)==1);
    fast_repeat=1;
    assert(widget_button(_widget_event_dpad_up,2,0,6000+expected_interval())==1);
    fast_repeat=0;
    assert(widget_button(_widget_event_dpad_up,2,0,6000+expected_interval())==2);
    assert(widget_button(_widget_event_dpad_up,2,0,6000+250+(unsigned long)(
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        100
#else
        250
#endif
    ))==1);
    /* Held confirmation buttons remain held; this option only repeats navigation. */
    assert(widget_button(_gamepad_analog_button_a,2,0,10000)==2);
    assert(widget_button(_widget_event_dpad_up,2,-1,10000)==2);
    assert(widget_button(_widget_event_dpad_up,2,MAXIMUM_NUMBER_OF_LOCAL_PLAYERS,10000)==2);
}
static void check_keyboard_repeats(void) {
    static const int directions[]={_gamepad_binary_button_dpad_left,_gamepad_binary_button_dpad_right,
        _gamepad_binary_button_dpad_up,_gamepad_binary_button_dpad_down};
    int speed,direction;
    for(speed=0;speed<2;speed++) for(direction=0;direction<4;direction++) {
        unsigned long first=20000+(unsigned long)(speed*4+direction)*1000,interval;
        fast_repeat=speed;interval=(unsigned long)expected_interval();reset_events();
        memset(&virtual_keyboard_globals,0,sizeof(virtual_keyboard_globals));
        memset(tabs,0,sizeof(tabs));virtual_keyboard_globals.last_event=NONE;
        keyboard_button(directions[direction],1,first);assert(tabs[direction]==1);
        keyboard_button(directions[direction],2,first+1);assert(tabs[direction]==1);
        keyboard_button(directions[direction],2,first+interval-1);assert(tabs[direction]==1);
        keyboard_button(directions[direction],2,first+interval);assert(tabs[direction]==2);
        keyboard_button(directions[direction],2,first+interval+1);assert(tabs[direction]==2);
        keyboard_button(directions[direction],1,first+interval+2);assert(tabs[direction]==3);
        /* Switching direction while held responds immediately. */
        keyboard_button(directions[(direction+1)%4],2,first+interval+3);
        assert(tabs[(direction+1)%4]==1);
    }
    reset_events();fast_repeat=0;
    keyboard_button(_gamepad_binary_button_dpad_up,1,40000);
    { unsigned prior=tabs[_event_tab_up];
        fast_repeat=1;
        keyboard_button(_gamepad_binary_button_dpad_up,2,40000+expected_interval());
        assert(tabs[_event_tab_up]==prior+1);
        fast_repeat=0;
        keyboard_button(_gamepad_binary_button_dpad_up,2,40250);
        assert(tabs[_event_tab_up]==prior+1);
        keyboard_button(_gamepad_binary_button_dpad_up,2,40250+(unsigned long)(
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
            100
#else
            250
#endif
        ));
        assert(tabs[_event_tab_up]==prior+2);
    }
    selects=0;
    keyboard_button(_gamepad_analog_button_a,1,50000);assert(selects==1);
    keyboard_button(_gamepad_analog_button_a,2,51000);assert(selects==1);
    cancels=0;
    keyboard_button(_gamepad_analog_button_b,1,52000);assert(cancels==1);
    keyboard_button(_gamepad_analog_button_b,2,53000);assert(cancels==1);
    keyboard_button(_gamepad_binary_button_back,1,54000);assert(cancels==2);
    keyboard_button(_gamepad_binary_button_back,2,55000);assert(cancels==2);
}
static void check_gameplay_hold_counts(void) {
    byte ticks=0;long down_time=0;int reads=config_reads;
    clock_ms=0;update_hold_ticks(&ticks,&down_time,TRUE);assert(ticks==1);
    fast_repeat=1;clock_ms=10;update_hold_ticks(&ticks,&down_time,TRUE);assert(ticks==2);
    clock_ms=100;update_hold_ticks(&ticks,&down_time,TRUE);assert(ticks==4);
    fast_repeat=0;clock_ms=250;update_hold_ticks(&ticks,&down_time,TRUE);assert(ticks==8);
    clock_ms=500;update_hold_ticks(&ticks,&down_time,TRUE);assert(ticks==16);
    update_hold_ticks(&ticks,&down_time,FALSE);assert(ticks==0);
    clock_ms++;update_hold_ticks(&ticks,&down_time,TRUE);assert(ticks==1);
    assert(config_reads==reads);
}
int main(void) {
    assert(!fast_repeat && expected_interval()==250);
    check_stick_repeats();check_widget_repeats();check_keyboard_repeats();check_gameplay_hold_counts();
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(config_reads>0);
#else
    assert(config_reads==0);
#endif
    puts("menu repeat timing tests passed");
    return 0;
}
'''


class MenuRepeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang"):
            raise unittest.SkipTest("clang required")
        events = (ROOT / "source/interface/event_manager.c").read_text()
        widgets = (ROOT / "source/interface/ui_widget.c").read_text()
        keyboard = (ROOT / "source/interface/virtual_keyboard.c").read_text()
        inputs = (ROOT / "source/input/input.h").read_text()
        hold = (ROOT / "source/input/input_xbox.c").read_text()
        buttons = inputs[inputs.rfind("enum\n", 0, inputs.index("FIRST_GAMEPAD_ANALOG_BUTTON")):]
        sticks = inputs[inputs.rfind("enum\n", 0, inputs.index("_gamepad_stick_left =")):]
        actions = keyboard[keyboard.rfind("enum\n", 0, keyboard.index("\t_event_tab_left,")):]
        constants = []
        for source,name in ((widgets,"DPAD_EVENT_REPEAT_MILLISECONDS"),
                            (keyboard,"VIRTUAL_KEYBOARD_TAB_REPEAT_MILLISECONDS")):
            value = re.search(rf"\b{name}\s*=\s*(\d+)", source)
            if not value:
                raise AssertionError(f"Missing production repeat constant: {name}")
            constants.append(f"enum {{ {name}={value[1]} }};")
        declarations = "\n".join([
            block(buttons,"enum\n")+";", block(sticks,"enum\n")+";",
            block(events,"enum\n")+";", block(actions,"enum\n")+";", *constants,
            "enum { _ui_audio_feedback_cursor };",
            block(events,"struct event_manager_state\n")+";",
            block(events,"struct event_manager_globals\n")+";",
            repeat_macro(events,"MENU_STICK_REPEAT_INTERVAL"),
            repeat_macro(widgets,"MENU_DPAD_REPEAT_INTERVAL"),
            repeat_macro(keyboard,"MENU_KEYBOARD_REPEAT_INTERVAL"),
        ])
        production = "\n".join([
            function(events,"static void queue_event("),
            function(events,"boolean get_next_event("),
            function(keyboard,"static void virtual_keyboard_process_internal("),
            function(hold,"static void update_hold_ticks("),
        ])
        widget_function = function(widgets,"static void widget_instance_process_one_event_recursive(")
        gate = block(widget_function,"if (event->type == _event_type_button &&\n\t\tevent->data.button.value > 1")
        timestamp = block(widget_function,"if (event->type == _event_type_button &&\n\t\tevent->data.button.value == 1")
        cls.source = (PREFIX.replace("/* DECLARATIONS */",declarations)
                      .replace("/* PRODUCTION */",production)
                      .replace("/* WIDGET GATE */",gate)
                      .replace("/* WIDGET TIMESTAMP */",timestamp))

    def run_timing(self, flags=()):
        with tempfile.TemporaryDirectory(prefix="halo-menu-repeat-") as temporary:
            directory=Path(temporary)
            (directory / "port_config.h").write_text(
                "int config_boolean(const char *); long config_integer(const char *);\n")
            source=directory / "test.c"
            source.write_text(self.source)
            executable=directory / ("test.exe" if sys.platform=="win32" else "test")
            command=["clang","-std=gnu89","-Wall","-Wextra","-Werror","-Wno-unused-function",
                     "-I",str(directory),"-iquote",str(ROOT / "port/linux/include"),*flags]
            if sys.platform != "win32":
                command += ["-fsanitize=undefined"]
            subprocess.run([*command,str(source),"-o",str(executable)],check=True,timeout=30)
            subprocess.run([str(executable)],check=True,timeout=10)

    def test_native_menu_intervals_live_changes_and_gameplay_hold_counts(self):
        self.run_timing(["-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16"])

    def test_retail_menu_intervals_remain_fixed(self):
        self.run_timing()


if __name__=="__main__":
    unittest.main()
