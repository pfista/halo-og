#!/usr/bin/env python3
"""Link the embedded iPhone guest and its native Metal renderer against Mac SDL.

This validates the game ABI independently of UIKit and device signing.
It does not replace simulator or hardware validation.
"""
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.linux_build import MINIUPNPC_DEFINES, MINIUPNPC_DIR, miniupnpc_sources

BUILD = ROOT / 'build/ios/mac-runtime-check'

def main():
    os.chdir(ROOT)
    BUILD.mkdir(parents=True, exist_ok=True)
    mac_host = ROOT / 'port/macos/host'
    ios_host = ROOT / 'port/ios/host'
    excluded = {'host_main.c', 'host_loader.c', 'host_perf.c', 'host_gl.c', 'host_gl_bridge.c'}
    sources = [p for p in sorted(mac_host.glob('*.c')) if p.name not in excluded]
    sources += [ios_host / 'host_loader.c', ios_host / 'host_main.m',
                mac_host / 'host_metal.mm', mac_host / 'metal_draw_encoder.mm', mac_host / 'entry.s',
                ROOT / 'build/ios/host/host_import_table.c', ROOT / 'build/ios/embed/guest_image.s',
                *miniupnpc_sources()]
    sdl = Path(os.environ.get('HALO_MACOS_SDL_PREFIX', '/opt/homebrew/opt/sdl3'))
    flags = ['-arch', 'arm64', '-O2', '-g', '-DHALO_MACOS=1', '-DHALO_IOS=1',
             '-DHALO_IOS_MAC_CHECK=1', '-DHALO_MACOS_NATIVE_METAL=1', '-D_DARWIN_C_SOURCE',
             '-I.', '-Iport/macos/host', '-Iport/android/include', '-Iport/linux/src',
             f'-I{sdl / "include"}', '-Ibuild/ios/embed',
             f'-I{MINIUPNPC_DIR / "include"}', f'-I{MINIUPNPC_DIR / "src"}', *MINIUPNPC_DEFINES]
    objects = []
    for source in sources:
        obj = BUILD / (source.name + '.o')
        language = ['-fobjc-arc', '-fblocks'] if source.suffix in ('.m', '.mm') else []
        if source.suffix == '.mm':
            language.append('-std=c++17')
        subprocess.run(['clang', *flags, *language, '-c', source, '-o', obj], check=True)
        objects.append(obj)
    subprocess.run(['clang++', '-arch', 'arm64', *objects, f'-L{sdl / "lib"}', '-lSDL3',
                    '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'QuartzCore',
                    '-o', BUILD / 'halo'], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(BUILD / 'halo')], check=True)
    print(BUILD / 'halo')
if __name__ == '__main__':
    main()
