#!/usr/bin/env python3
"""Native NV2A emitter regressions; no game build or guest runtime required."""
import ctypes
import errno
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def instruction(mac=1, ilu=0, a=(2, 0), b=(1, 1), c=(1, 2),
                constant=58, vertex=7, temporary=0, mac_mask=15, ilu_mask=15,
                output=0, output_mask=15, output_from_ilu=False, relative=False,
                c_swizzle=(0, 1, 2, 3), c_negate=False, end=True):
    """Encode named NV2A fields independently of the production decoder."""
    word1 = (mac << 21) | (ilu << 25) | (constant << 13) | (vertex << 9) | 27
    word2 = (a[1] << 28) | (a[0] << 26) | (1 << 21) | (2 << 19) | (3 << 17)
    word2 |= (b[1] << 13) | (b[0] << 11) | (int(c_negate) << 10)
    word2 |= sum(value << bit for value, bit in zip(c_swizzle, (8, 6, 4, 2)))
    word2 |= c[1] >> 2
    word3 = ((c[1] & 3) << 30) | (c[0] << 28) | (mac_mask << 24)
    word3 |= (temporary << 20) | (ilu_mask << 16) | (output_mask << 12)
    word3 |= (1 << 11) | (output << 3) | (int(output_from_ilu) << 2)
    word3 |= (int(relative) << 1) | int(end)
    return [0, word1, word2, word3]


def opcode_program():
    program = []
    for mac in range(14):
        for ilu in range(8):
            program.extend(instruction(mac, ilu, a=(1, 4), b=(2, 0), c=(3, 0),
                                       output=(0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)[mac % 11],
                                       temporary=mac % 12, mac_mask=5, ilu_mask=10,
                                       output_from_ilu=bool(ilu), relative=bool(mac % 2), end=False))
    program.extend(instruction(0, 3, c=(1, 12), c_swizzle=(3, 3, 3, 3),
                               temporary=1, output_mask=0))
    return program


class VertexEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('clang'):
            raise unittest.SkipTest('native clang is required')
        cls.temporary = tempfile.TemporaryDirectory(prefix='halo-metal-vertex-')
        cls.directory = Path(cls.temporary.name)
        cls.libraries = {}
        for android in (False, True):
            library = cls.directory / ('vertex_es.dylib' if android else 'vertex_gl.dylib')
            command = ['clang', '-std=c11', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                       '-DXGPU_SHADER_STANDALONE=1', '-I', str(ROOT / 'port/linux/src')]
            if android:
                command.append('-DHALO_ANDROID=1')
            command.extend([str(ROOT / 'port/linux/src/nv2a_vsh.c'),
                            str(ROOT / 'port/macos/metal-poc/shader_text.c'), '-o', str(library)])
            subprocess.run(command, check=True, capture_output=True)
            loaded = ctypes.CDLL(str(library), use_errno=True)
            for name in ('nv2a_vertex_shader_to_glsl', 'nv2a_vertex_shader_to_msl'):
                function = getattr(loaded, name)
                function.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_ulong, ctypes.c_ulong]
                function.restype = ctypes.c_void_p
            cls.libraries[android] = loaded
        cls.libc = ctypes.CDLL(None)
        cls.libc.free.argtypes = [ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def translate(self, words, metal=True, packed=0, android=True):
        data = (ctypes.c_uint32 * len(words))(*words)
        function = getattr(self.libraries[android],
                           'nv2a_vertex_shader_to_msl' if metal else 'nv2a_vertex_shader_to_glsl')
        ctypes.set_errno(0)
        address = function(data, len(words) // 4, packed)
        if not address:
            return None
        result = ctypes.string_at(address).decode()
        self.libc.free(address)
        return result

    def test_glsl_output_is_unchanged(self):
        # Golden digests captured from the previous GLSL emitter for all
        # MAC/ILU pairs, masks, relative constants, packed inputs and RCC r12.
        expected = {
            False: '424a44ec6aafb0215fbe75c26f168b70779546bf4457e5406440d936bfb5fc16',
            True: '718a9590a5c9e0fddbaecf69a5a03993c472b6a1eefc7a14effe3291a616cb95',
        }
        for android, digest in expected.items():
            with self.subTest(android=android):
                text = self.translate(opcode_program(), metal=False, packed=5, android=android)
                self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), digest)

    def test_metal_abi_and_xbox_viewport(self):
        text = self.translate(instruction(), packed=5)
        self.assertIn('vertex XgpuVaryings xgpu_vertex', text)
        self.assertIn('constant XgpuVertexUniforms &uniforms [[buffer(0)]]', text)
        self.assertIn('uint v0_packed [[attribute(0)]]', text)
        self.assertIn('float4 v1_in [[attribute(1)]]', text)
        self.assertIn('unpack_normpacked3(input.v0_packed)', text)
        self.assertIn('0.5 + screen_offset, 0.5', text)
        self.assertIn('output.xD0 = clamp(oD0, 0.0, 1.0)', text)
        self.assertNotIn('gl_Position', text)
        self.assertNotIn('output.position.y = -', text)
        self.assertNotIn('2.0 * output.position.z', text)
        self.assertEqual(text, self.translate(instruction(), packed=5, android=False))

    def test_parallel_units_read_before_writing_and_ilu_uses_r1(self):
        text = self.translate(instruction(4, 1, a=(1, 0), b=(1, 1), c=(1, 2), temporary=4))
        self.assertLess(text.index('C = r2.xyzw'), text.index('r4.xyzw = mac.xyzw'))
        self.assertIn('r1.xyzw = ilu.xyzw', text)
        self.assertNotIn('r4.xyzw = ilu.xyzw', text)

    def test_clip_capture_requires_r12_w(self):
        for swizzle, negate, captured in [((3, 3, 3, 3), False, True),
                                           ((0, 0, 0, 0), False, False),
                                           ((3, 3, 3, 3), True, False)]:
            with self.subTest(swizzle=swizzle, negate=negate):
                text = self.translate(instruction(0, 3, c=(1, 12), c_swizzle=swizzle,
                                                  c_negate=negate, output_mask=0))
                self.assertEqual('clip_captured = true;' in text, captured)

    def test_invalid_consumed_fields_fail_instead_of_rendering_zero(self):
        invalid = [instruction(mac=14), instruction(a=(0, 0)), instruction(a=(1, 13)),
                   instruction(a=(3, 0), constant=192), instruction(temporary=13),
                   instruction(mac=0, ilu=1, temporary=13), instruction(output=2),
                   instruction(output=255)]
        constant_write = instruction()
        constant_write[3] &= ~(1 << 11)
        invalid.append(constant_write)
        for words in invalid:
            with self.subTest(words=words):
                self.assertIsNone(self.translate(words))
                self.assertEqual(ctypes.get_errno(), errno.EINVAL)
        self.assertIsNone(self.translate(instruction(), packed=1 << 16))
        self.assertIsNone(self.translate([]))

    def test_unused_fields_are_ignored_and_final_bit_stops_decoding(self):
        words = instruction(b=(0, 15), c=(0, 15))
        self.assertIn('B = float4(0.0)', self.translate(words))
        self.assertIsNotNone(self.translate(words + instruction(mac=15)))

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'),
                         'Apple Metal compiler is required')
    def test_all_opcodes_compile_as_native_metal(self):
        path = self.directory / 'opcodes.metal'
        path.write_text(self.translate(opcode_program(), packed=5))
        command = ['xcrun', '-sdk', 'macosx', 'metal', '-fno-fast-math', '-fpreserve-invariance', '-c', str(path),
                   '-o', str(self.directory / 'opcodes.air')]
        result = subprocess.run(command, capture_output=True, text=True)
        if 'missing Metal Toolchain' in result.stderr:
            # Xcode can omit the optional CLI toolchain while the native Metal
            # runtime compiler remains available. Validate through that API.
            source = self.directory / 'compile.mm'
            source.write_text(r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 2) return 2;
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) { fprintf(stderr, "No Metal device is available\n"); return 77; }
        NSError *error = nil;
        NSString *text = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]
                                                   encoding:NSUTF8StringEncoding error:&error];
        MTLCompileOptions *options = [MTLCompileOptions new];
        options.fastMathEnabled = NO;
        options.preserveInvariance = YES;
        id<MTLLibrary> library = [device newLibraryWithSource:text options:options error:&error];
        if (!library) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
        if (![library newFunctionWithName:@"xgpu_vertex"]) return 3;
        return 0;
    }
}
''')
            executable = self.directory / 'compile_metal'
            subprocess.run(['clang++', '-std=c++17', '-fobjc-arc', str(source),
                            '-framework', 'Foundation', '-framework', 'Metal',
                            '-o', str(executable)], check=True, capture_output=True)
            result = subprocess.run([str(executable), str(path)], capture_output=True, text=True)
            if result.returncode == 77:
                self.skipTest(result.stderr.strip())
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
