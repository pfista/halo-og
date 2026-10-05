"""Exercise the production pistol impact refinement against controlled loaded tags.

Compiles the real helper, initializer and tag declarations. This verifies which
effect references may change; visual size is still a playtest check.
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
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef float real;
typedef uint16_t word;
typedef uint8_t byte;
#define TAG_STRING_LENGTH 31
#define NONE (-1)
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
typedef struct { real x,y,z; } real_point3d;
struct tag_reference { int32_t group_tag; const char *name; int32_t name_length, index; };
struct tag_block { int32_t count; void *address, *definition; };
#define TAG_BLOCK_GET_ELEMENT(b,i,t) ((t *)element(b,i,sizeof(t)))
static void *element(struct tag_block *b,int32_t i,size_t size) {
    assert(b->address && i>=0 && i<b->count);
    return (byte *)b->address+i*size;
}
/* DECLARATIONS */
static struct projectile_definition projectile;
static struct projectile_material_response_definition responses[8];
static unsigned missing;
static int null_projectile;
static int32_t tag_loaded(int32_t group,const char *name) {
    if(group==PROJECTILE_DEFINITION_TAG && !strcmp(name,"weapons\\pistol\\bullet"))
        return missing&1 ? NONE : 10;
    if(group==EFFECT_DEFINITION_TAG && !strcmp(name,"weapons\\pistol\\effects\\impact metal hollow reflect"))
        return missing&4 ? NONE : 30;
    if(group==EFFECT_DEFINITION_TAG && !strcmp(name,"weapons\\pistol\\effects\\impact metal thick reflect"))
        return missing&8 ? NONE : 31;
    assert(0); return NONE;
}
static struct projectile_definition *projectile_definition_get(int32_t index) {
    assert(index==10); return null_projectile ? NULL : &projectile;
}
/* PRODUCTION */
static void reset(void) {
    missing=0;null_projectile=0;
    memset(&projectile,0,sizeof(projectile));
    memset(responses,0x55,sizeof(responses));
    projectile.projectile.material_responses=(struct tag_block){8,responses,NULL};
    responses[5].default_effect=(struct tag_reference){EFFECT_DEFINITION_TAG,"hollow",6,30};
    responses[7].default_effect=(struct tag_reference){EFFECT_DEFINITION_TAG,"thick",5,31};
}
static void changes_only_requested_fields(void) {
    reset();
    struct projectile_material_response_definition expected_responses[8];
    struct projectile_definition original_projectile=projectile;
    memcpy(expected_responses,responses,sizeof(responses));
    expected_responses[5].default_effect=expected_responses[7].default_effect;
    projectiles_initialize_for_new_map();
    assert(!memcmp(responses,expected_responses,sizeof(responses)));
    assert(!memcmp(&projectile,&original_projectile,sizeof(projectile)));
    projectiles_initialize_for_new_map(); /* Idempotent on repeated initialization. */
    assert(!memcmp(responses,expected_responses,sizeof(responses)));
}
static void preserve_authored_responses(void) {
    for(int i=0;i<5;i++) {
        reset();
        if(i==0)responses[5].default_effect.index=99;
        if(i==1)responses[7].default_effect.index=99;
        if(i==2)responses[5].default_effect.group_tag='snd!';
        if(i==3)responses[7].default_effect.group_tag='snd!';
        if(i==4)responses[5].default_effect.index=NONE;
        struct projectile_material_response_definition expected[8];
        memcpy(expected,responses,sizeof(responses));
        projectiles_initialize_for_new_map();
        assert(!memcmp(responses,expected,sizeof(responses)));
    }
}
static void incomplete_assets(void) {
    for(int i=0;i<7;i++) {
        reset();
        if(i<3)missing=i==0 ? 1 : i==1 ? 4 : 8;
        if(i==3)projectile.projectile.material_responses.count=7;
        if(i==4)projectile.projectile.material_responses.count=0;
        if(i==5)projectile.projectile.material_responses.address=NULL;
        if(i==6)null_projectile=1;
        struct projectile_material_response_definition expected[8];
        memcpy(expected,responses,sizeof(responses));
        projectiles_initialize_for_new_map();
        assert(!memcmp(responses,expected,sizeof(responses)));
    }

}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"fields"))changes_only_requested_fields();
    else if(!strcmp(argv[1],"authored"))preserve_authored_responses();
    else if(!strcmp(argv[1],"missing"))incomplete_assets();
    else assert(0);
    return 0;
}
'''


def fixture():
    declarations = []
    for path, name in [
        ("source/objects/object_definitions.h", "_object_definition"),
        ("source/items/projectile_definitions.h", "projectile_material_response_definition"),
        ("source/items/projectile_definitions.h", "_projectile_definition"),
        ("source/items/projectile_definitions.h", "projectile_definition"),
    ]:
        declarations.append(block((ROOT / path).read_text(), "struct " + name + "\n{") + ";")
    for path, signature in [
        ("source/game/game_globals.h", "enum\n{\n\tGAME_GLOBALS_TAG"),
        ("source/items/projectile_definitions.h", "enum\n{\n\tPROJECTILE_DEFINITION_TAG"),
        ("source/effects/effect_definitions.h", "enum\n{\n\tEFFECT_DEFINITION_TAG"),
    ]:
        declarations.append(block((ROOT / path).read_text(), signature) + ";")
    helper = (ROOT / "source/items/refined_tag_effects.inc").read_text()
    initializer = block((ROOT / "source/items/projectiles.c").read_text(),
                        "void projectiles_initialize_for_new_map(\n")
    source = PREFIX.replace("/* DECLARATIONS */", "\n".join(declarations))
    source = source.replace("/* PRODUCTION */", helper + "\n" + initializer)
    source = re.sub(r"\bunsigned long\b", "uint32_t", source)
    return re.sub(r"\blong\b", "int32_t", source)


class RefinedTagEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-refined-tags-")
        work = Path(cls.temporary.name)
        source = work / "fixture.c"
        source.write_text(fixture())
        cls.binary = work / "fixture"
        subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-multichar",
                        str(source), "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_only_requested_fields_and_repeated_initialization(self):
        subprocess.run([str(self.binary), "fields"], check=True)

    def test_preserves_authored_replacement_effects(self):
        subprocess.run([str(self.binary), "authored"], check=True)

    def test_missing_tags_and_short_blocks(self):
        subprocess.run([str(self.binary), "missing"], check=True)



if __name__ == "__main__":
    unittest.main()
