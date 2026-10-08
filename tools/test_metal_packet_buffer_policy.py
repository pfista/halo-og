"""CPU checks of production Metal packet-buffer allocation/reuse policy.

The allocation function is extracted unchanged apart from Objective-C resource
syntax mapped to CPU buffers. Allocation failures are injected. No GPU device,
Metal command submission or game build runs.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.test_metal_backbuffer_history import function

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/macos/host/host_metal.mm"

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <set>
#include <string>
#include <vector>
#include "port/macos/include/halo_metal_abi.h"
struct Buffer {
    size_t length;
    std::vector<uint8_t> contents;
    explicit Buffer(size_t bytes):length(bytes),contents(bytes,0xa7) {}
};
static struct {
    std::shared_ptr<Buffer> draw_input_buffer;
    struct { bool enabled=true; uint64_t packet_buffers=0; } metrics;
} context;
static std::vector<size_t> attempts;
static std::set<size_t> failed_sizes;
static std::shared_ptr<Buffer> allocate(size_t size) {
    attempts.push_back(size);
    return failed_sizes.count(size) ? nullptr:std::make_shared<Buffer>(size);
}
struct Failure { int status; };
static void check(bool condition,int status) { if(!condition)throw Failure{status}; }
/* PRODUCTION */
static std::shared_ptr<Buffer> packet(size_t size,uint8_t value=33) {
    const std::vector<uint8_t> source(size,value);
    auto buffer=packet_input_buffer(source);
    assert(buffer && buffer->length>=size);
    // The submit path fills owned storage directly; this fixture exercises
    // allocation/retention while retaining independent payload canaries.
    memset(buffer->contents.data(),value,size);
    return buffer;
}
int main(int argc,char **argv) {
    assert(argc==2);
    constexpr size_t mib=1024u*1024u,limit=16u*mib;
    static_assert(HALO_METAL_MAX_PACKET==64u*mib,"unchanged hard limit");
    if(std::string(argv[1])=="growth") {
        auto small=packet(16385);assert(small->length==32768 && context.metrics.packet_buffers==1);
        auto medium=packet(4u*mib+1);assert(medium->length==8u*mib && context.metrics.packet_buffers==2);
        auto large=packet(8u*mib+1);assert(large->length==limit && context.metrics.packet_buffers==3);
        assert(packet(4u*mib,77)==large && context.metrics.packet_buffers==3);
        assert(packet(limit,88)==large && context.metrics.packet_buffers==3);
        assert(small->contents[0]==33 && medium->contents[0]==33);
    } else if(std::string(argv[1])=="boundary") {
        auto retained=packet(limit);assert(retained==context.draw_input_buffer && attempts.size()==1 && attempts[0]==limit);
        assert(packet(limit,44)==retained && context.metrics.packet_buffers==1);
        auto oversized=packet(limit+1,55);
        assert(oversized!=retained && oversized->length==limit+1 && context.draw_input_buffer==retained);
        assert(context.metrics.packet_buffers==2 && attempts.back()==limit+1);
        assert(packet(4u*mib,66)==retained && context.metrics.packet_buffers==2);
        assert(oversized->contents[0]==55 && retained->length==limit);
    } else if(std::string(argv[1])=="maximum") {
        auto retained=packet(limit);auto maximum=packet(HALO_METAL_MAX_PACKET,44);
        assert(maximum->length==HALO_METAL_MAX_PACKET && maximum!=retained && context.draw_input_buffer==retained);
        assert(context.metrics.packet_buffers==2 && attempts.back()==HALO_METAL_MAX_PACKET);
        assert(packet(limit,55)==retained && context.metrics.packet_buffers==2);
    } else if(std::string(argv[1])=="fallback") {
        failed_sizes.insert(8u*mib);auto exact=packet(4u*mib+1);
        assert(exact->length==4u*mib+1 && context.draw_input_buffer==exact && context.metrics.packet_buffers==1);
        assert((attempts==std::vector<size_t>{8u*mib,4u*mib+1}));
        assert(packet(4u*mib+1,44)==exact && attempts.size()==2);
        failed_sizes.clear();auto growth=packet(4u*mib+2,55);
        assert(growth->length==8u*mib && context.draw_input_buffer==growth && context.metrics.packet_buffers==2);
        assert(exact->contents[0]==44);
    } else if(std::string(argv[1])=="failure") {
        auto prior=packet(16384);failed_sizes={8u*mib,4u*mib+1};bool rejected=false;
        try { packet(4u*mib+1,44); } catch(Failure failure) { assert(failure.status==HALO_METAL_MEMORY);rejected=true; }
        assert(rejected && context.draw_input_buffer==prior && context.metrics.packet_buffers==1 && prior->contents[0]==33);
        assert(attempts.size()==3 && attempts[1]==8u*mib && attempts[2]==4u*mib+1);
        failed_sizes.clear();assert(packet(4u*mib+1,55)->length==8u*mib && context.metrics.packet_buffers==2);
    } else if(std::string(argv[1])=="exact-failure") {
        auto prior=packet(16384);failed_sizes.insert(limit);bool rejected=false;
        try { packet(limit); } catch(Failure failure) { assert(failure.status==HALO_METAL_MEMORY);rejected=true; }
        assert(rejected && attempts.size()==2 && attempts.back()==limit && context.draw_input_buffer==prior);
        assert(context.metrics.packet_buffers==1);
    } else if(std::string(argv[1])=="disabled") {
        context.metrics.enabled=false;auto retained=packet(limit);
        assert(packet(4u*mib,44)==retained && context.metrics.packet_buffers==0 && attempts.size()==1);
    } else assert(false);
    return 0;
}
'''


class PacketBufferPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-metal-buffer-policy-cpu-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        production = function(SOURCE.read_text(), "packet_input_buffer")
        replacements = {
            "id<MTLBuffer>": "std::shared_ptr<Buffer>",
            "nil": "nullptr",
            "buffer.length": "buffer->length",
            "buffer.contents": "buffer->contents.data()",
            "[context.device newBufferWithLength:packet.size() options:MTLResourceStorageModeShared]": "allocate(packet.size())",
            "[context.device newBufferWithLength:capacity options:MTLResourceStorageModeShared]": "allocate(capacity)",
        }
        for original, replacement in replacements.items():
            if original not in production:
                raise AssertionError(f"Production resource syntax changed: {original}")
            production = production.replace(original, replacement)
        path = folder / "policy.cpp"
        path.write_text(HARNESS.replace("/* PRODUCTION */", production))
        cls.binary = folder / "policy"
        compiled = subprocess.run(["clang++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                   "-I", str(ROOT), str(path), "-o", str(cls.binary)],
                                  capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_growth_from_4_mib_to_16_mib_retains_and_reuses_equal_capacity(self):
        self.run_case("growth")

    def test_16_mib_boundary_retains_only_bounded_storage(self):
        self.run_case("boundary")

    def test_64_mib_packets_keep_their_valid_temporary_allocation_path(self):
        self.run_case("maximum")

    def test_rounded_allocation_failure_falls_back_to_exact_size(self):
        self.run_case("fallback")

    def test_double_failure_preserves_previous_buffer_and_allocation_count(self):
        self.run_case("failure")

    def test_exact_allocation_failure_is_not_retried_identically(self):
        self.run_case("exact-failure")

    def test_disabled_diagnostics_do_not_change_reuse(self):
        self.run_case("disabled")


if __name__ == "__main__":
    unittest.main()
