#!/usr/bin/env python3
"""Numerically validate Xbox microcode on Metal without booting Halo.

Expected vectors come from independent opcode arithmetic. The compute wrapper
only removes shader stage annotations to expose the emitted vertex calculation;
real render tests additionally verify pixel centers, screen Y and 0..1 depth.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import re

from metal_shader_validate import ROOT, PORT, generated, run
from test_metal_vertex_shader import instruction


OUTPUT_INDEX = dict(position=0, point_fog=1, d0=2, d1=3, b0=4, b1=5,
                    t0=6, t1=7, t2=8, t3=9)


def default_fixture(name, words, expected, packed_mask=0):
    scale, offset = [4., -4., 1., 0.], [4., 4., 0., 0.]
    constants = [[.2, .3, .4, .5] for _ in range(192)]
    constants[58], constants[59] = scale, offset
    return dict(name=name, words=words, packed_mask=packed_mask,
                attributes=[[0., 0., 0., 1.] for _ in range(16)], packed_attributes={},
                uniforms=dict(c=constants, viewport_scale=scale, viewport_offset=offset,
                              point_size=1., screen_offset=0.), expected=expected)


def setup_operands():
    return (instruction(a=(3, 0), constant=70, temporary=3, output_mask=0, end=False) +
            instruction(a=(3, 0), constant=71, temporary=2, output_mask=0, end=False))


def numerical_fixtures():
    a, b, c = [.2, -.3, .7, 1.2], [.6, .4, -.2, .9], [.3, -.1, .5, .8]
    for opcode in range(14):
        if opcode == 0:
            result = [0., 0., 0., 1.]
        elif opcode in (1, 13):
            result = a
        elif opcode == 2:
            result = [x * y for x, y in zip(a, b)]
        elif opcode == 3:
            result = [x + y for x, y in zip(a, c)]
        elif opcode == 4:
            result = [x * y + z for x, y, z in zip(a, b, c)]
        elif opcode in (5, 6, 7):
            value = sum(x * y for x, y in zip(a[:3 if opcode != 7 else 4], b))
            if opcode == 6:
                value += b[3]
            result = [value] * 4
        elif opcode == 8:
            result = [1., a[1] * b[1], a[2], b[3]]
        elif opcode == 9:
            result = [min(x, y) for x, y in zip(a, b)]
        elif opcode == 10:
            result = [max(x, y) for x, y in zip(a, b)]
        elif opcode == 11:
            result = [float(x < y) for x, y in zip(a, b)]
        else:
            result = [float(x >= y) for x, y in zip(a, b)]
        words = setup_operands() + instruction(opcode, a=(2, 0), b=(1, 3), c=(1, 2), output=9)
        f = default_fixture(f'mac-{opcode}', words, dict(t0=result))
        f['attributes'][7] = a
        f['uniforms']['c'][70], f['uniforms']['c'][71] = b, c
        yield f
    # Each scalar unit reads C.x except LIT, whose vector components are used.
    for opcode, value in [(op, -.37 if op == 5 else -3.2 if op == 6 else .3)
                          for op in range(1, 8)] + [(3, 1e-22), (3, -1e-22)]:
        source = [value, .4, .6, 2.]
        if opcode == 1:
            result = source
        elif opcode in (2, 3):
            reciprocal = 1. / value
            if opcode == 3:
                reciprocal = (min(max(reciprocal, 5.42101e-20), 1.884467e19) if value > 0
                              else min(max(reciprocal, -1.884467e19), -5.42101e-20))
            result = [reciprocal] * 4
        elif opcode == 4:
            result = [1. / math.sqrt(abs(value))] * 4
        elif opcode == 5:
            result = [2. ** math.floor(value), value - math.floor(value), 2. ** value, 1.]
        elif opcode == 6:
            exponent = math.floor(math.log2(abs(value)))
            result = [exponent, abs(value) / 2. ** exponent, math.log2(abs(value)), 1.]
        else:
            result = [1., max(source[0], 0.), source[1] ** source[3], 1.]
        f = default_fixture(f'ilu-{opcode}-{value}',
                            instruction(0, opcode, c=(2, 0), output=9, output_from_ilu=True), dict(t0=result))
        f['attributes'][7] = source
        yield f
    # A MAC and ILU in one instruction both read the previous registers; the
    # ILU result goes to r1 even when the MAC writes r2.
    words = (instruction(a=(3, 0), constant=70, temporary=1, output_mask=0, end=False) +
             instruction(a=(3, 0), constant=71, temporary=2, output_mask=0, end=False) +
             instruction(3, 1, a=(1, 1), c=(1, 2), temporary=2, output_mask=0, end=False) +
             instruction(3, a=(1, 1), c=(1, 2), output=9))
    f = default_fixture('parallel-register-writes', words, dict(t0=[x + 2*y for x, y in zip(b, c)]))
    f['uniforms']['c'][70], f['uniforms']['c'][71] = b, c
    yield f
    f = default_fixture('address-register-relative-constant',
                        instruction(13, a=(2, 0), output_mask=0, end=False) +
                        instruction(a=(3, 0), constant=70, relative=True, output=9), dict(t0=b))
    f['attributes'][7][0] = 3.25
    f['uniforms']['c'][73] = b
    yield f
    for components in [(-256, 512, -128), (-1024, -1024, -512), (1023, 1023, 511)]:
        x, y, z = components
        packed = (x & 2047) | ((y & 2047) << 11) | ((z & 1023) << 22)
        f = default_fixture(f'normpacked3-{x}-{y}-{z}', instruction(vertex=1, output=9),
                            dict(t0=[x/1023., y/1023., z/511., 1.]), packed_mask=14)
        f['packed_attributes']['1'] = packed
        yield f
    f = default_fixture('color-clamp', instruction(output=3), dict(d0=[0., .4, 1., .8]))
    f['attributes'][7] = [-.25, .4, 1.6, .8]
    yield f
    f = default_fixture('screen-half-pixel-fallback', instruction(),
                        dict(position=[(5.25+.625-8)/8*2, (7.25+.5-6)/-6*2, .6*2, 2.]))
    f['attributes'][7] = [5.25, 7.25, .6, 2.]
    f['uniforms']['viewport_scale'] = [8., -6., 1., 0.]
    f['uniforms']['viewport_offset'] = [8., 6., 0., 0.]
    f['uniforms']['screen_offset'] = .125
    yield f
    # The known Xbox viewport suffix. Near-zero W checks that preserving the
    # original clip position avoids reconstructing it from the clamped RCC.
    for w in (2., 1e-22):
        words = (instruction(end=False) +
                 instruction(0, 3, c=(1, 12), c_swizzle=(3, 3, 3, 3), temporary=1,
                             output_mask=0, end=False) +
                 instruction(2, a=(1, 12), b=(3, 0), constant=58, mac_mask=0,
                             output_mask=14, end=False) +
                 instruction(4, a=(1, 12), b=(1, 1), c=(3, 0), constant=59,
                             mac_mask=0, output_mask=14))
        f = default_fixture(f'captured-rcc-{w}', words,
                            dict(position=[.25 + .5*w/4, -.75 + .5*w/-4, .4, w]))
        f['attributes'][7] = [.25, -.75, .4, w]
        yield f


def as_compute(source, packed_mask):
    # Test-only entry adaptation. Arithmetic/helper text remains the generated
    # Xbox emitter output; no renderer uses this transformation.
    source = re.sub(r'\[\[.*?\]\]', '', source)
    source = source.replace('vertex XgpuVaryings xgpu_vertex(', 'XgpuVaryings xgpu_vertex(')
    assignments = []
    for index in range(16):
        if packed_mask & (1 << index):
            assignments.append(f'input.v{index}_packed = as_type<uint>(attributes[{index}].x);')
        else:
            assignments.append(f'input.v{index}_in = attributes[{index}];')
    return source + '''
kernel void validate_vertex(constant float4 *attributes [[buffer(0)]],
                            constant XgpuVertexUniforms &uniforms [[buffer(1)]],
                            device float4 *result [[buffer(2)]]) {
    XgpuVertexInput input;
''' + '\n'.join(assignments) + '''
    XgpuVaryings output = xgpu_vertex(input, uniforms);
    result[0]=output.position; result[1]=float4(output.point_size,output.xFog,0,0);
    result[2]=output.xD0;result[3]=output.xD1;result[4]=output.xB0;result[5]=output.xB1;
    result[6]=output.xT0;result[7]=output.xT1;result[8]=output.xT2;result[9]=output.xT3;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/metal-poc/vertex-validation')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--gpu-result', type=Path)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    library_path = out/'native-vertex.dylib'
    run('clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
        '-DXGPU_SHADER_STANDALONE=1', '-DHALO_ANDROID=1', '-I', PORT,
        PORT/'nv2a_vsh.c', ROOT/'port/macos/metal-poc/shader_text.c', '-o', library_path)
    lib = C.CDLL(str(library_path), use_errno=True)
    lib.nv2a_vertex_shader_to_msl.argtypes = [C.POINTER(C.c_uint32), C.c_ulong, C.c_ulong]
    lib.nv2a_vertex_shader_to_msl.restype = C.c_void_p
    fixtures = []
    for index, f in enumerate(numerical_fixtures()):
        words = f.pop('words')
        data = (C.c_uint32 * len(words))(*words)
        source = generated(lib.nv2a_vertex_shader_to_msl, data, len(words)//4, f['packed_mask'])
        if source is None:
            raise RuntimeError(f'{f["name"]}: unsupported microcode, errno {C.get_errno()}')
        name = f'vertex-numeric-{index:02}.metal'
        (out/name).write_text(as_compute(source, f['packed_mask']))
        f['shader'] = name
        f['expected'] = {str(OUTPUT_INDEX[field]): vector for field, vector in f['expected'].items()}
        fixtures.append(f)
    render_tests = []
    for row, column, depth, w in [(1, 2, .25, 1.), (6, 5, .75, 2.)]:
        f = default_fixture(f'screen-position-{column}-{row}-{depth}', instruction(vertex=0), {})
        f['attributes'][0] = [column, row, depth, w]
        words = f.pop('words');data = (C.c_uint32 * len(words))(*words)
        source = generated(lib.nv2a_vertex_shader_to_msl, data, len(words)//4, 0)
        name = f'vertex-render-{len(render_tests)}.metal';(out/name).write_text(source)
        f['shader'] = name; f['pixel'] = [column, row];f['expected'] = [column+.5, row+.5, depth, 1.]
        render_tests.append(f)
    manifest = out/'manifest.json'
    manifest.write_text(json.dumps(dict(numerical=fixtures, render=render_tests), indent=2)+'\n')
    executable = out/'vertex_validate'
    run('xcrun', 'clang++', '-std=c++17', '-O2', '-fobjc-arc', '-Wall', '-Wextra',
        ROOT/'port/macos/metal-poc/vertex_validate.mm', '-framework', 'Foundation',
        '-framework', 'Metal', '-o', executable)
    run('codesign', '--force', '--sign', '-', executable)
    if args.prepare_only:
        print(json.dumps(dict(executable=str(executable), manifest=str(manifest),
                              numerical_cases=len(fixtures), render_cases=len(render_tests)), indent=2));return
    result = json.loads(args.gpu_result.read_text() if args.gpu_result else run(executable, manifest).stdout)
    if result['numerical_cases'] != len(fixtures) or result['render_cases'] != len(render_tests):
        raise RuntimeError('GPU result does not cover the current fixture manifest')
    result['source_sha256'] = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (PORT/'nv2a_vsh.c', PORT/'xgpu_msl.h')}
    result['limits'] = ['synthetic bounded inputs, not a complete game frame',
                         'independent opcode arithmetic, not a physical Xbox capture',
                         'no whole-frame performance or gameplay parity conclusion']
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
