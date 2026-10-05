#!/usr/bin/env python3
"""Exercise the live CPU mip API without GL, Metal, or a game build.

The host harness includes the actual production C file/public header, with
fixed-width guest scalar types and the checked-in XDK format masks. Captured
resource tests compare against frozen authored uploads, never generated mips.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT/'build/metal-reference-20261004/ordered-frame-runtime/run/saves/metal-frames/frame420/captured_frame.json'
PREPARED = ROOT/'build/metal-poc/frame-replay-420-current-verified/frame-replay.json'
FRAME_SHA = '75f256ed7d40324d24cfb754e93248699defdcdc89d3f60d271dc9482ff115ac'
COPY_RGBA, COPY_BGRA = 0, 1
OK, INVALID, UNSUPPORTED, BOUNDS = 0, -1, -2, -3


class Layout(C.Structure):
    _fields_ = [(name, C.c_ulong) for name in (
        'texture_width', 'texture_height', 'levels', 'faces', 'face', 'level', 'width', 'height',
        'source_face_pitch', 'source_total_size', 'source_offset', 'source_size', 'source_row_pitch',
        'output_row_pitch', 'output_size')] + [('format', C.c_int)]


def header(fmt, width=1, height=1, levels=1, cube=False, dimension=2):
    assert width > 0 and width & (width-1) == 0
    assert height > 0 and height & (height-1) == 0
    return (dimension << 4) | (fmt << 8) | (levels << 16) | \
        ((width.bit_length()-1) << 20) | ((height.bit_length()-1) << 24) | (4 if cube else 0)


def linear_size(width, height, pitch):
    assert pitch % 64 == 0
    return (width-1) | ((height-1) << 12) | ((pitch//64-1) << 24)


def morton(x, y, width, height):
    """Independent rectangular Morton indexing, alternating live axis bits."""
    value = 0
    target = 0
    for bit in range(max(width, height).bit_length()-1):
        for coordinate, dimension in ((x, width), (y, height)):
            if (1 << bit) < dimension:
                value |= ((coordinate >> bit) & 1) << target
                target += 1
    return value


def harness_prefix():
    xdk = (ROOT/'port/include/xdk/xdk_d3d8.h').read_text()
    masks = '\n'.join(line for line in xdk.splitlines() if re.match(
        r'#define (D3DFORMAT_|D3DSIZE_|D3DTEXTURE_(PITCH|CUBEFACE)_ALIGNMENT)', line))
    return '''#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define __HALO_LINUX_PLATFORM_H
#define HALO_MACOS_NATIVE_METAL 1
typedef uint32_t DWORD;
typedef uint32_t D3DCOLOR;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define D3DRS_PS_MAX 57
''' + masks + '\n'


class TextureCopyTests(unittest.TestCase):
    captured_summary = None

    @classmethod
    def setUpClass(cls):
        if not shutil.which('clang'):
            raise unittest.SkipTest('native clang is required')
        cls.temp = tempfile.TemporaryDirectory(prefix='halo-cpu-mip-copy-')
        cls.directory = Path(cls.temp.name)
        cls.prefix = harness_prefix()
        source = cls.directory/'copy.c'
        source.write_text(cls.prefix + '#include "' + str(ROOT/'port/linux/src/xbox_textures.c') + '"\n')
        cls.library_path = cls.directory/'copy.dylib'
        subprocess.run(['clang', '-std=c11', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        source, '-o', cls.library_path], check=True, capture_output=True)
        cls.lib = C.CDLL(str(cls.library_path))
        cls.lib.xgpu_texture_mip_layout.argtypes = [C.c_uint32, C.c_uint32, C.c_ulong, C.c_ulong,
                                                   C.c_int, C.POINTER(Layout)]
        cls.lib.xgpu_texture_mip_layout.restype = C.c_int
        cls.lib.xgpu_texture_mip_copy.argtypes = [C.c_uint32, C.c_uint32, C.c_void_p, C.c_ulong,
            C.c_void_p, C.c_ulong, C.c_ulong, C.c_ulong, C.c_int, C.c_void_p, C.c_ulong, C.POINTER(Layout)]
        cls.lib.xgpu_texture_mip_copy.restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def layout(self, fmt, size=0, face=0, level=0, order=COPY_RGBA):
        result = Layout()
        status = self.lib.xgpu_texture_mip_layout(fmt, size, face, level, order, C.byref(result))
        return status, result

    def copy(self, fmt, raw, size=0, face=0, level=0, order=COPY_RGBA, palette=None,
             source_bytes=None, capacity=None, palette_entries=None):
        status, needed = self.layout(fmt, size, face, level, order)
        length = needed.output_size if status == OK else 64
        source = C.create_string_buffer(raw, max(1, len(raw)))
        pal = C.create_string_buffer(palette, len(palette)) if palette is not None else None
        destination = C.create_string_buffer(bytes([0xa7])*(length+32), length+32)
        layout = Layout()
        written = self.lib.xgpu_texture_mip_copy(fmt, size, source,
            len(raw) if source_bytes is None else source_bytes, pal,
            (len(palette)//4 if palette is not None else 0) if palette_entries is None else palette_entries,
            face, level, order, C.byref(destination, 16), length if capacity is None else capacity,
            C.byref(layout))
        self.assertEqual(destination.raw[:16], bytes([0xa7])*16)
        self.assertEqual(destination.raw[16+length:], bytes([0xa7])*16)
        if written != OK:
            self.assertEqual(destination.raw, bytes([0xa7])*(length+32))
            self.assertEqual(bytes(layout), bytes(C.sizeof(Layout)))
        return written, destination.raw[16:16+length], layout

    def test_native_library_has_no_gl_imports(self):
        names = subprocess.check_output(['nm', '-u', self.library_path], text=True)
        self.assertNotRegex(names, r'\b_(?:gl[A-Z]|host_gl_|hud_hires_)')

    def test_color_formats_and_channel_order(self):
        # Explicit channel expectations independent of the production converter.
        cases = [
            (0x00, b'\x23', (35,35,35,255)), (0x01,b'\x59',(89,89,89,89)),
            (0x02,struct.pack('<H',0xe83a),(214,8,214,255)),
            (0x03,struct.pack('<H',0x683a),(214,8,214,255)),
            (0x04,struct.pack('<H',0x93a5),(51,170,85,153)),
            (0x05,struct.pack('<H',0xa63b),(165,199,222,255)),
            (0x06,bytes([7,31,83,129]),(83,31,7,129)),
            (0x07,bytes([7,31,83,129]),(83,31,7,255)),
            (0x19,b'\x81',(255,255,255,129)), (0x1a,bytes([43,151]),(43,43,43,151)),
            (0x27,struct.pack('<H',0xa63b),(166,140,222,255)),
            (0x28,bytes([21,79]),(21,79,0,255)), (0x29,bytes([21,79]),(79,0,21,255)),
            (0x32,bytes([33,95]),(95,95,95,255)),
            (0x33,bytes([1,43,2,97]),(43,97,0,255)),
            (0x38,struct.pack('<H',0xa63b),(165,198,239,255)),
            (0x39,struct.pack('<H',0x93a5),(153,51,170,85)),
            (0x3a,bytes([7,31,83,129]),(7,31,83,129)),
            (0x3b,bytes([7,31,83,129]),(31,83,129,7)),
            (0x3c,bytes([7,31,83,129]),(129,83,31,7)),
        ]
        for fmt, raw, expected in cases:
            for order in (COPY_RGBA, COPY_BGRA):
                with self.subTest(fmt=fmt, order=order):
                    status, data, layout = self.copy(header(fmt), raw, order=order)
                    self.assertEqual(status, OK)
                    channels = expected if order == COPY_RGBA else (expected[2],expected[1],expected[0],expected[3])
                    self.assertEqual(data, bytes(channels))
                    self.assertEqual((layout.width,layout.height,layout.output_row_pitch,layout.output_size), (1,1,4,4))

    def test_rectangular_swizzle_and_each_authored_mip(self):
        for width,height in ((8,2),(2,8),(8,4),(1,8),(8,1)):
            levels = max(width,height).bit_length()
            raw = bytearray(); golden = []
            for level in range(levels):
                w,h=max(1,width>>level),max(1,height>>level)
                payload = bytearray(w*h*4); expected = bytearray()
                for y in range(h):
                    for x in range(w):
                        rgba=bytes([(x+level*19)&255,(y+level*23)&255,(x+y+level*31)&255,173-level])
                        at=morton(x,y,w,h)*4;payload[at:at+4]=bytes([rgba[2],rgba[1],rgba[0],rgba[3]])
                        expected.extend(rgba)
                raw.extend(payload);golden.append(bytes(expected))
            for level,expected in enumerate(golden):
                with self.subTest(width=width,height=height,level=level):
                    status,data,layout=self.copy(header(0x06,width,height,levels),bytes(raw),level=level)
                    self.assertEqual(status,OK);self.assertEqual(data,expected)
                    self.assertEqual(layout.source_total_size,len(raw))

    def test_p8_uses_current_palette_each_call(self):
        raw=bytes([0,255,7,43])
        palette=b''.join(struct.pack('<I',(i<<24)|((255-i)<<16)|((i^83)<<8)|(i^171)) for i in range(256))
        status,data,_=self.copy(header(0x0b,4,1),raw,palette=palette)
        self.assertEqual(status,OK)
        self.assertEqual(data,b''.join(bytes([255-i,i^83,i^171,i]) for i in raw))
        updated=bytearray(palette);updated[255*4:256*4]=bytes([11,22,33,44])
        self.assertEqual(self.copy(header(0x0b,4,1),raw,palette=bytes(updated))[1][4:8],bytes([33,22,11,44]))
        for entries in (0,16,255,257):
            self.assertEqual(self.copy(header(0x0b,4,1),raw,palette=palette,palette_entries=entries)[0],INVALID)
        self.assertEqual(self.copy(header(0x0b,4,1),raw)[0],INVALID)

    def test_linear_rows_keep_source_pitch_and_remove_padding(self):
        raw=bytearray([0xcd]*128)
        for y in range(2):
            for x in range(3):raw[y*64+x*4:y*64+x*4+4]=bytes([x+3,y+7,x+y+19,201])
        status,data,layout=self.copy(header(0x12),bytes(raw),size=linear_size(3,2,64))
        self.assertEqual(status,OK)
        self.assertEqual(data,b''.join(bytes([x+y+19,y+7,x+3,201]) for y in range(2) for x in range(3)))
        self.assertEqual((layout.levels,layout.source_row_pitch,layout.output_row_pitch),(1,64,12))
        self.assertEqual((layout.source_size,layout.output_size),(128,24))
        # YUY2/ UYVY black + white luma share neutral chroma, without OOB pairs.
        for fmt, packed in ((0x24,bytes([16,128,235,128])),(0x25,bytes([128,16,128,235]))):
            status,data,_=self.copy(header(fmt),packed+bytes(60),size=linear_size(2,1,64))
            self.assertEqual(status,OK);self.assertEqual(data,bytes([0,0,0,255,255,255,255,255]))

    def test_compressed_faces_blocks_and_small_mips_are_verbatim(self):
        for fmt,stride,output in ((0x0c,8,3),(0x0e,16,4),(0x0f,16,5)):
            lengths=[4*stride,stride,stride,stride] # 8,4,2,1 texel mips.
            chain=sum(lengths);pitch=(chain+127)&~127
            raw=bytearray([0xee]*(pitch*6));expected={}
            for face in range(6):
                offset=face*pitch
                for level,length in enumerate(lengths):
                    block=bytes((face*29+level*17+i)&255 for i in range(length));raw[offset:offset+length]=block
                    expected[face,level]=(offset,block);offset+=length
            for (face,level),(offset,block) in expected.items():
                status,data,layout=self.copy(header(fmt,8,8,4,True),bytes(raw),face=face,level=level)
                self.assertEqual(status,OK);self.assertEqual(data,block)
                self.assertEqual((layout.faces,layout.source_face_pitch,layout.source_offset,layout.format),(6,pitch,offset,output))

    def test_invalid_layouts_and_truncated_ranges_are_atomic(self):
        cases=[(header(0x08),0,0,0,COPY_RGBA,UNSUPPORTED),
               (header(0x06,dimension=3),0,0,0,COPY_RGBA,UNSUPPORTED),
               (header(0x06,dimension=1),0,0,0,COPY_RGBA,UNSUPPORTED),
               (header(0x2a),0,0,0,COPY_RGBA,UNSUPPORTED),
               (header(0x0c),linear_size(4,4,64),0,0,COPY_RGBA,UNSUPPORTED),
               (header(0x06,8,4,1,True),0,0,0,COPY_RGBA,INVALID),
               (header(0x12,4,4,1,True),0,0,0,COPY_RGBA,INVALID),
               (header(0x06,4,4,4),0,0,0,COPY_RGBA,INVALID),
               (header(0x12),linear_size(17,1,64),0,0,COPY_RGBA,INVALID),
               (header(0x06),0,1,0,COPY_RGBA,INVALID),
               (header(0x06),0,0,1,COPY_RGBA,INVALID),
               (header(0x06),0,0,0,99,INVALID),
               (header(0x06,8192,1),0,0,0,COPY_RGBA,UNSUPPORTED)]
        for fmt,size,face,level,order,expected in cases:
            with self.subTest(fmt=fmt,size=size,face=face,level=level):
                status,_,_=self.copy(fmt,bytes(512),size,face,level,order)
                self.assertEqual(status,expected)
        self.assertEqual(self.copy(header(0x06),bytes(4),source_bytes=3)[0],BOUNDS)
        self.assertEqual(self.copy(header(0x06),bytes(4),capacity=3)[0],BOUNDS)
        # Requiring the full authored chain prevents a truncated later mip from
        # masquerading as a complete texture when only its base is requested.
        self.assertEqual(self.copy(header(0x0c,8,8,4,True),bytes(6*128-1))[0],BOUNDS)
        storage=C.create_string_buffer(bytes([0x35])*256,256);result=Layout()
        status=self.lib.xgpu_texture_mip_copy(header(0x06,4,4),0,storage,64,None,0,0,0,COPY_RGBA,
            C.byref(storage,16),64,C.byref(result))
        self.assertEqual(status,INVALID);self.assertEqual(storage.raw,bytes([0x35])*256)

    def test_final_small_texels_with_address_sanitizer(self):
        source=self.directory/'asan.c'
        source.write_text(self.prefix + '#include "' + str(ROOT/'port/linux/src/xbox_textures.c') + '''"
int main(void){const unsigned formats[]={0,1,2,3,4,5,6,7,0x19,0x1a,0x27,0x28,0x29,0x32,0x33,0x38,0x39,0x3a,0x3b,0x3c};
for(unsigned i=0;i<sizeof(formats)/sizeof(*formats);i++){
struct xgpu_texture_mip_layout m;DWORD f=(formats[i]<<8)|0x10020;
if(xgpu_texture_mip_layout(f,0,0,0,_xgpu_texture_copy_rgba,&m))return 1;
unsigned char*s=malloc(m.source_total_size),*d=malloc(m.output_size);memset(s,73,m.source_total_size);
if(xgpu_texture_mip_copy(f,0,s,m.source_total_size,NULL,0,0,0,_xgpu_texture_copy_rgba,d,m.output_size,&m))return 2;
free(s);free(d);}return 0;}
''')
        executable=self.directory/'asan'
        subprocess.run(['clang','-std=c11','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                        source,'-o',executable],check=True,capture_output=True)
        result=subprocess.run([executable],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_legacy_gl_description_and_decode_are_preserved(self):
        baseline=ROOT/'build/metal-poc/texture-copy-api-validation/before-source/xbox_textures.c'
        if not baseline.exists():
            self.skipTest('Pre-change GL texture source snapshot is unavailable')
        public='#include "'+str(ROOT/'port/linux/src/xgpu.h')+'"\n#undef HALO_MACOS_NATIVE_METAL\n'
        wrapper='''
void legacy_decode(DWORD f,DWORD s,unsigned long face,unsigned long level,const void *raw,
 const D3DCOLOR *palette,DWORD *output){struct xgpu_texture_description d;xgpu_texture_describe(f,s,&d);
unsigned long width=level_dimension(d.width,level),height=level_dimension(d.height,level);
unsigned long *words=malloc(width*height*sizeof(unsigned long));
decode_level(&d,level,(const unsigned char*)raw+face*xgpu_texture_face_size(&d)+xgpu_texture_level_offset(&d,level),palette,words);
for(unsigned long i=0;i<width*height;i++)output[i]=(DWORD)words[i];free(words);}
'''
        libs=[]
        for name,path in (('before',baseline),('after',ROOT/'port/linux/src/xbox_textures.c')):
            text=path.read_text().split('/* ---------- GL texture upload/cache */')[0]
            if name=='before':text=text.split('#ifdef HALO_ANDROID\n/* ---------- DXT decoding')[0]
            text=re.sub(r'^#include "(?:xgpu.h|hud_hires.h|port_config.h)"\n','',text,flags=re.M)
            source=self.directory/f'legacy-{name}.c';source.write_text(self.prefix+public+text+wrapper)
            library=self.directory/f'legacy-{name}.dylib'
            subprocess.run(['clang','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                '-Wno-unused-function',source,'-o',library],check=True,capture_output=True)
            lib=C.CDLL(str(library));lib.legacy_decode.argtypes=[C.c_uint32,C.c_uint32,C.c_ulong,C.c_ulong,
                                                               C.c_void_p,C.c_void_p,C.c_void_p]
            libs.append(lib)
        for fmt,stride in ((0x06,4),(0x05,2),(0x0b,1),(0x28,2),(0x3c,4)):
            raw=C.create_string_buffer(bytes((i*17+43)&255 for i in range(8*4*stride))+bytes(4))
            palette=C.create_string_buffer(b''.join(struct.pack('<I',0x80000000|(i*0x010101)) for i in range(256)))
            outputs=[(C.c_uint32*32)() for _ in libs]
            for lib,output in zip(libs,outputs):lib.legacy_decode(header(fmt,8,4),0,0,0,raw,palette,output)
            self.assertEqual(bytes(outputs[0]),bytes(outputs[1]))
        # The GL upload/cache implementation itself is only enclosed in a
        # native-build guard, with its legacy statements left byte-identical.
        old=baseline.read_text().split('#ifdef HALO_ANDROID\n/* ---------- DXT decoding',1)[1]
        new=(ROOT/'port/linux/src/xbox_textures.c').read_text().split('#ifdef HALO_ANDROID\n/* ---------- DXT decoding',1)[1]
        self.assertEqual(new.removesuffix('#endif /* !HALO_MACOS_NATIVE_METAL */\n'),old)

    def test_original_captured_resource_mips(self):
        if not FRAME.exists() or not PREPARED.exists():
            self.skipTest('Frozen original frame420 resources are unavailable')
        captured_bytes=FRAME.read_bytes();self.assertEqual(hashlib.sha256(captured_bytes).hexdigest(),FRAME_SHA)
        captured=json.loads(captured_bytes);prepared_bytes=PREPARED.read_bytes();prepared=json.loads(prepared_bytes)
        checked=set();formats=set();levels=0;byte_count=0
        def load(base,descriptor):
            path=base/descriptor['file'];data=path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),descriptor['sha256'])
            self.assertEqual(len(data),descriptor.get('size',descriptor.get('bytes')))
            return data
        for name,draw in captured['draws'].items():
            for slot,texture in enumerate(draw['textures']):
                mapping=prepared['draws'][name]['textures'][slot]
                if not texture or not mapping or mapping['type']!='static_texture':continue
                golden=prepared['static_textures'][mapping['resource']]
                key=(texture['format_word'],texture['size_word'],texture['payload']['sha256'],
                     texture.get('palette',{}).get('sha256'))
                if key in checked:continue
                checked.add(key);formats.add(texture['format_word']>>8&255)
                raw=load(FRAME.parent,texture['payload'])
                palette=load(FRAME.parent,texture['palette']) if 'palette' in texture else None
                self.assertEqual(golden['source_sha256'],hashlib.sha256(raw).hexdigest())
                for level,mip in enumerate(golden['mipmaps']):
                    faces=mip['faces'] if golden['type']=='cube' else [dict(mip,face=0)]
                    for face in faces:
                        expected=load(PREPARED.parent,face)
                        status,data,layout=self.copy(texture['format_word'],raw,texture['size_word'],
                            face['face'],level,palette=palette)
                        self.assertEqual(status,OK,(name,slot,face['face'],level));self.assertEqual(data,expected)
                        self.assertEqual((layout.width,layout.height),(mip['width'],mip['height']))
                        self.assertEqual((layout.source_offset,layout.source_size),(face['source_offset'],face['source_size']))
                        self.assertEqual((layout.output_row_pitch,layout.output_size),(face['bytes_per_row'],len(expected)))
                        levels+=1;byte_count+=len(expected)
        self.assertGreater(len(checked),20);self.assertTrue({0x0b,0x0c,0x0e,0x0f,0x05,0x07}.issubset(formats))
        type(self).captured_summary=dict(textures=len(checked),face_mips=levels,compared_bytes=byte_count,
            formats=sorted(formats),capture_sha256=FRAME_SHA,prepared_sha256=hashlib.sha256(prepared_bytes).hexdigest())


if __name__=='__main__':
    unittest.main()
