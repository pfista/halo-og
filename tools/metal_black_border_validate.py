#!/usr/bin/env python3
"""Exact independent transparent-black hardware border proof, real ILP32 wire.

The reference substitutes out-of-range texels before interpolation. This is not
the old GLES edge fallback, an ANGLE equality claim, or physical Xbox precision
proof. Exact authored mip values avoid an interpolation tolerance in this gate.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import metal_host_draw_validate as wire
import metal_shader_validate as shader

ROOT=wire.ROOT
WIDTH,HEIGHT=104,65
COLORS=[(64,128,192,192),(128,192,64,192),(192,64,128,192),
        (64,192,128,192),(192,128,64,192),(128,64,192,192)]
SOURCE_FILES=('tools/metal_black_border_validate.py','tools/metal_host_draw_validate.py',
    'tools/metal_shader_validate.py','port/macos/tests/guest_metal_black_border.c',
    'port/macos/tests/host_metal.mm','port/macos/host/host.h','port/macos/host/host_memory.c',
    'port/macos/host/host_metal.mm','port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h',
    'port/macos/host/metal_draw_encoder.mm','port/macos/include/halo_metal_abi.h',
    'port/android/include/halo_android_abi.h','port/macos/metal_imports.list',
    'tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py',
    'port/linux/src/nv2a_psh.c','port/linux/src/nv2a_vsh.c','port/linux/src/xgpu_msl.h',
    'port/linux/src/xgpu_shader_standalone.h','port/macos/metal-poc/shader_text.c')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,data):p.write_bytes(data);return data
def require(c,m):wire.require(c,m)

def texel(x,y,level,axes):
    size=32>>level
    if (axes&1 and not 0<=x<size) or (axes&2 and not 0<=y<size):return (0,0,0,0)
    return COLORS[level]

def sample_level(u,v,level,linear,axes):
    size=32>>level
    if not linear:return texel(math.floor(u*size),math.floor(v*size),level,axes)
    x,y=u*size-.5,v*size-.5;ix,iy=math.floor(x),math.floor(y);fx,fy=x-ix,y-iy
    weights=((ix,iy,(1-fx)*(1-fy)),(ix+1,iy,fx*(1-fy)),(ix,iy+1,(1-fx)*fy),(ix+1,iy+1,fx*fy))
    return tuple(sum(texel(a,b,level,axes)[c]*w for a,b,w in weights) for c in range(4))

def reference(u,v,lod,linear,axes):
    a=math.floor(lod);b=min(5,a+1);f=lod-a
    values=tuple((1-f)*x+f*y for x,y in zip(sample_level(u,v,a,linear,axes),sample_level(u,v,b,linear,axes)))
    require(all(x==round(x) for x in values),'Noninteger analytic fixture value')
    return bytes(round(x) for x in values)

def cases():
    records=[]
    for linear in (False,True):
        for lod in range(6):records.append(dict(lod=float(lod),linear=linear,axes=3,anisotropy=1,grid='fringe'))
    # Fractional trilinear: absolute boundary coordinates give exact coverage
    # at both adjacent mip sizes, preserving exact byte expectations.
    for lod in (.25,.5,.75,2.25,2.5,2.75,4.25,4.5,4.75):
        records.append(dict(lod=lod,linear=True,axes=3,anisotropy=1,grid='fractional'))
    for axes in (1,2):
        for linear in (False,True):records.append(dict(lod=2.,linear=linear,axes=axes,anisotropy=1,grid='fringe'))
    for lod in (0.,2.):records.append(dict(lod=lod,linear=True,axes=3,anisotropy=16,grid='fringe'))
    for lod in (1.,2.,3.):records.append(dict(lod=lod,linear=True,axes=3,anisotropy=1,grid='derivative'))
    return records

def create_packet(out,lib):
    key=shader.PixelKey();key.texture_modes=1;key.sampler_type[0]=1
    key.combiner_state[8]=8;key.combiner_state[9]=0x18<<8
    ps=shader.generated(lib.nv2a_pixel_shader_to_msl,C.byref(key))
    require(ps is not None and 'sample_border0' not in ps,'Production PS must use native sampler directly')
    write(out/'fragment.metal',ps.encode())
    # Safe vertex deliberately avoids original transform precision: the test
    # isolates the actual sampler and production NV2A pixel instruction path.
    varyings=ps[ps.index('struct XgpuVaryings'):ps.index('struct XgpuPixelUniforms')]
    vs=('#include <metal_stdlib>\nusing namespace metal;\n'+varyings+
        'struct I { float4 p [[attribute(0)]]; float4 uv [[attribute(4)]]; };\n'
        'vertex XgpuVaryings xgpu_vertex(I i [[stage_in]]) { XgpuVaryings o={};o.position=i.p;o.xT0=i.uv;return o;}\n').encode()
    write(out/'vertex.metal',vs)
    packet=wire.Packet(1)
    for resource,fmt in ((1,2),(2,3)):packet.command(struct.pack('<12I',10,48,resource,1,fmt,WIDTH,HEIGHT,1,1,1,2,0))
    packet.command(struct.pack('<12I',10,48,10,1,1,32,32,1,1,6,1,0))
    for level,color in enumerate(COLORS):
        size=32>>level;data=bytes(color)*(size*size);write(out/f'mip{level}.rgba',data)
        packet.command(struct.pack('<18I',11,72,10,1,level,0,0,0,0,size,size,1,size*4,size*size*4,0,len(data),1,0),[(56,data)])
    # Valid initialized cube exists only to exercise fail-closed border typing.
    packet.command(struct.pack('<12I',10,48,11,1,1,1,1,1,2,1,1,0))
    for face in range(6):packet.command(struct.pack('<18I',11,72,11,1,0,face,0,0,0,1,1,1,4,4,0,4,1,0),[(56,bytes((64,128,192,192)))])
    packet.command(struct.pack('<12I5fI',4,72,1,1,2,1,7,0,0,WIDTH,HEIGHT,0,0,0,0,0,1,0))
    packet.command(struct.pack('<10I',7,40,100,1,0,0,len(vs),0,len(ps.encode()),0),[(20,vs),(28,ps.encode())])
    expected=bytearray(WIDTH*HEIGHT*4);depth=[1.]*(WIDTH*HEIGHT);records=cases();vu=bytes(3120);pu=bytearray(608)
    for stage in range(4):struct.pack_into('<4f',pu,464+16*stage,1,1,1,1)
    for ordinal,record in enumerate(records):
        lod,linear,axes=record['lod'],record['linear'],record['axes'];size=32>>math.floor(lod)
        derivative=record['grid']=='derivative';tile=3 if derivative else 1
        coords=([-2/size,-.5/size,-.25/size,0,.25/size,.5/size,.5,1-.5/size,1-.25/size,1,1+.25/size,1+.5/size,1+2/size]
                if record['grid']=='fringe' else ([-1/size,0,.5/size,.5,1-.5/size,1,1+1/size] if derivative else [-2,-.5,0,.5,1,1.5,3]))
        ox,oy=(78,(ordinal-27)*21) if derivative else ((ordinal%6)*13,(ordinal//6)*13)
        vertices=bytearray();indices=[]
        for y,v in enumerate(coords):
            for x,u in enumerate(coords):
                for ty in range(tile):
                    for tx in range(tile):
                        du=(tx-1)/size if derivative else 0;dv=(ty-1)/size if derivative else 0
                        color=reference(u+du,v+dv,lod,linear,axes);at=((oy+y*tile+ty)*WIDTH+ox+x*tile+tx)*4
                        expected[at:at+4]=color;depth[at//4]=.5
                base=len(vertices)//256
                left,top=ox+x*tile,oy+y*tile
                for px,py in ((left,top),(left+tile,top),(left+tile,top+tile),(left,top+tile)):
                    vertex=bytearray(256);struct.pack_into('<4f',vertex,0,2*px/WIDTH-1,1-2*py/HEIGHT,.5,1)
                    du=(px-left-1.5)/size if derivative else 0;dv=(py-top-1.5)/size if derivative else 0
                    struct.pack_into('<4f',vertex,64,u+du,v+dv,0,1);vertices.extend(vertex)
                indices.extend((base,base+1,base+2,base,base+2,base+3))
        sampler=struct.pack('<8I2f',int(linear),int(linear),2 if linear else 1,3 if axes&1 else 0,3 if axes&2 else 0,2,record['anisotropy'],0,0 if derivative else lod,5 if derivative else lod)
        state=dict(viewport=dict(x=0,y=0,width=WIDTH,height=HEIGHT,znear=0,zfar=1),scissor=dict(x=0,y=0,width=WIDTH,height=HEIGHT),
            raster=dict(front_face='cw',cull='none',fill='solid',depth_bias=0,slope_scale=0,depth_bias_clamp=0),
            blend=dict(enabled=False,source='one',destination='zero',operation='add',write_mask=15),depth=dict(enabled=True,write=True,compare='less_equal'),
            stencil=dict(enabled=False,compare='always',reference=0,read_mask=255,write_mask=0,fail='keep',depth_fail='keep',**{'pass':'keep'}))
        fixed=struct.pack('<16I',9,416,100,1,1,1,2,1,10,1,0,0,0,0,0,0)+sampler+bytes(120)+wire.state_bytes(state)
        fixed+=struct.pack('<10I',len(vertices)//256,len(indices),0,3,0,0,0,0,0,0)
        packet.command(fixed,[(392,vertices),(396,struct.pack('<%dI'%len(indices),*indices)),(400,vu),(404,pu)])
        record.update(origin=[ox,oy],coordinates=coords,pixels=(len(coords)*tile)**2,
            derivative_texels_per_pixel=2**lod if derivative else 0,lod_forced=not derivative)
    raw=packet.finish();write(out/'packet.bin',raw)
    rejection,offsets=wire.rejection_packet(raw,WIDTH,HEIGHT);write(out/'rejection.bin',rejection)
    write(out/'expected-color.rgba',expected);write(out/'expected-depth.bin',struct.pack('<%df'%len(depth),*depth));write(out/'expected-stencil.bin',bytes(WIDTH*HEIGHT))
    (out/'cases.json').write_text(json.dumps(records,indent=2)+'\n')
    return records,offsets

def build_guest(out,llvm,linker,plugin,snapshot):
    sys.path.insert(0,str(ROOT));from tools.android_build import GUEST_ABI_FLAGS
    resource=Path(subprocess.check_output([llvm/'clang','-print-resource-dir'],text=True).strip());run=wire.run
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
        '-DHALO_MACOS=1','-I',out,'-emit-llvm','-S',snapshot/'port/macos/tests/guest_metal_black_border.c','-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,snapshot/'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    for name in ('guest','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    run(sys.executable,snapshot/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',snapshot/'port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',out/'guest.ld',out/'guest.o',out/'fixture.o',out/'imports.o','-o',out/'guest.elf')
    return {f[2]:int(f[0],16) for line in subprocess.check_output([llvm/'llvm-nm','--defined-only',out/'guest.elf'],text=True).splitlines() if len(f:=line.split())==3}

def prepare(out,llvm,linker,plugin):
    out.mkdir(parents=True,exist_ok=False);snapshot=out/'source-snapshot';source_hashes={}
    for name in SOURCE_FILES:
        p=ROOT/name;d=snapshot/name;d.parent.mkdir(parents=True,exist_ok=True);h=sha(p);shutil.copy2(p,d)
        require(h==sha(p)==sha(d),'Source changed during snapshot');source_hashes[str(p)]=h;source_hashes[str(d)]=h
    library=shader.build_library(out);records,offsets=create_packet(out,library)
    symbols={'halo_draw_packet':'packet.bin','halo_draw_rejection_template':'rejection.bin','halo_draw_expected_color':'expected-color.rgba',
             'halo_draw_expected_depth':'expected-depth.bin','halo_draw_expected_stencil':'expected-stencil.bin'}
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n'+'\n'.join(f'.balign 16\n.global {k}\n{k}:\n.incbin {json.dumps(str(out/v))}' for k,v in symbols.items())+'\n')
    macros=dict(PACKET_BYTES=(out/'packet.bin').stat().st_size,REJECTION_BYTES=(out/'rejection.bin').stat().st_size,REJECTION_DRAW_OFFSET=offsets['draw'],
                COLOR_BYTES=WIDTH*HEIGHT*4,DEPTH_BYTES=WIDTH*HEIGHT*4,STENCIL_BYTES=WIDTH*HEIGHT,WIDTH=WIDTH,HEIGHT=HEIGHT)
    (out/'metal_host_draw_fixture.h').write_text('\n'.join(f'#define HALO_DRAW_{k} {v}u' for k,v in macros.items())+'\n')
    addresses=build_guest(out,llvm,linker,plugin,snapshot);exe,_=wire.build_host(out,source_root=snapshot)
    # The proof backend is also strictly compiled, independent of the generic
    # driver's permissive build flags.
    wire.run('xcrun','clang++','-std=c++17','-fobjc-arc','-fblocks','-DHALO_MACOS=1','-Wall','-Wextra','-Werror',
        '-I'+str(snapshot/'port/macos/host'),'-I'+str(snapshot/'port/android/include'),'-c',snapshot/'port/macos/host/host_metal.mm','-o',out/'strict-host.o')
    for p,h in source_hashes.items():require(sha(p)==h,'Source changed during build')
    native=out/'native';native.mkdir();required=('__host_import_table','__host_import_names','__host_import_count','halo_draw_report','halo_draw_actual_color','halo_draw_actual_depth','halo_draw_actual_stencil')
    command=[str(exe),str(out/'guest.elf'),*[hex(addresses[k]) for k in required[:3]],'0x1000000',*[hex(addresses[k]) for k in required[3:]],str(WIDTH),str(HEIGHT),str(native)]
    artifacts={str(p):sha(p) for p in out.rglob('*') if p.is_file()}
    artifacts[str(plugin)]=sha(plugin)
    prepared=dict(kind='native_metal_black_border_prepared',source_sha256=source_hashes,artifact_sha256=artifacts,execution_command=command,
                  sample_cases=sum(r['pixels'] for r in records),draw_cases=len(records))
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(command,indent=2))

def consume(out,returncode):
    prepared=json.loads((out/'prepared.json').read_text())
    for mapping in ('source_sha256','artifact_sha256'):
        for p,h in prepared[mapping].items():require(sha(p)==h,'Changed proof input: '+p)
    native=out/'native';record=json.loads((native/'stdout.json').read_text());words=struct.unpack('<16I',(native/'guest-report.bin').read_bytes())
    observed=json.loads((native/'returncode.json').read_text())
    require(observed==dict(returncode=returncode),'Observed process exit code differs from requested verification')
    require('Metal API Validation Enabled' in (native/'stderr.log').read_text(),'Missing Metal API Validation execution evidence')
    bgra=(native/'native-color-bgra.bin').read_bytes();rgba=bytearray(bgra);rgba[0::4]=bgra[2::4];rgba[2::4]=bgra[0::4]
    write(native/'native-color.rgba',rgba)
    different={name:sum(a!=b for a,b in zip(actual,(out/file).read_bytes())) for name,actual,file in
        [('color',rgba,'expected-color.rgba'),('depth',(native/'native-depth.bin').read_bytes(),'expected-depth.bin'),('stencil',(native/'native-stencil.bin').read_bytes(),'expected-stencil.bin')]}
    for actual,file in ((rgba,'expected-color.rgba'),((native/'native-depth.bin').read_bytes(),'expected-depth.bin'),((native/'native-stencil.bin').read_bytes(),'expected-stencil.bin')):
        require(len(actual)==(out/file).stat().st_size,'Truncated proof output')
    passed=returncode==0 and record.get('kind')=='native_metal_ilp32_transport' and record.get('passed') is True and record.get('guest_pointer_bits')==32 and record.get('guest_result')==0 and words[0:3]==(1,3,0) and words[4]==8 and words[5]&1024 and words[6:9]==(0,0,0) and words[13:16]==(WIDTH,HEIGHT,(out/'packet.bin').stat().st_size) and not any(different.values())
    result=dict(kind='native_metal_black_border_ilp32',schema_version=1,complete=True,passed=bool(passed),returncode=returncode,
        draw_cases=prepared['draw_cases'],sample_cases=prepared['sample_cases'],atomic_rejections=words[4],different_bytes=different,guest_report=list(words),
        prepared_sha256=sha(out/'prepared.json'),source_sha256=prepared['source_sha256'],
        output_sha256={str(p):sha(p) for p in native.iterdir() if p.is_file()},
        limits=['Synthetic sampler proof; original full-frame/game fidelity remains separate.',
                'No old GLES clamp-to-edge fallback is used as the border oracle.',
                'Forced LOD isolates all authored levels; three isotropic derivative-driven minification cases independently cover LOD1/2/3.',
                'Anisotropy16 constant-coordinate cases verify the path; elongated anisotropic footprints are unverified.',
                'Reference bytes are guest comparison data only; never GPU target uploads.'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('passed','draw_cases','sample_cases','atomic_rejections','different_bytes')},indent=2))
    require(passed,'Native black-border proof failed; outputs retained')
    closure=dict(kind='native_metal_black_border_source_closure',complete=True,passed=True,gpu_validation_layer=True,
        result_sha256=sha(out/'result.json'),source_sha256=prepared['source_sha256'],
        artifact_sha256={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='closure.json'})
    (out/'closure.json').write_text(json.dumps(closure,indent=2)+'\n')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--consume-returncode',type=int)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--rebase-plugin',type=Path,default=ROOT/'build/macos-metal/guest_rebase.dylib');a=p.parse_args()
    if a.consume_returncode is not None:consume(a.output.resolve(),a.consume_returncode)
    else:prepare(a.output.resolve(),a.llvm.resolve(),a.linker.absolute(),a.rebase_plugin.resolve())

if __name__=='__main__':main()
