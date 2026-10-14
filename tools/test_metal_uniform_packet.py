"""CPU production frontend grouping protects packet-local typed uniform refs.

Real packet helpers and transport run; the host mock checks bounded command
extents and the uniform wire contract, then acknowledges the exact sequence.
Resource/GPU semantics and ILP32 host imports belong to the GPU/guest fixtures.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import function

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#define HALO_MACOS_NATIVE_METAL 1
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "metal_guest_transport.h"
#include "metal_packet_room.h"
#include "metal_draw_state.h"
#include "metal_uniform_cache.h"
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define NATIVE_BATCH_SOFT_BYTES (16u*1024u*1024u)
/* DECLARATIONS */
static struct halo_metal_guest_transport transport;
static struct metal_uniform_cache uniform_cache;
static BOOL packet_group_active,draw_diagnostics=TRUE,uniform_cache_enabled=TRUE;
static struct { unsigned long frame; } device;
static uint32_t packet_expected_end,largest_statistics_batch;
static uint64_t sequence,submitted_batches,submitted_commands,submitted_bytes,submit_wall_ns;
static struct native_flush_statistics flush_statistics[NATIVE_FLUSH_REASON_COUNT];
static struct native_draw_profile draw_profile;
static uint64_t monotonic_ns(void) { static uint64_t now;return ++now; }
static int config_boolean(const char *key) { (void)key;return 0; }
static void platform_log(const char *format,...) { (void)format; }
static void native_failed_packet(void) { fprintf(stderr,"transport failed: %s\n",transport.error); }
static _Noreturn void native_fail(const char *operation,int status) {
    fprintf(stderr,"%s: %d (%s)\n",operation,status,transport.error ? transport.error:"no transport error");abort();
}
static void require_status(const char *operation,int status) { if(status)native_fail(operation,status); }
/* TRANSPORT */
/* FRONTEND */
/* The exact production draw-side decision retains a legacy draw when optional
   definition records would exceed the hard packet limit. */
static BOOL sharing_selected(const uint32_t draw_payloads[4]) {
    uint32_t draw_end;
    return /* SELECTION */;
}
struct expected_uniforms { unsigned char vertex[3120],pixel[608]; };
static struct expected_uniforms expected[8192];
static uint32_t expected_count,consumed,host_packets,host_definitions,host_draws,host_max_commands;
static uint32_t minimum_packet_size=UINT32_MAX,maximum_packet_size;
static void expect_draw(const struct metal_draw_state_output *output) {
    assert(expected_count<8192);
    memcpy(expected[expected_count].vertex,&output->vertex,sizeof(output->vertex));
    memcpy(expected[expected_count++].pixel,&output->pixel,sizeof(output->pixel));
}
static void inspect_packet(void) {
    const unsigned char *bytes=transport.bytes;
    struct halo_metal_packet header;memcpy(&header,bytes,sizeof(header));
    assert(header.magic==HALO_METAL_MAGIC && header.abi_version==HALO_METAL_ABI_VERSION);
    assert(header.byte_size==transport.size && header.byte_size<=HALO_METAL_MAX_PACKET);
    assert(header.command_count && header.command_count<=65536);
    struct { uint32_t kind,offset,size; } definitions[65536];uint32_t definition_count=0;
    uint32_t cursor=sizeof(header);
    for(uint32_t i=0;i<header.command_count;i++) {
        struct halo_metal_command command;
        assert(cursor<=header.byte_size && sizeof(command)<=header.byte_size-cursor);
        memcpy(&command,bytes+cursor,sizeof(command));
        assert(command.byte_size>=sizeof(command) && !(command.byte_size&7u));
        assert(command.byte_size<=header.byte_size-cursor);
        uint32_t end=cursor+command.byte_size;
        if(command.opcode==HALO_METAL_DEFINE_UNIFORMS) {
            struct halo_metal_define_uniforms d;assert(sizeof(d)<=command.byte_size);memcpy(&d,bytes+cursor,sizeof(d));
            assert(!d.reserved && !(d.data_offset&15u));
            assert((d.kind==HALO_METAL_UNIFORM_VERTEX && d.data_size==3120) ||
                   (d.kind==HALO_METAL_UNIFORM_PIXEL && d.data_size==608));
            assert(d.data_offset>=cursor+sizeof(d) && d.data_offset<=end && d.data_size<=end-d.data_offset);
            assert(definition_count<65536);
            definitions[definition_count].kind=d.kind;definitions[definition_count].offset=d.data_offset;
            definitions[definition_count++].size=d.data_size;host_definitions++;
        } else if(command.opcode==HALO_METAL_DRAW_UNIFORM_REFS || command.opcode==HALO_METAL_DRAW_COMPACT) {
            struct halo_metal_draw d;assert(sizeof(d)<=command.byte_size);memcpy(&d,bytes+cursor,sizeof(d));
            assert(consumed<expected_count);
            uint32_t offsets[]={d.vertex_uniforms_offset,d.pixel_uniforms_offset};
            const uint32_t kinds[]={HALO_METAL_UNIFORM_VERTEX,HALO_METAL_UNIFORM_PIXEL},sizes[]={3120,608};
            const void *wanted[]={expected[consumed].vertex,expected[consumed].pixel};
            for(unsigned u=0;u<2;u++) {
                assert(offsets[u]<=header.byte_size && sizes[u]<=header.byte_size-offsets[u]);
                if(command.opcode==HALO_METAL_DRAW_UNIFORM_REFS) {
                    int prior=0;
                    for(uint32_t j=0;j<definition_count;j++)
                        if(definitions[j].kind==kinds[u] && definitions[j].offset==offsets[u] && definitions[j].size==sizes[u]) prior=1;
                    assert(prior && offsets[u]<cursor);
                } else assert(offsets[u]>=cursor+sizeof(struct halo_metal_draw_compact) && sizes[u]<=end-offsets[u]);
                assert(!memcmp(bytes+offsets[u],wanted[u],sizes[u]));
            }
            consumed++;host_draws++;
        }
        cursor=end;
    }
    assert(cursor==header.byte_size);
    host_packets++;if(header.command_count>host_max_commands)host_max_commands=header.command_count;
    if(header.byte_size<minimum_packet_size)minimum_packet_size=header.byte_size;
    if(header.byte_size>maximum_packet_size)maximum_packet_size=header.byte_size;
}
static void reply(void) {
    transport.reply=(struct halo_metal_reply){.abi_version=HALO_METAL_ABI_VERSION,.status=HALO_METAL_OK,
        .failed_command=UINT32_MAX,.capabilities=ALL_CAPABILITIES,
        .submitted_sequence=transport.sequence,.completed_sequence=transport.sequence};
}
int host_metal_initialize(uint32_t w,uint32_t f,uint32_t o,uint32_t n) {
    assert(w==1 && f==HALO_METAL_ENABLE_UNIFORM_SHARING && o==(uint32_t)(uintptr_t)&transport.reply && n==sizeof(transport.reply));
    reply();return HALO_METAL_OK;
}
int host_metal_submit(uint32_t p,uint32_t n,uint32_t o,uint32_t s) {
    assert(p==(uint32_t)(uintptr_t)transport.bytes && n==transport.size && o==(uint32_t)(uintptr_t)&transport.reply && s==sizeof(transport.reply));
    inspect_packet();reply();return HALO_METAL_OK;
}
int host_metal_readback(uint32_t i,uint32_t g,uint32_t p,uint32_t d,uint32_t n,uint32_t o,uint32_t s) {
    (void)i;(void)g;(void)p;(void)d;(void)n;(void)o;(void)s;assert(0);return HALO_METAL_INVALID;
}
void host_metal_shutdown(void) {}
static void setup(uint32_t capacity) {
    void *storage=aligned_alloc(16,capacity);assert(storage);
    sequence=packet_expected_end=0;packet_group_active=FALSE;metal_uniform_cache_reset(&uniform_cache);
    memset(&draw_profile,0,sizeof(draw_profile));
    expected_count=consumed=host_packets=host_definitions=host_draws=host_max_commands=maximum_packet_size=0;
    minimum_packet_size=UINT32_MAX;
    require_status("setup",halo_metal_guest_setup(&transport,storage,capacity));
    require_status("initialize",halo_metal_guest_initialize(&transport,1,HALO_METAL_ENABLE_UNIFORM_SHARING,HALO_METAL_CAP_UNIFORM_SHARING));
}
static void done(void) {
    packet_flush(NATIVE_FLUSH_EXIT);assert(consumed==expected_count);free(transport.bytes);
}
static struct metal_draw_state_output output(void) {
    struct metal_draw_state_output out;
    unsigned char *bytes=(void *)&out;for(size_t i=0;i<sizeof(out);i++)bytes[i]=(unsigned char)(i*37+19);
    return out;
}
static void shared_draw(const struct metal_draw_state_output *out,uint32_t vertex_bytes) {
    expect_draw(out);
    uint32_t uniform_vertex=0,uniform_pixel=0,payloads[]={vertex_bytes,4};
    uniform_group_begin(out,vertex_bytes ? payloads:NULL,vertex_bytes ? 2:0,&uniform_vertex,&uniform_pixel);
    struct halo_metal_draw_uniform_refs draw={0};draw.draw.command.opcode=HALO_METAL_DRAW_UNIFORM_REFS;
    draw.draw.vertex_uniforms_offset=uniform_vertex;draw.draw.pixel_uniforms_offset=uniform_pixel;
    draw.input_kind=vertex_bytes ? HALO_METAL_INPUT_EXPANDED:HALO_METAL_INPUT_GEOMETRY;
    if(!vertex_bytes)draw.geometry=(struct halo_metal_ref){1,1};
    packet_begin(sizeof(draw),vertex_bytes ? payloads:NULL,vertex_bytes ? 2:0);
    uint32_t offset=command_append(&draw,sizeof(draw));
    if(vertex_bytes) {
        void *data=malloc(vertex_bytes);assert(data);memset(data,0x71,vertex_bytes);uint32_t index=0;
        payload_append(offset,offsetof(struct halo_metal_draw,vertices_offset),data,vertex_bytes);
        payload_append(offset,offsetof(struct halo_metal_draw,indices_offset),&index,4);free(data);
    }
    packet_group_active=FALSE;packet_finish();
}
static void filler(uint32_t bytes) {
    struct halo_metal_upload command={0};command.command.opcode=HALO_METAL_UPLOAD;command.data_size=bytes;
    packet_begin(sizeof(command),&bytes,1);uint32_t offset=command_append(&command,sizeof(command));
    void *data=malloc(bytes);assert(data);memset(data,0x35,bytes);
    payload_append(offset,offsetof(struct halo_metal_upload,data_offset),data,bytes);free(data);packet_finish();
}
static void commands_until(uint32_t count) {
    while(transport.command_count<count) {
        struct halo_metal_delete command={{HALO_METAL_DELETE_TEXTURE,0},{1,1}};
        packet_begin(sizeof(command),NULL,0);command_append(&command,sizeof(command));packet_finish();
    }
}
int main(int argc,char **argv) {
    assert(argc==2);struct metal_draw_state_output out=output();
    if(!strcmp(argv[1],"mutations")) {
        setup(HALO_METAL_MAX_PACKET);shared_draw(&out,0);shared_draw(&out,0);
        ((unsigned char *)&out.vertex)[sizeof(out.vertex)-1]^=1;shared_draw(&out,0);
        ((unsigned char *)&out.pixel)[0]^=1;shared_draw(&out,0);
        memset(&out,0,sizeof(out));done();assert(host_definitions==4 && host_draws==4 && host_packets==1);
    } else if(!strcmp(argv[1],"saturation")) {
        setup(HALO_METAL_MAX_PACKET);
        for(uint32_t i=0;i<METAL_UNIFORM_CACHE_ENTRIES-1;i++) {
            memcpy(&out.vertex,&i,sizeof(i));shared_draw(&out,0);
        }
        uint32_t different=METAL_UNIFORM_CACHE_ENTRIES;memcpy(&out.vertex,&different,sizeof(different));
        shared_draw(&out,0);shared_draw(&out,0);done();
        assert(host_packets==1 && host_draws==METAL_UNIFORM_CACHE_ENTRIES+1);
        assert(host_definitions==METAL_UNIFORM_CACHE_ENTRIES+2);
    } else if(!strcmp(argv[1],"forced-flush")) {
        setup(HALO_METAL_MAX_PACKET);shared_draw(&out,0);packet_flush(NATIVE_FLUSH_VISIBILITY_READY);
        shared_draw(&out,0);done();assert(host_definitions==4 && host_draws==2 && host_packets==2);
    } else if(!strcmp(argv[1],"soft")) {
        setup(HALO_METAL_MAX_PACKET);filler(NATIVE_BATCH_SOFT_BYTES-1024);shared_draw(&out,0);done();
        assert(host_definitions==2 && host_draws==1 && host_packets==2);
        setup(HALO_METAL_MAX_PACKET);shared_draw(&out,NATIVE_BATCH_SOFT_BYTES);done();
        assert(host_definitions==2 && host_draws==1 && host_packets==1 && maximum_packet_size>NATIVE_BATCH_SOFT_BYTES);
    } else if(!strcmp(argv[1],"hard")) {
        setup(8192);filler(7000);shared_draw(&out,0);done();
        assert(host_definitions==2 && host_draws==1 && host_packets==2 && maximum_packet_size<=8192);
    } else if(!strcmp(argv[1],"commands")) {
        setup(HALO_METAL_MAX_PACKET);shared_draw(&out,0);commands_until(65534);
        ((unsigned char *)&out.vertex)[0]^=1;shared_draw(&out,0);done();
        assert(host_packets==1 && host_max_commands==65536 && host_definitions==3 && host_draws==2);
        setup(HALO_METAL_MAX_PACKET);shared_draw(&out,0);commands_until(65535);
        ((unsigned char *)&out.vertex)[0]^=1;shared_draw(&out,0);done();
        assert(host_packets==2 && host_definitions==4 && host_draws==2 && host_max_commands==65535);
    } else if(!strcmp(argv[1],"legacy-limit")) {
        setup(HALO_METAL_MAX_PACKET);
        uint32_t payloads[]={HALO_METAL_MAX_PACKET-8192,4,sizeof(out.vertex),sizeof(out.pixel)},end;
        while(!halo_metal_packet_room(sizeof(struct halo_metal_packet),transport.capacity,
            sizeof(struct halo_metal_draw_compact),payloads,4,&end)) payloads[0]+=8;
        payloads[0]-=8;
        assert(!halo_metal_packet_room(sizeof(struct halo_metal_packet),transport.capacity,
            sizeof(struct halo_metal_draw_compact),payloads,4,&end));
        assert(!sharing_selected(payloads));expect_draw(&out);
        struct halo_metal_draw_compact draw={0};draw.draw.command.opcode=HALO_METAL_DRAW_COMPACT;
        packet_begin(sizeof(draw),payloads,4);uint32_t offset=command_append(&draw,sizeof(draw));
        void *data=malloc(payloads[0]);assert(data);memset(data,0x17,payloads[0]);uint32_t index=0;
        payload_append(offset,offsetof(struct halo_metal_draw,vertices_offset),data,payloads[0]);free(data);
        payload_append(offset,offsetof(struct halo_metal_draw,indices_offset),&index,4);
        payload_append(offset,offsetof(struct halo_metal_draw,vertex_uniforms_offset),&out.vertex,sizeof(out.vertex));
        payload_append(offset,offsetof(struct halo_metal_draw,pixel_uniforms_offset),&out.pixel,sizeof(out.pixel));
        packet_finish();done();assert(host_packets==1 && host_draws==1 && !host_definitions);
        assert(maximum_packet_size<=HALO_METAL_MAX_PACKET && maximum_packet_size>HALO_METAL_MAX_PACKET-128);
    } else abort();
    return 0;
}
'''


class UniformPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-metal-uniform-packets-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = (ROOT / "port/linux/src/d3d8_metal.c").read_text()
        declarations = []
        for name in ("enum native_flush_reason", "struct native_flush_statistics", "struct native_draw_profile"):
            start = source.index(name + " {")
            declarations.append(source[start:source.index("};", start) + 2])
        names = ("native_flush_reason_name", "packet_flush", "packet_begin", "command_append", "payload_append",
                 "packet_finish", "uniform_group_room", "uniform_define", "uniform_group_begin")
        production = "\n\n".join(function(source, name) for name in names)
        transport = (ROOT / "port/linux/src/metal_guest_transport.c").read_text()
        assertion = '_Static_assert(sizeof(void *) == 4, "Native transport runs in the ILP32 guest");'
        assert transport.count(assertion) == 1
        transport = transport.replace(assertion, "")
        selection = source.split("BOOL shared_uniform_draw=", 1)[1].split(";", 1)[0]
        path = directory / "uniform_packet.c"
        path.write_text(HARNESS.replace("/* DECLARATIONS */", "\n".join(declarations))
                        .replace("/* TRANSPORT */", transport).replace("/* FRONTEND */", production)
                        .replace("/* SELECTION */", selection))
        cls.binary = directory / "uniform_packet"
        compiled = subprocess.run(["clang", "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                   "-DHALO_MACOS_NATIVE_METAL=1", "-I", str(ROOT / "port/linux/src"), str(path),
                                   str(ROOT / "port/linux/src/metal_vertex_fetch.c"),
                                   str(ROOT / "port/linux/src/metal_packet_room.c"), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def test_complete_uniform_groups_and_exact_prior_refs_across_all_packet_boundaries(self):
        for name in ("mutations", "forced-flush", "soft", "hard", "commands", "legacy-limit"):
            with self.subTest(boundary=name):
                result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_interning_dictionary_emits_fresh_owned_definitions_for_each_uncached_draw(self):
        result = subprocess.run([str(self.binary), "saturation"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
