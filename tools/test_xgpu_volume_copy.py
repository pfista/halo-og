#!/usr/bin/env python3
"""Independent CPU volume-layout/decoding proof for the live native uploader.

No GL/Metal calls or mip generation. The real attenuation asset and synthetic
rectangular volumes are decoded using a separate bit-by-bit Morton oracle.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from test_xgpu_texture_copy import Layout, harness_prefix, linear_size
SOURCE = ROOT/'port/linux/src/xbox_textures.c'
HEADER = ROOT/'port/linux/src/xgpu.h'
MAP = ROOT.parent/'pfista-halo-macos/assets/maps/bloodgulch.map'
MAP_SHA = '50fe52406f075d975e24100a65b26ff696458023dd3509878953052ab0ef858f'
RAW_SHA = 'de3f46809dd6dc460e877e2901bef644eed02452262bc1c3d47d54a7b21a3c5e'
RUNTIME = ROOT/'build/macos-metal/live-volume-diagnostic/dumps/native-volume-0726c000-55560139.bin'
AUTHORED_SHA = '0f23edd4a08b58514e0df7e67691da723b0095f74c0d94643747da7491454196'
OK, INVALID, UNSUPPORTED, BOUNDS = 0, -1, -2, -3


class VolumeLayout(C.Structure):
    _fields_ = [('mip', Layout)] + [(n, C.c_ulong) for n in
        ('texture_depth', 'depth', 'source_image_pitch', 'output_image_pitch')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def volume_header(fmt, width=1, height=1, depth=1, levels=1, cube=False):
    for n in (width, height, depth):
        assert n > 0 and n & (n-1) == 0
    return (3<<4) | (fmt<<8) | (levels<<16) | ((width.bit_length()-1)<<20) | \
        ((height.bit_length()-1)<<24) | ((depth.bit_length()-1)<<28) | (4 if cube else 0)


def morton3(x, y, z, width, height, depth):
    """Interleave only the coordinate bits present in each shrinking axis."""
    bits = []
    for bit in range(max(width, height, depth).bit_length()-1):
        for coordinate, extent in ((x, width), (y, height), (z, depth)):
            if 2**bit < extent:
                bits.append((coordinate//2**bit) % 2)
    return sum(value*2**place for place, value in enumerate(bits))


def rgba_order(data, order):
    if order == 0:
        return bytes(data)
    return bytes(component for p in range(0, len(data), 4)
                 for component in (data[p+2], data[p+1], data[p], data[p+3]))


def synthetic(fmt, width, height, depth, levels):
    bytes_per_texel = {0x01:1, 0x0b:1, 0x05:2, 0x06:4}[fmt]
    palette = b''.join(struct.pack('<I', ((i*19 & 255)<<24) | ((i*3 & 255)<<16) |
                                      ((i*7 & 255)<<8) | (i*11 & 255)) for i in range(256)) if fmt == 0x0b else None
    raw, golden = bytearray(), []
    for level in range(levels):
        w, h, d = (max(1, n//2**level) for n in (width, height, depth))
        swizzled = bytearray(w*h*d*bytes_per_texel)
        decoded = bytearray()
        for z in range(d):
            for y in range(h):
                for x in range(w):
                    code = (17*x+31*y+43*z+47*level) % 256
                    if fmt == 0x01:
                        texel, rgba = bytes([code]), bytes([code]*4)
                    elif fmt == 0x0b:
                        texel, rgba = bytes([code]), bytes([code*3 & 255, code*7 & 255,
                                                               code*11 & 255, code*19 & 255])
                    elif fmt == 0x06:
                        b, g, r, a = (x+3) % 256, (2*y+11) % 256, (3*z+19) % 256, (level*29+127) % 256
                        texel, rgba = bytes([b,g,r,a]), bytes([r,g,b,a])
                    else:
                        r, g, b = (x+2*level) % 32, (5*y+level) % 64, (3*z+level) % 32
                        texel = struct.pack('<H', (r<<11) | (g<<5) | b)
                        rgba = bytes([(r<<3) | (r>>2), (g<<2) | (g>>4), (b<<3) | (b>>2), 255])
                    address = morton3(x,y,z,w,h,d)*bytes_per_texel
                    swizzled[address:address+bytes_per_texel] = texel
                    decoded.extend(rgba)
        raw.extend(swizzled)
        golden.append(bytes(decoded))
    return bytes(raw), palette, golden


def authored_asset():
    from metal_poc_export import Cache
    if not MAP.exists():
        raise unittest.SkipTest('Original source map required for authored volume proof')
    cache = Cache(MAP)
    assert cache.sha256 == MAP_SHA, 'Original map changed'
    kind, tag, name = cache.tag(0xe6f60582)
    assert (kind, name) == ('bitm', 'rasterizer\\distance attenuation')
    count, pointer = cache.unpack('<II', tag+96)
    assert count == 1
    image = cache.pointer(pointer, 48)
    assert cache.unpack('<6H', image+4) == (32,32,32,1,2,137)
    assert cache.unpack('<h', image+20)[0] == 5
    assert (cache.u32(image+24), cache.u32(image+28)) == (16583680,37504)
    raw = cache.span(16583680,37504)
    assert hashlib.sha256(raw).hexdigest() == RAW_SHA, 'Original authored bytes changed'
    offsets, golden = [0], []
    for level in range(6):
        extent = 32//2**level
        mip = raw[offsets[-1]:offsets[-1]+extent**3]
        decoded = bytes(component for z in range(extent) for y in range(extent) for x in range(extent)
                        for component in [mip[morton3(x,y,z,extent,extent,extent)]]*4)
        golden.append(decoded)
        offsets.append(offsets[-1]+extent**3)
    assert offsets == [0,32768,36864,37376,37440,37448,37449]
    return raw, golden, dict(map=str(MAP), map_sha256=MAP_SHA, tag='0xe6f60582', name=name,
        original_bitmap_format=2, original_format_word='0x55560139', width=32,height=32,depth=32,
        levels=6, source_offset=16583680, source_bytes=37504, authored_bytes=37449,
        allocation_padding_bytes=55, source_sha256=RAW_SHA, authored_offsets=offsets,
        decoded_rgba_sha256=[hashlib.sha256(level).hexdigest() for level in golden])


def compile_library(directory):
    source = directory/'volume.c'
    source.write_text(harness_prefix()+'#include <limits.h>\n#include "'+str(SOURCE)+'"\n')
    library = directory/'volume.dylib'
    subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',source,'-o',library],
                   check=True,capture_output=True)
    lib = C.CDLL(str(library))
    lib.xgpu_texture_volume_mip_layout.argtypes = [C.c_uint32,C.c_uint32,C.c_ulong,C.c_ulong,C.c_int,C.POINTER(VolumeLayout)]
    lib.xgpu_texture_volume_mip_layout.restype = C.c_int
    lib.xgpu_texture_volume_mip_copy.argtypes = [C.c_uint32,C.c_uint32,C.c_void_p,C.c_ulong,
        C.c_void_p,C.c_ulong,C.c_ulong,C.c_ulong,C.c_int,C.c_void_p,C.c_ulong,C.POINTER(VolumeLayout)]
    lib.xgpu_texture_volume_mip_copy.restype = C.c_int
    lib.xgpu_texture_mip_layout.argtypes = [C.c_uint32,C.c_uint32,C.c_ulong,C.c_ulong,C.c_int,C.POINTER(Layout)]
    lib.xgpu_texture_mip_layout.restype = C.c_int
    return lib, library


class VolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='halo-cpu-volume-')
        cls.directory = Path(cls.temp.name)
        cls.lib, cls.library = compile_library(cls.directory)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def layout(self, fmt, size=0, face=0, level=0, order=0):
        output = VolumeLayout.from_buffer_copy(b'\xa7'*C.sizeof(VolumeLayout))
        status = self.lib.xgpu_texture_volume_mip_layout(fmt,size,face,level,order,C.byref(output))
        if status != OK:
            self.assertEqual(bytes(output), bytes(C.sizeof(VolumeLayout)))
        return status, output

    def copy(self, fmt, raw, level=0, order=0, palette=None, source_bytes=None, capacity=None,
             palette_entries=None, face=0):
        status, needed = self.layout(fmt, level=level, order=order, face=face)
        length = needed.mip.output_size if status == OK else 64
        source = C.create_string_buffer(raw, max(1,len(raw)))
        colors = C.create_string_buffer(palette,len(palette)) if palette is not None else None
        destination = C.create_string_buffer(b'\xa7'*(length+32),length+32)
        output = VolumeLayout.from_buffer_copy(b'\xa7'*C.sizeof(VolumeLayout))
        result = self.lib.xgpu_texture_volume_mip_copy(fmt,0,source,
            len(raw) if source_bytes is None else source_bytes, colors,
            (len(palette)//4 if palette is not None else 0) if palette_entries is None else palette_entries,
            face,level,order,C.byref(destination,16),length if capacity is None else capacity,C.byref(output))
        self.assertEqual(destination.raw[:16], b'\xa7'*16)
        self.assertEqual(destination.raw[16+length:], b'\xa7'*16)
        if result != OK:
            self.assertEqual(bytes(output), bytes(C.sizeof(VolumeLayout)))
            self.assertEqual(destination.raw, b'\xa7'*(length+32))
        return result, destination.raw[16:16+length], output

    def test_original_six_authored_volume_mips_and_full_byte_al8(self):
        raw, golden, _ = authored_asset()
        sources=[raw]
        if RUNTIME.exists():
            runtime=RUNTIME.read_bytes()
            self.assertEqual(hashlib.sha256(runtime).hexdigest(),AUTHORED_SHA)
            self.assertEqual(runtime,raw[:37449]);sources.append(runtime)
        for source in sources:
            for order in (0,1):
                for level in range(6):
                    status, rgba, layout = self.copy(0x55560139,source,level,order)
                    self.assertEqual(status,OK)
                    self.assertEqual(rgba,golden[level])
                    extent = 32//2**level
                    self.assertEqual((layout.texture_depth,layout.depth,layout.mip.width,layout.mip.height),
                                     (32,extent,extent,extent))
                    self.assertEqual((layout.mip.source_total_size,layout.mip.source_size), (37449,extent**3))
                    self.assertEqual((layout.source_image_pitch,layout.output_image_pitch,layout.mip.output_size),
                                     (extent**2,extent**2*4,extent**3*4))
        # Independent exhaustive byte semantics; AL8 is neither two4bit channels nor opaque luminance.
        for value in range(256):
            status, data, _ = self.copy(volume_header(1),bytes([value]))
            self.assertEqual((status,data),(OK,bytes([value]*4)))

    def test_rectangular_morton_all_axes_authored_chain_and_palette(self):
        for dimensions in ((8,4,2),(2,8,4),(4,2,8),(1,8,2),(8,1,4),(2,4,1),(1,1,8)):
            levels = max(dimensions).bit_length()
            for fmt in (0x01,0x05,0x06,0x0b):
                raw,palette,golden = synthetic(fmt,*dimensions,levels)
                format_word = volume_header(fmt,*dimensions,levels)
                offset = 0
                for level in range(levels):
                    for order in (0,1):
                        status,data,layout = self.copy(format_word,raw,level,order,palette)
                        self.assertEqual(status,OK)
                        self.assertEqual(data,rgba_order(golden[level],order))
                        self.assertEqual(layout.mip.source_offset,offset)
                    w,h,d = (max(1,n//2**level) for n in dimensions)
                    offset += w*h*d*{1:1,5:2,6:4,11:1}[fmt]
                self.assertEqual(layout.mip.source_total_size,offset)

    def test_other_color_formats_explicit_channels(self):
        formats = [(0,b'\x23',(35,35,35,255)),(2,bytes.fromhex('3ae8'),(214,8,214,255)),
            (3,bytes.fromhex('3a68'),(214,8,214,255)),(4,bytes.fromhex('a593'),(51,170,85,153)),
            (7,bytes([7,31,83,129]),(83,31,7,255)),(0x19,b'\x81',(255,255,255,129)),
            (0x1a,bytes([43,151]),(43,43,43,151)),(0x27,bytes.fromhex('3ba6'),(166,140,222,255)),
            (0x28,bytes([21,79]),(21,79,0,255)),(0x29,bytes([21,79]),(79,0,21,255)),
            (0x32,bytes([33,95]),(95,95,95,255)),(0x33,bytes([1,43,2,97]),(43,97,0,255)),
            (0x38,bytes.fromhex('3ba6'),(165,198,239,255)),(0x39,bytes.fromhex('a593'),(153,51,170,85)),
            (0x3a,bytes([7,31,83,129]),(7,31,83,129)),(0x3b,bytes([7,31,83,129]),(31,83,129,7)),
            (0x3c,bytes([7,31,83,129]),(129,83,31,7))]
        for fmt, raw, desired in formats:
            for order in (0,1):
                status, data, _ = self.copy(volume_header(fmt),raw,order=order)
                self.assertEqual((status,data),(OK,rgba_order(bytes(desired),order)))

    def test_layout_type_dimension_level_and_large_arithmetic(self):
        for fmt,size,face,level,order,expected in [
            (volume_header(1)^0x10,0,0,0,0,UNSUPPORTED),
            (volume_header(1,cube=True),0,0,0,0,UNSUPPORTED),
            (volume_header(0x0c),0,0,0,0,UNSUPPORTED),(volume_header(0x0e),0,0,0,0,UNSUPPORTED),
            (volume_header(0x0f),0,0,0,0,UNSUPPORTED),(volume_header(0x2a),0,0,0,0,UNSUPPORTED),
            (volume_header(0x2c),0,0,0,0,UNSUPPORTED),(volume_header(0x42),0,0,0,0,UNSUPPORTED),
            (volume_header(0x12),0,0,0,0,UNSUPPORTED),
            (volume_header(1),linear_size(2,1,64),0,0,0,UNSUPPORTED),
            (volume_header(1,1024,1,1),0,0,0,0,UNSUPPORTED),
            (volume_header(1,1,1024,1),0,0,0,0,UNSUPPORTED),
            (volume_header(1,1,1,1024),0,0,0,0,UNSUPPORTED),
            (volume_header(1,levels=2),0,0,0,0,INVALID),
            (volume_header(1),0,1,0,0,INVALID),(volume_header(1),0,0,1,0,INVALID),
            (volume_header(1),0,0,0,99,INVALID)]:
            with self.subTest(format_word=hex(fmt),size=size,face=face,level=level,order=order):
                self.assertEqual(self.layout(fmt,size,face,level,order)[0],expected)
        status,layout = self.layout(volume_header(1,512,512,512,10))
        self.assertEqual(status,OK)
        self.assertEqual((layout.mip.source_total_size,layout.mip.output_size),
                         (sum((512//2**n)**3 for n in range(10)),512**3*4))
        self.assertEqual(self.lib.xgpu_texture_volume_mip_layout(volume_header(1),0,0,0,0,None),INVALID)

    def test_bounds_missing_palette_overlap_and_atomic_failures(self):
        raw,palette,_ = synthetic(0x0b,4,2,8,4)
        fmt = volume_header(0x0b,4,2,8,4)
        for kwargs,expected in [({'source_bytes':len(raw)-1},BOUNDS),({'capacity':1},BOUNDS),
            ({'palette':None},INVALID),({'palette_entries':255},INVALID),({'palette_entries':257},INVALID),
            ({'face':1},INVALID),({'level':4},INVALID)]:
            args=dict(palette=palette);args.update(kwargs)
            self.assertEqual(self.copy(fmt,raw,**args)[0],expected)
        source=C.create_string_buffer(raw,len(raw)); colors=C.create_string_buffer(palette,len(palette))
        output=C.create_string_buffer(b'\xa7'*256,256)
        for src,dst,source_bytes,pal in [(None,output,len(raw),colors),(source,None,len(raw),colors),
            (source,C.byref(source,1),len(raw),colors),(source,C.byref(colors,1),len(raw),colors),
            (C.c_void_p(2**(C.sizeof(C.c_void_p)*8)-2),output,len(raw),colors),
            (source,C.c_void_p(2**(C.sizeof(C.c_void_p)*8)-2),len(raw),colors)]:
            layout=VolumeLayout.from_buffer_copy(b'\xa7'*C.sizeof(VolumeLayout))
            status=self.lib.xgpu_texture_volume_mip_copy(fmt,0,src,source_bytes,pal,256,0,0,0,dst,256,C.byref(layout))
            self.assertIn(status,(INVALID,BOUNDS))
            self.assertEqual(bytes(layout),bytes(C.sizeof(VolumeLayout)))
            self.assertEqual(output.raw,b'\xa7'*256)
            self.assertEqual(source.raw,raw);self.assertEqual(colors.raw,palette)

    def test_separate_legacy_api_still_rejects_volumes_and_no_gl_imports(self):
        layout=Layout()
        self.assertEqual(self.lib.xgpu_texture_mip_layout(0x55560139,0,0,0,0,C.byref(layout)),UNSUPPORTED)
        names=subprocess.check_output(['nm','-u',self.library],text=True)
        self.assertNotRegex(names,r'\b_(?:gl[A-Z]|host_gl_|hud_hires_)')

    def test_final_texel_and_rectangular_mips_under_sanitizers(self):
        source=self.directory/'asan.c'
        source.write_text(harness_prefix()+'#include <limits.h>\n#include "'+str(SOURCE)+'''"
int main(void){const unsigned formats[]={0,1,2,3,4,5,6,7,0xb,0x19,0x1a,0x27,0x28,0x29,0x32,0x33,0x38,0x39,0x3a,0x3b,0x3c};
uint32_t palette[256];for(unsigned i=0;i<256;i++)palette[i]=i*0x01010101;
for(unsigned i=0;i<sizeof(formats)/sizeof(*formats);i++){
unsigned f=(formats[i]<<8)|0x10030;struct xgpu_texture_volume_mip_layout m;
if(xgpu_texture_volume_mip_layout(f,0,0,0,0,&m))return 1;
unsigned char*s=malloc(m.mip.source_total_size),*d=malloc(m.mip.output_size);memset(s,73,m.mip.source_total_size);
if(xgpu_texture_volume_mip_copy(f,0,s,m.mip.source_total_size,palette,256,0,0,0,d,m.mip.output_size,&m))return 2;
free(s);free(d);}
unsigned f=0x12340630;struct xgpu_texture_volume_mip_layout m;
if(xgpu_texture_volume_mip_layout(f,0,0,0,0,&m))return 3;
unsigned char*s=malloc(m.mip.source_total_size);unsigned long total=m.mip.source_total_size;memset(s,91,total);
for(unsigned n=0;n<4;n++){if(xgpu_texture_volume_mip_layout(f,0,0,n,0,&m))return 4;
unsigned char*d=malloc(m.mip.output_size);if(xgpu_texture_volume_mip_copy(f,0,s,total,NULL,0,0,n,0,d,m.mip.output_size,&m))return 5;free(d);}
free(s);return 0;}
''')
        executable=self.directory/'asan'
        subprocess.run(['clang','-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                        source,'-o',executable],check=True,capture_output=True)
        result=subprocess.run([executable],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


def proof_cases():
    raw,golden,asset=authored_asset()
    runtime=RUNTIME.read_bytes()
    assert hashlib.sha256(runtime).hexdigest()==AUTHORED_SHA and runtime==raw[:37449]
    asset.update(runtime_file=str(RUNTIME),runtime_bytes=len(runtime),runtime_sha256=AUTHORED_SHA,
                 runtime_matches_authored_payload=True)
    cases=[]
    for source in (raw,runtime):
        for order in (0,1):
            for level in range(6):
                cases.append(dict(fmt=0x55560139,level=level,order=order,raw=source,palette=None,
                    expected=golden[level],dimensions=(32,32,32),levels=6,bpp=1,status=OK))
    for dimensions in ((8,4,2),(2,8,4),(4,2,8),(1,8,2),(8,1,4),(2,4,1),(1,1,8)):
        levels=max(dimensions).bit_length()
        for fmt in (1,5,6,11):
            raw,palette,golden=synthetic(fmt,*dimensions,levels)
            for order in (0,1):
                for level in range(levels):
                    cases.append(dict(fmt=volume_header(fmt,*dimensions,levels),level=level,order=order,
                        raw=raw,palette=palette,expected=rgba_order(golden[level],order),dimensions=dimensions,
                        levels=levels,bpp={1:1,5:2,6:4,11:1}[fmt],status=OK))
    for status,change in [(BOUNDS,dict(source_bytes=1)),(BOUNDS,dict(destination_bytes=1)),
                          (INVALID,dict(palette_entries=255)),(INVALID,dict(face=1))]:
        invalid=dict(next(c for c in cases if c['palette'] is not None));invalid.update(change,status=status)
        cases.append(invalid)
    return cases,asset


def expected_layout(case):
    if case['status'] != OK:
        return bytes(80)
    width,height,depth=case['dimensions'];level=case['level'];bpp=case['bpp']
    dimensions=[tuple(max(1,n//2**i) for n in (width,height,depth)) for i in range(case['levels'])]
    extents=[w*h*d*bpp for w,h,d in dimensions];w,h,d=dimensions[level]
    fields=[width,height,case['levels'],1,0,level,w,h,sum(extents),sum(extents),sum(extents[:level]),
            extents[level],w*bpp,w*4,w*h*d*4,1 if case['order']==0 else 2,depth,d,w*h*bpp,w*h*4]
    return struct.pack('<20I',*fields)


def prepare_ilp32(output):
    sys.path.insert(0,str(ROOT));from tools.android_build import GUEST_ABI_FLAGS
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    files=[SOURCE,HEADER,Path(__file__).resolve(),ROOT/'tools/test_xgpu_texture_copy.py',ROOT/'tools/metal_poc_export.py',
           ROOT/'port/include/xdk/xdk_d3d8.h',ROOT/'tools/android_build.py',ROOT/'tools/android_asm_convert.py',
           ROOT/'tools/android_imports.py',ROOT/'port/macos/metal_imports.list']
    bindings={str(p):sha(p) for p in files};snapshot=output/'source-snapshot'
    for p in files:
        destination=snapshot/p.relative_to(ROOT);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,destination)
    cases,asset=proof_cases();blob=bytearray()
    def append(data):
        blob.extend(data);blob.extend(bytes((-len(blob))%16))
    for case in cases:
        raw,palette=case['raw'],case['palette'] or b'';expected=case['expected']
        fields=[case['fmt'],0,case.get('face',0),case['level'],case['order'],case.get('source_bytes',len(raw)),
                len(raw),case.get('palette_entries',256 if palette else 0),len(palette),
                case.get('destination_bytes',len(expected)),case['status'] & 0xffffffff,len(expected),0,0,0,0]
        append(struct.pack('<16I',*fields));append(expected_layout(case));append(raw);append(palette);append(expected)
    (output/'cases.bin').write_bytes(blob)
    (output/'cases.s').write_text('.section .rodata\n.balign 16\n.global volume_cases\nvolume_cases:\n.incbin "'+str(output/'cases.bin')+'"\n')
    (output/'assets.json').write_text(json.dumps(asset,indent=2)+'\n')
    shims=output/'shims';shims.mkdir()
    (shims/'stdio.h').write_text('')
    (shims/'platform.h').write_text('/* Platform include already guarded by fixed-width CPU harness. */\n')
    (shims/'stdlib.h').write_text('#include <stddef.h>\nvoid *malloc(size_t);void free(void*);\n')
    (shims/'string.h').write_text('#include <stddef.h>\nvoid *memset(void*,int,size_t);void *memcpy(void*,const void*,size_t);\n')
    prefix=harness_prefix().replace('#include <stdlib.h>\n','').replace('#include <string.h>\n','')+'#include <limits.h>\n'
    guest=output/'guest.c';guest.write_text(prefix+'#include "'+str(snapshot/SOURCE.relative_to(ROOT))+'''"
_Static_assert(sizeof(void*)==4 && sizeof(unsigned long)==4,"actualILP32");
_Static_assert(sizeof(struct xgpu_texture_volume_mip_layout)==80,"volumeABI");
void*memset(void*p,int c,size_t n){unsigned char*d=p;for(size_t i=0;i<n;i++)d[i]=(unsigned char)c;return p;}
void*memcpy(void*p,const void*q,size_t n){unsigned char*d=p;const unsigned char*s=q;for(size_t i=0;i<n;i++)d[i]=s[i];return p;}
extern const unsigned char volume_cases[];
static unsigned char destination[131104];
static const unsigned char*next(const unsigned char*p,uint32_t n){return(const void*)(((uintptr_t)p+n+15)&~(uintptr_t)15);}
uint32_t guest_test(uint32_t unused){(void)unused;const unsigned char*p=volume_cases;
for(uint32_t i=0;i<'''+str(len(cases))+''';i++){
const uint32_t*h=(const void*)p;p+=64;const unsigned char*expected_layout=p;p+=80;
const void*s=p;p=next(p,h[6]);const uint32_t*palette=h[8]?(const void*)p:NULL;p=next(p,h[8]);
const unsigned char*expected=p;p=next(p,h[11]);
if(h[11]+32>sizeof(destination))return 50000+i;memset(destination,0xa7,sizeof(destination));
struct xgpu_texture_volume_mip_layout m;memset(&m,0xa7,sizeof(m));
int status=xgpu_texture_volume_mip_copy(h[0],h[1],s,h[5],palette,h[7],h[2],h[3],h[4],destination+16,h[9],&m);
if(status!=(int32_t)h[10])return 10000+i;
const unsigned char*b=(const void*)&m;for(uint32_t j=0;j<80;j++)if(b[j]!=expected_layout[j])return 20000+i;
for(uint32_t j=0;j<h[11];j++)if(destination[16+j]!=(status?0xa7:expected[j]))return 30000+i;
for(uint32_t j=0;j<16;j++)if(destination[j]!=0xa7||destination[16+h[11]+j]!=0xa7)return 40000+i;
}return 0;}
''')
    llvm=Path('/opt/homebrew/opt/llvm@22/bin');linker=Path('/opt/homebrew/opt/lld@22/bin/ld.lld')
    plugin=ROOT.parent/'pfista-halo-macos/build/macos/guest_rebase.dylib'
    previous=json.loads((ROOT/'build/metal-poc/native-draw-state-ilp32-final/prepared.json').read_text())
    executor=Path(previous['execution_command'][0]);assert sha(executor)==previous['executor_sha256']
    def run(*args):
        result=subprocess.run([str(x) for x in args],cwd=ROOT,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr or result.stdout)
    resource=Path(subprocess.check_output([llvm/'clang','-print-resource-dir'],text=True).strip())
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',shims,'-isystem',resource/'include',
        '-std=c11','-Wall','-Wextra','-Werror','-emit-llvm','-S',guest,'-o',output/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',output/'guest.ll','-o',output/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',output/'guest.rebased.ll','-o',output/'guest.darwin.s')
    run(sys.executable,ROOT/'tools/android_asm_convert.py',output/'guest.darwin.s',output/'guest.s')
    run(sys.executable,ROOT/'tools/android_imports.py','--host-table',output/'host_import_table.c',output/'imports.s',ROOT/'port/macos/metal_imports.list')
    for name in ('guest','cases','imports'):run(llvm/'clang','--target=aarch64-linux-android','-c',output/(name+'.s'),'-o',output/(name+'.o'))
    (output/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',output/'guest.ld',output/'guest.o',output/'cases.o',output/'imports.o','-o',output/'guest.elf')
    symbols={}
    for line in subprocess.check_output([llvm/'llvm-nm','--defined-only',output/'guest.elf'],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    copied=output/'host_ilp32_probe';shutil.copy2(executor,copied)
    command=[str(copied),str(output/'guest.elf'),*[hex(symbols[n]) for n in
        ('__host_import_table','__host_import_names','__host_import_count')],'0x5000000']
    assert all(sha(p)==h for p,h in bindings.items()),'Source changed during preparation'
    proof=dict(kind='native_cpu_authored_volume_extraction',complete=False,passed=False,case_count=len(cases),
        source_sha256=bindings,source_snapshot_sha256={str(snapshot/p.relative_to(ROOT)):sha(snapshot/p.relative_to(ROOT)) for p in files},
        inputs_sha256={str(output/n):sha(output/n) for n in ('cases.bin','cases.s','guest.c','guest.elf','host_ilp32_probe','assets.json',
                         'shims/platform.h','shims/stdio.h','shims/stdlib.h','shims/string.h')},
        map_sha256={str(MAP):MAP_SHA,str(RUNTIME):AUTHORED_SHA},toolchain_sha256={str(p):sha(p) for p in (llvm/'clang',llvm/'opt',llvm/'llc',linker,plugin)},
        execution_command=command,limits=['CPU extraction only; no native GPU sampling or lighting parity claim',
                                          'No generated mipmaps; allocation padding is excluded from authored levels'])
    (output/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(output/'prepared.json'),cases=len(cases)),indent=2))


def execute_ilp32(output):
    prepared=output/'prepared.json';proof=json.loads(prepared.read_text())
    hashes={**proof['source_sha256'],**proof['source_snapshot_sha256'],**proof['inputs_sha256'],
            **proof['map_sha256'],**proof['toolchain_sha256']}
    assert all(sha(p)==h for p,h in hashes.items()),'Stale proof input'
    run=subprocess.run(proof['execution_command'],capture_output=True,text=True,timeout=60)
    (output/'stdout.json').write_text(run.stdout);(output/'stderr.log').write_text(run.stderr)
    observed=json.loads(run.stdout)
    passed=run.returncode==0 and observed.get('passed') is True and observed.get('guest_result')==0 and observed.get('guest_pointer_bits')==32
    assert all(sha(p)==h for p,h in hashes.items()),'Input changed during execution'
    closure=dict(proof,complete=True,passed=passed,guest_run=observed,returncode=run.returncode,
        prepared_sha256=sha(prepared),stdout_sha256=sha(output/'stdout.json'),stderr_sha256=sha(output/'stderr.log'))
    (output/'closure.json').write_text(json.dumps(closure,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,cases=proof['case_count'],closure=str(output/'closure.json')),indent=2))
    if not passed:raise RuntimeError('Actual ILP32 volume proof failed; retained diagnostic')


if __name__=='__main__':
    if '--prepare-ilp32' in sys.argv or '--execute-ilp32' in sys.argv:
        parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
        group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--prepare-ilp32',action='store_true');group.add_argument('--execute-ilp32',action='store_true')
        args=parser.parse_args();prepare_ilp32(args.output) if args.prepare_ilp32 else execute_ilp32(args.output.resolve())
    else:unittest.main()
