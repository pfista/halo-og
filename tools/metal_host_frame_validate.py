#!/usr/bin/env python3
"""Execute ordered original attachments through the real ILP32 Metal imports.

Default full mode rejects missing native query support before submitting work.
The explicit attachments-only diagnostic executes the recorded draw sequence,
but never reports the complete native frame/query gate as passed.
"""
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_host_draw_validate as wire
import metal_frame_replay as frame

require=wire.require
sha=wire.sha
payload=wire.payload
INIT_EVENT=0xffffffff
PLANE_FIELDS={'color':1,'depth_values':2,'stencil_values':4}

def query_gate(manifest,diagnostic,native_queries=False):
    queries=[c for c in manifest['commands'] if c['kind'].startswith('visibility_')]
    require(diagnostic or native_queries or not queries,'Original cached query timing/presentation is unverified; full-mode submission rejected')
    return queries

def query_plan(commands):
    """Pair original Boolean query scopes by order and recorded end event.

    Source uses GL_ANY_SAMPLES_PASSED when atomic_counters is false.
    Begin's scratch slot and end's saved slot are intentionally different.
    """
    plans={};active=None;ended={};next_id=20000
    for c in commands:
        kind=c['kind']
        if not kind.startswith('visibility_'):continue
        require(c.get('atomic_counters',False) is False,'Atomic-counter query path lacks a captured native contract')
        if kind=='visibility_begin':
            require(active is None,'Nested original visibility scope')
            active=dict(resource=next_id,generation=1,mode=1,begin_event=c['event']);next_id+=1
            plans[c['event']]=dict(active)
        elif kind=='visibility_end':
            require(active is not None and c.get('gl_query',0)>0,'Unpaired original query end')
            record=dict(active,end_event=c['event'],gl_query=c['gl_query']);plans[c['event']]=record
            ended[c['event']]=record;active=None
        elif kind=='visibility_gpu_result':
            record=ended.get(c.get('source_event'))
            require(record is not None and c.get('gl_query')==record['gl_query'] and c.get('available') is True,
                'GPU query result is not paired with completed original scope')
            require(c.get('any_samples_passed') in (0,1),'Original query result is not Boolean')
            plans[c['event']]=dict(record,expected_value=c['any_samples_passed'])
        else:require(kind=='visibility_cpu_result','Unknown visibility operation')
    require(active is None,'Original query scope remains active at frame end')
    return plans

def append_texture(packet,resource,texture,usage):
    format_id={'rgba8unorm':1,'bgra8unorm':2,'depth32float_stencil8':3,'bc1_rgba':4,'bc2_rgba':5,'bc3_rgba':6}.get(texture['pixel_format'])
    type_id={'2d':1,'cube':2}.get(texture.get('type','2d'))
    require(format_id and type_id,'Unsupported original wire texture format/type')
    levels=len(texture.get('mipmaps',[None]))
    packet.command(struct.pack('<12I',10,48,resource,1,format_id,texture['width'],texture['height'],1,type_id,levels,usage,0))

def append_upload(packet,resource,mip,slice_index,width,height,row,image,data,plane=1):
    fixed=struct.pack('<18I',11,72,resource,1,mip,slice_index,0,0,0,width,height,1,row,image,0,len(data),plane,0)
    packet.command(fixed,[(56,data)])

def append_initial(packet,root,resource,target):
    require(target['generation']==0,'Only original initial content-version0 may enter seed uploads')
    for field,descriptor in target['initial'].items():
        require(field in PLANE_FIELDS,'Unknown original initial attachment plane')
        plane=PLANE_FIELDS[field];bpp=1 if plane==4 else 4
        data=payload(root,descriptor);row=target['width']*bpp
        require(len(data)==row*target['height'],'Initial target byte count mismatch')
        append_upload(packet,resource,0,0,target['width'],target['height'],row,len(data),data,plane)

def compiler_contract(shader):
    require(shader['entry']=='xgpu_vertex','Unknown original vertex entry')
    policy=shader.get('compile_options')
    if policy is None:return 0
    require(policy==dict(contract='angle_metal_invariant_fast_v1',fast_math=True,preserve_invariance=True,
        math_mode='fast',floating_point_functions='fast'),'Unsupported original vertex compiler contract')
    require('compiler_evidence' in shader and 'compiler_baseline' in shader,'Missing compiler policy provenance')
    return 1

def fragment_contract(shader,root):
    require(shader['entry']=='xgpu_fragment','Unknown original fragment entry')
    from metal_draw_replay import fragment_wire_contract
    return fragment_wire_contract(shader,lambda descriptor:payload(root,descriptor))

def checkpoint_records(manifest,event,refs):
    records=[]
    for ref in refs:
        if ref is None:continue
        checkpoint=manifest['reference_checkpoints'][f"{ref['target_id']}:{ref['version']}"]
        for field,plane in PLANE_FIELDS.items():
            if field not in checkpoint:continue
            descriptor=checkpoint[field]
            records.append(dict(event=event,resource=ref['target_id'],target_id=ref['target_id'],version=ref['version'],
                plane=plane,width=checkpoint['width'],height=checkpoint['height'],bytes=descriptor['size'],expected=descriptor))
    return records

def make_steps(root,manifest,diagnostic,native_queries=False):
    queries=query_gate(manifest,diagnostic,native_queries);plans=query_plan(manifest['commands']) if native_queries else {}
    targets=manifest['targets'];textures=manifest['static_textures']
    setup=wire.Packet(1);texture_ids={};program_ids={};program_for_draw={}
    for name,t in targets.items():
        require(name==f"target-{t['id']}" and t['generation']==0,'Unexpected original target identity')
        append_texture(setup,t['id'],t,3)
        append_initial(setup,root,t['id'],t)
    for index,(name,t) in enumerate(textures.items()):
        resource=1000+index;texture_ids[name]=resource;append_texture(setup,resource,t,1)
        for level,mip in enumerate(t['mipmaps']):
            faces=mip['faces'] if t['type']=='cube' else [dict(mip,face=0)]
            for face in faces:
                append_upload(setup,resource,level,face['face'],mip['width'],mip['height'],face['bytes_per_row'],face['bytes_per_image'],payload(root,face))
    for name,d in manifest['draws'].items():
        vertex=d['shaders']['vertex'];fragment=d['shaders']['fragment']
        contract=compiler_contract(vertex);fragment_policy=fragment_contract(fragment,root)
        key=(vertex['sha256'],fragment['sha256'],contract,fragment_policy)
        if key not in program_ids:
            resource=10000+len(program_ids);program_ids[key]=resource
            vs=payload(root,vertex);ps=payload(root,fragment)
            setup.command(struct.pack('<10I',7,40,resource,1,contract,0,len(vs),0,len(ps),fragment_policy),[(20,vs),(28,ps)])
        program_for_draw[name]=program_ids[key]
    for event,q in plans.items():
        if event==q['begin_event']:setup.command(struct.pack('<6I',12,24,q['resource'],1,q['mode'],0))
    versions={t['id']:0 for t in targets.values()}
    steps=[dict(event=INIT_EVENT,packet=setup.finish(),checkpoints=checkpoint_records(manifest,INIT_EVENT,
        [dict(target_id=t['id'],version=0) for t in targets.values()]),kind='initial_setup')]
    source_events=[]
    for command in manifest['commands']:
        kind=command['kind'];event=command['event'];source_events.append(dict(command))
        if kind in ('target_bind','present','visibility_cpu_result'):continue
        if kind.startswith('visibility_'):
            if not native_queries:continue
            q=plans[event];packet=wire.Packet(sum(bool(s['packet']) for s in steps)+1);checkpoints=[]
            if kind in ('visibility_begin','visibility_end'):
                packet.command(struct.pack('<4I',14 if kind=='visibility_begin' else 15,16,q['resource'],1))
            else:
                # Read at the original GPU-result event. Empty packet preserves
                # submission ordering without injecting a draw or target seed.
                checkpoints=[dict(event=event,resource=q['resource'],target_id=q['resource'],version=1,
                    plane=8,width=1,height=1,bytes=8,expected_value=q['expected_value'],source_event=q['end_event'])]
            steps.append(dict(event=event,kind=kind,packet=packet.finish() if kind!='visibility_gpu_result' else b'',checkpoints=checkpoints));continue
        require(kind in ('clear','draw'),'Unsupported recorded frame operation')
        for ref in command['before'].values():
            if ref is not None:require(versions[ref['target_id']]==ref['version'],'Original attachment history mismatch')
        packet=wire.Packet(sum(bool(s['packet']) for s in steps)+1)
        if kind=='clear':
            require(command['color_write_mask'] in (0,15),'Partial color-channel clear has no native wire operation')
            color=command['before'].get('color');depth=command['before'].get('depth_stencil')
            planes=(1 if command['color_write_mask'] else 0)|(2 if command['clear_depth'] else 0)|(4 if command['clear_stencil'] else 0)
            require(planes,'Empty original clear')
            for rectangle in command['rectangles']:
                fixed=struct.pack('<12I5fI',4,72,color['target_id'] if planes&1 else 0,1 if planes&1 else 0,
                    depth['target_id'] if planes&6 else 0,1 if planes&6 else 0,planes,
                    rectangle['x'],rectangle['y'],rectangle['width'],rectangle['height'],command['stencil'],
                    *command['color'],command['depth'],0)
                packet.command(fixed)
        else:
            d=manifest['draws'][command['draw']];refs=[];samplers=[]
            require(d['targets']==command['before'],'Original draw target binding differs from event history')
            for t in d['textures']:
                if t is None or t['type']=='unbound_passthrough':refs.append((0,0));samplers.append(None);continue
                if t['type']=='static_texture':resource=texture_ids[t['resource']]
                elif t['type']=='target_alias':
                    resource=targets[t['resource']]['id']
                    require(versions[resource]==t['expected_generation'],'Original sampled target alias is stale')
                else:raise ValueError('Unsupported original texture resource binding')
                refs.append((resource,1));samplers.append(t['sampler'])
            vertices,indices,packed,primitive,_=wire.geometry(root,d)
            vu=payload(root,d['uniforms']['vertex']);pu=payload(root,d['uniforms']['pixel'])
            require(len(vu)==3120 and len(pu)==608,'Unknown original uniform ABI')
            color=d['targets'].get('color');depth=d['targets'].get('depth_stencil')
            fixed=struct.pack('<16I',9,416,program_for_draw[command['draw']],1,
                color['target_id'] if color else 0,1 if color else 0,depth['target_id'] if depth else 0,1 if depth else 0,
                *[word for pair in refs for word in pair])
            fixed+=b''.join(wire.sampler_bytes(s) for s in samplers)+wire.state_bytes(d['render_state'])
            fixed+=struct.pack('<10I',len(vertices)//256,len(indices)//4,packed,primitive,0,0,0,0,0,0)
            packet.command(fixed,[(392,vertices),(396,indices),(400,vu),(404,pu)])
        refs=list(command['after'].values())
        for ref in refs:
            if ref is not None:versions[ref['target_id']]=ref['version']
        steps.append(dict(event=event,kind=kind,use=command.get('use'),packet=packet.finish(),
            readonly_visibility_query=command.get('readonly_visibility_query',False),checkpoints=checkpoint_records(manifest,event,refs)))
    require(len([s for s in steps if s['kind']=='draw'])==len(manifest['draws']),'Original frame draw was omitted')
    present=[c for c in manifest['commands'] if c['kind']=='present'];require(len(present)==1,'Original frame has no unique present')
    require(versions[present[0]['back_buffer']['target_id']]==present[0]['back_buffer']['version'],'Original final target history differs')
    return steps,dict(source_events=source_events,query_events=queries,programs=len(program_ids),static_textures=len(texture_ids),final_versions=versions,
        **(dict(native_query_plan=plans) if native_queries else {}))

def build_fixture(manifest_path,out,diagnostic,native_queries=False):
    frame.verify_replay(manifest_path)
    manifest=json.loads(manifest_path.read_text());root=manifest_path.parent
    steps,details=make_steps(root,manifest,diagnostic,native_queries)
    assembly=['.section .rodata,"a",@progbits'];readbacks=[];step_rows=[]
    for index,step in enumerate(steps):
        file=out/f'packet-{index:04}.bin';file.write_bytes(step.pop('packet'))
        symbol=f'halo_frame_packet_{index}'
        assembly+=['.balign 16',f'{symbol}:',f'.incbin {json.dumps(str(file))}']
        first=len(readbacks);readbacks+=step['checkpoints']
        step_rows.append(f'.long {symbol},{file.stat().st_size},{step["event"]},{first},{len(step["checkpoints"])}')
        step['packet']=dict(file=file.name,size=file.stat().st_size,sha256=sha(file))
    assembly+=['.balign 16','.global halo_frame_steps','halo_frame_steps:',*step_rows,
        '.balign 16','.global halo_frame_readbacks','halo_frame_readbacks:']
    for r in readbacks:assembly+=['.long '+','.join(str(r[k]) for k in ('resource','plane','bytes','target_id','version','width','height'))]
    (out/'fixture.s').write_text('\n'.join(assembly)+'\n')
    scratch=max(r['bytes'] for r in readbacks)
    macros=dict(STEPS=len(steps),READBACKS=len(readbacks),SCRATCH=scratch,SOURCE_FRAME=manifest['source_capture']['frame'],ATTACHMENTS_ONLY=int(diagnostic),NATIVE_QUERIES=int(native_queries))
    (out/'metal_host_frame_fixture.h').write_text('\n'.join(f'#define HALO_FRAME_{k} {v}u' for k,v in macros.items())+'\n')
    imports=(ROOT/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n'
    (out/'diagnostic-imports.list').write_text(imports)
    proof=dict(schema_version=1,kind='ordered_frame_ilp32_fixture',complete=True,manifest=str(manifest_path),manifest_sha256=sha(manifest_path),
        source_capture=manifest['source_capture'],attachments_only_diagnostic=diagnostic,native_query_diagnostic=native_queries,full_frame_gate=False,
        steps=steps,readbacks=readbacks,details=details,independent_expected_payloads={str((root/r['expected']['file']).resolve()):r['expected']['sha256'] for r in readbacks if 'expected' in r},
        packet_payload_sha256={str(out/s['packet']['file']):s['packet']['sha256'] for s in steps},
        limits=[('Original Boolean GPU queries execute natively; cached CPU results and their original availability/timing remain unverified.' if native_queries else 'Native visibility queries are omitted; recorded query geometry runs only in explicitly scoped attachment diagnostic.'),
            'Expected after-target data stays exclusively in CPU comparison; only original initial version0 seeds enter GPU uploads.',
            'Synchronous guest submissions/readbacks do not establish live scheduling or original query timing.',
            'ANGLEFloat32 backing storage; physical Xbox D24/F24 precision remains unverified.'])
    (out/'fixture.json').write_text(json.dumps(proof,indent=2)+'\n');return proof

def run(*args):subprocess.run([str(a) for a in args],cwd=ROOT,check=True)

def build_guest(out,llvm,linker,plugin):
    sys.path.insert(0,str(ROOT));from tools.android_build import GUEST_ABI_FLAGS
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    guest=ROOT/'port/macos/tests/guest_metal_frame.c'
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-DHALO_MACOS=1','-I',out,'-emit-llvm','-S',guest,'-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    for source in ('guest','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(source+'.s'),'-o',out/(source+'.o'))
    run(sys.executable,'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    script=out/'guest.ld';script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',script,out/'guest.o',out/'fixture.o',out/'imports.o','-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        f=line.split()
        if len(f)==3:symbols[f[2]]=int(f[0],16)
    sections=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=((sum(int(line.split()[1]) for line in sections.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)//16384)*16384
    require(span<=512*1024*1024,'Diagnostic guest exceeds bounded rebased arena')
    return symbols,span

def build_host(out):
    snapshot=out/'source-snapshot'
    flags=['-arch','arm64','-mmacosx-version-min=14.0','-O2','-g','-DHALO_MACOS=1','-I'+str(snapshot/'port/macos/host'),'-I'+str(snapshot/'port/android/include')]
    sources=[snapshot/'port/macos/host/host_memory.c',out/'host_import_table.c',snapshot/'port/macos/host/host_metal.mm',
        snapshot/'port/macos/host/metal_draw_encoder.mm',snapshot/'port/macos/tests/host_metal_frame.mm']
    objects=[]
    for i,source in enumerate(sources):
        obj=out/f'{i}-{source.name}.o';cpp=source.suffix=='.mm'
        run('clang++' if cpp else 'clang',*flags,*(['-std=c++17','-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror'] if cpp else []),'-c',source,'-o',obj);objects.append(obj)
    executable=out/'host_metal_frame_probe';run('clang++',*flags,*objects,'-framework','Foundation','-framework','Metal','-framework','QuartzCore','-o',executable)
    return executable,sources

def snapshot_backend(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
        'port/macos/host/metal_draw_encoder.mm','port/macos/host/metal_draw_encoder.h','port/macos/host/metal_function_cache.h','port/macos/host/metal_warmup_cache.h','port/macos/host/metal_packet_view.h','port/macos/include/halo_metal_abi.h',
        'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm']
    records={}
    for name in names:
        source=ROOT/name;destination=out/'source-snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        before=sha(source);shutil.copyfile(source,destination)
        require(sha(source)==before==sha(destination),'Backend changed during source snapshot')
        records[str(source)]={'snapshot':str(destination),'sha256':before}
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def validate_execution(out,stdout,prepared):
    execution=out/'execution.json';require(execution.is_file(),'Missing tool-observed host execution record')
    record=json.loads(execution.read_text())
    require(record.get('schema_version')==1 and record.get('kind')=='ordered_frame_host_execution' and
        record.get('complete') is True and type(record.get('returncode')) is int,'Invalid host execution record')
    require(record.get('command')==prepared['execution_command'],'Host execution command differs from preparation')
    require(record.get('prepared_sha256')==sha(out/'prepared.json'),'Host execution belongs to another preparation')
    require(record.get('executor_sha256')==sha(Path(__file__)),'Host execution uses another executor source')
    require(stdout.resolve()==(out/'native.stdout').resolve() and record.get('stdout_sha256')==sha(stdout) and
        record.get('stderr_sha256')==sha(out/'native.stderr'),'Host execution output changed')
    return record

def validate_prepared_inputs(out,prepared,fixture):
    for path,digest in prepared['source_and_binary_sha256'].items():require(sha(path)==digest,f'Stale source/binary: {path}')
    require(sha(out/'fixture.json')==prepared['fixture_sha256'],'Fixture changed')
    require(sha(fixture['manifest'])==fixture['manifest_sha256'],'Frame manifest changed')
    for collection in ('packet_payload_sha256','independent_expected_payloads'):
        for path,digest in fixture[collection].items():require(sha(path)==digest,f'Frame payload changed: {path}')
    frame.verify_replay(Path(fixture['manifest']))

def execute_prepared(out):
    require(not (out/'execution.json').exists() and not (out/'native.stdout').exists() and
        not (out/'native.stderr').exists(),'Execution output already exists; preserve earlier runs')
    prepared=json.loads((out/'prepared.json').read_text());fixture=json.loads((out/'fixture.json').read_text())
    validate_prepared_inputs(out,prepared,fixture)
    result=subprocess.run(prepared['execution_command'],cwd=ROOT,capture_output=True,text=True)
    stdout=out/'native.stdout';stderr=out/'native.stderr';stdout.write_text(result.stdout);stderr.write_text(result.stderr)
    validate_prepared_inputs(out,prepared,fixture)
    record=dict(schema_version=1,kind='ordered_frame_host_execution',complete=True,returncode=result.returncode,
        command=prepared['execution_command'],prepared_sha256=sha(out/'prepared.json'),
        stdout_sha256=sha(stdout),stderr_sha256=sha(stderr),executor_sha256=sha(Path(__file__)))
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n')
    print(result.stderr,end='',file=sys.stderr);consume(out,stdout)

def consume(out,stdout):
    prepared=json.loads((out/'prepared.json').read_text());fixture=json.loads((out/'fixture.json').read_text())
    def unchanged():
        validate_prepared_inputs(out,prepared,fixture)
    unchanged();execution=validate_execution(out,stdout,prepared);returncode=execution['returncode'];execution_sha=sha(out/'execution.json')
    native=out/'native';record=json.loads(stdout.read_text());dump=json.loads((native/'checkpoints.json').read_text())
    require(record.get('kind')=='native_metal_ilp32_ordered_frame' and record.get('guest_pointer_bits')==32,'Run did not use actual ILP32 imports')
    report=dump['report'];require(len(report)==16 and report[0]==1 and report[6]==len(fixture['steps']) and
        report[7]==len(fixture['readbacks']) and report[8]==fixture['source_capture']['frame'] and
        report[9]==int(fixture['attachments_only_diagnostic']),'Guest report belongs to another frame fixture')
    expected={(r['event'],r['target_id'],r['version'],r['plane']):r for r in fixture['readbacks']}
    comparisons=[];first=None;actual_hashes={}
    for r in dump['checkpoints']:
        key=(r['event'],r['target_id'],r['version'],r['plane']);require(key in expected,'Unexpected native checkpoint')
        e=expected.pop(key);require(all(r[k]==e[k] for k in ('event','target_id','version','plane','width','height','bytes')),'Native checkpoint shape differs')
        name=f"event-{r['event']}-target-{r['target_id']}-version-{r['version']}-plane-{r['plane']}.bin"
        require(r['file']==name,'Native checkpoint path differs from fixed event identity')
        actual=(native/name).read_bytes();reference=(struct.pack('<Q',e['expected_value']) if e['plane']==8 else payload(Path(fixture['manifest']).parent,e['expected']))
        require(len(actual)==len(reference)==e['bytes'],'Native checkpoint byte count differs')
        different=sum(a!=b for a,b in zip(actual,reference));first_byte=next((i for i,(a,b) in enumerate(zip(actual,reference)) if a!=b),None)
        entry=dict(event=r['event'],target_id=r['target_id'],version=r['version'],plane=r['plane'],different_bytes=different,
            first_different_byte=first_byte,actual_sha256=hashlib.sha256(actual).hexdigest(),expected_sha256=hashlib.sha256(reference).hexdigest())
        if e['plane']==8:entry.update(actual_value=struct.unpack('<Q',actual)[0],expected_value=e['expected_value'],source_event=e['source_event'])
        if different and first is None:first=entry
        comparisons.append(entry);actual_hashes[str(native/name)]=entry['actual_sha256']
    transport=returncode==0 and record.get('guest_result')==0 and report[1]==4 and report[13]==len(fixture['readbacks']) and report[14]==len(fixture['steps'])
    byte_exact=transport and not expected and first is None
    queries=[c for c in comparisons if c['plane']==8];attachments=[c for c in comparisons if c['plane']!=8]
    proof=dict(prepared,kind='ordered_frame_ilp32_attachment_diagnostic',complete=transport,build_only=False,
        full_frame_gate=False,attachment_gate=transport and not expected and all(c['different_bytes']==0 for c in attachments),
        native_query_gate=transport and bool(queries) and report[15]==len(queries) and all(c['different_bytes']==0 for c in queries),
        original_cpu_query_timing_gate=False,presentation_gate=False,guest_run=record,guest_report=report,returncode=returncode,
        compared_checkpoints=len(comparisons),missing_checkpoints=len(expected),first_difference=first,
        comparisons=comparisons,native_payload_sha256=actual_hashes,stdout_sha256=sha(stdout),checkpoint_metadata_sha256=sha(native/'checkpoints.json'),
        execution_record=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),limits=fixture['limits'])
    unchanged();require(sha(out/'execution.json')==execution_sha,'Host execution record changed during comparison')
    (out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({k:proof[k] for k in ('complete','full_frame_gate','attachment_gate','compared_checkpoints','missing_checkpoints','first_difference')},indent=2))
    print(out/'result.json')
    if not byte_exact:raise SystemExit('Ordered attachment diagnostic differs; complete provenance retained')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path)
    p.add_argument('--output',type=Path,required=True)
    diagnostic=p.add_mutually_exclusive_group();diagnostic.add_argument('--attachments-only-diagnostic',action='store_true');diagnostic.add_argument('--native-query-diagnostic',action='store_true')
    p.add_argument('--rebase-plugin',type=Path);p.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    modes=p.add_mutually_exclusive_group();modes.add_argument('--build-only',action='store_true');modes.add_argument('--consume-run',type=Path)
    modes.add_argument('--execute-prepared',action='store_true',help='Run a frozen prepared fixture and bind its actual host exit status')
    a=p.parse_args();out=a.output.resolve()
    if a.execute_prepared:execute_prepared(out);return
    if a.consume_run:consume(out,a.consume_run.resolve());return
    require(a.manifest and a.rebase_plugin,'Manifest and rebase plugin required');require(not out.exists(),'Output must be fresh to preserve failure evidence')
    manifest=a.manifest.resolve();m=json.loads(manifest.read_text());query_gate(m,a.attachments_only_diagnostic,a.native_query_diagnostic)
    out.mkdir(parents=True)
    try:
        backend_snapshot=snapshot_backend(out)
        fixture=build_fixture(manifest,out,a.attachments_only_diagnostic,a.native_query_diagnostic)
        symbols,span=build_guest(out,a.llvm_bin.resolve(),a.linker.absolute(),a.rebase_plugin.resolve());executable,sources=build_host(out)
    except Exception as error:
        (out/'failure.json').write_text(json.dumps(dict(schema_version=1,kind='ordered_frame_preparation_failure',complete=False,
            full_frame_gate=False,gpu_submitted=False,reason=str(error),manifest=str(manifest),manifest_sha256=sha(manifest),
            tool_sha256=sha(Path(__file__))),indent=2)+'\n')
        raise
    native=out/'native';native.mkdir()
    command=[str(executable),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],
        str(span),hex(symbols['halo_frame_report']),str(native)]
    inputs=[Path(__file__).resolve(),Path(wire.__file__),Path(frame.__file__),ROOT/'port/macos/tests/guest_metal_frame.c',*sources,
        *[Path(record['snapshot']) for record in backend_snapshot.values()],ROOT/'tools/android_imports.py',ROOT/'tools/android_asm_convert.py',
        a.rebase_plugin.resolve(),a.llvm_bin.resolve()/'clang',a.llvm_bin.resolve()/'opt',a.llvm_bin.resolve()/'llc',a.linker.absolute(),
        out/'guest.elf',executable,out/'fixture.s',out/'diagnostic-imports.list',out/'metal_host_frame_fixture.h']
    proof=dict(schema_version=1,kind='ordered_frame_ilp32_prepared',complete=False,build_only=True,full_frame_gate=False,
        fixture_sha256=sha(out/'fixture.json'),source_and_binary_sha256={str(path):sha(path) for path in inputs},execution_command=command,
        fixture_source_capture=fixture['source_capture'],attachments_only_diagnostic=a.attachments_only_diagnostic,
        native_query_diagnostic=a.native_query_diagnostic,
        backend_source_snapshot=backend_snapshot)
    (out/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(dict(steps=len(fixture['steps']),draws=len(m['draws']),
        readbacks=len(fixture['readbacks']),packet_bytes=sum(s['packet']['size'] for s in fixture['steps']),guest_span=span,execution_command=command),indent=2))
    if not a.build_only:
        execute_prepared(out)

if __name__=='__main__':main()
