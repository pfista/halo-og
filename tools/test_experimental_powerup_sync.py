"""Run optional camo/overshield sync through production receiver and refresh code.

The fixtures replace object allocation, map placement and message transport;
finite/axis validation and the object receiver code come from production source.
They do not establish real multiplayer behavior or original Xbox parity.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/game/network_objects.c"


def run_fixture(text):
    with tempfile.TemporaryDirectory(prefix="halo-powerup-sync-") as temporary:
        source = Path(temporary) / "fixture.c"
        binary = source.with_suffix(".exe" if sys.platform == "win32" else "")
        source.write_text(text)
        math_library = [] if sys.platform == "win32" else ["-lm"]
        subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", str(source), *math_library,
                        "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


RECEIVER_PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef unsigned char byte;
typedef unsigned short word;
typedef int boolean;
typedef float real;
typedef struct { real x,y,z; } real_point3d;
typedef struct { real i,j,k; } real_vector3d;
typedef struct { real red,green,blue; } real_rgb_color;
#define NONE (-1)
#define TRUE 1
#define FALSE 0
#define FLAG(bit) (1u<<(bit))
#define TEST_FLAG(flags,bit) (((flags)&FLAG(bit))!=0)
#define SET_FLAG(flags,bit,value) ((flags)=(value)?((flags)|FLAG(bit)):((flags)&~FLAG(bit)))
#define csmemcpy memcpy
#define csmemset memset
#define NUMBER_OF_OBJECT_CHANGE_COLORS 1
#define MAXIMUM_REGIONS_PER_OBJECT 1
#define MAXIMUM_TRACKED_OBJECTS 64
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->data)[i])
#define DATUM_INDEX_TO_ABSOLUTE_INDEX(i) ((i)&0xffff)
#define REMOTE_OBJECT_TOLERANCE .05f
#define REMOTE_OBJECT_ANGLE_TOLERANCE .99f
#define REMOTE_BLEND_DISTANCE 1.f
#define REMOTE_VEHICLE_BLEND_DISTANCE 1.f
#define LOCAL_VEHICLE_TOLERANCE .1f
#define OBJECT_WORLD_BOUND 32768.f
#define OBJECT_INDEX 0x10001L
enum { _object_type_equipment, _object_type_vehicle, _object_type_weapon, _object_type_biped };
enum { _object_mask_item=FLAG(_object_type_equipment)|FLAG(_object_type_weapon),
       _object_mask_unit=FLAG(_object_type_vehicle)|FLAG(_object_type_biped), _object_mask_all=15 };
enum { _object_at_rest_bit, _object_connected_to_map_bit, _object_dead_bit, _object_on_ground_bit };
enum { _distributed_object_carried_bit, _distributed_object_at_rest_bit,
       _distributed_object_dead_bit, _distributed_object_predicted_bit };
enum { _item_attached_to_unit_bit, _item_on_structure_bit, _item_on_object_bit };
enum { _equipment_powerup_none, _equipment_powerup_double_speed, _equipment_powerup_overshield,
       _equipment_powerup_active_camouflage, _equipment_powerup_full_spectrum_vision,
       _equipment_powerup_health, _equipment_powerup_grenade };
struct object_fields { unsigned flags,damage_flags; short type; long parent_object_index;
    real_point3d position; real_vector3d forward,up,translational_velocity,angular_velocity;
    real_rgb_color base_change_colors[1]; byte region_permutations[1]; };
struct object_datum { long definition_index; struct object_fields object; };
struct item_datum { long definition_index; struct object_fields object;
    struct { unsigned flags; short rested_surface_index,bsp_index; long item_on_rest_object_index;
             real_point3d item_rest_object_offset; } item; };
struct unit_datum { struct { long driver_object_index,player_index; } unit; };
struct object_definition { struct { struct { long index; } model; short type; } object; };
struct equipment_definition { struct { short powerup_type; } equipment; };
struct model_region { struct { int count; } permutations; };
struct model { struct { int count; void *data; } regions; };
struct distributed_object_change { byte flags,owner_player_index; long object_index,definition_index;
    short owner_team_index,variant_number; real_point3d position; real_vector3d forward,up,
    translational_velocity,angular_velocity; real_rgb_color change_colors[1]; byte region_permutations[1]; };
struct distributed_object_state { long object_index; byte flags; real_point3d position;
    real_vector3d forward,up,translational_velocity,angular_velocity; };
struct object_placement_data { long definition_index,owner_player_index; short owner_team_index,variant_number;
    real_point3d position; real_vector3d forward,up,translational_velocity,angular_velocity;
    real_rgb_color change_colors[1]; };
struct datum_header { short identifier; };
static struct datum_header headers[MAXIMUM_TRACKED_OBJECTS];
static struct { long maximum_count,size; void *data; } header_data={64,sizeof(struct datum_header),headers}, *object_header_data=&header_data;
static struct item_datum storage;
static struct object_datum *const object=(struct object_datum *)&storage;
static struct unit_datum unit={{NONE,NONE}};
static struct object_definition definition={.object.model.index=NONE,.object.type=_object_type_equipment};
static struct equipment_definition equipment={{_equipment_powerup_active_camouflage}};
static struct model model;
static long objects_client_has[MAXIMUM_TRACKED_OBJECTS];
static long objects_client_creating_index=NONE;
static boolean objects_client_creating,objects_client_deleting;
static struct { int creates,create_failures; } objects_statistics;
static int enabled,corrections,moves,new_calls,interpolation_calls,reconnects,visible=1,kill_immediate,damage_calls;
static struct object_datum *object_get(long i) { assert(i==OBJECT_INDEX && headers[1].identifier==1);return object; }
static struct object_datum *object_try_and_get(long i) { return i==OBJECT_INDEX && headers[1].identifier==1?object:NULL; }
static struct object_definition *object_definition_get(long i) { assert(i==13);return &definition; }
static struct equipment_definition *equipment_definition_get(long i) { assert(i==13);return &equipment; }
static struct model *model_definition_get(long i) { (void)i;return &model; }
static struct item_datum *item_get(long i) { assert(i==OBJECT_INDEX);return &storage; }
static struct unit_datum *unit_get(long i) { (void)i;return &unit; }
static int config_boolean(char const *name) { assert(!strcmp(name,"network.experimental_powerup_sync"));return enabled; }
static void object_set_garbage(long i,int v) { (void)i;(void)v; }
static void object_disconnect_from_map(long i) { SET_FLAG(object_get(i)->object.flags,_object_connected_to_map_bit,FALSE); }
static void object_reconnect_to_map(long i,void *location) { (void)location;reconnects++;SET_FLAG(object_get(i)->object.flags,_object_connected_to_map_bit,TRUE); }
static void object_set_visibility(long i,int value) { (void)i;visible=value; }
static void unit_kill_silent(long i) { (void)i; }
static void unit_kill_no_statistics(long i) { (void)i; }
static void object_damage_update(long i) { assert(i==OBJECT_INDEX);damage_calls++;if(kill_immediate) headers[1].identifier=0; }
static boolean distributed_object_index_valid(long i) { return i!=NONE && (i>>16)!=0; }
static boolean network_objects_client_has(long i) { return i==OBJECT_INDEX && objects_client_has[1]==i; }
static void distributed_client_dead_biped(long i) { (void)i; }
static void *object_try_and_get_and_verify_type(long i,int mask) { (void)mask;return object_try_and_get(i); }
static void distributed_object_state_unpack(struct distributed_object_state const *state,real_vector3d *f,
    real_vector3d *u,real_vector3d *v,real_vector3d *a) { *f=state->forward;*u=state->up;*v=state->translational_velocity;*a=state->angular_velocity; }
static boolean distributed_player_is_local(long i) { (void)i;return FALSE; }
static boolean distributed_client_correct_own_vehicle(long i,long p,struct distributed_object_state const *s) { (void)i;(void)p;(void)s;return FALSE; }
static boolean distributed_client_own_object(long i) { (void)i;return FALSE; }
static void distributed_count_correction(void) { corrections++; }
static void object_set_position(long i,real_point3d const *p,real_vector3d const *f,real_vector3d const *u) {
    struct object_datum *o=object_get(i);o->object.position=*p;o->object.forward=*f;o->object.up=*u;moves++;
}
static void render_interpolation_correct_object(long i,real_vector3d const *offset) { (void)i;(void)offset;interpolation_calls++; }
static void distributed_client_delete(long i) { (void)i;headers[1].identifier=0; }
static void distributed_client_create_failed(void) { objects_statistics.create_failures++; }
static long distributed_player_from_byte(byte player) { return player; }
static void object_placement_data_new(struct object_placement_data *p,long d,long owner) { (void)owner;memset(p,0,sizeof(*p));p->definition_index=d; }
static void object_delete_immediately(long i) { (void)i;headers[1].identifier=0; }
static long object_new(struct object_placement_data const *p) {
    assert(objects_client_creating && objects_client_creating_index==OBJECT_INDEX);new_calls++;
    memset(&storage,0,sizeof(storage));object->definition_index=p->definition_index;
    object->object.type=definition.object.type;object->object.parent_object_index=NONE;
    object->object.flags=FLAG(_object_connected_to_map_bit);object->object.position=p->position;
    object->object.forward=p->forward;object->object.up=p->up;
    object->object.translational_velocity=p->translational_velocity;object->object.angular_velocity=p->angular_velocity;
    headers[1].identifier=1;return OBJECT_INDEX;
}
/* VALIDATORS */
static boolean distributed_client_change_valid(struct distributed_object_change const *c,real_vector3d *f,real_vector3d *u) {
    return distributed_transform_valid(&c->position,&c->forward,&c->up,&c->translational_velocity,&c->angular_velocity,f,u);
}
/* PRODUCTION */
static void reset(int experimental,int powerup,int reused) {
    memset(&storage,0,sizeof(storage));memset(headers,0,sizeof(headers));
    for(int i=0;i<MAXIMUM_TRACKED_OBJECTS;i++) objects_client_has[i]=NONE;
    memset(&objects_statistics,0,sizeof(objects_statistics));enabled=experimental;
    corrections=moves=new_calls=interpolation_calls=reconnects=kill_immediate=damage_calls=0;visible=1;
    equipment.equipment.powerup_type=powerup;definition.object.type=_object_type_equipment;
    object->definition_index=13;object->object.type=_object_type_equipment;
    object->object.parent_object_index=NONE;object->object.flags=FLAG(_object_connected_to_map_bit);
    object->object.position=(real_point3d){5,-2,10};object->object.forward=(real_vector3d){1,0,0};object->object.up=(real_vector3d){0,0,1};
    object->object.translational_velocity=(real_vector3d){2,3,4};object->object.angular_velocity=(real_vector3d){5,6,7};
    headers[1].identifier=reused?1:0;objects_client_has[1]=reused?OBJECT_INDEX:NONE;
}
static struct distributed_object_change change(int rest) {
    struct distributed_object_change c={0};c.object_index=OBJECT_INDEX;c.definition_index=13;
    c.flags=rest?FLAG(_distributed_object_at_rest_bit):0;c.position=(real_point3d){5,-2,10};
    c.forward=(real_vector3d){1,0,0};c.up=(real_vector3d){0,0,1};
    c.translational_velocity=(real_vector3d){.1f,.2f,-.3f};c.angular_velocity=(real_vector3d){.4f,.5f,.6f};return c;
}
static struct distributed_object_state state(int rest) {
    struct distributed_object_change c=change(rest);struct distributed_object_state s={0};
    s.object_index=c.object_index;s.flags=c.flags;s.position=c.position;s.forward=c.forward;s.up=c.up;
    s.translational_velocity=c.translational_velocity;s.angular_velocity=c.angular_velocity;return s;
}
static void zero_velocity(void) {
    real_vector3d zero={0};assert(!memcmp(&object->object.translational_velocity,&zero,sizeof(zero)));
    assert(!memcmp(&object->object.angular_velocity,&zero,sizeof(zero)));
}
'''


class ExperimentalPowerupSyncTests(unittest.TestCase):
    def test_setting_defaults_off_without_environment_override(self):
        source = (ROOT / "port/linux/src/port_config.c").read_text()
        self.assertRegex(source, r'\{\s*"network\.experimental_powerup_sync",\s*'
                         r'_config_boolean,\s*"false",\s*NULL,\s*_environment_value,\s*_platform_all,')

    def test_create_and_state_receiver(self):
        source = SOURCE.read_text()
        distributed = (ROOT / "port/linux/game/network_distributed.c").read_text()
        validators = "\n".join(block(distributed, signature) for signature in (
            "boolean distributed_real_valid(\n", "boolean distributed_point_valid(\n",
            "boolean distributed_axes_make_valid(\n"))
        validators += "\n" + "\n".join(block(source, signature) for signature in (
            "static boolean distributed_vector_valid(\n", "static boolean distributed_transform_valid(\n"))
        production = "\n".join(block(source, signature) for signature in (
            "static void distributed_object_move(\n", "boolean network_objects_reconcile(\n",
            "static boolean distributed_client_powerup_sync_target(\n",
            "static void distributed_client_powerup_sync_rest(\n",
            "static void distributed_client_powerup_sync_correct_support(\n",
            "static void distributed_client_apply_change(\n", "static void distributed_client_create(\n",
            "void network_objects_handle_states(\n"))
        tests = r'''
static void contacts(void) {
    storage.item.flags=FLAG(_item_on_structure_bit)|FLAG(_item_on_object_bit)|FLAG(6);
    storage.item.rested_surface_index=17;storage.item.bsp_index=3;storage.item.item_on_rest_object_index=42;
    storage.item.item_rest_object_offset=(real_point3d){4,5,6};
}
static void contacts_preserved(void) {
    assert(storage.item.flags==(FLAG(_item_on_structure_bit)|FLAG(_item_on_object_bit)|FLAG(6)));
    assert(storage.item.rested_surface_index==17 && storage.item.bsp_index==3 && storage.item.item_on_rest_object_index==42);
    assert(storage.item.item_rest_object_offset.x==4 && storage.item.item_rest_object_offset.y==5 && storage.item.item_rest_object_offset.z==6);
}
static void contacts_cleared(void) {
    real_point3d zero={0};assert(storage.item.flags==FLAG(6));
    assert(storage.item.rested_surface_index==NONE && storage.item.bsp_index==NONE && storage.item.item_on_rest_object_index==NONE);
    assert(!memcmp(&storage.item.item_rest_object_offset,&zero,sizeof(zero)));
}
static void assert_vectors(real_vector3d const *v,real_vector3d const *a) {
    assert(!memcmp(&object->object.translational_velocity,v,sizeof(*v)));
    assert(!memcmp(&object->object.angular_velocity,a,sizeof(*a)));
}
int main(void) {
    for(int power=_equipment_powerup_overshield;power<=_equipment_powerup_active_camouflage;power++) {
        for(int experimental=0;experimental<=1;experimental++) for(int reused=0;reused<=1;reused++) for(int rest=0;rest<=1;rest++) {
            reset(experimental,power,reused);struct distributed_object_change c=change(rest);
            if(reused) { SET_FLAG(object->object.flags,_object_at_rest_bit,!rest);object->object.position.z=0;contacts(); }
            distributed_client_create(&c);
            assert(!objects_client_creating && !objects_client_deleting && objects_client_creating_index==NONE);
            assert(new_calls==!reused && objects_client_has[1]==OBJECT_INDEX);
            assert(object->object.position.z==10 && moves==reused && interpolation_calls==reused);
            assert(TEST_FLAG(object->object.flags,_object_at_rest_bit)==(experimental?rest:(reused?!rest:0)));
            assert_vectors(&c.translational_velocity,&c.angular_velocity);
            if(reused) { if(experimental) contacts_cleared();else contacts_preserved(); }
        }
        for(int experimental=0;experimental<=1;experimental++) {
            reset(experimental,power,1);contacts();struct distributed_object_state s=state(1);
            s.translational_velocity=(real_vector3d){0};s.angular_velocity=(real_vector3d){0};
            struct item_datum before=storage;
            network_objects_handle_states(&s,1);
            assert(moves==0 && corrections==0 && interpolation_calls==0);contacts_preserved();
            if(experimental) { assert(TEST_FLAG(object->object.flags,_object_at_rest_bit));zero_velocity(); }
            else assert(!memcmp(&storage,&before,sizeof(storage))); /* Same-pose legacy skip is byte exact. */
            if(experimental) {
                object->object.translational_velocity=(real_vector3d){9,8,7};
                object->object.angular_velocity=(real_vector3d){6,5,4};
                network_objects_handle_states(&s,1);zero_velocity(); /* Already resting locally repairs stale momentum. */
                s=state(0);network_objects_handle_states(&s,1);
                assert(!TEST_FLAG(object->object.flags,_object_at_rest_bit));assert_vectors(&s.translational_velocity,&s.angular_velocity);
                contacts_preserved();assert(moves==0 && corrections==0);
                before=storage;s.translational_velocity.i=99;network_objects_handle_states(&s,1);
                assert(!memcmp(&storage,&before,sizeof(storage))); /* Unchanged moving poses keep the existing velocity skip. */
                s=state(1);network_objects_handle_states(&s,1); /* Keep finite host vectors even while resting. */
                assert_vectors(&s.translational_velocity,&s.angular_velocity);
            }
        }
        /* Invalid message numbers/axes cannot freeze, wake or invalidate contacts. */
        for(int bad=0;bad<5;bad++) {
            reset(1,power,1);contacts();struct distributed_object_state s=state(1);
            if(bad==0) s.position.z=NAN;
            if(bad==1) s.position.z=OBJECT_WORLD_BOUND+1;
            if(bad==2) s.up=s.forward;
            if(bad==3) s.translational_velocity.k=INFINITY;
            if(bad==4) s.angular_velocity.i=NAN;
            struct item_datum before=storage;network_objects_handle_states(&s,1);
            assert(!memcmp(&storage,&before,sizeof(storage)) && moves==0 && corrections==0);
            reset(1,power,1);struct distributed_object_change c=change(1);c.up=c.forward;
            before=storage;distributed_client_create(&c);
            assert(objects_statistics.create_failures==1 && !memcmp(&storage,&before,sizeof(storage)));
        }
        /* Reused and carried creates follow existing inventory/visibility rules. */
        reset(1,power,1);contacts();struct distributed_object_change c=change(1);
        c.flags|=FLAG(_distributed_object_carried_bit);distributed_client_create(&c);
        assert(!TEST_FLAG(object->object.flags,_object_connected_to_map_bit) && !visible);
        assert(!TEST_FLAG(object->object.flags,_object_at_rest_bit) && moves==0);contacts_preserved();
        reset(1,power,1);contacts();c=change(1);distributed_client_create(&c);contacts_preserved(); /* No positional correction. */
        /* Large reconciliations clear stale support (including a moving-object cache).
           The actual accepted displacement decides, rather than packet error alone. */
        for(int experimental=0;experimental<=1;experimental++) for(int rest=0;rest<=1;rest++) for(int step=0;step<3;step++) {
            reset(experimental,power,1);contacts();struct distributed_object_state s=state(rest);
            real shift=step==0?.04f:step==1?.06f:.12f;s.position.z+=shift;
            network_objects_handle_states(&s,1);
            if(step==0) { assert(moves==0);contacts_preserved(); }
            else {
                assert(moves==1 && fabsf(object->object.position.z-(10+shift*(rest?1:.5f)))<.00001f);
                if(experimental && (rest || step==2)) contacts_cleared();else contacts_preserved();
                assert(corrections==rest && interpolation_calls==rest);
            }
        }
        reset(1,power,1);contacts();struct distributed_object_state s=state(1);s.position.z+=2;
        network_objects_handle_states(&s,1);assert(object->object.position.z==12 && corrections==1);contacts_cleared();
        reset(1,power,1);contacts();s=state(1);s.forward=(real_vector3d){0,1,0};
        network_objects_handle_states(&s,1);assert(moves==1 && object->object.forward.j==1);contacts_preserved(); /* Rotation alone. */
        reset(1,power,1);s=state(1);SET_FLAG(object->object.flags,_object_connected_to_map_bit,FALSE);
        network_objects_handle_states(&s,1);assert(reconnects==1 && visible && TEST_FLAG(object->object.flags,_object_at_rest_bit));
    }
    /* Other powerups, weapons/vehicles/bipeds, parented and attached objects preserve the existing close-pose path. */
    for(int exclusion=0;exclusion<10;exclusion++) {
        reset(1,_equipment_powerup_active_camouflage,1);contacts();struct distributed_object_state s=state(1);
        if(exclusion<4) equipment.equipment.powerup_type=exclusion==0?_equipment_powerup_none:exclusion==1?_equipment_powerup_double_speed:exclusion==2?_equipment_powerup_health:_equipment_powerup_grenade;
        if(exclusion>=4 && exclusion<=6) object->object.type=exclusion==4?_object_type_weapon:exclusion==5?_object_type_vehicle:_object_type_biped;
        if(exclusion==7) object->object.parent_object_index=50;
        if(exclusion>=8) storage.item.flags|=FLAG(_item_attached_to_unit_bit);
        if(exclusion==9) SET_FLAG(object->object.flags,_object_connected_to_map_bit,FALSE);
        struct item_datum before=storage;network_objects_handle_states(&s,1);
        assert(!memcmp(&storage,&before,sizeof(storage)) && moves==0 && corrections==0 && reconnects==0);
    }
    /* Some dead biped tags destroy the new/reused object during the existing
       damage callback. Optional equipment detection must tolerate that deletion. */
    for(int experimental=0;experimental<=1;experimental++) for(int reused=0;reused<=1;reused++) {
        reset(experimental,_equipment_powerup_active_camouflage,reused);kill_immediate=1;
        definition.object.type=_object_type_biped;object->object.type=_object_type_biped;
        struct distributed_object_change c=change(1);c.flags|=FLAG(_distributed_object_dead_bit);
        distributed_client_create(&c);
        assert(damage_calls==1 && headers[1].identifier==0 && new_calls==!reused);
    }
    return 0;
}
'''
        fixture = RECEIVER_PREFIX.replace("/* VALIDATORS */", validators).replace("/* PRODUCTION */", production)
        run_fixture(fixture + tests)

    def test_resting_refresh_budget_and_complete_cursor_coverage(self):
        function = block(SOURCE.read_text(), "static void distributed_host_send_states(\n")
        # Keep the production moving/rest selection exactly, ending before the
        # transport fanout. Capture its resulting states instead of sending.
        selection = function[:function.index("\n\tfor (machine_number = 0;")]
        selection += r'''
    captured_count=state_count;
    for(long i=0;i<state_count;i++) { captured[i]=states[i];captured_kinds[i]=kinds[i]; }
}
'''
        fixture = r'''
#include <assert.h>
#include <string.h>
typedef unsigned char byte;
typedef int boolean;
#define NONE (-1)
#define TRUE 1
#define FALSE 0
#define FLAG(bit) (1u<<(bit))
#define TEST_FLAG(flags,bit) (((flags)&FLAG(bit))!=0)
#define MAXIMUM_TRACKED_OBJECTS 64
#define RESTING_STATES_PER_TICK 4
#define MAXIMUM_ENTRIES_PER_MESSAGE 20
#define DATAGRAM_ENTRIES(t) 20
#define MIN(a,b) ((a)<(b)?(a):(b))
enum { _object_at_rest_bit, _host_state_moving=0, _host_state_to_all=1 };
struct object_datum { struct { unsigned flags; } object; };
struct distributed_object_state { long object_index; };
struct distributed_object_state_message { int unused; };
static struct object_datum objects[64];
static int present[64],enabled;
static long objects_host_told_count,objects_host_resting_cursor;
static boolean objects_host_state_moving[64];
static struct distributed_object_state captured[68];
static byte captured_kinds[68];
static long captured_count;
static boolean config_boolean(char const *name) { assert(!strcmp(name,"network.experimental_powerup_sync"));return enabled; }
static long distributed_host_placed_object(long index) { assert(index>=0 && index<objects_host_told_count);return present[index]?index:NONE; }
static struct object_datum *object_get(long index) { assert(index>=0 && index<64);return &objects[index]; }
static void distributed_state_from_object(long index,struct distributed_object_state *state) { state->object_index=index; }
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wunused-variable"
/* SELECTION */
#pragma clang diagnostic pop
static void reset(int experimental,long count) {
    enabled=experimental;objects_host_told_count=count;objects_host_resting_cursor=0;captured_count=0;
    memset(objects,0,sizeof(objects));memset(present,0,sizeof(present));memset(objects_host_state_moving,0,sizeof(objects_host_state_moving));
}
static int resting(long *indices,int *visited) {
    int count=0;int this_tick[64]={0};
    for(long i=0;i<captured_count;i++) if(captured_kinds[i]==_host_state_to_all) {
        long index=captured[i].object_index;
        assert(present[index] && TEST_FLAG(objects[index].object.flags,_object_at_rest_bit));
        assert(!this_tick[index]);this_tick[index]=1;visited[index]=1;indices[count++]=index;
    }
    assert(count<=RESTING_STATES_PER_TICK);return count;
}
int main(void) {
    long indices[4];int visited[64]={0};
    reset(0,30);for(int i=0;i<30;i++) { present[i]=1;objects[i].object.flags=FLAG(_object_at_rest_bit); }
    distributed_host_send_states();assert(resting(indices,visited)==4);
    assert(indices[0]==0 && indices[1]==2 && indices[2]==5 && indices[3]==9 && objects_host_resting_cursor==10);
    for(int tick=1;tick<30;tick++) { distributed_host_send_states();resting(indices,visited); }
    int seen=0;for(int i=0;i<30;i++) seen+=visited[i];assert(seen==12); /* Disabled preserves the exact legacy sweep. */
    for(int count=1;count<=64;count++) {
        reset(1,count);memset(visited,0,sizeof(visited));
        for(int i=0;i<count;i++) { present[i]=1;objects[i].object.flags=FLAG(_object_at_rest_bit); }
        for(int tick=0;tick<(count+3)/4;tick++) {
            distributed_host_send_states();assert(resting(indices,visited)==(count<4?count:4));
        }
        for(int i=0;i<count;i++) assert(visited[i]); /* Dense includes formerly starved indices. */
    }
    reset(1,64);memset(visited,0,sizeof(visited));
    int sparse[]={1,3,17,22,42,63};
    for(int i=0;i<6;i++) { present[sparse[i]]=1;objects[sparse[i]].object.flags=FLAG(_object_at_rest_bit); }
    present[8]=present[18]=1; /* Moving candidates between missing and resting slots. */
    objects_host_resting_cursor=63;distributed_host_send_states();assert(resting(indices,visited)==4);
    assert(indices[0]==63 && indices[1]==1 && indices[2]==3 && indices[3]==17 && objects_host_resting_cursor==18);
    distributed_host_send_states();assert(resting(indices,visited)==4);
    for(int i=0;i<6;i++) assert(visited[sparse[i]]);
    reset(1,64);memset(visited,0,sizeof(visited));
    for(int i=0;i<64;i++) { present[i]=1;objects[i].object.flags=FLAG(_object_at_rest_bit); }
    objects_host_resting_cursor=63;distributed_host_send_states();assert(resting(indices,visited)==4);
    assert(indices[0]==63 && indices[1]==0 && indices[2]==1 && indices[3]==2 && objects_host_resting_cursor==3);
    for(int experimental=0;experimental<=1;experimental++) {
        reset(experimental,0);distributed_host_send_states();assert(captured_count==0 && objects_host_resting_cursor==0);
    }
    reset(1,64);for(int i=0;i<64;i++) present[i]=1; /* No resting candidates: one full traversal, zero budget use. */
    distributed_host_send_states();memset(visited,0,sizeof(visited));assert(resting(indices,visited)==0 && objects_host_resting_cursor==0);
    reset(1,30);for(int i=0;i<30;i++) { present[i]=1;objects[i].object.flags=FLAG(_object_at_rest_bit); }
    objects_host_state_moving[7]=TRUE;distributed_host_send_states();
    assert(captured_count==5 && captured[0].object_index==7 && captured_kinds[0]==_host_state_to_all);
    for(int i=1;i<5;i++) assert(captured[i].object_index==i-1 && captured_kinds[i]==_host_state_to_all);
    /* An immediate stop notification remains additional to the four refresh states. */
    return 0;
}
'''
        run_fixture(fixture.replace("/* SELECTION */", selection))


if __name__ == "__main__":
    unittest.main()
