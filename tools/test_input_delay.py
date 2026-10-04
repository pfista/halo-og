"""Compile production input selection and queue paths against a source-only fixture.

The helper, frame accumulation, local/client/host selection, latching, outgoing
input/history and reset functions are production code. Game objects and update
delivery are deterministic stubs; no game assets, graphics or sockets are used.
Guest C long spellings become int32_t when compiling on an LP64 host. These
tests establish a one-update delay at the fixed 30 Hz simulation rate, not a
physical controller-to-display latency measurement.
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
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char byte, boolean;
typedef unsigned short word;
typedef float real;
typedef struct { real yaw,pitch; } real_euler_angles2d;
typedef struct { real i,j; } real_vector2d;
typedef struct { real i,j,k; } real_vector3d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define TICKS_PER_SECOND 30
#define MAXIMUM_LOCAL_PLAYERS 4
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 8
#define HALO_PORT_MAXIMUM_NETWORK_MACHINES 8
#define MAXIMUM_WEAPONS_PER_UNIT 4
#define NUMBER_OF_UNIT_GRENADE_TYPES 2
#define DISTRIBUTED_INPUT_HISTORY 4
#define PERFORMANCE_INPUT_DELAY_MILLISECONDS 33
#define UNIT_CONTROL_PORT_ACTION_ONLY_BIT 15
#define FLAG(i) (1U<<(i))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define csmemset memset
#define csmemcpy memcpy
#define csmemmove memmove
#define match_assert(f,l,c) assert(c)
#define match_assert_valid_real(f,l,v) assert(isfinite(v))
#define DATUM_INDEX_TO_ABSOLUTE_INDEX(i) ((i)&0xFFFF)
enum { _game_connection_local,_game_connection_network_client,_game_connection_network_server };
struct data_array { short count; byte *data; };
/* DECLARATIONS */
struct player_datum { long unit_index; short local_player_index; };
struct unit_datum { struct { real_vector3d desired_aiming_vector; } unit; };
struct game_variant { int delay; };
static struct game_variant variant;
static struct player_datum players[MAXIMUM_NUMBER_OF_PLAYERS];
static struct unit_datum units[MAXIMUM_NUMBER_OF_PLAYERS];
static real_euler_angles2d control_facings[MAXIMUM_LOCAL_PLAYERS];
static long local_players[MAXIMUM_LOCAL_PLAYERS], player_ids[MAXIMUM_NUMBER_OF_PLAYERS];
static struct update_server_queue_datum server_queues[MAXIMUM_NUMBER_OF_PLAYERS];
static struct update_client_queue_datum client_queues[MAXIMUM_NUMBER_OF_PLAYERS];
static struct data_array server_data,client_data;
static struct game_time_globals_struct game_time_storage;
static struct game_time_globals_struct *game_time_globals=&game_time_storage;
#define now game_time_storage.local_time
static boolean paused,held,engine_running;
static int connection;
static long game_time_get(void) { return now; }
static boolean game_time_initialized(void) { return TRUE; }
static boolean game_time_get_paused(void) { return paused; }
static boolean game_time_held(void) { return held; }
static int game_connection(void) { return connection; }
static boolean game_engine_running(void) { return engine_running; }
static struct game_variant *game_engine_get_variant(void) { return &variant; }
static unsigned performance_variant_get_input_delay_milliseconds(struct game_variant const *v) { return v->delay; }
static long local_player_get_player_index(short seat) { assert(seat>=0 && seat<MAXIMUM_LOCAL_PLAYERS); return local_players[seat]; }
static struct player_datum *player_try_and_get(long id) {
    if(id==NONE)return NULL;
    long slot=DATUM_INDEX_TO_ABSOLUTE_INDEX(id);
    return slot<MAXIMUM_NUMBER_OF_PLAYERS && player_ids[slot]==id ? &players[slot] : NULL;
}
static struct unit_datum *unit_get(long id) { assert(id!=NONE);return &units[DATUM_INDEX_TO_ABSOLUTE_INDEX(id)]; }
static void euler_angles2d_from_vector3d(real_euler_angles2d *a,real_vector3d const *v) {
    a->yaw=atan2f(v->j,v->i);a->pitch=atan2f(v->k,sqrtf(v->i*v->i+v->j*v->j));
}
static real_euler_angles2d const *player_control_get_facing_angles(short seat) { return &control_facings[seat]; }
static void player_control_set_facing(short seat,real_vector3d const *v) { euler_angles2d_from_vector3d(&control_facings[seat],v); }
static void *datum_try_and_get(struct data_array *data,long id) {
    if(id==NONE)return NULL;
    long slot=DATUM_INDEX_TO_ABSOLUTE_INDEX(id);
    if(slot>=data->count || player_ids[slot]!=id)return NULL;
    assert(data==&server_data);return &server_queues[slot];
}
static void *datum_get(struct data_array *data,long id) {
    long slot=DATUM_INDEX_TO_ABSOLUTE_INDEX(id);assert(data==&server_data && slot<data->count);
    return &server_queues[slot];
}
static long *machine_get_player_list(long machine) { assert(machine==0);return local_players; }
static long system_milliseconds(void) { return now*1000/TICKS_PER_SECOND; }
/* GLOBALS */
static void update_client_handle_server_update(struct server_update *update,long number) {
    struct update *record=&update_client_globals.updates[number&(MAXIMUM_CLIENT_UPDATES-1)];
    record->update_number=number;record->update=*update;
    update_client_globals.latest_update_number_received=number;
}
static boolean update_client_input_delay_enabled(void);
static struct player_action update_client_take_local_action(short local_player_index,long update_number,struct player_action const *sampled);
static void update_server_take_local_actions(void);
static struct update *update_server_get_update(long update_number);
static struct update *update_client_get_update(long update_number);
void update_client_build_client_update(struct player_action_collection *collection);
void update_server_handle_client_update(long machine_index,struct player_action *actions);
void update_server_next_update(void);
void update_server_build_server_update(long machine_index,struct server_update *update,long *update_number);
/* FUNCTIONS */
'''

HARNESS = r'''
static struct player_action sample(real n,unsigned flags) {
    struct player_action a={0};a.control_flags=flags;
    a.desired_facing=(real_euler_angles2d){n,n/10};a.throttle=(real_vector2d){n/10,-n/20};
    a.primary_trigger=n/10;a.desired_weapon_index=1;a.desired_grenade_index=1;a.desired_zoom_level=2;
    return a;
}
static void same(struct player_action const *a,struct player_action const *b) { assert(!memcmp(a,b,sizeof(*a))); }
static void neutral(struct player_action const *a,real yaw,real pitch) {
    assert(a->control_flags==0 && a->throttle.i==0 && a->throttle.j==0 && a->primary_trigger==0);
    assert(a->desired_weapon_index==NONE && a->desired_grenade_index==NONE && a->desired_zoom_level==NONE);
    assert(fabsf(a->desired_facing.yaw-yaw)<0.00001f && fabsf(a->desired_facing.pitch-pitch)<0.00001f);
}
static void reset(void) {
    memset(&update_client_globals,0,sizeof(update_client_globals));
    memset(&update_server_globals,0,sizeof(update_server_globals));
    memset(server_queues,0,sizeof(server_queues));memset(client_queues,0,sizeof(client_queues));
    memset(players,0,sizeof(players));memset(units,0,sizeof(units));
    memset(control_facings,0,sizeof(control_facings));
    memset(&game_time_storage,0,sizeof(game_time_storage));game_time_storage.initialized=TRUE;
    for(short i=0;i<MAXIMUM_LOCAL_PLAYERS;i++)local_players[i]=NONE;
    for(short i=0;i<MAXIMUM_NUMBER_OF_PLAYERS;i++)player_ids[i]=NONE;
    server_data=(struct data_array){MAXIMUM_NUMBER_OF_PLAYERS,(byte *)server_queues};
    client_data=(struct data_array){MAXIMUM_NUMBER_OF_PLAYERS,(byte *)client_queues};
    update_client_globals.queues=&client_data;update_client_globals.initialized=TRUE;
    update_server_globals.queues=&server_data;update_server_globals.initialized=TRUE;
    now=100;paused=held=FALSE;engine_running=TRUE;variant.delay=33;
    connection=_game_connection_network_client;update_queues_distributed_reset();
}
static long add(short seat,short slot,short generation) {
    long id=((unsigned)generation<<16)|slot;
    assert(seat>=0 && seat<MAXIMUM_LOCAL_PLAYERS && slot<MAXIMUM_NUMBER_OF_PLAYERS);
    local_players[seat]=id;player_ids[slot]=id;
    players[slot]=(struct player_datum){(1<<16)|slot,seat};
    server_queues[slot].identifier=client_queues[slot].identifier=generation;
    units[slot].unit.desired_aiming_vector=(real_vector3d){0,1,0};
    return id;
}
static void helper_off(void) {
    reset();struct player_input_delay d={0};struct player_action a=sample(3,0xFFFF),out;
    real_euler_angles2d idle={1,.2f};a.pad=123;
    player_input_delay_select(&d,FALSE,1,4,8,&a,&idle,&out);same(&a,&out);assert(!d.valid);
    player_input_delay_select(&d,TRUE,2,4,8,&a,&idle,&out);neutral(&out,1,.2f);
    struct player_action b=sample(4,4);
    player_input_delay_select(&d,FALSE,3,4,8,&b,&idle,&out);same(&b,&out);assert(!d.valid);
    player_input_delay_select(&d,TRUE,4,4,8,&b,&idle,&out);neutral(&out,1,.2f);
}
static void helper_delay(void) {
    reset();struct player_input_delay d={0};struct player_action a=sample(3,4),b=sample(5,16),out;
    real_euler_angles2d idle={1,.2f};
    player_input_delay_select(&d,TRUE,10,4,8,&a,&idle,&out);neutral(&out,1,.2f);
    player_input_delay_select(&d,TRUE,11,4,8,&b,&idle,&out);same(&a,&out);
    player_input_delay_select(&d,TRUE,12,4,8,&a,&idle,&out);same(&b,&out);
}
static void helper_repeated(void) {
    reset();struct player_input_delay d={0};struct player_action a=sample(3,4),b=sample(5,16),out;
    real_euler_angles2d idle={1,.2f};
    player_input_delay_select(&d,TRUE,10,4,8,&a,&idle,&out);
    player_input_delay_select(&d,TRUE,10,4,8,&b,&idle,&out);neutral(&out,1,.2f);
    player_input_delay_select(&d,TRUE,11,4,8,&b,&idle,&out);same(&a,&out);
    player_input_delay_select(&d,TRUE,11,4,8,&a,&idle,&out);same(&a,&out);
    player_input_delay_select(&d,TRUE,12,4,8,&a,&idle,&out);same(&b,&out);
}
static void helper_lifecycle(void) {
    reset();struct player_input_delay d={0};struct player_action a=sample(3,4),b=sample(5,16),out;
    real_euler_angles2d idle={1,.2f};
    player_input_delay_select(&d,TRUE,10,4,8,&a,&idle,&out);
    player_input_delay_select(&d,TRUE,11,4,9,&b,&idle,&out);neutral(&out,1,.2f); /* new life */
    player_input_delay_select(&d,TRUE,12,5,9,&a,&idle,&out);neutral(&out,1,.2f); /* new player */
    player_input_delay_select(&d,TRUE,14,5,9,&b,&idle,&out);neutral(&out,1,.2f); /* skipped update */
    player_input_delay_select(&d,TRUE,13,5,9,&a,&idle,&out);neutral(&out,1,.2f); /* clock reset */
    player_input_delay_select(&d,TRUE,14,5,NONE,&a,&idle,&out);neutral(&out,1,.2f);assert(!d.valid);
    player_input_delay_select(&d,TRUE,15,5,9,&b,&idle,&out);neutral(&out,1,.2f);
    player_input_delay_reset(&d);
    player_input_delay_select(&d,TRUE,16,5,9,&a,&idle,&out);neutral(&out,1,.2f);
}
static void accumulated_tap(void) {
    reset();add(0,0,1);struct player_action press=sample(3,FLAG(_unit_control_weapon_reload_bit));
    struct player_action release=sample(4,0);release.primary_trigger=0;
    update_client_queue_push();update_client_queue(&press);
    update_client_queue_push();update_client_queue(&release); /* a release on another display frame, same tick */
    struct player_action aggregated=release;aggregated.control_flags=press.control_flags;aggregated.primary_trigger=press.primary_trigger;
    same(&aggregated,&update_client_globals.saved_action_collection.actions[0]);
    struct player_action predicted[MAXIMUM_NUMBER_OF_PLAYERS]={0},wire;unsigned short history[DISTRIBUTED_INPUT_HISTORY];long tick;
    update_client_dequeue_distributed(predicted);neutral(&predicted[0],1.57079632679f,0);
    now++;update_client_queue_push();update_client_queue(&release);
    update_client_dequeue_distributed(predicted);
    same(&aggregated,&predicted[0]);
    assert(update_client_distributed_input(0,&tick,&wire,history));
    assert(tick==101);same(&aggregated,&wire);assert(history[0]==press.control_flags && history[1]==0);
    now++;update_client_queue_push();update_client_queue(&release);update_client_dequeue_distributed(predicted);
    same(&release,&predicted[0]);assert(update_client_distributed_input(0,&tick,&wire,history));
    assert(tick==102 && history[0]==0 && history[1]==press.control_flags);
}
static void latches(void) {
    reset();add(0,0,1);struct player_action held=sample(3,FLAG(_unit_control_weapon_reload_bit));
    struct player_action released=held;released.control_flags=0;
    struct player_action out[MAXIMUM_NUMBER_OF_PLAYERS]={0},wire;long tick;unsigned short history[4];
    update_client_globals.saved_action_collection.actions[0]=held;
    update_client_dequeue_distributed(out);assert(out[0].control_flags==0);
    now++;update_client_dequeue_distributed(out);assert(out[0].control_flags==held.control_flags);
    now++;update_client_globals.saved_action_collection.actions[0]=released;
    update_client_dequeue_distributed(out);assert(out[0].control_flags==0);
    assert(update_client_distributed_input(0,&tick,&wire,history));assert(wire.control_flags==held.control_flags);
    now++;update_client_globals.saved_action_collection.actions[0]=held;update_client_dequeue_distributed(out);
    assert(out[0].control_flags==0); /* delayed release resets the existing latch */
    now++;update_client_dequeue_distributed(out);assert(out[0].control_flags==held.control_flags);
}
static void sparse_controllers(void) {
    reset();add(1,2,1);add(3,5,1);struct player_action a=sample(3,2),b=sample(6,8);
    update_client_queue_push();update_client_queue(&a);update_client_queue(&b);
    same(&a,&update_client_globals.saved_action_collection.actions[1]);same(&b,&update_client_globals.saved_action_collection.actions[3]);
    struct player_action out[MAXIMUM_NUMBER_OF_PLAYERS]={0};update_client_dequeue_distributed(out);
    now++;update_client_dequeue_distributed(out);same(&a,&out[2]);same(&b,&out[5]);
    players[2].unit_index=(2<<16)|2;now++;update_client_dequeue_distributed(out);
    neutral(&out[2],1.57079632679f,0);same(&b,&out[5]);
    local_players[1]=(2<<16)|2;player_ids[2]=local_players[1];now++;update_client_dequeue_distributed(out);
    neutral(&out[2],1.57079632679f,0);same(&b,&out[5]);
}
static void host_batch(void) {
    reset();connection=_game_connection_network_server;add(1,2,1);add(3,5,1);
    player_ids[6]=(1<<16)|6;server_queues[6].identifier=1;
    struct player_action a=sample(3,2),b=sample(6,8),remote=sample(7,4);
    server_queues[6].current_action=remote;
    update_client_globals.saved_action_collection.actions[1]=a;update_client_globals.saved_action_collection.actions[3]=b;
    update_server_next_update();same(&a,&server_queues[2].current_action);
    struct player_action next=sample(8,1);update_client_globals.saved_action_collection.actions[1]=next;
    update_server_next_update();same(&next,&server_queues[2].current_action);same(&b,&server_queues[5].current_action);
    assert(now==100 && update_server_globals.next_update_number_to_build==2);
    struct player_action out[MAXIMUM_NUMBER_OF_PLAYERS]={0};
    assert(update_client_dequeue(out));neutral(&out[2],1.57079632679f,0);neutral(&out[5],1.57079632679f,0);
    neutral(&update_server_globals.updates[0].update.actions[2],1.57079632679f,0);
    assert(update_client_dequeue(out));same(&a,&out[2]);same(&b,&out[5]);same(&remote,&out[6]);
    same(&a,&update_server_globals.updates[1].update.actions[2]);same(&remote,&update_server_globals.updates[1].update.actions[6]);
    update_server_next_update();assert(update_client_dequeue(out));same(&next,&out[2]);same(&remote,&out[6]);
    variant.delay=0;update_server_next_update();assert(update_client_dequeue(out));same(&next,&out[2]);
}
static void local_buttons(void) {
    reset();connection=_game_connection_local;add(0,0,1);
    struct player_action press=sample(3,FLAG(_unit_control_jump_bit)|FLAG(_unit_control_weapon_reload_bit)|FLAG(_unit_control_throw_grenade_bit));
    struct player_action release=press;release.control_flags=0;release.primary_trigger=0;
    update_client_globals.saved_action_collection.actions[0]=press;
    struct player_action out[MAXIMUM_NUMBER_OF_PLAYERS]={0};
    update_client_local_ticks(1);assert(update_client_dequeue(out));neutral(&out[0],1.57079632679f,0);
    assert(update_server_pending_control_flags[0]==0);
    update_client_globals.saved_action_collection.actions[0]=release;now++;
    update_client_local_ticks(1);assert(update_client_dequeue(out));same(&press,&out[0]);
    now++;update_client_local_ticks(1);assert(update_client_dequeue(out));same(&release,&out[0]);
    reset();connection=_game_connection_local;add(0,0,1);variant.delay=0;
    update_client_globals.saved_action_collection.actions[0]=press;update_client_local_ticks(1);
    memset(out,0,sizeof(out));assert(update_client_dequeue(out));same(&press,&out[0]);
}
static void remote_passthrough(void) {
    reset();add(0,0,1);struct player_action remote=sample(7,FLAG(_unit_control_jump_bit));
    update_client_relayed_actions[4].valid=TRUE;update_client_relayed_actions[4].action=remote;
    update_client_relayed_actions[4].pending_control_flags=FLAG(_unit_control_throw_grenade_bit);
    struct player_action out[MAXIMUM_NUMBER_OF_PLAYERS]={0};update_client_dequeue_distributed(out);
    remote.control_flags|=FLAG(_unit_control_throw_grenade_bit);same(&remote,&out[4]);
    assert(update_client_relayed_actions[4].pending_control_flags==0);
    variant.delay=0;struct player_action local=sample(3,2);update_client_globals.saved_action_collection.actions[0]=local;
    now++;update_client_dequeue_distributed(out);same(&local,&out[0]);
    variant.delay=33;engine_running=FALSE;now++;update_client_dequeue_distributed(out);same(&local,&out[0]);
}
static void resets(void) {
    reset();add(0,0,1);add(1,1,1);struct player_action a=sample(3,2),b=sample(6,8);
    update_client_globals.saved_action_collection.actions[0]=a;update_client_globals.saved_action_collection.actions[1]=b;
    update_client_take_local_action(0,0,&a);update_client_take_local_action(1,0,&b);
    update_client_pending_control_flags[0]=2;update_client_pending_control_flags[1]=8;
    update_client_pending_primary_triggers[0]=.3f;update_client_pending_primary_triggers[1]=.6f;
    update_queues_reset_local_input_delay(0,NULL);
    assert(!update_client_input_delays[0].valid && update_client_input_delays[1].valid);
    assert(update_client_pending_control_flags[0]==0 && update_client_pending_control_flags[1]==8);
    assert(update_client_pending_primary_triggers[0]==0 && update_client_pending_primary_triggers[1]==.6f);
    update_queues_reset_local_input_delay(-1,NULL);update_queues_reset_local_input_delay(MAXIMUM_LOCAL_PLAYERS,NULL);
    update_queues_distributed_reset();assert(!update_client_input_delays[1].valid && update_client_pending_game_time==NONE);
    assert(update_client_pending_control_flags[1]==0 && update_client_pending_primary_triggers[1]==0);
    for(int i=0;i<2;i++) {
        update_client_take_local_action(0,10+i,&a);
        assert(update_client_input_delays[0].valid);paused=i==0;held=i==1;update_client_queue_push();
        assert(!update_client_input_delays[0].valid && !update_client_input_delays[1].valid);
        paused=held=FALSE;
    }
    variant.delay=0;update_client_input_delays[0].valid=TRUE;update_client_pending_control_flags[0]=2;
    update_queues_reset_local_input_delay(0,NULL);
    assert(update_client_input_delays[0].valid && update_client_pending_control_flags[0]==2); /* Off keeps original inputs. */
}
static void future_actions(void) {
    reset();connection=_game_connection_network_server;add(0,0,1);add(1,1,1);
    struct player_action a=sample(3,2),b=sample(6,8),out[MAXIMUM_NUMBER_OF_PLAYERS]={0};
    update_client_globals.saved_action_collection.actions[0]=a;update_client_globals.saved_action_collection.actions[1]=b;
    update_server_next_update();update_server_next_update();update_server_next_update();
    assert(update_client_dequeue(out));neutral(&out[0],1.57079632679f,0);
    /* The consumed tick teleports seat 0. Its aiming vector still points into
       the old frame; the target hook must supply the newly rotated facing. */
    real_vector3d new_facing={1,0,0};
    update_client_local_inputs[0].valid=TRUE;update_client_local_inputs[0].control_flags[0]=2;
    update_queues_reset_local_input_delay(0,&new_facing);
    assert(!update_client_local_inputs[0].valid && update_client_local_inputs[0].control_flags[0]==0);
    neutral(&update_client_globals.saved_action_collection.actions[0],0,0);
    neutral(&update_server_globals.updates[1].update.actions[0],0,0);
    neutral(&update_client_globals.updates[1].update.actions[0],0,0);
    same(&b,&update_server_globals.updates[1].update.actions[1]);
    assert(update_client_dequeue(out));neutral(&out[0],0,0);same(&b,&out[1]);
    assert(update_client_dequeue(out));neutral(&out[0],0,0);same(&b,&out[1]);
    /* A new unit uses controller-facing supplied by player_control_new_unit. */
    update_client_globals.saved_action_collection.actions[0]=a;update_server_next_update();update_server_next_update();
    players[0].unit_index=(2<<16)|0;control_facings[0]=(real_euler_angles2d){.8f,.1f};
    update_queues_reset_local_input_delay(0,NULL);
    assert(update_client_dequeue(out));neutral(&out[0],.8f,.1f);same(&b,&out[1]);
    assert(update_client_dequeue(out));neutral(&out[0],.8f,.1f);same(&b,&out[1]);
}
static void spawn_consumed_action(void) {
    reset();connection=_game_connection_network_server;
    add(0,2,1);add(1,5,1);players[2].unit_index=NONE;
    struct player_action a=sample(3,FLAG(_unit_control_jump_bit)),b=sample(5,4),out[MAXIMUM_NUMBER_OF_PLAYERS]={0};
    update_client_globals.saved_action_collection.actions[0]=a;
    update_client_globals.saved_action_collection.actions[1]=b;
    update_server_next_update();assert(update_client_dequeue(out));neutral(&out[2],3,.3f);
    /* players_update can create a unit after that action was dequeued. The
       action must use postspawn controller aim, not the dead player's aim. */
    players[2].unit_index=(2<<16)|2;control_facings[0]=(real_euler_angles2d){1.1f,.2f};
    update_queues_input_delay_new_unit_action(0,&out[2]);neutral(&out[2],1.1f,.2f);
    short count=0;struct player_action const *relayed=update_server_update_actions(0,&count);
    assert(relayed && count==MAXIMUM_NUMBER_OF_PLAYERS);same(&out[2],&relayed[2]);same(&out[5],&relayed[5]);
    struct player_action actual=out[2];
    a.pad=123;
    out[2]=a;update_queues_input_delay_new_unit_action(NONE,&out[2]);same(&a,&out[2]);
    update_queues_input_delay_new_unit_action(MAXIMUM_LOCAL_PLAYERS,&out[2]);same(&a,&out[2]);
    variant.delay=0;update_queues_input_delay_new_unit_action(0,&out[2]);same(&a,&out[2]);
    variant.delay=33;engine_running=FALSE;
    update_queues_input_delay_new_unit_action(0,&out[2]);same(&a,&out[2]);same(&actual,&relayed[2]);
}
static void clock_jump(void) {
    reset();add(0,2,1);add(3,5,1);
    struct player_action a=sample(3,FLAG(_unit_control_jump_bit)),b=sample(5,4),remote=sample(7,8);
    struct player_action out[MAXIMUM_NUMBER_OF_PLAYERS]={0};
    update_client_globals.saved_action_collection.actions[0]=a;
    update_client_globals.saved_action_collection.actions[3]=b;
    update_client_dequeue_distributed(out);now++;update_client_dequeue_distributed(out);
    same(&a,&out[2]);same(&b,&out[5]);assert(update_client_input_delays[0].valid);
    update_client_pending_control_flags[0]=a.control_flags;update_client_pending_primary_triggers[0]=.3f;
    update_client_relayed_actions[7].valid=TRUE;update_client_relayed_actions[7].action=remote;
    update_client_relayed_actions[7].update_number=10;update_client_relayed_actions[7].pending_control_flags=16;
    update_server_distributed_inputs[7].valid=TRUE;update_server_distributed_inputs[7].tick=50;
    update_server_distributed_inputs[7].received_time=now;update_server_pending_control_flags[7]=32;
    control_facings[0]=(real_euler_angles2d){.4f,.2f};control_facings[3]=(real_euler_angles2d){.9f,.1f};
    long logical=update_client_globals.next_update_number_to_dequeue;
    game_time_globals->leftover_dt=.02f;game_time_set_distributed(180);
    assert(now==180 && game_time_globals->server_time==180 && game_time_globals->leftover_dt==0);
    assert(update_client_globals.next_update_number_to_dequeue==logical);
    assert(!update_client_input_delays[0].valid && !update_client_input_delays[3].valid);
    assert(!update_client_local_inputs[0].valid && !update_client_local_inputs[3].valid);
    assert(update_client_pending_control_flags[0]==0 && update_client_pending_primary_triggers[0]==0);
    assert(update_client_relayed_actions[7].valid && update_client_relayed_actions[7].update_number==10);
    same(&remote,&update_client_relayed_actions[7].action);
    assert(update_client_relayed_actions[7].pending_control_flags==16);
    assert(update_server_distributed_inputs[7].valid && update_server_distributed_inputs[7].tick==50);
    assert(update_server_distributed_inputs[7].received_time==101 && update_server_pending_control_flags[7]==32);
    update_client_dequeue_distributed(out);neutral(&out[2],.4f,.2f);neutral(&out[5],.9f,.1f);
    remote.control_flags|=16;same(&remote,&out[7]);
    /* Setting the same clock value is not a discontinuity. */
    reset();add(0,0,1);update_client_take_local_action(0,20,&a);
    update_client_local_inputs[0].valid=TRUE;game_time_set_distributed(now);
    assert(update_client_input_delays[0].valid && update_client_local_inputs[0].valid);
    struct player_action selected=update_client_take_local_action(0,21,&b);same(&a,&selected);
    /* Off retains the old setter behavior and does not touch input history. */
    reset();add(0,0,1);variant.delay=0;update_client_input_delays[0].valid=TRUE;
    update_client_local_inputs[0].valid=TRUE;update_client_local_inputs[0].action=a;
    update_client_pending_control_flags[0]=a.control_flags;update_client_pending_primary_triggers[0]=.3f;
    update_client_globals.saved_action_collection.actions[0]=a;
    game_time_globals->leftover_dt=.02f;game_time_set_distributed(190);
    assert(now==190 && game_time_globals->server_time==190 && game_time_globals->leftover_dt==0);
    assert(update_client_input_delays[0].valid && update_client_local_inputs[0].valid);
    same(&a,&update_client_local_inputs[0].action);same(&a,&update_client_globals.saved_action_collection.actions[0]);
    assert(update_client_pending_control_flags[0]==a.control_flags && update_client_pending_primary_triggers[0]==.3f);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"off"))helper_off();
    else if(!strcmp(argv[1],"delay"))helper_delay();
    else if(!strcmp(argv[1],"repeated"))helper_repeated();
    else if(!strcmp(argv[1],"lifecycle"))helper_lifecycle();
    else if(!strcmp(argv[1],"tap"))accumulated_tap();
    else if(!strcmp(argv[1],"latches"))latches();
    else if(!strcmp(argv[1],"controllers"))sparse_controllers();
    else if(!strcmp(argv[1],"host"))host_batch();
    else if(!strcmp(argv[1],"local"))local_buttons();
    else if(!strcmp(argv[1],"remote"))remote_passthrough();
    else if(!strcmp(argv[1],"resets"))resets();
    else if(!strcmp(argv[1],"future"))future_actions();
    else if(!strcmp(argv[1],"spawn"))spawn_consumed_action();
    else if(!strcmp(argv[1],"clock"))clock_jump();
    else assert(0);
    return 0;
}
'''


def fixture():
    source = (ROOT / "source/game/player_queues_new.c").read_text()
    players = (ROOT / "source/game/players.h").read_text()
    units = (ROOT / "source/units/units.h").read_text()
    game_time = (ROOT / "source/game/game_time.c").read_text()
    declarations = [block(units, "enum\n{\n\t_unit_control_crouch_modifier_bit") + ";",
                    block(source, "enum\n{\n\t/* the native builds' session limits") + ";",
                    block(players, "struct player_action\n") + ";"]
    declarations += [block(source, "struct " + name + "\n") + ";" for name in (
        "player_action_collection", "server_update", "update", "update_server_queue_datum",
        "update_client_queue_datum", "update_server_globals", "update_client_globals")]
    declarations.append((ROOT / "source/game/player_input_delay.h").read_text().replace("#pragma once", ""))
    declarations.append(block(game_time, "struct game_time_globals_struct\n") + ";")
    globals_source = source[source.index("/* ---------- globals */"):source.index("/* ---------- public code */")]
    pending = source[source.index("static unsigned long update_client_pending_control_flags"):source.index("void update_client_queue(\n")]
    signatures = (
        "void update_client_queue_push(\n", "void update_client_queue(\n",
        "static short update_client_local_player_index(\n",
        "static boolean update_client_input_delay_enabled(void)\n{",
        "static struct player_action update_client_take_local_action(\n\tshort local_player_index,\n\tlong update_number,\n\tstruct player_action const *sampled)\n{",
        "static boolean update_client_dequeue_distributed(\n",
        "boolean update_client_dequeue(\n",
        "static void update_server_take_local_actions(\n\tvoid)\n{",
        "void update_queues_distributed_reset(\n", "void update_queues_reset_local_input_delay(",
        "void update_queues_input_delay_new_unit_action(",
        "void update_queues_reset_input_delays(",
        "struct player_action const *update_server_update_actions(",
        "boolean update_client_distributed_input(\n", "void update_server_next_update(\n",
        "static struct update *update_server_get_update(\n\tlong update_number)\n{",
        "static struct update *update_client_get_update(\n\tlong update_number)\n{",
        "void update_server_build_server_update(\n", "void update_client_build_client_update(\n",
        "void update_server_handle_client_update(\n", "void update_client_local_ticks(\n",
    )
    result = PREFIX.replace("/* DECLARATIONS */", "\n".join(declarations))
    result = result.replace("/* GLOBALS */", globals_source + pending)
    functions = [block(source, name) for name in signatures]
    functions.append(block(game_time, "void game_time_set_distributed(\n"))
    result = result.replace("/* FUNCTIONS */", "\n\n".join(functions))
    result += HARNESS
    result = re.sub(r"\bunsigned\s+long\b", "uint32_t", result)
    return re.sub(r"\blong\b", "int32_t", result)


class InputDelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-input-delay-")
        work = Path(cls.temporary.name)
        source = work / "fixture.c"
        source.write_text(fixture())
        cls.binary = work / ("fixture.exe" if sys.platform == "win32" else "fixture")
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A native C compiler is required")
        math_library = [] if sys.platform == "win32" else ["-lm"]
        result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                                 "-Wno-unused-function", "-Wno-unused-variable", "-Wno-sign-compare",
                                 str(source), *math_library, "-o", str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_off_is_exact_passthrough_and_enabling_starts_with_existing_aim(self):
        self.run_case("off")

    def test_full_action_moves_exactly_one_logical_update_later(self):
        self.run_case("delay")

    def test_selecting_an_update_twice_never_rotates_or_replaces_pending_input(self):
        self.run_case("repeated")

    def test_player_life_clock_discontinuity_and_reset_clear_stale_actions(self):
        self.run_case("lifecycle")

    def test_brief_frame_tap_and_analog_trigger_survive_delay_and_outgoing_history(self):
        self.run_case("tap")

    def test_existing_one_shot_latches_do_not_duplicate_delayed_presses(self):
        self.run_case("latches")

    def test_sparse_controllers_and_datum_generations_are_independent(self):
        self.run_case("controllers")

    def test_host_batch_advances_by_update_number_and_keeps_remote_input_immediate(self):
        self.run_case("host")

    def test_local_multiplayer_buttons_cannot_bypass_delay_through_pending_flags(self):
        self.run_case("local")

    def test_remote_inputs_off_and_inactive_engine_keep_existing_behavior(self):
        self.run_case("remote")

    def test_map_pause_hold_and_targeted_teleport_reset_clear_the_correct_state(self):
        self.run_case("resets")

    def test_teleport_and_new_life_clear_prebuilt_actions_and_prime_the_new_facing(self):
        self.run_case("future")

    def test_spawn_after_dequeue_uses_new_aim_and_leaves_off_remote_actions_unchanged(self):
        self.run_case("spawn")

    def test_clock_jump_discards_local_pending_actions_without_resetting_remote_history(self):
        self.run_case("clock")


if __name__ == "__main__":
    unittest.main()
