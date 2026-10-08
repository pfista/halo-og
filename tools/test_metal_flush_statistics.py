"""CPU checks of production native packet boundaries and diagnostic counters.

Production flush/reservation/callback/query functions are extracted unchanged;
only the GPU transport and clock are mocked. This validates ordering and log
accounting, not GPU timing or gameplay performance.
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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <setjmp.h>
#include "port/linux/src/metal_guest_transport.h"
#include "port/linux/src/metal_packet_room.h"
#define WINAPI
#define FALSE 0
#define VISIBILITY_ALL_SAMPLES 1000000
/* SOFT BATCH LIMIT */
typedef uint32_t DWORD;
typedef unsigned D3DCALLBACKTYPE;
typedef void (*D3DCALLBACK)(DWORD);
static struct {
    int ready;
    unsigned long frame;
    int query_pending[8];
    struct halo_metal_ref query_slots[8];
    unsigned query_results[8];
} device;
static struct halo_metal_guest_transport transport;
static uint64_t sequence;
static uint32_t packet_expected_end;
static uint64_t submitted_batches,submitted_commands,submitted_bytes,submit_wall_ns;
static uint32_t largest_statistics_batch;
static unsigned submits,begins,clock_reads,config_reads,logs,failed_packets,readbacks,callbacks;
static uint64_t result_word;
static int diagnostics,submit_status,failure_status;
static char log_lines[128][1024];
static jmp_buf failure;
static void platform_log(const char *format,...) {
    assert(logs<128);va_list args;va_start(args,format);
    int length=vsnprintf(log_lines[logs++],sizeof(log_lines[0]),format,args);va_end(args);
    assert(length>0 && (size_t)length<sizeof(log_lines[0]));
}
static int config_boolean(const char *key) {
    assert(!strcmp(key,"debug.gpu_stats"));config_reads++;return diagnostics;
}
static uint64_t monotonic_ns(void) { return (uint64_t)++clock_reads*1000; }
static _Noreturn void native_fail(const char *operation,int status) {
    assert(operation);failure_status=status;longjmp(failure,1);
}
static void require_status(const char *operation,int status) { if(status)native_fail(operation,status); }
static void native_failed_packet(void) { failed_packets++; }
int halo_metal_guest_submit(struct halo_metal_guest_transport *t) {
    assert(t==&transport && t->recording && t->command_count && t->size==packet_expected_end);
    submits++;if(submit_status)return submit_status;t->recording=0;return 0;
}
int halo_metal_guest_begin(struct halo_metal_guest_transport *t,uint64_t next) {
    assert(t==&transport && !t->recording && next>t->sequence);
    begins++;t->recording=1;t->sequence=next;t->size=sizeof(struct halo_metal_packet);t->command_count=0;return 0;
}
int halo_metal_guest_readback(struct halo_metal_guest_transport *t,struct halo_metal_ref ref,
                             uint32_t plane,void *out,uint32_t bytes) {
    assert(t==&transport && !t->recording && ref.id==9 && ref.generation==3);
    assert(plane==HALO_METAL_VISIBILITY && bytes==sizeof(result_word));
    readbacks++;memcpy(out,&result_word,bytes);return 0;
}
/* PRODUCTION */
static void reset(void) {
    memset(&device,0,sizeof(device));memset(&transport,0,sizeof(transport));
    memset(flush_statistics,0,sizeof(flush_statistics));memset(log_lines,0,sizeof(log_lines));
    sequence=0;packet_expected_end=0;submitted_batches=submitted_commands=submitted_bytes=submit_wall_ns=0;
    largest_statistics_batch=0;submits=begins=clock_reads=config_reads=logs=failed_packets=readbacks=callbacks=0;
    diagnostics=submit_status=failure_status=0;result_word=0;
    device.ready=1;device.frame=17;transport.capacity=HALO_METAL_MAX_PACKET;
}
static void queue(uint32_t bytes,uint32_t commands) {
    assert(!transport.recording && bytes>=sizeof(struct halo_metal_packet) && !(bytes&7));
    transport.recording=1;transport.sequence=++sequence;transport.size=bytes;transport.command_count=commands;
    packet_expected_end=bytes;
}
static void callback(DWORD context) {
    assert(context==29 && !transport.recording);callbacks++;
}
static void append_reserved(void) {
    transport.command_count++;transport.size=packet_expected_end;packet_finish();
}
int main(int argc,char **argv) {
    assert(argc==2);reset();
    if(!strcmp(argv[1],"disabled")) {
        queue(80,2);packet_flush(NATIVE_FLUSH_PRESENT);
        assert(submits==1 && submitted_batches==1 && submitted_commands==2 && submitted_bytes==80);
        assert(clock_reads==2 && config_reads==1 && submit_wall_ns==1000 && largest_statistics_batch==80);
        assert(!logs && !flush_statistics[NATIVE_FLUSH_PRESENT].packets && packet_expected_end==0);
    } else if(!strcmp(argv[1],"empty")) {
        diagnostics=1;
        for(unsigned i=0;i<NATIVE_FLUSH_REASON_COUNT;i++)packet_flush((enum native_flush_reason)i);
        halo_metal_flush_pending();D3DDevice_KickPushBuffer();D3DDevice_InsertCallback(0,NULL,29);
        assert(!submits && !clock_reads && !config_reads && !logs && !callbacks);
    } else if(!strcmp(argv[1],"totals")) {
        diagnostics=1;
        for(unsigned i=0;i<NATIVE_FLUSH_REASON_COUNT;i++) {
            queue(80+i*8,2+i);packet_flush((enum native_flush_reason)i);
            const struct native_flush_statistics *s=&flush_statistics[i];
            assert(s->packets==1 && s->commands==2+i && s->bytes==80+i*8 && s->wall_ns==1000);
            char expected[256];snprintf(expected,sizeof(expected),"Native flush: frame 17, sequence %u, reason %s, commands %u, bytes %u, start %u ns, end %u ns, submit 1000 ns",
                i+1,native_flush_reason_name((enum native_flush_reason)i),2+i,80+i*8,(2*i+1)*1000,(2*i+2)*1000);
            assert(!strcmp(log_lines[i],expected));
        }
        queue(96,3);packet_flush(NATIVE_FLUSH_PRESENT);
        struct native_flush_statistics present=flush_statistics[NATIVE_FLUSH_PRESENT];
        assert(present.packets==2 && present.commands==11 && present.bytes==224 && present.wall_ns==2000);
        native_flush_statistics_log(0,59);
        assert(logs==2*NATIVE_FLUSH_REASON_COUNT+1);
        assert(strstr(log_lines[NATIVE_FLUSH_REASON_COUNT+1+NATIVE_FLUSH_PRESENT],"frames 0-59, reason Present, packets 2, commands 11, bytes 224, submit 2000 ns"));
        for(unsigned i=0;i<NATIVE_FLUSH_REASON_COUNT;i++)assert(!memcmp(&flush_statistics[i],&(struct native_flush_statistics){0},sizeof(flush_statistics[i])));
        native_flush_statistics_log(60,119);assert(logs==2*NATIVE_FLUSH_REASON_COUNT+1);
    } else if(!strcmp(argv[1],"limits")) {
        diagnostics=1;
        assert(NATIVE_BATCH_SOFT_BYTES==16u*1024u*1024u && HALO_METAL_MAX_PACKET==64u*1024u*1024u);
        queue(4u*1024u*1024u,2);packet_finish();assert(!submits && transport.recording);
        packet_flush(NATIVE_FLUSH_PRESENT);
        queue(NATIVE_BATCH_SOFT_BYTES-8,2);packet_finish();assert(submits==1 && transport.recording);
        packet_flush(NATIVE_FLUSH_PRESENT);
        queue(NATIVE_BATCH_SOFT_BYTES-8,2);packet_begin(16,NULL,0);
        assert(submits==3 && begins==1 && flush_statistics[NATIVE_FLUSH_SOFT_BATCH_LIMIT].packets==1);
        append_reserved();packet_flush(NATIVE_FLUSH_PRESENT);
        transport.capacity=128;queue(120,2);packet_begin(16,NULL,0);
        assert(flush_statistics[NATIVE_FLUSH_HARD_CAPACITY].packets==1);append_reserved();packet_flush(NATIVE_FLUSH_PRESENT);
        transport.capacity=HALO_METAL_MAX_PACKET;queue(80,65536);packet_begin(16,NULL,0);
        assert(flush_statistics[NATIVE_FLUSH_COMMAND_LIMIT].packets==1);append_reserved();packet_flush(NATIVE_FLUSH_PRESENT);
        queue(NATIVE_BATCH_SOFT_BYTES,2);packet_finish();assert(flush_statistics[NATIVE_FLUSH_SOFT_BATCH_LIMIT].packets==2);
        queue(80,65536);packet_finish();assert(flush_statistics[NATIVE_FLUSH_COMMAND_LIMIT].packets==2);
        queue(80,2);unsigned prior=submits;uint32_t invalid[]={0};
        if(!setjmp(failure)) { packet_begin(16,invalid,1);assert(0); }
        assert(failure_status==HALO_METAL_INVALID && submits==prior && transport.recording);
        packet_flush(NATIVE_FLUSH_EXIT);
    } else if(!strcmp(argv[1],"boundaries")) {
        diagnostics=1;queue(80,2);D3DDevice_KickPushBuffer();
        assert(flush_statistics[NATIVE_FLUSH_KICK_PUSH_BUFFER].packets==1);
        queue(80,2);D3DDevice_InsertCallback(0,NULL,29);assert(transport.recording && submits==1);
        D3DDevice_InsertCallback(0,callback,29);assert(callbacks==1 && flush_statistics[NATIVE_FLUSH_INSERT_CALLBACK].packets==1);
        queue(80,2);device.ready=0;halo_metal_flush_pending();D3DDevice_KickPushBuffer();assert(submits==2 && transport.recording);
        device.ready=1;halo_metal_flush_pending();assert(flush_statistics[NATIVE_FLUSH_EXIT].packets==1);
        device.query_slots[3]=(struct halo_metal_ref){9,3};query_collect(3);assert(!readbacks && submits==3);
        queue(80,2);device.query_pending[3]=1;result_word=19;query_collect(3);
        assert(readbacks==1 && submits==4 && device.query_results[3]==VISIBILITY_ALL_SAMPLES && !device.query_pending[3]);
        assert(flush_statistics[NATIVE_FLUSH_VISIBILITY_COLLECT].packets==1);
        device.query_pending[3]=1;result_word=0;query_collect(3);
        assert(readbacks==2 && submits==4 && !device.query_results[3] && !device.query_pending[3]);
    } else if(!strcmp(argv[1],"rejection")) {
        diagnostics=1;queue(80,2);submit_status=HALO_METAL_INVALID;
        if(!setjmp(failure)) { packet_flush(NATIVE_FLUSH_PRESENT);assert(0); }
        assert(failure_status==HALO_METAL_INVALID && failed_packets==1 && submits==1);
        assert(!submitted_batches && !submitted_commands && !submitted_bytes && !submit_wall_ns);
        assert(!config_reads && !logs && !flush_statistics[NATIVE_FLUSH_PRESENT].packets && transport.recording);
        reset();diagnostics=1;queue(80,2);packet_expected_end=72;
        if(!setjmp(failure)) { packet_flush(NATIVE_FLUSH_PRESENT);assert(0); }
        assert(failure_status==HALO_METAL_INVALID && !submits && !clock_reads && !logs);
    } else abort();
    return 0;
}
'''


class NativeFlushStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-metal-flush-cpu-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        production = SOURCE.read_text()
        soft_limit = next(line for line in production.splitlines() if line.startswith("#define NATIVE_BATCH_SOFT_BYTES "))
        start = production.index("enum native_flush_reason {")
        end = production.index("static uint64_t monotonic_ns(void)", start)
        declarations = production[start:end]
        functions = "\n".join(function(production, name) for name in
                              ("packet_flush", "packet_begin", "packet_finish", "halo_metal_flush_pending",
                               "D3DDevice_KickPushBuffer", "D3DDevice_InsertCallback", "query_collect"))
        path = folder / "flush.c"
        path.write_text(HARNESS.replace("/* SOFT BATCH LIMIT */", soft_limit)
                        .replace("/* PRODUCTION */", declarations + functions))
        cls.binary = folder / "flush"
        compiled = subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                   "-DHALO_MACOS_NATIVE_METAL=1", "-I", str(ROOT), str(path),
                                   str(ROOT / "port/linux/src/metal_packet_room.c"), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, name):
        execution = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)

    def test_disabled_diagnostics_preserve_submission_and_existing_accounting(self):
        self.run_case("disabled")

    def test_empty_flushes_do_no_transport_clock_or_log_work(self):
        self.run_case("empty")

    def test_sequence_timing_and_reason_totals_reset_after_reporting(self):
        self.run_case("totals")

    def test_soft_hard_and_command_limits_preserve_reservation_before_submit(self):
        self.run_case("limits")

    def test_callbacks_exit_and_visibility_collection_preserve_order(self):
        self.run_case("boundaries")

    def test_failed_or_incomplete_packets_never_increment_success_totals(self):
        self.run_case("rejection")


if __name__ == "__main__":
    unittest.main()
