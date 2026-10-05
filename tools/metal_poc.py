#!/usr/bin/env python3
"""Build an isolated, local-only Metal scene viewer from a user-owned Xbox map."""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess

from metal_poc_export import export

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', type=Path, required=True, help='User-owned Xbox v5 .map file')
    parser.add_argument('--open', action='store_true', help='Open the completed scene viewer')
    parser.add_argument('--capture', type=Path, help='Render an offscreen PNG plus timing JSON')
    parser.add_argument('--overview', action='store_true', help='Blood Gulch overview camera')
    parser.add_argument('--output-directory', type=Path,
                        help='Separate build directory for another map preview')
    args = parser.parse_args()
    source = ROOT / 'port/macos/metal-poc'
    build = args.output_directory.resolve() if args.output_directory else ROOT / 'build/metal-poc'
    app = build / 'Halo Metal POC.app'
    resources = app / 'Contents/Resources'
    executable = app / 'Contents/MacOS/HaloMetalPOC'
    executable.parent.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    scene = export(args.map.resolve(), resources / 'scene')
    for shader in source.glob('*.metal'):
        shutil.copyfile(shader, resources / shader.name)
    identifier = 'local.halo.metal-poc'
    if args.output_directory:
        identifier += '.' + scene['map']
    plist = dict(CFBundleName='Halo Metal POC', CFBundleDisplayName='Halo Metal POC',
                 CFBundleIdentifier=identifier, CFBundleExecutable='HaloMetalPOC',
                 CFBundlePackageType='APPL', CFBundleVersion='6', CFBundleShortVersionString='0.6',
                 LSMinimumSystemVersion='13.0', NSHighResolutionCapable=True)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O2', '-fobjc-arc', '-Wall', '-Wextra',
                    '-Wno-unused-parameter', '-mmacosx-version-min=13.0', str(source / 'main.mm'),
                    '-framework', 'Cocoa', '-framework', 'Metal', '-framework', 'MetalKit',
                    '-framework', 'QuartzCore', '-o', str(executable)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    print(f'Built: {app}', flush=True)
    camera = ['--overview'] if args.overview else []
    if args.capture:
        args.capture.resolve().parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(executable), '--capture', str(args.capture.resolve()), *camera], check=True)
    if args.open:
        subprocess.run(['open', '-n', str(app), '--args', *camera], check=True)


if __name__ == '__main__':
    main()
