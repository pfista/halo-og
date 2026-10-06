#!/usr/bin/env python3
"""Build/run the native guest-to-Metal transport through real ILP32 imports.

Uses an existing LLVM22/rebase toolchain. Does not build/install the game or
change ANGLE, the primary checkout, user saves, or environment files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    subprocess.run([str(a) for a in args],cwd=ROOT,check=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--rebase-plugin',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'build/metal-poc/host-transport-validation')
    p.add_argument('--build-only',action='store_true')
    args=p.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    llvm=args.llvm_bin.resolve(); plugin=args.rebase_plugin.resolve()
    from tools.android_build import GUEST_ABI_FLAGS
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    guest=ROOT/'port/macos/tests/guest_metal.c'
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-std=gnu11','-DHALO_MACOS=1','-emit-llvm','-S',guest,'-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'guest.s','-o',out/'guest.o')
    run(sys.executable,'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s','port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    # RX and data do not share a Darwin 16KB page, matching the production image.
    script=out/'guest.ld'; script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(args.linker,'-m','aarch64elf','-T',script,out/'guest.o',out/'imports.o','-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3: symbols[fields[2]]=int(fields[0],16)
    flags=['-arch','arm64','-mmacosx-version-min=14.0','-O2','-g','-DHALO_MACOS=1','-Iport/macos/host','-Iport/android/include']
    objects=[]
    sources=[ROOT/'port/macos/host/host_memory.c',out/'host_import_table.c',ROOT/'port/macos/host/host_metal.mm',ROOT/'port/macos/host/metal_draw_encoder.mm',ROOT/'port/macos/tests/host_metal.mm']
    for index,source in enumerate(sources):
        obj=out/(str(index)+'-'+source.name+'.o'); cpp=source.suffix=='.mm'
        run('clang++' if cpp else 'clang',*flags,*(['-std=c++17','-fobjc-arc','-fblocks'] if cpp else []),'-c',source,'-o',obj)
        objects.append(obj)
    executable=out/'host_metal_probe'
    run('clang++',*flags,*objects,'-framework','Foundation','-framework','Metal','-framework','QuartzCore','-o',executable)
    dependencies=[guest,*sources,ROOT/'port/macos/host/host.h',ROOT/'port/macos/host/metal_function_cache.h',ROOT/'port/macos/host/metal_draw_encoder.h',ROOT/'port/android/include/halo_android_abi.h',ROOT/'port/macos/include/halo_metal_abi.h',ROOT/'port/macos/metal_imports.list',ROOT/'tools/android_imports.py',ROOT/'tools/android_asm_convert.py',Path(__file__).resolve(),plugin,llvm/'clang',llvm/'opt',llvm/'llc',args.linker,out/'guest.elf',executable]
    proof={'schema_version':1,'kind':'native_metal_guest_transport','scope':'Actual rebased ILP32 imports; GPU resources, padded uploads, copies, full/scissored clears, depth/stencil readbacks and lifetime validation. No original game draws or complete gameplay frame.',
        'source_and_binary_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in dependencies},'passed':False,'build_only':args.build_only,
        'cases':['ILP32 wire layouts and generated imports','13x7 padded RGBA upload','full depth/stencil clear','ordered texture copy','scissored color/depth/stencil clear','independent aspect readbacks','whole-batch unknown-op rejection','per-command upload snapshots','copy between two resource versions','lifetime generation reuse rejection','new generation invalidates old handle','undefined-content read rejection','stencil-only clear preserves depth','depth-only clear preserves stencil','BGRA full/copy/color-only rectangle clear channel ordering','overflowed and inaccessible guest ranges','shutdown rejects later access'],
        'limitations':['No original game draw submission yet','D32FloatStencil8 attachment storage; Xbox D24/F24 precision remains a separate fidelity requirement','Synchronous completion in this first bridge; in-flight scheduling remains incomplete','SDL drawable/presentation path compiles but is not exercised by this offscreen probe']}
    if not args.build_only:
        command=[str(executable),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')]]
        result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
        proof.update(execution_command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
        print(result.stdout,end=''); print(result.stderr,end='',file=sys.stderr)
        if result.returncode==0:
            record=json.loads(result.stdout.strip()); proof['passed']=record.get('passed') is True and record.get('guest_result')==0
    (out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
    if not args.build_only and not proof['passed']: raise SystemExit('Native transport verification failed; evidence retained')
    print(out/'result.json')

if __name__=='__main__':
    sys.path.insert(0,str(ROOT)); main()
