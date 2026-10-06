#!/usr/bin/env python3
"""Source-bound indexed-buffer contents/order proof through actual ILP32 imports.

The failed loading draw's generated shaders, inputs, uniforms and state remain
unchanged except for its sampled references, which resolve to distinct history.
Synthetic full-screen sampling and resize descriptors are separate controls.
This does not establish original SDK buffer rotation or a live map transition.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import metal_copy_subresource_validate as copy
import metal_host_draw_validate as wire
import metal_host_frame_coalesce as parse
import metal_host_frame_validate as frame

sha, require = wire.sha, wire.require
FAILED = ROOT / 'build/macos-metal/map-transition-125-attempt2'
PACKET = FAILED / 'dumps/native-failure-frame464-packet.bin'
CONTRACT = FAILED / 'indexed-buffer-source-contract.json'
W, H = 640, 480


def loading_route():
    data = PACKET.read_bytes()
    require(sha(PACKET) == '3beca702cb0a92b553345436cbcb88e85bdc5025760b084548db7752ec17e3c8', 'Original failure packet changed')
    sequence, records = parse.commands(data)
    program, draw = records[2], records[3]
    require(sequence == 1398 and program['opcode'] == 7 and draw['opcode'] == 9, 'Wrong loading route')
    require(struct.unpack_from('<I', program['fixed'], 8)[0] == 54, 'Wrong original program')
    require(struct.unpack_from('<2I', draw['fixed'], 376) == (4, 6), 'Wrong original quad')
    payloads = dict(program['payloads'])
    for field, stage in ((20, 'vertex'), (28, 'pixel')):
        require(payloads[field] == (FAILED / f'dumps/native-failure-frame464-program-54-{stage}.metal').read_bytes(), 'Shader dump differs from original packet')
    inputs = dict(draw['payloads'])
    # Independent semantic observation, not an ideal four-coordinate blur claim:
    # VS reads v0/v4/v9, emits only T0; captured v0 spans +/-1.0078125 pixels.
    require(all(struct.unpack_from('<4f', inputs[392], n*256)[2:] == (.5, 1.) for n in range(4)), 'Unexpected original positions')
    require([struct.unpack_from('<2f', inputs[392], n*256) for n in range(4)] ==
            [(-1.0078125,1.0078125),(1.0078125,1.0078125),(1.0078125,-1.0078125),(-1.0078125,-1.0078125)], 'Original position footprint changed')
    require(all(struct.unpack_from('<2f', inputs[392], n*256+4*16) == (55.,50.) for n in range(4)), 'Original fixed UV changed')
    require(struct.unpack('<6I', inputs[396]) == (0,1,2,0,2,3), 'Original fan order changed')
    fixed = bytearray(draw['fixed'])
    for field in (32,40,48,56): struct.pack_into('<2I', fixed, field, 3, 1)
    return program, (bytes(fixed), draw['payloads']), records


def create(id, width=W, height=H, fmt=2):
    return struct.pack('<12I',10,48,id,1,fmt,width,height,1,1,1,3 if fmt != 3 else 2,0)


def upload(id, data, width=W, height=H):
    return struct.pack('<18I',11,72,id,1,0,0,0,0,0,width,height,1,width*4,width*height*4,0,len(data),1,0), [(56,data)]


def clear(id, width=W, height=H, color=(0,0,0,1), depth=0):
    planes=(1 if id else 0)|(6 if depth else 0)
    return struct.pack('<12I5fI',4,72,id,1 if id else 0,depth,1 if depth else 0,planes,0,0,width,height,91,*color,.75,0)


def image(width, height, phase=0):
    # Byte-exact initial input, never an expected after-render image upload.
    return b''.join(bytes((48+16*((x//32+y//32+phase)%3),32+16*((x//32+phase)%3),16+16*((y//32+phase)%3),255))
                    for y in range(height) for x in range(width))


def sample_draw(id, texture, width=W, height=H):
    fixed, payloads = copy.draw(id, width, 101, texture=texture)
    fixed = bytearray(fixed)
    # Synthetic descriptor-only sampling control retains full rectangular size.
    struct.pack_into('<2f', fixed, 312, float(width), float(height))
    struct.pack_into('<2I', fixed, 336, width, height)
    payloads = [(field, struct.pack('<4f',width,height,0,0)+bytes(592) if field == 404 else data) for field,data in payloads]
    return bytes(fixed), payloads


SAMPLE = '''#include <metal_stdlib>
using namespace metal;
struct In { float4 position [[position]]; };
struct Out { float4 color [[color(0)]]; uint mask [[sample_mask]]; };
fragment Out xgpu_fragment(In i [[stage_in]], constant float4 &p [[buffer(0)]],
 texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {
 Out o; o.color=t.sample(s,i.position.xy/p.xy,level(0.0f)); o.mask=0xffffffffu; return o;
}
'''


class Fixture(copy.Fixture):
    def read_rect(self,id,width,height,expected,version,plane=1,mode=0,slot=0,label=''):
        self.event += 1
        self.actions.append([4,id,1,plane,len(expected),width,height,self.event,version,mode,slot,0])
        self.readbacks.append(dict(event=self.event,target_id=id,plane=plane,bytes=len(expected),width=width,height=height,
                                   version=version,sequence=self.sequence,expected=expected.hex(),label=label))


def fixture():
    f = Fixture(); program, actual_draw, _ = loading_route()
    initial_current, initial_history = image(W,H,1), image(W,H)
    black = bytes((0,0,0,255))*(W*H)
    first = bytearray(black); first[:4] = initial_history[:4]; first = bytes(first)
    second = bytearray(bytes((16,12,8,255))*(W*H))
    second[:4] = bytes((first[0]+16,first[1]+12,first[2]+8,255)); second = bytes(second)
    f.begin()
    for id,fmt in ((1,2),(2,3),(3,2),(4,2)): f.emit(create(id,fmt=fmt))
    f.emit(upload(1,initial_current)); f.emit(upload(3,initial_history))
    f.emit(clear(0,depth=2)); f.emit(clear(4))
    f.emit((program['fixed'],program['payloads'])); f.emit(copy.program(101,SAMPLE)); f.submit()
    f.read_rect(1,W,H,initial_current,1,label='distinct-current-initial')
    f.read_rect(3,W,H,initial_history,1,label='distinct-history-initial')
    # Current clear precedes Get(-1) in original progress rendering. Do not take
    # a lazy snapshot here: it would replace the history with cleared pixels.
    f.begin(); f.emit(clear(1)); f.emit(actual_draw); f.submit()
    f.read_rect(1,W,H,first,3,label='actual-program54-retained-history-after-current-clear')
    f.read_rect(3,W,H,initial_history,1,label='skip-capture-history-preserved')
    f.begin(); f.emit(sample_draw(4,3)); f.submit()
    f.read_rect(4,W,H,initial_history,2,label='synthetic-full-image-history-sample')
    f.begin(); f.emit(copy.copy(src=1,dst=3,w=W,h=H)); f.submit()
    f.read_rect(3,W,H,first,2,label='present-boundary-full-exact-copy')
    f.begin(); f.emit(clear(1,color=(8/255,12/255,16/255,1))); f.emit(actual_draw); f.submit()
    f.read_rect(1,W,H,second,5,label='actual-next-frame-history-survives-new-current-clear')
    f.read_rect(3,W,H,first,2,label='history-does-not-advance-on-draw-readback')
    f.begin(); f.emit(sample_draw(4,3)); f.submit()
    f.read_rect(4,W,H,first,3,label='synthetic-full-image-after-present-copy')
    # Explicit startup capture clear differs from map-change skip-capture.
    f.begin(); f.emit(clear(3)); f.emit(clear(1)); f.emit(actual_draw); f.submit()
    f.read_rect(3,W,H,black,3,label='explicit-history-clear')
    f.read_rect(1,W,H,black,7,label='actual-program54-cleared-history')
    baseline=[(1,black,7,1),(3,black,3,1),(2,struct.pack('<f',.75)*(W*H),1,2),(2,bytes([91])*(W*H),1,4),(4,first,3,1)]
    for slot,(id,data,version,plane) in enumerate(baseline):
        f.read_rect(id,W,H,data,version,plane,1,slot,label='actual-atomic-baseline')
    f.begin(); f.emit(clear(1,color=(1,0,1,1))); f.emit(copy.copy(src=1,dst=3,w=W,h=H))
    f.emit(copy.copy(src=1,dst=3,w=W+1,h=H)); f.submit(-1,2,'late-invalid-copy-after-current-clear-and-history-copy')
    for slot,(id,data,version,plane) in enumerate(baseline):
        f.read_rect(id,W,H,data,version,plane,2,slot,label='actual-atomic-rollback')
    # Synthetic bounded overlap only. No filtered resizing or SDK width parity.
    small=image(16,8); grown=bytearray(24*8*4)
    for y in range(8): grown[y*24*4:y*24*4+16*4]=small[y*16*4:(y+1)*16*4]
    shrink=b''.join(grown[y*24*4:y*24*4+8*4] for y in range(8))
    restored=bytearray(16*8*4)
    for y in range(8): restored[y*16*4:y*16*4+8*4]=shrink[y*8*4:(y+1)*8*4]
    f.begin()
    for id,w in ((10,16),(11,24),(12,8)): f.emit(create(id,w,8))
    f.emit(upload(10,small,16,8)); f.emit(clear(11,24,8,color=(0,0,0,0))); f.emit(copy.copy(src=10,dst=11,w=16,h=8)); f.submit()
    f.read_rect(11,24,8,bytes(grown),2,label='synthetic-grow-overlap-new-area-zero')
    f.begin(); f.emit(clear(12,8,8,color=(0,0,0,0))); f.emit(copy.copy(src=11,dst=12,w=8,h=8)); f.submit()
    f.read_rect(12,8,8,shrink,2,label='synthetic-shrink-exact-no-resampling')
    f.begin(); f.emit(clear(10,16,8,color=(0,0,0,0))); f.emit(copy.copy(src=12,dst=10,w=8,h=8)); f.submit()
    f.read_rect(10,16,8,bytes(restored),3,label='synthetic-cached-shape-reuse-clear-before-overlap')
    f.read_rect(2,W,H,struct.pack('<f',.75)*(W*H),1,2,label='depth-preserved-all-history-operations')
    f.read_rect(2,W,H,bytes([91])*(W*H),1,4,label='stencil-preserved-all-history-operations')
    return f


def snapshot(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
           'port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm','port/macos/include/halo_metal_abi.h',
           'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm',
           'port/macos/tests/guest_metal_backbuffer_history.c','port/linux/src/metal_guest_transport.h',
           'port/linux/src/metal_guest_transport.c','port/linux/src/d3d8_metal.c','port/linux/src/metal_draw_state.c',
           'port/macos/metal_imports.list','tools/metal_backbuffer_history_validate.py',
           'tools/metal_copy_subresource_validate.py','tools/metal_host_frame_validate.py','tools/metal_host_frame_coalesce.py',
           'tools/metal_host_draw_validate.py','tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py']
    records={}
    for n in names:
        source=ROOT/n; dest=out/'source-snapshot'/n; dest.parent.mkdir(parents=True,exist_ok=True)
        digest=sha(source); shutil.copyfile(source,dest); require(sha(source)==sha(dest)==digest,'Source changed during freeze')
        records[str(source)]=dict(snapshot=str(dest),sha256=digest)
    for source in (PACKET,CONTRACT,ROOT/'build/metal-poc/backbuffer-history-cpu-validation/closure.json'):
        dest=out/'original-inputs'/source.name; dest.parent.mkdir(exist_ok=True); shutil.copyfile(source,dest)
        require(sha(source)==sha(dest),'Original input changed during freeze')
        records[str(source)]=dict(snapshot=str(dest),sha256=sha(dest))
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n'); return records


def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    require(len(nodes)==1,'Guest ABI flags missing');flags=ast.literal_eval(nodes[0].value)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    for name,path in [('guest','port/macos/tests/guest_metal_backbuffer_history.c'),('transport','port/linux/src/metal_guest_transport.c')]:
        frame.run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
            '-DHALO_MACOS=1','-DHALO_MACOS_NATIVE_METAL=1','-I',out,'-emit-llvm','-S',frozen/path,'-o',out/(name+'.ll'))
        frame.run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/(name+'.ll'),'-o',out/(name+'.rebased.ll'))
        frame.run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/(name+'.rebased.ll'),'-o',out/(name+'.darwin.s'))
        frame.run(sys.executable,frozen/'tools/android_asm_convert.py',out/(name+'.darwin.s'),out/(name+'.s'))
    for name in ('guest','transport','fixture'): frame.run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    (out/'diagnostic-imports.list').write_text((frozen/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n')
    frame.run(sys.executable,frozen/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    frame.run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    frame.run(linker,'-m','aarch64elf','-T',out/'guest.ld',*[out/(n+'.o') for n in ('guest','transport','fixture','imports')],'-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3: symbols[fields[2]]=int(fields[0],16)
    sizes=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sizes.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    require(span<=512*1024*1024,'Fixture exceeds bounded guest arena'); return symbols,span


def prepare(out,llvm,linker,plugin):
    require(not out.exists(),'Output must be fresh');out.mkdir(parents=True)
    records=snapshot(out); f=fixture()
    (out/'inputs.bin').write_bytes(f.inputs);actions=out/'actions.bin'
    actions.write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_history_inputs\nhalo_history_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+
        '\n.balign 16\n.global halo_history_actions\nhalo_history_actions:\n.incbin '+json.dumps(str(actions))+'\n')
    (out/'metal_backbuffer_history_fixture.h').write_text(f'#define HALO_HISTORY_ACTIONS {len(f.actions)}u\n#define HALO_HISTORY_INPUT_BYTES {len(f.inputs)}u\n#define HALO_HISTORY_PACKET_CAPACITY 8388608u\n#define HALO_HISTORY_SCRATCH 1228800u\n#define HALO_HISTORY_REQUIRED_CAPS 4319u\n')
    for n,p in enumerate(f.packets):
        path=out/f'packet-{n:03}.bin';path.write_bytes(bytes.fromhex(p.pop('bytes')));p['file']=str(path);p['sha256']=sha(path)
    package=dict(schema_version=1,kind='indexed_history_contents_fixture',complete=True,actions=len(f.actions),packets=f.packets,
        readbacks=f.readbacks,negative_cases=f.negative,expected_after_gpu_uploaded=False,
        actual_original_route='Failed frame464/program54 VS/PS/expanded inputs/constants/state retained; only sampled references resolve to distinct history.',
        captured_route_limit='Captured immediate VS reads v0/v4/v9 and emits only T0; its +/-1.0078125-pixel geometry covers one pixel. This is not proof of the intended full-screen four-tap blur.',
        synthetic_controls='Full-screen nearest sampling and rectangular grow/shrink descriptors only.',
        frontend_executed=False,original_sdk_rotation_gate=False,live_map_transition_gate=False)
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n')
    symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out)
    native=out/'native';native.mkdir()
    command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    paths=[Path(r['snapshot']) for r in records.values()]+sources+[Path(__file__),plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',actions,
        out/'fixture.s',out/'metal_backbuffer_history_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json']+[Path(p['file']) for p in f.packets]
    for path,row in records.items(): require(sha(path)==row['sha256'],'Current source changed while preparing')
    prepared=dict(schema_version=1,kind='indexed_history_contents_prepared',complete=False,passed=False,gpu_executed=False,
        fixture_sha256=sha(out/'fixture.json'),source_snapshot=records,source_and_binary_sha256={str(p):sha(p) for p in paths},
        execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(out/'prepared.json'),readbacks=len(f.readbacks),negative_cases=len(f.negative),execution_command=command),indent=2))


def verify(out):
    p=json.loads((out/'prepared.json').read_text());f=json.loads((out/'fixture.json').read_text())
    require(sha(out/'fixture.json')==p['fixture_sha256'],'Fixture changed')
    for path,digest in p['source_and_binary_sha256'].items(): require(sha(path)==digest,'Frozen input changed: '+path)
    for path,row in p['source_snapshot'].items(): require(sha(path)==sha(row['snapshot'])==row['sha256'],'Source drift: '+path)
    return p,f


def execute(out):
    require(not (out/'execution.json').exists(),'Preserve prior execution'); p,f=verify(out)
    env=dict(os.environ);env.update(p['validation_environment'])
    observed=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(observed.stdout);(out/'native.stderr').write_text(observed.stderr)
    record=dict(schema_version=1,kind='indexed_history_contents_execution',complete=True,returncode=observed.returncode,
        command=p['execution_command'],prepared_sha256=sha(out/'prepared.json'),executor_sha256=sha(__file__),validation_environment=p['validation_environment'],
        stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');verify(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());run=json.loads(observed.stdout)
    expected={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=expected.pop(actual['event']);file=out/'native'/actual['file'];data=file.read_bytes();reference=bytes.fromhex(e['expected'])
        metadata=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        comparisons.append(dict(event=e['event'],label=e['label'],file=str(file),sha256=sha(file),expected_sha256=hashlib.sha256(reference).hexdigest(),
            different_bytes=sum(a!=b for a,b in zip(data,reference)) if len(data)==len(reference) else -1,metadata_valid=metadata))
    validation='Metal API Validation Enabled' in observed.stderr
    passed=observed.returncode==0 and run.get('guest_result')==0 and dump['report'][:2]==[1,4] and not expected and validation and all(c['different_bytes']==0 and c['metadata_valid'] for c in comparisons)
    result=dict(p,complete=True,passed=passed,gpu_executed=True,returncode=observed.returncode,guest_run=run,guest_report=dump['report'],comparisons=comparisons,
        compared_readbacks=len(comparisons),missing_readbacks=len(expected),gpu_api_validation_enabled=validation,
        execution_sha256=sha(out/'execution.json'),frontend_executed=False,original_sdk_rotation_gate=False,live_map_transition_gate=False,full_game_gate=False,
        limits=[f['captured_route_limit'],'Expected after images stay in CPU comparison; only independent initial inputs are uploaded.','No SDK physical swap ordering, CPU locks, presentation timing, frontend execution or live map-transition success follows from this isolated fixture.'])
    verify(out);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,returncode=observed.returncode,readbacks=len(comparisons),first_difference=next((c for c in comparisons if c['different_bytes'] or not c['metadata_valid']),None)),indent=2))
    return 0 if passed else 1


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','execute']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    a=p.parse_args();out=a.out.resolve()
    if a.mode=='prepare': prepare(out,a.llvm,a.linker.absolute(),a.plugin); return 0
    return execute(out)


if __name__=='__main__': sys.exit(main())
