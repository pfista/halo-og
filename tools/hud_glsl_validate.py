#!/usr/bin/env python3
"""Portable EGL/GLES checks of production HUD shaders, samplers and mip borders.

macOS selects the bundled ANGLE Metal backend. Linux defaults to surfaceless
EGL; --egl/--gles can select another EGL implementation, including ANGLE.
Uses original meter/reference cases shared with the native Metal validation.
"""
import argparse
import copy
import ctypes as C
import ctypes.util
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metal_shader_validate as shader
from metal_hud_hires_validate import border_fixtures, hud_fixtures, text_fixtures
from text_glyph_fixtures import real_text_fixtures

ROOT = shader.ROOT
PORT = ROOT / 'port/linux/src'
U, I, F, P = C.c_uint32, C.c_int32, C.c_float, C.c_void_p
GL = dict(TEXTURE_2D=0x0DE1, RGBA=0x1908, FLOAT=0x1406, RGBA8=0x8058,
          UNSIGNED_BYTE=0x1401, RGBA32F=0x8814, FRAMEBUFFER=0x8D40,
          COLOR_ATTACHMENT0=0x8CE0, FRAMEBUFFER_COMPLETE=0x8CD5,
          TEXTURE0=0x84C0, COLOR_BUFFER_BIT=0x4000, TRIANGLES=4,
          VERTEX_SHADER=0x8B31, FRAGMENT_SHADER=0x8B30, COMPILE_STATUS=0x8B81,
          LINK_STATUS=0x8B82, BLEND=0x0BE2, CONSTANT_COLOR=0x8001, SRC_ALPHA=0x0302,
          ONE_MINUS_SRC_ALPHA=0x0303, TEXTURE_MAX_LEVEL=0x813D)
VERTEX = '''#version 300 es
precision highp float;
uniform vec4 d0,d1,b0,b1,t[4],test_delta;uniform float fog;
out vec4 xD0,xD1,xB0,xB1,xT0,xT1,xT2,xT3;out float xFog;
void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);
gl_Position=vec4(p*2.0-1.0,0.5,1.0);xD0=d0;xD1=d1;xB0=b0;xB1=b1;
xT0=t[0]+vec4((p*4.0-vec2(2.5))*test_delta.xy,0.0,0.0);
xT1=t[1];xT2=t[2];xT3=t[3];xFog=fog;}
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    paths=[Path(__file__).resolve(),ROOT/'tools/metal_hud_hires_validate.py',
           ROOT/'tools/metal_shader_validate.py',PORT/'nv2a_psh.c',PORT/'nv2a_vsh.c',
           PORT/'d3d8_gl.c',PORT/'xgpu_shader_standalone.h',PORT/'xgpu_msl.h',
           PORT/'xbox_textures.c',PORT/'text_hires.c',PORT/'text_hires.h',
           ROOT/'tools/text_glyph_fixtures.py',ROOT/'tools/test_text_hires.py',
           ROOT/'port/third_party/stb/stb_truetype.h',
           ROOT/'source/text/draw_string.c',ROOT/'source/rasterizer/rasterizer_text.c',
           ROOT/'source/rasterizer/xbox/rasterizer_xbox_text.c',
           ROOT/'port/macos/metal-poc/shader_text.c',
           ROOT/'source/rasterizer/xbox/rasterizer_xbox_dynavobgeom.c']
    paths += sorted((ROOT/'port/assets/fonts').glob('*.ttf'))
    paths += [ROOT/'port/assets/fonts/fonts.json']
    return {str(p.relative_to(ROOT)):digest(p) for p in paths}


def function(source, name):
    match = re.search(r'static\s+\w+\s+' + name + r'\([^;]+?\)\s*\{', source, re.S)
    if not match:
        raise RuntimeError('Missing production function ' + name)
    start, depth = match.start(), 0
    for at in range(source.index('{', start), len(source)):
        depth += (source[at] == '{') - (source[at] == '}')
        if not depth:
            return source[start:at + 1]
    raise RuntimeError('Unterminated production function ' + name)


def libraries(egl=None, gles=None):
    if sys.platform == 'darwin':
        angle = ROOT / 'build/macos/angle/dist'
        egl = egl or angle / 'EGL.xcframework/macos-arm64/libEGL.framework/libEGL'
        gles = gles or angle / 'GLESv2.xcframework/macos-arm64/libGLESv2.framework/libGLESv2'
    else:
        egl = egl or ctypes.util.find_library('EGL') or 'libEGL.dll'
        gles = gles or ctypes.util.find_library('GLESv2') or 'libGLESv2.dll'
    loader = C.WinDLL if sys.platform == 'win32' else C.CDLL
    return loader(str(egl)), loader(str(gles))


class Gles:
    def __init__(self, egl, gles, backend=None):
        self.egl, self.gles = egl, gles
        for name, result, args in (
            ('eglGetProcAddress', P, [C.c_char_p]), ('eglGetError', U, []),
            ('eglInitialize', U, [P, P, P]), ('eglBindAPI', U, [U]),
            ('eglChooseConfig', U, [P, P, P, I, P]),
            ('eglCreateContext', P, [P, P, P, P]),
            ('eglCreatePbufferSurface', P, [P, P, P]), ('eglMakeCurrent', U, [P, P, P, P]),
            ('eglGetDisplay', P, [P]), ('eglDestroySurface', U, [P, P]),
            ('eglDestroyContext', U, [P, P]), ('eglTerminate', U, [P])):
            call = getattr(egl, name);call.restype=result;call.argtypes=args
        backend = backend or ('angle-metal' if sys.platform == 'darwin' else
                              'angle-default' if sys.platform == 'win32' else 'surfaceless')
        platform = egl.eglGetProcAddress(b'eglGetPlatformDisplayEXT')
        if backend != 'default' and platform:
            proto = C.WINFUNCTYPE if sys.platform == 'win32' else C.CFUNCTYPE
            get_display = proto(P, U, P, C.POINTER(I))(platform)
            attrs = (I * 3)(0x3203, 0x3489, 0x3038) if backend == 'angle-metal' else (I * 1)(0x3038)
            self.display = get_display(0x31DD if backend == 'surfaceless' else 0x3202, None, attrs)
        else:
            self.display = egl.eglGetDisplay(None)
        self.check(egl.eglInitialize(self.display, None, None), 'EGL initialization')
        self.check(egl.eglBindAPI(0x30A0), 'OpenGL ES API')
        attrs = (I * 15)(0x3033, 1, 0x3040, 0x40, 0x3024, 8, 0x3023, 8,
                           0x3022, 8, 0x3021, 8, 0x3025, 0, 0x3038)
        config, count = P(), I()
        self.check(egl.eglChooseConfig(self.display, attrs, C.byref(config), 1, C.byref(count)) and count.value, 'EGL config')
        self.context = egl.eglCreateContext(self.display, config, None, (I * 3)(0x3098, 3, 0x3038))
        self.surface = egl.eglCreatePbufferSurface(self.display, config, (I * 5)(0x3057, 4, 0x3056, 4, 0x3038))
        self.check(self.context and self.surface and egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context), 'EGL pbuffer context')
        declarations = {
            'GetString': (C.c_char_p, [U]), 'GetError': (U, []), 'Viewport': (None, [I, I, I, I]),
            'CreateShader': (U, [U]), 'ShaderSource': (None, [U, I, P, P]),
            'CompileShader': (None, [U]), 'GetShaderiv': (None, [U, U, P]),
            'GetShaderInfoLog': (None, [U, I, P, P]), 'CreateProgram': (U, []),
            'AttachShader': (None, [U, U]), 'LinkProgram': (None, [U]),
            'GetProgramiv': (None, [U, U, P]), 'GetProgramInfoLog': (None, [U, I, P, P]),
            'DeleteShader': (None, [U]), 'UseProgram': (None, [U]),
            'GetUniformLocation': (I, [U, C.c_char_p]), 'Uniform1i': (None, [I, I]),
            'Uniform1fv': (None, [I, I, P]), 'Uniform4fv': (None, [I, I, P]),
            'GenTextures': (None, [I, P]), 'BindTexture': (None, [U, U]),
            'TexImage2D': (None, [U, I, I, I, I, I, U, U, P]),
            'TexParameteri': (None, [U, U, I]), 'ColorMask': (None, [C.c_ubyte] * 4),
            'GenerateMipmap': (None, [U]), 'DeleteTextures': (None, [I, P]),
            'ActiveTexture': (None, [U]), 'GenFramebuffers': (None, [I, P]),
            'BindFramebuffer': (None, [U, U]), 'FramebufferTexture2D': (None, [U, U, U, U, I]),
            'CheckFramebufferStatus': (U, [U]), 'ClearColor': (None, [F, F, F, F]),
            'Clear': (None, [U]), 'DrawArrays': (None, [U, I, I]),
            'ReadPixels': (None, [I, I, I, I, U, U, P]), 'Enable': (None, [U]),
            'Disable': (None, [U]), 'BlendColor': (None, [F, F, F, F]),
            'BlendFunc': (None, [U, U]), 'GenSamplers': (None, [I, P]),
            'BindSampler': (None, [U, U]), 'SamplerParameteri': (None, [U, U, I]),
            'SamplerParameterf': (None, [U, U, F]), 'SamplerParameterfv': (None, [U, U, P])}
        for name, (result, args) in declarations.items():
            call = getattr(gles, 'gl' + name);call.restype=result;call.argtypes=args
            setattr(self, name, call)
        self.renderer = self.GetString(0x1F01).decode()
        self.border_clamp = 'GL_EXT_texture_border_clamp' in self.GetString(0x1F03).decode()
        self.Viewport(0, 0, 4, 4)
        color, fbo = U(), U()
        self.GenTextures(1, C.byref(color));self.BindTexture(GL['TEXTURE_2D'], color)
        self.TexImage2D(GL['TEXTURE_2D'], 0, GL['RGBA32F'], 4, 4, 0, GL['RGBA'], GL['FLOAT'], None)
        self.GenFramebuffers(1, C.byref(fbo));self.BindFramebuffer(GL['FRAMEBUFFER'], fbo)
        self.FramebufferTexture2D(GL['FRAMEBUFFER'], GL['COLOR_ATTACHMENT0'], GL['TEXTURE_2D'], color, 0)
        self.check(self.CheckFramebufferStatus(GL['FRAMEBUFFER']) == GL['FRAMEBUFFER_COMPLETE'], 'RGBA32F target')
        self.sampler = U();self.GenSamplers(1, C.byref(self.sampler));self.BindSampler(0, self.sampler)

    def check(self, ok, reason):
        if not ok:
            raise RuntimeError(f'{reason} failed: EGL error 0x{self.egl.eglGetError():04x}')

    def program(self, source):
        objects = []
        for kind, text in ((GL['VERTEX_SHADER'], VERTEX), (GL['FRAGMENT_SHADER'], source)):
            obj = self.CreateShader(kind);data=(C.c_char_p * 1)(text.encode())
            self.ShaderSource(obj, 1, data, None);self.CompileShader(obj)
            status=I();self.GetShaderiv(obj, GL['COMPILE_STATUS'], C.byref(status))
            if not status.value:
                log=C.create_string_buffer(32768);self.GetShaderInfoLog(obj,len(log),None,log)
                raise RuntimeError(log.value.decode())
            objects.append(obj)
        program=self.CreateProgram()
        for obj in objects:self.AttachShader(program,obj)
        self.LinkProgram(program);status=I();self.GetProgramiv(program,GL['LINK_STATUS'],C.byref(status))
        if not status.value:
            log=C.create_string_buffer(32768);self.GetProgramInfoLog(program,len(log),None,log)
            raise RuntimeError(log.value.decode())
        for obj in objects:self.DeleteShader(obj)
        return program

    def uniform(self, program, name, value):
        flat=[]
        for item in value if isinstance(value,list) else [value]:
            flat.extend(item if isinstance(item,list) else [item])
        location=self.GetUniformLocation(program,name.encode());data=(F * len(flat))(*flat)
        if len(flat)==1:self.Uniform1fv(location,1,data)
        else:self.Uniform4fv(location,len(flat)//4,data)

    def close(self):
        self.egl.eglMakeCurrent(self.display,None,None,None)
        self.egl.eglDestroySurface(self.display,self.surface)
        self.egl.eglDestroyContext(self.display,self.context)
        self.egl.eglTerminate(self.display)


def production_sampler(out, gl):
    source=(PORT / 'd3d8_gl.c').read_text()
    xdk=(ROOT / 'port/include/xdk/xdk_pdb.h').read_text()
    enums='\n'.join(re.search(r'enum _'+name+r'\s*\{.*?\};',xdk,re.S)[0] for name in
        ('D3DTEXTUREADDRESS','D3DTEXTUREFILTERTYPE','D3DTEXTURESTAGESTATETYPE'))
    constants=dict(GL_NEAREST=0x2600, GL_LINEAR=0x2601, GL_NEAREST_MIPMAP_NEAREST=0x2700,
        GL_LINEAR_MIPMAP_NEAREST=0x2701, GL_NEAREST_MIPMAP_LINEAR=0x2702,
        GL_LINEAR_MIPMAP_LINEAR=0x2703, GL_TEXTURE_MIN_FILTER=0x2801,
        GL_TEXTURE_MAG_FILTER=0x2800, GL_TEXTURE_WRAP_S=0x2802, GL_TEXTURE_WRAP_T=0x2803,
        GL_TEXTURE_WRAP_R=0x8072, GL_REPEAT=0x2901, GL_MIRRORED_REPEAT=0x8370,
        GL_CLAMP_TO_EDGE=0x812F, GL_CLAMP_TO_BORDER=0x812D, GL_TEXTURE_MIN_LOD=0x813A,
        GL_TEXTURE_MAX_ANISOTROPY_EXT=0x84FE, GL_TEXTURE_BORDER_COLOR=0x1004, GL_TEXTURE_2D=0x0DE1)
    prefix='''#include <stdint.h>
#include <string.h>
#define HALO_ANDROID 1
typedef uint32_t DWORD;typedef int BOOL;typedef unsigned GLuint,GLenum;typedef int GLint;
#define TRUE 1
#define FALSE 0
#define D3DTSS_MAXSTAGES 4
static void (*fixture_i)(GLuint,GLenum,GLint);
static void (*fixture_f)(GLuint,GLenum,float);
static void (*fixture_fv)(GLuint,GLenum,const float*);
#define glSamplerParameteri fixture_i
#define glSamplerParameterf fixture_f
#define glSamplerParameterfv fixture_fv
static struct { int anisotropy,border_clamp; } xgpu_capabilities;
static struct { GLuint samplers[4]; } device;
static DWORD D3D__TextureState[4][32];
struct xgpu_texture_description { unsigned long levels; int hires; };
struct nv2a_pixel_shader_key { unsigned char border_axes[4],border_filter[4]; };
static void color_to_vec4(DWORD word,float v[4]) {
v[0]=((word>>16)&255)/255.f;v[1]=((word>>8)&255)/255.f;v[2]=(word&255)/255.f;v[3]=(word>>24)/255.f;}
'''
    prefix+='\n'.join(f'#define {name} {value}' for name,value in constants.items())+'\n'+enums+'\n'
    prefix+='\n'.join(function(source,name) for name in
        ('address_mode','effective_texture_lod_bias','configure_sampler','texture_border_key'))
    prefix+='''
void fixture_functions(void *i,void *f,void *fv) {fixture_i=i;fixture_f=f;fixture_fv=fv;}
unsigned fixture_configure(unsigned sampler,const DWORD *state,unsigned levels,int hires,int native_border,unsigned *axes,unsigned *filter) {
device.samplers[0]=sampler;memcpy(D3D__TextureState[0],state,128);xgpu_capabilities.border_clamp=native_border;
configure_sampler(0,levels>1,hires);struct xgpu_texture_description description={levels,hires};
struct nv2a_pixel_shader_key key={0};texture_border_key(&key,0,GL_TEXTURE_2D,&description);
*axes=key.border_axes[0];*filter=key.border_filter[0];return effective_texture_lod_bias(hires,state[D3DTSS_MIPMAPLODBIAS]);}
'''
    path=out / 'sampler.c';path.write_text(prefix)
    library=out / 'sampler.dylib'
    shader.run('clang','-std=c11','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',path,'-o',library)
    lib=C.CDLL(str(library));lib.fixture_functions.argtypes=[P,P,P]
    lib.fixture_functions(C.cast(gl.SamplerParameteri,P),C.cast(gl.SamplerParameterf,P),C.cast(gl.SamplerParameterfv,P))
    lib.fixture_configure.argtypes=[U,C.POINTER(U),U,I,I,C.POINTER(U),C.POINTER(U)]
    lib.fixture_configure.restype=U
    return lib


def gl_fixtures():
    for key,f in hud_fixtures():
        f['hires']=True;yield key,f
    for key,f in border_fixtures():
        # The forced GLES fallback is always hires trilinear; integer nearest
        # controls still match because adjacent mips have zero interpolation.
        f['hires']=True;f['forced_border_fallback']=True
        f['test_delta']=[math.exp2(f['textures'][0]['lod'])/8,0,0,0]
        yield key,f
    for key,f in text_fixtures():
        f['hires']=True;f['single_mip']=True
        yield key,f
    colors=([51,102,153,204],[204,153,102,51])
    for hires in (False,True):
        for u in (.25,.375,.5,.75):
            key=shader.PixelKey();key.texture_modes=1;key.sampler_type[0]=1
            key.combiner_state[8]=8;key.combiner_state[9]=0x1800
            f=copy.deepcopy(shader.fixture(f'hud-original-point-vs-hires-linear-{int(hires)}-{u}'))
            f['hires']=hires;f['point_control']=True
            f['inputs']['t'][0]=[u,.5,0,1]
            f['textures'][0]=dict(kind=1,width=2,height=1,rgba=colors[0]+colors[1])
            weight=min(1,max(0,u*2-.5)) if hires else int(u>=.5)
            f['expected']=[(a*(1-weight)+b*weight)/255 for a,b in zip(*colors)]
            yield key,f
    for hires in (False,True):
        key=shader.PixelKey();key.texture_modes=1;key.sampler_type[0]=1
        key.combiner_state[8]=8;key.combiner_state[9]=0x1800
        f=copy.deepcopy(shader.fixture(f'hud-original-bias-vs-hires-unbiased-{int(hires)}'))
        f['hires']=hires;f['bias_control']=True;f['raw_bias']=1.
        f['test_delta']=[.25,0,0,0];f['inputs']['t'][0]=[.5,.5,0,1]
        colors=([17,34,51,68],[51,68,85,102],[85,102,119,136],[119,136,153,170])
        f['textures'][0]=dict(kind=1,width=8,height=8,
            mipmaps=[dict(rgba=list(color)*(size*size)) for color,size in zip(colors,(8,4,2,1))])
        f['expected']=[c/255 for c in colors[1 if hires else 2]]
        yield key,f


def validate(out, egl=None, gles=None, backend=None):
    out.mkdir(parents=True,exist_ok=True)
    before=source_hashes()
    gl=Gles(*libraries(egl,gles),backend=backend)
    try:
        sampler=production_sampler(out,gl);emitter=shader.build_library(out)
        programs={};tests=[];maximum=0.;discarded=0
        cases=itertools.chain(gl_fixtures(),real_text_fixtures(out))
        for provider_key,f in cases:
            if f.get('real_glyph'):f['hires']=True;f['single_mip']=True
            key=shader.PixelKey.from_buffer_copy(bytes(provider_key))
            texture=f['textures'][0];width,height=texture['width'],texture['height']
            state=(U*32)();state[10]=state[11]=state[12]=3
            state[13]=state[14]=state[15]=1;state[18]=1
            if f.get('bias_control'):state[13]=state[14]=state[15]=2
            if f.get('forced_border_fallback'):state[10]=state[11]=4;state[29]=0x46000000
            state[16]=struct.unpack('<I',struct.pack('<f',f.get('raw_bias',0.)))[0]
            levels=texture.get('mipmaps');count=1 if f.get('single_mip') else len(levels) if levels else (1+int(math.log2(max(width,height))) if f['hires'] else 1)
            axes,filtering=U(),U()
            bias=sampler.fixture_configure(gl.sampler,state,count,int(f['hires']),0,C.byref(axes),C.byref(filtering))
            key.border_axes[0]=axes.value;key.border_filter[0]=filtering.value
            if f.get('forced_border_fallback') and (axes.value,filtering.value)!=(3,4):
                raise RuntimeError('Production hires border fallback key was not enabled')
            f['uniforms']['texture_lod_bias'][0]=struct.unpack('<f',struct.pack('<I',bias))[0]
            identity=bytes(key)
            if identity not in programs:
                source=shader.generated(emitter.nv2a_pixel_shader_to_glsl,C.byref(key))
                name=f'pixel-{len(programs):02}.glsl';(out/name).write_text(source)
                programs[identity]=(gl.program(source),name)
            program,name=programs[identity];gl.UseProgram(program)
            for n in ('d0','d1','b0','b1','t','fog'):gl.uniform(program,n,f['inputs'][n])
            gl.uniform(program,'test_delta',f.get('test_delta',[0,0,0,0]))
            names=dict(c0='ps_c0',c1='ps_c1',final_c0='ps_final_c0',final_c1='ps_final_c1')
            for n,value in f['uniforms'].items():gl.uniform(program,names.get(n,n),value)
            tex=U();gl.GenTextures(1,C.byref(tex));gl.ActiveTexture(GL['TEXTURE0']);gl.BindTexture(GL['TEXTURE_2D'],tex)
            for level,mip in enumerate(levels or [texture]):
                data=(C.c_ubyte*len(mip['rgba']))(*mip['rgba'])
                gl.TexImage2D(GL['TEXTURE_2D'],level,GL['RGBA8'],max(1,width>>level),max(1,height>>level),0,GL['RGBA'],GL['UNSIGNED_BYTE'],data)
            if f.get('single_mip'):gl.TexParameteri(GL['TEXTURE_2D'],GL['TEXTURE_MAX_LEVEL'],0)
            elif not levels and f['hires']:gl.GenerateMipmap(GL['TEXTURE_2D'])
            gl.Uniform1i(gl.GetUniformLocation(program,b'tex0'),0)
            gl.ColorMask(1,1,1,1)
            clear=f.get('clear_color',[0,0,0,0]);gl.ClearColor(*clear);gl.Clear(GL['COLOR_BUFFER_BIT'])
            if 'meter_blend' in f:
                gl.Enable(GL['BLEND']);gl.BlendColor(*f['meter_blend']);gl.BlendFunc(GL['CONSTANT_COLOR'],GL['SRC_ALPHA'])
            elif f.get('text_blend'):
                gl.Enable(GL['BLEND']);gl.BlendFunc(GL['SRC_ALPHA'],GL['ONE_MINUS_SRC_ALPHA']);gl.ColorMask(1,1,1,0)
            else:gl.Disable(GL['BLEND'])
            gl.DrawArrays(GL['TRIANGLES'],0,3);actual=(F*4)();gl.ReadPixels(2,2,1,1,GL['RGBA'],GL['FLOAT'],actual)
            error_code=gl.GetError()
            if error_code:raise RuntimeError(f'{f["name"]}: GL error 0x{error_code:04x}')
            expected=clear if f.get('discard') else f['expected']
            tolerance=f.get('float_tolerance',.00002)
            error=max(abs(a-b) for a,b in zip(actual,expected));maximum=max(maximum,error)
            if not all(math.isfinite(a) for a in actual) or error>=tolerance:
                raise RuntimeError(f'{f["name"]}: actual {list(actual)}, expected {expected}, error {error}')
            discarded+=bool(f.get('discard'));f['shader']=name;tests.append(f)
            gl.DeleteTextures(1,C.byref(tex))
        if before!=source_hashes():
            raise RuntimeError('HUD shader/sampler/fixture sources changed during GPU validation')
        proof=dict(passed=True,backend='EGL-GLES',renderer=gl.renderer,pixel_cases=len(tests),
            compiled_programs=len(programs),discard_cases=discarded,max_float_error=maximum,
            forced_hires_mip_border_cases=77,original_point_controls=4,hires_filter_controls=4,
            bias_controls=2,production_sampler=True,native_border_available=gl.border_clamp,
            synthetic_text_cases=30,real_glyph_cases=24,
            source_sha256=before,
            shader_sha256={name:digest(out/name) for _,name in programs.values()},
            sampler_source_sha256=digest(out/'sampler.c'),sampler_library_sha256=digest(out/'sampler.dylib'),
            limits=['Synthetic HUD texels and real font coverage through original meter/text shaders and sampler; no live placement or retail Xbox parity proof',
                    'This result covers the named EGL driver; other platforms require their own GPU run'])
        (out/'fixtures.json').write_text(json.dumps(tests,indent=2)+'\n')
        (out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
        return proof
    finally:
        gl.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/hud-glsl-validation')
    parser.add_argument('--egl');parser.add_argument('--gles')
    parser.add_argument('--backend',choices=('angle-metal','angle-default','surfaceless','default'))
    args=parser.parse_args()
    print(json.dumps(validate(args.output.resolve(),args.egl,args.gles,args.backend),indent=2))


if __name__=='__main__':main()
