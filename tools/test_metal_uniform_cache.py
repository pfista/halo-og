"""Protect packet-local uniform reuse: owned bytes, never fingerprint equality."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "metal_uniform_cache.h"

int main(void) {
    struct metal_uniform_cache *cache=malloc(sizeof(*cache));
    const uint32_t vertex_size=METAL_UNIFORM_VERTEX_BYTES, pixel_size=METAL_UNIFORM_PIXEL_BYTES;
    const uint32_t first=7, pixel=first+vertex_size, second=pixel+pixel_size;
    const size_t extent=second+vertex_size;
    unsigned char *source_storage=malloc(vertex_size+1), *packet_storage=malloc(extent+1);
    assert(cache && source_storage && packet_storage);
    unsigned char *source=source_storage+1, *packet=packet_storage+1;
    for (uint32_t i=0;i<vertex_size;i++) source[i]=(unsigned char)(i*37+19);
    uint32_t zero=0, negative_zero=0x80000000u, nan=0x7fc12345u, other_nan=0x7fc12344u;
    memcpy(source+8,&zero,4); memcpy(source+12,&nan,4);
    memcpy(packet+first,source,vertex_size);
    metal_uniform_cache_reset(cache);
    uint32_t offset=UINT32_MAX;
    const uint64_t collision=UINT64_C(0x1234567890abcdef);
    assert(metal_uniform_cache_register(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,first,packet,extent));
    assert(metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
    assert(offset==first);
    /* Numerical equality/canonical NaNs must never replace bitwise equality. */
    memcpy(source+8,&negative_zero,4); offset=UINT32_MAX;
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
    assert(offset==UINT32_MAX); memcpy(source+8,&zero,4);
    memcpy(source+12,&other_nan,4);
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
    memcpy(source+12,&nan,4);
    /* Forced identical fingerprints: every differing byte still rejects reuse. */
    for (uint32_t i=0;i<vertex_size;i++) {
        source[i]^=0x80;
        assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
        source[i]^=0x80;
    }
    packet[first+vertex_size-1]^=1;
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
    packet[first+vertex_size-1]^=1;
    memcpy(packet+pixel,source,pixel_size);
    assert(metal_uniform_cache_register(cache,collision,METAL_UNIFORM_PIXEL,pixel_size,pixel,packet,extent));
    assert(metal_uniform_cache_find(cache,collision,METAL_UNIFORM_PIXEL,pixel_size,packet,extent,source,&offset));
    assert(offset==pixel);
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,pixel_size,packet,extent,source,&offset));
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_PIXEL,vertex_size,packet,extent,source,&offset));
    source[vertex_size-1]^=1; memcpy(packet+second,source,vertex_size);
    assert(metal_uniform_cache_register(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,second,packet,extent));
    assert(metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
    assert(offset==second); source[vertex_size-1]^=1;
    assert(metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,&offset));
    assert(offset==first);
    uint32_t count=cache->count; offset=UINT32_MAX;
    assert(!metal_uniform_cache_register(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,UINT32_MAX,packet,extent));
    assert(!metal_uniform_cache_register(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,first,packet,first+vertex_size-1));
    assert(cache->count==count);
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,first+vertex_size-1,source,&offset));
    assert(offset==UINT32_MAX);
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,NULL,extent,source,&offset));
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,NULL,&offset));
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,extent,source,NULL));
    assert(!metal_uniform_cache_register(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,(uint32_t)0,(void *)(UINTPTR_MAX-3),extent));
    assert(metal_uniform_hash((void *)(UINTPTR_MAX-3),8)==0);
    /* Reset excludes the previous packet, even when new storage has equal bytes. */
    metal_uniform_cache_reset(cache); free(packet_storage);
    packet_storage=malloc(vertex_size+1); assert(packet_storage); packet=packet_storage+1;
    memcpy(packet,source,vertex_size);
    assert(!metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,vertex_size,source,&offset));
    assert(metal_uniform_cache_register(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,0,packet,vertex_size));
    assert(metal_uniform_cache_find(cache,collision,METAL_UNIFORM_VERTEX,vertex_size,packet,vertex_size,source,&offset));
    assert(offset==0);
    assert(metal_uniform_hash(packet,vertex_size)==metal_uniform_hash(source,vertex_size));
    metal_uniform_cache_reset(cache);
    for (uint32_t i=0;i<METAL_UNIFORM_CACHE_ENTRIES;i++)
        assert(metal_uniform_cache_register(cache,i,METAL_UNIFORM_PIXEL,pixel_size,0,packet,vertex_size));
    assert(!metal_uniform_cache_register(cache,UINT64_MAX,METAL_UNIFORM_PIXEL,pixel_size,0,packet,vertex_size));
    assert(cache->count==METAL_UNIFORM_CACHE_ENTRIES);
    assert(metal_uniform_cache_find(cache,0,METAL_UNIFORM_PIXEL,pixel_size,packet,vertex_size,source,&offset));
    assert(metal_uniform_cache_find(cache,METAL_UNIFORM_CACHE_ENTRIES-1,METAL_UNIFORM_PIXEL,pixel_size,packet,vertex_size,source,&offset));
    /* Exact allocation ends exercise the hash's wide blocks and scalar tail. */
    for (size_t size=0;size<=65;size++) {
        unsigned char *aligned=malloc(size?size:1), *unaligned=malloc(size+1);
        assert(aligned && unaligned);
        for (size_t i=0;i<size;i++) aligned[i]=unaligned[i+1]=(unsigned char)(i*37+19);
        assert(metal_uniform_hash(aligned,size)==metal_uniform_hash(unaligned+1,size));
        free(aligned); free(unaligned);
    }
    free(source_storage); free(packet_storage); free(cache);
    return 0;
}
'''


class UniformCacheTests(unittest.TestCase):
    def test_exact_owned_packet_uniform_reuse(self):
        if not shutil.which("clang"):
            self.skipTest("clang is required")
        with tempfile.TemporaryDirectory(prefix="halo-metal-uniform-cache-") as temporary:
            directory = Path(temporary)
            source = directory / "fixture.c"
            source.write_text(FIXTURE)
            for name, flags in (("optimized", ["-O2"]),
                                ("sanitized", ["-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"])):
                with self.subTest(build=name):
                    binary = directory / name
                    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                                    "-DHALO_MACOS_NATIVE_METAL=1", "-I", ROOT / "port/linux/src", source,
                                    ROOT / "port/linux/src/metal_vertex_fetch.c", "-o", binary],
                                   check=True, capture_output=True, text=True)
                    subprocess.run([binary], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
