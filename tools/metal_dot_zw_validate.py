#!/usr/bin/env python3
"""Independent raw-D24 DOT_ZW GPU and guest packing checks.

Expected depth/color/stencil/query bytes remain exclusively in the CPU oracle.
This is a component fixture, not a captured original sprite draw comparison.
"""
import argparse
import ast
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_copy_subresource_validate as base
import metal_host_frame_validate as frame
import metal_host_draw_validate as wire
import metal_shader_validate as shader
sha,require=base.sha,base.require
CAPS=223
D24=16777215
CAPTURE=ROOT/'build/macos-metal/live-depth-diagnostic'
SPEC='https://registry.khronos.org/OpenGL/extensions/NV/NV_texture_shader.txt'
VS='''#include <metal_stdlib>
using namespace metal;
struct VIn { float4 position [[attribute(0)]]; };
struct Out { float4 position [[position]];
float4 xD0 [[user(xD0)]],xD1 [[user(xD1)]],xB0 [[user(xB0)]],xB1 [[user(xB1)]];
float4 xT0 [[user(xT0)]],xT1 [[user(xT1)]],xT2 [[user(xT2)]],xT3 [[user(xT3)]];
float xFog [[user(xFog)]]; };
vertex Out xgpu_vertex(VIn v [[stage_in]],constant float4 *c [[buffer(0)]]) {
Out o; o.position=v.position; o.xD0=c[0];o.xD1=o.xB0=o.xB1=float4(0);
o.xT0=c[1];o.xT1=c[2];o.xT2=c[3];o.xT3=c[4];o.xFog=1;return o;
}
'''
class Options(C.Structure):
    _fields_=[('version',C.c_uint32),('depth_contract',C.c_uint32),('native_alpha_border_mask',C.c_uint32)]
def f32(x):
    try:return struct.unpack('<f',struct.pack('<f',x))[0]
    except OverflowError:return math.copysign(math.inf,x)
def ratio_depth(numerator,denominator,rgb):
    # NV_texture_shader section3.8.13.1.21: previous and current three-channel
    # dot products, then raw Xbox integer-D24 to normalized window units.
    mapped=[f32(v/255) for v in rgb]
    def dot(row):
        products=[f32(f32(v)*m) for v,m in zip(row,mapped)]
        return f32(f32(products[0]+products[1])+products[2])
    n,d=dot(numerator),dot(denominator)
    if d==0:return math.nan if n==0 else math.copysign(math.inf,n)
    return f32(f32(n/d)*f32(1/D24))
def key(kind='normal'):
    k=shader.PixelKey();k.texture_modes=0x54421;k.sampler_type[:]=(1,1,0,0)
    k.combiner_state[56]=0x110000;k.combiner_state[8]=4;k.combiner_state[9]=0x1400
    if kind=='alpha-kill':k.alpha_kill[0]=1
    if kind=='alpha-test':k.alpha_test_function=516
    if kind=='input-stage0':k.combiner_state[56]=0
    return k
def canonical(k):
    b=struct.pack('<58I',*k.combiner_state,k.texture_modes)
    for name in ('sampler_type','alpha_kill','color_sign','border_axes','border_filter'):b+=bytes(getattr(k,name))
    return b+struct.pack('<I4B',k.alpha_test_function,k.fog_enable,k.fog_table_mode,k.count_samples,k.coverage_alpha)
def captured_key():
    raw=(CAPTURE/'dumps/native-program-frame89-pixel-key.bin').read_bytes()
    require(len(raw)==260 and hashlib.sha256(raw).hexdigest()=='f13524b388b542bc2c4d328e9df265e6acd4265df92dd2916b0d89a52067d0aa','Actual key identity changed')
    k=shader.PixelKey();k.combiner_state[:]=struct.unpack_from('<57I',raw);k.texture_modes=struct.unpack_from('<I',raw,228)[0]
    for i,name in enumerate(('sampler_type','alpha_kill','color_sign','border_axes','border_filter')):getattr(k,name)[:]=raw[232+i*4:236+i*4]
    k.alpha_test_function=struct.unpack_from('<I',raw,252)[0]
    k.fog_enable,k.fog_table_mode,k.count_samples,k.coverage_alpha=raw[256:260]
    require(canonical(k)==raw,'Guest to harness key conversion changed bytes');return k
def generated_programs(out):
    frozen=out/'source-snapshot';port=frozen/'port/linux/src';libpath=out/'native-shaders.dylib'
    frame.run('clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC','-DXGPU_SHADER_STANDALONE=1','-DHALO_ANDROID=1',
              '-I',port,port/'nv2a_vsh.c',port/'nv2a_psh.c',frozen/'port/macos/metal-poc/shader_text.c','-o',libpath)
    lib=C.CDLL(str(libpath));lib.nv2a_pixel_shader_to_msl_with_options.argtypes=[C.POINTER(shader.PixelKey),C.POINTER(Options)]
    lib.nv2a_pixel_shader_to_msl_with_options.restype=C.c_void_p
    lib.nv2a_pixel_shader_to_msl.argtypes=[C.POINTER(shader.PixelKey)];lib.nv2a_pixel_shader_to_msl.restype=C.c_void_p
    require(shader.generated(lib.nv2a_pixel_shader_to_msl,C.byref(key())) is None,'Ordinary entrypoint inferred a depth contract')
    for options in (Options(2,0,0),Options(2,2,0),Options(3,1,0)):
        require(shader.generated(lib.nv2a_pixel_shader_to_msl_with_options,C.byref(key()),C.byref(options)) is None,'Invalid emitter depth contract accepted')
    result={};records=[]
    for n,kind in enumerate(('normal','alpha-kill','alpha-test','captured','input-stage0')):
        k=captured_key() if kind=='captured' else key(kind)
        text=shader.generated(lib.nv2a_pixel_shader_to_msl_with_options,C.byref(k),C.byref(Options(2,1,0)))
        require(text and 'replacement_depth' in text and 'isfinite' in text,'Typed generated depth shader missing guards')
        f=out/(kind+'.metal');f.write_text(text);v=out/'matching-varyings.metal';v.write_text(VS)
        kb=out/(kind+'.key.bin');kb.write_bytes(canonical(k));result[kind]=(100+n,text)
        records.append(dict(kind=kind,program_id=100+n,key_file=str(kb),key_sha256=sha(kb),fragment=str(f),fragment_sha256=sha(f),
                            vertex=str(v),vertex_sha256=sha(v),vertex_compiler_contract=0,fragment_compiler_contract=0,depth_contract='raw_d24'))
    # Compile original VS66 from captured words as evidence only; geometry was
    # not captured, so synthetic fullscreen execution uses the named matching VS.
    raw=(CAPTURE/'dumps/native-program-frame89-vertex-words.bin').read_bytes();words=(C.c_uint32*(len(raw)//4)).from_buffer_copy(raw)
    lib.nv2a_vertex_shader_to_msl.argtypes=[C.POINTER(C.c_uint32),C.c_ulong,C.c_ulong];lib.nv2a_vertex_shader_to_msl.restype=C.c_void_p
    vtext=shader.generated(lib.nv2a_vertex_shader_to_msl,words,len(raw)//16,0)
    require(vtext,'Captured original VS66 rejected');(out/'captured-vs66-not-executed.metal').write_text(vtext)
    return result,records
def program(id,source,fragment_contract=0):
    v,f=VS.encode(),source.encode()
    return struct.pack('<10I',7,40,id,1,0,0,len(v),0,len(f),fragment_contract),[(20,v),(28,f)]
def draw(id=1,size=8,program_id=100,numerator=(0,0,D24*.25),denominator=(0,0,1),
         near=0,far=1,depth_compare='always',depth_write=True,color_mask=15,stencil_compare='always',
         stencil_pass='replace',stencil_depth_fail='keep',stencil_fail='keep',stencil_mask=255,alpha=1):
    fixed,payloads=base.draw(id,size,program_id,depth=2);fixed=bytearray(fixed)
    sampler=struct.pack('<8I2f',0,0,0,2,2,2,1,0,0,0)
    for slot,texture in ((0,10),(1,11)):
        struct.pack_into('<2I',fixed,32+slot*8,texture,1);fixed[64+slot*40:104+slot*40]=sampler
    state=dict(viewport=dict(x=0,y=0,width=size,height=size,znear=near,zfar=far),scissor=dict(x=0,y=0,width=size,height=size),
      blend=dict(enabled=False,source='one',destination='zero',operation='add',write_mask=color_mask),
      depth=dict(enabled=True,write=depth_write,compare=depth_compare),
      stencil=dict(enabled=True,compare=stencil_compare,read_mask=255,write_mask=stencil_mask,
                   fail=stencil_fail,depth_fail=stencil_depth_fail,pass_=stencil_pass,reference=33),
      raster=dict(front_face='cw',cull='none',fill='solid',depth_bias=0,slope_scale=0,depth_bias_clamp=0))
    state['stencil']['pass']=state['stencil'].pop('pass_');fixed[224:376]=wire.state_bytes(state)
    vs=bytearray(3120);vectors=[(32/255,64/255,128/255,alpha),(.5,.5,0,1),(.5,.5,0,1),(*numerator,1),(*denominator,1)]
    for n,v in enumerate(vectors):struct.pack_into('<4f',vs,n*16,*v)
    ps=bytearray(608);struct.pack_into('<4f',ps,320,128,f32(1/D24),near,far);struct.pack_into('<16f',ps,464,*([1.]*16))
    payloads[-2:]=[(400,bytes(vs)),(404,bytes(ps))];return bytes(fixed),payloads
def depth_cases():
    for z in (-.125,0,.125,.25,.5,.875,1,1.125):
        for w in (.5,1,3):yield dict(label=f'ratio/z{z}/w{w}',numerator=(0,0,f32(z*D24*w)),denominator=(0,0,w))
    for z in (.2499,.25,.5,.75,.7501):yield dict(label=f'viewport/{z}',numerator=(0,0,f32(z*D24)),near=.25,far=.75)
    for channel in range(3):
        n=[0,0,0];d=[0,0,0];n[channel]=f32(D24*.375);d[channel]=1
        yield dict(label=f'depth-rgb-source/channel{channel}',numerator=tuple(n),denominator=tuple(d),rgb=(64,128,255))
        yield dict(label=f'depth-rgb-stage0/channel{channel}',kind='input-stage0',numerator=tuple(n),denominator=tuple(d),rgb=(64,128,255))
    for z in (.25,.75):
        yield dict(label=f'captured-original-key/synthetic-input/z{z}',kind='captured',color_mask=0,numerator=(0,0,f32(z*D24)))
    yield dict(label='captured-original-key/synthetic-zero-denominator',kind='captured',color_mask=0,denominator=(0,0,0))
    yield dict(label='zero-denominator-infinity',denominator=(0,0,0))
    yield dict(label='zero-denominator-NaN',numerator=(0,0,0),denominator=(0,0,0))
    yield dict(label='finite-input-overflow-infinity',numerator=(0,0,3e38),denominator=(0,0,1e-38))
    for z,write in ((.25,True),(.75,True),(.25,False)):
        yield dict(label=f'depth-less/z{z}/write{write}',numerator=(0,0,f32(z*D24)),depth_compare='less',depth_write=write)
    yield dict(label='alpha-kill-discard',kind='alpha-kill',texture_alpha=0)
    yield dict(label='alpha-test-discard',kind='alpha-test',alpha=.25)
    yield dict(label='color-mask-rb-depth-readonly',color_mask=5,depth_write=False)
    yield dict(label='color-mask-zero-depth-readonly',color_mask=0,depth_write=False)
    yield dict(label='stencil-depth-fail',numerator=(0,0,f32(.75*D24)),depth_compare='less',stencil_depth_fail='replace')
    yield dict(label='stencil-test-fail',stencil_compare='never',stencil_fail='replace')
    yield dict(label='stencil-write-mask',stencil_mask=0x0f)
    yield dict(label='readonly-all-targets',color_mask=0,depth_write=False,stencil_mask=0)
def oracle(case):
    rgb=case.get('rgb',(0,0,255));n=case.get('numerator',(0,0,D24*.25));d=case.get('denominator',(0,0,1))
    depth=ratio_depth(n,d,rgb);near=f32(case.get('near',0));far=f32(case.get('far',1))
    discarded=not math.isfinite(depth) or depth<near or depth>far or case.get('kind') in ('alpha-kill','alpha-test')
    stencil_pass=case.get('stencil_compare','always')!='never'
    depth_pass=case.get('depth_compare','always')!='less' or depth<f32(.5)
    visible=not discarded and stencil_pass and depth_pass
    color=[17,23,31,255];value=[32,64,128,255];mask=case.get('color_mask',15)
    if visible:
        for channel in range(4):
            if mask&(1<<channel):color[channel]=value[channel]
    final_depth=depth if visible and case.get('depth_write',True) else f32(.5)
    stencil=7;op=case.get('stencil_pass','replace') if visible else case.get('stencil_depth_fail','keep') if not discarded and stencil_pass else case.get('stencil_fail','keep') if not discarded else 'keep'
    if op=='replace':
        m=case.get('stencil_mask',255);stencil=(stencil&~m)|(33&m)
    return bytes(color)*64,struct.pack('<f',final_depth)*64,bytes([stencil])*64,struct.pack('<Q',64 if visible else 0),depth
def fixture(programs):
    f=base.Fixture();f.begin()
    f.emit(base.create(1,8));f.emit(base.create(2,8,fmt=3,usage=2));f.versions[1]=f.versions[2]=0
    f.emit(base.create(10,1));f.emit(base.create(11,1));f.emit(base.upload(10,bytes((17,31,47,255)),1));f.emit(base.upload(11,bytes((0,0,255,255)),1))
    for name,(id,text) in programs.items():f.emit(program(id,text))
    f.emit(struct.pack('<6I',12,24,200,1,2,0));f.versions[200]=0;f.submit()
    cases=list(depth_cases())
    for case in cases:
        f.begin();f.emit(base.clear(1,8,2,(17/255,23/255,31/255,1),.5,7));f.versions[1]+=1;f.versions[2]+=1
        rgb0=case.get('rgb',(0,0,255)) if case.get('kind')=='input-stage0' else (17,31,47)
        f.emit(base.upload(10,bytes((*rgb0,case.get('texture_alpha',255))),1));f.emit(base.upload(11,bytes((*case.get('rgb',(0,0,255)),255)),1))
        f.emit(struct.pack('<4I',14,16,200,1));args={k:v for k,v in case.items() if k not in ('label','kind','rgb','texture_alpha')}
        f.emit(draw(program_id=programs[case.get('kind','normal')][0],**args))
        if case.get('color_mask',15):f.versions[1]+=1
        if case.get('depth_write',True) or case.get('stencil_mask',255):f.versions[2]+=1
        f.emit(struct.pack('<4I',15,16,200,1));f.versions[200]+=1;f.submit()
        color,depth,stencil,count,z=oracle(case)
        for id,plane,e in ((1,1,color),(2,2,depth),(2,4,stencil),(200,8,count)):
            f.read(id,1 if id==200 else 8,e,f.versions[id],plane,label=case['label'])
        case['expected_normalized_depth']=z if math.isfinite(z) else 'NaN' if math.isnan(z) else 'Infinity'
    # Save real GPU before-state. Later malformed packets may contain CLEAR,
    # UPLOAD, DRAW/query commands but cannot modify any completed state.
    last=oracle(cases[-1]);baselines=[(1,8,last[0],f.versions[1],1),(2,8,last[1],f.versions[2],2),(2,8,last[2],f.versions[2],4),(200,1,last[3],f.versions[200],8)]
    for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,1,slot,label='actual-atomic-baseline')
    typed_labels=('integer-d24','linear-integer-d24','missing-contract','unknown-contract','missing-depth',
      'requested-f24','requested-d16','current-f24','floating-z1','floating-z2','viewport-min-negative',
      'viewport-max-over1','viewport-inverted','viewport-NaN','scale-not-d24','offset-not-d24','scale-NaN',
      'request-missing','surface-missing','viewport-quarter-range')
    f.typed_cases=[]
    for index,label in enumerate(typed_labels):
        reject=index not in (0,1,19)
        f.begin();f.emit(base.clear(1,8,2,(1,0,1,1),.25,99))
        f.actions.append([5,index,int(reject)]+[0]*9)
        # The caller discards the rejected pending packet via begin. A real
        # readonly draw completes next, retaining all prior attachment/query
        # bytes and versions; the pending clear is never submitted.
        f.begin();f.emit(draw(color_mask=0,depth_write=False,stencil_mask=0));f.submit()
        for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,2,slot,label='typed-atomic/'+label)
        f.typed_cases.append(dict(index=index,label=label,rejected=reject))
    invalid=[]
    bad_program=program(400,programs['normal'][1],2);invalid.append(('unknown-fragment-compiler-contract',bad_program,-2))
    normal=draw();bad=bytearray(normal[0]);struct.pack_into('<I',bad,16,999);invalid.append(('missing-color-resource',(bytes(bad),normal[1]),-3))
    for field in (400,404):
        fixed,payloads=draw();payloads=list(payloads);n=next(i for i,p in enumerate(payloads) if p[0]==field);bad=bytearray(payloads[n][1]);struct.pack_into('<I',bad,0,0x7fc00000);payloads[n]=(field,bytes(bad))
        invalid.append(('nonfinite-'+('VS' if field==400 else 'PS')+'-uniform',(fixed,payloads),-1))
    for label,cmd,status in invalid:
        f.begin();f.emit(struct.pack('<4I',14,16,200,1));f.emit(base.clear(1,8,2,(1,0,1,1),.25,99));f.emit(draw());f.emit(struct.pack('<4I',15,16,200,1));f.emit(cmd);f.submit(status,4,label)
        for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,2,slot,label='backend-atomic/'+label)
    return f,cases

def snapshot(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm','port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm',
      'port/macos/include/halo_metal_abi.h','port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm','port/macos/tests/guest_metal_dot_zw.c',
      'port/linux/src/metal_guest_transport.h','port/linux/src/metal_guest_transport.c','port/linux/src/metal_draw_state.h','port/linux/src/metal_draw_state.c',
      'port/linux/src/platform.h','port/linux/src/xgpu.h','port/linux/src/xgpu_msl.h','port/linux/src/xgpu_shader_standalone.h','port/linux/src/nv2a_psh.c','port/linux/src/nv2a_vsh.c',
      'port/macos/metal-poc/shader_text.c','port/macos/metal_imports.list','port/include/xdk/xdk_pdb.h','port/include/xdk/xdk_d3d8.h',
      'tools/metal_dot_zw_validate.py','tools/metal_copy_subresource_validate.py','tools/metal_host_frame_validate.py','tools/metal_host_draw_validate.py',
      'tools/metal_shader_validate.py','tools/test_metal_dot_zw_validate.py','tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py']
    records={}
    for name in names:
        source=ROOT/name;dest=out/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True);digest=sha(source);shutil.copy2(source,dest)
        require(sha(source)==sha(dest)==digest,'Source changed during DOT_ZW freeze');records[str(source)]=dict(snapshot=str(dest),sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records
def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    flags=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)))
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    for name,path in [('guest','port/macos/tests/guest_metal_dot_zw.c'),('transport','port/linux/src/metal_guest_transport.c')]:
        frame.run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-I',out,'-I',out/'freestanding','-include',out/'prefix.h',
          '-std=gnu11','-Wall','-Wextra','-Werror','-DHALO_MACOS=1','-DHALO_MACOS_NATIVE_METAL=1','-emit-llvm','-S',frozen/path,'-o',out/(name+'.ll'))
        frame.run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/(name+'.ll'),'-o',out/(name+'.rebased.ll'))
        frame.run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/(name+'.rebased.ll'),'-o',out/(name+'.darwin.s'))
        frame.run(sys.executable,frozen/'tools/android_asm_convert.py',out/(name+'.darwin.s'),out/(name+'.s'))
    for name in ('guest','transport','fixture'):frame.run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    (out/'diagnostic-imports.list').write_text((frozen/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n')
    frame.run(sys.executable,frozen/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    frame.run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    frame.run(linker,'-m','aarch64elf','-T',out/'guest.ld',*[out/(n+'.o') for n in ('guest','transport','fixture','imports')],'-o',out/'guest.elf')
    symbols={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines() if len(line.split())==3}
    sections=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sections.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    return symbols,span
def prefix(out):
    # Original enum declarations only; no replacement numeric source constants.
    xdk=(out/'source-snapshot/port/include/xdk/xdk_pdb.h').read_text()
    names=('D3DBLEND','D3DBLENDOP','D3DCMPFUNC','D3DCULL','D3DFILLMODE','D3DFOGMODE','D3DFRONT','D3DFORMAT','D3DRENDERSTATETYPE',
           'D3DSTENCILOP','D3DTEXTUREADDRESS','D3DTEXTUREALPHAKILL','D3DTEXTUREFILTERTYPE','D3DTEXTURESTAGESTATETYPE')
    s='#include <stdint.h>\n#define __HALO_LINUX_PLATFORM_H\ntypedef uint32_t DWORD;\ntypedef uint32_t D3DCOLOR;\ntypedef int BOOL;\n#define TRUE 1\n#define FALSE 0\n'
    for name in names:s+=re.search(r'enum _'+name+r'\s*\{.*?\};',xdk,re.S).group(0)+'\n'
    (out/'prefix.h').write_text(s);d=out/'freestanding';d.mkdir();(d/'math.h').write_text('#define isfinite(x) __builtin_isfinite(x)\n')
    (d/'string.h').write_text('void *memcpy(void *,const void *,unsigned long);\nvoid *memset(void *,int,unsigned long);\n')
def prepare(out,llvm,linker,plugin):
    require(not out.exists(),'Preserve prior proof; output must be fresh');out.mkdir(parents=True);records=snapshot(out);prefix(out)
    programs,program_records=generated_programs(out);f,cases=fixture(programs)
    (out/'inputs.bin').write_bytes(f.inputs);(out/'actions.bin').write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_dot_inputs\nhalo_dot_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+
      '\n.balign 16\n.global halo_dot_actions\nhalo_dot_actions:\n.incbin '+json.dumps(str(out/'actions.bin'))+'\n')
    (out/'metal_dot_zw_fixture.h').write_text(f'#define HALO_DOT_ACTIONS {len(f.actions)}u\n#define HALO_DOT_INPUT_BYTES {len(f.inputs)}u\n#define HALO_DOT_PACKET_CAPACITY 1048576u\n#define HALO_DOT_REQUIRED_CAPS {CAPS}u\n')
    for n,p in enumerate(f.packets):file=out/f'packet-{n:03}.bin';file.write_bytes(bytes.fromhex(p.pop('bytes')));p['file']=str(file);p['sha256']=sha(file)
    package=dict(schema_version=1,kind='dot_zw_raw_d24_fixture',complete=True,actions=len(f.actions),packets=f.packets,readbacks=f.readbacks,
      negative_cases=f.negative,typed_contract_cases=f.typed_cases,depth_cases=cases,programs=program_records,expected_after_gpu_uploaded=False,source_contract=dict(url=SPEC,section='3.8.13.1.21',
      equation='window_depth = (previous_dot / current_dot) * float32(1 / 16777215)'),fragment_fast_math=False,required_capabilities=CAPS)
    (out/'fixture.json').write_text(json.dumps(package,indent=2,allow_nan=False)+'\n');symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out)
    native=out/'native';native.mkdir();command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    dependencies=([Path(r['snapshot']) for r in records.values()]+sources+[plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',out/'actions.bin',out/'fixture.s',
       out/'metal_dot_zw_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json',out/'prefix.h',out/'native-shaders.dylib',Path(__file__)]+
       list((out/'freestanding').iterdir())+list(out.glob('*.metal'))+list(out.glob('*.key.bin'))+list((CAPTURE/'dumps').iterdir())+[CAPTURE/'execution.json']+[Path(p['file']) for p in f.packets])
    prepared=dict(schema_version=1,kind='dot_zw_raw_d24_prepared',complete=False,passed=False,fixture_sha256=sha(out/'fixture.json'),source_snapshot=records,
       source_and_binary_sha256={str(p):sha(p) for p in dependencies if p.is_file()},execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(dict(prepared=str(out/'prepared.json'),depth_cases=len(cases),readbacks=len(f.readbacks),negative_cases=len(f.negative))))
def execute(out):
    require(not (out/'execution.json').exists(),'Preserve historical execution');p,f=base.verify_prepared(out);env=dict(os.environ);env.update(p['validation_environment'])
    run=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(run.stdout);(out/'native.stderr').write_text(run.stderr)
    execution=dict(schema_version=1,kind='dot_zw_ilp32_execution',complete=True,returncode=run.returncode,command=p['execution_command'],prepared_sha256=sha(out/'prepared.json'),
      executor_sha256=sha(__file__),validation_environment=p['validation_environment'],stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution,indent=2)+'\n');base.verify_prepared(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());record=json.loads(run.stdout);expected={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=expected.pop(actual['event']);file=out/'native'/actual['file'];data=file.read_bytes();reference=bytes.fromhex(e['expected'])
        valid=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        comparisons.append(dict(event=e['event'],label=e['label'],plane=e['plane'],file=str(file),sha256=sha(file),expected_sha256=hashlib.sha256(reference).hexdigest(),
          different_bytes=sum(a!=b for a,b in zip(data,reference)) if len(data)==len(reference) else -1,metadata_valid=valid))
    report=dump['report'];validation='Metal API Validation Enabled' in run.stderr
    passed=run.returncode==0 and record.get('guest_result')==0 and report[:2]==[1,4] and not expected and validation and all(c['different_bytes']==0 and c['metadata_valid'] for c in comparisons)
    result=dict(p,complete=True,passed=passed,returncode=run.returncode,guest_run=record,guest_report=report,comparisons=comparisons,compared_readbacks=len(comparisons),missing_readbacks=len(expected),
      negative_cases=len(f['negative_cases']),gpu_api_validation_enabled=validation,fragment_compiler_contract=0,execution=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),
      full_game_gate=False,original_draw_pixel_parity_gate=False,physical_xbox_depth_quantization_gate=False,original_cpu_query_timing_gate=False,
      limits=['NV2A depth-stage component and explicit guest integer-D24 metadata; native float32 storage is not physical Xbox D24 quantization.',
              'The current ANGLE DOT_ZW fallback omits depth replacement and is not the source oracle.',
              'Captured key/VS provenance does not supply original geometry/textures; matching-varyings fixture remains synthetic.',
              'Expected after-target bytes stay in CPU comparison.'])
    base.verify_prepared(out);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,returncode=run.returncode,guest_report=report,readbacks=len(comparisons),missing=len(expected),
      first_difference=next((c for c in comparisons if c['different_bytes'] or not c['metadata_valid']),None),result=str(out/'result.json')),indent=2));return 0 if passed else 1
def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','execute']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'));a=p.parse_args()
    if a.mode=='prepare':prepare(a.out.resolve(),a.llvm,a.linker,a.plugin);return 0
    return execute(a.out.resolve())
if __name__=='__main__':sys.exit(main())
