#!/usr/bin/env python3
"""Validate CPU vertex fetch against source rules and immutable original draws.

Captured comparisons read the already-executed ILP32 wire packet vertex/index
payloads, rather than regenerating an oracle using today's Python importer.
The configured ILP32 toolchain check is in check_metal_vertex_fetch_ilp32.py.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'port/linux/src/metal_vertex_fetch.c'
HEADER = SOURCE.with_suffix('.h')
FRAME = ROOT/'build/metal-reference-20261004/ordered-frame-runtime/run/saves/metal-frames/frame420/captured_frame.json'
FRAME_SHA = '75f256ed7d40324d24cfb754e93248699defdcdc89d3f60d271dc9482ff115ac'
WIRE = ROOT/'build/metal-poc/host-frame-attachments-ready'
WIRE_FIXTURE_SHA = '884ea78898c2cec27b655af8ce3c5a394ba4fa0be02f50b113e66bab098de175'
BYTES = {0x02:0, 0x12:4, 0x22:8, 0x32:12, 0x42:16, 0x72:12,
         0x40:4, 0x16:4, 0x11:2, 0x21:4, 0x31:6, 0x41:8,
         0x15:2, 0x25:4, 0x35:6, 0x45:8, 0x14:1, 0x24:2, 0x34:3, 0x44:4}
OK, INVALID, UNSUPPORTED, BOUNDS = 0, -1, -2, -3


class Element(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('reg','stream','type','bytes','offset')]


class Declaration(C.Structure):
    _fields_ = [('element_count',C.c_uint32),('packed_mask',C.c_uint32),('elements',Element*16)]


class Stream(C.Structure):
    _fields_ = [('pointer',C.c_void_p),('byte_count',C.c_size_t),('stride',C.c_uint32)]


class Plan(C.Structure):
    _fields_ = [(name,C.c_uint32) for name in ('source_first','source_count','index_count','wire_primitive')]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def declaration(elements):
    result = Declaration()
    result.element_count = len(elements)
    for i, (reg, stream, kind, offset) in enumerate(elements):
        result.elements[i] = Element(reg,stream,kind,BYTES[kind],offset)
        if kind == 0x16:
            result.packed_mask |= 1 << reg
    return result


def reconstruct_tokens(elements):
    """Convert captured normalized offsets back to bounded stream/skip tokens.

    Actual original declaration token words are not recorded in frame420; this
    parser check validates the normalized source fields, not missing token bytes.
    """
    tokens, offsets = [], [0]*16
    for reg, stream, kind, offset in elements:
        tokens.append(0x20000000 | stream)
        assert offset >= offsets[stream]
        gap = offset-offsets[stream]
        while gap:
            n = min(gap,15)
            tokens.append(0x58000000 | n << 16)
            gap -= n
        tokens.append(0x40000000 | kind << 16 | reg)
        offsets[stream] = offset + BYTES[kind]
    return tokens + [0xffffffff]


class VertexFetchTests(unittest.TestCase):
    captured_summary = None

    @classmethod
    def setUpClass(cls):
        if not shutil.which('clang'):
            raise unittest.SkipTest('clang is required')
        cls.temp = tempfile.TemporaryDirectory(prefix='halo-native-vertex-fetch-')
        cls.directory = Path(cls.temp.name)
        cls.library_path = cls.directory/'fetch.dylib'
        subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                        '-DHALO_MACOS_NATIVE_METAL=1',SOURCE,'-o',cls.library_path],check=True,capture_output=True)
        cls.lib = C.CDLL(str(cls.library_path))
        cls.lib.metal_vertex_declaration_parse.argtypes = [C.c_void_p,C.c_size_t,C.POINTER(Declaration)]
        cls.lib.metal_vertex_fetch.argtypes = [C.POINTER(Declaration),C.POINTER(Stream),C.c_void_p,
            C.c_uint32,C.c_uint32,C.c_void_p,C.c_size_t]
        for name in ('metal_vertex_index_plan','metal_vertex_indices'):
            getattr(cls.lib,name).argtypes = [C.c_uint32,C.c_void_p,C.c_size_t,C.c_uint32,C.c_uint32,C.c_uint32] + \
                ([C.c_void_p,C.c_size_t,C.POINTER(Plan)] if name.endswith('indices') else [C.POINTER(Plan)])
            getattr(cls.lib,name).restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def parse(self,tokens):
        data = C.create_string_buffer(struct.pack('<'+'I'*len(tokens),*tokens) if tokens else b'')
        result = Declaration()
        C.memset(C.byref(result),0xa7,C.sizeof(result))
        status = self.lib.metal_vertex_declaration_parse(data,len(tokens),C.byref(result))
        return status,result

    def fetch(self,d,stream_values,count=1,first=0,fixed=None,capacity=None,output_offset=4):
        fixed = fixed if fixed is not None else struct.pack('<64f',*[float(i)+.25 for i in range(64)])
        keep = [C.create_string_buffer(fixed,256)]
        streams = (Stream*16)()
        for slot,data,stride in stream_values:
            # Every source is deliberately unaligned, so the API must not use
            # typed loads even when source FLOAT4/uint32 happens to be aligned.
            memory = C.create_string_buffer(b'x'+data,len(data)+1)
            keep.append(memory)
            streams[slot] = Stream(C.addressof(memory)+1,len(data),stride)
        size = count*256
        # Offset 4 is float-aligned but deliberately not 16-byte aligned.
        # Offsets 1--3 exercise arbitrary byte-buffer output via the fallback.
        out = C.create_string_buffer(bytes([0xa7])*(size+64),size+64)
        offset = 16 + (-C.addressof(out) % 16) + output_offset
        status = self.lib.metal_vertex_fetch(C.byref(d),streams,keep[0],first,count,
            C.byref(out,offset),size if capacity is None else capacity)
        self.assertEqual((C.addressof(out)+offset)%16,output_offset)
        self.assertEqual(out.raw[:offset],bytes([0xa7])*offset)
        self.assertEqual(out.raw[size+offset:],bytes([0xa7])*(64-offset))
        if status:
            self.assertEqual(out.raw,bytes([0xa7])*(size+64))
        return status,out.raw[offset:offset+size]

    def indices(self,primitive,values=None,count=None,first=0,base=0,capacity=None):
        data = struct.pack('<'+'H'*len(values),*values) if values is not None else None
        source = C.create_string_buffer(data,len(data)) if data else None
        count = len(values) if values is not None and count is None else count
        plan = Plan()
        status = self.lib.metal_vertex_index_plan(primitive,source,len(data) if data else 0,
            count,first,base,C.byref(plan))
        if status:
            return status,plan,b''
        size = plan.index_count*4
        out = C.create_string_buffer(bytes([0xa7])*(size+32),size+32)
        written = Plan()
        status = self.lib.metal_vertex_indices(primitive,source,len(data) if data else 0,count,first,base,
            C.byref(out,16),size if capacity is None else capacity,C.byref(written))
        self.assertEqual(out.raw[:16],bytes([0xa7])*16)
        self.assertEqual(out.raw[size+16:],bytes([0xa7])*16)
        if status:
            self.assertEqual(out.raw,bytes([0xa7])*(size+32))
        else:
            self.assertEqual(bytes(plan),bytes(written))
        return status,plan,out.raw[16:16+size]

    def test_declaration_stream_offsets_skips_constants_and_failures(self):
        tokens = [0x20000002,0x40320000,0x50020000,0x40210008,0x20000001,
                  0x40400003,0x58030000,0x40720009,0x20000002,0x40160004,
                  0x82000000,0xffffffff,0,0,0,0xffffffff]
        status,d = self.parse(tokens)
        self.assertEqual(status,OK)
        self.assertEqual([(e.reg,e.stream,e.type,e.bytes,e.offset) for e in d.elements[:d.element_count]],
            [(0,2,0x32,12,0),(8,2,0x21,4,20),(3,1,0x40,4,0),(9,1,0x72,12,7),(4,2,0x16,4,24)])
        self.assertEqual(d.packed_mask,16)
        for tokens,expected in [([],BOUNDS),([0x40320000],BOUNDS),
            ([0x40320010,0xffffffff],INVALID),([0x40320000,0x40320000,0xffffffff],INVALID),
            ([0x40730000,0xffffffff],UNSUPPORTED),([0x60000000,0xffffffff],UNSUPPORTED),
            ([0xa0000000,0xffffffff],UNSUPPORTED),([0x30000000,0xffffffff],UNSUPPORTED),
            ([0x82000000,0,0,0xffffffff],BOUNDS),([0x50010001,0xffffffff],INVALID)]:
            with self.subTest(tokens=tokens):
                status,d = self.parse(tokens)
                self.assertEqual(status,expected)
                self.assertEqual(bytes(d),bytes([0xa7])*C.sizeof(d))

    def test_all_twenty_fetch_formats_and_original_component_defaults(self):
        # Hand-built source/expected records; no production importer oracle.
        for kind in BYTES:
            if not BYTES[kind]:
                continue
            components = 3 if kind == 0x72 else kind >> 4
            expected = [0.,0.,0.,1.]
            if kind == 0x16:
                data = struct.pack('<I',0xffc12345)
                golden = data+struct.pack('<3f',0,0,1)
            elif kind == 0x40:
                data = bytes([19,85,201,254])
                golden = struct.pack('<4f',201/255,85/255,19/255,254/255)
            elif kind & 15 == 2:
                data = struct.pack('<4I',0x80000000,0x3f234567,0x00000001,0x7f800000)[:BYTES[kind]]
                golden = data+struct.pack('<4f',0,0,0,1)[len(data):]
            elif kind & 15 in (1,5):
                values = [-32768,-32767,1,32767][:components]
                data = struct.pack('<'+'h'*components,*values)
                expected[:components] = [max(-1,v/32767) if kind & 15 == 1 else v for v in values]
                golden = struct.pack('<4f',*expected)
            else:
                values = [0,1,127,255][:components]
                data = bytes(values)
                expected[:components] = [v/255 for v in values]
                golden = struct.pack('<4f',*expected)
            with self.subTest(kind=kind):
                reference = None
                for output_offset in (4,1,2,3):
                    with self.subTest(output_offset=output_offset):
                        status,out = self.fetch(declaration([(6,0,kind,0)]),[(0,data,0)],
                            output_offset=output_offset)
                        self.assertEqual(status,OK)
                        self.assertEqual(out[6*16:7*16],golden)
                        self.assertEqual(out[:6*16],struct.pack('<24f',*[float(i)+.25 for i in range(24)]))
                        if reference is None:
                            reference = out
                        self.assertEqual(out,reference)

    def test_fixed_missing_packed_zero_and_zero_stride(self):
        d = declaration([(2,0,0x16,0),(5,1,0x02,0),(6,2,0x22,1)])
        # Untouched fixed registers must retain payload/signaling NaN, signed
        # zero, subnormal and infinity bits, without float canonicalization.
        bits = [0x7fc12345,0x7fa12345,0x80000000,0x00000001,0x7f800000,0xff800000,0xffffffff,0]
        fixed = struct.pack('<64I',*(bits*8))
        expected = bytearray(fixed)
        expected[2*16:3*16] = bytes(16)
        expected[6*16:7*16] = struct.pack('<4f',1.5,-2.5,0,1)
        for output_offset in (4,1,2,3):
            with self.subTest(output_offset=output_offset):
                status,out = self.fetch(d,[(2,b'x'+struct.pack('<2f',1.5,-2.5),0)],
                    count=3,first=700,fixed=fixed,output_offset=output_offset)
                self.assertEqual(status,OK)
                self.assertEqual(out,bytes(expected)*3)

    def test_multistream_nonzero_first_and_padded_unaligned_stride(self):
        positions = b''.join(b'p'+struct.pack('<3f',*v)+b'pad!' for v in ((1,2,3),(4,5,6),(7,8,9)))
        shorts = b''.join(b'pad'+struct.pack('<h',v)+b'zz' for v in (-32768,-16384,32767))
        d = declaration([(0,0,0x32,1),(9,3,0x11,3)])
        status,out = self.fetch(d,[(0,positions,17),(3,shorts,7)],count=2,first=1)
        self.assertEqual(status,OK)
        self.assertEqual(out[:16],struct.pack('<4f',4,5,6,1))
        self.assertEqual(out[256:272],struct.pack('<4f',7,8,9,1))
        self.assertEqual(out[9*16:10*16],struct.pack('<4f',-16384/32767,0,0,1))
        self.assertEqual(out[256+9*16:256+10*16],struct.pack('<4f',1,0,0,1))

    def test_fetch_preflight_bounds_alias_and_declaration_integrity(self):
        d = declaration([(0,0,0x32,0),(15,1,0x42,3)])
        streams = [(0,struct.pack('<9f',*range(9)),12),(1,b'x'*31,16)]
        for output_offset in (4,1,2,3):
            for count,first,capacity in [(2,0,None),(1,0,255),(1,0xffffffff,None),(2,0xffffffff,None)]:
                with self.subTest(output_offset=output_offset,count=count,first=first,capacity=capacity):
                    self.assertEqual(self.fetch(d,streams,count,first,capacity=capacity,
                        output_offset=output_offset)[0],BOUNDS)
            d.elements[1].bytes = 12
            self.assertEqual(self.fetch(d,streams,output_offset=output_offset)[0],INVALID)
            d.elements[1].bytes = 16; d.packed_mask = 1
            self.assertEqual(self.fetch(d,streams,output_offset=output_offset)[0],INVALID)
            d.packed_mask = 0
        d = declaration([(0,0,0x42,0)])
        memory = C.create_string_buffer(bytes([0x55])*512,512)
        fixed = C.create_string_buffer(bytes(256),256)
        s = (Stream*16)(); s[0] = Stream(C.addressof(memory),512,16)
        before = memory.raw
        for output_offset in (4,1,2,3):
            self.assertEqual(self.lib.metal_vertex_fetch(C.byref(d),s,fixed,0,1,
                C.byref(memory,output_offset),256),INVALID)
            self.assertEqual(memory.raw,before)

    def test_all_original_primitive_order_and_rebase(self):
        values = [15,4,19,6,8,12,7,2]
        cases = [(1,values,values,0),(2,values,values,1),
            (3,values,values+[15],2),(4,values,values,2),
            (5,values[:6],values[:6],3),(6,values,values,4),
            (7,values,[v for i in range(1,7) for v in (15,values[i],values[i+1])],3),
            (8,values,[15,4,19,15,19,6,8,12,7,8,7,2],3),
            (9,values,values,4),(10,values,[v for i in range(1,7) for v in (15,values[i],values[i+1])],3)]
        for primitive,source,golden,wire in cases:
            with self.subTest(primitive=primitive):
                status,plan,out = self.indices(primitive,source,base=503)
                self.assertEqual(status,OK)
                self.assertEqual((plan.source_first,plan.source_count,plan.wire_primitive),
                    (503+min(source),max(source)-min(source)+1,wire))
                self.assertEqual(out,struct.pack('<'+'I'*len(golden),*[i-min(source) for i in golden]))
        self.assertEqual(self.indices(8,count=4,first=100000)[2],struct.pack('<6I',0,1,2,0,2,3))
        # Degenerate strip indices are retained, never removed/reordered.
        self.assertEqual(self.indices(6,[3,3,4,5])[2],struct.pack('<4I',0,0,1,2))

    def test_index_preflight_rejects_without_writes(self):
        for primitive,count in [(0,3),(11,3),(2,3),(3,1),(4,1),(5,4),(6,2),(7,2),(8,5),(9,5),(10,2)]:
            self.assertNotEqual(self.indices(primitive,count=count)[0],OK)
        self.assertEqual(self.indices(5,[65535]*3,base=0xffffffff)[0],BOUNDS)
        self.assertEqual(self.indices(1,count=2,first=0xffffffff)[0],BOUNDS)
        self.assertEqual(self.indices(5,[1,2,3],first=1)[0],INVALID)
        self.assertEqual(self.indices(8,[0,1,2,3],capacity=23)[0],BOUNDS)
        sentinel = Plan(0xa7,0xa7,0xa7,0xa7)
        before = bytes(sentinel)
        raw = C.create_string_buffer(struct.pack('<2H',1,2),4)
        self.assertEqual(self.lib.metal_vertex_index_plan(5,raw,4,3,0,0,C.byref(sentinel)),BOUNDS)
        self.assertEqual(bytes(sentinel),before)

    def test_sanitizers_exact_end_of_minimum_attribute_and_index_ranges(self):
        unit = self.directory/'sanitizers.c'
        sizes = ','.join(str(BYTES[k]) for k in BYTES if BYTES[k])
        kinds = ','.join(str(k) for k in BYTES if BYTES[k])
        unit.write_text('#include <stdlib.h>\n#include <assert.h>\n#include <string.h>\n'
            '#include "'+str(SOURCE)+'"\n'
            'int main(void) {\n'
            'const unsigned sizes[]={'+sizes+'}, kinds[]={'+kinds+'};\n'
            'float fixed[16][4]={{0}}; unsigned i,j; unsigned char reference[512];\n'
            'const unsigned offsets[]={4,1,2,3};\n'
            'for(i=0;i<sizeof(sizes)/sizeof(sizes[0]);i++){\n'
            'struct metal_vertex_declaration d={0}; struct metal_vertex_stream s[16]={{0}};\n'
            'unsigned char *input=malloc(sizes[i]*3);\n'
            'assert(input); memset(input,0xa7,sizes[i]*3);\n'
            'd.element_count=1; d.elements[0]=(struct metal_vertex_element){15,0,kinds[i],sizes[i],0};\n'
            'd.packed_mask=kinds[i]==0x16?32768:0; s[0]=(struct metal_vertex_stream){input,sizes[i]*3,sizes[i]};\n'
            'for(j=0;j<sizeof(offsets)/sizeof(offsets[0]);j++){\n'
            'unsigned n; unsigned char *storage=malloc(512+offsets[j]), *output;\n'
            'assert(storage); output=storage+offsets[j]; memset(storage,0xa7,512+offsets[j]);\n'
            'assert(metal_vertex_fetch(&d,s,fixed,1,2,output,512)==0);\n'
            'for(n=0;n<offsets[j];n++)assert(storage[n]==0xa7);\n'
            'if(j==0)memcpy(reference,output,512); else assert(memcmp(reference,output,512)==0);\n'
            's[0].byte_count--; memset(storage,0x55,512+offsets[j]);\n'
            'assert(metal_vertex_fetch(&d,s,fixed,1,2,output,512)==METAL_VERTEX_BOUNDS);\n'
            'for(n=0;n<512+offsets[j];n++)assert(storage[n]==0x55);\n'
            's[0].byte_count++; free(storage); } free(input); }\n'
            '{struct metal_vertex_index_plan p; unsigned char *input=malloc(1), output[12];\n'
            'assert(metal_vertex_indices(5,(const uint16_t*)input,1,3,0,0,output,12,&p)==METAL_VERTEX_BOUNDS);\n'
            'free(input);}\nreturn 0;}\n')
        executable = self.directory/'sanitizers'
        subprocess.run(['clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
            '-DHALO_MACOS_NATIVE_METAL=1','-fsanitize=address,undefined','-fno-omit-frame-pointer',
            unit,'-o',executable],check=True,capture_output=True)
        subprocess.run([executable],check=True,capture_output=True)

    def test_all_126_original_draws_match_executed_frozen_wire_payloads(self):
        if not FRAME.exists() or not (WIRE/'fixture.json').exists():
            raise unittest.SkipTest('immutable original frame and executed wire fixture unavailable')
        frame_bytes = FRAME.read_bytes(); self.assertEqual(digest(frame_bytes),FRAME_SHA)
        frame = json.loads(frame_bytes)
        fixture_bytes = (WIRE/'fixture.json').read_bytes(); fixture = json.loads(fixture_bytes)
        self.assertEqual(digest(fixture_bytes),WIRE_FIXTURE_SHA)
        self.assertTrue(fixture['complete']); self.assertEqual(fixture['source_capture']['sha256'],FRAME_SHA)
        payload_hashes, rows = {}, []
        def payload(value):
            path = FRAME.parent/value['file']; data = path.read_bytes()
            self.assertEqual(len(data),value['bytes']);self.assertEqual(digest(data),value['sha256'])
            payload_hashes[str(path)] = digest(data)
            return data
        for step in fixture['steps']:
            if step['kind'] != 'draw':
                continue
            original = frame['draws'][f'draw-{step["use"]:04}.json']
            packet_path = WIRE/step['packet']['file']; packet = packet_path.read_bytes()
            self.assertEqual(digest(packet),step['packet']['sha256'])
            payload_hashes[str(packet_path)] = digest(packet)
            offset = 24; draw_offset = None
            for _ in range(struct.unpack_from('<I',packet,12)[0]):
                op,size = struct.unpack_from('<2I',packet,offset)
                if op == 9:
                    self.assertIsNone(draw_offset); draw_offset = offset
                offset += size
            self.assertEqual(offset,len(packet)); self.assertIsNotNone(draw_offset)
            nvertices,nindices,packed,topology = struct.unpack_from('<4I',packet,draw_offset+376)
            vertex_offset,index_offset = struct.unpack_from('<2I',packet,draw_offset+392)
            expected_vertices = packet[vertex_offset:vertex_offset+nvertices*256]
            expected_indices = packet[index_offset:index_offset+nindices*4]
            raw = payload(original['indices']) if original['indices'] is not None else None
            values = list(struct.unpack('<'+'H'*(len(raw)//2),raw)) if raw is not None else None
            count = original['index_count'] if values is not None else original['vertex_count']
            status,plan,actual_indices = self.indices(original['primitive_d3d'],values,count,
                first=0 if values is not None else original['source_first_vertex'],
                base=original['source_base_vertex'] if values is not None else 0)
            self.assertEqual(status,OK)
            self.assertEqual((plan.source_first,plan.source_count,plan.index_count,plan.wire_primitive),
                (original['source_first_vertex'],nvertices,nindices,topology))
            self.assertEqual(actual_indices,expected_indices,f'original indices use{original["use"]}')
            fields = [(e['register'],e['stream'],e['type'],e['offset']) for e in original['vertex_declaration']['elements']]
            if original['immediate']:
                fields = [(reg,0,0x42,reg*16) for reg in range(16)]
            status,d = self.parse(reconstruct_tokens(fields)); self.assertEqual(status,OK)
            self.assertEqual(d.packed_mask,packed)
            streams = []
            for s in original['streams']:
                self.assertEqual(s['source_first_vertex'],plan.source_first)
                streams.append((s['stream'],payload(s['payload']),s['stride']))
            # Captured stream pointers denote the already-bounded span vertex0.
            status,actual_vertices = self.fetch(d,streams,plan.source_count,first=0,
                fixed=payload(original['fixed_attributes']))
            self.assertEqual(status,OK)
            self.assertEqual(actual_vertices,expected_vertices,f'original vertex bytes use{original["use"]}')
            rows.append(dict(use=original['use'],vertices=nvertices,indices=nindices,packed_mask=packed,
                immediate=original['immediate'],vertex_sha256=digest(actual_vertices),index_sha256=digest(actual_indices)))
        self.assertEqual(len(rows),126)
        type(self).captured_summary = dict(frame_sha256=FRAME_SHA,fixture_sha256=digest(fixture_bytes),
            draws=len(rows),vertices=sum(r['vertices'] for r in rows),indices=sum(r['indices'] for r in rows),
            immediate_draws=sum(r['immediate'] for r in rows),rows=rows,input_sha256=payload_hashes,
            limits=['Original raw declaration tokens are absent; normalized declaration fields are exercised.',
                    'Missing packed-register fallback is independently source-tested; loaded captured packed values are unchanged.',
                    'CPU input/index proof does not establish GPU shader/raster fidelity.'])

    def test_native_compile_guards_and_no_gl_imports(self):
        result = subprocess.check_output(['nm','-u',self.library_path],text=True)
        self.assertNotRegex(result,r'\b_?(gl|host_gl|guest_gl|MTL)[A-Z_]')
        disabled = self.directory/'disabled.o'
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-c',SOURCE,'-o',disabled],check=True,capture_output=True)
        self.assertNotIn('metal_vertex_',subprocess.check_output(['nm','-g',disabled],text=True))


if __name__ == '__main__':
    unittest.main()
