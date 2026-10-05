#!/usr/bin/env python3
"""CPU checks for direct 3D companion sampling; no GPU or game launch.

Real-arithmetic footprint identities are independent of emitter syntax. They
do not prove native sampler precision, framebuffer rounding or Xbox parity.
The optional frozen frame baseline checks exact existing GLSL/MSL output.
"""
import ctypes as C
from fractions import Fraction as F
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_metal_pixel_shader as pixel_tests
from test_metal_pixel_shader import (ROOT, PixelKey,
                                     PixelMslOptions, PixelMslOptionsV2,
                                     compiler_cases, textured_key)


class PixelMslOptionsV3(C.Structure):
    _fields_ = PixelMslOptionsV2._fields_ + [('native_volume_border_mask', C.c_uint32)]


def from_record(record):
    key = PixelKey()
    for name, _ in key._fields_:
        if isinstance(record[name], list):
            getattr(key, name)[:] = record[name]
        else:
            setattr(key, name, record[name])
    return key


class VolumeBorderEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pixel_tests.PixelEmitterTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        pixel_tests.PixelEmitterTests.tearDownClass()

    def test_project3d_preserves_coordinates_bias_and_operation_order(self):
        key = textured_key(2, 1)
        key.alpha_kill[1] = 1
        key.color_sign[1] = 15
        source = pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 0, 2))
        self.assertIn('texture3d<float> tex1 [[texture(1)]]', source)
        self.assertIn('volume_border_sampler1 [[sampler(5)]]', source)
        self.assertNotIn('volume_border_sampler0', source)
        self.assertNotIn('alpha_border_sampler', source)
        self.assertIn('float4 b = tex.sample(black_sampler, uvw, bias(u.texture_lod_bias[1]))', source)
        self.assertIn('float4 w = tex.sample(white_sampler, uvw, bias(u.texture_lod_bias[1]))', source)
        self.assertIn('return b + u.texture_border_color[1] * (w - b)', source)
        self.assertIn('t1 = sample_volume_border1(tex1, sampler1, volume_border_sampler1, u, '
                      '(float4(xT1.xyz / (xT1.w != 0.0 ? xT1.w : 1.0), 1.0)).xyz)', source)
        self.assertLess(source.index('t1 = sample_volume_border1'), source.index('t1.a = signed_byte(t1.a)'))
        self.assertLess(source.index('t1.b = signed_byte(t1.b)'), source.index('if (t1.a == 0.0) discard_fragment()'))
        self.assertNotIn('get_width', source)
        self.assertNotIn('dfdx', source)
        self.assertNotIn('sample_volume_border', pixel_tests.PixelEmitterTests.emit(key, 'glsl'))

    def test_all_volume_stage_bindings_and_dependent_str3d(self):
        key = textured_key(2)
        key.texture_modes = sum(2 << (5 * stage) for stage in range(4))
        key.sampler_type[:] = [2] * 4
        source = pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 0, 15))
        for stage in range(4):
            self.assertIn(f'volume_border_sampler{stage} [[sampler({stage + 4})]]', source)
            self.assertIn(f't{stage} = sample_volume_border{stage}', source)
        source = pixel_tests.PixelEmitterTests.emit_options(textured_key(13, 3), PixelMslOptionsV3(3, 0, 0, 8))
        self.assertIn('(float4(dot1, dot2, dot3, 1.0)).xyz', source)

    def test_disjoint_alpha_volume_and_depth_contracts_combine(self):
        key = textured_key(2, 1)
        key.texture_modes |= 1
        source = pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 1, 2))
        self.assertIn('alpha_border_sampler0 [[sampler(4)]]', source)
        self.assertIn('volume_border_sampler1 [[sampler(5)]]', source)
        self.assertEqual(source.count('[[sampler(4)]]'), 1)
        self.assertEqual(source.count('[[sampler(5)]]'), 1)
        # Sample2D at0 and3D at1 can precede DOT_PRODUCT at2/DOT_ZW at3.
        key.texture_modes = 1 | (2 << 5) | (17 << 10) | (10 << 15)
        key.combiner_state[56] = 0x110000
        source = pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 1, 1, 2))
        self.assertIn('float depth [[depth(any)]]', source)
        self.assertIn('(dot2 / dot3) * u.depth_scale', source)
        self.assertIn('sample_alpha_border0', source)
        self.assertIn('sample_volume_border1', source)
        self.assertIsNone(pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 1, 2)))

    def test_bad_masks_types_and_legacy_border_contracts_reject(self):
        key = textured_key(2, 1)
        for options in (PixelMslOptionsV3(4, 0, 0, 2), PixelMslOptionsV3(3, 2, 0, 2),
                        PixelMslOptionsV3(3, 0, 16, 2), PixelMslOptionsV3(3, 0, 0, 16),
                        PixelMslOptionsV3(3, 0, 2, 2)):
            self.assertIsNone(pixel_tests.PixelEmitterTests.emit_options(key, options))
        for mode, stage in ((0, 0), (1, 0), (3, 0), (4, 0), (5, 0), (17, 1), (9, 2)):
            self.assertIsNone(pixel_tests.PixelEmitterTests.emit_options(textured_key(mode, stage),
                                                             PixelMslOptionsV3(3, 0, 0, 1 << stage)))
        for field in ('border_axes', 'border_filter'):
            for value in (1, 2, 3):
                key = textured_key(2, 1)
                getattr(key, field)[1] = value
                self.assertIsNone(pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 0, 2)))
        # Alpha cannot be redirected to a volume stage even in version3.
        self.assertIsNone(pixel_tests.PixelEmitterTests.emit_options(textured_key(2, 1), PixelMslOptionsV3(3, 0, 2, 0)))

    def test_zero_masks_and_version3_alpha_are_byte_preserved(self):
        for key in compiler_cases().values():
            self.assertEqual(pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 0, 0)),
                             pixel_tests.PixelEmitterTests.emit(key))
        for mask in (1, 2, 4, 8, 15):
            key = textured_key()
            key.texture_modes = sum(1 << (5 * stage) for stage in range(4))
            self.assertEqual(pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, mask, 0)),
                             pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV2(2, 0, mask)))

    def test_exact_real_arithmetic_footprints_include_corners_axes_and_mip_blends(self):
        cases = 0
        for axes in (1, 2, 3, 4, 5, 6, 7):
            for fractions in itertools.product((F(0), F(1, 4), F(1, 2), F(1)), repeat=3):
                for mip_weight in (F(0), F(1, 4), F(1, 2), F(1)):
                    black = [F(0)] * 4
                    white = [F(0)] * 4
                    expected = [F(0)] * 4
                    border = [F(5, 255), F(70, 255), F(128, 255), F(1)]
                    for level, level_weight in enumerate((1 - mip_weight, mip_weight)):
                        for corner in itertools.product((0, 1), repeat=3):
                            weight = level_weight
                            outside = False
                            for axis, bit in enumerate(corner):
                                weight *= fractions[axis] if bit else 1 - fractions[axis]
                                outside |= bool((axes & (1 << axis)) and bit)
                            # Distinct varying interior RGBA and levels avoid a solid-color-only identity.
                            texel = [F((level * 71 + sum(corner) * 33 + channel * 47) % 256, 255)
                                     for channel in range(4)]
                            for channel in range(4):
                                black[channel] += weight * (0 if outside else texel[channel])
                                white[channel] += weight * (1 if outside else texel[channel])
                                expected[channel] += weight * (border[channel] if outside else texel[channel])
                    reconstructed = [b + c * (w - b) for b, w, c in zip(black, white, border)]
                    self.assertEqual(reconstructed, expected)
                    cases += 1
        self.assertEqual(cases, 1792)

    def test_versions_do_not_read_past_their_original_allocations(self):
        code = r'''
#include "xgpu_shader_standalone.h"
#include <sys/mman.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    unsigned char *memory = mmap(NULL, page * 2, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANON, -1, 0);
    if (memory == MAP_FAILED || mprotect(memory + page, page, PROT_NONE)) return 1;
    struct nv2a_pixel_shader_key key = {0};
    for (unsigned int version = 1; version <= 4; version++) {
        unsigned int words = version == 4 ? 2 : version + 1;
        unsigned int *p = (unsigned int *)(memory + page - words * 4);
        memset(p, 0, words * 4); p[0] = version;
        memset(&key, 0, sizeof(key));
        if (version == 1) p[1] = 1;
        if (version == 2) {p[2] = 1; key.texture_modes = 1; key.sampler_type[0] = 1;}
        if (version == 3) {p[3] = 1; key.texture_modes = 2; key.sampler_type[0] = 2;}
        char *s = nv2a_pixel_shader_to_msl_with_options(&key,
            (const struct nv2a_pixel_shader_msl_options *)p);
        if (version == 4 ? s != NULL : s == NULL) return 2;
        free(s);
    }
    munmap(memory, page * 2); return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='halo-metal-options-read-limit-') as tmp:
            source = Path(tmp) / 'guard.c'
            executable = Path(tmp) / 'guard'
            source.write_text(code)
            subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-DXGPU_SHADER_STANDALONE=1', '-DHALO_ANDROID=1', '-Iport/linux/src',
                            source, 'port/linux/src/nv2a_psh.c', 'port/macos/metal-poc/shader_text.c',
                            '-o', executable], cwd=ROOT, check=True)
            subprocess.run([executable], cwd=ROOT, check=True)

    def test_all126_original_draws_preserve_frozen_glsl_and_msl(self):
        baseline = ROOT / 'build/metal-poc/volume-border-emitter-cpu-proof/baseline.json'
        if not baseline.exists():
            self.skipTest('immutable original126-draw baseline is required')
        raw = baseline.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         'd6eb1a9c3c77006d23a7e6cfadea524703a185e7d39368f2437f9934999f5f4f')
        data = json.loads(raw)
        self.assertEqual(hashlib.sha256(Path(data['frame']).read_bytes()).hexdigest(), data['frame_sha256'])
        self.assertEqual(len(data['draws']), 126)
        for record in data['draws']:
            self.assertEqual(hashlib.sha256(Path(record['key_file']).read_bytes()).hexdigest(), record['key_sha256'])
            key = from_record(record['key'])
            with self.subTest(draw=record['draw']):
                for language in ('msl', 'glsl'):
                    self.assertEqual(hashlib.sha256(pixel_tests.PixelEmitterTests.emit(key, language).encode()).hexdigest(),
                                     record[language + '_sha256'])
                self.assertEqual(pixel_tests.PixelEmitterTests.emit_options(key, PixelMslOptionsV3(3, 0, 0, 0)),
                                 pixel_tests.PixelEmitterTests.emit(key))


if __name__ == '__main__':
    unittest.main()
