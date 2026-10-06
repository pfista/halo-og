#!/usr/bin/env python3
"""Exercise logical RGBA channel clears through the real ILP32 Metal imports."""
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

FIELDS=['abi_version','phase','status','failed_command','clear_cases','atomic_rejections',
        'attachment_invariant_checks','color_errors','depth_errors','stencil_errors','width','height',
        'capabilities','completed_sequence_lo','completed_sequence_hi','initialized_target_check']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(v,message):
    if not v:raise ValueError(message)


def snapshot(out):
    names=['port/macos/tests/guest_metal_clear_channels.c','port/macos/tests/host_metal.mm',
        'port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
        'port/macos/host/metal_draw_encoder.mm','port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h',
        'port/macos/include/halo_metal_abi.h','port/android/include/halo_android_abi.h',
        'port/macos/metal_imports.list','tools/android_build.py','tools/android_imports.py',
        'tools/android_asm_convert.py','tools/metal_host_draw_validate.py','tools/metal_host_clear_validate.py']
    records={}
    for name in names:
        src=ROOT/name;dst=out/'source-snapshot'/name;dst.parent.mkdir(parents=True,exist_ok=True)
        h=sha(src);shutil.copy2(src,dst);require(sha(src)==sha(dst)==h,'Source changed during snapshot')
        records[str(src)]=dict(snapshot=str(dst),sha256=h)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n')
    return records


def build_guest(out,llvm,linker,plugin,source_root):
    sys.path.insert(0,str(ROOT));from tools.android_build import GUEST_ABI_FLAGS
    resource=Path(subprocess.check_output([llvm/'clang','-print-resource-dir'],text=True).strip())
    run=wire.run
    guest=source_root/'port/macos/tests/guest_metal_clear_channels.c'
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-std=gnu11','-Wall','-Wextra','-Werror','-DHALO_MACOS=1','-emit-llvm','-S',guest,'-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,source_root/'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'guest.s','-o',out/'guest.o')
    run(sys.executable,source_root/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',source_root/'port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    script=out/'guest.ld';script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',script,out/'guest.o',out/'imports.o','-o',out/'guest.elf')
    result={}
    for line in subprocess.check_output([llvm/'llvm-nm','--defined-only',out/'guest.elf'],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:result[fields[2]]=int(fields[0],16)
    return result


def consume(out,stdout,returncode):
    prepared=json.loads((out/'prepared.json').read_text())
    for path,h in prepared['source_and_binary_sha256'].items():require(sha(path)==h,'Stale clear proof source/binary: '+path)
    result=json.loads(Path(stdout).read_text())
    require(returncode==0 and result['guest_result']==0 and result['guest_pointer_bits']==32,'Actual ILP32 clear test failed')
    raw=(out/'native/guest-report.bin').read_bytes();require(len(raw)==64,'Truncated raw clear report')
    report=dict(zip(FIELDS,struct.unpack('<16I',raw)))
    require(report['phase']==3000 and report['clear_cases']==246 and report['atomic_rejections']==14 and
        report['attachment_invariant_checks']==261 and report['initialized_target_check']==1 and
        report['color_errors']==report['depth_errors']==report['stencil_errors']==0,'Clear coverage/case counts failed')
    expected_color=bytes(v for y in range(7) for x in range(13) for v in (17+x,33+y,71+x+y,90+x+2*y))
    expected_depth=struct.pack('<91f',*[.25+i/1024 for i in range(91)])
    expected_stencil=bytes(49+x+3*y for y in range(7) for x in range(13))
    native=out/'native';attachments={}
    for name,data in [('native-color-bgra.bin',expected_color),('native-depth.bin',expected_depth),('native-stencil.bin',expected_stencil)]:
        path=native/name;require(path.read_bytes()==data,'Independent final seeded attachment differs: '+name)
        attachments[str(path)]=sha(path)
    # The generic driver has old draw labels. Preserve, then decode our raw
    # report under its actual schema instead of calling counts differences.
    legacy=native/'guest-report.json'
    if legacy.exists():legacy.rename(native/'legacy-driver-labels-ignored.json')
    (native/'clear-report.json').write_text(json.dumps(report,indent=2)+'\n')
    proof=dict(prepared,complete=True,passed=True,returncode=returncode,report=report,
        raw_report_sha256=sha(native/'guest-report.bin'),attachment_sha256=attachments,
        stdout_sha256=sha(stdout),record=result)
    (out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(dict(passed=True,cases=report['clear_cases'],atomic_rejections=report['atomic_rejections'],
        independent_attachment_checks=report['attachment_invariant_checks'],result=str(out/'result.json')),indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--rebase-plugin',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'build/metal-poc/channel-clear-validation')
    group=p.add_mutually_exclusive_group();group.add_argument('--build-only',action='store_true');group.add_argument('--consume-run',type=Path)
    p.add_argument('--consume-returncode',type=int)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.consume_run:
        require(args.consume_returncode is not None,'Need observed native exit status')
        consume(out,args.consume_run,args.consume_returncode);return
    require(args.rebase_plugin,'Existing rebase toolchain plugin required')
    require(not (out/'prepared.json').exists(),'Preserve previous proof; choose a fresh output directory')
    records=snapshot(out);source_root=out/'source-snapshot'
    llvm=args.llvm_bin.resolve();linker=args.linker.absolute();plugin=args.rebase_plugin.resolve()
    symbols=build_guest(out,llvm,linker,plugin,source_root)
    # Strict compile the actual retained backend; the existing runner builds the
    # remaining production allocator/encoder/imports with its established flags.
    wire.run('clang++','-std=c++17','-fobjc-arc','-fblocks','-arch','arm64','-mmacosx-version-min=14.0',
        '-DHALO_MACOS=1','-Wall','-Wextra','-Werror','-I'+str(source_root/'port/macos/host'),
        '-I'+str(source_root/'port/android/include'),'-fsyntax-only',source_root/'port/macos/host/host_metal.mm')
    executable,sources=wire.build_host(out,source_root=source_root)
    required=['__host_import_table','__host_import_names','__host_import_count','halo_clear_report',
        'halo_clear_color','halo_clear_depth','halo_clear_stencil']
    require(all(n in symbols for n in required),'Missing clear guest symbols')
    native=out/'native';native.mkdir()
    command=[str(executable),str(out/'guest.elf'),*[hex(symbols[n]) for n in required[:3]],'0x400000',
        *[hex(symbols[n]) for n in required[3:]],'13','7',str(native)]
    for path,record in records.items():require(sha(path)==record['sha256'],'Source changed during clear build')
    dependencies=[*map(Path,records),*[Path(v['snapshot']) for v in records.values()],*sources,
        plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,out/'guest.elf',executable,
        out/'imports.s',out/'host_import_table.c',out/'source-snapshot.json']
    prepared=dict(kind='native_metal_channel_clear_ilp32',schema_version=1,complete=False,passed=False,
        execution_command=command,source_and_binary_sha256={str(path):sha(path) for path in dependencies},
        scope='Actual rebased ILP32 guest commands and original host backend; synthetic independent patterned attachments.',
        cases=['All15 logicalRGBA masks, RGBA8/BGRA8, full/rectangle, color/depth/stencil aspect combinations',
            'Depth-only/stencil-only/combined clears preserve other initialized aspects','Untouched byte channels/pixels and content versions',
            'Fourteen malformed/stale/undefined later records reject atomically before the earlier valid clear',
            'Full15mask initializes fresh color target; partial mask rejects undefined prior channels'],
        limits=['Offscreen clear proof does not establish original game frame fidelity.',
            'Generic driver file native-color-bgra.bin contains raw RGBA bytes for this RGBA final target; explicit expected bytes control interpretation.',
            'Generic driver JSON field labels are ignored; consumer uses raw64B clear report schema.',
            'Window/scaled presentation/vsync are a separate fixture.'])
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    if args.build_only:print(json.dumps(dict(prepared=str(out/'prepared.json'),execution_command=command),indent=2));return
    result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    (native/'stdout.json').write_text(result.stdout);(native/'stderr.log').write_text(result.stderr)
    consume(out,native/'stdout.json',result.returncode)


if __name__=='__main__':main()
