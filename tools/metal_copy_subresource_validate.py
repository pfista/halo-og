#!/usr/bin/env python3
"""Independent rendered-mip copy and atomic-preflight test via real ILP32 C.

Only synthetic draw inputs enter the GPU. Analytic expected pixels remain in
the host comparator. This tests the copy operation, not original water fidelity.
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_host_draw_validate as wire
import metal_host_frame_validate as frame
sha,require=wire.sha,wire.require
VS='''#include <metal_stdlib>
using namespace metal;
struct VIn { float4 position [[attribute(0)]]; };
struct Out { float4 position [[position]]; };
vertex Out xgpu_vertex(VIn v [[stage_in]]) { Out o; o.position=v.position; return o; }
'''
PATTERN='''#include <metal_stdlib>
using namespace metal;
struct In { float4 position [[position]]; };
struct Out { float4 color [[color(0)]]; uint mask [[sample_mask]]; };
fragment Out xgpu_fragment(In i [[stage_in]], constant float4 &p [[buffer(0)]]) {
 uint x=uint(i.position.x), y=uint(i.position.y), k=uint(p.x), phase=uint(p.y);
 uint r=(3*x+5*y+37*k+11+128*phase)&255;
 uint g=((x^y)+19*k+23)&255;
 uint b=(7*x+11*y+13*k+31)&255;
 Out o; o.color=float4(float3(r,g,b)/255.0f,1.0f); o.mask=0xffffffffu; return o;
}
'''
SAMPLE='''#include <metal_stdlib>
using namespace metal;
struct In { float4 position [[position]]; };
struct Out { float4 color [[color(0)]]; uint mask [[sample_mask]]; };
fragment Out xgpu_fragment(In i [[stage_in]], constant float4 &p [[buffer(0)]],
 texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {
 Out o; o.color=t.sample(s,i.position.xy/p.y,level(p.x)); o.mask=0xffffffffu; return o;
}
'''

def pattern(size,level,phase=0,bgra=False):
    data=bytearray()
    for y in range(size):
        for x in range(size):
            r=(3*x+5*y+37*level+11+128*phase)&255
            g=((x^y)+19*level+23)&255
            b=(7*x+11*y+13*level+31)&255
            data.extend((b,g,r,255) if bgra else (r,g,b,255))
    return bytes(data)

def copy_region(source,source_size,destination,destination_size,sx,sy,dx,dy,w,h):
    result=bytearray(destination)
    for y in range(h):
        a=((sy+y)*source_size+sx)*4;b=((dy+y)*destination_size+dx)*4
        result[b:b+w*4]=source[a:a+w*4]
    return bytes(result)

def create(id,size,fmt=1,mips=1,usage=3,type=1,gen=1):
    return struct.pack('<12I',10,48,id,gen,fmt,size,size,1,type,mips,usage,0)
def clear(id,size,depth=0,rgba=(0,0,0,1),z=1,stencil=7):
    return struct.pack('<12I5fI',4,72,id,1,depth,1 if depth else 0,7 if depth else 1,
                       0,0,size,size,stencil,*rgba,z,0)
def copy(src=10,dst=20,sm=0,dm=0,size=128,ss=0,ds=0,sx=0,sy=0,dx=0,dy=0,w=None,h=None,plane=1,reserved=0,sg=1,dg=1):
    return struct.pack('<18I',20,72,src,sg,dst,dg,sm,ss,dm,ds,sx,sy,dx,dy,size if w is None else w,size if h is None else h,plane,reserved)
def upload(id,data,size):
    return (struct.pack('<18I',11,72,id,1,0,0,0,0,0,size,size,1,size*4,size*size*4,0,len(data),1,0),[(56,data)])
def program(id,source):
    v,f=VS.encode(),source.encode()
    return struct.pack('<10I',7,40,id,1,0,0,len(v),0,len(f),0),[(20,v),(28,f)]

def draw(id,size,program_id,level=0,phase=0,texture=0,depth=0,half=False):
    state=dict(viewport=dict(x=0,y=0,width=size,height=size,znear=0,zfar=1),
      scissor=dict(x=0,y=0,width=size//2 if half else size,height=size),
      blend=dict(enabled=False,source='one',destination='zero',operation='add',write_mask=15),
      depth=dict(enabled=bool(depth),write=bool(depth),compare='always'),
      stencil=dict(enabled=bool(depth),compare='always',read_mask=255,write_mask=255,
                   fail='keep',depth_fail='keep',pass_='replace',reference=33),
      raster=dict(front_face='cw',cull='none',fill='solid',depth_bias=0,slope_scale=0,depth_bias_clamp=0))
    state['stencil']['pass']=state['stencil'].pop('pass_')
    sampler=struct.pack('<8I2f',0,0,1,2,2,2,1,0,0,3) if texture else bytes(40)
    refs=[program_id,1,id,1,depth,1 if depth else 0,texture,1 if texture else 0,0,0,0,0,0,0]
    fixed=struct.pack('<16I',9,416,*refs)+sampler+bytes(120)+wire.state_bytes(state)+struct.pack('<10I',4,6,0,3,0,0,0,0,0,0)
    vertices=bytearray(4*256)
    for n,p in enumerate(((-1,1,.5,1),(1,1,.5,1),(1,-1,.5,1),(-1,-1,.5,1))):
        struct.pack_into('<4f',vertices,n*256,*p)
    constants=struct.pack('<4f',level,size if texture else phase,0,0)+bytes(592)
    return fixed,[(392,bytes(vertices)),(396,struct.pack('<6I',0,1,2,0,2,3)),(400,bytes(3120)),(404,constants)]

class Fixture:
    def __init__(self):
        self.inputs=bytearray();self.actions=[];self.readbacks=[];self.packets=[];self.current=[];self.negative=[]
        self.sequence=0;self.event=0;self.versions={};self.composite_versions=[]
    def blob(self,data):
        self.inputs.extend(bytes((-len(self.inputs))&15));offset=len(self.inputs);self.inputs.extend(data);return offset
    def begin(self):self.actions.append([1]+[0]*11);self.current=[]
    def emit(self,fixed,payloads=()):
        if isinstance(fixed,tuple):fixed,payloads=fixed
        descriptors=[]
        for field,data in payloads:descriptors.extend((field,self.blob(data),len(data)))
        offset=self.blob(fixed);description=self.blob(struct.pack('<'+'I'*len(descriptors),*descriptors)) if descriptors else 0
        self.actions.append([2,offset,len(fixed),description,len(payloads)]+[0]*7);self.current.append((fixed,payloads))
    def submit(self,status=0,failed=0,label=None):
        self.actions.append([3,status&0xffffffff,failed]+[0]*9)
        p=wire.Packet(self.sequence+1)
        for fixed,payloads in self.current:p.command(fixed,payloads)
        self.packets.append(dict(sequence=self.sequence+1,status=status,failed_command=failed,label=label,
                                 bytes=p.finish().hex()))
        if not status:self.sequence+=1
        else:self.negative.append(dict(label=label,status=status,failed_command=failed))
    def read(self,id,size,expected,version,plane=1,mode=0,slot=0,label=''):
        self.event+=1;bytes_=len(expected)
        self.actions.append([4,id,1,plane,bytes_,size,size,self.event,version,mode,slot,0])
        self.readbacks.append(dict(event=self.event,target_id=id,plane=plane,bytes=bytes_,width=size,height=size,
                                   version=version,sequence=self.sequence,expected=expected.hex(),label=label))
    def samples(self,expected,label):
        self.begin()
        for level in range(4):self.emit(draw(30+level,128>>level,101,level,texture=20));self.versions[30+level]+=1
        self.submit()
        for level,e in enumerate(expected):self.read(30+level,128>>level,e,self.versions[30+level],label=f'{label}/mip{level}')

def fixture():
    f=Fixture();initial=[pattern(128>>level,level) for level in range(4)]
    f.begin()
    for id,size,fmt,mips,usage,type in [(1,128,1,1,3,1),(2,128,3,1,2,1),(3,4,1,1,3,1),
        (20,128,1,4,1,1),(60,128,1,1,3,1),(70,128,2,1,3,1),(80,128,1,1,1,1),
        (81,128,1,4,1,1),(90,128,1,1,1,2),(91,4,2,1,3,1),(92,4,2,1,1,1),(34,4,1,1,3,1),
        (95,128,1,1,1,1)]+[(10+i,128>>i,1,1,3,1) for i in range(4)]+[(30+i,128>>i,1,1,3,1) for i in range(4)]:
        f.emit(create(id,size,fmt,mips,usage,type));f.versions[id]=0
    f.emit(struct.pack('<4I',2,16,95,1));f.emit(create(95,128,usage=1,gen=2))
    f.emit(program(100,PATTERN));f.emit(program(101,SAMPLE));f.emit(struct.pack('<6I',12,24,200,1,2,0))
    f.emit(clear(1,128,2));f.versions[1]=f.versions[2]=1
    f.emit(upload(3,bytes((17,23,31,255))*16,4));f.versions[3]=1
    for id in [60,70,34,91]+list(range(10,14))+list(range(30,34)):
        size=4 if id in (34,91) else 128>>(id-10) if 10<=id<14 else 128>>(id-30) if 30<=id<34 else 128
        f.emit(clear(id,size));f.versions[id]=1
    f.emit(struct.pack('<4I',14,16,200,1))
    f.emit(draw(10,128,100,0));f.versions[10]+=1
    f.emit(struct.pack('<4I',15,16,200,1))
    for level in range(1,4):f.emit(draw(10+level,128>>level,100,level));f.versions[10+level]+=1
    f.emit(draw(91,4,100,4));f.versions[91]+=1
    for level in range(4):f.emit(copy(src=10+level,dm=level,size=128>>level));f.composite_versions.append(level+1)
    f.emit(copy(src=91,dst=92,size=4))
    f.emit(draw(34,4,101,0,texture=92));f.versions[34]+=1
    f.emit(struct.pack('<12I',5,48,10,1,60,1,0,0,0,0,128,128));f.versions[60]+=1
    f.submit()
    for level in range(4):f.read(10+level,128>>level,initial[level],2,label=f'rendered-source/mip{level}')
    f.read(91,4,pattern(4,4,bgra=True),2,label='bgra-rendered-source')
    f.read(34,4,pattern(4,4),2,label='bgra-copy-sampled-as-rgba')
    f.read(60,128,initial[0],2,label='legacy-copy-level-zero')
    f.samples(initial,'initial-composite')
    f.begin();f.emit(draw(12,32,100,2,1));f.versions[12]+=1;f.submit()
    f.read(12,32,pattern(32,2,1),3,label='one-source-mutated')
    f.samples(initial,'old-composite-retained')
    updated=list(initial);updated[2]=pattern(32,2,1)
    f.begin();f.emit(copy(src=12,dm=2,size=32));f.submit();f.composite_versions.append(5)
    f.samples(updated,'one-mip-recopied')
    updated[1]=copy_region(initial[1],64,initial[1],64,8,8,24,24,16,16)
    f.begin();f.emit(copy(src=11,dm=1,size=64,sx=8,sy=8,dx=24,dy=24,w=16,h=16));f.submit();f.composite_versions.append(6)
    f.samples(updated,'partial-mip-retention')
    baselines=[(1,128,bytes((0,0,0,255))*16384,1,1),(2,128,struct.pack('<f',1)*16384,1,2),
               (2,128,bytes([7])*16384,1,4),(3,4,bytes((17,23,31,255))*16,1,1),
               (200,1,struct.pack('<Q',16384),1,8)]
    for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,1,slot,label='atomic-baseline')
    cases=[('source-mip',copy(sm=1),-1),('destination-mip',copy(dm=4),-1),('source-slice',copy(ss=1),-1),
       ('destination-slice',copy(ds=1),-1),('plane-zero',copy(plane=0),-1),('plane-depth',copy(plane=2),-1),
       ('plane-extra',copy(plane=9),-1),('reserved',copy(reserved=1),-1),('format',copy(dst=70),-2),
       ('source-uninitialized',copy(src=80),-7),('partial-destination-uninitialized',copy(dst=81,w=16,h=16),-7),
       ('source-x',copy(sx=1),-1),('destination-x',copy(dx=1),-1),('zero-width',copy(w=0),-1),
       ('zero-height',copy(h=0),-1),('overflow-x',copy(sx=0xffffffff),-1),
       ('same-subresource',copy(src=20,dst=20),-1),('same-id-distinct-mips',copy(src=20,dst=20,dm=1,size=64),-1),
       ('source-stale-generation',copy(src=95),-3),('destination-stale-generation',copy(dst=95),-3),
       ('cube-source',copy(src=90),-2),('cube-destination',copy(dst=90),-2),('depth-source',copy(src=2),-2),
       ('short-fixed-metadata',copy()[:-8],-1),('long-fixed-metadata',copy()+bytes(8),-1)]
    for label,invalid,status in cases:
        f.begin();f.emit(struct.pack('<4I',14,16,200,1))
        f.emit(clear(1,128,2,(1,0,1,1),.25,99));f.emit(upload(3,bytes((99,77,55,255))*4,2))
        f.emit(draw(1,128,100,6,depth=2,half=True));f.emit(struct.pack('<4I',15,16,200,1))
        f.emit(invalid);f.submit(status,5,label)
        for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,2,slot,label=f'atomic/{label}')
        f.samples(updated,f'composite-after-reject/{label}')
    return f

def snapshot(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
           'port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm','port/macos/include/halo_metal_abi.h',
           'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm',
           'port/macos/tests/guest_metal_copy_subresource.c','port/linux/src/metal_guest_transport.h',
           'port/linux/src/metal_guest_transport.c','port/macos/metal_imports.list',
           'tools/metal_copy_subresource_validate.py','tools/metal_host_frame_validate.py','tools/metal_host_draw_validate.py',
           'tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py']
    records={}
    for name in names:
        source=ROOT/name;dest=out/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        digest=sha(source);shutil.copy2(source,dest);require(sha(source)==sha(dest)==digest,'Source changed during freeze')
        records[str(source)]=dict(snapshot=str(dest),sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    require(len(nodes)==1,'Guest ABI flags missing');flags=ast.literal_eval(nodes[0].value)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    run=frame.run
    for name,path in [('guest','port/macos/tests/guest_metal_copy_subresource.c'),('transport','port/linux/src/metal_guest_transport.c')]:
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

def prepare(out,llvm,linker,plugin):
    require(not out.exists(),'Preserve prior proof; output must be fresh');out.mkdir(parents=True)
    records=snapshot(out);f=fixture()
    (out/'inputs.bin').write_bytes(f.inputs);actions=out/'actions.bin'
    actions.write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_copy_inputs\nhalo_copy_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+
        '\n.balign 16\n.global halo_copy_actions\nhalo_copy_actions:\n.incbin '+json.dumps(str(actions))+'\n')
    (out/'metal_copy_subresource_fixture.h').write_text(f'#define HALO_COPY_ACTIONS {len(f.actions)}u\n#define HALO_COPY_INPUT_BYTES {len(f.inputs)}u\n#define HALO_COPY_PACKET_CAPACITY 1048576u\n#define HALO_COPY_REQUIRED_CAPS 4319u\n')
    for n,p in enumerate(f.packets):
        path=out/f'packet-{n:03}.bin';path.write_bytes(bytes.fromhex(p.pop('bytes')));p['file']=str(path);p['sha256']=sha(path)
    package=dict(schema_version=1,kind='rendered_mip_copy_fixture',complete=True,actions=len(f.actions),packets=f.packets,
                 readbacks=f.readbacks,negative_cases=f.negative,composite_expected_version_progression=f.composite_versions,
                 expected_after_gpu_uploaded=False,source_levels=[128,64,32,16],required_capabilities=4319)
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n')
    symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out)
    native=out/'native';native.mkdir()
    command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    dependencies=[Path(r['snapshot']) for r in records.values()]+sources+[plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',actions,
       out/'fixture.s',out/'metal_copy_subresource_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json',Path(__file__)]+[Path(p['file']) for p in f.packets]
    prepared=dict(schema_version=1,kind='rendered_mip_copy_prepared',complete=False,passed=False,fixture_sha256=sha(out/'fixture.json'),
        source_snapshot=records,source_and_binary_sha256={str(p):sha(p) for p in dependencies},execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(out/'prepared.json'),negative_cases=len(f.negative),readbacks=len(f.readbacks),actions=len(f.actions)),indent=2))

def verify_prepared(out):
    p=json.loads((out/'prepared.json').read_text());f=json.loads((out/'fixture.json').read_text())
    require(sha(out/'fixture.json')==p['fixture_sha256'],'Fixture changed')
    for path,digest in p['source_and_binary_sha256'].items():require(sha(path)==digest,'Frozen input changed: '+path)
    return p,f

def execute(out):
    require(not (out/'execution.json').exists(),'Preserve previous execution');p,f=verify_prepared(out)
    env=dict(os.environ);env.update(p['validation_environment']);run=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(run.stdout);(out/'native.stderr').write_text(run.stderr)
    execution=dict(schema_version=1,kind='rendered_mip_copy_execution',complete=True,returncode=run.returncode,command=p['execution_command'],
        prepared_sha256=sha(out/'prepared.json'),executor_sha256=sha(__file__),validation_environment=p['validation_environment'],
        stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution,indent=2)+'\n');verify_prepared(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());record=json.loads(run.stdout);expected={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=expected.pop(actual['event']);file=out/'native'/actual['file'];data=file.read_bytes();reference=bytes.fromhex(e['expected'])
        valid=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        comparisons.append(dict(event=e['event'],label=e['label'],file=str(file),sha256=sha(file),expected_sha256=hashlib.sha256(reference).hexdigest(),
            different_bytes=sum(a!=b for a,b in zip(data,reference)) if len(data)==len(reference) else -1,metadata_valid=valid))
    report=dump['report'];validation='Metal API Validation Enabled' in run.stderr
    passed=run.returncode==0 and record.get('guest_result')==0 and report[:2]==[1,4] and not expected and validation and all(c['different_bytes']==0 and c['metadata_valid'] for c in comparisons)
    result=dict(p,complete=True,passed=passed,returncode=run.returncode,guest_run=record,guest_report=report,comparisons=comparisons,
        compared_readbacks=len(comparisons),missing_readbacks=len(expected),negative_cases=len(f['negative_cases']),gpu_api_validation_enabled=validation,
        execution=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),full_game_gate=False,original_water_gate=False,
        original_cpu_query_timing_gate=False,limits=['Synthetic rendered-mip patterns only; original water shader/material fidelity remains separate.',
        'Multi-mip sampled destination has no direct readback/version entrypoint; all four contents are independently GPU-sampled.',
        'Expected pixels remain in host CPU comparison; no expected after-target upload is used.'])
    verify_prepared(out);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,returncode=run.returncode,guest_report=report,readbacks=len(comparisons),missing=len(expected),
        first_difference=next((c for c in comparisons if c['different_bytes'] or not c['metadata_valid']),None),result=str(out/'result.json')),indent=2))
    return 0 if passed else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','execute']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    a=p.parse_args();out=a.out.resolve()
    if a.mode=='prepare':prepare(out,a.llvm,a.linker,a.plugin);return 0
    return execute(out)
if __name__=='__main__':sys.exit(main())
