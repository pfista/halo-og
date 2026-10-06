"""CPU guards for the original loading screen's bounded fixed vertex route.

The immutable failed packet proves input registers, not fixed-function output.
No graphics context is created and no Xbox hardware parity is inferred here.
"""
import ctypes as C
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'port/linux/src/metal_fixed_function.c'
CAPTURE=ROOT/'build/macos-metal/map-transition-125-attempt2/dumps/native-failure-frame464-packet.bin'
U32,F32=C.c_uint32,C.c_float
Row=U32*32
Uniform=F32*780
Matrix=F32*16

class Input(C.Structure):
    _fields_=[('render_state',C.POINTER(U32)),('texture_state',C.POINTER(Row)),
              ('world',C.POINTER(F32)),('view',C.POINTER(F32)),
              ('projection',C.POINTER(F32)),('base',C.POINTER(Uniform)),('immediate',U32)]

class Error(C.Structure):
    _fields_=[('stage',U32),('state',U32),('value',U32),('message',C.c_char_p)]

def identity():
    return Matrix(*(1.0 if r==c else 0.0 for r in range(4) for c in range(4)))

def source_prefix():
    original=(ROOT/'port/include/xdk/xdk_pdb.h').read_text()
    result='''#include <stdint.h>
#define __HALO_LINUX_PLATFORM_H
#define HALO_MACOS_NATIVE_METAL 1
typedef uint32_t DWORD;
typedef uint32_t D3DCOLOR;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
'''
    for name in ('D3DRENDERSTATETYPE','D3DTEXTURESTAGESTATETYPE','D3DFOGMODE','D3DTRANSFORMSTATETYPE'):
        result+=re.search(r'enum _'+name+r'\s*\{.*?\};',original,re.S).group(0)+'\n'
    return result

class FixedFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('clang'):raise unittest.SkipTest('clang required')
        cls.temp=tempfile.TemporaryDirectory(prefix='halo-metal-fixed-')
        cls.directory=Path(cls.temp.name)
        pref=cls.directory/'prefix.h';pref.write_text(source_prefix())
        cls.library=cls.directory/'fixed.dylib'
        subprocess.run(['clang','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                        '-include',pref,SOURCE,'-o',cls.library],check=True,capture_output=True)
        cls.lib=C.CDLL(str(cls.library))
        cls.lib.metal_fixed_function_pack_unlit_immediate.argtypes=[C.POINTER(Input),C.POINTER(Uniform),C.POINTER(Error)]
        cls.lib.metal_fixed_function_pack_unlit_immediate.restype=C.c_int
        cls.lib.metal_fixed_function_vertex_to_msl.restype=C.c_void_p

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def basic(self):
        rs=(U32*144)();ts=(Row*4)();base=Uniform()
        for stage in range(4):ts[stage][28]=stage
        rs[82]=1;rs[93]=1 # original rasterizer initialization
        base[768:776]=(320,-240,16777215,0,320,240,0,0)
        base[776]=1
        world,view=identity(),identity()
        projection=Matrix(1,0,0,0,0,1,0,0,0,0,F32(1/3).value,0,0,0,F32(1/3).value,1)
        data=Input(rs,ts,world,view,projection,C.pointer(base),1)
        return data,(rs,ts,base,world,view,projection)

    def run_pack(self,data):
        out=Uniform();error=Error()
        status=self.lib.metal_fixed_function_pack_unlit_immediate(C.byref(data),C.byref(out),C.byref(error))
        return status,out,error

    def reject(self,data,status,message):
        out=Uniform();error=Error();C.memset(C.byref(out),0x73,C.sizeof(out))
        self.assertEqual(self.lib.metal_fixed_function_pack_unlit_immediate(C.byref(data),C.byref(out),C.byref(error)),status)
        self.assertEqual(bytes(out),b'\x73'*C.sizeof(out))
        self.assertIn(message,error.message.decode())

    def test_original_loading_matrices_and_private_uniform_copy(self):
        source=(ROOT/'source/interface/progress_bar.c').read_text()
        self.assertRegex(source,r'D3DXMatrixOrthoLH\(&progress_bar_globals\.projection, 2\.f, 2\.f, -1\.f, 2\.f\)')
        data,keep=self.basic();base=keep[2]
        C.memmove(C.addressof(base)+13*16,b'\xff'*4,4) # legitimate unused original bank bits
        before=tuple(bytes(value) for value in keep)
        status,out,error=self.run_pack(data)
        self.assertEqual(status,0,error.message)
        self.assertEqual(bytes(out)[:192],b''.join(bytes(value) for value in keep[3:]))
        self.assertEqual(bytes(out)[192:],bytes(base)[192:])
        self.assertEqual(tuple(bytes(value) for value in keep),before)

    def test_individual_matrices_retain_order_and_every_component(self):
        data,keep=self.basic()
        for matrix in range(3):
            for word in range(16):
                with self.subTest(matrix=matrix,word=word):
                    keep[matrix+3][word]=F32(100*matrix+word+.125).value
                    status,out,error=self.run_pack(data)
                    self.assertEqual(status,0,error.message)
                    self.assertEqual(bytes(out)[matrix*64:(matrix+1)*64],bytes(keep[matrix+3]))

    def test_lighting_streams_and_table_fog_are_explicitly_unsupported(self):
        for field,value,status,phrase in [('immediate',0,-2,'stream/FVF'),('immediate',2,-1,'malformed'),
                                         ('lighting',1,-2,'lighting'),('fog',3,-2,'table fog')]:
            data,keep=self.basic()
            if field=='immediate':data.immediate=value
            else:keep[0][92 if field=='lighting' else 83]=value
            self.reject(data,status,phrase)

    def test_all_texture_matrix_and_generated_coordinate_guards(self):
        for stage in range(4):
            for state,value,phrase in [(9,1,'texture matrices'),(28,(stage+1)%4,'remapped'),(28,0x10000,'generated')]:
                data,keep=self.basic();keep[1][stage][state]=value
                self.reject(data,-2,phrase)

    def test_enabled_fog_combiner_inputs_reject_but_inactive_words_do_not(self):
        for state,bytes_count in ((0,4),(34,4),(8,4),(9,3)):
            for byte in range(bytes_count):
                data,keep=self.basic();keep[0][53]=1;keep[0][state]=3<<(24-8*byte)
                self.reject(data,-2,'pixel fog input')
                keep[0][82]=0
                self.assertEqual(self.run_pack(data)[0],0)
        data,keep=self.basic();keep[0][1]=0x03030303;keep[0][9]=3
        self.assertEqual(self.run_pack(data)[0],0) # inactive stage and final settings byte

    def test_every_nonfinite_transform_word_rejects_atomically(self):
        for matrix in range(3):
            for word in range(16):
                for bits in (0x7f800000,0xff800000,0x7fc12345,0xffffffff):
                    data,keep=self.basic()
                    C.memmove(C.addressof(keep[3+matrix])+word*4,struct.pack('<I',bits),4)
                    self.reject(data,-1,'nonfinite fixed-function transform')

    def test_nonfinite_tail_and_zero_or_reversed_viewport_reject_atomically(self):
        for word in range(768,780):
            data,keep=self.basic();keep[2][word]=float('nan')
            self.reject(data,-1,'nonfinite fixed-function viewport')
        for word,value in [(768,0),(768,-320),(769,0),(769,240)]:
            data,keep=self.basic();keep[2][word]=value
            self.reject(data,-1,'positive X and negative Y')

    def test_every_missing_pointer_rejects_atomically(self):
        for field in ('render_state','texture_state','world','view','projection','base'):
            data,_keep=self.basic();setattr(data,field,None)
            self.reject(data,-1,'missing fixed-function state')

    def test_captured_immediate_registers_match_original_xdk_usage(self):
        if not CAPTURE.exists():raise unittest.SkipTest('immutable failed packet required')
        import hashlib
        raw=CAPTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'3beca702cb0a92b553345436cbcb88e85bdc5025760b084548db7752ec17e3c8')
        command=11128;count=struct.unpack_from('<I',raw,command+376)[0]
        offset=struct.unpack_from('<I',raw,command+392)[0]
        self.assertEqual(count,4)
        for i in range(4):
            attrs=struct.unpack_from('<64f',raw,offset+256*i)
            self.assertEqual(attrs[12:16],(F32(254/255).value,F32(254/255).value,1,F32(.9).value))
            self.assertEqual(attrs[16:20],(55,50,0,1)) # real unrelated stale v4, never rewritten
            self.assertNotEqual(attrs[36:40],attrs[12:16])
            self.assertEqual(len(set(attrs[4*r:4*r+4] for r in (9,10,11,12))),4)
            self.assertEqual(attrs[2:4],(.5,1))

    def test_msl_uses_correct_registers_three_transforms_and_normalized_z(self):
        pointer=self.lib.metal_fixed_function_vertex_to_msl();self.assertTrue(pointer)
        try:source=C.string_at(pointer).decode()
        finally:
            libc=C.CDLL(None);libc.free.argtypes=[C.c_void_p];libc.free(pointer)
        for register in (0,3,4,9,10,11,12):self.assertIn(f'[[attribute({register})]]',source)
        for row in ('uniforms.c);','uniforms.c + 4);','uniforms.c + 8);'):self.assertIn(row,source)
        self.assertIn('output.xD0 = clamp(input.diffuse',source)
        self.assertIn('output.xT3 = input.tex3',source)
        self.assertIn('output.position = clip_position',source)
        self.assertNotIn('viewport_scale.z',source)
        self.assertNotIn('c[28]',source) # previous UI matrix is never consumed

    def test_no_gl_imports(self):
        self.assertNotRegex(subprocess.check_output(['nm','-u',self.library],text=True),r'\b_(?:gl[A-Z]|host_gl_)')

    def test_production_selection_preserves_slots_and_correct_immediate_registers(self):
        sys.path.insert(0,str(ROOT))
        from tools.test_metal_backbuffer_history import function
        front=(ROOT/'port/linux/src/d3d8_metal.c').read_text().replace('static void immediate_emit(void);','')
        original=(ROOT/'source/interface/progress_bar.c').read_text()
        definitions='\n'.join(function(front[front.index('static void immediate_emit(void) {'):] if name=='immediate_emit' else front,name) for name in (
            'vertex_shader_from_handle','D3DDevice_SetVertexShader','D3DDevice_LoadVertexShader',
            'D3DDevice_SelectVertexShader','current_program','D3DDevice_Begin','set_attribute',
            'D3DDevice_SetVertexData2f','D3DDevice_SetVertexData4f','immediate_emit'))
        draws='\n'.join(function(original[original.rindex('static void '+name+'('):],name) for name in ('do_convoluation_coords','draw_fade_layer'))
        harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define WINAPI
#define TRUE 1
#define FALSE 0
#define VERTEX_PROGRAM_SLOTS 136
#define VERTEX_SHADER_SIGNATURE 0x76736864UL
#define XGPU_VERTEX_ATTRIBUTE_COUNT 16
#define HALO_METAL_MAX_PACKET (16u*1024u*1024u)
#define HALO_METAL_MEMORY (-3)
#define HALO_METAL_UNSUPPORTED (-2)
#define D3DVSDE_DIFFUSE 3
#define D3DVSDE_VERTEX (-1)
#define D3DVSDE_TEXCOORD0 9
#define D3DVSDE_TEXCOORD1 10
#define D3DVSDE_TEXCOORD2 11
#define D3DVSDE_TEXCOORD3 12
#define D3DPT_TRIANGLEFAN 6
typedef uintptr_t DWORD;typedef int BOOL,INT,D3DPRIMITIVETYPE;typedef float FLOAT,real;
struct vertex_shader_object { struct vertex_shader_object *next;unsigned long signature;void *instructions; };
static struct { struct vertex_shader_object *vertex_shader,*program_slots[136],*vertex_shader_objects;
    unsigned long program_address;BOOL immediate_active,fixed_function_selected;D3DPRIMITIVETYPE immediate_type;
    float attributes[16][4],*immediate_vertices;unsigned long immediate_count,immediate_capacity; } device;
static jmp_buf rejected;static int status;
static void native_fail(const char *message,int value) { (void)message;status=value;longjmp(rejected,1); }
static void immediate_emit(void);
static void D3DDevice_End(void) { device.immediate_active=FALSE; }
static void *global_d3d_device;static real blur_offset=.1f;
#define IDirect3DDevice8_Begin(d,t) ((void)(d),D3DDevice_Begin(t))
#define IDirect3DDevice8_End(d) ((void)(d),D3DDevice_End())
#define IDirect3DDevice8_SetVertexData4f(d,r,a,b,c,w) ((void)(d),D3DDevice_SetVertexData4f(r,a,b,c,w))
'''+definitions+'\n'+draws+r'''
int main(int argc,char **argv) {
    assert(argc==2);int words=1;
    struct vertex_shader_object b={0,VERTEX_SHADER_SIGNATURE,&words},a={&b,VERTEX_SHADER_SIGNATURE,&words};
    device.vertex_shader_objects=&a;
    D3DDevice_SetVertexShader((DWORD)&a);D3DDevice_LoadVertexShader((DWORD)&b,7);
    D3DDevice_SelectVertexShader((DWORD)&b,7);assert(current_program()==&b && !device.fixed_function_selected);
    D3DDevice_SetVertexShader(0);assert(device.fixed_function_selected && current_program()==&b);
    assert(device.program_slots[0]==&a && device.program_slots[7]==&b && device.program_address==7);
    D3DDevice_LoadVertexShader((DWORD)&a,19);assert(device.fixed_function_selected);
    D3DDevice_SelectVertexShader(0,7);assert(!device.fixed_function_selected && current_program()==&b);
    D3DDevice_SetVertexShader(0);D3DDevice_SetVertexShader((DWORD)&a);
    assert(!device.fixed_function_selected && current_program()==&a && device.program_address==0);
    D3DDevice_SetVertexShader(0);D3DDevice_SelectVertexShader((DWORD)&b,7);
    assert(!device.fixed_function_selected && current_program()==&b);
    for(uintptr_t handle=1;handle<0x2000;handle++) {
        assert(!vertex_shader_from_handle(handle));
        if(!setjmp(rejected)) { D3DDevice_SetVertexShader(handle);assert(0); }
        assert(status==HALO_METAL_UNSUPPORTED);
    }
    unsigned char expected[1024];FILE *file=fopen(argv[1],"rb");assert(file);
    assert(fread(expected,1,sizeof(expected),file)==sizeof(expected));assert(!fclose(file));
    memcpy(device.attributes,expected,256);D3DDevice_SetVertexShader(0);draw_fade_layer(0,0,.9f);
    assert(device.fixed_function_selected && device.immediate_count==4 && !device.immediate_active);
    assert(!memcmp(device.immediate_vertices,expected,sizeof(expected)));
    free(device.immediate_vertices);return 0;
}
'''
        source=self.directory/'selection.c';source.write_text(harness)
        binary=self.directory/'selection'
        subprocess.run(['clang','-std=c11','-O1','-ffp-contract=off','-Wall','-Wextra','-Werror',
                        '-fsanitize=address,undefined','-g',source,'-o',binary],check=True,capture_output=True)
        if not CAPTURE.exists():raise unittest.SkipTest('immutable failed packet required')
        raw=CAPTURE.read_bytes();offset=struct.unpack_from('<I',raw,11128+392)[0]
        expected=self.directory/'registers.bin';expected.write_bytes(raw[offset:offset+1024])
        subprocess.run([binary,expected],check=True,capture_output=True)

def build_ilp32(output):
    """Freeze and build the real 32-bit guest CPU module; no Metal commands."""
    sys.path.insert(0,str(ROOT))
    from tools.android_build import GUEST_ABI_FLAGS
    llvm=Path('/opt/homebrew/opt/llvm@22/bin');linker=Path('/opt/homebrew/opt/lld@22/bin/ld.lld')
    plugin=ROOT.parent/'pfista-halo-macos/build/macos/guest_rebase.dylib'
    executor=ROOT/'build/metal-poc/host-opaque-mad-corrected-validation/host_metal_probe'
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    sources=[Path(__file__).resolve(),SOURCE,ROOT/'port/linux/src/metal_fixed_function.h',
             ROOT/'port/linux/src/d3d8_metal.c',ROOT/'port/linux/src/metal_draw_state.h',ROOT/'port/linux/src/xgpu.h',
             ROOT/'port/linux/src/xgpu_msl.h',ROOT/'port/linux/src/platform.h',
             ROOT/'port/macos/include/halo_metal_abi.h',ROOT/'port/include/xdk/xdk_pdb.h',
             ROOT/'source/interface/progress_bar.c',ROOT/'tools/android_build.py',
             ROOT/'tools/android_asm_convert.py',ROOT/'tools/android_imports.py',
             ROOT/'port/macos/metal_imports.list',CAPTURE]
    before={str(path):sha(path) for path in sources}
    frozen=output/'source-snapshot'
    for path in sources:
        destination=frozen/path.relative_to(ROOT);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,destination)
    cases=[]
    fixture=FixedFunctionTests()
    def case(change=None,status=0):
        data,keep=fixture.basic()
        C.memmove(C.addressof(keep[2])+13*16,b'\xff'*4,4)
        if change:change(data,keep)
        expected=bytes(keep[2]);expected=b''.join(bytes(value) for value in keep[3:])+expected[192:]
        if status:expected=b'\x73'*3120
        cases.append(bytes(keep[0])+bytes(keep[1])+b''.join(bytes(value) for value in keep[3:])+
                     bytes(keep[2])+struct.pack('<Ii',data.immediate,status)+expected)
    case()
    for matrix in range(3):
        for word in range(16):
            case(lambda _d,k,m=matrix,w=word:k[m+3].__setitem__(w,100*m+w+.125))
            for bits in (0x7f800000,0xff800000,0x7fc12345,0xffffffff):
                case(lambda _d,k,m=matrix,w=word,b=bits:C.memmove(C.addressof(k[m+3])+w*4,struct.pack('<I',b),4),-1)
    for stage in range(4):
        case(lambda _d,k,s=stage:k[1][s].__setitem__(9,1),-2)
        case(lambda _d,k,s=stage:k[1][s].__setitem__(28,(s+1)%4),-2)
        case(lambda _d,k,s=stage:k[1][s].__setitem__(28,0x10000),-2)
    for state,value in ((92,1),(83,3)):case(lambda _d,k,s=state,v=value:k[0].__setitem__(s,v),-2)
    for state,count in ((0,4),(34,4),(8,4),(9,3)):
        for byte in range(count):
            case(lambda _d,k,s=state,b=byte:(k[0].__setitem__(53,1),k[0].__setitem__(s,3<<(24-8*b))),-2)
    for value,status in ((0,-2),(2,-1)):case(lambda d,_k,v=value:setattr(d,'immediate',v),status)
    for word in range(768,780):case(lambda _d,k,w=word:k[2].__setitem__(w,float('nan')),-1)
    for word,value in ((768,0),(768,-320),(769,0),(769,240)):
        case(lambda _d,k,w=word,v=value:k[2].__setitem__(w,v),-1)
    binary=output/'cases.bin';binary.write_bytes(b''.join(cases))
    assert all(len(value)==7528 for value in cases)
    (output/'cases.s').write_text('.section .rodata\n.balign 16\n.global fixed_cases\nfixed_cases:\n.incbin "'+str(binary)+'"\n')
    include=output/'freestanding';include.mkdir()
    (include/'math.h').write_text('#define isfinite(x) __builtin_isfinite(x)\n')
    (include/'string.h').write_text('void *memcpy(void*,const void*,unsigned long);\n')
    (include/'stdlib.h').write_text('void *malloc(unsigned long);\n')
    source=output/'guest.c'
    from tools.test_metal_backbuffer_history import function
    frontend=(ROOT/'port/linux/src/d3d8_metal.c').read_text()
    selector='\n'.join(function(frontend,name) for name in (
        'vertex_shader_from_handle','D3DDevice_SetVertexShader','D3DDevice_LoadVertexShader',
        'D3DDevice_SelectVertexShader','current_program'))
    source.write_text(source_prefix()+'\n#include "'+str(frozen/'port/linux/src/metal_fixed_function.c')+'"\n'+'''
_Static_assert(sizeof(void*)==4 && sizeof(unsigned long)==4,"actual ILP32 guest");
#define WINAPI
#define VERTEX_PROGRAM_SLOTS 136
#define VERTEX_SHADER_SIGNATURE 0x76736864UL
struct vertex_shader_object { struct vertex_shader_object *next;unsigned long signature;void *instructions; };
static struct { struct vertex_shader_object *vertex_shader,*program_slots[136],*vertex_shader_objects;
    unsigned long program_address;BOOL fixed_function_selected; } device;
_Noreturn static void native_fail(const char *message,int status) { (void)message;(void)status;for(;;){} }
'''+selector+'''
static uint32_t selection_test(void) {
    int words=1;struct vertex_shader_object b={0,VERTEX_SHADER_SIGNATURE,&words},a={&b,VERTEX_SHADER_SIGNATURE,&words};
    device.vertex_shader_objects=&a;D3DDevice_SetVertexShader((DWORD)&a);D3DDevice_LoadVertexShader((DWORD)&b,7);
    D3DDevice_SelectVertexShader((DWORD)&b,7);
    if(current_program()!=&b || device.fixed_function_selected)return 1;
    D3DDevice_SetVertexShader(0);
    if(!device.fixed_function_selected || current_program()!=&b || device.program_address!=7)return 2;
    if(device.program_slots[0]!=&a || device.program_slots[7]!=&b)return 3;
    D3DDevice_LoadVertexShader((DWORD)&a,19);if(!device.fixed_function_selected)return 4;
    D3DDevice_SelectVertexShader(0,7);if(device.fixed_function_selected || current_program()!=&b)return 5;
    D3DDevice_SetVertexShader(0);D3DDevice_SetVertexShader((DWORD)&a);
    if(device.fixed_function_selected || current_program()!=&a || device.program_address!=0)return 6;
    D3DDevice_SetVertexShader(0);D3DDevice_SelectVertexShader((DWORD)&b,7);
    if(device.fixed_function_selected || current_program()!=&b)return 7;
    for(DWORD handle=1;handle<0x2000;handle++)if(vertex_shader_from_handle(handle))return 8;
    return 0;
}
struct test_case { uint32_t rs[144],ts[4][32];float matrices[3][16];
    struct metal_draw_vertex_uniforms base;uint32_t immediate;int32_t status;unsigned char expected[3120]; };
_Static_assert(sizeof(struct test_case)==7528,"immutable CPU case ABI");
extern const struct test_case fixed_cases['''+str(len(cases))+'''];
void *memcpy(void *destination,const void *source,unsigned long n) {
    unsigned char *d=destination;const unsigned char *s=source;for(unsigned long i=0;i<n;i++)d[i]=s[i];return d;
}
void *malloc(unsigned long n) { (void)n;return 0; } /* unused source-emission function */
uint32_t guest_test(uint32_t unused) {
    (void)unused;
    uint32_t selection=selection_test();if(selection)return 9000+selection;
    for(uint32_t i=0;i<'''+str(len(cases))+''';i++) {
        const struct test_case *test=fixed_cases+i;struct metal_fixed_function_input input={
            test->rs,test->ts,test->matrices[0],test->matrices[1],test->matrices[2],&test->base,test->immediate};
        struct metal_draw_vertex_uniforms output;struct metal_draw_state_error error;
        unsigned char *bytes=(unsigned char *)&output;for(unsigned j=0;j<3120;j++)bytes[j]=0x73;
        int status=metal_fixed_function_pack_unlit_immediate(&input,&output,&error);
        if(status!=test->status)return 1000+i;
        for(unsigned j=0;j<3120;j++)if(bytes[j]!=test->expected[j])return 2000+i;
        if(status && !error.message)return 3000+i;
    }
    return 0;
}
''')
    def run(*args):
        result=subprocess.run([str(arg) for arg in args],cwd=ROOT,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr or result.stdout)
    resource=Path(subprocess.check_output([llvm/'clang','-print-resource-dir'],text=True).strip())
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-O2','-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-I',include,'-std=gnu11','-Wall','-Wextra','-Werror','-emit-llvm','-S',source,'-o',output/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',output/'guest.ll','-o',output/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',output/'guest.rebased.ll','-o',output/'guest.darwin.s')
    run(sys.executable,'tools/android_asm_convert.py',output/'guest.darwin.s',output/'guest.s')
    for name in ('guest','cases'):run(llvm/'clang','--target=aarch64-linux-android','-c',output/(name+'.s'),'-o',output/(name+'.o'))
    run(sys.executable,'tools/android_imports.py','--host-table',output/'host_import_table.c',output/'imports.s','port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',output/'imports.s','-o',output/'imports.o')
    script=output/'guest.ld';script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',script,output/'guest.o',output/'cases.o',output/'imports.o','-o',output/'guest.elf')
    symbols={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output(
        [llvm/'llvm-nm','--defined-only',output/'guest.elf'],text=True).splitlines() if len(line.split())==3}
    copied=output/'host_ilp32_probe';shutil.copy2(executor,copied)
    command=[str(copied),str(output/'guest.elf'),*[hex(symbols[name]) for name in
        ('__host_import_table','__host_import_names','__host_import_count')],'0x800000']
    assert before=={str(path):sha(path) for path in sources},'source changed during preparation'
    proof=dict(schema_version=1,kind='metal_fixed_function_cpu_ilp32',complete=False,passed=False,
        case_count=len(cases),positive_cases=49,atomic_reject_cases=len(cases)-49,
        production_selection_controls=8,small_integer_handle_lookup_controls=8191,
        source_sha256=before,prepared_sha256={str(path):sha(path) for path in output.rglob('*') if path.is_file()},
        toolchain_sha256={str(path):sha(path) for path in (llvm/'clang',llvm/'opt',llvm/'llc',linker,plugin)},
        execution_command=command,limits=['CPU packing only; no Metal initialization or GPU commands',
            'Xbox physical fixed-function pipeline and complete loading-screen pixels unproven'])
    (output/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'prepared':str(output/'prepared.json'),'execution_command':command},indent=2))

if __name__=='__main__':
    if '--ilp32' in sys.argv:
        parser=argparse.ArgumentParser();parser.add_argument('--ilp32',action='store_true')
        parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
        build_ilp32(args.output)
    else:unittest.main()
