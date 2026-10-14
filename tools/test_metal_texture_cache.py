"""Execute production resource/texture fast paths with a mock native queue.

Actual Xbox mip conversion and target scaling run. The named regressions are
same-frame texture/palette rewrites, hash collisions, newest rendered aliases,
target metadata/backing changes, and retired resource pointers. No GPU runs.
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
#include <stdio.h>
#include "port/linux/src/metal_mip_composite.h"
#include "port/linux/src/metal_render_scale.h"
#include "port/linux/src/metal_render_scale.c"
#include "port/linux/src/xbox_textures.c"
#define D3DFMT_P8 0x0b
enum { D3DRS_PSTEXTUREMODES=0,D3DTSS_ADDRESSU=0,D3DTSS_ADDRESSV,D3DTSS_ADDRESSW,
       D3DTSS_BORDERCOLOR,D3DTSS_MINFILTER,D3DTSS_MAGFILTER,D3DTSS_MIPFILTER,D3DTSS_MAXANISOTROPY };
typedef struct { DWORD Common,Data,Lock,Format,Size; } D3DSurface;
typedef D3DSurface D3DBaseTexture;
typedef D3DSurface D3DPalette;
/* RESOURCE */
static struct native_resource *resources, *history_sample_override;
static struct { D3DSurface history_buffer; } device;
static struct { uint32_t capacity; struct { uint32_t capabilities; } reply; } transport;
static BOOL texture_cache_enabled,draw_diagnostics=TRUE;
/* CACHE GLOBALS */
static unsigned char guest[0x20000], uploaded[0x20000];
static struct halo_metal_upload_ex pending_upload;
static uint32_t next_id=1,creates,uploads,initialized_targets,composites;
static unsigned long generation=1,generation_reads,protects;
static uint32_t logical_width=640,render_height=480,native_storage_width,native_storage_height;
static uint32_t D3D__RenderState[144],D3D__TextureState[4][32];
#define PLATFORM_PHYSICAL_TO_VIRTUAL(data) ((void *)(guest+(data)))
static _Noreturn void native_fail(const char *message,int status) {
    fprintf(stderr,"%s: %d\n",message,status);abort();
}
static void require_status(const char *message,int status) { if(status)native_fail(message,status); }
static void platform_log(const char *format,...) { assert(format); }
static const char *config_string(const char *key) { assert(!strcmp(key,"debug.texture_dump_directory"));return ""; }
static void physical_span(DWORD data,unsigned long bytes) {
    assert(data && data<=sizeof(guest) && bytes<=sizeof(guest)-data);
}
static unsigned long memory_watch_generation(unsigned long address,unsigned long bytes) {
    assert(address>=(unsigned long)guest && bytes<=sizeof(guest));generation_reads++;return generation;
}
static void memory_watch_protect(unsigned long address,unsigned long bytes) {
    assert(address>=(unsigned long)guest && bytes<=sizeof(guest));protects++;
}
static long halo_screen_width(void) { return logical_width; }
static uint32_t native_render_height(void) { return render_height; }
static void surface_dimensions(const D3DSurface *surface,unsigned long *width,unsigned long *height,BOOL *depth) {
    struct xgpu_texture_description d;xgpu_texture_describe(surface->Format,surface->Size,&d);
    *width=d.width;*height=d.height;*depth=d.format==0x2a || d.format==0x2e;
}
static void resource_create(struct native_resource *entry) { entry->ref=(struct halo_metal_ref){next_id++,1};creates++; }
static void target_storage_initialize(struct native_resource *entry) { assert(entry);initialized_targets++; }
static void packet_begin(uint32_t bytes,const uint32_t *payloads,unsigned count) {
    assert(bytes==sizeof(pending_upload) && count==1 && payloads && payloads[0]<=sizeof(uploaded));
}
static uint32_t command_append(const void *data,uint32_t bytes) {
    assert(bytes==sizeof(pending_upload));memcpy(&pending_upload,data,bytes);return 0;
}
static void payload_append(uint32_t command,uint32_t field,const void *data,uint32_t bytes) {
    assert(!command && field==offsetof(struct halo_metal_upload_ex,data_offset));
    assert(bytes==pending_upload.data_size && bytes<=sizeof(uploaded));memcpy(uploaded,data,bytes);uploads++;
}
static void packet_finish(void) {}
static struct native_resource *text_texture_get(DWORD data) { (void)data;return NULL; }
static long hud_hires_override_find(unsigned long address,unsigned long width,unsigned long height,unsigned long bytes) {
    assert(address && width && height && bytes);return -1;
}
static struct native_resource *hud_texture_get(long asset) { (void)asset;return NULL; }
static struct native_resource composite_result;
static struct native_resource *rendered_mip_composite(DWORD data,const struct xgpu_texture_description *d) {
    assert(data && d->levels>1);composites++;return &composite_result;
}
/* PRODUCTION */
static DWORD format(unsigned fmt,unsigned width_log2,unsigned height_log2,unsigned levels) {
    return (2u<<4)|(fmt<<8)|(levels<<16)|(width_log2<<20)|(height_log2<<24);
}
static struct native_resource *make_resource(DWORD data,DWORD fmt,DWORD size,uint32_t usage) {
    struct native_resource *entry=calloc(1,sizeof(*entry));assert(entry);
    entry->data=data;entry->format_word=fmt;entry->size_word=size;entry->usage=usage;
    entry->format=HALO_METAL_BGRA8;xgpu_texture_describe(fmt,size,&entry->description);
    entry->storage_width=entry->description.width;entry->storage_height=entry->description.height;
    entry->scale_mode=HALO_METAL_RENDER_SCALE_UNIFORM;resource_create(entry);resource_insert(entry);return entry;
}
static void cleanup(void) {
    while(resources) { struct native_resource *entry=resources;resource_cache_remove(entry);resources=entry->next;free(entry); }
    resource_cache_reset();
}
int main(int argc,char **argv) {
    assert(argc==3);texture_cache_enabled=!strcmp(argv[2],"on");
    transport.capacity=HALO_METAL_MAX_PACKET;transport.reply.capabilities=HALO_METAL_CAP_VOLUME;
    resource_cache_reset();
    D3DBaseTexture texture={0,0x1000,0,format(7,2,2,1),0};
    D3DPalette palette={0,0x2000,0,0,0};
    if(!strcmp(argv[1],"freshness")) {
        memset(guest+texture.Data,0x11,64);
        struct native_resource *entry=texture_get(&texture,NULL,0);
        assert(uploads==1 && uploaded[0]==0x11);
        unsigned long reads=generation_reads,plans=texture_cache_statistics.layout_plans;
        assert(texture_get(&texture,NULL,0)==entry && uploads==1 && generation_reads>reads);
        assert(texture_cache_statistics.layout_plans==plans+(texture_cache_enabled?0:1));
        memset(guest+texture.Data,0x22,64);generation++;
        assert(texture_get(&texture,NULL,0)==entry && uploads==2 && uploaded[0]==0x22);
        generation++;assert(texture_get(&texture,NULL,0)==entry && uploads==3);
        texture.Format=format(0x0b,2,2,1);memset(guest+texture.Data,3,16);
        D3DCOLOR *colors=(D3DCOLOR *)(void *)(guest+palette.Data);colors[3]=UINT32_C(0xff123456);
        struct native_resource *indexed=texture_get(&texture,&palette,0);
        assert(indexed!=entry && uploads==4 && uploaded[0]==0x56 && uploaded[1]==0x34 && uploaded[2]==0x12);
        colors[3]=UINT32_C(0xffabcdef);
        assert(texture_get(&texture,&palette,0)==indexed && uploads==5 && uploaded[0]==0xef);
        assert(protects>=5);
    } else if(!strcmp(argv[1],"collision-alias")) {
        struct native_resource *authored=texture_get(&texture,NULL,0);assert(uploads==1);
        DWORD collision=texture.Data+1;
        while(resource_cache_bucket(collision)!=resource_cache_bucket(texture.Data))collision++;
        struct native_resource *other=make_resource(collision,texture.Format,0,HALO_METAL_SHADER_READ);
        assert(texture_get(&texture,NULL,0)==authored && other!=authored && uploads==1);
        struct native_resource *older=make_resource(texture.Data,texture.Format,0,HALO_METAL_RENDER_TARGET);
        older->last_rendered=10;
        struct native_resource *newer=make_resource(texture.Data,texture.Format,0,HALO_METAL_RENDER_TARGET);
        newer->last_rendered=10;
        assert(rendered_alias(texture.Data)==newer);
        resource_cache_reset();assert(rendered_alias(texture.Data)==newer);
        older->last_rendered=11;assert(rendered_alias(texture.Data)==older);
        assert(texture_get(&texture,NULL,0)==older && uploads==1);
        texture.Format=format(7,2,2,2);
        assert(texture_get(&texture,NULL,0)==&composite_result && composites==1 && uploads==1);
        resource_cache_remove(newer);assert(resources==newer);resources=newer->next;free(newer);
        assert(rendered_alias(texture.Data)==older);
    } else if(!strcmp(argv[1],"target")) {
        DWORD size=639u|(479u<<12)|(39u<<24);
        D3DSurface surface={0,0x3000,0,format(0x12,0,0,1),size};
        struct native_resource *first=target_get(&surface);unsigned allocations=creates;
        assert(target_get(&surface)==first && creates==allocations);
        assert(texture_cache_statistics.target_hits==(texture_cache_enabled?1u:0u));
        render_height=720;
        struct native_resource *larger=target_get(&surface);assert(larger!=first && larger->storage_width==960);
        render_height=480;assert(target_get(&surface)==first);
        first->storage_width=641;
        struct native_resource *replacement=target_get(&surface);assert(replacement!=first && replacement->storage_width==640);
        surface.Size=319u|(479u<<12)|(39u<<24);assert(target_get(&surface)!=replacement);
        surface.Size=size;render_height=0;native_storage_width=1280;native_storage_height=960;
        struct native_resource *native=target_get(&surface);assert(native->storage_width==1280);
        native_storage_width=1920;native_storage_height=1440;assert(target_get(&surface)!=native);
        render_height=480;assert(target_get(&surface)==replacement);
        resource_cache_remove(replacement);
        struct native_resource **link=&resources;while(*link!=replacement)link=&(*link)->next;
        *link=replacement->next;free(replacement);
        struct native_resource *after=target_get(&surface);assert(after->storage_width==640 && initialized_targets);
    } else if(!strcmp(argv[1],"reset-hud")) {
        struct native_resource *one=make_resource(0,texture.Format,0,HALO_METAL_SHADER_READ);
        one->description.hires=TRUE;one->hud_asset=7;
        struct native_resource *two=make_resource(0,texture.Format,0,HALO_METAL_SHADER_READ);
        two->description.hires=TRUE;two->hud_asset=7;
        resource_cache_reset();resource_cache_rebuild();
        assert(hud_resource_buckets[hud_resource_bucket(7)]==two && two->hud_cache_next==one);
        resource_cache_remove(two);assert(resources==two);resources=two->next;free(two);
        assert(hud_resource_buckets[hud_resource_bucket(7)]==one);
        resource_cache_reset();assert(!resource_index_ready);
        if(texture_cache_enabled)assert(resource_lookup_first(0)==one);
    } else abort();
    cleanup();return 0;
}
'''


class MetalTextureCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-metal-texture-cache-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        production = SOURCE.read_text()
        start = production.index("struct native_resource {")
        resource = production[start:production.index("};", start) + 2]
        start = production.index("#define NATIVE_RESOURCE_BUCKETS")
        globals_text = production[start:production.index("/* Keep the last completed", start)]
        names = ("resource_cache_bucket", "hud_resource_bucket", "resource_cache_reset",
                 "resource_cache_rebuild", "resource_insert", "resource_cache_remove",
                 "resource_lookup_first", "resource_lookup_next", "target_cache_bucket",
                 "target_cache_find", "target_cache_store", "texture_format", "target_get",
                 "rendered_alias", "palette_hash", "texture_get")
        functions = "\n".join(function(production[production.index("static void resource_cache_reset(void) {"):]
                                       if name == "resource_cache_reset" else production, name)
                              for name in names)
        # The production room helper is independent of GPU command submission.
        code = harness_prefix() + '#include "port/linux/src/metal_packet_room.c"\n' + HARNESS
        code = code.replace("/* RESOURCE */", resource).replace("/* CACHE GLOBALS */", globals_text)
        code = code.replace("/* PRODUCTION */", functions)
        path = folder / "cache.c"
        path.write_text(code)
        cls.binary = folder / "cache"
        result = subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-Wno-format",
                                 "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                 "-I", str(ROOT), str(path), "-o", str(cls.binary)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        for enabled in ("off", "on"):
            with self.subTest(cache=enabled):
                result = subprocess.run([str(self.binary), name, enabled], capture_output=True,
                                        text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_same_frame_pixel_and_palette_mutations_still_upload(self):
        self.run_case("freshness")

    def test_hash_collision_and_newest_rendered_alias_keep_exact_lookup(self):
        self.run_case("collision-alias")

    def test_target_resize_backing_changes_and_retirement_invalidate_memo(self):
        self.run_case("target")

    def test_reset_rebuild_preserves_hud_order_and_removes_retired_nodes(self):
        self.run_case("reset-hud")


if __name__ == "__main__":
    unittest.main()
