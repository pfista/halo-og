#!/usr/bin/env python3
"""Direct Xbox pixel shader emitter checks; no game, GL context or app install.

Run python3 tools/test_metal_pixel_shader.py. The --emit-cases DIRECTORY option
also saves representative MSL for a native Metal compiler/parity harness.
"""

import argparse
import ctypes
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PixelKey(ctypes.Structure):
    _fields_ = [
        ("combiner_state", ctypes.c_uint32 * 57),
        ("texture_modes", ctypes.c_uint32),
        ("sampler_type", ctypes.c_ubyte * 4),
        ("alpha_kill", ctypes.c_ubyte * 4),
        ("color_sign", ctypes.c_ubyte * 4),
        ("border_axes", ctypes.c_ubyte * 4),
        ("border_filter", ctypes.c_ubyte * 4),
        ("alpha_test_function", ctypes.c_ulong),
        ("fog_enable", ctypes.c_ubyte),
        ("fog_table_mode", ctypes.c_ubyte),
        ("count_samples", ctypes.c_ubyte),
        ("coverage_alpha", ctypes.c_ubyte),
    ]


class PixelMslOptions(ctypes.Structure):
    _fields_ = [('version', ctypes.c_uint32), ('depth_contract', ctypes.c_uint32)]

class PixelMslOptionsV2(ctypes.Structure):
    _fields_ = PixelMslOptions._fields_ + [('native_alpha_border_mask', ctypes.c_uint32)]


def textured_key(mode=1, stage=0):
    key = PixelKey()
    key.texture_modes = mode << (5 * stage)
    key.combiner_state[53] = 1
    # v0 * t0 -> r0, independently for RGB and alpha.
    key.combiner_state[34] = 0x04082000
    key.combiner_state[45] = 0xC0
    key.combiner_state[0] = 0x14182000
    key.combiner_state[26] = 0xC0
    # final RGB = r0, alpha = r0.a.
    key.combiner_state[8] = 0x0C200000
    key.combiner_state[9] = 0x00001C00
    for index in range(4):
        key.sampler_type[index] = 1
    key.sampler_type[stage] = (
        3 if mode in (3, 11, 12, 14, 18) else 2 if mode in (2, 13) else 1
    )
    if mode == 9 and stage >= 2:
        key.texture_modes |= 17 << (5 * (stage - 1))
    elif mode in (11, 12, 13, 14):
        key.texture_modes |= 17 << 5
        if mode == 11:
            key.texture_modes |= 12 << 15
            key.sampler_type[3] = 3
        else:
            key.texture_modes |= 17 << 10
    return key


def compiler_cases():
    cases = {}
    for mode, stage in (
        (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 1),
        (7, 1), (9, 2), (11, 2), (12, 3), (13, 3), (14, 3),
        (15, 2), (16, 2), (17, 1),
    ):
        key = textured_key(mode, stage)
        key.fog_enable = 1
        key.fog_table_mode = stage % 4
        key.alpha_test_function = 516
        key.color_sign[stage] = 0 if mode == 7 else 15
        key.alpha_kill[stage] = 1
        cases[f"texture-mode-{mode}"] = key
    for filtering in range(4):
        key = textured_key()
        key.border_axes[0] = 3
        key.border_filter[0] = filtering
        cases[f"border-filter-{filtering}"] = key
    for mapping in (0, 8, 16, 24, 32, 48):
        key = textured_key()
        key.combiner_state[53] |= 0x11100
        key.combiner_state[34] = 0x0122C405
        key.combiner_state[45] |= (mapping | 0xC4) << 12
        key.coverage_alpha = 1
        cases[f"combiner-map-{mapping}"] = key
    return cases


class PixelEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-metal-pixel-test-")
        cls.library_path = Path(cls.temporary.name) / "pixel.dylib"
        subprocess.run(
            ["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-dynamiclib",
             "-DXGPU_SHADER_STANDALONE=1", "-DHALO_ANDROID=1", "-Iport/linux/src",
             "port/linux/src/nv2a_psh.c", "port/macos/metal-poc/shader_text.c",
             "-o", str(cls.library_path)], cwd=ROOT, check=True,
        )
        cls.library = ctypes.CDLL(str(cls.library_path))
        cls.library.nv2a_pixel_shader_to_msl.argtypes = [ctypes.POINTER(PixelKey)]
        cls.library.nv2a_pixel_shader_to_msl.restype = ctypes.c_void_p
        cls.library.nv2a_pixel_shader_to_glsl.argtypes = [ctypes.POINTER(PixelKey)]
        cls.library.nv2a_pixel_shader_to_glsl.restype = ctypes.c_void_p
        cls.library.nv2a_pixel_shader_to_msl_with_options.argtypes = [ctypes.POINTER(PixelKey), ctypes.c_void_p]
        cls.library.nv2a_pixel_shader_to_msl_with_options.restype = ctypes.c_void_p
        cls.libc = ctypes.CDLL(None)
        cls.libc.free.argtypes = [ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def emit(cls, key, language="msl"):
        function = getattr(cls.library, f"nv2a_pixel_shader_to_{language}")
        result = function(ctypes.byref(key) if key is not None else None)
        if not result:
            return None
        source = ctypes.string_at(result).decode()
        cls.libc.free(result)
        return source

    @classmethod
    def emit_options(cls, key, options):
        result = cls.library.nv2a_pixel_shader_to_msl_with_options(ctypes.byref(key), ctypes.byref(options))
        if not result:
            return None
        source = ctypes.string_at(result).decode(); cls.libc.free(result)
        return source

    def test_direct_metal_samples_and_uniforms(self):
        source = self.emit(textured_key())
        self.assertIn("fragment XgpuFragmentResult xgpu_fragment", source)
        self.assertIn("uint sample_mask [[sample_mask]]", source)
        self.assertIn("clamp(result, 0.0, 1.0), 0xffffffffu", source)
        self.assertIn("tex0.sample(sampler0", source)
        self.assertIn("u.texture_scale[0].xy, bias(u.texture_lod_bias[0])", source)
        self.assertIn("constant XgpuPixelUniforms &u [[buffer(0)]]", source)
        self.assertNotIn("#version", source)
        self.assertNotIn("texture(tex", source)
        self.assertNotIn("uniform vec", source)

    def test_register_portions_read_before_write(self):
        source = self.emit(textured_key())
        self.assertLess(source.index("float aA"), source.index("r0.rgb = cAB"))
        self.assertIn("float4 r0 = float4(0.0, 0.0, 0.0, t0.a)", source)
        self.assertIn("clamp((cAB), -1.0, 1.0)", source)

    def test_alpha_test_matches_eight_bit_reference(self):
        key = textured_key()
        key.alpha_test_function = 516
        key.alpha_kill[0] = 1
        source = self.emit(key)
        self.assertIn("if (t0.a == 0.0) discard_fragment()", source)
        self.assertIn("floor(clamp(result.a, 0.0, 1.0) * 255.0 + 0.5) > u.alpha_reference", source)

    def test_declares_texture_dimension_from_key(self):
        for mode, dimension in ((1, "texture2d"), (2, "texture3d"), (3, "texturecube")):
            self.assertIn(f"{dimension}<float> tex0", self.emit(textured_key(mode)))

    def test_representative_supported_states_emit(self):
        for name, key in compiler_cases().items():
            with self.subTest(name=name):
                self.assertIsNotNone(self.emit(key))

    def test_unsupported_states_fail_closed(self):
        self.assertIsNone(self.emit(None))
        for mode in (8, 10, 18, 19, 31):
            self.assertIsNone(self.emit(textured_key(mode, 1)))
        key = textured_key()
        key.sampler_type[0] = 0
        self.assertIsNone(self.emit(key))
        key = textured_key(17, 1)
        key.combiner_state[55] = 4
        self.assertIsNone(self.emit(key))
        key = textured_key()
        key.count_samples = 1
        self.assertIsNone(self.emit(key))
        key = textured_key()
        key.combiner_state[53] = 9
        self.assertIsNone(self.emit(key))
        key = textured_key()
        key.combiner_state[34] = 0x06000000
        self.assertIsNone(self.emit(key))
        key = textured_key(9, 1)
        self.assertIsNone(self.emit(key))
        key = textured_key(1)
        key.sampler_type[0] = 3
        self.assertIsNone(self.emit(key))
        key = textured_key(17, 1)
        key.texture_modes |= 1
        key.color_sign[0] = 8
        self.assertIsNone(self.emit(key))
        key = textured_key(7, 2)
        key.texture_modes |= 1
        key.color_sign[0] = 2
        self.assertIsNone(self.emit(key))
        key = textured_key(7, 2)
        key.color_sign[2] = 1
        self.assertIsNone(self.emit(key))

    def test_glsl_emitter_still_uses_glsl(self):
        source = self.emit(textured_key(), "glsl")
        self.assertIn("texture(tex0", source)
        self.assertIn("layout(location = 0) out vec4 fragment_color", source)
        self.assertNotIn("xgpu_fragment", source)

    def test_inconsistent_dot_chains_fail_closed(self):
        for mode, stage, predecessor in ((9, 2, 1), (9, 3, 2), (11, 2, 1),
                                         (12, 3, 1), (12, 3, 2), (13, 3, 1),
                                         (13, 3, 2), (14, 3, 1), (14, 3, 2)):
            key = textured_key(mode, stage)
            key.texture_modes &= ~(31 << (5 * predecessor))
            with self.subTest(mode=mode, predecessor=predecessor):
                self.assertIsNone(self.emit(key))
        key = textured_key(11, 2)
        key.texture_modes &= ~(31 << 15)
        self.assertIsNone(self.emit(key))

    def test_depth_replace_requires_explicit_d24_contract(self):
        key = PixelKey(); key.texture_modes = 0x54421
        key.sampler_type[0] = key.sampler_type[1] = 1
        key.combiner_state[56] = 0x110000
        self.assertIsNone(self.emit(key))
        function = self.library.nv2a_pixel_shader_to_msl_with_options
        for version, contract in ((0, 1), (4, 1), (1, 0), (1, 2), (1, 43)):
            options = PixelMslOptions(version, contract)
            self.assertFalse(function(ctypes.byref(key), ctypes.byref(options)))
            ordinary_key = textured_key()
            self.assertFalse(function(ctypes.byref(ordinary_key), ctypes.byref(options)))
        options = PixelMslOptions(1, 1)
        pointer = function(ctypes.byref(key), ctypes.byref(options))
        self.assertTrue(pointer)
        source = ctypes.string_at(pointer).decode(); self.libc.free(pointer)
        self.assertIn('float depth [[depth(any)]]', source)
        self.assertIn('uint sample_mask [[sample_mask]]', source)
        self.assertIn('(dot2 / dot3) * u.depth_scale', source)
        self.assertIn('replacement_depth < u.depth_clip_min', source)
        self.assertIn('clamp(result, 0.0, 1.0), 0xffffffffu, replacement_depth', source)
        key.texture_modes &= ~(31 << 10)
        self.assertFalse(function(ctypes.byref(key), ctypes.byref(options)))

    def test_alpha_border_options_preserve_legacy_and_zero_mask_output(self):
        for key in compiler_cases().values():
            expected = self.emit(key)
            self.assertEqual(self.emit_options(key, PixelMslOptionsV2(2, 0, 0)), expected)
            # Keep the actual original8-byte options allocation covered.
            self.assertEqual(self.emit_options(key, PixelMslOptions(1, 1)), expected)

    def test_alpha_border_pair_precedes_signed_alpha_kill_and_combiner(self):
        key = textured_key(); key.alpha_kill[0] = 1; key.color_sign[0] = 1
        source = self.emit_options(key, PixelMslOptionsV2(2, 0, 1))
        self.assertIn('sampler alpha_border_sampler0 [[sampler(4)]]', source)
        self.assertNotIn('alpha_border_sampler1', source)
        self.assertIn('float4 b = tex.sample(black_sampler, uv, bias(u.texture_lod_bias[0]))', source)
        self.assertIn('float4 o = tex.sample(opaque_sampler, uv, bias(u.texture_lod_bias[0]))', source)
        self.assertIn('return float4(b.rgb, b.a + u.texture_border_color[0].a * (o.a - b.a))', source)
        self.assertIn('t0 = sample_alpha_border0(tex0, sampler0, alpha_border_sampler0, u, (float4(xT0.xyz / (xT0.w != 0.0 ? xT0.w : 1.0), 1.0)).xy * u.texture_scale[0].xy)', source)
        self.assertLess(source.index('t0 = sample_alpha_border0'), source.index('t0.a = signed_byte(t0.a)'))
        self.assertLess(source.index('t0.a = signed_byte(t0.a)'), source.index('if (t0.a == 0.0) discard_fragment()'))
        self.assertIn('uint sample_mask [[sample_mask]]', source)
        self.assertNotIn('sample_alpha_border', self.emit(key, 'glsl'))

    def test_alpha_border_all_four_stage_bindings(self):
        key = textured_key(); key.texture_modes = sum(1 << (5 * stage) for stage in range(4))
        source = self.emit_options(key, PixelMslOptionsV2(2, 0, 15))
        for stage in range(4):
            self.assertIn(f'alpha_border_sampler{stage} [[sampler({stage + 4})]]', source)
            self.assertIn(f't{stage} = sample_alpha_border{stage}', source)

    def test_alpha_border_unknown_or_conflicting_contract_rejects(self):
        key = textured_key()
        for options in (PixelMslOptionsV2(2, 2, 1), PixelMslOptionsV2(2, 0, 16), PixelMslOptionsV2(4, 0, 1)):
            self.assertIsNone(self.emit_options(key, options))
        for mode, stage in ((0, 0), (2, 0), (3, 0), (4, 0), (5, 0), (17, 1)):
            self.assertIsNone(self.emit_options(textured_key(mode, stage), PixelMslOptionsV2(2, 0, 1 << stage)))
        for field in ('border_axes', 'border_filter'):
            key = textured_key(); getattr(key, field)[0] = 1
            self.assertIsNone(self.emit_options(key, PixelMslOptionsV2(2, 0, 1)))

    def test_alpha_border_v2_depth_contract_remains_explicit(self):
        key = PixelKey(); key.texture_modes = 0x54421
        key.sampler_type[0] = key.sampler_type[1] = 1
        key.combiner_state[56] = 0x110000
        self.assertIsNone(self.emit_options(key, PixelMslOptionsV2(2, 0, 1)))
        source = self.emit_options(key, PixelMslOptionsV2(2, 1, 1))
        self.assertIn('float depth [[depth(any)]]', source)
        self.assertIn('sample_alpha_border0', source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-cases", type=Path)
    options, unittest_arguments = parser.parse_known_args()
    if options.emit_cases:
        PixelEmitterTests.setUpClass()
        try:
            options.emit_cases.mkdir(parents=True, exist_ok=True)
            for name, key in compiler_cases().items():
                (options.emit_cases / f"{name}.metal").write_text(PixelEmitterTests.emit(key))
            print(f"Wrote {len(compiler_cases())} representative Metal pixel shaders")
        finally:
            PixelEmitterTests.tearDownClass()
    else:
        unittest.main(argv=[__file__, *unittest_arguments])
