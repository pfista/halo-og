"""CPU regression for selecting the exact retained Metal shader program.

Execute the production lookup helpers. A forced full-hash collision must never
select a different shader identity; real bucket collisions preserve references
and the existing lifetime list. No shader compiler or GPU runs.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import function

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/d3d8_metal.c"

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "port/linux/src/xgpu_shader_standalone.h"
#include "port/macos/include/halo_metal_abi.h"
struct vertex_shader_object { uint32_t id; };
/* PROGRAM */
static struct native_program *programs;
/* CACHE GLOBALS */
/* PRODUCTION */
static struct native_program *find(const struct native_program *entry) {
    return program_cache_find(entry->vertex,entry->packed_mask,&entry->key,entry->alpha_border_mask,
        entry->volume_border_mask,entry->depth_contract,entry->compact_vertices);
}
int main(int argc,char **argv) {
    assert(argc==2);
    struct vertex_shader_object vertices[2]={{1},{2}};
    struct native_program original={0};
    original.vertex=&vertices[0];original.ref=(struct halo_metal_ref){17,3};
    original.packed_mask=14;original.compact_vertices=1;
    original.key.texture_modes=0x421;original.key.sampler_type[0]=1;
    program_cache_insert(&original);
    assert(find(&original)==&original && last_program==&original);
    if (!strcmp(argv[1],"identity-collision")) {
        /* Each mismatch is placed ahead of the true entry with the same hash,
           representing a hash collision independently of the hash algorithm. */
        for (size_t i=0;i<7+sizeof(original.key);i++) {
            struct native_program collision=original;
            collision.ref=(struct halo_metal_ref){99,1};
            switch (i) {
                case 0: collision.vertex=&vertices[1];break;
                case 1: collision.packed_mask^=1;break;
                case 2: collision.alpha_border_mask^=1;break;
                case 3: collision.volume_border_mask^=1;break;
                case 4: collision.depth_contract^=1;break;
                case 5: collision.compact_vertices^=1;break;
                case 6: collision.packed_mask^=0x80000000u;break;
                default: ((unsigned char *)&collision.key)[i-7]^=1;break;
            }
            collision.cache_next=&original;
            program_buckets[original.cache_hash&(NATIVE_PROGRAM_BUCKETS-1)]=&collision;
            last_program=&collision;
            assert(find(&original)==&original);
            assert(last_program==&original);
            /* A miss cannot return the just-used entry merely because its
               vertex object matches. */
            assert(find(&collision)==NULL);
            program_buckets[original.cache_hash&(NATIVE_PROGRAM_BUCKETS-1)]=&original;
        }
        assert(programs==&original && original.next==NULL);
    } else {
        assert(!strcmp(argv[1],"bucket-lifetime"));
        struct native_program other=original;
        other.ref=(struct halo_metal_ref){23,7};
        uint32_t hash=0;
        for (uint32_t i=1;i<1000000;i++) {
            other.key.combiner_state[0]=i;
            hash=program_hash(other.vertex,other.packed_mask,&other.key,other.alpha_border_mask,
                other.volume_border_mask,other.depth_contract,other.compact_vertices);
            if (hash!=original.cache_hash &&
                (hash&(NATIVE_PROGRAM_BUCKETS-1))==(original.cache_hash&(NATIVE_PROGRAM_BUCKETS-1))) break;
        }
        assert(hash!=original.cache_hash &&
            (hash&(NATIVE_PROGRAM_BUCKETS-1))==(original.cache_hash&(NATIVE_PROGRAM_BUCKETS-1)));
        assert(find(&other)==NULL);
        program_cache_insert(&other);
        for (unsigned i=0;i<20;i++) {
            assert(find(&original)==&original);
            assert(find(&other)==&other);
            assert(find(&other)==&other);
        }
        assert(original.ref.id==17 && original.ref.generation==3);
        assert(other.ref.id==23 && other.ref.generation==7);
        assert(programs==&other && other.next==&original && original.next==NULL);
    }
    return 0;
}
'''


class ProgramCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="metal-program-cache-")
        source = SOURCE.read_text()
        start = source.index("struct native_program {")
        program = source[start:source.index("};", start) + 2]
        start = source.index("#define NATIVE_PROGRAM_BUCKETS")
        globals_text = source[start:source.index("#define NATIVE_GEOMETRY_SLOTS", start)]
        functions = "\n".join(function(source, name) for name in
                              ("program_matches", "program_hash", "program_cache_find", "program_cache_insert"))
        code = HARNESS.replace("/* PROGRAM */", program).replace("/* CACHE GLOBALS */", globals_text)
        code = code.replace("/* PRODUCTION */", functions)
        folder = Path(cls.temp.name)
        path = folder / "program.c"
        path.write_text(code)
        cls.binary = folder / "program"
        result = subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                 "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                 "-I", str(ROOT), str(path), "-o", str(cls.binary)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_hash_collision_checks_every_identity_field(self):
        self.run_case("identity-collision")

    def test_bucket_collision_keeps_resource_identity_and_lifetime_order(self):
        self.run_case("bucket-lifetime")


if __name__ == "__main__":
    unittest.main()
