#!/usr/bin/env python3
"""Execute one signed iOS guest image with its data and stack at two different bases."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/ios/probe'
LLVM = Path(os.environ.get('HALO_MACOS_LLVM_BIN', '/opt/homebrew/opt/llvm/bin'))
GL = ROOT / 'build/macos/toolchain/gl'


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True, timeout=60)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Exercise a real generated GLES wrapper and iOS import thunk. The native
    # callback checks both the pointer array and its individually widened entries.
    gl_list = OUT / 'gl.h'
    gl_list.write_text('/* ANDROID_GL_FUNCTIONS_BEGIN */\nX(glShaderSource)\n/* ANDROID_GL_FUNCTIONS_END */\n')
    imports = OUT / 'gl_imports.list'
    run(sys.executable, 'tools/android_gl_stubs.py', gl_list, GL / 'GLES3/gl32.h',
        GL / 'GLES2/gl2ext.h', OUT / 'guest_gl.c', imports)
    if imports.read_text().splitlines() != ['hostgl_glShaderSource']:
        raise RuntimeError('Expected one native glShaderSource slot in the probe import table')
    run(sys.executable, 'tools/android_imports.py', '--ios', OUT / 'imports.s', imports)
    run(LLVM / 'clang', '--target=aarch64-linux-android', '-c', OUT / 'imports.s', '-o', OUT / 'imports.o')
    objects = [OUT / 'imports.o']
    for source in (Path('port/macos/tests/guest_memory.c'), Path('port/ios/tests/guest_libc.c'),
                   Path('port/ios/tests/guest_gl_probe.c'), OUT / 'guest_gl.c'):
        base = OUT / source.stem
        run(sys.executable, 'tools/ios_guest_cc.py', '--target=arm64_32-apple-watchos',
            '-mcpu=cortex-a53', '-O2', '-ffreestanding', '-fno-stack-protector', '-fno-unwind-tables',
            '-fno-asynchronous-unwind-tables', '-nostdlibinc', f'-I{GL}', '-Iport/ios/tests/freestanding',
            '-S', source, '-o', base.with_suffix('.darwin.s'))
        run(sys.executable, 'tools/android_asm_convert.py', base.with_suffix('.darwin.s'), base.with_suffix('.s'))
        run(LLVM / 'clang', '--target=aarch64-linux-android', '-c', base.with_suffix('.s'), '-o', base.with_suffix('.o'))
        objects.append(base.with_suffix('.o'))
    run('build/macos/toolchain/bin/ld.lld', '-m', 'aarch64linux', '-static', '-nostdlib',
        '-Ttext=0x88000000', '-e', 'guest_probe', *objects, '-o', OUT / 'guest.elf')
    symbols = subprocess.check_output([LLVM / 'llvm-nm', '--defined-only', OUT / 'guest.elf'], text=True)
    table = next(line.split()[0] for line in symbols.splitlines() if line.split()[-1] == '__host_import_table')
    run(sys.executable, 'tools/ios_embed.py', OUT / 'guest.elf', OUT / 'embed')
    run('clang', '-arch', 'arm64', '-O2', '-Wall', '-Wextra', '-Werror', f'-DPROBE_IMPORT_TABLE=0x{table}',
        f'-I{OUT / "embed"}', 'port/ios/tests/signed_image.c', OUT / 'embed/guest_image.s', '-o', OUT / 'signed_image')
    run('codesign', '--force', '--sign', '-', OUT / 'signed_image')
    run(OUT / 'signed_image')


if __name__ == '__main__':
    main()
