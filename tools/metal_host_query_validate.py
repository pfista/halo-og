#!/usr/bin/env python3
"""Exercise native visibility wire commands through actual rebased ILP32 imports.

The captured opaque program, packed input registers, constants, textures and
original raster tests stay intact. Query copies disable attachment writes.
Independent ANGLE after-targets are guest CPU comparisons, never GPU uploads.
This tests raw GPU query results, not original cached CPU polling or timing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_host_draw_validate as wire
import metal_draw_compare as comparison
from metal_draw_replay import prepare

require=wire.require
sha=wire.sha
CASES=['visibility_capability','original_opaque_attachments','empty_boolean','empty_counting',
    'active_result_undefined','nested_begin_rejects','wrong_end_rejects','active_delete_rejects',
    'wrong_generation_rejects','visible_boolean','boolean_or_across_packets','positive_counting',
    'counting_sum_across_packets','counting_sum_within_packet','explicit_begin_resets',
    'invalid_later_draw_atomic_rejection','rejected_packet_adds_no_samples','end_without_begin_rejects',
    'invalid_mode_rejects','reserved_creation_rejects','deleted_ref_rejects','same_generation_reuse_rejects',
    'new_generation_empty_query','old_generation_rejects','query_resource_lifetime_restored',
    'attachments_and_versions_preserved']
REPORT_FIELDS=['abi_version','phase','status','failed_command','case_bits','attachment_invariant_checks',
    'single_count_lo','single_count_hi','double_count_lo','double_count_hi','visible_boolean',
    'multi_boolean','empty_count','width','height','original_packet_bytes']

def draw_inputs(packet):
    require(len(packet)>=24,'Truncated original packet')
    magic,version,size,count,_=struct.unpack_from('<4IQ',packet)
    require((magic,version,size)==(0x4c544d48,1,len(packet)),'Invalid original packet')
    offset=24;commands=[]
    for _ in range(count):
        require(offset+8<=size,'Truncated original command')
        op,length=struct.unpack_from('<2I',packet,offset)
        require(length>=8 and length%8==0 and offset+length<=size,'Invalid original command extent')
        commands.append((op,offset,length));offset+=length
    require(offset==size and commands and commands[-1][0]==9,'Original packet must end in captured DRAW')
    _,offset,length=commands[-1];require(length>=416,'Truncated original DRAW')
    fixed=packet[offset:offset+416];vertex_count,index_count=struct.unpack_from('<2I',fixed,376)
    payloads=[]
    for field,extent in ((392,vertex_count*256),(396,index_count*4),(400,3120),(404,608)):
        position=struct.unpack_from('<I',fixed,field)[0]
        require(extent and position%16==0 and offset+416<=position and position+extent<=offset+length,
            'Original DRAW payload exceeds command')
        payloads.append((field,packet[position:position+extent]))
    return fixed,payloads

def query_packets(original):
    fixed,payloads=draw_inputs(original)
    readonly=bytearray(fixed)
    # Fixed DRAW state starts at224: color mask, depth write, stencil mask,
    # and three stencil operations. Geometry/program/resources stay original.
    mutations={224:0,248:0,268:0,272:1,276:1,280:1}
    for offset,value in mutations.items():struct.pack_into('<I',readonly,offset,value)
    occluded=bytearray(readonly);struct.pack_into('<I',occluded,252,1) # Diagnostic depth Never, unchanged geometry.
    invalid=bytearray(readonly);struct.pack_into('<I',invalid,252,9) # Invalid comparison in later DRAW.
    def packet(draws):
        result=wire.Packet(2)
        for draw in draws:result.command(draw,payloads)
        return result.finish()
    return dict(single=packet([readonly]),occluded=packet([occluded]),double=packet([readonly,readonly]),
        invalid_later=packet([readonly,invalid])),dict(readonly_state_word_mutations=mutations,
            occluded_diagnostic_depth_compare='never',invalid_later_depth_compare=9)

def build_fixture(capture,reference,evidence,out):
    replay=out/'replay';replay.mkdir()
    prepare(capture,replay,vertex_compiler_evidence=evidence)
    replay_path=replay/'replay.json';manifest=comparison.load_manifest(replay_path)
    ref,attachments=comparison.load_result(reference,replay_path,manifest,'angle')
    require(set(attachments)=={'color','depth','stencil'},'All independent original attachments are required')
    require(ref.get('actual_depth_format')=='depth32float_stencil8','Independent native depth backing storage is unverified')
    original,geometry=wire.wire_packet(replay,manifest)
    packets,diagnostics=query_packets(original)
    symbols={'halo_draw_packet':('packet.bin',original)}
    symbols.update({f'halo_query_{name}':(f'query-{name}.bin',data) for name,data in packets.items()})
    symbols.update({f'halo_draw_expected_{name}':(f'expected-{name}.bin',data) for name,data in attachments.items()})
    assembly=['.section .rodata,"a",@progbits'];payload_hashes={}
    for symbol,(name,data) in symbols.items():
        path=out/name;path.write_bytes(data);payload_hashes[str(path)]=sha(path)
        assembly+=['.balign 16',f'.global {symbol}',f'{symbol}:',f'.incbin {json.dumps(str(path))}']
    (out/'fixture.s').write_text('\n'.join(assembly)+'\n')
    target=manifest['target']
    macros=dict(PACKET_BYTES=len(original),SINGLE_BYTES=len(packets['single']),DOUBLE_BYTES=len(packets['double']),
        COLOR_BYTES=len(attachments['color']),DEPTH_BYTES=len(attachments['depth']),STENCIL_BYTES=len(attachments['stencil']),
        WIDTH=target['width'],HEIGHT=target['height'])
    require(len(packets['occluded'])==macros['SINGLE_BYTES'] and len(packets['invalid_later'])==macros['DOUBLE_BYTES'],
        'Guest mutable query packet extents differ')
    (out/'metal_host_query_fixture.h').write_text('\n'.join(f'#define HALO_QUERY_{name} {value}u' for name,value in macros.items())+'\n')
    fixture=dict(schema_version=1,kind='actual_draw_ilp32_query_fixture',complete=True,replay=str(replay_path),replay_sha256=sha(replay_path),
        source_capture=manifest['source_capture'],reference=str(reference),reference_sha256=sha(reference),target=target,geometry=geometry,
        packet_bytes=len(original),payload_sha256=payload_hashes,cases=CASES,diagnostics=diagnostics,
        expected_after_targets_gpu_uploaded=False,limits=['Original opaque geometry and shaders, modified readonly query write masks.',
            'Diagnostic depth-Never copy tests Boolean OR across a visible and occluded draw.',
            'Raw GPU result aggregation only; original cached CPU result-availability/timing remains unverified.',
            'Physical Xbox D24/F24 precision remains unverified.'])
    (out/'fixture.json').write_text(json.dumps(fixture,indent=2)+'\n');return fixture

def snapshot_sources(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
        'port/macos/host/metal_draw_encoder.mm','port/macos/host/metal_function_cache.h','port/macos/host/metal_warmup_cache.h','port/macos/host/metal_draw_encoder.h','port/macos/include/halo_metal_abi.h',
        'port/android/include/halo_android_abi.h','port/macos/tests/host_metal.mm','port/macos/tests/guest_metal_query.c',
        'port/macos/metal_imports.list','tools/android_build.py','tools/android_asm_convert.py','tools/android_imports.py',
        'tools/metal_host_draw_validate.py','tools/metal_draw_replay.py','tools/metal_draw_compare.py','tools/metal_host_query_validate.py']
    records={}
    for name in names:
        src=ROOT/name;dst=out/'source-snapshot'/name;dst.parent.mkdir(parents=True,exist_ok=True)
        before=sha(src);shutil.copy2(src,dst);require(sha(src)==sha(dst)==before,'Source changed during snapshot')
        records[str(src)]=dict(snapshot=str(dst),sha256=before)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def build_guest(out,llvm,linker,plugin,source_root):
    sys.path.insert(0,str(ROOT));from tools.android_build import GUEST_ABI_FLAGS
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    run=wire.run;guest=source_root/'port/macos/tests/guest_metal_query.c'
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-std=gnu11','-DHALO_MACOS=1','-I',out,'-emit-llvm','-S',guest,'-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,source_root/'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    for name in ('guest','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    run(sys.executable,source_root/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',source_root/'port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    script=out/'guest.ld';script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',script,out/'guest.o',out/'fixture.o',out/'imports.o','-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    return symbols

def consume_run(out,stdout,returncode):
    require(type(returncode) is int,'Observed native process exit status is required')
    prepared=json.loads((out/'prepared.json').read_text());fixture=json.loads((out/'fixture.json').read_text())
    def unchanged():
        for path,digest in prepared['source_and_binary_sha256'].items():require(sha(path)==digest,f'Stale query source/binary: {path}')
        require(sha(out/'fixture.json')==prepared['fixture_sha256'],'Query fixture changed')
        for path,digest in fixture['payload_sha256'].items():require(sha(path)==digest,f'Query packet/comparison changed: {path}')
        require(sha(fixture['replay'])==fixture['replay_sha256'],'Prepared original replay changed')
        require(sha(fixture['reference'])==fixture['reference_sha256'],'Independent reference changed')
        comparison.load_manifest(Path(fixture['replay']))
    unchanged();record=json.loads(stdout.read_text());native=out/'native'
    require(record.get('kind')=='native_metal_ilp32_transport' and record.get('guest_pointer_bits')==32,
        'Run did not use actual ILP32 imports')
    raw=(native/'guest-report.bin').read_bytes();require(len(raw)==64,'Query report is not64bytes')
    words=struct.unpack('<16I',raw);report=dict(zip(REPORT_FIELDS,words))
    require(words[0]==1 and words[13:15]==(fixture['target']['width'],fixture['target']['height']) and
        words[15]==fixture['packet_bytes'],'Query report belongs to another fixture')
    # The existing driver's guest-report.json has DRAW-specific labels. Never
    # interpret its first-difference fields as query results; decode raw words.
    (native/'query-report.json').write_text(json.dumps(report,indent=2)+'\n')
    comparisons={};actual_hashes={}
    for name,file in [('color','native-color-bgra.bin'),('depth','native-depth.bin'),('stencil','native-stencil.bin')]:
        path=native/file;data=path.read_bytes();expected=(out/f'expected-{name}.bin').read_bytes()
        require(len(data)==len(expected),'Native query attachment extent differs')
        if name=='color':
            rgba=bytearray(len(data));rgba[0::4]=data[2::4];rgba[1::4]=data[1::4];rgba[2::4]=data[0::4];rgba[3::4]=data[3::4];data=bytes(rgba)
        comparisons[name]=sum(a!=b for a,b in zip(data,expected));actual_hashes[str(path)]=sha(path)
    single=words[6]|words[7]<<32;double=words[8]|words[9]<<32
    passed=(returncode==0 and record.get('passed') is True and record.get('guest_result')==0 and words[1]==7 and
        words[2]==0 and words[3]==2**32-1 and words[4]==(1<<len(CASES))-1 and words[5]>=10 and
        single>0 and double==single*2 and words[10:13]==(1,1,0) and not any(comparisons.values()))
    proof=dict(prepared,complete=words[1]==7,passed=passed,build_only=False,returncode=returncode,guest_run=record,
        query_report=report,counting_single=single,counting_two_draws=double,attachment_different_bytes=comparisons,
        actual_payload_sha256=actual_hashes,stdout_sha256=sha(stdout),raw_report_sha256=sha(native/'guest-report.bin'),
        original_cpu_query_timing_verified=False)
    unchanged();(out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,guest_result=record.get('guest_result'),counting_single=single,
        counting_two_draws=double,attachment_different_bytes=comparisons,result=str(out/'result.json')),indent=2))
    require(passed,'Actual ILP32 query lifecycle failed; evidence retained')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path);parser.add_argument('--reference',type=Path)
    parser.add_argument('--vertex-compiler-evidence',type=Path);parser.add_argument('--rebase-plugin',type=Path)
    parser.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    parser.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    parser.add_argument('--output',type=Path,default=ROOT/'build/metal-poc/host-query-validation')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--build-only',action='store_true');mode.add_argument('--consume-run',type=Path)
    parser.add_argument('--consume-returncode',type=int)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.consume_run:consume_run(out,args.consume_run,args.consume_returncode);return
    require(args.capture and args.reference and args.rebase_plugin,'Build needs original capture, reference and rebase plugin')
    require(not (out/'fixture.json').exists(),'Output already contains a fixture; preserve it and choose a new folder')
    records=snapshot_sources(out)
    fixture=build_fixture(args.capture.resolve(),args.reference.resolve(),
        args.vertex_compiler_evidence.resolve() if args.vertex_compiler_evidence else None,out)
    llvm=args.llvm_bin.resolve();linker=args.linker.absolute();plugin=args.rebase_plugin.resolve()
    symbols=build_guest(out,llvm,linker,plugin,out/'source-snapshot')
    executable,sources=wire.build_host(out,source_root=out/'source-snapshot')
    for path,r in records.items():require(sha(path)==r['sha256'],'Source changed during query preparation; preserve attempt and reprepare')
    required=('__host_import_table','__host_import_names','__host_import_count','halo_draw_report',
        'halo_draw_actual_color','halo_draw_actual_depth','halo_draw_actual_stencil')
    require(all(k in symbols for k in required),'Missing actual ILP32 query fixture symbols')
    native=out/'native';native.mkdir()
    command=[str(executable),str(out/'guest.elf'),*[hex(symbols[k]) for k in required[:3]],'0x2000000',
        *[hex(symbols[k]) for k in required[3:]],str(fixture['target']['width']),str(fixture['target']['height']),str(native)]
    dependencies=[*map(Path,records),*[Path(r['snapshot']) for r in records.values()],*sources,plugin,
        llvm/'clang',llvm/'opt',llvm/'llc',linker,out/'guest.elf',executable,out/'fixture.json',out/'fixture.s',
        out/'metal_host_query_fixture.h',out/'source-snapshot.json',out/'host_import_table.c',out/'imports.s']
    proof=dict(schema_version=1,kind='actual_draw_ilp32_visibility_queries',complete=False,passed=False,
        fixture_sha256=sha(out/'fixture.json'),source_capture=fixture['source_capture'],
        source_and_binary_sha256={str(path):sha(path) for path in dependencies},execution_command=command,
        build_only=args.build_only,cases=CASES,limits=fixture['limits'],original_cpu_query_timing_verified=False)
    (out/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n')
    if args.build_only:print(json.dumps(dict(prepared=str(out/'prepared.json'),execution_command=command),indent=2));return
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    (native/'stdout.json').write_text(result.stdout);(native/'stderr.log').write_text(result.stderr)
    consume_run(out,native/'stdout.json',result.returncode)

if __name__=='__main__':main()
