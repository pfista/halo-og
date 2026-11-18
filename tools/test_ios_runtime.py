#!/usr/bin/env python3
"""Exercise native Metal imports from a signed iOS guest at two data and stack bases."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/ios/probe'
LLVM = Path(os.environ.get('HALO_MACOS_LLVM_BIN', '/opt/homebrew/opt/llvm/bin'))


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True, timeout=60)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    imports = OUT / 'probe_imports.list'
    imports.write_text('host_probe_arguments\n')
    run(sys.executable, 'tools/android_imports.py', '--ios', '--host-table', OUT / 'host_import_table.c',
        OUT / 'imports.s', 'port/macos/metal_imports.list', imports)
    run(LLVM / 'clang', '--target=aarch64-linux-android', '-c', OUT / 'imports.s', '-o', OUT / 'imports.o')
    objects = [OUT / 'imports.o']
    for source in (Path('port/macos/tests/guest_memory.c'), Path('port/ios/tests/guest_libc.c'),
                   Path('port/ios/tests/guest_metal_probe.c')):
        base = OUT / source.stem
        run(sys.executable, 'tools/ios_guest_cc.py', '--target=arm64_32-apple-watchos',
            '-mcpu=cortex-a53', '-O2', '-ffreestanding', '-fno-stack-protector', '-fno-unwind-tables',
            '-fno-asynchronous-unwind-tables', '-nostdlibinc',
            '-S', source, '-o', base.with_suffix('.darwin.s'))
        run(sys.executable, 'tools/android_asm_convert.py', base.with_suffix('.darwin.s'), base.with_suffix('.s'))
        run(LLVM / 'clang', '--target=aarch64-linux-android', '-c', base.with_suffix('.s'), '-o', base.with_suffix('.o'))
        objects.append(base.with_suffix('.o'))
    run('build/macos/toolchain/bin/ld.lld', '-m', 'aarch64linux', '-static', '-nostdlib',
        '-Ttext=0x88000000', '-e', 'guest_probe', *objects, '-o', OUT / 'guest.elf')
    symbols = subprocess.check_output([LLVM / 'llvm-nm', '--defined-only', OUT / 'guest.elf'], text=True)
    addresses = {line.split()[-1]: line.split()[0] for line in symbols.splitlines() if line.strip()}
    symbols = [f'-DPROBE_IMPORT_{key.upper()}=0x{addresses["__host_import_" + key]}'
               for key in ('table', 'names', 'count')]
    run(sys.executable, 'tools/ios_embed.py', OUT / 'guest.elf', OUT / 'embed')
    flags = ['-arch', 'arm64', '-mmacosx-version-min=14.0', '-O2', '-DHALO_MACOS=1', '-DHALO_IOS=1',
             '-Iport/macos/host', '-Iport/android/include', f'-I{OUT / "embed"}']
    objects = []
    for source in (Path('port/ios/tests/signed_image.m'), Path('port/macos/host/host_memory.c'),
                   OUT / 'host_import_table.c', OUT / 'embed/guest_image.s',
                   Path('port/macos/host/host_metal.mm'), Path('port/macos/host/metal_draw_encoder.mm')):
        obj = OUT / (source.name + '.o')
        options = []
        if source.suffix in ('.m', '.mm'):
            options.extend(['-fobjc-arc', '-fblocks'])
        if source.suffix == '.mm':
            options.append('-std=c++17')
        if source.name == 'signed_image.m':
            options.extend(['-Wall', '-Wextra', '-Werror', *symbols])
        run('clang', *flags, *options, '-c', source, '-o', obj)
        objects.append(obj)
    run('clang++', '-arch', 'arm64', '-mmacosx-version-min=14.0', '-Wl,-dead_strip', *objects,
        '-framework', 'Metal', '-framework', 'QuartzCore', '-framework', 'Foundation', '-o', OUT / 'signed_image')
    run('codesign', '--force', '--sign', '-', OUT / 'signed_image')
    run('codesign', '--verify', '--strict', OUT / 'signed_image')
    run(OUT / 'signed_image')


if __name__ == '__main__':
    main()
