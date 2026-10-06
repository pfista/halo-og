#!/usr/bin/env python3
"""Check original meter combiners, filtered HUD coverage and blending on Metal.

The production meter's four combiner stages are used unchanged. Independent
arithmetic predicts source color, coverage alpha, alpha kill/test and the
original CONSTANTCOLOR/SRCALPHA blend. No game build or installation is needed.
"""
import argparse
import copy
import ctypes as C
import hashlib
import itertools
import json
import math
from pathlib import Path
import re

import metal_shader_validate as shader

ROOT = shader.ROOT
METER = ROOT / 'source/rasterizer/xbox/rasterizer_xbox_dynavobgeom.c'
HARNESS = ROOT / 'port/macos/metal-poc/shader_validate.mm'
CLEAR = [.11, .22, .33, .2]
MINIMUM = [51 / 255, 89 / 255, 127 / 255, 115 / 255]
MAXIMUM = [178 / 255, 127 / 255, 76 / 255, 204 / 255]
FLASH = [17 / 255, 34 / 255, 51 / 255, 128 / 255]
BACKGROUND = [13 / 255, 26 / 255, 39 / 255, 217 / 255]
TINT = [204 / 255, 178 / 255, 153 / 255, 102 / 255]


class AlphaBorderOptions(C.Structure):
    _fields_ = [('version', C.c_uint32), ('depth_contract', C.c_uint32),
                ('native_alpha_border_mask', C.c_uint32)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def meter_key(coverage=True, negative=False, alpha_test=False):
    """Copy only literal shader state from the game's original meter branch."""
    source = METER.read_text().split('meter = parameters->meter_parameters;', 1)[1]
    source = source.split('else if (parameters->map[0])', 1)[0]
    key = shader.PixelKey()
    key.sampler_type[0] = 1
    key.alpha_kill[0] = 1
    for field, base in (('combiner_count', 53), ('rgb_inputs', 34), ('alpha_inputs', 0),
                        ('rgb_outputs', 45), ('alpha_outputs', 26),
                        ('final_combiner_inputs_abcd', 8), ('final_combiner_inputs_efg', 9)):
        for match in re.finditer(r'pixel_shader\.' + field + r'(?:\[(\d+)\])?\s*=\s*(0x[0-9A-Fa-f]+)\s*;', source):
            key.combiner_state[base + int(match[1] or 0)] = int(match[2], 16)
    if '0x0C201C00 | (meter->flash_color_is_negative ? 0x000000E2 : 0x00000002)' not in source:
        raise RuntimeError('Original flash polarity expression changed; review fixture')
    key.combiner_state[36] = 0x0C201C00 | (0xE2 if negative else 2)
    if key.combiner_state[53] != 0x11104 or key.combiner_state[8:10] != [0x0C180000, 0x1C00]:
        raise RuntimeError('Original meter state changed; review independent arithmetic')
    key.texture_modes = 1
    key.coverage_alpha = int(coverage)
    key.alpha_test_function = 516 if alpha_test else 0
    return key


def signed_clamp(value):
    return min(1., max(-1., value))


def meter_reference(blue, coverage, art_alpha, corrected, negative=False):
    """Evaluate the meter's fill/gradient/flash/background equations directly.

    This is independent of generated shader source and register translation.
    General combiner writes saturate to [-1,1]; the final output to [0,1].
    """
    gradient_alpha = signed_clamp(8 * (32 / 255) * blue)
    fill_blue = signed_clamp(4 * (MINIMUM[3] - blue))
    gradient = [signed_clamp((1 - shader.clamp(gradient_alpha)) * MINIMUM[i] +
                             gradient_alpha * MAXIMUM[i]) for i in range(3)]
    flash_weight = max(signed_clamp(1 - 2 * max(fill_blue, 0)), 0)
    flashed = [signed_clamp(max(gradient[i], 0) +
                            flash_weight * FLASH[i] * (-1 if negative else 1))
               for i in range(3)]
    background_selected = signed_clamp(blue + .5 - FLASH[3]) >= .5
    rgb = BACKGROUND[:3] if background_selected else flashed
    alpha = BACKGROUND[3] if background_selected else TINT[3]
    source = [shader.clamp(max(value, 0) * art_alpha) for value in rgb] + [alpha]
    if corrected:
        source[3] = (1 - coverage) + coverage * alpha
    return source


def hud_fixtures():
    # A transparent texel retains its nearest covered neighbour's fill blue.
    # The independent art alpha and green coverage exercise filtered edges.
    for corrected in (False, True):
        for negative in (False, True):
            for blue_byte in (0, 96, 192):
                for art_byte in (64, 192):
                    for u in (.25, .375, .5, .75):
                        weight = min(1., max(0., u * 2 - .5))
                        for alpha_test in (False, True):
                            key = meter_key(corrected, negative, alpha_test)
                            f = copy.deepcopy(shader.fixture(
                                f'hud-meter-{int(corrected)}-{int(negative)}-{blue_byte}-{art_byte}-{u}-{int(alpha_test)}'))
                            f['inputs']['t'][0] = [u, .5, 0, 1]
                            f['textures'][0] = dict(kind=1, width=2, height=1, linear=True,
                                clamp_axes=3, rgba=[blue_byte, 0, blue_byte, 0,
                                                  blue_byte, 255, blue_byte, art_byte])
                            f['uniforms']['c0'][:4] = [MINIMUM, MINIMUM, MINIMUM, BACKGROUND]
                            f['uniforms']['c1'][:4] = [MAXIMUM[:3] + [32 / 255], MAXIMUM, FLASH, TINT]
                            source = meter_reference(blue_byte / 255, weight, weight * art_byte / 255,
                                                     corrected, negative)
                            f['meter_blend'] = TINT
                            f['clear_color'] = CLEAR
                            f['expected'] = [a * tint + background * source[3]
                                             for a, tint, background in zip(source, TINT, CLEAR)]
                            f['discard'] = (weight == 0 or
                                (alpha_test and math.floor(source[3] * 255 + .5) <= 128))
                            f['source_expected'] = source
                            f['coverage'] = weight
                            yield key, f


def border_fixtures():
    """Authored alpha70 border through the same fractional-mip footprint.

    Each level has a different constant RGBA value. The independent reference
    bilinearly weighs its in-bounds taps, substitutes authored border alpha,
    then interpolates mip levels. GPU expected colors never enter uploads.
    """
    sizes = (8, 4, 2, 1)
    colors = ([17, 51, 85, 119], [34, 68, 102, 136],
              [51, 85, 119, 153], [68, 102, 136, 170])
    mips = [dict(rgba=rgba * (size * size)) for size, rgba in zip(sizes, colors)]
    for trilinear in (False, True):
        for lod in ((0, .5, 1, 1.5, 2, 2.5, 3) if trilinear else (0, 1, 2, 3)):
            for u, v in ((-.125, .5), (0, .5), (.125, .5), (.5, .5),
                         (.875, .875), (1, 1), (1.125, .5)):
                key = shader.PixelKey()
                key.texture_modes = 1
                key.sampler_type[0] = 1
                key.combiner_state[8] = 8
                key.combiner_state[9] = 0x1800
                f = copy.deepcopy(shader.fixture(f'hud-alpha-border-{int(trilinear)}-{lod}-{u}-{v}'))
                f['inputs']['t'][0] = [u, v, 0, 1]
                f['uniforms']['texture_border_color'][0] = [0, 0, 0, 70 / 255]
                f['native_alpha_border_mask'] = 1
                # Native RGBA8 filtering has finite interpolation precision;
                # require error below half of one authored eight-bit code.
                f['float_tolerance'] = .5 / 255
                f['textures'][0] = dict(kind=1, width=8, height=8, linear=True,
                    clamp_axes=0, native_border_axes=3, trilinear=trilinear,
                    lod=lod, mipmaps=mips, alpha_border_companion=True)
                def sampled(level):
                    size = sizes[level]
                    footprint = (shader.clamp(.5 + min(u, 1 - u) * size) *
                                 shader.clamp(.5 + min(v, 1 - v) * size))
                    rgba = [c / 255 for c in colors[level]]
                    return [c * footprint for c in rgba[:3]] + [rgba[3] * footprint +
                        (70 / 255) * (1 - footprint)]
                low, high = math.floor(lod), math.ceil(lod)
                fraction = lod - low
                f['expected'] = [a * (1 - fraction) + b * fraction
                                  for a, b in zip(sampled(low), sampled(high))]
                yield key, f


def sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in
        (Path(__file__).resolve(), METER, HARNESS, ROOT / 'port/linux/src/nv2a_psh.c',
         ROOT / 'port/linux/src/xgpu_msl.h', ROOT / 'port/linux/src/xgpu_shader_standalone.h',
         ROOT / 'port/macos/metal-poc/shader_text.c', ROOT / 'tools/metal_shader_validate.py')}


def consume(out, result):
    manifest_path = out / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest['source_sha256'] != sources():
        raise RuntimeError('HUD proof sources changed; prepare again')
    for name, expected in manifest['shader_sha256'].items():
        if sha(out / name) != expected:
            raise RuntimeError('Prepared HUD shader changed: ' + name)
    if (result['manifest_sha256'] != sha(manifest_path) or
        result['runner_sha256'] != manifest['runner_sha256'] or
        sha(out / 'shader_validate') != manifest['runner_sha256'] or
        result['pixel_cases'] != len(manifest['pixel_tests']) or
        result['compiled'] != len(manifest['compile'])):
        raise RuntimeError('HUD GPU result does not match prepared fixture')
    result.update(passed=True, source_sha256=manifest['source_sha256'],
        limits=['Synthetic filtered texels and original meter shader/blend only; no live HUD placement or retail Xbox visual parity proof'])
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/metal-poc/hud-hires-validation')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--gpu-result', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.gpu_result:
        consume(out, json.loads(args.gpu_result.read_text()))
        return
    before = sources()
    library = shader.build_library(out)
    names, compiled, tests = {}, [], []
    library.nv2a_pixel_shader_to_msl_with_options.argtypes = [C.POINTER(shader.PixelKey), C.c_void_p]
    for key, f in itertools.chain(hud_fixtures(), border_fixtures()):
        mask = f.get('native_alpha_border_mask', 0)
        identity = (bytes(key), mask)
        if identity not in names:
            name = f'pixel-{len(names):02}.metal'
            source = (shader.generated(library.nv2a_pixel_shader_to_msl_with_options,
                        C.byref(key), C.byref(AlphaBorderOptions(2, 0, mask))) if mask else
                      shader.generated(library.nv2a_pixel_shader_to_msl, C.byref(key)))
            if source is None:
                raise RuntimeError('Original HUD meter key unsupported')
            (out / name).write_text(source)
            names[identity] = name
            compiled.append(name)
        f['shader'] = names[identity]
        tests.append(f)
    executable = out / 'shader_validate'
    shader.run('xcrun', 'clang++', '-std=c++17', '-O2', '-fobjc-arc', '-Wall', '-Wextra',
               HARNESS, '-framework', 'Foundation', '-framework', 'Metal', '-o', executable)
    shader.run('codesign', '--force', '--sign', '-', executable)
    if before != sources():
        raise RuntimeError('HUD proof sources changed during preparation')
    manifest = out / 'manifest.json'
    manifest.write_text(json.dumps(dict(compile=compiled, pixel_tests=tests,
        shader_sha256={name: sha(out / name) for name in compiled},
        runner_sha256=sha(executable), source_sha256=before), indent=2) + '\n')
    if args.prepare_only:
        print(json.dumps(dict(executable=str(executable), manifest=str(manifest),
                              pixel_cases=len(tests)), indent=2))
    else:
        consume(out, json.loads(shader.run(executable, manifest).stdout))


if __name__ == '__main__':
    main()
