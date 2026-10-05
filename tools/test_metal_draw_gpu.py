#!/usr/bin/env python3
"""Independent attachment/state checks for the native draw replay runner.

Test-only shaders isolate host fetch/raster state from NV2A translation. Expected
pixels come from analytic rectangles and seeded attachments, without rendering
through a second copy of the runner. --prepare and --verify split GPU execution
for hosts where only the native executable needs an explicit GPU permission.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNNER_SOURCE = ROOT / 'port/macos/metal-poc/draw_replay.mm'
WIDTH, HEIGHT = 32, 24


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def payload(folder, filename, raw):
    (folder / filename).write_bytes(raw)
    return dict(file=filename, sha256=digest(raw), size=len(raw))


def shaders(packed):
    # Point size is deliberately present for triangles, matching the real ABI.
    varyings = '''struct V { float4 position [[position]];
        float point_size [[point_size]]; float4 color [[user(xD0)]]; };'''
    position = '''#include <metal_stdlib>
using namespace metal;
''' + varyings + '''
struct I { float4 position [[attribute(0)]];
    ''' + ('uint packed [[attribute(1)]];' if packed else 'float4 color [[attribute(4)]];') + '''
    float4 fixed [[attribute(9)]]; };
vertex V xgpu_vertex(I i [[stage_in]]) {
    V o; o.position = i.position; o.point_size = 1;
    o.color = ''' + ('float4(float(i.packed & 1u), i.fixed.yzw);' if packed else 'i.color;') + '''
    return o;
}
'''
    fragment = '''#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; float4 color [[user(xD0)]]; };
fragment float4 xgpu_fragment(V v [[stage_in]]) { return v.color; }
'''
    return position.encode(), fragment.encode()


def prepare(folder, name):
    folder.mkdir(parents=True, exist_ok=False)
    packed = name == 'packed-top-left-cull'
    vs, ps = shaders(packed)
    # Canonical uniform buffers are present even when the test shader omits them.
    vu = bytearray(3120)
    struct.pack_into('<4f', vu, 3072, 1, -1, 1, 0)
    struct.pack_into('<f', vu, 3104, 1)
    positions = ([(-.75, .75, .5, 1), (-.25, .75, .5, 1),
                  (-.25, .25, .5, 1), (-.75, .25, .5, 1)] if packed else
                 [(-1, 1, .5, 1), (1, 1, .5, 1), (1, -1, .5, 1), (-1, -1, .5, 1)])
    # Packed bits deliberately look nonfinite as float32. D3DCOLOR is BGRA.
    raw = b''.join(struct.pack('<4fI', *p, 0xFFF80001) if packed else
                   struct.pack('<4f4B', *p, 192, 128, 64, 128) for p in positions)
    declaration = dict(packed_mask=2 if packed else 0,
                       elements=[dict(register=0, stream=0, offset=0, type=0x42),
                                 dict(register=1 if packed else 4, stream=0, offset=16,
                                      type=0x16 if packed else 0x40)])
    state = dict(viewport=dict(x=0, y=0, width=WIDTH, height=HEIGHT, znear=0, zfar=1),
                 scissor=dict(x=0, y=0, width=WIDTH, height=HEIGHT),
                 raster=dict(front_face='cw', cull='back' if packed else 'none', fill='solid',
                             depth_bias=0, slope_scale=0, depth_bias_clamp=0),
                 blend=dict(enabled=not packed, source='one', destination='one', operation='add', write_mask=7),
                 depth=dict(enabled=True, write=not packed, compare='less_equal'),
                 stencil=dict(enabled=not packed, compare='equal', reference=1,
                              read_mask=255, write_mask=255, fail='zero',
                              depth_fail='invert', pass_='increment_wrap'))
    state['stencil']['pass'] = state['stencil'].pop('pass_')
    target = dict(width=WIDTH, height=HEIGHT, color_format='rgba8unorm',
                  depth_format='depth32float_stencil8', orientation='top_left',
                  clear_color=[0, 0, 0, 0], clear_depth=1, clear_stencil=0)
    expected_color = bytearray(WIDTH * HEIGHT * 4)
    expected_depth = [1.0] * (WIDTH * HEIGHT)
    expected_stencil = bytearray(WIDTH * HEIGHT)
    if packed:
        # Positive clip Y maps to the top of the Metal attachment. Fixed v9
        # survives the absent stream; packed uint fetch supplies red=1.
        for y in range(3, 9):
            for x in range(4, 12):
                at = y * WIDTH + x
                expected_color[at*4:at*4+3] = bytes([255, 128, 191])
    else:
        seed_color = bytearray()
        seed_depth, seed_stencil = [], bytearray()
        for y in range(HEIGHT):
            for x in range(WIDTH):
                seed_color.extend([3*y, 2*x, 7, 100+x])
                seed_depth.append(.25 if x < 16 else .75)
                seed_stencil.append(0 if y < 12 else 1)
        target.update(initial_color=payload(folder, 'seed-color.bin', seed_color),
                      initial_depth=payload(folder, 'seed-depth.bin', struct.pack('<%df' % len(seed_depth), *seed_depth)),
                      initial_stencil=payload(folder, 'seed-stencil.bin', seed_stencil))
        expected_color[:] = seed_color
        expected_depth[:] = seed_depth
        expected_stencil[:] = seed_stencil
        state['viewport'].update(x=4, y=2, width=24, height=16, znear=.25, zfar=.75)
        state['scissor'].update(x=7, y=4, width=18, height=12)
        for y in range(4, 16):
            for x in range(7, 25):
                at = y * WIDTH + x
                if y < 12:
                    expected_stencil[at] = 0  # stencil fail
                elif x < 16:
                    expected_stencil[at] = 254  # depth fail: invert 1
                else:
                    expected_stencil[at] = 2  # depth+stencil pass
                    expected_depth[at] = .5
                    before = expected_color[at*4:at*4+3]
                    expected_color[at*4:at*4+3] = bytes(min(255, a+b) for a, b in zip(before, [64, 128, 192]))
    fixed = [[0, 0, 0, 1] for _ in range(16)]
    fixed[9] = [.25, .5, .75, 1]
    manifest = dict(schema_version=1, kind='nv2a_draw_replay', source_capture=dict(test=name),
                    source_sha256={str(RUNNER_SOURCE): digest(RUNNER_SOURCE.read_bytes())},
                    shaders=dict(vertex=dict(payload(folder, 'vertex.metal', vs), entry='xgpu_vertex'),
                                 fragment=dict(payload(folder, 'fragment.metal', ps), entry='xgpu_fragment')),
                    uniforms=dict(vertex=payload(folder, 'vertex.bin', vu), pixel=payload(folder, 'pixel.bin', bytes(608))),
                    vertex_declaration=declaration,
                    vertex_streams=[dict(payload(folder, 'stream.bin', raw), stream=0, stride=20, offset=0, first_vertex=0)],
                    fixed_attributes=fixed,
                    draw=dict(primitive='quad', indexed=False, vertex_start=0, vertex_count=4),
                    textures=[None]*4, render_state=state, target=target,
                    limitations=['Synthetic state test; shader translator equivalence is tested separately.'])
    (folder/'replay.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (folder/'expected-color.bin').write_bytes(expected_color)
    (folder/'expected-depth.bin').write_bytes(struct.pack('<%df' % len(expected_depth), *expected_depth))
    (folder/'expected-stencil.bin').write_bytes(expected_stencil)


def prepare_cube(folder):
    """Six standard cube directions sample asymmetric original-face pixels."""
    folder.mkdir(parents=True, exist_ok=False)
    vs = b'''#include <metal_stdlib>
using namespace metal;
struct I { float4 position [[attribute(0)]]; float4 uvFace [[attribute(4)]]; };
struct V { float4 position [[position]]; float2 uv; float face [[flat]]; };
vertex V xgpu_vertex(I i [[stage_in]]) { return {i.position, i.uvFace.xy, i.uvFace.z}; }
'''
    ps = b'''#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; float2 uv; float face [[flat]]; };
fragment float4 xgpu_fragment(V i [[stage_in]], texturecube<float> original [[texture(3)]]) {
    float s = 2*i.uv.x-1, t = 2*i.uv.y-1;
    float3 direction;
    switch (uint(i.face)) {
        case 0: direction=float3(1,-t,-s); break;
        case 1: direction=float3(-1,-t,s); break;
        case 2: direction=float3(s,1,t); break;
        case 3: direction=float3(s,-1,-t); break;
        case 4: direction=float3(s,-t,1); break;
        default: direction=float3(-s,-t,-1); break;
    }
    constexpr sampler exact(filter::nearest, mip_filter::nearest, address::clamp_to_edge);
    return original.sample(exact, direction, level(1));
}
'''
    raw = bytearray()
    for face in range(6):
        left, right = -.75+face*.25, -.5+face*.25
        for x, y, u, v in [(left, .5, 0, 0), (right, .5, 1, 0),
                            (right, -.5, 1, 1), (left, -.5, 0, 1)]:
            raw.extend(struct.pack('<8f', x, y, .5, 1, u, v, face, 1))
    mips = []
    for level, size in enumerate((4, 2, 1)):
        faces = []
        for face in range(6):
            # Level0/2 differ from the tested level; level1 is asymmetric in
            # both axes, so every original face orientation is observable.
            rgba = (b''.join(bytes([face*32, x*64, y*128, 255])
                            for y in range(size) for x in range(size)) if level == 1 else
                    bytes([255, level*64, face*32, 255])*(size*size))
            faces.append(dict(payload(folder, f'cube-{face}-mip{level}.bin', rgba),
                              face=face, bytes_per_row=size*4, bytes_per_image=size*size*4))
        mips.append(dict(level=level, width=size, height=size, faces=faces))
    texture = dict(slot=3, type='cube', pixel_format='rgba8unorm', width=4, height=4,
                   mipmaps=mips, sampler=dict(min_filter='nearest', mag_filter='nearest',
                   mip_filter='nearest', address_u='clamp_to_edge', address_v='clamp_to_edge',
                   address_w='clamp_to_edge', lod_min=0, lod_max=2, max_anisotropy=1))
    state = dict(viewport=dict(x=0, y=0, width=WIDTH, height=HEIGHT, znear=0, zfar=1),
                 scissor=dict(x=0, y=0, width=WIDTH, height=HEIGHT),
                 raster=dict(front_face='cw', cull='back', fill='solid', depth_bias=0,
                             slope_scale=0, depth_bias_clamp=0),
                 blend=dict(enabled=False, source='one', destination='zero', operation='add', write_mask=15),
                 depth=dict(enabled=True, write=True, compare='less_equal'),
                 stencil=dict(enabled=False, compare='always', reference=0, read_mask=255,
                              write_mask=0, fail='keep', depth_fail='keep', **{'pass':'keep'}))
    vu = bytearray(3120)
    struct.pack_into('<4f', vu, 3072, 1, -1, 1, 0)
    struct.pack_into('<f', vu, 3104, 1)
    manifest = dict(schema_version=1, kind='nv2a_draw_replay',
                    source_capture=dict(test='cube-face-orientation-authored-mip'),
                    source_sha256={str(RUNNER_SOURCE):digest(RUNNER_SOURCE.read_bytes())},
                    shaders=dict(vertex=dict(payload(folder, 'vertex.metal', vs), entry='xgpu_vertex'),
                                 fragment=dict(payload(folder, 'fragment.metal', ps), entry='xgpu_fragment')),
                    uniforms=dict(vertex=payload(folder, 'vertex.bin', vu),
                                  pixel=payload(folder, 'pixel.bin', bytes(608))),
                    vertex_declaration=dict(packed_mask=0, elements=[
                        dict(register=0, stream=0, offset=0, type=0x42),
                        dict(register=4, stream=0, offset=16, type=0x42)]),
                    vertex_streams=[dict(payload(folder, 'stream.bin', raw), stream=0,
                                         stride=32, offset=0, first_vertex=0)],
                    fixed_attributes=[[0,0,0,1] for _ in range(16)],
                    draw=dict(primitive='quad', indexed=False, vertex_start=0, vertex_count=24),
                    textures=[None,None,None,texture], render_state=state,
                    target=dict(width=WIDTH,height=HEIGHT,color_format='rgba8unorm',
                                depth_format='depth32float_stencil8',orientation='top_left',
                                clear_color=[0,0,0,0],clear_depth=1,clear_stencil=0),
                    limitations=['Synthetic cube upload/orientation test; original NV2A replay uses generated shaders.'])
    (folder/'replay.json').write_text(json.dumps(manifest,indent=2)+'\n')
    expected_color = bytearray(WIDTH*HEIGHT*4)
    expected_depth = [1.0]*(WIDTH*HEIGHT)
    for face in range(6):
        for y in range(6,18):
            for x in range(4+face*4,8+face*4):
                at=y*WIDTH+x
                expected_color[at*4:at*4+4]=bytes([face*32,((x-4)%4//2)*64,((y-6)//6)*128,255])
                expected_depth[at]=.5
    (folder/'expected-color.bin').write_bytes(expected_color)
    (folder/'expected-depth.bin').write_bytes(struct.pack('<%df'%len(expected_depth),*expected_depth))
    (folder/'expected-stencil.bin').write_bytes(bytes(WIDTH*HEIGHT))


def verify(folder):
    result = json.loads((folder/'native/result.json').read_text())
    manifest = folder/'replay.json'
    assert result['complete'] and result['manifest_sha256'] == digest(manifest.read_bytes())
    errors = {}
    for field in ('color', 'depth', 'stencil'):
        desc = result[field]
        raw = (folder/'native'/desc['file']).read_bytes()
        assert digest(raw) == desc['sha256']
        expected = (folder/f'expected-{field}.bin').read_bytes()
        assert len(raw) == len(expected)
        if field == 'depth':
            a = struct.unpack('<%df' % (len(raw)//4), raw)
            b = struct.unpack('<%df' % (len(expected)//4), expected)
            errors[field] = max(abs(x-y) for x, y in zip(a, b))
        else:
            errors[field] = max(abs(x-y) for x, y in zip(raw, expected))
    if folder.name == 'bc1-cube-six-faces-five-authored-mips':
        # BC1 interpolation is not exactly ideal8-bit thirds on this GPU.
        # Keep the analytic discrepancy visible; exact ANGLE attachment
        # equality is an independent working-port gate, with no tolerance.
        actual = (folder/'native/color.rgba').read_bytes()
        ideal = (folder/'expected-color.bin').read_bytes()
        reference = (folder/'angle/color.rgba').read_bytes()
        angle = json.loads((folder/'angle/result.json').read_text())
        assert angle['manifest_sha256'] == digest(manifest.read_bytes())
        assert angle['color_sha256'] == digest(reference)
        assert len(actual) == len(ideal) == len(reference) and actual == reference
        assert all(x == y for at,(x,y) in enumerate(zip(actual,ideal))
                   if at % 4 == 3 or y in (0,255)), 'BC1 endpoint/alpha/coverage mismatch'
        assert errors['depth'] == 0 and errors['stencil'] == 0
        provenance = json.loads((folder/'angle-provenance.json').read_text())
        for name,expected in provenance['source_sha256'].items():
            assert digest(Path(name).read_bytes()) == expected, 'ANGLE fixture source changed'
        assert provenance['runner_sha256'] == angle['runner_sha256'] == digest((folder/'cube_glsl_validate').read_bytes())
        return dict(case=folder.name, passed=True, native_angle_maximum_error=0,
                    independent_ideal_palette_maximum_error=errors['color'],
                    independent_endpoints_alpha_coverage_passed=True,
                    depth_stencil_maximum_error={k:errors[k] for k in ('depth','stencil')},
                    manifest_sha256=result['manifest_sha256'],
                    limits=['Exact working ANGLE BC1 decode gate; ideal third-color rounding differs.',
                            'Physical Xbox BC1 decode precision remains unverified.'])
    assert errors == dict(color=0, depth=0.0, stencil=0), (folder.name, errors)
    return dict(case=folder.name, maximum_error=errors, passed=True,
                manifest_sha256=result['manifest_sha256'], result_sha256=digest((folder/'native/result.json').read_bytes()))


def prepare_bc1_cube(folder):
    """Captured-size BC1 cube: six oriented faces and five authored mip levels.

    RGB endpoints are exact primary channels, so four-color interpolation
    yields integer85/170 and no tolerance can hide a decode discrepancy.
    Face5 also samples the transparent selector of BC1's three-color mode.
    """
    prepare_cube(folder)
    manifest = json.loads((folder/'replay.json').read_text())
    source = (folder/'fragment.metal').read_text()
    source = source.replace('texturecube<float> original [[texture(3)]])',
                            'texturecube<float> original [[texture(3)]], sampler authored [[sampler(3)]])')
    source = source.replace('float s = 2*i.uv.x-1, t = 2*i.uv.y-1;',
                            'float lod = min(floor(i.uv.y*5), 4.0);\n    float s = 2*i.uv.x-1, t = 2*fract(i.uv.y*5)-1;')
    source = source.replace('constexpr sampler exact(filter::nearest, mip_filter::nearest, address::clamp_to_edge);\n    return original.sample(exact, direction, level(1));',
                            'return original.sample(authored, direction, level(lod));')
    manifest['shaders']['fragment'] = dict(payload(folder,'fragment.metal',source.encode()),entry='xgpu_fragment')
    endpoints = [(0xf800,(255,0,0)), (0x07e0,(0,255,0)), (0x001f,(0,0,255)),
                 (0xffe0,(255,255,0)), (0xf81f,(255,0,255))]
    def sample(face,level,x,y,size):
        selector = ((x*4//size) + 2*(y*4//size) + face + level) & 3
        if face == 5:
            selector = (0,1,3,1)[selector]
            return selector, (0,0,0,0) if selector==3 else ((255,255,255,255) if selector==1 else (0,0,0,255))
        rgb = endpoints[(face+level)%len(endpoints)][1]
        numerator = (3,0,2,1)[selector]
        return selector, tuple(channel*numerator//3 for channel in rgb)+(255,)
    mips = []
    for level,size in enumerate((64,32,16,8,4)):
        faces = []
        for face in range(6):
            raw = bytearray()
            for block_y in range(size//4):
                for block_x in range(size//4):
                    selectors = sum(sample(face,level,block_x*4+x,block_y*4+y,size)[0] << (2*(y*4+x))
                                    for y in range(4) for x in range(4))
                    c0,c1 = (0,0xffff) if face==5 else (endpoints[(face+level)%len(endpoints)][0],0)
                    raw.extend(struct.pack('<HHI',c0,c1,selectors))
            row=(size//4)*8
            faces.append(dict(payload(folder,f'bc1-face{face}-mip{level}.bin',raw),
                              face=face,bytes_per_row=row,bytes_per_image=row*(size//4)))
        mips.append(dict(level=level,width=size,height=size,faces=faces))
    texture = manifest['textures'][3]
    texture.update(pixel_format='bc1_rgba',width=64,height=64,mipmaps=mips)
    texture['sampler']['lod_max'] = 4
    manifest['source_capture']['test'] = 'bc1-cube-six-faces-five-authored-mips'
    manifest['limitations'] = ['Independent synthetic BC1 cube decoding/orientation/mip test; no physical Xbox sampling claim.']
    (folder/'replay.json').write_text(json.dumps(manifest,indent=2)+'\n')
    color = bytearray(WIDTH*HEIGHT*4)
    for face in range(6):
        for y in range(6,18):
            v=(y-6+.5)/12
            level=min(int(v*5),4);local_v=v*5-level;size=64>>level
            for x in range(4+face*4,8+face*4):
                u=(x-4-face*4+.5)/4
                rgba=sample(face,level,int(u*size),int(local_v*size),size)[1]
                color[(y*WIDTH+x)*4:(y*WIDTH+x)*4+4]=bytes(rgba)
    (folder/'expected-color.bin').write_bytes(color)


def build_cube_angle(folder):
    """Pin an independent ANGLE compressed-cube test executable and libraries."""
    dependencies = ROOT if (ROOT/'build/macos/angle/dist').exists() else ROOT.parent/'pfista-halo-macos'
    base = dependencies/'build/macos'
    frameworks = [base/'angle/dist/EGL.xcframework/macos-arm64',
                  base/'angle/dist/GLESv2.xcframework/macos-arm64']
    source = ROOT/'port/macos/metal-poc/cube_glsl_validate.mm'
    paths = [source,Path(__file__).resolve(),
             frameworks[0]/'libEGL.framework/libEGL',frameworks[1]/'libGLESv2.framework/libGLESv2']
    hashes = {str(path):digest(path.read_bytes()) for path in paths}
    runner = folder/'cube_glsl_validate'
    command = ['xcrun','clang++','-std=c++17','-fobjc-arc','-O2','-Wall','-Wextra','-Werror',str(source),
               '-I'+str(base/'toolchain/gl'),'-framework','Foundation','-framework','libEGL','-framework','libGLESv2',
               '-o',str(runner)]
    for path in frameworks: command.extend(['-F',str(path),'-Wl,-rpath,'+str(path)])
    subprocess.run(command,check=True)
    assert hashes == {str(path):digest(path.read_bytes()) for path in paths}, 'ANGLE fixture sources changed during build'
    (folder/'angle-provenance.json').write_text(json.dumps(dict(source_sha256=hashes,
                    runner_sha256=digest(runner.read_bytes())),indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    folder = args.output.resolve()
    if not args.verify:
        folder.mkdir(parents=True, exist_ok=False)
        for case in ('seeded-depth-stencil-blend', 'packed-top-left-cull'):
            prepare(folder/case, case)
        prepare_cube(folder/'cube-face-orientation-authored-mip')
        prepare_bc1_cube(folder/'bc1-cube-six-faces-five-authored-mips')
        build_cube_angle(folder/'bc1-cube-six-faces-five-authored-mips')
        if args.prepare:
            print(json.dumps(dict(packages=[str(p/'replay.json') for p in folder.iterdir()]), indent=2))
            return
        runner = folder/'draw-replay'
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-O2', '-mmacosx-version-min=13.0',
                        str(RUNNER_SOURCE), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(runner)], check=True)
        for case in folder.iterdir():
            if case.is_dir():
                subprocess.run([str(runner), str(case/'replay.json'), str(case/'native')], check=True, stdout=subprocess.DEVNULL)
                if case.name == 'bc1-cube-six-faces-five-authored-mips':
                    subprocess.run([str(case/'cube_glsl_validate'),str(case/'replay.json'),str(case/'angle')],check=True)
    summary = [verify(case) for case in folder.iterdir() if case.is_dir()]
    (folder/'validation.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
