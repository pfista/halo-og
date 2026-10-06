"""Exercise production Fiesta selection, inventory transactions and placement rules.

The fixture runs the C helpers and ordinary weapon initialization/inventory APIs
with deterministic tag/object storage. It does not simulate network transport or
certify physical-controller playability.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


def run_fixture(text):
    with tempfile.TemporaryDirectory(prefix="halo-fiesta-spawn-") as temporary:
        source = Path(temporary) / "fixture.c"
        binary = source.with_suffix("")
        source.write_text(text)
        subprocess.run(["clang", "-std=gnu89", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", "-Wno-multichar", "-Wno-sign-compare",
                        str(source), "-o", str(binary)], check=True, capture_output=True)
        subprocess.run([str(binary)], check=True, capture_output=True)


PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define NONE (-1)
#define TRUE 1
#define FALSE 0
#define NUMBEROF(a) (sizeof(a)/sizeof((a)[0]))
#define FLAG(b) (1u<<(b))
#define TEST_FLAG(v,b) (((v)&FLAG(b))!=0)
#define SET_FLAG(v,b,on) ((v)=(on)?((v)|FLAG(b)):((v)&~FLAG(b)))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define TAG_BLOCK_GET_ELEMENT(b,i,t) (&((t *)(b)->address)[i])
typedef int boolean;
enum { _object_type_weapon=2, _object_type_equipment=3,
    _object_mask_unit=1, _object_connected_to_map_bit=0,
    _unit_control_weapon_primary_trigger_bit=0,
    _unit_grenade_human_fragmentation=0, _unit_grenade_covenant_plasma=1,
    _weapon_state_idle=0,
    _weapon_must_be_readied_bit=3, _weapon_doesnt_count_toward_maximum_bit=4,
    GAME_WEAPON_SET_UNCUT=11, GAME_WEAPON_SET_ALL=12,
    _game_engine_weapons_plasma_weapons=3, _game_engine_weapons_human=9,
    _game_engine_weapons_no_grenades=10,
    _game_engine_9_or_more_players_bit=3, _game_engine_5_or_more_players_bit=2,
    _game_variant_generic_starting_equipment_bit=5,
    _starting_equipment_custom=0, _starting_equipment_generic=1, _starting_equipment_fiesta=2,
    MAXIMUM_WEAPONS_PER_UNIT=4 };
/* PLACEMENT FLAGS */
/* INVENTORY MODES */
struct tag_block { short count; void *address; };
struct object_definition { struct { short type; } object; };
struct weapon_magazine_definition { short rounds_total_initial, rounds_loaded_maximum; };
struct weapon_trigger_definition { int unused; };
struct tag_reference { long index; };
struct weapon_definition { struct { unsigned flags; struct tag_block magazines, triggers;
    struct { struct tag_reference first_person_model, first_person_animations; } interface_definition; } weapon; };
struct tag_iterator { int index; };
struct weapon_magazine { short rounds_loaded, rounds_total; };
struct weapon_trigger { long charging_effect_index; short idle_ticks; };
struct weapon_datum {
    long definition_index;
    struct { unsigned flags; long parent_object_index; } object;
    struct { short state; long overheated_effect_index; float age;
        struct weapon_magazine magazines[1]; struct weapon_trigger triggers[1]; } weapon;
    int alive, inventory, deleted, objective;
};
struct unit_datum { struct { long weapon_object_indices[4], weapon_last_used_at_game_time[4];
    short current_weapon_index, desired_weapon_index; unsigned control_flags;
    char grenade_counts[2]; } unit; };
struct object_placement_data { long definition_index; unsigned flags; long owner; };
struct game_variant { int mode; struct { unsigned flags; int weapon_set; } universal_variant; };
struct game_globals_grenade { long maximum_count; };
struct game_globals { struct tag_block grenades; };
struct player_datum { long unit_index; };
struct game_engine { void (*player_update)(long); };
static struct game_variant global_variant;
static struct game_engine engine, *game_engine=&engine;
static struct { unsigned flags; } game_engine_globals;
static struct game_globals_grenade grenade_definitions[2]={{4},{4}};
static struct game_globals globals={{2,grenade_definitions}};
static struct player_datum player={1};
static struct unit_datum player_unit;
static struct weapon_datum objects[256];
static struct object_definition object_definitions[64];
static struct weapon_definition weapon_definitions[64];
static struct weapon_magazine_definition magazine_definitions[64];
static long tag_indices[64];
static long packed_indices[9];
static char packed_names[9][128];
static int multiplayer=1, client, create_calls, delete_calls, add_calls, can_use_calls, reverse_tag_iteration,
    allocation_failure, can_use_failure, picking_up_failure, custom_calls, infinite_grenades, global_arsenal_loaded,
    remap_calls, rng_calls, forced_rng, draw[2], predicted_count;
static long predicted[64];
static short local_desired;
static uint32_t seed;
static unsigned long rng_seed;
static const char *canonical_names[26]={
    "weapons\\assault rifle\\assault rifle", "weapons\\needler\\needler",
    "weapons\\pistol\\pistol", "weapons\\plasma pistol\\plasma pistol",
    "weapons\\plasma rifle\\plasma rifle", "weapons\\rocket launcher\\rocket launcher",
    "weapons\\shotgun\\shotgun", "weapons\\sniper rifle\\sniper rifle",
    "weapons\\smg\\smg", "weapons\\grenade launcher\\assault rifle",
    "weapons\\chaingun\\chaingun", "weapons\\excavator\\excavator",
    "weapons\\gravity_wrench\\gravity_wrench", "weapons\\machete\\machete",
    "weapons\\speargun\\speargun", "weapons\\space luger\\space luger",
    "weapons\\missile launcher\\missile launcher", "weapons\\bolt action rifle\\bolt action rifle",
    "weapons\\battle rifle\\battle rifle", "weapons\\flamethrower\\flamethrower",
    "weapons\\flag\\flag", "weapons\\vehicle\\gun", "weapons\\ai\\gun",
    "weapons\\sentinel beam\\sentinel beam",
    "community\\digsite_compat\\weapons\\flamethrower\\flamethrower",
    "community\\weapon_pack\\community\\digsite_compat\\weapons\\flamethrower\\flamethrower" };
static int game_engine_running(void) { return multiplayer; }
static int network_game_distributed_client(void) { return client; }
static int network_objects_creating_host_object(void) { return client; }
static int starting_equipment_get(const struct game_variant *v) { return v->mode; }
static unsigned long *get_global_random_seed_address(void) { return &rng_seed; }
static short seed_random_range(unsigned long *s,short lower,short upper) {
    unsigned value;
    assert(s==&rng_seed && lower==0 && upper>=1 && upper<=64);
    value=forced_rng?(unsigned)draw[rng_calls]:
        (unsigned)(upper*(uint32_t)((seed=seed*1664525u+1013904223u)>>16)>>16);
    rng_calls++; assert(value<(unsigned)upper); return (short)value;
}
static long tag_loaded(long group,const char *name) {
    int i;
    if(group=='bipd') {
        assert(!strcmp(name,"community\\weapon_pack\\player\\cyborg"));
        return global_arsenal_loaded ? 100:NONE;
    }
    assert(group=='weap');
    for(i=0;i<26;i++) if(!strcmp(name,canonical_names[i])) return tag_indices[i];
    if(!strncmp(name,"community\\weapon_pack\\",22)) {
        for(i=0;i<9;i++) if(!strcmp(name+22,canonical_names[8+i])) return packed_indices[i];
        return NONE;
    }
    return NONE;
}
static const char *tag_get_name(long i) { assert(i>=0 && i<35);return i<26 ? canonical_names[i]:packed_names[i-26]; }
static struct object_definition *object_definition_get(long i) {
    assert(i>=0 && i<64); return &object_definitions[i];
}
static struct weapon_definition *weapon_definition_get(long i) {
    assert(i>=0 && i<64); return &weapon_definitions[i];
}
static struct weapon_datum *weapon_get(long i) {
    assert(i>=0 && i<256 && objects[i].alive); return &objects[i];
}
static struct weapon_magazine *weapon_magazine_get(struct weapon_datum *w,short i) {
    assert(i==0); return &w->weapon.magazines[i];
}
static struct weapon_trigger *weapon_trigger_get(struct weapon_datum *w,short i) {
    assert(i==0); return &w->weapon.triggers[i];
}
static void weapon_precache_projectile_trails(long i) { (void)i; }
static struct unit_datum *unit_get(long i) { assert(i==1); return &player_unit; }
static int weapon_is_flag(long i) { return weapon_get(i)->objective; }
static void object_placement_data_new(struct object_placement_data *p,long d,long owner) {
    p->definition_index=d; p->flags=0; p->owner=owner;
}
static long game_engine_remap_object_definition(long d) {
    remap_calls++; return global_variant.universal_variant.weapon_set==6?5:d;
}
/* WEAPON INITIALIZATION */
static long object_new(struct object_placement_data *data) {
    long definition_index=data->definition_index, i;
    create_calls++; if(create_calls==allocation_failure) return NONE;
    /* PLACEMENT REMAP */
    assert(definition_index>=0 && definition_index<64);
    i=200+create_calls;
    objects[i].alive=1; objects[i].definition_index=definition_index;
    objects[i].object.flags=FLAG(_object_connected_to_map_bit);
    objects[i].object.parent_object_index=NONE; objects[i].weapon.age=0;
    assert(data->owner==1); weapon_new(i); return i;
}
static void object_delete(long i) {
    assert(i!=NONE && objects[i].alive && !objects[i].objective);
    objects[i].alive=0; objects[i].deleted=1; delete_calls++;
}
static boolean unit_can_use_weapon(long unit,long w) {
    assert(unit==1 && objects[w].alive); can_use_calls++;
    return can_use_calls!=can_use_failure;
}
static boolean game_engine_picking_up(long unit,long w) {
    assert(unit==1 && objects[w].alive); add_calls++;
    return add_calls!=picking_up_failure;
}
static void object_disconnect_from_map(long w) {
    assert(TEST_FLAG(objects[w].object.flags,_object_connected_to_map_bit));
    SET_FLAG(objects[w].object.flags,_object_connected_to_map_bit,FALSE);
}
static void object_set_visibility(long w,boolean v) { (void)w;(void)v; }
static void item_in_unit_inventory(long w,long u) { assert(u==1); objects[w].inventory=1; }
static short unit_weapon_next_index(long u,short current,int unused) {
    short i;(void)current;(void)unused; assert(u==1);
    for(i=0;i<4;i++) if(player_unit.unit.weapon_object_indices[i]!=NONE) return i;
    return NONE;
}
static void unit_delete_all_weapons(long u) { (void)u;assert(!"Fiesta used partial deletion helper"); }
static void player_control_set_desired_weapon(long u,short i) {
    assert(u==1);local_desired=i;
}
/* INVENTORY FREE SLOT */
/* INVENTORY ATTACH */
static void tag_iterator_new(struct tag_iterator *iterator,long group) {
    assert(group=='weap'); iterator->index=0;
}
static long tag_iterator_next(struct tag_iterator *iterator) {
    while(iterator->index<35) { int i=reverse_tag_iteration ? 34-iterator->index++ : iterator->index++,previous;
        if(tag_indices[i]==NONE) continue;
        for(previous=0;previous<i;previous++) if(tag_indices[previous]==tag_indices[i]) break;
        if(previous==i) return tag_indices[i];
    }
    return NONE;
}
/* FIESTA POOL */
static short collect_pool(long *pool) {
    struct fiesta_weapon_iterator iterator;long definition;short count=0;
    fiesta_weapon_iterator_new(&iterator,global_variant.universal_variant.weapon_set);
    while((definition=fiesta_weapon_iterator_next(&iterator))!=NONE) pool[count++]=definition;
    return count;
}
/* FIESTA SPAWN */
static struct player_datum *player_get(long i) { assert(i==0); return &player; }
static struct game_globals *scenario_get_game_globals(void) { return &globals; }
static struct unit_datum *object_get_and_verify_type(long i,int mask) {
    assert(mask==_object_mask_unit);return unit_get(i);
}
static void handle_custom_starting_equipment(long u,long *frag,long *plasma) {
    assert(u==1);custom_calls++;*frag=0;*plasma=3;
}
static boolean game_engine_infinite_grenades_internal(void) { return infinite_grenades; }
/* POSTSPAWN */
static void object_definition_predict(long i) { predicted[predicted_count++]=i; }
static void predict_fiesta(void) {
    /* PREDICTION */
}
static void reset(void) {
    int i;
    memset(objects,0,sizeof(objects));memset(&player_unit,0,sizeof(player_unit));
    global_variant.mode=_starting_equipment_fiesta;
    global_variant.universal_variant.flags=FLAG(_game_variant_generic_starting_equipment_bit);
    global_variant.universal_variant.weapon_set=0;
    for(i=0;i<9;i++) {
        packed_indices[i]=NONE;
        sprintf(packed_names[i],"community\\weapon_pack\\%s",canonical_names[i+8]);
    }
    for(i=0;i<35;i++) {
        tag_indices[i]=i<8?i:NONE;object_definitions[i].object.type=_object_type_weapon;
        weapon_definitions[i].weapon.flags=0;
        weapon_definitions[i].weapon.interface_definition.first_person_model.index=i;
        weapon_definitions[i].weapon.interface_definition.first_person_animations.index=i;
        magazine_definitions[i].rounds_total_initial=(short)(30+i*10);
        magazine_definitions[i].rounds_loaded_maximum=(short)(5+i);
        weapon_definitions[i].weapon.magazines.count=1;
        weapon_definitions[i].weapon.magazines.address=&magazine_definitions[i];
        weapon_definitions[i].weapon.triggers.count=0;
    }
    for(i=0;i<4;i++) {player_unit.unit.weapon_object_indices[i]=NONE;
        player_unit.unit.weapon_last_used_at_game_time[i]=100+i;}
    objects[100].alive=objects[101].alive=1;
    objects[100].definition_index=0;objects[101].definition_index=2;
    player_unit.unit.weapon_object_indices[0]=100;player_unit.unit.weapon_object_indices[1]=101;
    player_unit.unit.current_weapon_index=0;player_unit.unit.desired_weapon_index=1;
    local_desired=1;
    player.unit_index=1;multiplayer=1;client=0;engine.player_update=0;
    reverse_tag_iteration=0;
    global_arsenal_loaded=0;
    create_calls=delete_calls=add_calls=can_use_calls=custom_calls=remap_calls=rng_calls=0;
    allocation_failure=can_use_failure=picking_up_failure=infinite_grenades=predicted_count=0;
    forced_rng=1;draw[0]=2;draw[1]=5;seed=1;game_engine_globals.flags=0;
}
static void assert_original(void) {
    int i;assert(objects[100].alive && objects[101].alive);
    assert(player_unit.unit.weapon_object_indices[0]==100);
    assert(player_unit.unit.weapon_object_indices[1]==101);
    assert(player_unit.unit.weapon_object_indices[2]==NONE);
    assert(player_unit.unit.weapon_object_indices[3]==NONE);
    assert(player_unit.unit.current_weapon_index==0 && player_unit.unit.desired_weapon_index==1);
    assert(local_desired==1);
    for(i=0;i<4;i++) assert(player_unit.unit.weapon_last_used_at_game_time[i]==100+i);
}
static void assert_pair(long first,long second) {
    int i;
    assert(rng_calls==2 && create_calls==2 && remap_calls==0);
    assert(!objects[100].alive && !objects[101].alive && delete_calls==2);
    assert(player_unit.unit.current_weapon_index==NONE && player_unit.unit.desired_weapon_index==0);
    assert(local_desired==0);
    for(i=0;i<2;i++) {
        struct weapon_datum *w=weapon_get(player_unit.unit.weapon_object_indices[i]);
        long d=i?second:first;
        assert(w->definition_index==d && w->inventory && !w->deleted && w->weapon.age==0);
        assert(w->weapon.magazines[0].rounds_loaded==magazine_definitions[d].rounds_loaded_maximum);
        assert(w->weapon.magazines[0].rounds_total==magazine_definitions[d].rounds_total_initial-
            magazine_definitions[d].rounds_loaded_maximum);
    }
    assert(player_unit.unit.weapon_object_indices[2]==NONE && player_unit.unit.weapon_object_indices[3]==NONE);
}
'''


class FiestaSpawnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "source/game/game_engine.c").read_text()
        objects = (ROOT / "source/objects/objects.c").read_text()
        units = (ROOT / "source/units/units.c").read_text()
        flags = (ROOT / "source/objects/objects.h").read_text()
        flags_start = flags.index("enum\n{\n\t_new_object_mirrored_bit")
        flags = flags[flags_start:flags.index("};", flags_start) + 2]
        modes = block((ROOT / "source/units/units.h").read_text(), "enum unit_add_weapon_mode") + ";"
        remap_start = objects.index("if (game_engine_running() && definition_index!=NONE")
        remap = objects[remap_start:objects.index("if (definition_index!=NONE)", remap_start)]
        prediction = block(source, "static void game_engine_predict_resources(\n\tvoid)\n{")
        prediction_start = prediction.index("if (starting_equipment_get(&global_variant)")
        prediction = "#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS\n" + prediction[prediction_start:prediction.rindex("#endif") + 6]
        replacements = {
            "/* PLACEMENT FLAGS */": flags,
            "/* INVENTORY MODES */": modes,
            "/* PLACEMENT REMAP */": remap,
            "/* WEAPON INITIALIZATION */": block((ROOT / "source/items/weapons.c").read_text(), "boolean weapon_new(\n\tlong weapon_index)\n{"),
            "/* INVENTORY FREE SLOT */": block(units, "static short unit_first_free_weapon_index(\n\tlong unit_index)\n{"),
            "/* INVENTORY ATTACH */": block(units, "boolean unit_add_weapon_to_inventory(\n\tlong unit_index,\n\tlong weapon_index,\n\tlong is_starting_weapon)\n{"),
            "/* FIESTA POOL */": "\n".join(line for line in (ROOT / "source/game/fiesta_weapon_pool.h").read_text().splitlines() if not line.startswith("#include")),
            "/* FIESTA SPAWN */": block(source, "static void handle_fiesta_starting_equipment(long unit_index)\n{"),
            "/* POSTSPAWN */": block(source, "void game_engine_postspawn_player_update(\n\tlong player_index)\n{"),
            "/* PREDICTION */": prediction,
        }
        cls.fixture = PREFIX
        for marker, replacement in replacements.items():
            cls.fixture = cls.fixture.replace(marker, replacement)

    def test_all_ordered_pairs_and_rng_determinism(self):
        run_fixture(self.fixture + r'''
int main(void) {
    int a,b,i,seen[8][8]={{0}},first[64],second[64];
    for(a=0;a<8;a++) for(b=0;b<7;b++) {
        reset();draw[0]=a;draw[1]=b;handle_fiesta_starting_equipment(1);
        assert_pair(a,b>=a?b+1:b);seen[a][b>=a?b+1:b]++;
    }
    for(a=0;a<8;a++) for(b=0;b<8;b++) assert(seen[a][b]==(a!=b));
    seed=42;
    for(i=0;i<64;i++) {
        uint32_t keep=seed;reset();seed=keep;forced_rng=0;handle_fiesta_starting_equipment(1);
        first[i]=(int)weapon_get(player_unit.unit.weapon_object_indices[0])->definition_index;
        second[i]=(int)weapon_get(player_unit.unit.weapon_object_indices[1])->definition_index;
        assert(first[i]!=second[i] && rng_calls==2);
    }
    seed=42;
    for(i=0;i<64;i++) {
        uint32_t keep=seed;reset();seed=keep;forced_rng=0;handle_fiesta_starting_equipment(1);
        assert(weapon_get(player_unit.unit.weapon_object_indices[0])->definition_index==first[i]);
        assert(weapon_get(player_unit.unit.weapon_object_indices[1])->definition_index==second[i]);
    }
    return 0;
}
''')

    def test_stock_modes_clients_campaign_and_objectives_do_not_draw(self):
        run_fixture(self.fixture + r'''
int main(void) {
    int mode;
    for(mode=0;mode<2;mode++) {reset();global_variant.mode=mode;
        handle_fiesta_starting_equipment(1);assert_original();assert(!rng_calls && !create_calls);}
    reset();client=1;handle_fiesta_starting_equipment(1);assert_original();assert(!rng_calls);
    reset();multiplayer=0;handle_fiesta_starting_equipment(1);assert_original();assert(!rng_calls);
    reset();handle_fiesta_starting_equipment(NONE);assert_original();assert(!rng_calls);
    reset();objects[100].objective=1;handle_fiesta_starting_equipment(1);assert_original();assert(!rng_calls);
    return 0;
}
''')

    def test_unavailable_invalid_and_aliased_tags(self):
        run_fixture(self.fixture + r'''
int main(void) {
    long pool[8];int i;
    reset();assert(collect_pool(pool)==8);
    for(i=0;i<8;i++) assert(pool[i]==i);
    tag_indices[2]=1;assert(collect_pool(pool)==7);
    object_definitions[4].object.type=_object_type_equipment;
    tag_indices[6]=NONE;assert(collect_pool(pool)==5);
    weapon_definitions[3].weapon.flags=FLAG(_weapon_must_be_readied_bit);
    assert(collect_pool(pool)==4);
    for(i=0;i<4;i++) assert(pool[i]!=3);
    reset();weapon_definitions[0].weapon.flags=FLAG(_weapon_must_be_readied_bit);
    draw[0]=0;draw[1]=0;handle_fiesta_starting_equipment(1);assert_pair(1,2);
    reset();for(i=1;i<8;i++) tag_indices[i]=NONE;
    handle_fiesta_starting_equipment(1);assert_original();assert(!rng_calls && !create_calls);
    tag_indices[7]=7;draw[0]=1;draw[1]=0;
    handle_fiesta_starting_equipment(1);assert_pair(7,0);
    return 0;
}
''')

    def test_allocation_compatibility_and_attachment_failures_restore_inventory(self):
        run_fixture(self.fixture + r'''
int main(void) {
    int failure;
    for(failure=1;failure<=2;failure++) {
        reset();allocation_failure=failure;handle_fiesta_starting_equipment(1);
        assert_original();assert(delete_calls==failure-1);
    }
    for(failure=1;failure<=4;failure++) {
        reset();can_use_failure=failure;handle_fiesta_starting_equipment(1);
        assert_original();assert(delete_calls==(failure==1?1:2));
        assert(!objects[201].alive && !objects[202].alive);
    }
    for(failure=1;failure<=2;failure++) {
        reset();picking_up_failure=failure;handle_fiesta_starting_equipment(1);
        assert_original();assert(delete_calls==2 && !objects[201].alive && !objects[202].alive);
    }
    return 0;
}
''')

    def test_uncut_and_all_pool_membership_and_every_ordered_pair(self):
        run_fixture(self.fixture + r'''
int main(void) {
    long pool[32];int set,a,b,i,count;
    for(set=11;set<=12;set++) {
        reset();for(i=8;i<24;i++) tag_indices[i]=i;
        weapon_definitions[20].weapon.flags=FLAG(_weapon_must_be_readied_bit);
        weapon_definitions[21].weapon.flags=FLAG(_weapon_doesnt_count_toward_maximum_bit);
        weapon_definitions[22].weapon.interface_definition.first_person_model.index=NONE;
        global_variant.universal_variant.weapon_set=set;
        count=collect_pool(pool);assert(count==(set==11?9:21));
        for(i=0;i<count;i++) assert(pool[i]==(set==11?i+8:(i<20?i:23)));
        predict_fiesta();assert(predicted_count==count);
        for(i=0;i<count;i++) assert(predicted[i]==pool[i]);
        for(a=0;a<count;a++) for(b=0;b<count-1;b++) {
            reset();for(i=8;i<24;i++) tag_indices[i]=i;
            weapon_definitions[20].weapon.flags=FLAG(_weapon_must_be_readied_bit);
            weapon_definitions[21].weapon.flags=FLAG(_weapon_doesnt_count_toward_maximum_bit);
            weapon_definitions[22].weapon.interface_definition.first_person_model.index=NONE;
            global_variant.universal_variant.weapon_set=set;draw[0]=a;draw[1]=b;
            handle_fiesta_starting_equipment(1);
            assert_pair(pool[a],pool[b>=a?b+1:b]);
        }
    }
    return 0;
}
''')

    def test_uncut_missing_assets_never_substitute_launch_weapons(self):
        run_fixture(self.fixture + r'''
int main(void) {
    long pool[32];int i;
    reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_UNCUT;
    assert(!collect_pool(pool));handle_fiesta_starting_equipment(1);
    assert_original();assert(!rng_calls && !create_calls);
    tag_indices[8]=8;tag_indices[9]=8;assert(collect_pool(pool)==1);
    handle_fiesta_starting_equipment(1);assert_original();assert(!rng_calls);
    tag_indices[10]=10;weapon_definitions[10].weapon.interface_definition.first_person_animations.index=NONE;
    assert(collect_pool(pool)==1);
    weapon_definitions[10].weapon.interface_definition.first_person_animations.index=10;
    draw[0]=0;draw[1]=0;handle_fiesta_starting_equipment(1);assert_pair(8,10);
    reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    for(i=8;i<24;i++) tag_indices[i]=i;
    weapon_definitions[0].weapon.flags=FLAG(_weapon_must_be_readied_bit);
    assert(collect_pool(pool)==23);
    for(i=0;i<23;i++) assert(pool[i]!=0);
    return 0;
}
''')

    def test_all_counts_compatibility_alias_only_once(self):
        run_fixture(self.fixture + r'''
int main(void) {
    long pool[32];
    reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    tag_indices[19]=19;tag_indices[24]=24;
    assert(collect_pool(pool)==9 && pool[8]==19);
    tag_indices[19]=NONE;
    assert(collect_pool(pool)==9 && pool[8]==24);
    return 0;
}
''')

    def test_all_flamethrower_alias_precedence_prediction_and_ordered_pairs(self):
        run_fixture(self.fixture + r'''
static void aliases(int presence,int reverse) {
    reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    tag_indices[19]=(presence&1)?19:NONE;
    tag_indices[24]=(presence&2)?24:NONE;
    tag_indices[25]=(presence&4)?25:NONE;
    reverse_tag_iteration=reverse;
}
int main(void) {
    long pool[32];int presence,reverse,a,b,i,count,preferred;
    /* Cover canonical/plain/packed aliases individually and together. The
     * real pack cache visits its packed alias before the stock canonical. */
    for(presence=1;presence<8;presence++) for(reverse=0;reverse<2;reverse++) {
        aliases(presence,reverse);count=collect_pool(pool);assert(count==9);
        preferred=(presence&1)?19:(presence&2)?24:25;
        assert(pool[reverse?0:8]==preferred);
        for(i=0;i<count;i++) assert(pool[i]<8 || pool[i]==preferred);
        predict_fiesta();assert(predicted_count==count);
        for(i=0;i<count;i++) assert(predicted[i]==pool[i]);
        for(a=0;a<count;a++) for(b=0;b<count-1;b++) {
            aliases(presence,reverse);draw[0]=a;draw[1]=b;
            handle_fiesta_starting_equipment(1);
            assert_pair(pool[a],pool[b>=a?b+1:b]);
        }
    }
    return 0;
}
''')

    def test_all_eligible_alias_survives_ineligible_preferred_identities(self):
        run_fixture(self.fixture + r'''
int main(void) {
    long pool[32];int invalid,preferred,alias;
    for(invalid=0;invalid<5;invalid++) for(preferred=19;preferred<=24;preferred+=5) {
        reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
        alias=preferred==19?24:25;
        tag_indices[preferred]=preferred;tag_indices[alias]=alias;
        if(invalid==0) object_definitions[preferred].object.type=_object_type_equipment;
        if(invalid==1) weapon_definitions[preferred].weapon.flags=FLAG(_weapon_must_be_readied_bit);
        if(invalid==2) weapon_definitions[preferred].weapon.flags=FLAG(_weapon_doesnt_count_toward_maximum_bit);
        if(invalid==3) weapon_definitions[preferred].weapon.interface_definition.first_person_model.index=NONE;
        if(invalid==4) weapon_definitions[preferred].weapon.interface_definition.first_person_animations.index=NONE;
        assert(collect_pool(pool)==9 && pool[8]==alias);
        predict_fiesta();assert(predicted_count==9 && predicted[8]==alias);
        draw[0]=8;draw[1]=0;handle_fiesta_starting_equipment(1);assert_pair(alias,0);
        if(preferred==19) {
            /* An invalid canonical plus both eligible aliases still contributes
             * exactly one weapon, using the plain compatibility identity. */
            tag_indices[25]=25;assert(collect_pool(pool)==9 && pool[8]==24);
            tag_indices[24]=NONE;assert(collect_pool(pool)==9 && pool[8]==25);
        }
    }
    return 0;
}
''')

    def test_uncut_resolves_namespaced_weapon_pack_without_retail_replacements(self):
        run_fixture(self.fixture + r'''
int main(void) {
    long pool[32];
    reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_UNCUT;
    packed_indices[0]=8;packed_indices[1]=9;
    assert(collect_pool(pool)==2 && pool[0]==8 && pool[1]==9);
    draw[0]=0;draw[1]=0;handle_fiesta_starting_equipment(1);assert_pair(8,9);
    reset();global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_UNCUT;
    tag_indices[8]=8;packed_indices[0]=24;packed_indices[1]=9;
    assert(collect_pool(pool)==2 && pool[0]==8 && pool[1]==9);
    return 0;
}
''')

    def test_global_uncut_has_all_nine_on_stock_map_and_prefers_global_definitions(self):
        run_fixture(self.fixture + r'''
static void global_uncut(int originals) {
    int i;reset();global_arsenal_loaded=1;
    global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_UNCUT;
    for(i=0;i<9;i++) {
        packed_indices[i]=tag_indices[26+i]=26+i;
        tag_indices[8+i]=originals?8+i:NONE;
    }
}
int main(void) {
    long pool[64];int originals,a,b,i;
    for(originals=0;originals<2;originals++) {
        global_uncut(originals);assert(collect_pool(pool)==9);
        /* The full arsenal must not pin every candidate's textures at once. */
        predict_fiesta();assert(predicted_count==0);
        for(i=0;i<9;i++) assert(pool[i]==26+i);
        for(a=0;a<9;a++) for(b=0;b<8;b++) {
            global_uncut(originals);draw[0]=a;draw[1]=b;
            handle_fiesta_starting_equipment(1);
            assert_pair(26+a,26+(b>=a?b+1:b));
        }
    }
    global_uncut(1);packed_indices[0]=tag_indices[26]=NONE;
    assert(collect_pool(pool)==8);
    for(i=0;i<8;i++) assert(pool[i]==27+i);
    return 0;
}
''')

    def test_global_all_counts_imported_identity_once_in_either_cache_order(self):
        run_fixture(self.fixture + r'''
static void global_all(int reverse) {
    int i;reset();global_arsenal_loaded=1;reverse_tag_iteration=reverse;
    global_variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    for(i=0;i<9;i++) {
        packed_indices[i]=tag_indices[26+i]=26+i;
        tag_indices[8+i]=8+i;
    }
}
int main(void) {
    long pool[64];int reverse,a,b,i;
    for(reverse=0;reverse<2;reverse++) {
        global_all(reverse);assert(collect_pool(pool)==17);
        predict_fiesta();assert(predicted_count==0);
        for(i=0;i<17;i++) {
            assert(pool[i]==(reverse?(i<9?34-i:16-i):(i<8?i:18+i)));
        }
        for(a=0;a<17;a++) for(b=0;b<16;b++) {
            global_all(reverse);draw[0]=a;draw[1]=b;
            handle_fiesta_starting_equipment(1);
            assert_pair(pool[a],pool[b>=a?b+1:b]);
        }
    }
    return 0;
}
''')

    def test_weapon_set_independence_and_original_resource_prediction(self):
        run_fixture(self.fixture + r'''
int main(void) {
    int mode,i;struct object_placement_data placement;
    reset();global_variant.universal_variant.weapon_set=6;
    handle_fiesta_starting_equipment(1);assert_pair(2,6);
    predict_fiesta();assert(predicted_count==8);
    for(i=0;i<8;i++) assert(predicted[i]==i);
    assert(remap_calls==0 && rng_calls==2);
    for(mode=0;mode<2;mode++) {reset();global_variant.mode=mode;predict_fiesta();assert(!predicted_count);}
    reset();global_variant.universal_variant.weapon_set=6;
    object_placement_data_new(&placement,2,1);assert(weapon_get(object_new(&placement))->definition_index==5);
    assert(remap_calls==1);
    reset();global_variant.universal_variant.weapon_set=6;client=1;
    object_placement_data_new(&placement,2,1);assert(weapon_get(object_new(&placement))->definition_index==2);
    assert(remap_calls==0);
    reset();multiplayer=0;global_variant.universal_variant.weapon_set=6;
    object_placement_data_new(&placement,2,1);assert(weapon_get(object_new(&placement))->definition_index==2);
    assert(remap_calls==0);
    return 0;
}
''')

    def test_postspawn_keeps_original_grenade_rules_and_custom_generic_behavior(self):
        run_fixture(self.fixture + r'''
int main(void) {
    reset();game_engine_postspawn_player_update(0);assert_pair(2,6);
    assert(!custom_calls && player_unit.unit.grenade_counts[0]==4 && player_unit.unit.grenade_counts[1]==0);
    reset();global_variant.universal_variant.flags=0;game_engine_postspawn_player_update(0);
    assert_pair(2,6);assert(!custom_calls);
    assert(player_unit.unit.grenade_counts[0]==4 && player_unit.unit.grenade_counts[1]==0);
    reset();game_engine_globals.flags=FLAG(_game_engine_5_or_more_players_bit);
    game_engine_postspawn_player_update(0);assert(player_unit.unit.grenade_counts[0]==2);
    reset();game_engine_globals.flags=FLAG(_game_engine_9_or_more_players_bit);
    game_engine_postspawn_player_update(0);assert(player_unit.unit.grenade_counts[0]==1);
    reset();global_variant.universal_variant.weapon_set=_game_engine_weapons_plasma_weapons;
    game_engine_postspawn_player_update(0);assert_pair(2,6);
    assert(player_unit.unit.grenade_counts[0]==0 && player_unit.unit.grenade_counts[1]==4);
    reset();global_variant.universal_variant.weapon_set=_game_engine_weapons_no_grenades;
    game_engine_postspawn_player_update(0);
    assert(player_unit.unit.grenade_counts[0]==0 && player_unit.unit.grenade_counts[1]==0);
    reset();global_variant.universal_variant.weapon_set=_game_engine_weapons_no_grenades;infinite_grenades=1;
    game_engine_postspawn_player_update(0);
    assert(player_unit.unit.grenade_counts[0]==4 && player_unit.unit.grenade_counts[1]==4);
    reset();global_variant.mode=_starting_equipment_custom;global_variant.universal_variant.flags=0;
    game_engine_postspawn_player_update(0);assert(custom_calls==1 && !rng_calls && !create_calls);
    assert(player_unit.unit.grenade_counts[0]==0 && player_unit.unit.grenade_counts[1]==3);
    reset();global_variant.mode=_starting_equipment_generic;
    game_engine_postspawn_player_update(0);assert_original();assert(!custom_calls && !rng_calls && !create_calls);
    assert(player_unit.unit.grenade_counts[0]==4 && player_unit.unit.grenade_counts[1]==0);
    return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
