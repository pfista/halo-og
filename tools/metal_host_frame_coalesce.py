#!/usr/bin/env python3
"""Test one ordered original frame in one native submission, final outputs only.

Rebuild command-relative payload extents through the existing wire Packet API.
Removing old packet headers can change alignment, so raw concatenation is never
used. Initial version0 seeds and original static resources are retained; final
expected targets stay in CPU comparison and never enter the guest packet.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_host_draw_validate as wire
import metal_host_frame_validate as ordered

require,sha=wire.require,wire.sha
FIXED={1:32,2:16,3:48,4:72,5:48,6:16,7:40,8:16,9:416,10:48,11:72,
       12:24,13:16,14:16,15:16,16:24,17:80,18:16,19:424}

def commands(packet):
    require(len(packet)>=24,'Truncated packet header')
    magic,version,size,count,sequence=struct.unpack_from('<4IQ',packet)
    require((magic,version,size)==(0x4c544d48,1,len(packet)) and 0<count<=65536 and 0<sequence,
            'Invalid original packet header')
    cursor=24;result=[]
    for _ in range(count):
        require(cursor+8<=size,'Truncated command header')
        opcode,extent=struct.unpack_from('<2I',packet,cursor)
        fixed_size=FIXED.get(opcode)
        require(fixed_size and extent>=fixed_size and extent%8==0 and cursor+extent<=size,
                'Unknown or truncated original command')
        fixed=bytearray(packet[cursor:cursor+fixed_size]);fields=[]
        if opcode==3:fields=[(36,struct.unpack_from('<I',fixed,40)[0])]
        elif opcode==11:fields=[(56,struct.unpack_from('<I',fixed,60)[0])]
        elif opcode==7:fields=[(20,struct.unpack_from('<I',fixed,24)[0]),(28,struct.unpack_from('<I',fixed,32)[0])]
        elif opcode in (9,19):
            vertices,indices=struct.unpack_from('<2I',fixed,376)
            require(0<vertices<=1024*1024 and 0<indices<=16*1024*1024,'Invalid original draw payload counts')
            fields=[(392,vertices*256),(396,indices*4),(400,3120),(404,608)]
        payloads=[];end=cursor+fixed_size
        for field,length in fields:
            offset=struct.unpack_from('<I',fixed,field)[0]
            require(length and offset%16==0 and end<=offset<=cursor+extent and length<=cursor+extent-offset,
                    'Original payload outside command or out of order')
            require(not any(packet[end:offset]),'Nonzero hidden payload padding')
            payloads.append((field,packet[offset:offset+length]));end=offset+length
            struct.pack_into('<I',fixed,field,0)
        require(not any(packet[end:cursor+extent]),'Nonzero hidden command padding')
        struct.pack_into('<I',fixed,4,0)
        identity=hashlib.sha256(struct.pack('<I',len(fixed))+fixed+b''.join(
            struct.pack('<II',field,len(data))+data for field,data in payloads)).hexdigest()
        result.append(dict(opcode=opcode,fixed=bytes(fixed),payloads=payloads,identity=identity,old_offset=cursor))
        cursor+=extent
    require(cursor==size,'Trailing original packet bytes')
    return sequence,result

def coalesce(packets):
    merged=wire.Packet(1);identities=[];mapping=[];previous=0
    for number,packet in enumerate(packets):
        sequence,records=commands(packet)
        require(sequence==previous+1,'Original packet sequence is not contiguous')
        previous=sequence
        for record in records:
            require(number==0 or record['opcode'] not in (3,11),'Only initial resource uploads are allowed')
            start=len(merged.data);merged.command(record['fixed'],record['payloads'])
            identities.append(record['identity'])
            mapping.append(dict(original_packet=number,original_offset=record['old_offset'],
                                coalesced_offset=start,opcode=record['opcode'],semantic_sha256=record['identity']))
    result=merged.finish();_,rebuilt=commands(result)
    require([r['identity'] for r in rebuilt]==identities,'Coalescing changed command metadata, payload bytes or order')
    require(len(rebuilt)<=65536,'Coalesced command count exceeds host bound')
    return result,mapping

def verify_reference(baseline):
    fixture=json.loads((baseline/'fixture.json').read_text());prepared=json.loads((baseline/'prepared.json').read_text())
    proof=json.loads((baseline/'comparison.json').read_text())
    require(proof['attachment_gate'] and proof['native_query_gate'] and proof['native_host_exit_gate'] and
            proof['packet_rederivation_passed'] and proof['compared_checkpoints']==378 and
            proof['missing_checkpoints']==0 and proof['first_difference'] is None,'Canonical ordered-frame proof is not exact')
    ordered.validate_prepared_inputs(baseline,prepared,fixture)
    ordered.validate_execution(baseline,baseline/'native.stdout',prepared)
    manifest=json.loads(Path(fixture['manifest']).read_text())
    steps,details=ordered.make_steps(Path(fixture['manifest']).parent,manifest,False,True)
    require(len(steps)==len(fixture['steps']) and json.loads(json.dumps(details))==fixture['details'],'Original event derivation changed')
    packets=[]
    for step,saved in zip(steps,fixture['steps']):
        data=(baseline/saved['packet']['file']).read_bytes()
        require(hashlib.sha256(data).hexdigest()==saved['packet']['sha256'] and data==step['packet'],'Original prepared packet changed')
        if data:packets.append(data)
    native=json.loads((baseline/'native/checkpoints.json').read_text())
    actual={(r['event'],r['target_id'],r['version'],r['plane']):r for r in native['checkpoints']}
    comparisons={(r['event'],r['target_id'],r['version'],r['plane']):r for r in proof['comparisons']}
    latest={}
    for r in fixture['readbacks']:latest[(r['resource'],r['plane'])]=dict(r)
    for r in latest.values():
        key=(r['event'],r['target_id'],r['version'],r['plane']);checkpoint=actual[key];comparison=comparisons[key]
        file=baseline/'native'/checkpoint['file']
        require(sha(file)==comparison['actual_sha256']==comparison['expected_sha256'],'Final canonical checkpoint changed')
        r['expected_wire_version']=checkpoint['wire_content_version']
        r['canonical_file']=str(file);r['canonical_sha256']=sha(file)
    require(len(latest)==6 and {r['plane'] for r in latest.values()}=={1,2,4,8},'Unexpected original final target/query set')
    return fixture,packets,list(latest.values())

def snapshot(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
           'port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm','port/macos/host/metal_function_cache.h','port/macos/host/metal_warmup_cache.h','port/macos/host/metal_packet_view.h','port/macos/include/halo_metal_abi.h',
           'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm',
           'port/macos/tests/guest_metal_frame_coalesced.c','port/macos/metal_imports.list',
           'tools/metal_host_frame_coalesce.py','tools/metal_host_frame_validate.py','tools/metal_host_draw_validate.py',
           'tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py']
    records={}
    for name in names:
        source=ROOT/name;target=out/'source-snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        digest=sha(source);shutil.copyfile(source,target)
        require(sha(source)==sha(target)==digest,'Coalescing source changed during snapshot')
        records[str(source)]=dict(snapshot=str(target),sha256=digest)
    for source,r in records.items():require(sha(source)==r['sha256'],'Coalescing source window changed')
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def build_guest(out,llvm,linker,plugin):
    source_root=out/'source-snapshot';tree=ast.parse((source_root/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    require(len(nodes)==1,'Missing guest ABI flags');flags=ast.literal_eval(nodes[0].value)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    run=ordered.run
    run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
        '-DHALO_MACOS=1','-I',out,'-emit-llvm','-S',source_root/'port/macos/tests/guest_metal_frame_coalesced.c','-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,source_root/'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    for name in ('guest','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    imports=(source_root/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n'
    (out/'diagnostic-imports.list').write_text(imports)
    run(sys.executable,source_root/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',out/'guest.ld',out/'guest.o',out/'fixture.o',out/'imports.o','-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        f=line.split()
        if len(f)==3:symbols[f[2]]=int(f[0],16)
    sections=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sections.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    require(span<=512*1024*1024,'Coalesced fixture exceeds guest arena')
    return symbols,span

def prepare(baseline,out,llvm,linker,plugin):
    require(not out.exists(),'Output must be fresh; preserve earlier proof')
    fixture,packets,readbacks=verify_reference(baseline)
    merged,mapping=coalesce(packets);draws=sum(r['opcode'] in (9,19) for r in mapping)
    require(draws==126,'Original draw omitted or added')
    out.mkdir(parents=True);records=snapshot(out)
    packet=out/'packet.bin';packet.write_bytes(merged)
    assembly=['.section .rodata,"a",@progbits','.balign 16','.global halo_coalesced_packet','halo_coalesced_packet:',
              f'.incbin {json.dumps(str(packet))}','.balign 16','.global halo_coalesced_readbacks','halo_coalesced_readbacks:']
    for r in readbacks:assembly+=['.long '+','.join(str(r[k]) for k in ('event','resource','plane','bytes','target_id','version','width','height','expected_wire_version'))]
    (out/'fixture.s').write_text('\n'.join(assembly)+'\n')
    macros=dict(PACKET_BYTES=len(merged),READBACKS=len(readbacks),SCRATCH=max(r['bytes'] for r in readbacks),
                DRAWS=draws,SOURCE_FRAME=fixture['source_capture']['frame'],ORIGINAL_PACKETS=len(packets),COMMANDS=len(mapping))
    (out/'metal_host_frame_coalesced_fixture.h').write_text('\n'.join(f'#define HALO_COALESCED_{k} {v}u' for k,v in macros.items())+'\n')
    package=dict(schema_version=1,kind='original_frame_coalesced_fixture',complete=True,baseline=str(baseline),
        baseline_comparison_sha256=sha(baseline/'comparison.json'),baseline_fixture_sha256=sha(baseline/'fixture.json'),
        source_capture=fixture['source_capture'],manifest=fixture['manifest'],manifest_sha256=fixture['manifest_sha256'],
        original_packets=len(packets),original_packet_bytes=sum(map(len,packets)),coalesced_commands=len(mapping),draws=draws,
        packet=dict(file=str(packet),sha256=sha(packet),size=len(merged)),command_mapping=mapping,final_readbacks=readbacks,
        expected_after_targets_gpu_uploaded=False,readbacks_deferred_until_end=True,intermediate_checkpoints_verified=False,
        full_frame_gate=False,original_cpu_query_timing_gate=False,presentation_gate=False)
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n')
    symbols,span=build_guest(out,llvm,linker,plugin);executable,sources=ordered.build_host(out)
    for path,r in records.items():require(sha(path)==r['sha256'],'Source changed during coalesced preparation')
    native=out/'native';native.mkdir()
    command=[str(executable),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],
             str(span),hex(symbols['halo_frame_report']),str(native)]
    dependencies=[*[Path(r['snapshot']) for r in records.values()],*sources,plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,
        executable,out/'guest.elf',out/'fixture.s',out/'diagnostic-imports.list',out/'metal_host_frame_coalesced_fixture.h',
        out/'source-snapshot.json',out/'guest.ld',out/'imports.s',out/'host_import_table.c',Path(__file__)]
    prepared=dict(schema_version=1,kind='coalesced_frame_ilp32_prepared',complete=False,passed=False,
        fixture_sha256=sha(out/'fixture.json'),source_and_binary_sha256={str(p):sha(p) for p in dependencies},source_snapshot=records,
        execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(draws=draws,original_submissions=len(packets),coalesced_submissions=1,
                         packet_bytes=len(merged),final_readbacks=len(readbacks),prepared=str(out/'prepared.json')),indent=2))

def unchanged(out):
    prepared=json.loads((out/'prepared.json').read_text());fixture=json.loads((out/'fixture.json').read_text())
    for p,digest in prepared['source_and_binary_sha256'].items():require(sha(p)==digest,'Frozen coalesced source or binary changed')
    require(sha(out/'fixture.json')==prepared['fixture_sha256'] and sha(fixture['packet']['file'])==fixture['packet']['sha256'],
            'Coalesced fixture changed')
    _,packets,readbacks=verify_reference(Path(fixture['baseline']));merged,mapping=coalesce(packets)
    require(merged==Path(fixture['packet']['file']).read_bytes() and mapping==fixture['command_mapping'] and
            readbacks==fixture['final_readbacks'],'Coalesced data no longer derives from original input')
    return prepared,fixture

def execute(out):
    require(not any((out/p).exists() for p in ('execution.json','native.stdout','native.stderr')),'Execution already exists; preserve it')
    prepared,fixture=unchanged(out);env=dict(os.environ);env.update(prepared['validation_environment'])
    run=subprocess.run(prepared['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(run.stdout);(out/'native.stderr').write_text(run.stderr)
    execution=dict(schema_version=1,kind='coalesced_original_frame_host_execution',complete=True,returncode=run.returncode,
        command=prepared['execution_command'],validation_environment=prepared['validation_environment'],
        prepared_sha256=sha(out/'prepared.json'),executor_sha256=sha(__file__),
        stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution,indent=2)+'\n');unchanged(out)
    record=json.loads(run.stdout);dump=json.loads((out/'native/checkpoints.json').read_text());report=dump['report']
    expected={(r['event'],r['target_id'],r['version'],r['plane']):r for r in fixture['final_readbacks']};comparisons=[]
    for r in dump['checkpoints']:
        key=(r['event'],r['target_id'],r['version'],r['plane']);require(key in expected,'Unexpected coalesced final readback');e=expected.pop(key)
        require(all(r[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and
                r['wire_content_version']==e['expected_wire_version'] and r['completed_sequence']==1,'Final version/history mismatch')
        name=f"event-{r['event']}-target-{r['target_id']}-version-{r['version']}-plane-{r['plane']}.bin";require(r['file']==name,'Unexpected final file path')
        data=(out/'native'/name).read_bytes();reference=Path(e['canonical_file']).read_bytes()
        require(len(data)==len(reference)==e['bytes'] and sha(e['canonical_file'])==e['canonical_sha256'],'Final reference changed')
        comparisons.append(dict(event=r['event'],target_id=r['target_id'],version=r['version'],plane=r['plane'],
            different_bytes=sum(a!=b for a,b in zip(data,reference)),actual_sha256=hashlib.sha256(data).hexdigest(),
            expected_sha256=e['canonical_sha256'],file=str(out/'native'/name)))
    validation='Metal API Validation Enabled' in run.stderr
    passed=(run.returncode==0 and record.get('guest_result')==0 and report[0:2]==[1,4] and report[4:6]==[1,0] and
        report[6:10]==[126,len(fixture['final_readbacks']),420,fixture['original_packets']] and report[11:13]==[1,len(fixture['final_readbacks'])] and
        report[15]==1 and not expected and all(r['different_bytes']==0 for r in comparisons) and validation)
    proof=dict(prepared,complete=True,passed=passed,returncode=run.returncode,guest_run=record,guest_report=report,
        execution=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),gpu_api_validation_enabled=validation,
        original_submissions=fixture['original_packets'],coalesced_submissions=1,draws=fixture['draws'],final_readbacks=len(comparisons),
        comparisons=comparisons,full_frame_gate=False,intermediate_checkpoints_gate=False,original_cpu_query_timing_gate=False,
        presentation_gate=False,performance_improvement_gate=False,
        limits=['Final output equality only; intermediate checkpoints and original CPU query availability/timing are not tested.',
                'One captured frame, with existing synchronous host backend; no live scheduling or performance improvement claim.',
                'Expected after-target data is exclusively a CPU comparison and never uploaded.'])
    unchanged(out);(out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,returncode=run.returncode,gpu_api_validation_enabled=validation,
                         original_submissions=fixture['original_packets'],coalesced_submissions=1,
                         final_readbacks=len(comparisons),different_bytes=[r['different_bytes'] for r in comparisons],result=str(out/'result.json')),indent=2))
    require(passed,'Coalesced original frame differs; complete diagnostic retained')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,default=ROOT/'build/metal-poc/host-frame-alpha-border-current')
    parser.add_argument('--rebase-plugin',type=Path)
    parser.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    parser.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--build-only',action='store_true');mode.add_argument('--execute-prepared',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if args.execute_prepared:execute(out);return
    require(args.rebase_plugin,'Original ILP32 rebase plugin required')
    prepare(args.baseline.resolve(),out,args.llvm_bin.resolve(),args.linker.absolute(),args.rebase_plugin.resolve())
    if not args.build_only:execute(out)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print(error,file=sys.stderr);sys.exit(1)
