#!/usr/bin/env python3
"""Source-bound ILP32 clear/draw proof for original mirrored target footprints.

Synthetic before-content is allowed; analytical expected after-content stays
on the CPU. The real guest C transport and original host encoder execute every
packet. This does not claim original c40 shader or physical Xbox parity.
"""
import argparse,ast,hashlib,json,os,shutil,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_host_draw_validate as wire
import metal_host_frame_validate as frame
sha,require=wire.sha,wire.require
VS='''#include <metal_stdlib>
using namespace metal;
struct VIn {float4 p [[attribute(0)]];};
struct VOut {float4 p [[position]];};
vertex VOut xgpu_vertex(VIn v [[stage_in]]) {VOut o; o.p=v.p; return o;}
'''
PS='''#include <metal_stdlib>
using namespace metal;
struct In {float4 p [[position]];};
struct Out {float4 c [[color(0)]]; uint mask [[sample_mask]];};
fragment Out xgpu_fragment(In v [[stage_in]], constant float4 &p [[buffer(0)]]) {Out o; o.c=p; o.mask=0xffffffffu; return o;}
'''

def create(id,w,h,fmt=1):return struct.pack('<12I',10,48,id,1,fmt,w,h,1,1,1,3,0)
def upload(id,w,h,plane,data):
    row=w*(1 if plane==4 else 4)
    return struct.pack('<18I',11,72,id,1,0,0,0,0,0,w,h,1,row,row*h,0,len(data),plane,0),[(56,data)]
def clear(color,depth,w,h,planes=7,mask=15,rgba=(10/255,13/255,22/255,0),z=1.,stencil=0,x=0,y=0):
    return struct.pack('<12I5f3I',17,80,color,1 if color else 0,depth,1 if depth else 0,planes,x,y,w,h,stencil,*rgba,z,0,mask,0)
def program():return struct.pack('<10I',7,40,100,1,0,0,len(VS.encode()),0,len(PS.encode()),0),[(20,VS.encode()),(28,PS.encode())]
def draw(color,depth,w,h,rect=None,z=.5,rgba=(64/255,128/255,192/255,1),stencil=True,raw_bank=False):
    x,y,sw,sh=rect if rect else (0,0,w,h)
    state=dict(viewport=dict(x=0,y=0,width=w,height=h,znear=0,zfar=1),scissor=dict(x=x,y=y,width=sw,height=sh),
        blend=dict(enabled=False,source='one',destination='zero',operation='add',write_mask=15),
        depth=dict(enabled=True,write=True,compare='less_equal'),
        stencil=dict(enabled=stencil,compare='equal' if stencil else 'always',reference=0,read_mask=255,write_mask=255 if stencil else 0,
            fail='keep',depth_fail='keep',**{'pass':'increment_wrap' if stencil else 'keep'}),
        raster=dict(front_face='cw',cull='none',fill='solid',depth_bias=0,slope_scale=0,depth_bias_clamp=0))
    refs=[100,1,color,1,depth,1,0,0,0,0,0,0,0,0]
    fixed=struct.pack('<16I',9,416,*refs)+bytes(160)+wire.state_bytes(state)+struct.pack('<10I',4,6,0,3,0,0,0,0,0,0)
    vertices=bytearray(1024)
    for i,p in enumerate(((-1,1,z,1),(1,1,z,1),(1,-1,z,1),(-1,-1,z,1))):struct.pack_into('<4f',vertices,i*256,*p)
    vu=bytearray(3120)
    if raw_bank:
        for offset,bits in ((0,0x7f800000),(23*16+12,0xffffffff),(3068,0xff800000)):struct.pack_into('<I',vu,offset,bits)
    return fixed,[(392,bytes(vertices)),(396,struct.pack('<6I',0,1,2,0,2,3)),(400,bytes(vu)),(404,struct.pack('<4f',*rgba)+bytes(592))]
def changed_payload(command,field,offset,bits):
    fixed,payloads=command;output=[]
    for name,data in payloads:
        if name==field:data=bytearray(data);struct.pack_into('<I',data,offset,bits);data=bytes(data)
        output.append((name,data))
    return fixed,output

def color_pattern(w,h):return bytes(v for y in range(h) for x in range(w) for v in ((17+x)&255,(33+y)&255,(71+x+y)&255,(90+x+2*y)&255))
def replace_rect(data,w,h,rect,value,bpp):
    x,y,rw,rh=rect;require(len(data)==w*h*bpp and len(value)==bpp,'Invalid analytical rectangle')
    result=bytearray(data)
    for row in range(y,y+rh):result[(row*w+x)*bpp:(row*w+x+rw)*bpp]=value*rw
    return bytes(result)

class Fixture:
    def __init__(self):self.inputs=bytearray();self.actions=[];self.readbacks=[];self.packets=[];self.negative=[];self.current=[];self.sequence=0;self.event=0
    def blob(self,data):self.inputs.extend(bytes((-len(self.inputs))&15));offset=len(self.inputs);self.inputs.extend(data);return offset
    def begin(self):self.actions.append([1]+[0]*11);self.current=[]
    def emit(self,command):
        fixed,payloads=command if isinstance(command,tuple) else (command,[]);descriptors=[]
        for field,data in payloads:descriptors.extend((field,self.blob(data),len(data)))
        offset=self.blob(fixed);payload=self.blob(struct.pack('<'+'I'*len(descriptors),*descriptors)) if descriptors else 0
        self.actions.append([2,offset,len(fixed),payload,len(payloads)]+[0]*7);self.current.append((fixed,payloads))
    def submit(self,status=0,failed=0,label=''):
        self.actions.append([3,status&0xffffffff,failed]+[0]*9);p=wire.Packet(self.sequence+1)
        for fixed,payloads in self.current:p.command(fixed,payloads)
        self.packets.append(dict(sequence=self.sequence+1,status=status,failed_command=failed,label=label,data=p.finish()))
        if status:self.negative.append(dict(label=label,status=status,failed_command=failed))
        else:self.sequence+=1
    def read(self,id,w,h,plane,data,version,label,mode=0,slot=0):
        self.event+=1;self.actions.append([4,id,1,plane,len(data),w,h,self.event,version,mode,slot,0])
        self.readbacks.append(dict(event=self.event,target_id=id,plane=plane,bytes=len(data),width=w,height=h,version=version,sequence=self.sequence,label=label,data=data))

def fixture():
    f=Fixture();mw,mh,pw,ph=320,240,640,480
    mirror=color_pattern(mw,mh);primary=color_pattern(pw,ph)
    depth=struct.pack('<'+'f'*(pw*ph),*(.25+(x+2*y)/4096 for y in range(ph) for x in range(pw)))
    stencil=bytes((49+x+3*y)&255 for y in range(ph) for x in range(pw))
    f.begin()
    for c in (create(10,mw,mh),create(11,pw,ph),create(12,pw,ph,3),create(13,pw,120,3),program()):f.emit(c)
    for c in (upload(10,mw,mh,1,mirror),upload(11,pw,ph,1,primary),upload(12,pw,ph,2,depth),upload(12,pw,ph,4,stencil),
              upload(13,pw,120,2,struct.pack('<f',1)*(pw*120)),upload(13,pw,120,4,bytes(pw*120))):f.emit(c)
    f.submit(label='independent before seeds')
    f.read(10,mw,mh,1,mirror,1,'mirror before');f.read(11,pw,ph,1,primary,1,'primary before')
    f.read(12,pw,ph,2,depth,2,'primary depth before');f.read(12,pw,ph,4,stencil,2,'primary stencil before')
    f.begin();f.emit(clear(10,12,mw,mh));f.submit(label='actual mirror color+larger primaryZ clear')
    mirror=bytes((10,13,22,0))*(mw*mh)
    depth=replace_rect(depth,pw,ph,(0,0,mw,mh),struct.pack('<f',1),4);stencil=replace_rect(stencil,pw,ph,(0,0,mw,mh),b'\0',1)
    f.read(10,mw,mh,1,mirror,2,'mirror clear');f.read(12,pw,ph,2,depth,3,'mirror clear outside depth preserved');f.read(12,pw,ph,4,stencil,3,'mirror clear outside stencil preserved')
    rect=(40,30,200,120);f.begin();f.emit(draw(10,12,mw,mh,rect=rect,raw_bank=True));f.submit(label='cropped mirror draw with raw nonfinite constant-bank lanes')
    mirror=replace_rect(mirror,mw,mh,rect,bytes((64,128,192,255)),4)
    depth=replace_rect(depth,pw,ph,rect,struct.pack('<f',.5),4);stencil=replace_rect(stencil,pw,ph,rect,b'\1',1)
    f.read(10,mw,mh,1,mirror,3,'cropped mirror color');f.read(12,pw,ph,2,depth,4,'cropped mirror outside depth preserved');f.read(12,pw,ph,4,stencil,4,'cropped mirror outside stencil preserved')
    f.begin();f.emit(draw(11,12,pw,ph,z=.75,rgba=(200/255,44/255,90/255,1),stencil=False));f.submit(label='primary draw reuses physical primaryZ')
    for y in range(mh):
        for x in range(mw):
            if not (rect[0]<=x<rect[0]+rect[2] and rect[1]<=y<rect[1]+rect[3]):
                primary=bytearray(primary) if isinstance(primary,bytes) else primary;depth=bytearray(depth) if isinstance(depth,bytes) else depth
                primary[(y*pw+x)*4:(y*pw+x)*4+4]=bytes((200,44,90,255));struct.pack_into('<f',depth,(y*pw+x)*4,.75)
    primary,depth=bytes(primary),bytes(depth)
    baseline=[(10,mw,mh,1,mirror,3),(11,pw,ph,1,primary,2),(12,pw,ph,2,depth,5),(12,pw,ph,4,stencil,5)]
    for slot,(id,w,h,plane,data,version) in enumerate(baseline):f.read(id,w,h,plane,data,version,'primary alias baseline',1,slot)
    bad=[('smaller depth clear',clear(10,13,160,120),-1),('smaller depth draw',draw(10,13,mw,mh),-2),
      ('clear exceeds color footprint',clear(10,12,321,240),-1),
      ('nonfinite native VS controls',changed_payload(draw(10,12,mw,mh),400,3072,0x7fc01234),-1),
      ('nonfinite pixel uniforms',changed_payload(draw(10,12,mw,mh),404,0,0x7f800000),-1),
      ('nonfinite nonpacked input',changed_payload(draw(10,12,mw,mh),392,0,0xffffffff),-1),
      ('out of range original index',changed_payload(draw(10,12,mw,mh),396,0,99),-1)]
    for label,command,status in bad:
        f.begin();f.emit(clear(11,0,pw,ph,planes=1,mask=15,rgba=(1,0,1,1)));f.emit(command);f.submit(status,1,label)
        for slot,(id,w,h,plane,data,version) in enumerate(baseline):f.read(id,w,h,plane,data,version,'atomic '+label,2,slot)
    # A full color clear initializes a fresh smaller color resource, even
    # though the same command only partially clears initialized primary-Z.
    f.begin();f.emit(create(14,mw,mh));f.emit(clear(14,12,mw,mh,rgba=(24/255,50/255,100/255,128/255),z=.875,stencil=19));f.submit(label='fresh smaller color plus partial initialized primaryZ')
    fresh=bytes((24,50,100,128))*(mw*mh)
    depth=replace_rect(depth,pw,ph,(0,0,mw,mh),struct.pack('<f',.875),4)
    stencil=replace_rect(stencil,pw,ph,(0,0,mw,mh),bytes((19,)),1)
    f.read(14,mw,mh,1,fresh,1,'fresh full color initialized by partial common clear')
    f.read(12,pw,ph,2,depth,6,'fresh clear outside primary depth preserved')
    f.read(12,pw,ph,4,stencil,6,'fresh clear outside primary stencil preserved')
    return f

SOURCES=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
 'port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm','port/macos/include/halo_metal_abi.h',
 'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm','port/macos/tests/guest_metal_unequal_attachments.c',
 'port/linux/src/metal_guest_transport.h','port/linux/src/metal_guest_transport.c','port/macos/metal_imports.list',
 'tools/metal_unequal_attachment_validate.py','tools/test_metal_unequal_attachments.py','tools/metal_host_frame_validate.py',
 'tools/metal_host_draw_validate.py','tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py',
 'source/render/render.c','source/rasterizer/xbox/rasterizer_xbox.c']
def snapshot(out):
    records={}
    for name in SOURCES:
        src=ROOT/name;dst=out/'source-snapshot'/name;dst.parent.mkdir(parents=True,exist_ok=True);digest=sha(src);shutil.copy2(src,dst)
        require(sha(src)==sha(dst)==digest,'Source changed during freeze');records[str(src)]=dict(snapshot=str(dst),sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    require(len(nodes)==1,'Guest ABI flags missing');flags=ast.literal_eval(nodes[0].value)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip());run=frame.run
    for name,path in [('guest','port/macos/tests/guest_metal_unequal_attachments.c'),('transport','port/linux/src/metal_guest_transport.c')]:
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
    require(not out.exists(),'Preserve previous proof; choose fresh output');out.mkdir(parents=True);records=snapshot(out);f=fixture()
    (out/'inputs.bin').write_bytes(f.inputs);(out/'actions.bin').write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_attachment_inputs\nhalo_attachment_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+'\n.balign 16\n.global halo_attachment_actions\nhalo_attachment_actions:\n.incbin '+json.dumps(str(out/'actions.bin'))+'\n')
    (out/'metal_unequal_attachment_fixture.h').write_text(f'#define HALO_ATTACHMENT_ACTIONS {len(f.actions)}u\n#define HALO_ATTACHMENT_INPUT_BYTES {len(f.inputs)}u\n#define HALO_ATTACHMENT_PACKET_CAPACITY 8388608u\n#define HALO_ATTACHMENT_READBACK_CAPACITY 1228800u\n#define HALO_ATTACHMENT_REQUIRED_CAPS 599u\n')
    expected=out/'expected';expected.mkdir()
    for n,p in enumerate(f.packets):
        path=out/f'packet-{n:03}.bin';path.write_bytes(p.pop('data'));p['file']=str(path);p['sha256']=sha(path)
    for r in f.readbacks:
        data=r.pop('data');digest=hashlib.sha256(data).hexdigest();path=expected/(digest+'.bin')
        if not path.exists():path.write_bytes(data)
        r['expected']=dict(file=str(path),sha256=digest)
    package=dict(kind='original_attachment_footprint_fixture',schema_version=1,complete=True,packets=f.packets,readbacks=f.readbacks,negative_cases=f.negative,expected_after_gpu_uploaded=False,
        mirror_extent=[320,240],primary_extent=[640,480],rawbank_original_padding_bits='ffffffff',scope='Synthetic independent source route; no original c40 VS or pixel oracle.')
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n');symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out);native=out/'native';native.mkdir()
    command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    dependencies=[Path(r['snapshot']) for r in records.values()]+sources+[plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',out/'actions.bin',out/'fixture.s',out/'metal_unequal_attachment_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json',Path(__file__)]+[Path(p['file']) for p in f.packets]+list(expected.glob('*.bin'))
    prepared=dict(kind='original_attachment_footprint_prepared',schema_version=1,complete=False,passed=False,fixture_sha256=sha(out/'fixture.json'),source_snapshot=records,
        source_and_binary_sha256={str(p):sha(p) for p in dependencies},execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(dict(prepared=str(out/'prepared.json'),readbacks=len(f.readbacks),atomic_guards=len(f.negative),command=command),indent=2))
def verify(out):
    p=json.loads((out/'prepared.json').read_text());f=json.loads((out/'fixture.json').read_text());require(sha(out/'fixture.json')==p['fixture_sha256'],'Fixture drift')
    for path,digest in p['source_and_binary_sha256'].items():require(sha(path)==digest,'Frozen dependency drift: '+path)
    return p,f

def execute(out):
    require(not (out/'execution.json').exists(),'Preserve previous execution');p,f=verify(out);env=dict(os.environ);env.update(p['validation_environment']);run=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(run.stdout);(out/'native.stderr').write_text(run.stderr)
    execution=dict(kind='original_attachment_footprint_execution',returncode=run.returncode,command=p['execution_command'],prepared_sha256=sha(out/'prepared.json'),executor_sha256=sha(__file__),
        validation_environment=p['validation_environment'],stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution,indent=2)+'\n');verify(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());record=json.loads(run.stdout);pending={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=pending.pop(actual['event']);path=out/'native'/actual['file'];data=path.read_bytes();expected=Path(e['expected']['file']).read_bytes()
        valid=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        comparisons.append(dict(event=e['event'],label=e['label'],actual_file=str(path),sha256=sha(path),expected_sha256=e['expected']['sha256'],different_bytes=sum(a!=b for a,b in zip(data,expected)) if len(data)==len(expected) else -1,metadata_valid=valid))
    report=dump['report'];validation='Metal API Validation Enabled' in run.stderr;errors=[x for x in run.stderr.splitlines() if 'Validation Error' in x or 'failed assertion' in x or 'Assertion failed' in x]
    passed=run.returncode==0 and record.get('guest_result')==0 and record.get('guest_pointer_bits')==32 and report[:2]==[1,4] and report[7]==len(f['negative_cases']) and report[9]==4*len(f['negative_cases']) and not pending and validation and not errors and all(c['different_bytes']==0 and c['metadata_valid'] for c in comparisons)
    result=dict(kind='original_attachment_footprint_result',complete=True,passed=passed,returncode=run.returncode,prepared=dict(file=str(out/'prepared.json'),sha256=sha(out/'prepared.json')),execution=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),
        guest_record=record,guest_report=report,comparisons=comparisons,readbacks=len(comparisons),missing=len(pending),atomic_guards=len(f['negative_cases']),actual_saved_byte_version_checks=report[9],
        api_validation_enabled=validation,api_validation_errors=errors,original_game_pixel_parity_gate=False,physical_xbox_gate=False,
        limits=['Exact synthetic320x240 mirrored color plus640x480 primary depth/stencil footprint; larger-depth outside bytes and later primary alias draw checked.',
                'NaN/Inf bank bytes are preserved for a synthetic shader that does not read them; no original VS9 execution claimed.',
                'All48 native VS control bytes/all608PS bytes/nonpacked vertices remain finite-validated; invalid later records cannot commit the earlier clear.'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(passed=passed,returncode=run.returncode,guest_report=report,readbacks=len(comparisons),missing=len(pending),first_difference=next((c for c in comparisons if c['different_bytes'] or not c['metadata_valid']),None),result=str(out/'result.json')),indent=2));return 0 if passed else 1

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','execute']);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));parser.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'));parser.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    a=parser.parse_args();out=a.out.resolve()
    if a.mode=='prepare':prepare(out,a.llvm,a.linker,a.plugin);return 0
    return execute(out)
if __name__=='__main__':sys.exit(main())
