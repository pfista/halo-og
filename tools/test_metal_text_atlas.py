#!/usr/bin/env python3
"""Check native atlas upload snapshots and cache lifetime without a GPU.

Compile the production adapter and resource creation function with a tiny
ordered packet recorder. Real wire records and packet capacity validation are
retained; the CPU atlas provider and host submission are mocked. Glyph layout
and GPU rasterization belong to the text-core and renderer fixtures.
"""
import ctypes as C
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'port/linux/src/d3d8_metal.c'


def declaration(source, start):
    """Extract one production function/struct including its balanced body."""
    begin = source.index(start)
    opening = source.index('{', begin)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end] + (';' if source[end:end + 1] == ';' else '')


def fixture_source():
    native = NATIVE.read_text()
    description = declaration((ROOT / 'port/linux/src/xgpu.h').read_text(),
                              'struct xgpu_texture_description\n')
    resource = declaration(native, 'struct native_resource {')
    create = declaration(native, 'static void resource_create(')
    adapter = declaration(native, 'static struct native_resource *text_texture_get(')
    # The source's registration check must run before authored texture access.
    texture = declaration(native, 'static struct native_resource *texture_get(')
    if not re.search(r'^static[^\n]+\{\s*struct native_resource \*text=text_texture_get\(texture->Data\);\s*if \(text\) return text;', texture):
        raise AssertionError('Registered text must resolve before authored memory')
    return r'''
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include "halo_metal_abi.h"
#include "metal_packet_room.h"
#include "text_hires.h"
typedef uint32_t DWORD;
typedef int BOOL;
#define TRUE 1
#define D3DFMT_A8R8G8B8 6
''' + description + '\n' + resource + r'''
static struct native_resource *resources, *text_atlas_resource;
static uint32_t next_resource_id=1;
static struct { uint32_t capacity; } transport;
static struct text_hires_atlas_pixels provided;
static unsigned long placeholder;
static int enabled, failed;
static jmp_buf failure;
struct event { uint32_t opcode,resource,width,height,format,levels,usage,y;
    uint32_t row,size,plane; unsigned char *pixels; };
static struct event events[256];
static uint32_t event_count, pending_size;
static unsigned char pending[256];
float halo_screen_pixel_scale(void) { return 3.0f; }
static void platform_log(const char *format,...) { (void)format; }
int text_hires_atlas_pixels_since(unsigned long data,uint64_t uploaded,struct text_hires_atlas_pixels *out) {
    if (!enabled || data!=placeholder) return 0;
    *out=provided;
    if (uploaded==provided.revision) { out->dirty_top=provided.height;out->dirty_bottom=0; }
    return 1;
}
static void native_fail(const char *where,int status) {
    (void)where; failed=status; longjmp(failure,1);
}
static void require_status(const char *where,int status) {
    if (status) native_fail(where,status);
}
static void packet_begin(uint32_t fixed,const uint32_t *sizes,uint32_t count) {
    uint32_t end;
    require_status("fixture packet",halo_metal_packet_room(sizeof(struct halo_metal_packet),
        transport.capacity,fixed,sizes,count,&end));
    if (fixed>sizeof(pending) || event_count>=256) native_fail("fixture record",HALO_METAL_MEMORY);
    pending_size=fixed;
}
static uint32_t command_append(const void *command,uint32_t bytes) {
    if (bytes!=pending_size) native_fail("fixture command",HALO_METAL_INVALID);
    memcpy(pending,command,bytes); return sizeof(struct halo_metal_packet);
}
static void payload_append(uint32_t command,uint32_t field,const void *pixels,uint32_t bytes) {
    (void)command;(void)field;
    events[event_count].pixels=malloc(bytes);
    if (!events[event_count].pixels) native_fail("fixture pixels",HALO_METAL_MEMORY);
    memcpy(events[event_count].pixels,pixels,bytes);
}
static void packet_finish(void) {
    const struct halo_metal_command *command=(const void *)pending;
    struct event *event=&events[event_count++];event->opcode=command->opcode;
    if (command->opcode==HALO_METAL_CREATE_TEXTURE_EX) {
        const struct halo_metal_create_ex *c=(const void *)pending;
        event->resource=c->resource.id;event->width=c->width;event->height=c->height;
        event->format=c->format;event->levels=c->mip_levels;event->usage=c->usage;
    } else if (command->opcode==HALO_METAL_UPLOAD_EX) {
        const struct halo_metal_upload_ex *u=(const void *)pending;
        event->resource=u->resource.id;event->width=u->width;event->height=u->height;
        event->row=u->bytes_per_row;event->size=u->data_size;event->plane=u->plane;event->y=u->y;
    } else native_fail("fixture opcode",HALO_METAL_INVALID);
}
''' + create + '\n' + adapter + r'''
void fixture_reset(void) {
    for (uint32_t i=0;i<event_count;i++) free(events[i].pixels);
    memset(events,0,sizeof(events));event_count=0;
    while (resources) { struct native_resource *next=resources->next;free(resources);resources=next; }
    text_atlas_resource=NULL;next_resource_id=1;failed=0;enabled=0;
    memset(&provided,0,sizeof(provided));placeholder=0x1000;transport.capacity=HALO_METAL_MAX_PACKET;
}
void fixture_atlas(unsigned char *pixels,unsigned long width,unsigned long height,uint64_t revision,int active) {
    provided=(struct text_hires_atlas_pixels){.rgba=pixels,.width=width,.height=height,
        .revision=revision,.dirty_top=0,.dirty_bottom=height};enabled=active;
}
void fixture_dirty(unsigned long top,unsigned long bottom) { provided.dirty_top=top;provided.dirty_bottom=bottom; }
void fixture_capacity(uint32_t capacity) { transport.capacity=capacity; }
uint32_t fixture_resolve(unsigned long data) {
    failed=0;
    if (setjmp(failure)) return 0;
    struct native_resource *entry=text_texture_get(data);
    return entry ? entry->ref.id:0;
}
int fixture_failure(void) { return failed; }
uint32_t fixture_events(void) { return event_count; }
uint32_t fixture_field(uint32_t index,uint32_t field) {
    const struct event *e=&events[index];
    const uint32_t values[]={e->opcode,e->resource,e->width,e->height,e->format,e->levels,e->usage,e->row,e->size,e->plane,e->y};
    return field<11 ? values[field]:0;
}
unsigned char fixture_pixel(uint32_t index,uint32_t offset) { return events[index].pixels[offset]; }
uint32_t fixture_metadata(void) {
    const struct native_resource *e=text_atlas_resource;
    return e ? (e->text_atlas | e->description.hires<<1 | e->description.hires_coverage<<2 |
                e->description.linear<<3 | (e->hud_asset==-1)<<4 | (e->data==0)<<5):0;
}
uint32_t fixture_resources(void) {
    uint32_t count=0;for (struct native_resource *e=resources;e;e=e->next) count++;return count;
}
void fixture_draw(uint32_t resource) {
    struct event *event=&events[event_count++];event->opcode=HALO_METAL_DRAW;event->resource=resource;
}
'''


class MetalTextAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('clang'):
            raise unittest.SkipTest('clang required')
        cls.directory = tempfile.TemporaryDirectory(prefix='halo-metal-text-')
        folder = Path(cls.directory.name)
        source = folder / 'fixture.c'
        source.write_text(fixture_source())
        library = folder / ('fixture.dll' if sys.platform == 'win32' else 'fixture.dylib')
        command = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                   '-shared', '-DHALO_MACOS_NATIVE_METAL=1']
        if sys.platform == 'win32':
            # MSVC-target Clang rejects -fPIC and DLL functions are private
            # unless exported. Match the existing portable ctypes fixtures.
            command += ['-Wl,/EXPORT:' + name for name in (
                'fixture_reset', 'fixture_atlas', 'fixture_dirty', 'fixture_capacity',
                'fixture_resolve', 'fixture_failure', 'fixture_events', 'fixture_field',
                'fixture_pixel', 'fixture_metadata', 'fixture_resources', 'fixture_draw')]
        else:
            command += ['-fPIC']
        command += ['-I', str(ROOT / 'port/linux/src'), '-I', str(ROOT / 'port/macos/include'),
                    str(source), str(ROOT / 'port/linux/src/metal_packet_room.c'), '-o', str(library)]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.library = C.CDLL(str(library))
        cls.library.fixture_atlas.argtypes = [C.POINTER(C.c_ubyte), C.c_ulong, C.c_ulong, C.c_uint64, C.c_int]
        cls.library.fixture_resolve.argtypes = [C.c_ulong]
        cls.library.fixture_resolve.restype = C.c_uint32
        cls.library.fixture_field.argtypes = [C.c_uint32, C.c_uint32]
        cls.library.fixture_field.restype = C.c_uint32
        cls.library.fixture_pixel.argtypes = [C.c_uint32, C.c_uint32]
        cls.library.fixture_pixel.restype = C.c_ubyte
        cls.library.fixture_dirty.argtypes = [C.c_ulong, C.c_ulong]

    @classmethod
    def tearDownClass(cls):
        cls.library.fixture_reset()
        cls.directory.cleanup()

    def setUp(self):
        self.library.fixture_reset()
        self.pixels = (C.c_ubyte * 16)(255, 255, 255, 0, 255, 255, 255, 64,
                                     255, 255, 255, 192, 255, 255, 255, 255)

    def atlas(self, revision=1, width=2, height=2, enabled=True):
        self.library.fixture_atlas(self.pixels, width, height, revision, enabled)

    def field(self, event, field):
        return self.library.fixture_field(event, field)

    def snapshot(self, event):
        return bytes(self.library.fixture_pixel(event, i) for i in range(self.field(event, 8)))

    def test_original_and_other_textures_issue_no_replacement_commands(self):
        self.atlas(enabled=False)
        self.assertEqual(self.library.fixture_resolve(0x1000), 0)
        self.atlas()
        self.assertEqual(self.library.fixture_resolve(0x2000), 0)
        self.assertEqual(self.library.fixture_events(), 0)
        self.assertEqual(self.library.fixture_resources(), 0)

    def test_glyph_coverage_stays_rgba_alpha_in_one_linear_mip(self):
        self.atlas()
        self.assertEqual(self.library.fixture_resolve(0x1000), 1)
        self.assertEqual([self.field(0, i) for i in range(7)], [10, 1, 2, 2, 1, 1, 1])
        self.assertEqual([self.field(1, i) for i in (0, 1, 2, 3, 7, 8, 9)], [11, 1, 2, 2, 8, 16, 1])
        self.assertEqual(self.snapshot(1), bytes(self.pixels))
        # hires + text identity, ordinary alpha, no authored guest address.
        self.assertEqual(self.library.fixture_metadata(), 0b110011)

    def test_cached_revision_uploads_zero_bytes_then_reset_is_ordered(self):
        revision = (1 << 40) + 1
        self.atlas(revision)
        ref = self.library.fixture_resolve(0x1000)
        self.library.fixture_draw(ref)
        old = bytes(self.pixels)
        self.assertEqual(self.library.fixture_resolve(0x1000), ref)
        self.assertEqual(self.library.fixture_events(), 3)
        # Simulate new ink and a whole-atlas reset within this same frame.
        self.pixels[7] = 0
        self.atlas(revision + 1)
        self.assertEqual(self.library.fixture_resolve(0x1000), ref)
        self.library.fixture_draw(ref)
        self.pixels[15] = 0
        self.assertEqual([self.field(i, 0) for i in range(5)], [10, 11, 9, 11, 9])
        self.assertEqual(self.snapshot(1), old)
        self.assertEqual(self.snapshot(3)[7], 0)
        self.assertEqual(self.snapshot(3)[15], 255)
        self.assertEqual(self.library.fixture_resources(), 1)

    def test_changed_atlas_size_keeps_previous_draw_resource_valid(self):
        self.atlas()
        old = self.library.fixture_resolve(0x1000)
        self.library.fixture_draw(old)
        self.atlas(2, width=4, height=1)
        new = self.library.fixture_resolve(0x1000)
        self.assertNotEqual(old, new)
        self.assertEqual(self.library.fixture_resources(), 2)
        self.assertEqual(self.field(2, 1), old)
        self.assertEqual([self.field(3, i) for i in (1, 2, 3)], [new, 4, 1])
        self.assertEqual(self.snapshot(1), bytes(self.pixels))

    def test_dirty_rows_preserve_stride_and_copy_only_changed_ink(self):
        self.atlas()
        ref = self.library.fixture_resolve(0x1000)
        self.library.fixture_draw(ref)
        self.pixels[11] = 128
        self.atlas(2)
        self.library.fixture_dirty(1, 2)
        self.assertEqual(self.library.fixture_resolve(0x1000), ref)
        self.assertEqual([self.field(3, i) for i in (0, 2, 3, 7, 8, 10)], [11, 2, 1, 8, 8, 1])
        self.assertEqual(self.snapshot(3), bytes(self.pixels[8:16]))
        self.assertEqual(self.snapshot(1)[11], 192)
        self.assertEqual(self.library.fixture_resources(), 1)

    def test_full_size_atlas_updates_one_glyph_row_without_full_copy(self):
        pixels = (C.c_ubyte * (2048 * 2048 * 4))()
        self.library.fixture_atlas(pixels, 2048, 2048, 1, True)
        ref = self.library.fixture_resolve(0x1000)
        self.assertEqual(self.field(1, 8), 16 * 1024 * 1024)
        # A new line of glyphs is 32 physical rows. Its immutable update
        # remains valid even when the packet cannot hold another full image.
        self.library.fixture_capacity(1024 * 1024)
        self.library.fixture_atlas(pixels, 2048, 2048, 2, True)
        self.library.fixture_dirty(64, 96)
        self.assertEqual(self.library.fixture_resolve(0x1000), ref)
        self.assertEqual(self.library.fixture_failure(), 0)
        self.assertEqual([self.field(2, i) for i in (3, 7, 8, 10)], [32, 8192, 262144, 64])
        self.assertEqual(self.library.fixture_resources(), 1)

    def test_invalid_metadata_and_packet_limits_fail_before_allocation(self):
        for width, height, revision in ((0, 2, 1), (2, 0, 1), (8193, 2, 1), (2, 8193, 1), (2, 2, 0)):
            with self.subTest(width=width, height=height, revision=revision):
                self.atlas(revision, width, height)
                self.assertEqual(self.library.fixture_resolve(0x1000), 0)
                self.assertEqual(self.library.fixture_failure(), -1)
                self.assertEqual(self.library.fixture_events(), 0)
        self.library.fixture_atlas(None, 2, 2, 1, True)
        self.assertEqual(self.library.fixture_resolve(0x1000), 0)
        self.assertEqual(self.library.fixture_failure(), -1)
        self.atlas(width=2048, height=2048)
        self.library.fixture_capacity(1024 * 1024)
        self.assertEqual(self.library.fixture_resolve(0x1000), 0)
        self.assertEqual(self.library.fixture_failure(), -4)
        self.assertEqual(self.library.fixture_events(), 0)
        self.assertEqual(self.library.fixture_resources(), 0)


if __name__ == '__main__':
    unittest.main()
