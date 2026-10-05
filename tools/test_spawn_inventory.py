"""Run production inventory sender/receiver code against reordered object creates.

This deterministic C fixture exercises snapshot retention, reliable structural
updates, per-unit host times, datum generations, and existing ammo cadence.
Object allocation and transport are controlled fixtures; this is not a live
network or retail-Xbox gameplay test. Guest C long is int32_t on LP64 hosts.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/game/network_objects.c"

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
typedef unsigned char byte;
typedef uint16_t word;
typedef float real;
typedef int boolean;
typedef struct { real x, y, z; } real_point3d;
typedef struct { real i, j, k; } real_vector3d;
typedef struct { real red, green, blue; } real_rgb_color;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define TEST_FLAG(v,b) (((v)&(1u<<(b)))!=0)
#define csmemset memset
#define csmemcpy memcpy
#define MAXIMUM_TRACKED_OBJECTS 16
#define MAXIMUM_WEAPONS_PER_UNIT 4
#define NUMBER_OF_UNIT_GRENADE_TYPES 2
#define MAXIMUM_LOCAL_PLAYERS 4
#define MAXIMUM_ENTRIES_PER_MESSAGE 64
#define NUMBER_OF_OBJECT_CHANGE_COLORS 4
#define MAXIMUM_REGIONS_PER_OBJECT 8
#define DATAGRAM_ENTRIES(t) (512/sizeof(t))
#define DATUM_INDEX_TO_ABSOLUTE_INDEX(i) ((int32_t)((uint32_t)(i)&0xffff))
enum { TICKS_PER_SECOND=30, INVENTORY_INTERVAL_TICKS=3,
    INVENTORY_REFRESH_TICKS=30, EMPTY_INVENTORY_TICKS=90,
    MAXIMUM_OBJECT_PERIOD_TICKS=4, MAXIMUM_INVENTORY_GRENADES=16,
    _object_dead_bit=0, _object_mask_unit=1, _object_mask_weapon=2,
    _object_change_create=0, _object_change_delete=1,
    _distributed_message_inventories=4 };
#define AGE_SCALE 65535.0f
struct distributed_message_header { uint16_t header; byte type,count; int32_t game_time; };
struct weapon_magazine { short rounds_total,rounds_loaded; };
struct weapon_datum { int32_t definition_index; struct { struct weapon_magazine magazines[2]; real age; } weapon; };
struct weapon_magazine_definition { short rounds_total_maximum,rounds_total_initial,rounds_loaded_maximum; };
struct tag_block { int32_t count; struct weapon_magazine_definition *address; };
struct weapon_definition { struct { struct tag_block magazines; } weapon; };
struct unit_datum {
    struct { unsigned damage_flags; } object;
    struct { int32_t player_index; char grenade_counts[2]; short current_weapon_index,desired_weapon_index;
        int32_t weapon_object_indices[4]; } unit;
};
struct player_datum { short local_player_index; };
struct distributed_own_inventory {
    int32_t unit_index,weapon_indices[4],weapon_times[4],grenade_times[2];
};
static struct distributed_own_inventory objects_client_own_inventories[4];
static struct unit_datum units[16];
static struct weapon_datum weapons[16];
static struct weapon_magazine_definition magazines[2]={{100,100,10},{100,100,10}};
static struct weapon_definition definition={{{2,magazines}}};
static struct player_datum player={0};
static int32_t ids[16],now,objects_client_has[16],objects_host_told[16];
static boolean objects_host_state_moving[16];
static struct { int32_t object_index; } objects_client_dead[16];
static byte types[16];
static unsigned adds,drops,creates,deletes,reliable_sends,datagram_sends,create_order;
static int32_t last_sent_unit,last_sent_weapon;
static struct { unsigned deletes; } objects_statistics;
static struct { uint32_t checksum,weapons_checksum; int32_t time,ammunition_time,carried_time; }
    objects_host_inventories[16];
static struct { short count; int32_t indices[1];
    struct { short unit_count; int32_t unit_indices[4]; } machines[1]; } objects_host_viewers;
/* INVENTORY_DECLARATIONS */
static int32_t game_time_get(void) { return now; }
static boolean distributed_object_index_valid(int32_t index) {
    return index!=NONE && ((uint32_t)index>>16)!=0 && DATUM_INDEX_TO_ABSOLUTE_INDEX(index)<16;
}
static boolean network_objects_client_has(int32_t index) {
    return distributed_object_index_valid(index) &&
        objects_client_has[DATUM_INDEX_TO_ABSOLUTE_INDEX(index)]==index;
}
static void *object_try_and_get_and_verify_type(int32_t index,unsigned mask) {
    if (!distributed_object_index_valid(index) || ids[index&0xffff]!=index || !(types[index&0xffff]&mask)) return NULL;
    return mask==_object_mask_unit ? (void *)&units[index&0xffff] : (void *)&weapons[index&0xffff];
}
static struct unit_datum *unit_get(int32_t index) { assert(ids[index&0xffff]==index); return &units[index&0xffff]; }
static struct weapon_datum *weapon_try_and_get(int32_t index) {
    return object_try_and_get_and_verify_type(index,_object_mask_weapon);
}
static struct weapon_definition *weapon_definition_get(int32_t index) { (void)index; return &definition; }
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&(b)->address[i])
static boolean distributed_player_is_local(int32_t index) { return index==0; }
static struct player_datum *player_get(int32_t index) { assert(index==0); return &player; }
static boolean distributed_client_own_settled(int32_t time) { (void)time; return TRUE; }
static void distributed_client_note_own_inventory(struct distributed_own_inventory *own,int32_t index,boolean spent) {
    (void)spent; own->unit_index=index;
    memcpy(own->weapon_indices,unit_get(index)->unit.weapon_object_indices,sizeof(own->weapon_indices));
}
static void unit_network_drop_weapon(int32_t index,short slot) {
    struct unit_datum *u=unit_get(index); u->unit.weapon_object_indices[slot]=NONE;
    if (u->unit.current_weapon_index==slot) u->unit.current_weapon_index=NONE; drops++;
}
static void distributed_client_release_item(int32_t index,boolean deleting) {
    (void)deleting;
    for (int i=0;i<16;i++) if (types[i]==_object_mask_unit)
        for (int slot=0;slot<4;slot++) if (units[i].unit.weapon_object_indices[slot]==index)
            unit_network_drop_weapon(ids[i],slot);
}
static void unit_network_add_weapon(int32_t index,int32_t weapon,short slot) {
    unit_get(index)->unit.weapon_object_indices[slot]=weapon; adds++;
}
static void distributed_client_create(struct distributed_object_change const *change) {
    int slot=change->object_index&0xffff; ids[slot]=objects_client_has[slot]=change->object_index;
    types[slot]=(byte)change->definition_index; creates++;
}
static void distributed_client_delete(int32_t index) {
    if (ids[index&0xffff]==index) { ids[index&0xffff]=NONE; types[index&0xffff]=0; deletes++; }
}
struct object_iterator { int slot; int32_t index; };
static void object_iterator_new(struct object_iterator *it,unsigned mask,unsigned flags) { (void)mask;(void)flags;it->slot=-1; }
static boolean object_iterator_next(struct object_iterator *it) {
    while (++it->slot<16) if (types[it->slot]==_object_mask_unit) {it->index=ids[it->slot];return TRUE;} return FALSE;
}
static boolean distributed_object_networked(int32_t index) { return ids[index&0xffff]==index; }
static void object_get_origin(int32_t index,real_point3d *origin) { (void)index; memset(origin,0,sizeof(*origin)); }
static short distributed_host_object_period(short machine,real_point3d const *origin) { (void)machine;(void)origin;return 1; }
static void record_send(void *message,byte type,short count,word size,boolean reliable) {
    struct distributed_inventory_message *m=message;
    assert(type==_distributed_message_inventories && count>0);
    assert(size==sizeof(m->header)+count*sizeof(m->inventories[0]));
    assert(create_order); last_sent_unit=m->inventories[0].unit_index; last_sent_weapon=m->inventories[0].weapon_indices[0];
    if (reliable) reliable_sends++; else datagram_sends++;
}
static void distributed_send_to_machine(int32_t machine,void *m,byte type,short count,word size) {
    assert(machine==0); record_send(m,type,count,size,FALSE);
}
static void distributed_send_to_machine_reliably(int32_t machine,void *m,byte type,short count,word size) {
    assert(machine==0); record_send(m,type,count,size,TRUE);
}
static void distributed_host_update_objects(void) { create_order=1; }
static void distributed_host_find_viewers(void) { }
static void distributed_host_send_states(void) { assert(create_order); }
/* FUNCTIONS */
'''

HARNESS = r'''
#define UNIT ((int32_t)0x10001)
#define WEAPON ((int32_t)0x10002)
#define SECOND ((int32_t)0x10003)
#define NEXT_UNIT ((int32_t)0x20001)
static void reset(void) {
    memset(units,0,sizeof(units)); memset(weapons,0,sizeof(weapons)); memset(types,0,sizeof(types));
    memset(objects_host_inventories,0,sizeof(objects_host_inventories));
    memset(objects_client_own_inventories,0xff,sizeof(objects_client_own_inventories));
    memset(objects_client_inventories,0,sizeof(objects_client_inventories));
    reset_production_arrays();
    for(int i=0;i<16;i++) { ids[i]=NONE; units[i].unit.player_index=NONE;
        units[i].unit.current_weapon_index=units[i].unit.desired_weapon_index=NONE;
        for(int s=0;s<4;s++) units[i].unit.weapon_object_indices[s]=NONE; }
    objects_host_viewers.count=1; objects_host_viewers.indices[0]=0;
    objects_host_viewers.machines[0].unit_count=1; objects_host_viewers.machines[0].unit_indices[0]=UNIT;
    adds=drops=creates=deletes=reliable_sends=datagram_sends=create_order=0; now=1;
}
static void create(int32_t id,byte type) {
    struct distributed_object_change change={0}; change.change=_object_change_create;
    change.object_index=id; change.definition_index=type; network_objects_handle_changes(&change,1);
}
static struct distributed_inventory snapshot(int32_t unit,int32_t weapon) {
    struct distributed_inventory inv={0}; inv.unit_index=unit; inv.current_weapon_index=0;
    for(int s=0;s<4;s++) inv.weapon_indices[s]=NONE;
    inv.weapon_indices[0]=weapon; inv.rounds_loaded[0][0]=4; inv.rounds_total[0][0]=12; return inv;
}
static void ordered_spawn(void) {
    reset(); create(UNIT,_object_mask_unit); create(WEAPON,_object_mask_weapon);
    struct distributed_inventory inv=snapshot(UNIT,WEAPON); receive(&inv,1,1);
    assert(unit_get(UNIT)->unit.weapon_object_indices[0]==WEAPON);
    assert(unit_get(UNIT)->unit.desired_weapon_index==0 && adds==1);
    assert(weapon_try_and_get(WEAPON)->weapon.magazines[0].rounds_loaded==4);
}
static void early_inventory(void) {
    reset(); struct distributed_inventory inv=snapshot(UNIT,WEAPON); receive(&inv,1,1);
    assert(!adds); create(UNIT,_object_mask_unit); assert(!adds);
    create(WEAPON,_object_mask_weapon);
    assert(unit_get(UNIT)->unit.weapon_object_indices[0]==WEAPON && adds==1);
    assert(unit_get(UNIT)->unit.desired_weapon_index==0);
    create(WEAPON,_object_mask_weapon); assert(adds==1); /* duplicate reliable create */
}
static void early_weapon(void) {
    reset(); create(UNIT,_object_mask_unit); struct distributed_inventory inv=snapshot(UNIT,WEAPON);
    receive(&inv,1,1); create(WEAPON,_object_mask_weapon);
    assert(unit_get(UNIT)->unit.weapon_object_indices[0]==WEAPON && adds==1);
}
static void delayed_secondary(void) {
    reset(); create(UNIT,_object_mask_unit); create(WEAPON,_object_mask_weapon);
    struct distributed_inventory inv=snapshot(UNIT,WEAPON);
    struct unit_datum *unit=unit_get(UNIT);
    inv.weapon_indices[1]=SECOND; inv.current_weapon_index=1;
    inv.rounds_loaded[1][0]=7; inv.rounds_total[1][0]=20;
    receive(&inv,1,1);
    /* A known primary must not partially apply the two-weapon spawn. */
    assert(objects_client_inventories[UNIT&0xffff].pending && !adds);
    assert(unit->unit.weapon_object_indices[0]==NONE && unit->unit.weapon_object_indices[1]==NONE);
    assert(unit->unit.desired_weapon_index==NONE);
    assert(weapon_try_and_get(WEAPON)->weapon.magazines[0].rounds_loaded==0);
    distributed_client_retry_inventories(); assert(!adds);
    create(SECOND,_object_mask_weapon);
    assert(!objects_client_inventories[UNIT&0xffff].pending && adds==2 && !drops);
    assert(unit->unit.weapon_object_indices[0]==WEAPON && unit->unit.weapon_object_indices[1]==SECOND);
    assert(unit->unit.desired_weapon_index==1);
    assert(weapon_try_and_get(WEAPON)->weapon.magazines[0].rounds_loaded==4);
    assert(weapon_try_and_get(WEAPON)->weapon.magazines[0].rounds_total==12);
    assert(weapon_try_and_get(SECOND)->weapon.magazines[0].rounds_loaded==7);
    assert(weapon_try_and_get(SECOND)->weapon.magazines[0].rounds_total==20);
    distributed_client_retry_inventories(); create(SECOND,_object_mask_weapon);
    assert(adds==2 && !drops); /* retry and duplicate create do not reattach either slot */
}
static void newer_inventory(void) {
    reset(); create(UNIT,_object_mask_unit);
    struct distributed_inventory old=snapshot(UNIT,WEAPON), newer=snapshot(UNIT,SECOND);
    receive(&old,1,1); receive(&newer,1,2); create(WEAPON,_object_mask_weapon); assert(!adds);
    create(SECOND,_object_mask_weapon); assert(unit_get(UNIT)->unit.weapon_object_indices[0]==SECOND);
    receive(&old,1,1); assert(unit_get(UNIT)->unit.weapon_object_indices[0]==SECOND && !drops);
}
static void independent_units(void) {
    reset(); struct distributed_inventory newer=snapshot((int32_t)0x10004,NONE), older=snapshot(UNIT,WEAPON);
    newer.current_weapon_index=NONE;
    receive(&newer,1,20); receive(&older,1,10); create(UNIT,_object_mask_unit); create(WEAPON,_object_mask_weapon);
    assert(unit_get(UNIT)->unit.weapon_object_indices[0]==WEAPON);
}
static void generation(void) {
    reset(); create(UNIT,_object_mask_unit); struct distributed_inventory inv=snapshot(UNIT,WEAPON);
    receive(&inv,1,1); struct distributed_object_change del={0}; del.change=_object_change_delete;del.object_index=UNIT;
    network_objects_handle_changes(&del,1); create(NEXT_UNIT,_object_mask_unit); create(WEAPON,_object_mask_weapon);
    assert(!adds && unit_get(NEXT_UNIT)->unit.weapon_object_indices[0]==NONE);
    receive(&inv,1,1); distributed_client_retry_inventories(); assert(!adds);
    inv.unit_index=NEXT_UNIT; receive(&inv,1,3);
    assert(unit_get(NEXT_UNIT)->unit.weapon_object_indices[0]==WEAPON && adds==1);
}
static void reset_cache(void) {
    reset(); struct distributed_inventory inv=snapshot(UNIT,WEAPON); receive(&inv,1,100);
    reset_production_arrays(); create(UNIT,_object_mask_unit);create(WEAPON,_object_mask_weapon); assert(!adds);
    receive(&inv,1,1); assert(adds==1); /* new game can restart its clock */
}
static void host_cadence(void) {
    reset(); create(UNIT,_object_mask_unit);create(WEAPON,_object_mask_weapon);
    struct unit_datum *unit=unit_get(UNIT); unit->unit.weapon_object_indices[0]=WEAPON;unit->unit.current_weapon_index=0;
    /* The spawn occurs off the old tick%3 cadence and its unreliable batch is lost. */
    network_objects_host_tick(); assert(reliable_sends==1 && datagram_sends==0);
    assert(last_sent_unit==UNIT && last_sent_weapon==WEAPON);
    now=2; network_objects_host_tick(); assert(reliable_sends==1 && !datagram_sends);
    weapon_try_and_get(WEAPON)->weapon.magazines[0].rounds_loaded=3;
    network_objects_host_tick(); assert(reliable_sends==1 && !datagram_sends);
    now=3;network_objects_host_tick(); assert(reliable_sends==1 && datagram_sends==1);
    now=4;unit->unit.grenade_counts[0]=1;network_objects_host_tick();assert(reliable_sends==2 && datagram_sends==1);
    now=6;network_objects_host_tick();assert(reliable_sends==2 && datagram_sends==1);
    now=36;network_objects_host_tick();assert(reliable_sends==2 && datagram_sends==2); /* unchanged refresh */
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"ordered")) ordered_spawn();
    else if(!strcmp(argv[1],"early")) early_inventory();
    else if(!strcmp(argv[1],"weapon")) early_weapon();
    else if(!strcmp(argv[1],"secondary")) delayed_secondary();
    else if(!strcmp(argv[1],"newer")) newer_inventory();
    else if(!strcmp(argv[1],"independent")) independent_units();
    else if(!strcmp(argv[1],"generation")) generation();
    else if(!strcmp(argv[1],"reset")) reset_cache();
    else if(!strcmp(argv[1],"cadence")) host_cadence();
    else assert(0);
    puts("spawn inventory fixture passed");return 0;
}
'''


def fixture(source):
    declarations = "\n".join(block(source, signature) + ";" for signature in (
        "struct distributed_inventory\n", "struct distributed_inventory_message\n",
        "struct distributed_object_change\n"))
    fixed = "static boolean distributed_client_inventory_ready(" in source
    cache = """static struct { long time; boolean pending; struct distributed_inventory inventory; }
        objects_client_inventories[MAXIMUM_TRACKED_OBJECTS];"""
    functions = [block(source, "static void distributed_client_apply_inventory(")]
    if fixed:
        functions.extend(block(source, signature) for signature in (
            "static boolean distributed_client_inventory_ready(",
            "static void distributed_client_retry_inventories(\n"))
    else:
        functions.append("static void distributed_client_retry_inventories(void) {}")
    functions.append(block(source, "void network_objects_handle_inventories("))
    arguments = "entries,count,time" if fixed else "entries,count"
    functions.append(f"static void receive(void const *entries,short count,long time) "
                     f"{{ (void)time; network_objects_handle_inventories({arguments}); }}")
    functions.extend(block(source, signature) for signature in (
        "void network_objects_handle_changes(", "static void distributed_inventory_from_unit(",
        "static unsigned long distributed_checksum("))
    kinds = source.split("/* the kinds of inventories sent this time */", 1)[1].split(
        "/* what every unit carries", 1)[0]
    functions.append(kinds)
    functions.extend(block(source, signature) for signature in (
        "static void distributed_host_send_inventories(", "void network_objects_host_tick("))
    new_game = block(source, "void network_objects_new_game(")
    reset_loop = block(new_game, "for (absolute_index = 0;")
    functions.append("static void reset_production_arrays(void) { long absolute_index;" + reset_loop + "}")
    text = PREFIX.replace("/* INVENTORY_DECLARATIONS */", declarations + "\n" + cache).replace(
        "/* FUNCTIONS */", "\n".join(functions)) + HARNESS
    text = re.sub(r"\bunsigned long\b", "uint32_t", text)
    return re.sub(r"\blong\b", "int32_t", text)


def compile_fixture(source, directory):
    path = Path(directory) / "spawn_inventory.c"
    path.write_text(fixture(source))
    executable = path.with_suffix(".exe" if os.name == "nt" else "")
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise RuntimeError("The spawn inventory fixture requires a C compiler (clang or cc)")
    math_library = [] if os.name == "nt" else ["-lm"]
    subprocess.run([compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                    str(path), *math_library, "-o", str(executable)], check=True, capture_output=True, text=True)
    return executable


class SpawnInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        try:
            cls.executable = compile_fixture(SOURCE.read_text(), cls.directory.name)
        except subprocess.CalledProcessError as exc:
            cls.directory.cleanup()
            raise RuntimeError(exc.stderr) from exc

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, scenario):
        subprocess.run([str(self.executable), scenario], check=True, capture_output=True, text=True)

    def test_ordered_spawn(self): self.run_case("ordered")
    def test_inventory_before_unit_and_weapons(self): self.run_case("early")
    def test_inventory_before_weapon(self): self.run_case("weapon")
    def test_two_weapon_spawn_waits_for_delayed_secondary(self): self.run_case("secondary")
    def test_latest_pending_and_older_reliable_snapshot(self): self.run_case("newer")
    def test_other_units_do_not_discard_spawn_snapshot(self): self.run_case("independent")
    def test_deleted_life_and_reused_absolute_index(self): self.run_case("generation")
    def test_new_game_resets_pending_and_host_time(self): self.run_case("reset")
    def test_same_tick_reliable_spawn_and_existing_ammo_cadence(self): self.run_case("cadence")


if __name__ == "__main__":
    unittest.main()
