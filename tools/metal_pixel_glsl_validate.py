#!/usr/bin/env python3
"""Run independent cube/DOT/volume fixtures through unchanged generated GLES.

The known native-only GL signed-dot mapping correction is excluded explicitly.
This component check is not a complete-frame or physical Xbox parity proof.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess

import metal_shader_validate as v
from metal_pixel_fixtures import texture_stage_fixtures

ROOT = v.ROOT
# Reuse the already built local port dependency checkout when this recovered
# worktree has no dependency build. No installation or environment mutation.
DEPENDENCIES = ROOT if (ROOT / 'build/macos/angle/dist').exists() else ROOT.parent / 'pfista-halo-macos'
ANGLE = DEPENDENCIES / 'build/macos/angle/dist'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [ROOT / p for p in ('port/linux/src/nv2a_psh.c', 'port/linux/src/nv2a_vsh.c',
             'port/linux/src/xgpu_shader_standalone.h', 'port/linux/src/xgpu_msl.h',
             'port/macos/metal-poc/shader_text.c', 'port/macos/metal-poc/pixel_glsl_validate.mm',
             'tools/metal_pixel_fixtures.py', 'tools/metal_shader_validate.py')]
    paths += [Path(__file__).resolve(), ANGLE / 'EGL.xcframework/macos-arm64/libEGL.framework/libEGL',
              ANGLE / 'GLESv2.xcframework/macos-arm64/libGLESv2.framework/libGLESv2']
    return {str(p.resolve()): digest(p) for p in paths}


def consume(out, gpu):
    manifest = json.loads((out / 'manifest.json').read_text())
    if manifest['source_sha256'] != sources():
        raise RuntimeError('Sources or ANGLE libraries changed; prepare again')
    if manifest['baseline_commit'] != v.run('git', 'rev-parse', 'HEAD').stdout.strip():
        raise RuntimeError('GLES baseline changed; prepare again')
    for file, sha in manifest['shader_sha256'].items():
        if digest(out / file) != sha:
            raise RuntimeError(f'Generated shader changed: {file}')
    if (gpu['manifest_sha256'] != digest(out / 'manifest.json') or
            gpu['runner_sha256'] != digest(out / 'pixel_glsl_validate') or
            gpu['runner_sha256'] != manifest['runner_sha256'] or
            gpu['pixel_cases'] != len(manifest['tests'])):
        raise RuntimeError('GPU result does not match current prepared fixture package')
    result = dict(gpu=gpu, source_sha256=manifest['source_sha256'],
                  baseline_commit=manifest['baseline_commit'],
                  existing_glsl_unchanged=manifest['existing_glsl_unchanged'],
                  excluded=manifest['excluded'], limits=manifest['limits'])
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/metal-poc/pixel-glsl-validation')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--gpu-result', type=Path)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    if args.gpu_result:
        consume(out, json.loads(args.gpu_result.read_text())); return
    before = sources(); commit = v.run('git', 'rev-parse', 'HEAD').stdout.strip()
    current, baseline = v.build_library(out), v.build_library(out, True)
    tests, shaders, excluded = [], {}, []
    for provider_key, f in texture_stage_fixtures():
        # Use one ctypes ABI class even when Python namespace-package imports
        # gave the fixture provider a structurally identical class.
        key = v.PixelKey.from_buffer_copy(bytes(provider_key))
        if 'mapping-2' in f['name']:
            excluded.append(f['name']); continue
        identity = bytes(key)
        if identity not in shaders:
            source = v.generated(current.nv2a_pixel_shader_to_glsl, C.byref(key))
            if source != v.generated(baseline.nv2a_pixel_shader_to_glsl, C.byref(key)):
                raise RuntimeError('Existing generated GLSL changed')
            name = f'pixel-{len(shaders):03}.glsl'; (out / name).write_text(source)
            shaders[identity] = name
        f['shader'] = shaders[identity]; tests.append(f)
    egl, gles = ANGLE / 'EGL.xcframework/macos-arm64', ANGLE / 'GLESv2.xcframework/macos-arm64'
    executable = out / 'pixel_glsl_validate'
    v.run('xcrun', 'clang++', '-std=c++17', '-O2', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
          ROOT / 'port/macos/metal-poc/pixel_glsl_validate.mm',
          f'-I{DEPENDENCIES / "build/macos/toolchain/gl"}', f'-F{egl}', f'-F{gles}',
          '-framework', 'Foundation', '-framework', 'libEGL', '-framework', 'libGLESv2',
          f'-Wl,-rpath,{egl}', f'-Wl,-rpath,{gles}', '-o', executable)
    v.run('codesign', '--force', '--sign', '-', executable)
    if before != sources() or commit != v.run('git', 'rev-parse', 'HEAD').stdout.strip():
        raise RuntimeError('Sources changed during preparation')
    manifest = dict(tests=tests, shader_sha256={name: digest(out / name) for name in shaders.values()},
                    runner_sha256=digest(executable), source_sha256=before, baseline_commit=commit,
                    existing_glsl_unchanged=len(shaders), excluded=excluded,
                    limits=['independent component fixture check; no complete game frame',
                            'known native-only signed-dot GL mapping correction excluded explicitly',
                            'GLES is not a physical Xbox reference'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.prepare_only:
        print(json.dumps(dict(executable=str(executable), manifest=str(out / 'manifest.json'),
                              pixel_cases=len(tests), excluded=len(excluded)), indent=2)); return
    consume(out, json.loads(v.run(executable, out / 'manifest.json').stdout))


if __name__ == '__main__':
    main()
