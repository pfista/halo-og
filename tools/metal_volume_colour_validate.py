#!/usr/bin/env python3
"""Independent GPU/ILP32 test of normalized3D arbitrary RGBA border sampling.

The oracle enumerates the source footprint with rational arithmetic. Expected
pixels remain in CPU comparisons. Synthetic shaders and generated PROJECT3D
components are distinct from original dynamic-light draw parity.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from fractions import Fraction as Q

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_volume_validate as volume
import metal_copy_subresource_validate as copy
import metal_host_frame_validate as frame
import metal_host_draw_validate as wire
sha,require=wire.sha,wire.require
GENERATED=ROOT/'build/metal-poc/volume-border-generated-project3d-component'
SHADER='''#include <metal_stdlib>
using namespace metal;
struct In { float4 position [[position]]; };
struct Out { float4 color [[color(0)]]; uint mask [[sample_mask]]; };
fragment Out xgpu_fragment(In i [[stage_in]], constant float4 *p [[buffer(0)]],
 texture3d<float> t [[texture(0)]], sampler b [[sampler(0)]], sampler w [[sampler(4)]]) {
 float3 c=float3(i.position.xy/p[0].y,(p[0].z+0.5f)/p[0].y);
 if(p[0].w>0.5f)c=p[1].xyz;
 float4 black,white;
 if(p[0].w>1.5f && p[0].w<2.5f) {
  gradient3d g=gradient3d(float3(1.0f/128.0f,0,0),float3(0,1.0f/128.0f,0));
  black=t.sample(b,c,g);white=t.sample(w,c,g);
 } else {black=t.sample(b,c,level(p[0].x));white=t.sample(w,c,level(p[0].x));}
 Out o;o.color=black+p[33]*(white-black);o.mask=0xffffffffu;return o;
}
'''
# This separate negative program compiles a 2D resource and companion. Its
# reflection must reject a selected3D resource before any earlier GPU mutation.
WRONG_TEXTURE='''#include <metal_stdlib>
using namespace metal;struct In {float4 p [[position]];};
fragment float4 xgpu_fragment(In i [[stage_in]],texture2d<float> t [[texture(0)]],
sampler b [[sampler(0)]],sampler w [[sampler(4)]]) {return t.sample(b,float2(.5))+t.sample(w,float2(.5));}
'''
REQUIRED_CAPS=1|2|4|8|16|64|128|8192|16384

def round_half_up(value):
    require(0<=value<=255,'Oracle outside normalized byte range')
    return (value+Q(1,2)).numerator//(value+Q(1,2)).denominator

def footprint(levels,lod,coordinate,border,linear=True,mip_linear=True):
    """Exact original footprint, independent of the b+colour*(w-b) identity."""
    lod=max(Q(0),min(Q(5),Q(lod)))
    first=lod.numerator//lod.denominator
    next_=min(5,first+1)
    blend=lod-first if mip_linear else Q(0)
    if not mip_linear:first=min(5,(lod+Q(1,2)).numerator//(lod+Q(1,2)).denominator);next_=first
    def sample(level):
        size=32>>level
        if not linear:
            xyz=[(Q(c)*size).numerator//(Q(c)*size).denominator for c in coordinate]
            if not all(0<=x<size for x in xyz):return list(map(Q,border))
            p=((xyz[2]*size+xyz[1])*size+xyz[0])*4
            return list(map(Q,levels[level][p:p+4]))
        p=[Q(c)*size-Q(1,2) for c in coordinate]
        base=[x.numerator//x.denominator for x in p];fr=[x-y for x,y in zip(p,base)]
        result=[Q(0)]*4
        for bit in range(8):
            xyz=[base[a]+((bit>>a)&1) for a in range(3)];weight=Q(1)
            for a in range(3):weight*=fr[a] if (bit>>a)&1 else 1-fr[a]
            if all(0<=x<size for x in xyz):
                at=((xyz[2]*size+xyz[1])*size+xyz[0])*4;rgba=levels[level][at:at+4]
            else:rgba=border
            for c in range(4):result[c]+=weight*rgba[c]
        return result
    a,b=sample(first),sample(next_)
    return [x*(1-blend)+y*blend for x,y in zip(a,b)]

def expected(levels,lod,coordinate,border,linear=True,mip_linear=True,integer_only=True):
    values=footprint(levels,lod,coordinate,border,linear,mip_linear)
    if integer_only:require(all(x.denominator==1 for x in values),'Fractional byte tie is a separate precision gate')
    return bytes(round_half_up(x) for x in values)

def extended_draw(target,size,texture,lod=0,coordinate=(0,0,0),border=(5,5,5,5),
                  linear=False,mode=1,program=101,stage=0,alpha=False,q=2,depth=0):
    fixed,payloads=volume.sample(target,size,texture,float(lod),mode=mode,coordinate=tuple(map(float,coordinate)),
                               min_filter=int(linear),mag_filter=1,mip_filter=2 if linear else 1)
    fixed=bytearray(fixed);struct.pack_into('<2I',fixed,0,21,424);struct.pack_into('<I',fixed,8,program)
    if stage:
        sampler=bytes(fixed[64:104]);fixed[32:40]=bytes(8);fixed[64:104]=bytes(40)
        struct.pack_into('<2I',fixed,32+stage*8,texture,1);fixed[64+stage*40:104+stage*40]=sampler
    ps=bytearray(payloads[-1][1]);struct.pack_into('<4f',ps,528+stage*16,*[c/255 for c in border])
    if program>=110:
        struct.pack_into('<16f',ps,464,*([1.]*16));struct.pack_into('<4f',ps,592,0,0,0,0)
        vs=bytearray(3120);struct.pack_into('<4f',vs,0,*[float(c)*q for c in coordinate],q)
        payloads[-2]=(400,bytes(vs))
        # Select source authored mip while preserving generated implicit sample.
        struct.pack_into('<2f',fixed,64+stage*40+32,float(lod),float(lod))
    payloads[-1]=(404,bytes(ps))
    if depth:
        struct.pack_into('<2I',fixed,24,depth,1)
        # Read-only depth/stencil state, same shape as the original wire state.
        state=bytearray(fixed[224:376]);struct.pack_into('<3I',state,40,1,0,7)
        fixed[224:376]=state
    return bytes(fixed)+struct.pack('<2I',1<<stage,0),payloads

def generated_programs():
    description=json.loads((GENERATED/'fixture.json').read_text());result=[]
    for p,h in description['source_sha256'].items():require(sha(p)==h,'Generated emitter source drift')
    for n,c in enumerate(description['cases']):
        for field in ('key_file','fragment','vertex'):
            require(sha(GENERATED/c[field])==c[field+'_sha256'],'Generated fixture bytes changed')
        v=(GENERATED/c['vertex']).read_bytes();f=(GENERATED/c['fragment']).read_bytes()
        result.append((110+n,c,(struct.pack('<10I',7,40,110+n,1,0,0,len(v),0,len(f),0),[(20,v),(28,f)])))
    return result

def changed(draw,offset,fmt,*value):
    fixed,payloads=draw;fixed=bytearray(fixed);struct.pack_into(fmt,fixed,offset,*value);return bytes(fixed),payloads

def changed_ps(draw,offset,*values):
    fixed,payloads=draw;ps=bytearray(payloads[-1][1]);struct.pack_into('<'+'f'*len(values),ps,offset,*values)
    return fixed,payloads[:-1]+[(404,bytes(ps))]

def fixture(strict_ties=False):
    authored=volume.decode_authored();synth=[volume.synthetic(32>>n,n) for n in range(6)];linear=volume.linear_levels()
    f=copy.Fixture();f.begin()
    for id,size,fmt,usage in [(1,32,1,3),(2,32,3,2),(3,4,1,3),(35,1,1,3)]+[(30+n,32>>n,1,3) for n in range(5)]:
        f.emit(copy.create(id,size,fmt=fmt,usage=usage));f.versions[id]=0
    for id in (10,11,14,80):f.emit(volume.create(id))
    f.emit(volume.create(81,mips=1))
    f.emit(copy.program(100,copy.PATTERN));f.emit(copy.program(101,SHADER));f.emit(copy.program(102,volume.SHADER))
    f.emit(copy.program(103,WRONG_TEXTURE))
    programs=generated_programs()
    for _,_,p in programs:f.emit(p)
    f.emit(struct.pack('<6I',12,24,200,1,2,0));f.emit(copy.clear(1,32,2));f.versions[1]=f.versions[2]=1
    f.emit(copy.upload(3,bytes((17,23,31,255))*16,4));f.versions[3]=1
    for id in [35]+list(range(30,35)):
        size=1 if id==35 else 32>>(id-30);f.emit(copy.clear(id,size));f.versions[id]=1
    for n in range(6):
        size=32>>n
        for id,levels in ((10,synth),(11,authored),(14,linear)):f.emit(volume.upload(id,n,size,levels[n]))
        if n<5:f.emit(volume.upload(80,n,size,synth[n]))
    f.emit(volume.upload(81,0,32,synth[0]))
    f.emit(struct.pack('<4I',14,16,200,1));f.emit(copy.draw(1,32,100,0));f.versions[1]+=1
    f.emit(struct.pack('<4I',15,16,200,1));f.submit();query_version=1
    # Authored source chain and asymmetric channel/axis oracle at exact centers.
    for texture,levels,label in ((10,synth,'asymmetric-xyz'),(11,authored,'authored-actual')):
        for n,data in enumerate(levels):
            size=32>>n;target=35 if n==5 else 30+n
            for z in range(size):
                for lin in (False,True):
                    draw=extended_draw(target,size,texture,n,mode=0,border=(5,5,5,5),linear=lin)
                    fixed,payloads=draw;ps=bytearray(payloads[-1][1]);struct.pack_into('<f',ps,8,z)
                    f.begin();f.emit((fixed,payloads[:-1]+[(404,bytes(ps))]));f.versions[target]+=1;f.submit()
                    f.read(target,size,volume.slice_bytes(data,size,z),f.versions[target],label=f'{label}/{"linear" if lin else "point"}/mip{n}/z{z}')
    # Exact actual RGBA0x05050505 outside each axis and all authored mips.
    for n in range(6):
        for lin in (False,True):
            for axis in range(3):
                for side in (-1,2):
                    coord=[Q(1,2)]*3;coord[axis]=Q(side)
                    f.begin();f.emit(extended_draw(35,1,11,n,coord,linear=lin));f.versions[35]+=1;f.submit()
                    f.read(35,1,bytes([5]*4),f.versions[35],label=f'actual-05050505/outside/mip{n}/axis{axis}/{side}/{lin}')
    # Distinct RGBA with rational integral 8-voxel/two-mip border results.
    rgba=(64,96,160,192)
    for lod in [Q(n) for n in range(6)]+[Q(n)+t for n in range(5) for t in (Q(1,4),Q(1,2),Q(3,4))]:
        size=32>>(lod.numerator//lod.denominator)
        coords=[(Q(0),)*3,(Q(1),)*3,(Q(1,2),)*3]
        for axis in range(3):
            for edge in (Q(0),Q(1),-Q(1,4*size),Q(1)+Q(1,4*size)):
                coord=[Q(1,2)]*3;coord[axis]=edge;coords.append(tuple(coord))
        for coord in coords:
            e=expected(linear,lod,coord,rgba)
            f.begin();f.emit(extended_draw(35,1,14,lod,coord,rgba,linear=True));f.versions[35]+=1;f.submit()
            f.read(35,1,e,f.versions[35],label=f'rational-rgba-xyz-mip/lod{lod}/{coord}')
    # Forced linear MAG and safe quarter nearest-MIP selection controls.
    for axis in range(3):
        for side in (Q(0),Q(1)):
            coord=[Q(1,64)]*3;coord[axis]=side
            e=expected(synth,0,coord,rgba,linear=True,mip_linear=False)
            f.begin();f.emit(extended_draw(35,1,10,0,coord,rgba,mode=2));f.versions[35]+=1;f.submit()
            f.read(35,1,e,f.versions[35],label=f'point-min-linear-mag/axis{axis}/{side}')
    for lod in (Q(1,4),Q(3,4),Q(5,4),Q(7,4),Q(17,4),Q(19,4)):
        coord=(Q(1,2),)*3;e=expected(linear,lod,coord,rgba,linear=False,mip_linear=False)
        f.begin();f.emit(extended_draw(35,1,14,lod,coord,rgba));f.versions[35]+=1;f.submit()
        f.read(35,1,e,f.versions[35],label=f'safe-quarter-nearest-mip/{lod}')
    # Production q division, stage mask, both filter contracts and alpha kill.
    for pid,c,_ in programs:
        stage=c['stage'];kill=c['alpha_kill']
        for n in range(6):
            size=32>>n
            for lin in (False,True):
                for outside in (False,True):
                    coord=(-1,Q(1,2),Q(1,2)) if outside else (Q(1,2*size),)*3
                    rgba=(64,96,160,192) if not kill else (64,96,160,0)
                    e=bytes(rgba) if outside else authored[n][:4]
                    # Alpha-zero generated samples discard, preserving target.
                    discard=kill and e[3]==0
                    f.begin();f.emit(copy.clear(35,1,rgba=(17/255,23/255,31/255,1)));f.versions[35]+=1
                    f.emit(struct.pack('<4I',14,16,200,1));f.emit(extended_draw(35,1,11,n,coord,rgba,linear=lin,program=pid,stage=stage,q=2))
                    f.versions[35]+=1;f.emit(struct.pack('<4I',15,16,200,1));f.submit();query_version+=1
                    f.read(35,1,bytes((17,23,31,255)) if discard else e,f.versions[35],label=f'generated-project3d/stage{stage}/kill{kill}/mip{n}/outside{outside}/linear{lin}')
                    f.read(200,1,struct.pack('<Q',0 if discard else 1),query_version,plane=8,label='generated-alpha-kill-query')
    if strict_ties:
        # Deliberately separate ideal half-up control. Failed precision is kept
        # unchanged; no tolerance enters the positive rational fixture.
        for n in range(6):
            coord=(Q(0),Q(1,2),Q(1,2));e=expected(authored,n,coord,(5,5,5,5),integer_only=False)
            f.begin();f.emit(extended_draw(35,1,11,n,coord,linear=True));f.versions[35]+=1;f.submit()
            f.read(35,1,e,f.versions[35],label=f'ideal-half-up-actual-border/mip{n}')
    # Refresh original saved baselines after query controls have reset the word.
    f.begin();f.emit(struct.pack('<4I',14,16,200,1));f.emit(copy.draw(1,32,100,0));f.versions[1]+=1
    f.emit(struct.pack('<4I',15,16,200,1));f.submit();query_version+=1
    baselines=[(1,32,copy.pattern(32,0),f.versions[1],1),(2,32,struct.pack('<f',1)*1024,1,2),
               (2,32,bytes([7])*1024,1,4),(3,4,bytes((17,23,31,255))*16,1,1),(200,1,struct.pack('<Q',1024),query_version,8)]
    for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,1,slot,label='atomic-baseline')
    valid=extended_draw(35,1,11,2,(Q(1,16),)*3)
    cases=[('zero-mask',changed(valid,416,'<I',0),-1),('high-mask',changed(valid,416,'<I',16),-1),
           ('overlap-mask',changed(valid,420,'<I',1),-1),('alpha-high-mask',changed(valid,420,'<I',16),-1),
           ('unbound-selected-stage',changed_ps(changed(valid,416,'<I',2),528,0.,0.,0.,0.),-1),
           ('absent-volume',changed(valid,32,'<2I',0,0),-1),
           ('wrong-2d-type',changed(changed(valid,32,'<2I',3,1),84,'<I',2),-2),('single-mip',changed(valid,32,'<2I',81,1),-2),
           ('missing-mip',changed(valid,32,'<2I',80,1),-7),('missing-ref',changed(valid,32,'<2I',99,1),-3),
           ('stale-generation',changed(valid,36,'<I',2),-3),('edge-not-border',changed(valid,76,'<3I',2,2,2),-2),
           ('unsupported-filter',changed(valid,64,'<3I',1,1,1),-2),('anisotropy',changed(valid,88,'<I',2),-2),
           ('no-companion-reflection',changed(valid,8,'<I',102),-1),('wrong-texture-reflection',changed(valid,8,'<I',103),-1),
           ('colour-negative',changed_ps(valid,528,-1.),-2),('colour-over-one',changed_ps(valid,540,1.25),-2),
           ('colour-nan',changed_ps(valid,532,float('nan')),-1),('colour-inf',changed_ps(valid,536,float('inf')),-1)]
    for label,invalid,status in cases:
        f.begin();f.emit(struct.pack('<4I',14,16,200,1));f.emit(copy.clear(1,32,2,(1,0,1,1),.25,99))
        f.emit(copy.upload(3,bytes((99,77,55,255))*4,2));f.emit(copy.draw(1,32,100,6,depth=2,half=True))
        f.emit(struct.pack('<4I',15,16,200,1));f.emit(invalid);f.submit(status,5,label)
        for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,2,slot,label=f'atomic/{label}')
    return f

def snapshot(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
           'port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm','port/macos/include/halo_metal_abi.h',
           'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm','port/macos/tests/guest_metal_volume_colour.c',
           'port/linux/src/metal_guest_transport.h','port/linux/src/metal_guest_transport.c','port/macos/metal_imports.list',
           'tools/metal_volume_colour_validate.py','tools/test_metal_volume_colour_validate.py','tools/metal_volume_validate.py',
           'tools/metal_copy_subresource_validate.py','tools/metal_host_frame_validate.py','tools/metal_host_draw_validate.py',
           'tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py',
           'port/linux/src/nv2a_psh.c','port/linux/src/xgpu_msl.h','port/linux/src/xgpu_shader_standalone.h']
    records={}
    for name in names:
        source=ROOT/name;dest=out/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        digest=sha(source);shutil.copy2(source,dest);require(sha(source)==sha(dest)==digest,'Source changed during freeze')
        records[str(source)]=dict(snapshot=str(dest),sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    flags=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)))
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip());run=frame.run
    for name,path in [('guest','port/macos/tests/guest_metal_volume_colour.c'),('transport','port/linux/src/metal_guest_transport.c')]:
        run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
            '-DHALO_MACOS=1','-DHALO_MACOS_NATIVE_METAL=1','-I',out,'-emit-llvm','-S',frozen/path,'-o',out/(name+'.ll'))
        run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/(name+'.ll'),'-o',out/(name+'.rebased.ll'))
        run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/(name+'.rebased.ll'),'-o',out/(name+'.darwin.s'))
        run(sys.executable,frozen/'tools/android_asm_convert.py',out/(name+'.darwin.s'),out/(name+'.s'))
    for name in ('guest','transport','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    (out/'diagnostic-imports.list').write_text((frozen/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n')
    run(sys.executable,frozen/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',out/'guest.ld',*[out/(n+'.o') for n in ('guest','transport','fixture','imports')],'-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    sections=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sections.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    return symbols,span

def prepare(out,llvm,linker,plugin,strict_ties=False):
    require(not out.exists(),'Preserve historical proof; fresh output required');out.mkdir(parents=True)
    records=snapshot(out);f=fixture(strict_ties)
    (out/'inputs.bin').write_bytes(f.inputs);(out/'actions.bin').write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_volume_colour_inputs\nhalo_volume_colour_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+
        '\n.balign 16\n.global halo_volume_colour_actions\nhalo_volume_colour_actions:\n.incbin '+json.dumps(str(out/'actions.bin'))+'\n')
    (out/'metal_volume_colour_fixture.h').write_text(f'#define HALO_VOLUME_COLOUR_ACTIONS {len(f.actions)}u\n#define HALO_VOLUME_COLOUR_INPUT_BYTES {len(f.inputs)}u\n#define HALO_VOLUME_COLOUR_PACKET_CAPACITY 1048576u\n#define HALO_VOLUME_COLOUR_REQUIRED_CAPS {REQUIRED_CAPS}u\n')
    for n,p in enumerate(f.packets):
        path=out/f'packet-{n:03}.bin';path.write_bytes(bytes.fromhex(p.pop('bytes')));p['file']=str(path);p['sha256']=sha(path)
    package=dict(schema_version=1,kind='volume_colour_fixture',complete=True,actions=len(f.actions),packets=f.packets,
                 readbacks=f.readbacks,negative_cases=f.negative,source_levels=[32,16,8,4,2,1],actual_argb=0x05050505,
                 expected_after_gpu_uploaded=False,required_capabilities=REQUIRED_CAPS,strict_edge_ties_included=strict_ties)
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n');symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out)
    native=out/'native';native.mkdir();command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    dependencies=[Path(r['snapshot']) for r in records.values()]+sources+[plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',out/'actions.bin',out/'fixture.s',
        out/'metal_volume_colour_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json',Path(__file__),volume.RUNTIME]+list(volume.ASSETS.iterdir())+list(GENERATED.iterdir())+[Path(p['file']) for p in f.packets]
    prepared=dict(schema_version=1,kind='volume_colour_ilp32_prepared',complete=False,passed=False,fixture_sha256=sha(out/'fixture.json'),source_snapshot=records,
        source_and_binary_sha256={str(p):sha(p) for p in dependencies if p.is_file()},execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(out/'prepared.json'),readbacks=len(f.readbacks),negative_cases=len(f.negative),actions=len(f.actions)),indent=2))

def execute(out):
    require(not (out/'execution.json').exists(),'Preserve earlier execution');p,f=copy.verify_prepared(out)
    env=dict(os.environ);env.update(p['validation_environment']);run=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(run.stdout);(out/'native.stderr').write_text(run.stderr)
    execution=dict(schema_version=1,kind='volume_colour_ilp32_execution',complete=True,returncode=run.returncode,command=p['execution_command'],prepared_sha256=sha(out/'prepared.json'),
        executor_sha256=sha(__file__),validation_environment=p['validation_environment'],stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution,indent=2)+'\n');copy.verify_prepared(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());record=json.loads(run.stdout);expected={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=expected.pop(actual['event']);file=out/'native'/actual['file'];data=file.read_bytes();reference=bytes.fromhex(e['expected'])
        valid=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        comparisons.append(dict(event=e['event'],label=e['label'],file=str(file),sha256=sha(file),expected_sha256=hashlib.sha256(reference).hexdigest(),
            different_bytes=sum(a!=b for a,b in zip(data,reference)) if len(data)==len(reference) else -1,max_delta=max((abs(a-b) for a,b in zip(data,reference)),default=0),metadata_valid=valid))
    report=dump['report'];validation='Metal API Validation Enabled' in run.stderr
    passed=run.returncode==0 and record.get('guest_result')==0 and report[:2]==[1,4] and not expected and validation and all(c['different_bytes']==0 and c['metadata_valid'] for c in comparisons)
    result=dict(p,complete=True,passed=passed,returncode=run.returncode,guest_run=record,guest_report=report,comparisons=comparisons,
        compared_readbacks=len(comparisons),missing_readbacks=len(expected),negative_cases=len(f['negative_cases']),gpu_api_validation_enabled=validation,
        execution=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),original_dynamic_light_draw_gate=False,original_full_frame_gate=False,physical_xbox_gate=False,
        original_cpu_query_timing_gate=False,ideal_half_rounding_gate=bool(passed and f['strict_edge_ties_included']),
        limits=['Synthetic XYZ/channel and authored source sampling with an independent footprint oracle; no original game draw parity.',
                'Production PROJECT3D fragment uses synthetic matching-varyings vertex inputs.',
                'Rational integer byte controls are exact; ideal half-up precision remains a separate explicit gate.',
                'Expected pixels remain CPU-only; hardware black/opaqueWhite samples share original resource and filter footprint.'])
    copy.verify_prepared(out);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    failures=[c for c in comparisons if c['different_bytes'] or not c['metadata_valid']]
    print(json.dumps(dict(passed=passed,returncode=run.returncode,guest_report=report,readbacks=len(comparisons),missing=len(expected),differences=len(failures),
                         first_difference=failures[0] if failures else None,result=str(out/'result.json')),indent=2));return 0 if passed else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','execute']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--strict-edge-ties',action='store_true');p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    a=p.parse_args()
    if a.mode=='prepare':prepare(a.out.resolve(),a.llvm,a.linker,a.plugin,a.strict_edge_ties);return 0
    return execute(a.out.resolve())
if __name__=='__main__':sys.exit(main())
