#!/usr/bin/env python3
"""Native fetch/topology tests for raw Xbox draw replay; no GPU or game."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('xcrun'), 'Native macOS fetch')
class NativeFetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='metal-draw-fetch-')
        cls.folder = Path(cls.temporary.name)
        source = cls.folder/'probe.mm'
        source.write_text('''#define main nativeDrawReplayMain
#include "''' + str(ROOT/'port/macos/metal-poc/draw_replay.mm') + '''"
#undef main
int main(int argc, const char **argv) { @autoreleasepool {
    require(argc == 3, @"probe manifest output");
    NSString *path = @(argv[1]);
    NSDictionary *manifest = [NSJSONSerialization JSONObjectWithData:readFile(path) options:0 error:nil];
    Resources resources = {path.stringByDeletingLastPathComponent, [NSMutableDictionary new]};
    if (manifest[@"compiler_probe"]) {
        printf("%u\\n", vertexFastMath(resources, manifest[@"compiler_probe"]) ? 1 : 0);
        return 0;
    }
    if (manifest[@"texture_probe"]) {
        bindTextures(nil, nil, resources, manifest[@"texture_probe"]);
        return 0;
    }
    Geometry g = geometry(resources, manifest);
    NSData *vertices = [NSData dataWithBytes:g.vertices.data() length:g.vertices.size()*sizeof(Inputs)];
    require([vertices writeToFile:@(argv[2]) atomically:YES], @"probe output");
    printf("%lu %lu %u", g.sourceVertexFirst, g.sourceVertexCount, g.packedMask);
    for (uint32_t i : g.indices) printf(" %u", i);
    printf("\\n"); return 0;
} }
''')
        cls.probe = cls.folder/'probe'
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-O0',
                        '-mmacosx-version-min=13.0', str(source), '-framework', 'Foundation',
                        '-framework', 'Metal', '-o', str(cls.probe)],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = self.folder/self._testMethodName
        self.case.mkdir()
        self.manifest = dict(vertex_declaration=dict(elements=[], packed_mask=0), vertex_streams=[],
                             fixed_attributes=[[0, 0, 0, 1] for _ in range(16)],
                             draw=dict(primitive='point', indexed=False, vertex_start=0, vertex_count=1))

    def payload(self, name, raw):
        (self.case/name).write_bytes(raw)
        return dict(file=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def stream(self, raw, stride, elements, offset=0, first=0):
        self.manifest['vertex_streams'] = [dict(self.payload('stream.bin', raw), stream=0,
                                               stride=stride, offset=offset, first_vertex=first)]
        self.manifest['vertex_declaration']['elements'] = [dict(register=reg, stream=0,
                                                                 offset=at, type=kind)
                                                           for reg, at, kind in elements]

    def replay(self, error=None):
        path, output = self.case/'input.json', self.case/'vertices.bin'
        path.write_text(json.dumps(self.manifest))
        result = subprocess.run([str(self.probe), str(path), str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1 if error else 0, result.stderr)
        if error:
            self.assertIn(error, result.stderr)
            return None
        return list(map(int, result.stdout.split())), output.read_bytes()

    @staticmethod
    def register(raw, vertex, reg):
        return struct.unpack_from('<4f', raw, vertex*256+reg*16)

    def test_original_decal_float3_normshort2_and_quad_order(self):
        # The original decal declaration uses a 16-byte stride. Signed UVs
        # include both normalized endpoints and an exactly positive half.
        raw = b''.join(struct.pack('<3f2h', i, i+1, i+2, u, v)
                       for i, (u, v) in enumerate([(-32768, 32767), (0, 16384),
                                                   (32767, -32768), (-1, 1)]))
        self.stream(raw, 16, [(0, 0, 0x32), (9, 12, 0x21)])
        self.manifest['draw'].update(primitive='quad', vertex_count=4)
        header, fetched = self.replay()
        self.assertEqual(header, [0, 4, 0, 0, 1, 2, 0, 2, 3])
        self.assertEqual(self.register(fetched, 2, 0), (2, 3, 4, 1))
        self.assertEqual(self.register(fetched, 0, 9), (-1, 1, 0, 1))
        self.assertAlmostEqual(self.register(fetched, 1, 9)[1], 16384/32767, places=7)

    def test_compiler_defaults_and_unknown_contracts_fail_closed(self):
        descriptor = dict(entry='xgpu_vertex')
        path = self.case/'compiler.json'
        def check(value, error=None):
            path.write_text(json.dumps(dict(compiler_probe=value)))
            result = subprocess.run([str(self.probe), str(path), str(self.case/'unused')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1 if error else 0, result.stderr)
            if error:
                self.assertIn(error, result.stderr)
            else:
                self.assertEqual(result.stdout.strip(), '0')
        check(descriptor)
        check(dict(descriptor, compiler_evidence={}), 'explicit contract')
        contract = dict(contract='angle_metal_invariant_fast_v1', fast_math=True,
                        preserve_invariance=True, math_mode='fast', floating_point_functions='fast')
        for field, value in [('contract','unknown'), ('fast_math',False),
                             ('preserve_invariance',False), ('math_mode','safe'),
                             ('floating_point_functions','precise'), ('extra',True)]:
            with self.subTest(field=field):
                check(dict(descriptor, compile_options=dict(contract, **{field:value})),
                      'shader compiler contract')
        check(dict(entry='xgpu_fragment',compile_options=contract), 'shader compiler contract')
        check(dict(descriptor,compile_options=contract), 'resource descriptor')

    def test_original_packed_normal_bits_reach_uint_attribute_unchanged(self):
        bits = 0xFFF80001  # Deliberately looks nonfinite when treated as float.
        self.stream(struct.pack('<I', bits), 4, [(1, 0, 0x16)])
        self.manifest['vertex_declaration']['packed_mask'] = 2
        header, fetched = self.replay()
        self.assertEqual(header[:3], [0, 1, 2])
        self.assertEqual(struct.unpack_from('<I', fetched, 16)[0], bits)

    def test_unvalidated_bc2_bc3_cube_formats_remain_rejected(self):
        path = self.case/'cube.json'
        for format_name in ('bc2_rgba','bc3_rgba'):
            with self.subTest(format=format_name):
                descriptor = dict(slot=3,type='cube',pixel_format=format_name,width=64,height=64)
                path.write_text(json.dumps(dict(texture_probe=[None,None,None,descriptor])))
                result = subprocess.run([str(self.probe),str(path),str(self.case/'unused')],
                                        capture_output=True,text=True)
                self.assertEqual(result.returncode,1)
                self.assertIn('BC2/BC3 cube replay has not been validated',result.stderr)

    def test_fixed_registers_and_unbound_streams_use_captured_values(self):
        self.manifest['fixed_attributes'][4] = [.25, .5, .75, 1]
        self.manifest['vertex_declaration']['elements'] = [dict(register=4, stream=1, offset=0, type=0x42)]
        _, fetched = self.replay()
        self.assertEqual(self.register(fetched, 0, 4), (.25, .5, .75, 1))

    def test_unaligned_short_and_bgra_color_fetch(self):
        raw = bytes([10, 20, 30, 40])+bytes(26)+struct.pack('<h', -1234)
        self.stream(raw, 32, [(4, 0, 0x40), (8, 30, 0x15)])
        _, fetched = self.replay()
        for got, expected in zip(self.register(fetched, 0, 4), [30/255, 20/255, 10/255, 40/255]):
            self.assertAlmostEqual(got, expected, places=7)
        self.assertEqual(self.register(fetched, 0, 8), (-1234, 0, 0, 1))

    def test_captured_window_origin_base_vertex_and_index_offset(self):
        raw = b'prefix!!'+struct.pack('<3f', 100, 101, 102)+struct.pack('<3f', 200, 201, 202)
        self.stream(raw, 12, [(0, 0, 0x32)], offset=8, first=5)
        self.manifest['draw'] = dict(primitive='line', indexed=True, base_vertex=5, index_count=2,
                                    index_type='uint16', index_offset_bytes=2,
                                    index_buffer=self.payload('indices.bin', struct.pack('<3H', 99, 1, 0)))
        header, fetched = self.replay()
        self.assertEqual(header, [5, 2, 0, 1, 0])
        self.assertEqual(self.register(fetched, 0, 0), (100, 101, 102, 1))
        self.assertEqual(self.register(fetched, 1, 0), (200, 201, 202, 1))

    def test_constant_stride_zero_and_partial_component_defaults(self):
        self.stream(struct.pack('<f', .125), 0, [(2, 0, 0x12)])
        self.manifest['draw'].update(primitive='line', vertex_start=100, vertex_count=2)
        _, fetched = self.replay()
        self.assertEqual(self.register(fetched, 0, 2), (.125, 0, 0, 1))
        self.assertEqual(self.register(fetched, 1, 2), (.125, 0, 0, 1))

    def test_out_of_bounds_fetch_and_unknown_format_fail_closed(self):
        self.stream(bytes(16), 16, [(0, 0, 0x32)])
        self.manifest['draw']['vertex_count'] = 2
        self.replay('Vertex fetch exceeds')
        self.manifest['vertex_declaration']['elements'][0]['type'] = 0x99
        self.replay('Unsupported Xbox vertex attribute')

    def test_packed_mask_mismatch_and_changed_raw_bytes_reject(self):
        self.stream(bytes(4), 4, [(1, 0, 0x16)])
        self.replay('packed masks differ')
        self.manifest['vertex_declaration']['packed_mask'] = 2
        (self.case/'stream.bin').write_bytes(b'edit')
        self.replay('Resource hash mismatch')


if __name__ == '__main__':
    unittest.main()
