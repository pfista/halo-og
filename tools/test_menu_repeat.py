"""Compile production menu input with deterministic input and clock fixtures.

The complete event manager, widget repeat gates, virtual-keyboard dispatcher and
gameplay hold counter come from production. Platform input and rendering are
mocked; these checks establish event semantics, not native latency or retail parity.
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
    return block(source[source.rindex(signature):], signature)


def repeat_macro(source, name):
    definition = source.index(f"#define {name} ")
    start = source.rfind("#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS", 0, definition)
    return source[start:source.index("#endif", definition) + len("#endif")]


PREFIX = r'''
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char byte,boolean;
typedef struct { short x,y; } point2d;
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
#define HALO_DIRECTORY_JOIN_READY_EVENT 99
static unsigned long clock_ms;
static int fast_repeat,config_reads;
static unsigned long system_milliseconds(void) { return clock_ms; }
int config_boolean(const char *name) {
    assert(!strcmp(name,"input.fast_menu_repeat"));config_reads++;return fast_repeat;
}
long config_integer(const char *name) { (void)name;return 0; }
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
#include "controller_settings.h"
#include "menu_navigation.h"
#endif
/* INPUT DECLARATIONS */
struct event_record {
    short type,controller_index;
    union { point2d stick;struct { byte index,value; } button; } data;
};
static boolean present[MAXIMUM_GAMEPADS];
static struct gamepad_state inputs[MAXIMUM_GAMEPADS];
static boolean input_has_gamepad(short index) { return present[index]; }
static const struct gamepad_state *input_get_gamepad_state(short index) { return &inputs[index]; }
/* DEADZONE PRODUCTION */
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
static struct halo_menu_navigation_state navigation[MAXIMUM_GAMEPADS];
static struct halo_menu_keyboard_event key_events[32];
static unsigned key_event_count,key_event_read,key_held;
int halo_menu_navigation_read(short index,struct halo_menu_navigation_state *state) {
    *state=navigation[index];return present[index];
}
int halo_menu_keyboard_next(struct halo_menu_keyboard_event *event) {
    if(key_event_read==key_event_count) return FALSE;
    *event=key_events[key_event_read++];return TRUE;
}
unsigned halo_menu_keyboard_held(void) { return key_held; }
void halo_menu_keyboard_clear(void) { key_event_count=key_event_read=0; }
#endif
/* EVENT MANAGER PRODUCTION */
/* UI DECLARATIONS */
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
static boolean virtual_keyboard_active(void) { return TRUE; }
static boolean virtual_keyboard_tab_left(void) { tabs[_event_tab_left]++;return TRUE; }
static boolean virtual_keyboard_tab_right(void) { tabs[_event_tab_right]++;return TRUE; }
static boolean virtual_keyboard_tab_up(void) { tabs[_event_tab_up]++;return TRUE; }
static boolean virtual_keyboard_tab_down(void) { tabs[_event_tab_down]++;return TRUE; }
static boolean virtual_keyboard_select(void) { selects++;return TRUE; }
static boolean virtual_keyboard_cancel(void) { cancels++;return TRUE; }
static void virtual_keyboard_backspace(void) {}
static void ui_play_audio_feedback_sound(int sound) { (void)sound; }
/* KEYBOARD PRODUCTION */
/* HOLD PRODUCTION */
static struct event_record posted[300];
static unsigned posted_count;
static void reset_events(int faster) {
    event_manager_dispose();memset(&event_manager_globals,0,sizeof(event_manager_globals));
    memset(present,0,sizeof(present));memset(inputs,0,sizeof(inputs));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    memset(navigation,0,sizeof(navigation));key_held=0;halo_menu_keyboard_clear();
#endif
    fast_repeat=faster;clock_ms=0;event_manager_initialize();
    memset(dpad_event_times,0,sizeof(dpad_event_times));
    memset(&virtual_keyboard_globals,0,sizeof(virtual_keyboard_globals));
    memset(tabs,0,sizeof(tabs));virtual_keyboard_globals.last_event=NONE;posted_count=0;
}
static void capture_events(unsigned long time) {
    struct event_record event;
    clock_ms=time;posted_count=0;event_manager_update();
    while(get_next_event(&event,NONE)) if(event.type!=_event_type_null) {
        assert(posted_count<sizeof(posted)/sizeof(posted[0]));posted[posted_count++]=event;
    }
}
static void expect_button(int direction,int controller) {
    if(posted_count!=1 || posted[0].type!=_event_type_button)
        fprintf(stderr,"expected button %d controller %d at %lu ms; got %u events\n",
                direction,controller,clock_ms,posted_count);
    assert(posted_count==1 && posted[0].type==_event_type_button);
    assert(posted[0].data.button.index==direction && posted[0].data.button.value==1);
    assert(posted[0].controller_index==controller);
}
static void expect_stick(int stick,int x,int y,int controller) {
    assert(posted_count==1);
    assert(posted[0].type==(stick ? _event_type_right_stick : _event_type_left_stick));
    assert(posted[0].data.stick.x==x && posted[0].data.stick.y==y);
    assert(posted[0].controller_index==controller);
}
static int widget_button(int direction,int value,int controller,unsigned long time) {
    struct event_record storage,*event=&storage;memset(event,0,sizeof(*event));
    event->type=_event_type_button;event->controller_index=(short)controller;
    event->data.button.index=(byte)direction;event->data.button.value=(byte)value;
    widget_globals.current_system_milliseconds=time;
    /* WIDGET GATE */
    /* WIDGET TIMESTAMP */
    return event->data.button.value;
}
static int post_stick(int stick,short x,short y,unsigned long time) {
    struct event_record event,output;memset(&event,0,sizeof(event));clock_ms=time;
    event.type=(short)(stick ? _event_type_right_stick : _event_type_left_stick);
    event.data.stick.x=x;event.data.stick.y=y;queue_event(&event,0);
    return get_next_event(&output,0);
}
static void keyboard_button(int direction,int value,unsigned long time) {
    struct event_record event;memset(&event,0,sizeof(event));clock_ms=time;
    event.type=_event_type_button;event.data.button.index=(byte)direction;
    event.data.button.value=(byte)value;queue_event(&event,0);virtual_keyboard_process_internal();
}
static void check_original(void) {
    static const int buttons[]={_gamepad_binary_button_dpad_left,_gamepad_binary_button_dpad_right,
        _gamepad_binary_button_dpad_up,_gamepad_binary_button_dpad_down};
    int speed,stick,direction,controller;
    for(speed=0;speed<2;speed++) {
        for(stick=0;stick<2;stick++) {
            reset_events(speed);
            assert(!post_stick(stick,STICK_EVENT_THRESHOLD-1,0,1000));
            assert(post_stick(stick,SHORT_MAX,0,1000));
            assert(!post_stick(stick,SHORT_MAX,0,1249));
            assert(post_stick(stick,SHORT_MAX,0,1250));
            assert(!post_stick(stick,SHORT_MAX,0,1251));
            /* A full sign reversal is not a fresh edge in the Original path. */
            assert(!post_stick(stick,SHORT_MIN,0,1252));
            assert(!post_stick(stick,1,0,1253));
            assert(post_stick(stick,SHORT_MIN,0,1254));
            reset_events(speed);present[0]=TRUE;inputs[0].sticks[stick].x=SHORT_MAX;
            capture_events(2000);expect_stick(stick,SHORT_MAX,0,0);
            inputs[0].sticks[stick].x=0;capture_events(2001);assert(!posted_count);
            inputs[0].sticks[stick].x=SHORT_MAX;capture_events(2002);assert(!posted_count);
            capture_events(2250);expect_stick(stick,SHORT_MAX,0,0);
        }
        for(direction=_widget_event_dpad_up;direction<=_widget_event_dpad_right;direction++)
            for(controller=0;controller<MAXIMUM_NUMBER_OF_LOCAL_PLAYERS;controller++) {
            reset_events(speed);
            assert(widget_button(direction,1,controller,4000)==1);
            assert(widget_button(direction,2,controller,4001)==2);
            assert(widget_button(direction,2,controller,4249)==2);
            assert(widget_button(direction,2,controller,4250)==1);
            assert(widget_button(direction,2,controller,4251)==2);
            assert(widget_button(direction,1,controller,4252)==1);
        }
        for(direction=0;direction<4;direction++) {
            unsigned long first=20000+(unsigned long)(speed*4+direction)*1000;
            reset_events(speed);
            keyboard_button(buttons[direction],1,first);assert(tabs[direction]==1);
            keyboard_button(buttons[direction],2,first+1);assert(tabs[direction]==1);
            keyboard_button(buttons[direction],2,first+249);assert(tabs[direction]==1);
            keyboard_button(buttons[direction],2,first+250);assert(tabs[direction]==2);
            keyboard_button(buttons[direction],2,first+251);assert(tabs[direction]==2);
            keyboard_button(buttons[direction],1,first+252);assert(tabs[direction]==3);
            keyboard_button(buttons[(direction+1)%4],2,first+253);assert(tabs[(direction+1)%4]==1);
        }
    }
    assert(widget_button(_gamepad_analog_button_a,2,0,10000)==2);
    assert(widget_button(_widget_event_dpad_up,2,-1,10000)==2);
    assert(widget_button(_widget_event_dpad_up,2,MAXIMUM_NUMBER_OF_LOCAL_PLAYERS,10000)==2);
    reset_events(0);selects=cancels=0;
    keyboard_button(_gamepad_analog_button_a,1,50000);assert(selects==1);
    keyboard_button(_gamepad_analog_button_a,2,51000);assert(selects==1);
    keyboard_button(_gamepad_analog_button_b,1,52000);assert(cancels==1);
    keyboard_button(_gamepad_analog_button_b,2,53000);assert(cancels==1);
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
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
/* Expected user policy, independent of the production header constants. */
enum { FIRST_REPEAT=500, REPEAT_INTERVAL=100 };
static const int dpad_buttons[4]={_gamepad_binary_button_dpad_up,_gamepad_binary_button_dpad_down,
    _gamepad_binary_button_dpad_left,_gamepad_binary_button_dpad_right};
static void set_dpad(int controller,unsigned mask) {
    int direction;navigation[controller].dpad=mask;
    for(direction=0;direction<4;direction++)
        inputs[controller].buttons[dpad_buttons[direction]]=(byte)((mask & (1u<<direction)) ? 2 : 0);
}
static void check_faster_dpad(void) {
    int direction,controller;
    for(direction=0;direction<4;direction++) for(controller=0;controller<MAXIMUM_GAMEPADS;controller++) {
        unsigned long after_stall=2000,repress=after_stall+REPEAT_INTERVAL+2;
        unsigned long redirected=repress+FIRST_REPEAT+1;
        reset_events(1);present[controller]=TRUE;set_dpad(controller,1u<<direction);
        capture_events(0);expect_button(dpad_buttons[direction],controller);
        event_manager_flush();
        capture_events(1);assert(!posted_count);capture_events(499);assert(!posted_count);
        capture_events(500);expect_button(dpad_buttons[direction],controller);
        capture_events(599);assert(!posted_count);capture_events(600);expect_button(dpad_buttons[direction],controller);
        /* A delayed poll emits once and starts the next interval there. */
        capture_events(after_stall);expect_button(dpad_buttons[direction],controller);
        capture_events(after_stall);assert(!posted_count);
        capture_events(after_stall+REPEAT_INTERVAL-1);assert(!posted_count);
        capture_events(after_stall+REPEAT_INTERVAL);expect_button(dpad_buttons[direction],controller);
        set_dpad(controller,0);capture_events(repress-1);assert(!posted_count);
        set_dpad(controller,1u<<direction);capture_events(repress);expect_button(dpad_buttons[direction],controller);
        capture_events(repress+FIRST_REPEAT-1);assert(!posted_count);
        capture_events(repress+FIRST_REPEAT);expect_button(dpad_buttons[direction],controller);
        set_dpad(controller,1u<<((direction+1)%4));capture_events(redirected);
        expect_button(dpad_buttons[(direction+1)%4],controller);
        capture_events(redirected+REPEAT_INTERVAL);assert(!posted_count);
        capture_events(redirected+FIRST_REPEAT);expect_button(dpad_buttons[(direction+1)%4],controller);
    }
    reset_events(1);present[0]=present[1]=TRUE;set_dpad(0,HALO_MENU_DIRECTION_LEFT);
    capture_events(1000);expect_button(_gamepad_binary_button_dpad_left,0);
    set_dpad(1,HALO_MENU_DIRECTION_RIGHT);capture_events(1050);expect_button(_gamepad_binary_button_dpad_right,1);
    capture_events(1000+FIRST_REPEAT);expect_button(_gamepad_binary_button_dpad_left,0);
    capture_events(1050+FIRST_REPEAT);expect_button(_gamepad_binary_button_dpad_right,1);
    present[0]=FALSE;capture_events(1051+FIRST_REPEAT);assert(!posted_count);
    present[0]=TRUE;capture_events(1052+FIRST_REPEAT);expect_button(_gamepad_binary_button_dpad_left,0);
    reset_events(1);present[0]=TRUE;inputs[0].buttons[_gamepad_analog_button_a]=2;
    capture_events(1000);assert(posted_count==1 && posted[0].data.button.value==2);
    assert(widget_button(_gamepad_analog_button_a,2,0,2000)==2);
    assert(widget_button(_widget_event_dpad_up,2,0,1000)==2);
    assert(widget_button(_widget_event_dpad_up,1,0,1000)==1);
    reset_events(1);present[0]=TRUE;set_dpad(0,HALO_MENU_DIRECTION_UP);
    capture_events(ULONG_MAX-250);expect_button(_gamepad_binary_button_dpad_up,0);
    capture_events(248);assert(!posted_count);capture_events(249);expect_button(_gamepad_binary_button_dpad_up,0);
    capture_events(249+REPEAT_INTERVAL-1);assert(!posted_count);
    capture_events(249+REPEAT_INTERVAL);expect_button(_gamepad_binary_button_dpad_up,0);
}
static void set_stick(int controller,int stick,short x,short y) {
    if(stick) { navigation[controller].right_x=x;navigation[controller].right_y=y; }
    else { navigation[controller].left_x=x;navigation[controller].left_y=y; }
    navigation[controller].physical_axes=15u;
    inputs[controller].sticks[stick].x=x;inputs[controller].sticks[stick].y=y;
}
static void check_faster_sticks(void) {
    int stick,controller;
    for(stick=0;stick<2;stick++) for(controller=0;controller<MAXIMUM_GAMEPADS;controller++) {
        unsigned long first=1001,repeat=first+FIRST_REPEAT;
        unsigned long changed=repeat+REPEAT_INTERVAL+2,repress=changed+FIRST_REPEAT+4;
        reset_events(1);present[controller]=TRUE;
        set_stick(controller,stick,STICK_EVENT_THRESHOLD-1,0);capture_events(1000);assert(!posted_count);
        set_stick(controller,stick,STICK_EVENT_THRESHOLD,0);capture_events(first);expect_stick(stick,SHORT_MAX,0,controller);
        set_stick(controller,stick,STICK_EVENT_THRESHOLD-1,0);capture_events(first+1);assert(!posted_count);
        set_stick(controller,stick,28000,0);capture_events(repeat-1);assert(!posted_count);
        capture_events(repeat);expect_stick(stick,SHORT_MAX,0,controller);
        capture_events(repeat+REPEAT_INTERVAL-1);assert(!posted_count);
        capture_events(repeat+REPEAT_INTERVAL);expect_stick(stick,SHORT_MAX,0,controller);
        set_stick(controller,stick,SHORT_MIN,0);capture_events(changed-1);expect_stick(stick,SHORT_MIN,0,controller);
        set_stick(controller,stick,0,SHORT_MAX);capture_events(changed);expect_stick(stick,0,SHORT_MAX,controller);
        capture_events(changed+REPEAT_INTERVAL);assert(!posted_count);
        capture_events(changed+FIRST_REPEAT);expect_stick(stick,0,SHORT_MAX,controller);
        set_stick(controller,stick,0,24576);capture_events(repress-3);assert(!posted_count);
        set_stick(controller,stick,0,24575);capture_events(repress-2);assert(!posted_count);
        set_stick(controller,stick,0,28000);capture_events(repress-1);assert(!posted_count);
        set_stick(controller,stick,0,SHORT_MAX);capture_events(repress);expect_stick(stick,0,SHORT_MAX,controller);
        /* Exact neutral resets even while another button remains held. */
        inputs[controller].buttons[_gamepad_analog_button_a]=2;
        set_stick(controller,stick,0,0);capture_events(repress+1);assert(posted_count==1);
        inputs[controller].buttons[_gamepad_analog_button_a]=0;
        set_stick(controller,stick,0,SHORT_MAX);capture_events(repress+2);expect_stick(stick,0,SHORT_MAX,controller);
        capture_events(repress+2+FIRST_REPEAT-1);assert(!posted_count);
        capture_events(repress+2+FIRST_REPEAT);expect_stick(stick,0,SHORT_MAX,controller);
    }
    /* Small changes near a diagonal must not create fresh direction changes. */
    reset_events(1);present[0]=TRUE;set_stick(0,0,32000,31900);
    capture_events(1000);expect_stick(0,SHORT_MAX,0,0);
    set_stick(0,0,31900,32000);capture_events(1001);assert(!posted_count);
    set_stick(0,0,32000,31900);capture_events(1002);assert(!posted_count);
    set_stick(0,0,31900,32000);capture_events(1000+FIRST_REPEAT);expect_stick(0,SHORT_MAX,0,0);
    set_stick(0,0,28000,SHORT_MAX);capture_events(1001+FIRST_REPEAT);expect_stick(0,0,SHORT_MAX,0);
    capture_events(1000+2*FIRST_REPEAT);assert(!posted_count);
    capture_events(1001+2*FIRST_REPEAT);expect_stick(0,0,SHORT_MAX,0);
}
static void queue_key(unsigned pressed,unsigned released,unsigned held) {
    struct halo_menu_keyboard_event *event;
    assert(key_event_count<sizeof(key_events)/sizeof(key_events[0]));
    event=&key_events[key_event_count++];event->pressed=pressed;event->released=released;event->held=held;key_held=held;
}
static void queue_two_taps(void) {
    queue_key(HALO_MENU_DIRECTION_LEFT,0,HALO_MENU_DIRECTION_LEFT);
    queue_key(0,HALO_MENU_DIRECTION_LEFT,0);
    queue_key(HALO_MENU_DIRECTION_LEFT,0,HALO_MENU_DIRECTION_LEFT);
    queue_key(0,HALO_MENU_DIRECTION_LEFT,0);
}
static void check_faster_keyboard(void) {
    int direction;
    for(direction=0;direction<4;direction++) {
        unsigned long first=1000,repeat=first+FIRST_REPEAT;
        unsigned long repress=repeat+REPEAT_INTERVAL+2,changed=repress+FIRST_REPEAT+1;
        unsigned mask=1u<<direction;reset_events(1);present[0]=TRUE;
        inputs[0].buttons[dpad_buttons[direction]]=1;
        queue_key(mask,0,mask);capture_events(first);expect_button(dpad_buttons[direction],0);
        inputs[0].buttons[dpad_buttons[direction]]=2;
        capture_events(repeat-1);assert(!posted_count);capture_events(repeat);expect_button(dpad_buttons[direction],0);
        capture_events(repeat+REPEAT_INTERVAL-1);assert(!posted_count);
        capture_events(repeat+REPEAT_INTERVAL);expect_button(dpad_buttons[direction],0);
        queue_key(0,mask,0);inputs[0].buttons[dpad_buttons[direction]]=0;capture_events(repress-1);assert(!posted_count);
        queue_key(mask,0,mask);capture_events(repress);expect_button(dpad_buttons[direction],0);
        capture_events(repress+FIRST_REPEAT-1);assert(!posted_count);
        capture_events(repress+FIRST_REPEAT);expect_button(dpad_buttons[direction],0);
        queue_key(1u<<((direction+1)%4),mask,1u<<((direction+1)%4));capture_events(changed);
        expect_button(dpad_buttons[(direction+1)%4],0);
        capture_events(changed+REPEAT_INTERVAL);assert(!posted_count);
        capture_events(changed+FIRST_REPEAT);expect_button(dpad_buttons[(direction+1)%4],0);
    }
    reset_events(1);present[0]=TRUE;queue_two_taps();capture_events(1000);
    assert(posted_count==2 && posted[0].data.button.index==_gamepad_binary_button_dpad_left &&
           posted[1].data.button.index==_gamepad_binary_button_dpad_left);
    capture_events(2000);assert(!posted_count);
    /* More than the Original eight-event queue can preserve discrete taps. */
    reset_events(1);present[0]=TRUE;
    for(direction=0;direction<6;direction++) queue_two_taps();
    capture_events(1000);assert(posted_count==12);
    reset_events(1);present[0]=TRUE;queue_two_taps();
    clock_ms=1000;event_manager_update();virtual_keyboard_process_internal();assert(tabs[_event_tab_left]==2);
    queue_key(HALO_MENU_DIRECTION_RIGHT,0,HALO_MENU_DIRECTION_RIGHT);
    clock_ms=2000;event_manager_update();virtual_keyboard_process_internal();assert(tabs[_event_tab_right]==1);
    clock_ms=2000+FIRST_REPEAT-1;event_manager_update();virtual_keyboard_process_internal();assert(tabs[_event_tab_right]==1);
    clock_ms=2000+FIRST_REPEAT;event_manager_update();virtual_keyboard_process_internal();assert(tabs[_event_tab_right]==2);
    clock_ms=2000+FIRST_REPEAT+REPEAT_INTERVAL-1;event_manager_update();virtual_keyboard_process_internal();assert(tabs[_event_tab_right]==2);
    clock_ms=2000+FIRST_REPEAT+REPEAT_INTERVAL;event_manager_update();virtual_keyboard_process_internal();assert(tabs[_event_tab_right]==3);
    reset_events(1);present[0]=TRUE;
    queue_key(HALO_MENU_DIRECTION_UP<<HALO_MENU_KEYBOARD_MOVE_SHIFT,0,
              HALO_MENU_DIRECTION_UP<<HALO_MENU_KEYBOARD_MOVE_SHIFT);
    inputs[0].sticks[_gamepad_stick_left].y=SHORT_MAX;capture_events(1000);expect_stick(0,0,SHORT_MAX,0);
    capture_events(1000+FIRST_REPEAT-1);assert(!posted_count);
    capture_events(1000+FIRST_REPEAT);expect_stick(0,0,SHORT_MAX,0);
    /* Brief opposing movement keys cancel the direction even between polls.
     * Releasing the opposing key restarts W's hold delay without a fresh move. */
    reset_events(1);present[0]=TRUE;
    queue_key(HALO_MENU_DIRECTION_UP<<HALO_MENU_KEYBOARD_MOVE_SHIFT,0,
              HALO_MENU_DIRECTION_UP<<HALO_MENU_KEYBOARD_MOVE_SHIFT);
    capture_events(1000);expect_stick(0,0,SHORT_MAX,0);
    queue_key(HALO_MENU_DIRECTION_DOWN<<HALO_MENU_KEYBOARD_MOVE_SHIFT,0,
              0);
    queue_key(0,HALO_MENU_DIRECTION_DOWN<<HALO_MENU_KEYBOARD_MOVE_SHIFT,
              HALO_MENU_DIRECTION_UP<<HALO_MENU_KEYBOARD_MOVE_SHIFT);
    capture_events(1450);assert(!posted_count);
    capture_events(1000+FIRST_REPEAT);assert(!posted_count);
    capture_events(1450+FIRST_REPEAT-1);assert(!posted_count);
    capture_events(1450+FIRST_REPEAT);expect_stick(0,0,SHORT_MAX,0);
}
static void check_fixed_faster_policy(void) {
    /* Native menus always use 500/100 ms. Legacy config changes must neither
     * select the Original path nor reset an active hold. Retail is checked
     * separately without HALO_PORT_MAXIMUM_NETWORK_PLAYERS. */
    reset_events(0);present[0]=TRUE;set_dpad(0,HALO_MENU_DIRECTION_LEFT);
    capture_events(1000);expect_button(_gamepad_binary_button_dpad_left,0);
    fast_repeat=1;
    capture_events(1000+FIRST_REPEAT-1);assert(!posted_count);
    fast_repeat=0;capture_events(1000+FIRST_REPEAT);expect_button(_gamepad_binary_button_dpad_left,0);
    fast_repeat=1;capture_events(1000+FIRST_REPEAT+REPEAT_INTERVAL-1);assert(!posted_count);
    fast_repeat=0;capture_events(1000+FIRST_REPEAT+REPEAT_INTERVAL);expect_button(_gamepad_binary_button_dpad_left,0);
    reset_events(0);present[0]=TRUE;
    queue_key(HALO_MENU_DIRECTION_LEFT,0,HALO_MENU_DIRECTION_LEFT);
    capture_events(1000);expect_button(_gamepad_binary_button_dpad_left,0);
    fast_repeat=1;capture_events(1001);assert(!posted_count);
    capture_events(1000+FIRST_REPEAT-1);assert(!posted_count);
    fast_repeat=0;capture_events(1000+FIRST_REPEAT);expect_button(_gamepad_binary_button_dpad_left,0);
    assert(config_reads==0);
}
#endif
int main(void) {
#if TEST_CHECK==1
    check_original();check_gameplay_hold_counts();
#ifndef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(config_reads==0);
#endif
#elif TEST_CHECK==2
    check_faster_dpad();check_gameplay_hold_counts();
#elif TEST_CHECK==3
    check_faster_sticks();check_gameplay_hold_counts();
#elif TEST_CHECK==4
    check_faster_keyboard();check_gameplay_hold_counts();
#elif TEST_CHECK==5
    check_fixed_faster_policy();check_gameplay_hold_counts();
#endif
    puts("menu repeat timing tests passed");return 0;
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
        for source, name in ((widgets, "DPAD_EVENT_REPEAT_MILLISECONDS"),
                             (keyboard, "VIRTUAL_KEYBOARD_TAB_REPEAT_MILLISECONDS")):
            value = re.search(rf"\b{name}\s*=\s*(\d+)", source)
            if not value:
                raise AssertionError(f"Missing production repeat constant: {name}")
            constants.append(f"enum {{ {name}={value[1]} }};")
        input_declarations = "\n".join([
            block(buttons, "enum\n") + ";", block(sticks, "enum\n") + ";",
            block(inputs, "struct gamepad_state\n") + ";",
        ])
        ui_declarations = "\n".join([
            block(actions, "enum\n") + ";", *constants,
            "enum { _ui_audio_feedback_cursor };",
            repeat_macro(widgets, "MENU_DPAD_REPEAT_INTERVAL"),
            repeat_macro(keyboard, "MENU_KEYBOARD_REPEAT_INTERVAL"),
        ])
        event_production = re.sub(r"^#include[^\n]*\n", "", events, flags=re.M)
        # Guest 32-bit structure assertions do not apply to the host's long type.
        event_production = re.sub(r"typedef char verify_event_manager_[\s\S]*?;", "", event_production)
        keyboard_production = "\n".join([
            function(keyboard, "static void virtual_keyboard_process_action("),
            function(keyboard, "static void virtual_keyboard_process_internal("),
        ])
        widget_function = function(widgets, "static void widget_instance_process_one_event_recursive(")
        gate = block(widget_function, "if (event->type == _event_type_button &&\n\t\tevent->data.button.value > 1")
        timestamp = block(widget_function, "if (event->type == _event_type_button &&\n\t\tevent->data.button.value == 1")
        cls.source = (PREFIX.replace("/* INPUT DECLARATIONS */", input_declarations)
                      .replace("/* DEADZONE PRODUCTION */", function(hold, "short fix_dead_zone("))
                      .replace("/* EVENT MANAGER PRODUCTION */", event_production)
                      .replace("/* UI DECLARATIONS */", ui_declarations)
                      .replace("/* KEYBOARD PRODUCTION */", keyboard_production)
                      .replace("/* HOLD PRODUCTION */", function(hold, "static void update_hold_ticks("))
                      .replace("/* WIDGET GATE */", gate)
                      .replace("/* WIDGET TIMESTAMP */", timestamp))

    def run_timing(self, check, *, native=True):
        with tempfile.TemporaryDirectory(prefix="halo-menu-repeat-") as temporary:
            directory = Path(temporary)
            (directory / "port_config.h").write_text(
                "int config_boolean(const char *); long config_integer(const char *);\n")
            source = directory / "test.c"
            source.write_text(self.source)
            executable = directory / ("test.exe" if sys.platform == "win32" else "test")
            flags = [f"-DTEST_CHECK={check}"]
            if native:
                flags.append("-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16")
            command = ["clang", "-std=gnu89", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                       "-I", str(directory), "-iquote", str(ROOT / "port/linux/include"), *flags]
            if sys.platform != "win32":
                command += ["-fsanitize=undefined"]
            compiled = subprocess.run([*command, str(source), "-o", str(executable)],
                                      text=True, capture_output=True, timeout=30)
            if compiled.returncode:
                self.fail(compiled.stderr)
            tested = subprocess.run([str(executable)], text=True, capture_output=True, timeout=10)
            if tested.returncode:
                self.fail(tested.stderr)

    def test_native_faster_default_ignores_legacy_configuration(self):
        self.run_timing(5)

    def test_retail_navigation_ignores_faster_configuration(self):
        self.run_timing(1, native=False)

    def test_faster_dpad_taps_hold_reset_and_controller_slots(self):
        self.run_timing(2)

    def test_faster_stick_hysteresis_direction_and_exact_neutral(self):
        self.run_timing(3)

    def test_faster_keyboard_preserves_taps_and_shares_menu_repeat_events(self):
        self.run_timing(4)


if __name__ == "__main__":
    unittest.main()
