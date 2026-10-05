"""Independent arithmetic fixtures for direct NV2A Metal pixel behavior.

These exercise shader semantics separately from emitted source. Corrected
behaviors follow NV2A state interpretation checked against the xemu primary
implementation; physical Xbox image/timing comparison remains a separate gate.
"""

import copy
import math
import sys
import struct

# A CLI run names the validator module __main__; using that same ctypes class
# avoids importing a second, structurally identical but incompatible PixelKey.
active = sys.modules.get('__main__')
if getattr(active, '__file__', '').endswith('metal_shader_validate.py'):
    PixelKey, fixture = active.PixelKey, active.fixture
else:
    try:
        from tools.metal_shader_validate import PixelKey, fixture
    except ModuleNotFoundError:
        from metal_shader_validate import PixelKey, fixture


def clamp(value):
    return min(1.0, max(0.0, value))


def signed_byte(byte):
    return (byte if byte < 128 else byte - 256) / 127.0


def select_output(key, stage):
    key.combiner_state[8] = 8 + stage
    key.combiner_state[9] = (0x18 + stage) << 8


def texture(pixels, width=1, height=1):
    return dict(kind=1, width=width, height=height, rgba=pixels,
                linear=False, clamp_axes=0)


def fresh(name):
    # Original fixture intentionally reuses immutable nested defaults; these
    # additions mutate values so isolate every fixture before doing so.
    return copy.deepcopy(fixture(name))


def cube_texture():
    # Every face/column/row has a distinct value, so checking a face alone
    # cannot conceal a swapped axis or an inverted texture coordinate.
    return dict(kind=3, width=4, height=4, linear=False, clamp_axes=7,
                faces=[[component for y in range(4) for x in range(4)
                        for component in (17 + face * 31 + x * 11,
                                          23 + face * 23 + y * 17,
                                          31 + (x + y) * 19, 127 + face * 7)]
                       for face in range(6)])


def cube_nearest(texture, direction):
    # Standard cube-map face selection and (sc,tc,ma) projection. This CPU
    # reference never reads emitted shader text. Directions avoid face ties.
    x, y, z = direction
    axis = max(range(3), key=lambda i: abs(direction[i]))
    if axis == 0:
        face, sc, tc = (0, -z, -y) if x > 0 else (1, z, -y)
    elif axis == 1:
        face, sc, tc = (2, x, z) if y > 0 else (3, x, -z)
    else:
        face, sc, tc = (4, x, -y) if z > 0 else (5, -x, -y)
    ma = abs(direction[axis])
    u, v = (sc / ma + 1) / 2, (tc / ma + 1) / 2
    ix = min(texture['width'] - 1, max(0, math.floor(u * texture['width'])))
    iy = min(texture['height'] - 1, max(0, math.floor(v * texture['height'])))
    start = (iy * texture['width'] + ix) * 4
    return [value / 255 for value in texture['faces'][face][start:start + 4]]


def dot_mapped_bytes(rgba, mapping):
    # The three signed variants intentionally differ at 0x7f/0x80. Keep the
    # reference in byte units instead of using the emitter's helper functions.
    if mapping == 0:
        return [byte / 255 for byte in rgba[:3]]
    if mapping == 1:
        return [(byte - 128) / 127 for byte in rgba[:3]]
    if mapping == 2:
        return [(byte + .5 if byte < 128 else byte - 255.5) / 127.5
                for byte in rgba[:3]]
    return [(byte if byte < 128 else byte - 256) / 127 for byte in rgba[:3]]


def dot_rows(mapped, desired):
    # Non-diagonal rows require all three mapped channels to participate. The
    # result is deliberately away from texel edges to avoid rounding ambiguity.
    return [[(value - .125 * mapped[1] + .25 * mapped[2]) / mapped[0],
             .125, -.25] for value in desired]


def reflect_vector(normal, eye):
    # Reflect the eye across the plane perpendicular to the normal. Reflecting
    # twice restores the original vector even when normal is not unit length.
    scale = 2 * sum(n * e for n, e in zip(normal, eye)) / sum(n * n for n in normal)
    return [scale * n - e for n, e in zip(normal, eye)]


def texture_stage_fixtures():
    """Cube/volume/dependent DOT cases, including Blood Gulch's 17/11/12 path.

    Reflection/chain semantics are checked against the original game's
    rasterizer_xbox_environment.c:2905-2915 and NVIDIA NV_texture_shader
    sections 3.8.13.1.15/.17-.20. This is independent component coverage,
    not a real-draw or physical-Xbox image comparison.
    """
    directions = [(1, .25, -.625), (-1, .25, -.625),
                  (.25, 1, -.625), (.25, -1, -.625),
                  (.25, -.625, 1), (.25, -.625, -1)]
    cube = cube_texture()
    for face, direction in enumerate(directions):
        key = PixelKey(); key.texture_modes = 3; key.sampler_type[0] = 3
        select_output(key, 0)
        f = fresh(f'cube-direct-face-{face}-axis-orientation')
        f['textures'][0] = cube
        # Cube coordinates ignore Q and 2D texture_scale.
        f['inputs']['t'][0] = [*direction, 7]
        f['uniforms']['texture_scale'][0] = [5, 9, 11, 1]
        f['expected'] = cube_nearest(cube, direction)
        yield key, f

    rgba = [31, 103, 219, 177]
    for mapping in range(4):
        mapped = dot_mapped_bytes(rgba, mapping)
        for face, direction in enumerate(directions):
            for stage2 in (17, 11):
                key = PixelKey()
                key.texture_modes = 1 | (17 << 5) | (stage2 << 10) | (12 << 15)
                key.sampler_type[0] = 1
                key.sampler_type[2] = 3 if stage2 == 11 else 0
                key.sampler_type[3] = 3
                key.combiner_state[55] = mapping * 0x111
                select_output(key, 3)
                f = fresh(f'dot-reflect-{stage2}-mapping-{mapping}-face-{face}')
                f['textures'][0] = texture(rgba)
                f['textures'][3] = cube
                if stage2 == 11:
                    f['textures'][2] = cube
                normal = [.3, -.45, .8]
                # Inverse reflection constructs a nonparallel eye which must
                # yield this independently chosen six-face lookup direction.
                eye = reflect_vector(normal, direction)
                rows = dot_rows(mapped, normal)
                for i in range(3):
                    f['inputs']['t'][i + 1] = rows[i] + [eye[i]]
                f['expected'] = cube_nearest(cube, direction)
                yield key, f
                if stage2 == 11:
                    diffuse_key = copy.copy(key)
                    select_output(diffuse_key, 2)
                    diffuse = copy.deepcopy(f)
                    diffuse['name'] = f'dot-reflect-diffuse-mapping-{mapping}-face-{face}'
                    diffuse['expected'] = cube_nearest(cube, normal)
                    yield diffuse_key, diffuse

            key = PixelKey()
            key.texture_modes = 1 | (17 << 5) | (17 << 10) | (14 << 15)
            key.sampler_type[0] = 1; key.sampler_type[3] = 3
            key.combiner_state[55] = mapping * 0x111
            select_output(key, 3)
            f = fresh(f'dot-str-cube-mapping-{mapping}-face-{face}')
            f['textures'][0] = texture(rgba); f['textures'][3] = cube
            for i, row in enumerate(dot_rows(mapped, direction)):
                f['inputs']['t'][i + 1] = row + [1]
            f['expected'] = cube_nearest(cube, direction)
            yield key, f


    volume = dict(kind=2, width=2, height=2, depth=2, linear=False, clamp_axes=0,
                  rgba=[value for z in range(2) for y in range(2) for x in range(2)
                        for value in (17 + x * 61, 23 + y * 73, 31 + z * 89, 127 + x * 17)])
    for z in range(2):
        for y in range(2):
            for x in range(2):
                coordinates = [(i + .5) / 2 for i in (x, y, z)]
                start = (z * 4 + y * 2 + x) * 4
                expected = [v / 255 for v in volume['rgba'][start:start + 4]]
                key = PixelKey(); key.texture_modes = 2; key.sampler_type[0] = 2
                select_output(key, 0)
                f = fresh(f'project3d-volume-{x}-{y}-{z}-q-divide')
                f['inputs']['t'][0] = [v * 3 for v in coordinates] + [3]
                f['textures'][0] = volume; f['expected'] = expected
                yield key, f
                for mapping in range(4):
                    key = PixelKey()
                    key.texture_modes = 1 | (17 << 5) | (17 << 10) | (13 << 15)
                    key.sampler_type[0] = 1; key.sampler_type[3] = 2
                    key.combiner_state[55] = mapping * 0x111
                    select_output(key, 3)
                    f = fresh(f'dot-str-volume-mapping-{mapping}-{x}-{y}-{z}')
                    f['textures'][0] = texture(rgba); f['textures'][3] = volume
                    for i, row in enumerate(dot_rows(dot_mapped_bytes(rgba, mapping), coordinates)):
                        f['inputs']['t'][i + 1] = row + [1]
                    f['expected'] = expected
                    yield key, f

    pixels = [17, 43, 89, 255, 67, 97, 127, 192,
              151, 173, 199, 128, 211, 229, 251, 64]
    for stage in (2, 3):
        for mapping in range(4):
            key = PixelKey()
            key.texture_modes = 1 | (17 << (5 * (stage - 1))) | (9 << (5 * stage))
            key.sampler_type[0] = key.sampler_type[stage] = 1
            key.combiner_state[55] = mapping << ((stage - 2) * 4) | mapping << ((stage - 1) * 4)
            select_output(key, stage)
            f = fresh(f'dot-st-stage-{stage}-mapping-{mapping}')
            rows = dot_rows(dot_mapped_bytes(rgba, mapping), [.25, .75])
            f['inputs']['t'][stage - 1] = rows[0] + [1]
            f['inputs']['t'][stage] = rows[1] + [1]
            f['textures'][0] = texture(rgba); f['textures'][stage] = texture(pixels, 2, 2)
            f['expected'] = [v / 255 for v in pixels[8:12]]
            yield key, f


def depth_replace_fixtures():
    """Original zsprite 1/1/17/10 state with an explicit raw integer-D24 ABI.

    DOT_ZW is dotP/dotC (NVIDIA NV_texture_shader3.8.13.1.21); the game's
    zsprite constants use raw range16777215 or1e30, transparent_geometry.c
    :1625. Only integer D24 is opted in here. This does not certify physical
    Xbox depth storage/quantization or the GLES fallback, which omits writes.
    """
    f32 = lambda v: struct.unpack('<f', struct.pack('<f', v))[0]
    scale = f32(1 / 16777215)
    cases = [(z, w, 0, 1) for z in (-.125, 0, .125, .25, .5, .875, 1, 1.125)
             for w in (.5, 1, 3)]
    cases += [(z, 1, .25, .75) for z in (.2499, .25, .5, .75, .7501)]
    for index, (z, w, near, far) in enumerate(cases):
        key = PixelKey(); key.texture_modes = 0x54421
        key.sampler_type[0] = key.sampler_type[1] = 1
        key.combiner_state[56] = 0x110000
        key.combiner_state[8] = 4; key.combiner_state[9] = 0x1400
        f = fresh(f'dot-zw-raw-d24-{index}-z{z}-w{w}')
        f['depth_contract'] = 'raw_d24'
        f['uniforms'].update(depth_scale=scale, depth_clip_min=near, depth_clip_max=far)
        f['textures'][0] = texture([17, 31, 47, 255])
        f['textures'][1] = texture([64, 128, 255, 255])
        raw_z = f32(z * 16777215 * w)
        f['inputs']['t'][2] = [0, 0, raw_z, 1]
        f['inputs']['t'][3] = [0, 0, w, 1]
        depth = f32(f32(raw_z / f32(w)) * scale)
        f['discard'] = depth < near or depth > far
        f['expected'] = f['inputs']['d0'][:]
        f['expected_depth'] = .9 if f['discard'] else depth
        yield key, f

    # Depth compare and depth-write tests prove the returned replacement value
    # participates in the actual GPU attachment state, after alpha testing.
    for z, write in ((.25, True), (.75, True), (.25, False)):
        f = fresh(f'dot-zw-depth-test-z{z}-write{write}')
        key = PixelKey(); key.texture_modes = 0x54421
        key.sampler_type[0] = key.sampler_type[1] = 1
        key.combiner_state[56] = 0x110000
        key.combiner_state[8] = 4; key.combiner_state[9] = 0x1400
        f['depth_contract'] = 'raw_d24'
        f['uniforms'].update(depth_scale=scale, depth_clip_min=0, depth_clip_max=1)
        f['textures'][0] = f['textures'][1] = texture([0, 0, 255, 255])
        f['inputs']['t'][2] = [0, 0, f32(z * 16777215), 1]
        f['inputs']['t'][3] = [0, 0, 1, 1]
        f['clear_depth'] = .5; f['depth_compare'] = 'less'; f['depth_write'] = write
        f['discard'] = z > .5
        f['expected'] = f['inputs']['d0'][:]
        f['expected_depth'] = f32(f['inputs']['t'][2][2] * scale) if write and z < .5 else .5
        yield key, f

    # Both sampler alpha kill and final alpha test must leave the depth target
    # untouched even though DOT_ZW computed an otherwise passing .25 value.
    for rejection in ('texture-alpha-kill', 'final-alpha-test'):
        key = PixelKey(); key.texture_modes = 0x54421
        key.sampler_type[0] = key.sampler_type[1] = 1
        key.combiner_state[56] = 0x110000
        key.combiner_state[8] = 4; key.combiner_state[9] = 0x1400
        f = fresh(f'dot-zw-discard-{rejection}')
        f['depth_contract'] = 'raw_d24'
        f['uniforms'].update(depth_scale=scale, depth_clip_min=0, depth_clip_max=1,
                             alpha_reference=128)  # Xbox alpha reference is an 8-bit integer
        f['textures'][0] = texture([0, 0, 255, 0])
        f['textures'][1] = texture([0, 0, 255, 255])
        f['inputs']['t'][2] = [0, 0, f32(.25 * 16777215), 1]
        f['inputs']['t'][3] = [0, 0, 1, 1]
        f['inputs']['d0'][3] = .25
        if rejection == 'texture-alpha-kill': key.alpha_kill[0] = 1
        else: key.alpha_test_function = 516  # Xbox D3DCMP_GREATER (0x204)
        f['clear_depth'] = .5; f['depth_compare'] = 'less'; f['depth_write'] = True
        f['discard'] = True; f['expected'] = [0, 0, 0, 0]; f['expected_depth'] = .5
        yield key, f

    # A zero denominator or a missing uniform contract must fail closed at
    # execution even after an explicit emitter opt-in.
    for bad in ('zero-denominator', 'missing-depth-scale'):
        key = PixelKey(); key.texture_modes = 0x54421
        key.sampler_type[0] = key.sampler_type[1] = 1
        key.combiner_state[56] = 0x110000
        f = fresh(f'dot-zw-invalid-{bad}')
        f['depth_contract'] = 'raw_d24'
        f['uniforms'].update(depth_scale=scale if bad == 'zero-denominator' else 0,
                             depth_clip_min=0, depth_clip_max=1)
        f['textures'][0] = f['textures'][1] = texture([0, 0, 255, 255])
        f['inputs']['t'][2] = [0, 0, 16777215, 1]
        f['inputs']['t'][3] = [0, 0, 0 if bad == 'zero-denominator' else 1, 1]
        f['discard'] = True; f['expected'] = [0, 0, 0, 0]; f['expected_depth'] = .9
        yield key, f


def extra_pixel_fixtures():
    yield from texture_stage_fixtures()
    yield from depth_replace_fixtures()
    for alpha in (0, 1, 127, 255):
        key = PixelKey()
        key.texture_modes = 1
        key.sampler_type[0] = 1
        key.alpha_kill[0] = 1
        select_output(key, 0)
        f = fresh(f'alpha-kill-sampled-byte-{alpha}')
        f['textures'][0] = texture([51, 102, 153, alpha])
        f['expected'] = [.2, .4, .6, alpha / 255]
        f['discard'] = alpha == 0
        yield key, f

    # A signed texture component must retain negative values until combiner
    # math. Adding 0.5 makes its effect visible in the final UNORM range.
    rgba = [17, 113, 239, 243]
    for mask in (1, 2, 4, 8, 15):
        key = PixelKey()
        key.texture_modes = 1
        key.sampler_type[0] = 1
        key.color_sign[0] = mask
        key.combiner_state[53] = 1
        key.combiner_state[34] = 0xC8202001
        key.combiner_state[0] = 0xD8202011
        key.combiner_state[45] = key.combiner_state[26] = 0xC00
        f = fresh(f'signed-color-mask-{mask}')
        f['uniforms']['c0'][0] = [.5] * 4
        f['textures'][0] = texture(rgba)
        channel_bits = (2, 4, 8, 1)
        f['expected'] = [clamp((signed_byte(byte) if mask & bit else byte / 255) + .5)
                         for byte, bit in zip(rgba, channel_bits)]
        yield key, f

    key = PixelKey()
    f = fresh('none-texture-initial-alpha-one')
    f['expected'] = [0, 0, 0, 1]
    yield key, f

    key = PixelKey()
    key.texture_modes = 4
    key.color_sign[0] = 15
    key.alpha_kill[0] = 1
    key.combiner_state[53] = 1
    key.combiner_state[34] = 0xC8202001
    key.combiner_state[0] = 0xD8202011
    key.combiner_state[45] = key.combiner_state[26] = 0xC00
    f = fresh('passthru-keeps-signed-range-no-texture-alpha-kill')
    f['uniforms']['c0'][0] = [.5] * 4
    f['inputs']['t'][0] = [-.25, 1.25, .1, 0]
    f['expected'] = [.25, 1, .6, .5]
    yield key, f

    pixels = [17, 43, 89, 255, 67, 97, 127, 192,
              151, 173, 199, 128, 211, 229, 251, 64]
    for selected in (0, 1):
        key = PixelKey()
        key.texture_modes = 4 | (4 << 5) | (6 << 10)
        key.combiner_state[56] = selected << 16
        key.sampler_type[2] = 1
        select_output(key, 2)
        f = fresh(f'bump-selected-input-{selected}-bg-order')
        f['inputs']['t'][0] = [.25, 224 / 255, 32 / 255, 1]
        f['inputs']['t'][1] = [.75, 32 / 255, 224 / 255, 1]
        f['inputs']['t'][2] = [.5, .5, 0, 1]
        f['uniforms']['bump_matrix'][2] = [.5, .25, -.25, .75]
        f['textures'][2] = texture(pixels, 2, 2)
        # Opposite B/G displacements choose top-right versus bottom-left.
        index = 1 if selected == 0 else 2
        f['expected'] = [v / 255 for v in pixels[index * 4:index * 4 + 4]]
        yield key, f

    key = PixelKey()
    key.texture_modes = 1 | (6 << 10)
    key.sampler_type[0] = key.sampler_type[2] = 1
    key.color_sign[0] = 8
    select_output(key, 2)
    f = fresh('bump-already-signed-blue-converts-once')
    f['textures'][0] = texture([64, 0, 224, 255])
    f['inputs']['t'][2] = [.5, .25, 0, 1]
    f['uniforms']['bump_matrix'][2] = [.6, 0, 0, 0]
    f['textures'][2] = texture(pixels, 4, 1)
    u = .5 + .6 * signed_byte(224)
    index = math.floor(u * 4)
    f['expected'] = [v / 255 for v in pixels[index * 4:index * 4 + 4]]
    yield key, f

    for selected in (0, 1):
        key = PixelKey()
        key.texture_modes = 4 | (4 << 5) | (7 << 10)
        key.combiner_state[56] = selected << 16
        key.sampler_type[2] = 1
        select_output(key, 2)
        f = fresh(f'bump-luminance-input-{selected}-rgba-no-factor-clamp')
        f['inputs']['t'][0] = [.25, 0, 0, 1]
        f['inputs']['t'][1] = [.75, 0, 0, 1]
        f['uniforms']['bump_luminance'][2] = [2, .25, 0, 0]
        rgba = [51, 102, 17, 64]
        f['textures'][2] = texture(rgba)
        factor = 2 * f['inputs']['t'][selected][0] + .25
        f['expected'] = [clamp(v / 255 * factor) for v in rgba]
        yield key, f

    for mode in (15, 16):
        for selected in (0, 1, 2):
            key = PixelKey()
            key.texture_modes = 4 | (4 << 5) | (4 << 10) | (mode << 15)
            key.combiner_state[56] = selected << 20
            key.sampler_type[3] = 1
            select_output(key, 3)
            f = fresh(f'dependent-mode-{mode}-input-{selected}')
            f['inputs']['t'][:3] = [[.25, .75, .25, .75], [.75, .25, .75, .25], [.25, .25, .25, .25]]
            f['textures'][3] = texture(pixels, 2, 2)
            source = f['inputs']['t'][selected]
            u, v = (source[3], source[0]) if mode == 15 else (source[1], source[2])
            index = math.floor(u * 2) + math.floor(v * 2) * 2
            f['expected'] = [p / 255 for p in pixels[index * 4:index * 4 + 4]]
            yield key, f

    key = PixelKey()
    key.texture_modes = 1
    key.sampler_type[0] = 1
    select_output(key, 0)
    f = fresh('project2d-w-divide-linear-texture-scale')
    f['inputs']['t'][0] = [.75, 1.5, 0, 3]
    f['uniforms']['texture_scale'][0] = [2, .5, 1, 1]
    f['textures'][0] = texture(pixels, 2, 2)
    f['expected'] = [v / 255 for v in pixels[4:8]]
    yield key, f

    for x in (-.2, 0, .2):
        key = PixelKey()
        key.texture_modes = 5
        key.combiner_state[42] = 5
        key.combiner_state[8] = 1
        key.combiner_state[9] = 0x1100
        f = fresh(f'clipplane-positive-compare-boundary-{x}')
        f['inputs']['t'][0] = [x, .3, -.4, 1]
        f['discard'] = x >= 0
        f['expected'] = f['uniforms']['final_c0']
        yield key, f

    # A final SUM input greater than 1 must remain greater than 1 unless the
    # clampSum bit is set; it can extrapolate the final lerp before output clamp.
    for settings in (0, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0):
        key = PixelKey()
        key.combiner_state[53] = 1
        key.combiner_state[34] = 0x04200000
        key.combiner_state[45] = 0xC0
        key.combiner_state[8] = 0x0E010200
        key.combiner_state[9] = 0x00001400 | settings
        f = fresh(f'final-sum-clamp-complement-flags-{settings}')
        f['inputs']['d0'] = [.8, -.3, .5, .4]
        f['inputs']['d1'] = [.6, .2, -.1, .7]
        f['uniforms']['final_c0'] = [.2, .2, .2, .2]
        f['uniforms']['final_c1'] = [.8, .8, .8, .8]
        # General unsigned input maps negative diffuse components to zero.
        r0 = [max(v, 0) for v in f['inputs']['d0'][:3]]
        v1 = f['inputs']['d1'][:3]
        values = []
        for r, v in zip(r0, v1):
            a = (1 - r if settings & 0x20 else r) + (1 - v if settings & 0x40 else v)
            if settings & 0x80:
                a = clamp(a)
            a = max(a, 0)
            values.append(clamp(a * .2 + (1 - a) * .8))
        f['expected'] = values + [.4]
        yield key, f

    for alpha in (126.75 / 255, 127.25 / 255, 127.75 / 255, 128.75 / 255):
        key = PixelKey()
        key.texture_modes = 4
        key.combiner_state[53] = 1
        key.combiner_state[34] = 0x04200520
        key.combiner_state[45] = 0xC00 | (4 << 12)
        f = fresh(f'mux-lsb-truncates-fractional-byte-{alpha}')
        f['inputs']['t'][0][3] = alpha
        chosen = 'd1' if int(alpha * 255) & 1 else 'd0'
        f['expected'] = f['inputs'][chosen][:3] + [alpha]
        yield key, f
