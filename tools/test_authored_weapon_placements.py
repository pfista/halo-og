"""Run production weapon remapping and map-capability lifecycle offline.

The fixture supplies deterministic tag storage and engine callbacks. It uses
the real registry lookup, marker detector, cache iterator, remapper and timer
classifier; it never builds or launches the game.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block


ROOT = Path(__file__).resolve().parents[1]


PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#include <strings.h>
#define _stricmp strcasecmp
#endif
typedef unsigned char byte;
typedef int boolean;
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define NUMBEROF(a) (sizeof(a)/sizeof(*(a)))
#define TEST_FLAG(v,b) (((v)&(1UL<<(b)))!=0)
#define TAG_BLOCK_GET_ELEMENT(b,i,t) ((t *)(b)->address+(i))
#define csmemset memset
#define csmemcmp memcmp
#define csstrcmp strcmp
#define string_list_definition_get(index) ((struct string_list *)tag_get(STRING_LIST_TAG,(index)))
#define _error_silent 0
#define error(...) ((void)0)
/* PRODUCTION DECLARATIONS */
struct cache_file_tag_instance {
    long group_tag, parent_group_tags[2], tag_index;
    char *name;
    void *base_address;
};
struct cache_file_tag_header {long tag_count;};
static struct cache_file_tag_header tag_header;
static struct {struct cache_file_tag_header *tag_header; boolean tags_loaded;}
    cache_file_globals = {&tag_header, TRUE};
static struct cache_file_tag_instance *global_tag_instances;
static struct string_list list;
static struct string_list_entry strings[2];
static char marker_payload[] = "halo-og:authored-weapon-placements:v1";
static long definition(short slot) {return 1000 + 17 * slot;}
struct game_globals {struct tag_block weapon_list;};
static struct tag_reference registry[16];
static struct game_globals globals;
static struct game_globals *scenario_get_game_globals(void) {return &globals;}
static char *tag_get_name(long index) {
    long absolute = index & 0xffff;
    assert(absolute >= 0 && absolute < tag_header.tag_count);
    return global_tag_instances[absolute].name;
}
static boolean tag_index_is_group(long index, long group) {
    long absolute = index & 0xffff;
    return index != NONE && absolute >= 0 && absolute < tag_header.tag_count &&
        global_tag_instances[absolute].tag_index == index &&
        global_tag_instances[absolute].group_tag == group &&
        global_tag_instances[absolute].base_address;
}
static void *tag_get(long group, long index) {
    long absolute = index & 0xffff;
    assert(absolute >= 0 && absolute < tag_header.tag_count);
    assert(global_tag_instances[absolute].group_tag == group);
    return global_tag_instances[absolute].base_address;
}
struct game_variant {struct {unsigned long flags; long weapon_set;} universal_variant;};
static struct game_variant global_variant;
static struct game_variant *game_engine_get_variant(void) {return &global_variant;}
struct game_engine {boolean (*initialize_for_new_map)(void); void (*dispose)(void);
    void (*dispose_from_old_map)(void);};
static struct game_engine engine, *game_engine;
static struct {long next_team_index;} game_engine_globals;
static long global_goal[8], timeout_for_endgame_sound;
static boolean game_engine_network_state_read;
static long expected_callback_weapon;
static unsigned initialize_callbacks, predictions, dispose_callbacks;
static void game_engine_verify_current_map(void) {}
static void game_engine_intialize_queued_sounds(void) {}
static void game_engine_predict_resources(void);
static boolean initialize_callback(void);
static void dispose_callback(void) {dispose_callbacks++;}
struct object_definition {struct {short type;} object;};
struct equipment_definition {struct {short powerup_type;} equipment;};
enum {_object_type_weapon=2,_object_type_equipment=3,
    _equipment_powerup_active_camouflage=1,_equipment_powerup_overshield=2,
    _game_variant_always_invisible_bit=2,_game_variant_no_shields_bit=3};
static struct object_definition *object_definition_get(long index) {
    static struct object_definition weapon={{_object_type_weapon}};
    assert(index != NONE);
    return &weapon;
}
static struct equipment_definition *equipment_definition_get(long index) {
    (void)index; abort();
}
/* PRODUCTION FUNCTIONS */
static boolean initialize_callback(void) {
    assert(timeout_for_endgame_sound==0 && !game_engine_network_state_read);
    initialize_callbacks++;
    assert(game_engine_remap_weapon(definition(1)) == expected_callback_weapon);
    return TRUE;
}
static void game_engine_predict_resources(void) {
    predictions++;
    assert(game_engine_remap_weapon(definition(1)) == expected_callback_weapon);
}
static void populate(long count) {
    free(global_tag_instances);
    global_tag_instances=calloc((size_t)(count ? count : 1), sizeof(*global_tag_instances));
    assert(global_tag_instances);
    tag_header.tag_count=count;
    cache_file_globals.tags_loaded=TRUE;
    for(long i=0;i<count;i++) {
        global_tag_instances[i].group_tag='weap';
        global_tag_instances[i].parent_group_tags[0]=NONE;
        global_tag_instances[i].parent_group_tags[1]=NONE;
        global_tag_instances[i].tag_index=0x10000+i;
        global_tag_instances[i].name="unrelated\\weapon";
    }
    memset(&list,0,sizeof(list)); memset(strings,0,sizeof(strings));
    list.strings.count=1; list.strings.address=strings;
    strings[0].string.size=sizeof(marker_payload);
    strings[0].string.address=marker_payload;
}
static void marker(long absolute) {
    assert(absolute>=0 && absolute<tag_header.tag_count);
    global_tag_instances[absolute].group_tag='str#';
    global_tag_instances[absolute].name="__native_policy\\authored_weapon_placements_v1";
    global_tag_instances[absolute].base_address=&list;
}
static void reset(void) {
    populate(3);
    memset(registry,0,sizeof(registry));
    for(short i=0;i<16;i++) registry[i].index=definition(i);
    globals.weapon_list.count=NUMBEROF(registry); globals.weapon_list.address=registry;
    memset(&global_variant,0,sizeof(global_variant));
    memset(&engine,0,sizeof(engine));
    engine.initialize_for_new_map=initialize_callback;
    engine.dispose_from_old_map=dispose_callback;
    game_engine=&engine;
    initialize_callbacks=predictions=dispose_callbacks=0;
    timeout_for_endgame_sound=7; game_engine_network_state_read=TRUE;
    native_authored_weapon_placements=FALSE;
    expected_callback_weapon=definition(7);
}
/* Original engine outputs: rows are saved weapon-set IDs 0-12; columns are
 * AR, Flame, Gravity, Needler, Pistol, PP, PR, Rocket, Shotgun, Sniper,
 * Ball, Flag, and two original NPC registry entries appended at 14 and 15. */
static short const slots[]={0,1,2,3,4,5,6,7,8,9,10,11,14,15};
static short const original[13][14]={
    {0,7,2,3,4,5,6,7,8,9,10,11,14,15},
    {4,5,4,5,5,4,5,5,4,4,10,11,4,4},
    {0,6,0,6,6,0,6,6,0,0,10,11,0,0},
    {6,6,6,5,5,5,6,6,6,6,10,11,6,6},
    {9,9,9,9,4,9,9,9,9,9,10,11,9,9},
    {0,7,2,3,0,5,6,7,8,8,10,11,14,15},
    {7,7,7,7,7,7,7,7,7,7,10,11,7,7},
    {8,8,8,8,8,8,8,8,8,8,10,11,8,8},
    {8,7,2,8,8,5,6,7,8,8,10,11,14,15},
    {0,7,2,0,4,4,0,7,8,9,10,11,14,15},
    {0,7,2,3,4,5,6,7,8,9,10,11,14,15},
    {0,7,2,3,4,5,6,7,8,9,10,11,14,15},
    {0,7,2,3,4,5,6,7,8,9,10,11,14,15},
};
static void matrix(void) {
    for(short enabled=0;enabled<2;enabled++) for(short mode=0;mode<13;mode++) {
        reset();
        if(enabled) marker(1);
        global_variant.universal_variant.weapon_set=mode;
        short flame=enabled && (mode==0 || mode==10 || mode==11 || mode==12) ? 1 : original[mode][1];
        expected_callback_weapon=definition(flame);
        game_engine_initialize_for_new_map();
        assert(initialize_callbacks==1 && predictions==1);
        for(unsigned column=0;column<NUMBEROF(slots);column++) {
            short expected=column==1 ? flame : original[mode][column];
            assert(game_engine_remap_weapon(definition(slots[column]))==definition(expected));
            assert(performance_timer_item_category(definition(slots[column]))==(expected==7 ? 1u : 0u));
        }
        assert(game_engine_remap_weapon(900001)==900001);
        assert(game_engine_remap_weapon(NONE)==NONE);
    }
    /* A duplicate registry reference cannot replace the first enum identity. */
    reset(); registry[15].index=definition(1);
    game_engine_initialize_for_new_map();
    assert(game_engine_remap_weapon(definition(1))==definition(7));
    marker(1); expected_callback_weapon=definition(1);
    game_engine_initialize_for_new_map();
    assert(game_engine_remap_weapon(definition(1))==definition(1));
    /* Unknown future IDs keep the original pre-remap, even on opted-in maps. */
    global_variant.universal_variant.weapon_set=13;
    assert(game_engine_remap_weapon(definition(1))==definition(7));
    global_variant.universal_variant.weapon_set=-1;
    assert(game_engine_remap_weapon(definition(1))==definition(7));
    /* Changing the variant within one loaded map does not reuse a cached mode. */
    global_variant.universal_variant.weapon_set=0;
    assert(game_engine_remap_weapon(definition(1))==definition(1));
    global_variant.universal_variant.weapon_set=6;
    assert(game_engine_remap_weapon(definition(1))==definition(7));
    global_variant.universal_variant.weapon_set=10;
    assert(game_engine_remap_weapon(definition(1))==definition(1));
}
static void malformed_marker(void) {
    reset(); marker(1); assert(game_engine_map_has_authored_weapon_placements());
    global_tag_instances[1].group_tag='ustr'; assert(!game_engine_map_has_authored_weapon_placements());
    global_tag_instances[1].group_tag='str#';
    global_tag_instances[1].name="__native_policy\\authored_weapon_placements_v2";
    assert(!game_engine_map_has_authored_weapon_placements());
    global_tag_instances[1].name="custom\\__native_policy\\authored_weapon_placements_v1";
    assert(!game_engine_map_has_authored_weapon_placements());
    global_tag_instances[1].name=NULL; assert(!game_engine_map_has_authored_weapon_placements());
    marker(1);
    global_tag_instances[1].base_address=NULL; assert(!game_engine_map_has_authored_weapon_placements());
    marker(1);
    list.strings.count=0; assert(!game_engine_map_has_authored_weapon_placements());
    list.strings.count=2; assert(!game_engine_map_has_authored_weapon_placements());
    list.strings.count=1;
    list.strings.address=NULL; assert(!game_engine_map_has_authored_weapon_placements());
    list.strings.address=strings;
    strings[0].string.address=NULL; assert(!game_engine_map_has_authored_weapon_placements());
    strings[0].string.address=marker_payload;
    strings[0].string.size=sizeof(marker_payload)-1; assert(!game_engine_map_has_authored_weapon_placements());
    strings[0].string.size=sizeof(marker_payload)+1; assert(!game_engine_map_has_authored_weapon_placements());
    strings[0].string.size=-1; assert(!game_engine_map_has_authored_weapon_placements());
    strings[0].string.size=sizeof(marker_payload);
    char invalid[sizeof(marker_payload)]; memcpy(invalid,marker_payload,sizeof(invalid));
    invalid[0]='H'; strings[0].string.address=invalid;
    assert(!game_engine_map_has_authored_weapon_placements());
    memcpy(invalid,marker_payload,sizeof(invalid)); invalid[sizeof(invalid)-1]='x';
    assert(!game_engine_map_has_authored_weapon_placements());
    strings[0].string.address=marker_payload; assert(game_engine_map_has_authored_weapon_placements());
}
static void lifecycle(void) {
    reset(); marker(1); expected_callback_weapon=definition(1);
    game_engine_initialize_for_new_map();
    assert(native_authored_weapon_placements && game_engine_remap_weapon(definition(1))==definition(1));
    game_engine_dispose_from_old_map();
    assert(!native_authored_weapon_placements && dispose_callbacks==1);
    assert(game_engine_remap_weapon(definition(1))==definition(7));
    /* Initialize clears stale capability even without an intervening dispose. */
    marker(1); game_engine_initialize_for_new_map();
    populate(3); expected_callback_weapon=definition(7);
    game_engine_initialize_for_new_map();
    assert(!native_authored_weapon_placements && game_engine_remap_weapon(definition(1))==definition(7));
    /* A menu/no-engine map also refreshes and clears the map-scoped state. */
    marker(1); game_engine=NULL; game_engine_initialize_for_new_map();
    assert(native_authored_weapon_placements);
    game_engine_dispose_from_old_map(); assert(!native_authored_weapon_placements);
    native_authored_weapon_placements=TRUE; populate(0);
    game_engine_initialize_for_new_map(); assert(!native_authored_weapon_placements);
}
static void large_cache(void) {
    reset(); populate(40000);
    assert(!game_engine_map_has_authored_weapon_placements());
    marker(32767); assert(game_engine_map_has_authored_weapon_placements());
    global_tag_instances[32767].group_tag='weap'; marker(32768);
    assert(!game_engine_map_has_authored_weapon_placements());
    populate(32768); marker(32767); assert(game_engine_map_has_authored_weapon_placements());
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"matrix")) matrix();
    else if(!strcmp(argv[1],"malformed")) malformed_marker();
    else if(!strcmp(argv[1],"lifecycle")) lifecycle();
    else if(!strcmp(argv[1],"large_cache")) large_cache();
    else abort();
    free(global_tag_instances);
    return 0;
}
'''


class AuthoredWeaponPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = (ROOT / "source/game/game_engine.c").read_text()
        cache = (ROOT / "source/cache/cache_files.c").read_text()
        tags = (ROOT / "source/tag_files/tag_groups.h").read_text()
        text = (ROOT / "source/text/text_group.h").read_text()
        declarations = [
            block(tags, "struct tag_block\n") + ";",
            block(tags, "struct tag_reference\n") + ";",
            block(tags, "struct tag_data\n") + ";",
            block(text, "struct string_list\n") + ";",
            block(text, "struct string_list_entry\n") + ";",
            block(text, "enum\n") + ";",
            block((ROOT / "source/cache/cache_files.h").read_text(), "struct tag_iterator\n") + ";",
            block((ROOT / "source/game/weapon_sets.h").read_text(), "enum\n") + ";",
            block(engine, "enum game_engine_weapons\n") + ";",
            block(engine[engine.rfind("enum\n", 0, engine.index("_weapon_list_assault_rifle =")):], "enum\n") + ";",
        ]
        state = re.search(r"(?m)^static boolean native_authored_weapon_placements[^;]*;", engine)
        if state is None:
            raise ValueError("Production map-scoped placement capability is missing")
        declarations.append(state.group(0))
        functions = [
            block(cache, "void tag_iterator_new(\n"),
            block(cache, "long tag_iterator_next(\n"),
            "#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS\n" +
            block(engine, "static boolean game_engine_map_has_authored_weapon_placements(void)\n{") + "\n" +
            block(engine, "static boolean game_engine_preserves_authored_weapon_placements(void)\n{") + "\n#endif",
            block(engine, "long game_globals_get_weapon(\n"),
            block(engine, "long list_index_to_weapon_definition_index(\n"),
            block(engine, "long weapon_definition_index_to_list_index(\n"),
            block(engine, "long game_engine_remap_weapon(\n"),
            block(engine, "void game_engine_initialize_for_new_map(\n"),
            block(engine, "void game_engine_dispose_from_old_map(\n"),
            block((ROOT / "port/linux/game/performance_timer_items.c").read_text(),
                  "static unsigned performance_timer_item_category("),
        ]
        fixture = PREFIX.replace("/* PRODUCTION DECLARATIONS */", "\n".join(declarations))
        fixture = fixture.replace("/* PRODUCTION FUNCTIONS */", "\n".join(functions))
        native_off = fixture[:fixture.index("static void matrix(void)")]
        native_off = native_off.replace("#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128\n", "")
        native_off = native_off.replace(state.group(0), "")
        native_off = native_off.replace("    native_authored_weapon_placements=FALSE;\n", "")
        native_off += r'''
int main(void) {
    assert(NUMBER_OF_GAME_ENGINE_WEAPON_SETS==11);
    for(short mode=0;mode<13;mode++) {
        reset(); marker(1); global_variant.universal_variant.weapon_set=mode;
        expected_callback_weapon=definition(original[mode][1]);
        game_engine_initialize_for_new_map();
        assert(initialize_callbacks==1 && predictions==1);
        for(unsigned column=0;column<NUMBEROF(slots);column++)
            assert(game_engine_remap_weapon(definition(slots[column]))==definition(original[mode][column]));
        assert(game_engine_remap_weapon(900001)==900001);
        assert(game_engine_remap_weapon(NONE)==NONE);
        game_engine_dispose_from_old_map(); assert(dispose_callbacks==1);
    }
    free(global_tag_instances);
    return 0;
}
'''
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-authored-placements-")
        cls.addClassCleanup(cls.temporary.cleanup)
        for name, contents in (("fixture", fixture), ("native_off", native_off)):
            source = Path(cls.temporary.name) / (name + ".c")
            binary = source.with_suffix("")
            setattr(cls, "binary" if name == "fixture" else "native_off_binary", binary)
            source.write_text(contents)
            result = subprocess.run(["clang", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                                     "-Wno-multichar", "-Wno-sign-compare", "-Wno-unused-function",
                                     str(source), "-o", str(binary)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError("Production placement fixture failed to compile:\n" + result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_original_and_marked_weapon_set_matrix(self):
        self.run_case("matrix")

    def test_marker_requires_exact_type_name_and_payload(self):
        self.run_case("malformed")

    def test_map_reload_callbacks_and_disposal(self):
        self.run_case("lifecycle")

    def test_large_cache_search_stays_within_guest_index_range(self):
        self.run_case("large_cache")

    def test_original_build_ignores_marker(self):
        result = subprocess.run([str(self.native_off_binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
