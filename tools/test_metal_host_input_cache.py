"""CPU checks of the production sampler keys and immutable draw-input slices.

These exercise extracted production code without a Metal device. Actual Metal
binding alignment, GPU lifetime and ordered output remain GPU fixture checks.
"""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'port/macos/host/host_metal.mm'


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class HostInputCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('clang++ is required for production CPU extraction')
        source = HOST.read_text()
        key_code = source[source.index('using SamplerKey ='):source.index('struct Metrics {')]
        slice_code = source[source.index('    draw.vertices = draw.indices ='):
                            source.index('    if (query) {', source.index('    draw.vertices = draw.indices ='))]
        cls.directory = tempfile.TemporaryDirectory(prefix='metal-host-input-cache-')
        folder = Path(cls.directory.name)
        harness = folder / 'cache.cpp'
        harness.write_text('''#include <array>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <map>
#include <stdexcept>
#include "halo_metal_abi.h"
''' + key_code + '''
static std::map<SamplerKey,uint32_t> cache;
extern "C" void key_for(const halo_metal_sampler *value,uint32_t border,uint32_t *out) {
    auto key=sampler_key(*value,border);memcpy(out,key.data(),sizeof(key));
}
extern "C" int valid(const halo_metal_sampler *value) { return sampler_valid(*value); }
extern "C" void reset(void) { cache.clear(); }
extern "C" unsigned count(void) { return cache.size(); }
extern "C" int insert(const halo_metal_sampler *value,uint32_t border,uint32_t handle) {
    return sampler_cache_insert(cache,sampler_key(*value,border),handle);
}
extern "C" unsigned lookup(const halo_metal_sampler *value,uint32_t border) {
    auto found=cache.find(sampler_key(*value,border));return found==cache.end() ? 0:found->second;
}
struct MockDraw {
    uintptr_t vertices=0,indices=0,vertexUniforms=0,pixelUniforms=0;
    uint64_t vertexOffset=0,indexOffset=0,vertexUniformOffset=0,pixelUniformOffset=0;
};
extern "C" unsigned draw_record_size(void) { return sizeof(halo_metal_draw); }
extern "C" unsigned draw_offset_start(void) { return offsetof(halo_metal_draw,vertices_offset); }
extern "C" void input_slices(const halo_metal_draw *command,uint64_t *out) {
    const auto &c=*command;MockDraw draw;uintptr_t input_buffer=0x12345678u;
''' + slice_code + '''
    const uint64_t result[]={draw.vertices,draw.indices,draw.vertexUniforms,draw.pixelUniforms,
        draw.vertexOffset,draw.indexOffset,draw.vertexUniformOffset,draw.pixelUniformOffset};
    memcpy(out,result,sizeof(result));
}
static void check(bool value) { if(!value)throw std::runtime_error("invalid"); }
''' + function(source, 'void inline_range(') + '''
extern "C" int valid_slice(uint64_t position,uint32_t command_bytes,uint64_t fixed,
                            uint32_t offset,uint64_t bytes,uint32_t alignment) {
    try { inline_range(position,command_bytes,fixed,offset,bytes,alignment);return 1; }
    catch(const std::runtime_error &) { return 0; }
}
''')
        library = folder / 'cache.dylib'
        subprocess.run([compiler, '-std=c++17', '-dynamiclib', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(ROOT / 'port/macos/include'), str(harness), '-o', str(library)],
                       check=True, capture_output=True, text=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.key_for.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        cls.lib.valid.argtypes = [ctypes.c_void_p]
        cls.lib.insert.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        cls.lib.lookup.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        cls.lib.input_slices.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cls.lib.valid_slice.argtypes = [ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint64,
                                       ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32]

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @staticmethod
    def sampler(**changes):
        values = dict(min_filter=1, mag_filter=1, mip_filter=2, address_u=0,
                      address_v=2, address_w=2, max_anisotropy=1, reserved=0,
                      lod_min=0.0, lod_max=100.0)
        values.update(changes)
        return ctypes.create_string_buffer(struct.pack('<8I2f', *values.values()), 40)

    def key(self, sampler, border=0):
        output = (ctypes.c_uint32 * 11)()
        self.lib.key_for(sampler, border, output)
        return bytes(output)

    def test_key_preserves_all_wire_bits_and_native_border(self):
        original = self.sampler()
        self.assertEqual(self.key(original, 2), original.raw + struct.pack('<I', 2))
        for byte in range(40):
            changed = bytearray(original.raw)
            changed[byte] ^= 1
            with self.subTest(byte=byte):
                self.assertNotEqual(self.key(ctypes.create_string_buffer(bytes(changed), 40)), self.key(original))
        self.assertEqual(len({self.key(original, border) for border in (0, 1, 2)}), 3)
        self.assertNotEqual(self.key(self.sampler(lod_min=-0.0)), self.key(original))

    def test_original_sampler_acceptance_and_rejection(self):
        for valid in (self.sampler(), self.sampler(lod_min=-0.0),
                      self.sampler(min_filter=0, mag_filter=0, mip_filter=0, max_anisotropy=16),
                      self.sampler(address_u=3, address_v=3, address_w=3, lod_min=10.0, lod_max=10.0)):
            self.assertEqual(self.lib.valid(valid), 1)
        invalid = dict(reserved=1, min_filter=2, mag_filter=2, mip_filter=3,
                       address_u=4, address_v=4, address_w=4, max_anisotropy=0,
                       lod_min=-1.0, lod_max=-1.0)
        for field, value in invalid.items():
            with self.subTest(field=field):
                self.assertEqual(self.lib.valid(self.sampler(**{field: value})), 0)
        self.assertEqual(self.lib.valid(self.sampler(max_anisotropy=17)), 0)
        self.assertEqual(self.lib.valid(self.sampler(lod_min=101.0)), 0)
        for field in ('lod_min', 'lod_max'):
            for value in (float('nan'), float('inf'), -float('inf')):
                self.assertEqual(self.lib.valid(self.sampler(**{field: value})), 0)

    def test_bounded_cache_preserves_hot_states_and_falls_back_when_full(self):
        self.lib.reset()
        for number in range(256):
            self.assertEqual(self.lib.insert(self.sampler(lod_max=float(number)), 0, number + 1), 1)
        self.assertEqual(self.lib.count(), 256)
        self.assertEqual(self.lib.insert(self.sampler(lod_max=256.0), 0, 257), 0)
        self.assertEqual(self.lib.lookup(self.sampler(lod_max=256.0), 0), 0)
        self.assertEqual(self.lib.lookup(self.sampler(lod_max=0.0), 0), 1)
        self.assertEqual(self.lib.insert(self.sampler(lod_max=0.0), 0, 999), 0)
        self.assertEqual(self.lib.lookup(self.sampler(lod_max=0.0), 0), 1)
        self.lib.reset()
        self.assertEqual(self.lib.count(), 0)
        self.assertEqual(self.lib.insert(self.sampler(), 0, 42), 1)

    def test_border_and_lod_variants_do_not_reuse_wrong_state(self):
        self.lib.reset()
        for border in range(3):
            self.assertEqual(self.lib.insert(self.sampler(), border, 10 + border), 1)
        self.assertEqual(self.lib.insert(self.sampler(lod_min=-0.0), 0, 30), 1)
        for border in range(3):
            self.assertEqual(self.lib.lookup(self.sampler(), border), 10 + border)
        self.assertEqual(self.lib.lookup(self.sampler(lod_min=-0.0), 0), 30)

    def test_all_draw_inputs_share_packet_and_keep_distinct_payload_slices(self):
        for offsets in ((512, 1536, 1552, 4672), (8208, 9232, 9248, 12368)):
            # Use the actual ABI layout; the command retains original metadata.
            # Distinct commands use different packet slices.
            command = bytearray(self.lib.draw_record_size())
            struct.pack_into('<4I', command, self.lib.draw_offset_start(), *offsets)
            wire = ctypes.create_string_buffer(bytes(command), len(command))
            result = (ctypes.c_uint64 * 8)()
            self.lib.input_slices(wire, result)
            self.assertEqual(list(result[:4]), [0x12345678] * 4)
            self.assertEqual(tuple(result[4:]), offsets)
            self.assertEqual(wire.raw, bytes(command))

    def test_payload_extent_and_alignment_validation_precedes_gpu_copy(self):
        self.assertEqual(self.lib.valid_slice(24, 4352, 432, 464, 256, 16), 1)
        for values in ((24, 4352, 432, 465, 256, 16),  # unaligned
                       (24, 4352, 432, 448, 256, 16),  # inside fixed command
                       (24, 4352, 432, 464, 0, 16),    # empty
                       (24, 4352, 432, 4368, 16, 16),  # beyond this command
                       (24, 4352, 432, 464, 2**32, 16)):
            with self.subTest(values=values):
                self.assertEqual(self.lib.valid_slice(*values), 0)


if __name__ == '__main__':
    unittest.main()
