"""CPU execution of production rendered-mip reuse with a mock command queue.

The frontend functions and resource fields are extracted unchanged. The actual
mip planner and Xbox offset helper run; only resource creation and GPU command
submission are mocked. This proves copy freshness/order, not GPU pixel parity.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import function
from tools.test_xgpu_texture_copy import harness_prefix

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/d3d8_metal.c"

HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include "port/linux/src/metal_mip_composite.h"
#include "port/linux/src/xbox_textures.c"
#include "port/linux/src/metal_mip_composite.c"
/* RESOURCE */
static struct native_resource *resources, *sources[16];
static struct { struct { uint32_t capabilities; } reply; } transport;
static struct halo_metal_copy_subresource commands[16];
static uint32_t command_count, allocations, next_id=1000;
static int failure_status, fail_append_at=-1;
static jmp_buf failure;
static _Noreturn void native_fail(const char *operation,int status) {
    assert(operation);failure_status=status;longjmp(failure,1);
}
static void require_status(const char *operation,int status) { if(status)native_fail(operation,status); }
static void platform_log(const char *format,...) { assert(format); }
static void resource_create(struct native_resource *resource) {
    assert(resource && resource->mip_composite && resource->usage==HALO_METAL_SHADER_READ);
    assert(resource->description.levels>=1 && resource->description.levels<=16);
    resource->ref=(struct halo_metal_ref){next_id++,1};allocations++;
}
static void packet_begin(uint32_t bytes,const uint32_t *payloads,unsigned count) {
    assert(bytes==sizeof(struct halo_metal_copy_subresource) && !payloads && !count);
    if(fail_append_at>=0 && command_count==(unsigned)fail_append_at)
        native_fail("mock failed append",HALO_METAL_MEMORY);
}
static uint32_t command_append(const void *command,uint32_t bytes) {
    assert(bytes==sizeof(commands[0]) && command_count<16);
    memcpy(&commands[command_count++],command,bytes);return 0;
}
static void packet_finish(void) {}
/* PRODUCTION */
static struct xgpu_texture_description description(uint32_t width,uint32_t height,uint32_t levels) {
    struct xgpu_texture_description d={0};
    d.format=7;d.width=width;d.height=height;d.depth=1;d.levels=levels;return d;
}
static void make_sources(DWORD data,const struct xgpu_texture_description *d) {
    for(uint32_t mip=0;mip<d->levels;mip++) {
        struct native_resource *source=calloc(1,sizeof(*source));assert(source);
        source->ref=(struct halo_metal_ref){mip+1,3};
        source->data=data+xgpu_texture_level_offset(d,mip);
        source->description=description(d->width>>mip ? d->width>>mip:1,
                                       d->height>>mip ? d->height>>mip:1,1);
        source->storage_width=source->description.width;source->storage_height=source->description.height;
        source->format=HALO_METAL_BGRA8;source->usage=HALO_METAL_SHADER_READ|HALO_METAL_RENDER_TARGET;
        source->last_rendered=(UINT64_C(1)<<40)+mip+1;
        source->next=resources;resources=source;sources[mip]=source;
    }
}
static int resolve(DWORD data,const struct xgpu_texture_description *d,struct native_resource **out) {
    command_count=0;failure_status=0;*out=NULL;
    if(setjmp(failure))return failure_status;
    *out=rendered_mip_composite(data,d);return 0;
}
static void expect_copies(const struct native_resource *destination,const unsigned *mips,unsigned count) {
    assert(command_count==count);
    for(unsigned i=0;i<count;i++) {
        unsigned mip=mips[i];const struct halo_metal_copy_subresource *c=&commands[i];
        assert(c->command.opcode==HALO_METAL_COPY_SUBRESOURCE && c->planes==HALO_METAL_COLOR);
        assert(c->source.id==sources[mip]->ref.id && c->source.generation==sources[mip]->ref.generation);
        assert(c->destination.id==destination->ref.id && c->destination.generation==destination->ref.generation);
        assert(c->destination_mip==mip && !c->source_mip && !c->source_slice && !c->destination_slice);
        assert(!c->source_x && !c->source_y && !c->destination_x && !c->destination_y);
        assert(c->width==sources[mip]->storage_width && c->height==sources[mip]->storage_height);
    }
}
static void cleanup(void) {
    while(resources) {
        struct native_resource *next=resources->next;
        free(resources->mip_copy_cache);free(resources);resources=next;
    }
}
int main(int argc,char **argv) {
    assert(argc==2);transport.reply.capabilities=HALO_METAL_CAP_COPY_SUBRESOURCE;
    const DWORD data=0x00100000;
    struct xgpu_texture_description d=description(128,128,4);
    struct native_resource *composite=NULL,*again=NULL;
    const unsigned all[]={0,1,2,3},one[]={2},changed[]={0,2};
    make_sources(data,&d);
    if(!strcmp(argv[1],"reuse")) {
        assert(!resolve(data,&d,&composite));expect_copies(composite,all,4);assert(allocations==1);
        assert(!resolve(data,&d,&again) && again==composite);expect_copies(composite,NULL,0);
        for(unsigned mip=0;mip<4;mip++)sources[mip]->last_rendered+=100;
        assert(!resolve(data,&d,&again));expect_copies(composite,all,4);
        assert(!resolve(data,&d,&again));expect_copies(composite,NULL,0);assert(allocations==1);
    } else if(!strcmp(argv[1],"rewrite")) {
        assert(!resolve(data,&d,&composite));sources[2]->last_rendered++;
        assert(!resolve(data,&d,&again));expect_copies(composite,one,1);
        sources[2]->ref.generation++;
        assert(!resolve(data,&d,&again));expect_copies(composite,one,1);
        sources[2]->ref.id+=100;
        assert(!resolve(data,&d,&again));expect_copies(composite,one,1);
        struct native_resource *newer=calloc(1,sizeof(*newer));assert(newer);*newer=*sources[2];
        newer->ref.id+=100;newer->last_rendered++;newer->next=resources;resources=newer;sources[2]=newer;
        assert(!resolve(data,&d,&again));expect_copies(composite,one,1);
        assert(!resolve(data,&d,&again));expect_copies(composite,NULL,0);
    } else if(!strcmp(argv[1],"validation")) {
        assert(!resolve(data,&d,&composite));
        struct halo_metal_mip_composite_copy saved[4];memcpy(saved,composite->mip_copy_cache,sizeof(saved));
        sources[3]->usage=HALO_METAL_SHADER_READ;
        assert(resolve(data,&d,&again)==HALO_METAL_UNSUPPORTED && !command_count);
        sources[3]->usage|=HALO_METAL_RENDER_TARGET;sources[3]->storage_width++;
        assert(resolve(data,&d,&again)==HALO_METAL_UNSUPPORTED && !command_count);
        sources[3]->storage_width--;uint64_t serial=sources[3]->last_rendered;sources[3]->last_rendered=0;
        assert(resolve(data,&d,&again)==HALO_METAL_UNDEFINED_CONTENT && !command_count);
        sources[3]->last_rendered=serial;
        struct native_resource *newer=calloc(1,sizeof(*newer));assert(newer);*newer=*sources[1];
        newer->ref.id+=100;newer->last_rendered++;newer->description.width++;
        newer->next=resources;resources=newer;
        assert(resolve(data,&d,&again)==HALO_METAL_UNSUPPORTED && !command_count);
        newer->description.width--;newer->last_rendered=sources[1]->last_rendered;
        assert(resolve(data,&d,&again)==HALO_METAL_INVALID && !command_count);
        newer->usage=HALO_METAL_SHADER_READ;
        assert(!memcmp(saved,composite->mip_copy_cache,sizeof(saved)));
        assert(!resolve(data,&d,&again));expect_copies(composite,NULL,0);assert(allocations==1);
    } else if(!strcmp(argv[1],"partial")) {
        assert(!resolve(data,&d,&composite));
        struct halo_metal_mip_composite_copy saved[4];memcpy(saved,composite->mip_copy_cache,sizeof(saved));
        sources[0]->last_rendered++;sources[2]->last_rendered++;fail_append_at=1;
        assert(resolve(data,&d,&again)==HALO_METAL_MEMORY && command_count==1);
        assert(!memcmp(saved,composite->mip_copy_cache,sizeof(saved)));
        fail_append_at=-1;assert(!resolve(data,&d,&again));expect_copies(composite,changed,2);
        assert(!resolve(data,&d,&again));expect_copies(composite,NULL,0);
    } else if(!strcmp(argv[1],"cold-partial")) {
        fail_append_at=2;assert(resolve(data,&d,&again)==HALO_METAL_MEMORY && command_count==2);
        assert(allocations==1 && resources->mip_composite);
        for(unsigned mip=0;mip<4;mip++)assert(!resources->mip_copy_cache[mip].source.id);
        fail_append_at=-1;assert(!resolve(data,&d,&composite));expect_copies(composite,all,4);
        assert(!resolve(data,&d,&again));expect_copies(composite,NULL,0);assert(allocations==1);
    } else if(!strcmp(argv[1],"counts")) {
        assert(!resolve(data,&d,&composite));d.levels=2;
        assert(!resolve(data,&d,&again));expect_copies(again,all,2);assert(again!=composite && allocations==2);
        struct native_resource *short_chain=again;
        assert(!resolve(data,&d,&again) && again==short_chain);expect_copies(again,NULL,0);
        d.levels=4;assert(!resolve(data,&d,&again) && again==composite);expect_copies(again,NULL,0);
    } else if(!strcmp(argv[1],"maximum")) {
        cleanup();d=description(32768,1,16);make_sources(data,&d);
        assert(!resolve(data,&d,&composite));unsigned mips[16];for(unsigned i=0;i<16;i++)mips[i]=i;
        expect_copies(composite,mips,16);
        assert(!resolve(data,&d,&again));expect_copies(composite,NULL,0);
        d.levels=17;assert(resolve(data,&d,&again)==HALO_METAL_UNSUPPORTED && !command_count);
        assert(allocations==1);
    } else if(!strcmp(argv[1],"signatures")) {
        struct halo_metal_mip_composite_copy a={0},b;
        a.source=(struct halo_metal_ref){9,3};a.source_content_version=(UINT64_C(1)<<48)+7;
        a.source_physical_data=data;a.width=128;a.height=64;
        memset(&b,0xa7,sizeof(b));
        b.source=a.source;b.source_content_version=a.source_content_version;b.source_physical_data=a.source_physical_data;
        b.source_mip=a.source_mip;b.source_slice=a.source_slice;b.destination_mip=a.destination_mip;
        b.destination_slice=a.destination_slice;b.width=a.width;b.height=a.height;
        assert(rendered_mip_copy_matches(&a,&b));
#define DIFFERENT(field) do { b=a;b.field++;assert(!rendered_mip_copy_matches(&a,&b)); } while(0)
        DIFFERENT(source.id);DIFFERENT(source.generation);DIFFERENT(source_content_version);
        DIFFERENT(source_physical_data);DIFFERENT(source_mip);DIFFERENT(source_slice);
        DIFFERENT(destination_mip);DIFFERENT(destination_slice);DIFFERENT(width);DIFFERENT(height);
#undef DIFFERENT
    } else abort();
    cleanup();return 0;
}
'''


class MetalMipCopyCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-metal-mip-cache-cpu-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        production = SOURCE.read_text()
        start = production.index("struct native_resource {")
        resource = production[start:production.index("};", start) + 2]
        functions = "\n".join(function(production, name) for name in
                              ("rendered_mip_copy_matches", "rendered_mip_composite"))
        path = folder / "cache.c"
        path.write_text(harness_prefix() + HARNESS.replace("/* RESOURCE */", resource)
                        .replace("/* PRODUCTION */", functions))
        cls.binary = folder / "cache"
        compiled = subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                   "-I", str(ROOT), str(path), "-o", str(cls.binary)],
                                  capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeat_bindings_skip_copies_until_next_frame_writes(self):
        self.run_case("reuse")

    def test_single_mip_rewrite_generation_and_newer_alias_copy_in_order(self):
        self.run_case("rewrite")

    def test_warm_cache_cannot_hide_missing_invalid_or_undefined_levels(self):
        self.run_case("validation")

    def test_failed_changed_chain_does_not_publish_freshness(self):
        self.run_case("partial")

    def test_failed_initial_chain_retries_every_level(self):
        self.run_case("cold-partial")

    def test_requested_level_counts_have_independent_destinations(self):
        self.run_case("counts")

    def test_maximum_levels_are_bounded_and_invalid_count_still_fails(self):
        self.run_case("maximum")

    def test_exact_signature_includes_64_bit_versions_and_ignores_padding(self):
        self.run_case("signatures")


if __name__ == "__main__":
    unittest.main()
