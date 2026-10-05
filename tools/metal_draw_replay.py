#!/usr/bin/env python3
"""Prepare an actual Xbox draw for direct NV2A-to-Metal replay.

This imports captured resources, never scene tags or replacement geometry.
The native runner consumes the original vertex declaration/stream bytes. VS and
PS are independently emitted and linked through the shared user interpolants.
Unverified resource formats fail closed. No game, GPU or GL runtime is required
to prepare a package.
"""
import argparse
import copy
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import struct

from metal_shader_validate import ROOT, PORT, PixelKey, build_library, generated, load_corpus


class PixelMslOptions(C.Structure):
    _fields_ = [('version', C.c_uint32), ('depth_contract', C.c_uint32)]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def uint(value, bits=32):
    return type(value) is int and 0 <= value < 1 << bits


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    paths = [PORT/'nv2a_vsh.c', PORT/'nv2a_psh.c', PORT/'xgpu_msl.h',
             PORT/'xgpu_shader_standalone.h', PORT/'xbox_textures.c',
             ROOT/'port/macos/metal-poc/shader_text.c', Path(__file__).resolve()]
    paths.append(ROOT/'port/macos/metal-poc/draw_replay.mm')
    return {str(path): sha256(path.read_bytes()) for path in paths}


def vertex_compile_contract(lib, words, vertex, evidence_path, package):
    """Opt in to the pinned working port's source-derived vertex math policy.

    This is a regression contract for ANGLE's Metal backend, not a statement
    about physical NV2A instruction precision. The generated GLSL is retained
    only to prove the flags used by that backend; it is never compiled here.
    """
    evidence_path = evidence_path.resolve()
    raw = evidence_path.read_bytes()
    evidence = json.loads(raw)
    require(evidence.get('kind') == 'angle_shader_evidence' and
            evidence.get('complete') is True and evidence.get('source_revision') == 'c053bf85793b',
            'Unknown original vertex compiler evidence contract')
    flags = evidence.get('evidence', {}).get('compiler_options_inferred_from_pinned_source', {})
    expected = dict(disableFastMath=False, usesInvariance_vertex=True,
                    preserveInvariance_vertex=True, mathMode_ifSDK_andRuntimeMacOS15='Fast',
                    mathFloatingPointFunctions_ifSDK_andRuntimeMacOS15='Fast',
                    legacy_fastMathEnabled=True)
    require(all(type(flags.get(name)) is type(value) and flags[name] == value
                for name, value in expected.items()), 'Original compiler evidence is not invariant fast vertex math')
    pinned_sources = {
        'ProgramMtl.mm': '7d4eab2d9ec9c16ee0ba9acdae980aef3d0552095a2171a9025675add012149a',
        'mtl_utils.mm': '167da7b64935428bf0bdd59b04d765fb72acd4769ebbaab27d665fa70c303065'}
    for name, expected_hash in pinned_sources.items():
        descriptor = evidence.get('source_files', {}).get(name, {})
        source = Path(descriptor.get('file', ''))
        require(source.is_absolute() and descriptor.get('sha256') == expected_hash and
                sha256(source.read_bytes()) == expected_hash, 'Original compiler policy source is stale or unknown')
        package.hashes[str(source)] = expected_hash
    glsl = generated(lib.nv2a_vertex_shader_to_glsl, words,
                     vertex['instruction_count'], vertex['packed_mask'])
    require(glsl is not None and 'invariant gl_Position;' in glsl and
            'isnan' not in glsl and 'isinf' not in glsl,
            'Vertex shader does not satisfy the pinned original fast math flags')
    baseline = package.write('vertex-baseline.glsl', glsl.encode())
    package.hashes[str(evidence_path)] = sha256(raw)
    return (dict(contract='angle_metal_invariant_fast_v1', fast_math=True,
                 preserve_invariance=True, math_mode='fast', floating_point_functions='fast'),
            package.write('vertex-compiler-evidence.json', raw), baseline)


FRAGMENT_FAST_OPTIONS = dict(contract='angle_metal_fast_fragment_v1', fast_math=True,
    preserve_invariance=False, math_mode='fast', floating_point_functions='fast')
PINNED_ANGLE_COMPILER_SOURCES = {
    'ProgramMtl.mm': '7d4eab2d9ec9c16ee0ba9acdae980aef3d0552095a2171a9025675add012149a',
    'mtl_utils.mm': '167da7b64935428bf0bdd59b04d765fb72acd4769ebbaab27d665fa70c303065'}


def validate_fragment_compiler_evidence(raw, baseline, hashes=None):
    """Check the per-stage pinned ANGLE policy and this key's original GLSL.

    Absence of the builtins/invariance is deliberately conservative. The GLSL
    is flag evidence only, never a source for runtime GLSL-to-MSL conversion.
    A dump of another shader alone cannot opt this shader into fast math.
    """
    evidence = json.loads(raw)
    require(evidence.get('kind') == 'angle_shader_evidence' and
            evidence.get('complete') is True and evidence.get('source_revision') == 'c053bf85793b',
            'Unknown original fragment compiler evidence contract')
    flags = evidence.get('evidence', {}).get('compiler_options_inferred_from_pinned_source', {})
    expected = dict(disableFastMath=False, usesInvariance_fragment=False,
        mathMode_ifSDK_andRuntimeMacOS15='Fast',
        mathFloatingPointFunctions_ifSDK_andRuntimeMacOS15='Fast', legacy_fastMathEnabled=True)
    require(all(type(flags.get(name)) is type(value) and flags[name] == value
                for name, value in expected.items()),
            'Original compiler evidence is not noninvariant fast fragment math')
    for name, digest in PINNED_ANGLE_COMPILER_SOURCES.items():
        descriptor = evidence.get('source_files', {}).get(name, {})
        source = Path(descriptor.get('file', ''))
        require(source.is_absolute() and descriptor.get('sha256') == digest and
                source.is_file() and sha256(source.read_bytes()) == digest,
                'Original fragment compiler policy source is stale or unknown')
        if hashes is not None:
            hashes[str(source)] = digest
    glsl = baseline.decode('utf-8')
    require(glsl and 'void main' in glsl and 'isnan' not in glsl and 'isinf' not in glsl and
            'invariant' not in glsl,
            'Fragment shader does not satisfy the pinned original fast math flags')


def fragment_compile_contract(lib, key, evidence_path, package):
    """Opt one emitted fragment key into ANGLE's source-derived fast policy."""
    evidence_path = evidence_path.resolve()
    raw = evidence_path.read_bytes()
    glsl = generated(lib.nv2a_pixel_shader_to_glsl, C.byref(key))
    require(glsl is not None, 'Original fragment baseline cannot be emitted')
    baseline = glsl.encode()
    validate_fragment_compiler_evidence(raw, baseline, package.hashes)
    package.hashes[str(evidence_path)] = sha256(raw)
    return (dict(FRAGMENT_FAST_OPTIONS), package.write('fragment-compiler-evidence.json', raw),
            package.write('fragment-baseline.glsl', baseline))


def fragment_wire_contract(description, load):
    """Validate explicit prepared fragment metadata before encoding PROGRAM."""
    if 'compile_options' not in description:
        require('compiler_evidence' not in description and 'compiler_baseline' not in description,
                'Fragment compiler evidence requires an explicit contract')
        return 0
    policy = description['compile_options']
    require(isinstance(policy, dict) and policy == FRAGMENT_FAST_OPTIONS and
            all(type(policy.get(name)) is type(value) for name, value in FRAGMENT_FAST_OPTIONS.items()),
            'Unverified fragment compiler policy')
    require('compiler_evidence' in description and 'compiler_baseline' in description,
            'Missing pinned fragment compiler evidence')
    validate_fragment_compiler_evidence(load(description['compiler_evidence']),
                                       load(description['compiler_baseline']))
    return 1


def split_uniforms(vertex_constants, draw_uniforms, pixel_depth=None):
    """Repack the captured GL float structs without float round trips.

    draw_uniforms is 159 float32 words (636 bytes) from d3d8_gl.c. The
    destination layouts are the explicitly padded shared xgpu_msl.h ABI.
    Constants preserve the original biased 192-register ordering.
    """
    require(len(vertex_constants) == 3072, 'Vertex constants must be exactly 3072 bytes')
    require(len(draw_uniforms) == 636, 'Captured draw_uniforms must be exactly 636 bytes')
    require(all(math.isfinite(x) for x in struct.unpack('<768f', vertex_constants)),
            'Non-finite vertex constants need explicit replay support')
    require(all(math.isfinite(x) for x in struct.unpack('<159f', draw_uniforms)),
            'Non-finite draw constants need explicit replay support')
    vertex = vertex_constants + draw_uniforms[:36] + draw_uniforms[616:620] + bytes(8)
    depth_fields = bytes(12) if pixel_depth is None else struct.pack('<3f',
        pixel_depth['scale'], pixel_depth['clip_min'], pixel_depth['clip_max'])
    pixel = draw_uniforms[36:360] + depth_fields + draw_uniforms[360:616] + draw_uniforms[620:636]
    assert len(vertex) == 3120 and len(pixel) == 608
    return vertex, pixel


def pixel_depth_contract(capture, key):
    """Explicit captured Xbox D24 coordinates for the opt-in DOT_ZW emitter.

    Never derive original depth semantics from ANGLE's backing texture format.
    F16/F24 encode another raw range and remain unsupported. The original GLES
    DOT_ZW fallback does not write depth; importing this contract therefore
    does not imply parity with that fallback or certify Xbox quantization.
    """
    modes = [key.texture_modes >> (5 * stage) & 31 for stage in range(4)]
    if 10 not in modes:
        require('pixel_depth_contract' not in capture, 'Unexpected pixel depth contract without DOT_ZW')
        return None
    request = capture.get('pixel_depth_contract')
    require(isinstance(request, dict) and request.get('version') == 1 and
            request.get('kind') == 'xbox_raw_d24', 'DOT_ZW needs an explicit captured Xbox D24 contract')
    original = capture.get('original_depth_request')
    require(isinstance(original, dict) and original.get('auto_depth_stencil_format') in (42, 46) and
            uint(original.get('actual_port_surface_format_word')) and
            (original['actual_port_surface_format_word'] >> 8 & 255) in (42, 46) and
            type(original.get('floating_point_zbuffer_byte')) is int and
            original['floating_point_zbuffer_byte'] == 0, 'DOT_ZW original target is not verified integer D24')
    viewport = capture['render_state']['viewport']
    near, far = viewport.get('znear'), viewport.get('zfar')
    require(type(near) in (int, float) and type(far) in (int, float) and
            math.isfinite(near) and math.isfinite(far) and 0 <= near <= far <= 1,
            'DOT_ZW needs the captured original viewport depth bounds')
    return dict(kind='xbox_raw_d24', version=1, raw_range=16777215,
                scale=1 / 16777215, clip_min=near, clip_max=far,
                original_depth_format=original['auto_depth_stencil_format'],
                current_surface_format_word=original['actual_port_surface_format_word'],
                floating_point_zbuffer_byte=0,
                limitations=['original GLES DOT_ZW fallback omits depth replacement',
                             'raw D24 normalization; physical Xbox depth quantization not certified'])


# Xbox format IDs, source element size and the exact existing upload channels.
# P8 requires a captured palette; depth/YUV resource aliases require future
# validation and are rejected instead of inventing an interpretation.
FORMATS = {
    0x00: ('l8', 1, False), 0x01: ('al8', 1, False),
    0x02: ('a1r5g5b5', 2, False), 0x03: ('x1r5g5b5', 2, False),
    0x04: ('a4r4g4b4', 2, False), 0x05: ('r5g6b5', 2, False),
    0x06: ('a8r8g8b8', 4, False), 0x07: ('x8r8g8b8', 4, False),
    0x0b: ('p8', 1, False),
    0x0c: ('bc1_rgba', 8, False), 0x0e: ('bc2_rgba', 16, False), 0x0f: ('bc3_rgba', 16, False),
    0x10: ('a1r5g5b5', 2, True), 0x11: ('r5g6b5', 2, True),
    0x12: ('a8r8g8b8', 4, True), 0x13: ('l8', 1, True),
    0x16: ('r8b8', 2, True), 0x17: ('g8b8', 2, True),
    0x19: ('a8', 1, False), 0x1a: ('a8l8', 2, False),
    0x1b: ('al8', 1, True), 0x1c: ('x1r5g5b5', 2, True),
    0x1d: ('a4r4g4b4', 2, True), 0x1e: ('x8r8g8b8', 4, True),
    0x1f: ('a8', 1, True), 0x20: ('a8l8', 2, True),
    0x27: ('r6g5b5', 2, False), 0x28: ('g8b8', 2, False), 0x29: ('r8b8', 2, False),
    0x32: ('l16', 2, False), 0x33: ('v16u16', 4, False),
    0x35: ('l16', 2, True), 0x36: ('v16u16', 4, True), 0x37: ('r6g5b5', 2, True),
    0x38: ('r5g5b5a1', 2, False), 0x39: ('r4g4b4a4', 2, False),
    0x3a: ('a8b8g8r8', 4, False), 0x3b: ('b8g8r8a8', 4, False), 0x3c: ('r8g8b8a8', 4, False),
    0x3d: ('r5g5b5a1', 2, True), 0x3e: ('r4g4b4a4', 2, True),
    0x3f: ('a8b8g8r8', 4, True), 0x40: ('b8g8r8a8', 4, True), 0x41: ('r8g8b8a8', 4, True),
}


def texture_description(format_word, size_word):
    require(uint(format_word) and uint(size_word), 'Invalid captured texture header')
    fmt = format_word >> 8 & 255
    require(fmt in FORMATS, f'Unsupported captured Xbox texture format 0x{fmt:02x}')
    kind, stride, linear = FORMATS[fmt]
    cube_map = bool(format_word & 4)
    require((format_word >> 4 & 15) != 3,
            'Volume resource layout is not yet validated for draw replay')
    require(not cube_map or (format_word >> 4 & 15) == 2,
            'Cube resource must use the original two-dimensional face header')
    if size_word:
        width, height = (size_word & 4095)+1, (size_word >> 12 & 4095)+1
        levels, pitch, linear = 1, ((size_word >> 24 & 255)+1)*64, True
    else:
        width, height = 1 << (format_word >> 20 & 15), 1 << (format_word >> 24 & 15)
        levels, pitch = max(1, format_word >> 16 & 15), width*stride
    require(width <= 4096 and height <= 4096, 'Texture exceeds replay size limit')
    require(levels <= 1+int(math.log2(max(width, height))), 'Invalid captured mip level count')
    compressed = kind.startswith('bc')
    require(not cube_map or (width == height and not linear),
            'Cube resource requires square swizzled or compressed faces')
    require(not (compressed and size_word), 'Linear compressed resource layout is unsupported')
    require(compressed or pitch >= width*stride, 'Invalid linear texture pitch')
    return dict(width=width, height=height, levels=levels, pitch=pitch,
                linear=linear, compressed=compressed, kind=kind, stride=stride, format=fmt,
                cube_map=cube_map)


def morton_offset(x, y, width, height):
    result, output_bit, bit = 0, 1, 1
    while bit < max(width, height):
        if bit < width:
            if x & bit:
                result |= output_bit
            output_bit <<= 1
        if bit < height:
            if y & bit:
                result |= output_bit
            output_bit <<= 1
        bit <<= 1
    return result


def convert_texel(kind, data, palette=None):
    """Exact declared channel conversion, with Xbox bit expansion rounding."""
    value = int.from_bytes(data, 'little')
    expand5 = lambda v: (v << 3) | (v >> 2)
    expand6 = lambda v: (v << 2) | (v >> 4)
    if kind in ('a8r8g8b8', 'x8r8g8b8'):
        b, g, r, a = data
        return r, g, b, a if kind[0] == 'a' else 255
    if kind == 'a8b8g8r8':
        return tuple(data)
    if kind == 'b8g8r8a8':
        a, r, g, b = data
        return r, g, b, a
    if kind == 'r8g8b8a8':
        a, b, g, r = data
        return r, g, b, a
    if kind in ('a1r5g5b5', 'x1r5g5b5'):
        return expand5(value >> 10 & 31), expand5(value >> 5 & 31), expand5(value & 31), \
               (255 if kind[0] == 'x' or value & 32768 else 0)
    if kind == 'r5g6b5':
        return expand5(value >> 11), expand6(value >> 5 & 63), expand5(value & 31), 255
    if kind == 'a4r4g4b4':
        return (value >> 8 & 15)*17, (value >> 4 & 15)*17, (value & 15)*17, (value >> 12)*17
    if kind == 'r5g5b5a1':
        return expand5(value >> 11), expand5(value >> 6 & 31), expand5(value >> 1 & 31), 255 if value & 1 else 0
    if kind == 'r4g4b4a4':
        return (value >> 12)*17, (value >> 8 & 15)*17, (value >> 4 & 15)*17, (value & 15)*17
    if kind == 'l8':
        return data[0], data[0], data[0], 255
    if kind == 'al8':
        return (data[0],)*4
    if kind == 'a8':
        return 255, 255, 255, data[0]
    if kind == 'a8l8':
        return data[0], data[0], data[0], data[1]
    if kind == 'l16':
        return data[1], data[1], data[1], 255
    if kind == 'g8b8':
        return data[0], data[1], 0, 255
    if kind == 'r8b8':
        return data[1], 0, data[0], 255
    if kind == 'r6g5b5':
        return expand6(value >> 10), expand5(value >> 5 & 31), expand5(value & 31), 255
    if kind == 'v16u16':
        return data[1], data[3], 0, 255
    if kind == 'p8':
        require(palette is not None and len(palette) == 1024, 'P8 texture needs exact captured palette')
        return convert_texel('a8r8g8b8', palette[data[0]*4:data[0]*4+4])
    raise ValueError(f'Unverified texel conversion {kind}')


def texture_mipmaps(raw, description, palette=None):
    if description['cube_map']:
        # Source xgpu_texture_face_size: each full mip chain is padded to128
        # bytes. Faces are +X,-X,+Y,-Y,+Z,-Z; each mip restarts Morton indexing.
        lengths = []
        for level in range(description['levels']):
            width = max(1, description['width'] >> level)
            height = max(1, description['height'] >> level)
            lengths.append(((width+3)//4)*((height+3)//4)*description['stride']
                           if description['compressed'] else width*height*description['stride'])
        face_size = (sum(lengths)+127)&~127
        require(len(raw) >= 6*face_size, 'Truncated captured cube face allocation/mip chain')
        faces = [texture_mipmaps(raw[face*face_size:(face+1)*face_size],
                                dict(description, cube_map=False), palette) for face in range(6)]
        result = []
        for level in range(description['levels']):
            result.append(dict(level=level, width=faces[0][level]['width'],
                height=faces[0][level]['height'], pixel_format=faces[0][level]['pixel_format'],
                faces=[dict(mips[level], face=face,
                            source_offset=face*face_size+mips[level]['source_offset'])
                       for face, mips in enumerate(faces)]))
        return result
    result, offset = [], 0
    for level in range(description['levels']):
        width, height = max(1, description['width'] >> level), max(1, description['height'] >> level)
        if description['compressed']:
            row = ((width+3)//4)*description['stride']
            length = row*((height+3)//4)
        else:
            row = description['pitch'] if description['linear'] else width*description['stride']
            length = row*height
        require(offset+length <= len(raw), 'Truncated captured authored mip chain')
        source = raw[offset:offset+length]
        if description['compressed']:
            decoded, pixel_format = source, description['kind']
        else:
            decoded, pixel_format = bytearray(width*height*4), 'rgba8unorm'
            stride = description['stride']
            for y in range(height):
                for x in range(width):
                    pos = y*row+x*stride if description['linear'] else morton_offset(x, y, width, height)*stride
                    decoded[(y*width+x)*4:(y*width+x+1)*4] = bytes(
                        convert_texel(description['kind'], source[pos:pos+stride], palette))
            row = width*4
        result.append(dict(width=width, height=height, bytes_per_row=row,
                           bytes_per_image=len(decoded), data=bytes(decoded),
                           source_offset=offset, source_size=length, pixel_format=pixel_format))
        offset += length
    # Resource allocations may have captured trailing alignment bytes. Keep the
    # entire source hash, but only upload the header's exact authored levels.
    return result


def import_texture(package, slot, record, sampler_type, border_axes):
    """Bind declared shader dimension to exact captured resource bytes."""
    require(sampler_type in (1, 3) and isinstance(record, dict),
            f'Texture slot {slot}: captured 2D/cube resource is required; volume is unsupported')
    description = texture_description(record['format_word'], record['size_word'])
    require(description['cube_map'] == (sampler_type == 3),
            f'Texture slot {slot}: shader sampler type differs from captured resource dimension')
    require(not (description['cube_map'] and description['compressed'] and
                 description['kind'] != 'bc1_rgba'),
            f'Texture slot {slot}: only captured BC1 compressed cubes are validated')
    for field, expected in [('width', description['width']), ('height', description['height']),
                            ('depth', 1), ('levels', description['levels']), ('format_d3d', description['format'])]:
        require(field not in record or record[field] == expected,
                f'Texture slot {slot}: captured {field} differs from original resource header')
    raw = package.read(record)
    palette_record = record.get('palette')
    if description['kind'] == 'p8':
        require(isinstance(palette_record, dict) and
                palette_record.get('format') == 'argb32_little_endian',
                f'Texture slot {slot}: P8 requires exact captured ARGB32 palette')
    palette = package.read(palette_record) if palette_record is not None else None
    levels = texture_mipmaps(raw, description, palette)
    mips = []
    for level, mip in enumerate(levels):
        if description['cube_map']:
            faces = []
            for face in mip.pop('faces'):
                payload = face.pop('data')
                faces.append(dict(face, **package.write(
                    f'texture-{slot}-face-{face["face"]}-mip-{level}.bin', payload)))
            mips.append(dict(mip, faces=faces))
        else:
            payload = mip.pop('data')
            mips.append(dict(mip, **package.write(f'texture-{slot}-mip-{level}.bin', payload)))
    result = dict(slot=slot, type='cube' if description['cube_map'] else '2d',
        width=description['width'], height=description['height'], pixel_format=mips[0]['pixel_format'], mipmaps=mips,
        sampler=sampler_state(record['sampler'], len(mips), border_axes, sampler_type),
        source_sampler=dict(record['sampler']),
        source_header=dict(format_word=record['format_word'], size_word=record['size_word']),
        source_sha256=sha256(raw))
    if palette is not None:
        result['source_palette'] = dict(palette_record,
            **package.write(f'texture-{slot}-palette.bin', palette))
    if description['cube_map']:
        result['face_order'] = ['positive_x', 'negative_x', 'positive_y', 'negative_y', 'positive_z', 'negative_z']
        result['source_face_pitch_bytes'] = (sum(m['faces'][0]['source_size'] for m in mips)+127)&~127
    return result


def sampler_state(state, mip_count, border_axes, sampler_type=1):
    require(sampler_type in (1, 3), 'Unsupported replay sampler dimension')
    filters = {1: 'nearest', 2: 'linear', 3: 'linear'}
    mip_filters = {0: 'none', 1: 'nearest', 2: 'linear'}
    # Xbox5 is CLAMPTOEDGE in its native enum domain (not the identically
    # numbered Windows MIRRORONCE enum).
    addresses = {1: 'repeat', 2: 'mirror_repeat', 3: 'clamp_to_edge',
                 4: 'clamp_to_edge', 5: 'clamp_to_edge'}
    require(state['min_filter'] in filters and state['mag_filter'] in filters and
            state['mip_filter'] in mip_filters, 'Unsupported captured sampler filter')
    require(all(state[f'address_{axis}'] in addresses for axis in 'uvw'),
            'Unsupported captured sampler address mode')
    for axis, bit in zip('uv', (1, 2)):
        require((state[f'address_{axis}'] == 4) == bool(border_axes & bit),
                'Captured border address and pixel key disagree')
    # Metal texture2d reads only U/V. The original sampler object stores W
    # even on2D draws (d3d8_gl.c:2108); retain that raw value in source_sampler,
    # and use clamp-to-edge for the unused native R axis. Cube/volume W border
    # semantics require separate validation and are not inferred here.
    require(state['address_w'] != 4 or sampler_type == 1,
            'W border sampling requires separately validated cube/volume support')
    anisotropy = state['max_anisotropy'] if state['min_filter'] == 3 else 1
    require(uint(anisotropy) and 1 <= anisotropy <= 16, 'Unsupported captured anisotropy')
    lod_min = state['max_mip_level']
    require(uint(lod_min) and lod_min < mip_count, 'Captured sampler minimum mip exceeds authored chain')
    return dict(min_filter=filters[state['min_filter']], mag_filter=filters[state['mag_filter']],
                mip_filter=mip_filters[state['mip_filter']] if mip_count > 1 else 'none',
                **{f'address_{axis}': addresses[state[f'address_{axis}']] for axis in 'uvw'},
                lod_min=lod_min, lod_max=mip_count-1, max_anisotropy=anisotropy)


def validate_capture_shape(capture):
    require(isinstance(capture, dict) and capture.get('schema_version') == 1 and
            capture.get('kind') == 'captured_draw' and capture.get('complete') is True,
            'Incomplete or unsupported captured draw package')
    fields = ('frame', 'use', 'vertex_id', 'pixel_id', 'program_id', 'declaration_id',
              'shader_corpus', 'shader_corpus_sha256', 'vertex_constants', 'draw_uniforms',
              'vertex_declaration', 'vertex_streams', 'fixed_attributes', 'draw',
              'textures', 'target', 'render_state')
    require(all(field in capture for field in fields), 'Captured draw package is missing required fields')
    require(all(uint(capture[field]) for field in fields[:6]), 'Invalid captured draw shader/use identity')
    declaration = capture['vertex_declaration']
    require(isinstance(declaration, dict) and uint(declaration.get('packed_mask'), 16) and
            isinstance(declaration.get('elements'), list) and len(declaration['elements']) <= 16,
            'Invalid captured vertex declaration')
    types = {0x02, 0x12, 0x22, 0x32, 0x42, 0x72, 0x40, 0x16,
             0x11, 0x21, 0x31, 0x41, 0x15, 0x25, 0x35, 0x45, 0x14, 0x24, 0x34, 0x44}
    registers, packed_mask = set(), 0
    for element in declaration['elements']:
        require(isinstance(element, dict) and uint(element.get('register'), 4) and
                uint(element.get('stream'), 4) and uint(element.get('offset'), 16) and
                element.get('type') in types, 'Invalid captured vertex declaration element')
        require(element['register'] not in registers, 'Duplicate captured vertex register')
        registers.add(element['register'])
        if element['type'] == 0x16:
            packed_mask |= 1 << element['register']
    require(packed_mask == declaration['packed_mask'], 'Declaration elements and packed mask disagree')
    streams = capture['vertex_streams']
    require(isinstance(streams, list) and len(streams) <= 16, 'Invalid captured vertex streams')
    slots = set()
    for stream in streams:
        require(isinstance(stream, dict) and uint(stream.get('stream'), 4) and
                uint(stream.get('stride'), 16) and stream['stride'] > 0,
                'Invalid captured vertex stream')
        require(stream['stream'] not in slots, 'Duplicate captured vertex stream')
        slots.add(stream['stream'])
    require(all(e['type'] == 0x02 or e['stream'] in slots for e in declaration['elements']),
            'Declaration uses missing captured vertex stream')
    draw = capture['draw']
    require(isinstance(draw, dict) and type(draw.get('indexed')) is bool and
            draw.get('primitive') in ('point', 'line', 'line_strip', 'line_loop', 'triangle',
                                     'triangle_strip', 'triangle_fan', 'quad'), 'Invalid captured draw topology')
    if draw['indexed']:
        require(uint(draw.get('index_count')) and draw['index_count'] > 0 and
                draw.get('index_type') in ('uint16', 'uint32') and
                isinstance(draw.get('index_buffer'), dict), 'Invalid captured index draw')
    else:
        require(uint(draw.get('vertex_start')) and uint(draw.get('vertex_count')) and
                draw['vertex_count'] > 0, 'Invalid captured vertex draw')
    require(isinstance(capture['textures'], list) and len(capture['textures']) == 4,
            'Draw must capture all four texture slots')
    target = capture['target']
    require(isinstance(target, dict) and target.get('orientation') == 'top_left' and
            all(uint(target.get(field)) and 0 < target[field] <= 16384 for field in ('width', 'height')),
            'Invalid captured target dimensions/orientation')
    require(target.get('color_format') == 'bgra8unorm' and
            target.get('depth_format') == 'depth32float_stencil8', 'Unsupported native replay attachment formats')
    require(isinstance(target.get('clear_color'), list) and len(target['clear_color']) == 4 and
            all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in target['clear_color']) and
            type(target.get('clear_depth')) in (int, float) and 0 <= target['clear_depth'] <= 1 and
            uint(target.get('clear_stencil'), 8), 'Invalid captured clear attachments')
    state = capture['render_state']
    require(isinstance(state, dict) and all(isinstance(state.get(field), dict)
            for field in ('depth', 'raster', 'blend', 'stencil', 'viewport', 'scissor')),
            'Missing captured raster state')
    comparisons = {'never', 'less', 'equal', 'less_equal', 'greater', 'not_equal', 'greater_equal', 'always'}
    require(type(state['depth'].get('enabled')) is bool and type(state['depth'].get('write')) is bool and
            state['depth'].get('compare') in comparisons, 'Unsupported captured depth state')
    require(type(state['stencil'].get('enabled')) is bool and state['stencil'].get('compare') in comparisons,
            'Unsupported captured stencil state')
    raster = state['raster']
    require(raster.get('front_face') in ('cw', 'ccw') and raster.get('cull') in ('none', 'front', 'back') and
            raster.get('fill') in ('solid', 'wireframe'), 'Unsupported captured cull/fill state')
    factors = {'zero', 'one', 'source_color', 'one_minus_source_color', 'source_alpha', 'one_minus_source_alpha',
               'destination_color', 'one_minus_destination_color', 'destination_alpha', 'one_minus_destination_alpha',
               'source_alpha_saturated', 'blend_color', 'one_minus_blend_color', 'blend_alpha', 'one_minus_blend_alpha'}
    blend = state['blend']
    require(type(blend.get('enabled')) is bool and blend.get('source') in factors and
            blend.get('destination') in factors and blend.get('operation') in ('add', 'subtract', 'reverse_subtract', 'min', 'max') and
            uint(blend.get('write_mask'), 4), 'Unsupported captured blend state')
    if any('blend_' in blend[field] for field in ('source', 'destination')):
        require(isinstance(blend.get('color'), list) and len(blend['color']) == 4 and
                all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in blend['color']),
                'Constant blend factors require captured blend color')


class Package:
    def __init__(self, source, output):
        self.source, self.output = source.resolve(), output.resolve()
        self.hashes = {}

    def read(self, descriptor):
        require(isinstance(descriptor, dict) and isinstance(descriptor.get('file'), str),
                'Invalid captured payload descriptor')
        path = (self.source/descriptor['file']).resolve()
        require(path.is_relative_to(self.source), 'Captured payload escapes package directory')
        data = path.read_bytes()
        require(descriptor.get('sha256') == sha256(data), f'Captured payload hash mismatch: {path.name}')
        if 'size' in descriptor:
            require(descriptor['size'] == len(data), f'Captured payload size mismatch: {path.name}')
        self.hashes[str(path)] = sha256(data)
        return data

    def write(self, name, data):
        (self.output/name).write_bytes(data)
        return dict(file=name, size=len(data), sha256=sha256(data))


def normalize_xbox_state(raw, target, viewport, scissor):
    """Translate Xbox enums while preserving the original logical top rows."""
    comparisons = dict(zip(range(512, 520), ('never', 'less', 'equal', 'less_equal',
                       'greater', 'not_equal', 'greater_equal', 'always')))
    factors = {0: 'zero', 1: 'one', 768: 'source_color', 769: 'one_minus_source_color',
               770: 'source_alpha', 771: 'one_minus_source_alpha', 772: 'destination_alpha',
               773: 'one_minus_destination_alpha', 774: 'destination_color',
               775: 'one_minus_destination_color', 776: 'source_alpha_saturated',
               32769: 'blend_color', 32770: 'one_minus_blend_color',
               32771: 'blend_alpha', 32772: 'one_minus_blend_alpha'}
    operations = {32774: 'add', 32778: 'subtract', 32779: 'reverse_subtract', 32775: 'min', 32776: 'max'}
    stencil_ops = {7680: 'keep', 0: 'zero', 7681: 'replace', 7682: 'increment_clamp',
                   7683: 'decrement_clamp', 5386: 'invert', 34055: 'increment_wrap', 34056: 'decrement_wrap'}
    def enum(mapping, name):
        require(raw.get(name) in mapping, f'Unsupported captured Xbox state {name}')
        return mapping[raw[name]]
    for name in ('depth_enable', 'depth_write', 'blend_enable', 'stencil_enable', 'offset_enable'):
        require(raw.get(name) in (0, 1), f'Unsupported captured Xbox state {name}')
    front = enum({2304: 'cw', 2305: 'ccw'}, 'front_face')
    require(raw.get('cull') in (0, 2304, 2305), 'Unsupported captured Xbox culling')
    cull = 'none' if raw['cull'] == 0 else 'front' if raw['cull'] == raw['front_face'] else 'back'
    mask = raw['color_write']
    require(uint(mask) and not mask & ~0x01010101, 'Unsupported Xbox color write mask')
    write_mask = ((bool(mask & 0x10000))*1 | (bool(mask & 0x100))*2 |
                  (bool(mask & 1))*4 | (bool(mask & 0x1000000))*8)
    vp = dict(x=viewport['origin_x'], y=viewport['origin_y'], width=viewport['width'],
              height=viewport['height'], znear=viewport['znear'], zfar=viewport['zfar'])
    require(type(scissor.get('enabled')) is bool, 'Missing original scissor enable')
    if scissor['enabled']:
        x, y, width, height = scissor['box_gl']
        # apply_raster_state copies the D3D viewport directly to glScissor
        # (d3d8_gl.c:2382–2390). Internal GLrow0 is already Xbox picturetop;
        # this is the same source contract as color readback, with no Y flip.
        rectangle = dict(x=x, y=y, width=width, height=height)
    else:
        rectangle = dict(x=0, y=0, width=target['width'], height=target['height'])
    result = dict(viewport=vp, scissor=rectangle,
        depth=dict(enabled=bool(raw['depth_enable']), write=bool(raw['depth_write']), compare=enum(comparisons, 'depth_compare')),
        raster=dict(front_face=front, cull=cull, fill='solid',
            depth_bias=raw['offset_units'] if raw['offset_enable'] else 0.,
            slope_scale=raw['offset_slope'] if raw['offset_enable'] else 0., depth_bias_clamp=0.),
        blend=dict(enabled=bool(raw['blend_enable']), source=enum(factors, 'blend_source'),
            destination=enum(factors, 'blend_destination'), operation=enum(operations, 'blend_op'), write_mask=write_mask),
        stencil=dict(enabled=bool(raw['stencil_enable']), compare=enum(comparisons, 'stencil_compare'),
            reference=raw['stencil_ref'], read_mask=raw['stencil_read_mask'], write_mask=raw['stencil_write_mask'],
            fail=enum(stencil_ops, 'stencil_fail'), depth_fail=enum(stencil_ops, 'stencil_depth_fail'),
            **{'pass': enum(stencil_ops, 'stencil_pass')}))
    if any('blend_' in result['blend'][field] for field in ('source', 'destination')):
        require(uint(raw.get('blend_color')), 'Constant blend factors require captured Xbox blend color')
        color = raw['blend_color']
        result['blend']['color'] = [(color >> shift & 255)/255. for shift in (16, 8, 0, 24)]
    return result


def freeze_raw_capture(raw_path, runner_path):
    """Finalize a completed development capture into immutable hashed sidecars.

    The raw capture and payloads remain untouched. This packaging operation
    freezes their current bytes and generates no geometry or shader input.
    Reference bytes retain the source renderer's logical top-first row order.
    """
    raw_path, runner_path = raw_path.resolve(), runner_path.resolve()
    raw_bytes = raw_path.read_bytes()
    raw = json.loads(raw_bytes)
    require(raw.get('kind') == 'captured_draw' and raw.get('complete') is True,
            'Raw game draw capture is incomplete')
    base = raw_path.parent
    metadata_path = base/'captured_draw.json'
    require(not metadata_path.exists(), 'Capture already frozen; preserve its original identity')
    _, uses, status, hashes = load_corpus((base/raw['shader_corpus']).resolve())
    require(raw['frame'] == status['frame'] and uint(raw['use']) and raw['use'] < len(uses),
            'Raw draw frame/use missing from completed shader corpus')
    use = uses[raw['use']]
    require(raw['program_id'] == use['program_id'] and raw['declaration_id'] == use['declaration_id'],
            'Raw draw program/declaration does not match captured shader use')
    capture = copy.deepcopy(raw)
    capture.update(vertex_id=use['vertex_id'], pixel_id=use['pixel_id'],
                   shader_corpus_sha256={Path(path).name: expected for path, expected in hashes.items()})
    def descriptor(record):
        path = (base/record['file']).resolve()
        require(path.is_relative_to(base), 'Raw captured resource escapes package')
        data = path.read_bytes()
        result = dict(record, size=len(data), sha256=sha256(data))
        if 'bytes' in record:
            require(record['bytes'] == len(data), 'Raw captured resource size differs from completion record')
        return result
    for field in ('vertex_constants', 'draw_uniforms', 'fixed_attributes'):
        capture[field] = descriptor(capture[field])
    capture['vertex_streams'] = [descriptor(record) for record in capture['vertex_streams']]
    for index, record in enumerate(capture['textures']):
        if record is not None:
            capture['textures'][index] = descriptor(record)
            if 'palette' in record:
                capture['textures'][index]['palette'] = descriptor(record['palette'])
    draw = capture['draw']
    if draw['primitive'] == 'quadlist':
        draw['primitive'] = 'quad'
    if draw['indexed']:
        draw['index_buffer'] = descriptor(draw['index_buffer'])
    if 'reference_triangle_indices' in draw:
        draw['reference_triangle_indices'] = descriptor(draw['reference_triangle_indices'])
    capture['reference_target'] = copy.deepcopy(capture['target'])
    require(capture['target']['color_format'] == 'rgba8unorm' and
            capture['target']['depth_format'] == 'depth24_stencil8', 'Unverified original capture target formats')
    capture['target'].update(color_format='bgra8unorm', depth_format='depth32float_stencil8')
    capture['render_state'] = normalize_xbox_state(capture['render_state_d3d'], capture['target'],
                                                  capture['viewport'], capture['scissor'])
    capture['state_sha256'] = sha256(json.dumps(capture['render_state'], sort_keys=True,
                                               separators=(',', ':'), allow_nan=False).encode())
    reference = capture['reference']['color']
    reference_bytes = (base/reference['file']).read_bytes()
    width, height = capture['target']['width'], capture['target']['height']
    require(len(reference_bytes) == width*height*4, 'Original color readback size mismatch')
    require(reference['format'] == 'rgba8unorm' and reference['orientation'] in ('top_left', 'bottom_left'),
            'Unverified original readback format/orientation')
    # The collector's bottom_left label describes physical GL row indexing,
    # not this renderer's logical Xbox attachment indexing. Source screenshot
    # writes glReadPixels bytes unchanged with a negative BMP height (top-down),
    # and Present states row0 is picturetop, reversing the window blit. GLES
    # vertex Y inversion implements the same contract. Thus raw internal-target
    # rows are ALREADY logical D3Dtop-left; never flip them to fit native output.
    capture['raw_reference'] = dict(reference, size=len(reference_bytes), sha256=sha256(reference_bytes))
    capture['readback_contract'] = dict(storage_orientation=reference['orientation'],
        logical_orientation='top_left', transformed=False,
        evidence='d3d8_gl.c Screenshot writes top-down BMP from unchanged readback; Present reverses destination Y')
    reference_file = base/'angle-color-top-left.rgba8'
    reference_file.write_bytes(reference_bytes)
    capture['reference']['color'] = dict(reference, file=reference_file.name, size=len(reference_bytes),
                                         sha256=sha256(reference_bytes), orientation='top_left')
    capture['raw_capture'] = dict(file=raw_path.name, size=len(raw_bytes), sha256=sha256(raw_bytes))
    validate_capture_shape(capture)
    metadata_bytes = (json.dumps(capture, indent=2, allow_nan=False)+'\n').encode()
    metadata_path.write_bytes(metadata_bytes)
    runner_bytes = runner_path.read_bytes()
    result = dict(schema_version=1, kind='nv2a_draw_result', complete=True, backend='angle',
        source_capture=dict(sha256=sha256(metadata_bytes), frame=capture['frame'], use=capture['use'],
                            state_sha256=capture['state_sha256']),
        runner=dict(file=str(runner_path), size=len(runner_bytes), sha256=sha256(runner_bytes)),
        actual_depth_format='depth24_stencil8', color=capture['reference']['color'],
        limits=capture.get('limits', [])+['No physical Xbox reference; one isolated draw only.',
                'Depth/stencil readback unavailable in this scoped ANGLE capture.'],
        visible_reference=any(reference_bytes), raw_capture=capture['raw_capture'])
    (base/'reference-result.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    return metadata_path


def prepare(capture_path, output, corpus_path=None, vertex_compiler_evidence=None,
            fragment_compiler_evidence=None):
    capture_path = capture_path.resolve()
    data = capture_path.read_bytes()
    capture = json.loads(data)
    validate_capture_shape(capture)
    output.mkdir(parents=True, exist_ok=True)
    package = Package(capture_path.parent, output)
    corpus_path = corpus_path or capture_path.parent/capture['shader_corpus']
    records, uses, status, corpus_hashes = load_corpus(corpus_path.resolve())
    require(capture['shader_corpus_sha256'] == {Path(path).name: digest for path, digest in corpus_hashes.items()},
            'Captured shader corpus is stale or does not match original draw package')
    require(capture['frame'] == status['frame'] and uint(capture['use']) and capture['use'] < len(uses),
            'Captured draw does not belong to shader corpus frame/use')
    use = uses[capture['use']]
    for field in ('vertex_id', 'pixel_id', 'program_id', 'declaration_id'):
        require(capture[field] == use[field], f'Captured draw shader pairing mismatch: {field}')
    vertex = next(record for _, record in records if record['kind'] == 'vertex' and record['id'] == use['vertex_id'])
    pixel = next(record for _, record in records if record['kind'] == 'pixel' and record['id'] == use['pixel_id'])
    require(capture['vertex_declaration']['packed_mask'] == vertex['packed_mask'],
            'Captured declaration packed mask differs from shader key')
    prepared_sources = source_hashes()
    lib = build_library(output)
    words = (C.c_uint32*len(vertex['instructions']))(*vertex['instructions'])
    vertex_source = generated(lib.nv2a_vertex_shader_to_msl, words,
                              vertex['instruction_count'], vertex['packed_mask'])
    key = PixelKey()
    for name, _ in PixelKey._fields_:
        if isinstance(pixel[name], list):
            getattr(key, name)[:] = pixel[name]
        else:
            setattr(key, name, pixel[name])
    depth_contract = pixel_depth_contract(capture, key)
    if depth_contract is None:
        pixel_source = generated(lib.nv2a_pixel_shader_to_msl, C.byref(key))
    else:
        lib.nv2a_pixel_shader_to_msl_with_options.argtypes = [C.POINTER(PixelKey), C.POINTER(PixelMslOptions)]
        lib.nv2a_pixel_shader_to_msl_with_options.restype = C.c_void_p
        options = PixelMslOptions(1, 1)
        pixel_source = generated(lib.nv2a_pixel_shader_to_msl_with_options, C.byref(key), C.byref(options))
    require(vertex_source is not None and pixel_source is not None,
            f'Captured shader pair is not yet supported by direct Metal emitter (errno={C.get_errno()})')
    shaders = {kind: dict(package.write(f'{kind}.metal', text.encode()), entry=entry)
               for kind, text, entry in [('vertex', vertex_source, 'xgpu_vertex'),
                                          ('fragment', pixel_source, 'xgpu_fragment')]}
    if vertex_compiler_evidence is not None:
        options, evidence, baseline = vertex_compile_contract(lib, words, vertex,
                                                             vertex_compiler_evidence, package)
        shaders['vertex'].update(compile_options=options, compiler_evidence=evidence,
                                 compiler_baseline=baseline)
    if fragment_compiler_evidence is not None:
        options, evidence, baseline = fragment_compile_contract(lib, key,
            fragment_compiler_evidence, package)
        shaders['fragment'].update(compile_options=options, compiler_evidence=evidence,
                                  compiler_baseline=baseline)
    v_uniforms, p_uniforms = split_uniforms(package.read(capture['vertex_constants']),
                                          package.read(capture['draw_uniforms']), depth_contract)
    uniforms = {kind: package.write(f'{kind}-uniforms.bin', raw)
                for kind, raw in [('vertex', v_uniforms), ('pixel', p_uniforms)]}
    streams = []
    for record in capture['vertex_streams']:
        streams.append(dict(record, **package.write(f'stream-{record["stream"]}.bin', package.read(record))))
    draw = copy.deepcopy(capture['draw'])
    if draw['indexed']:
        draw['index_buffer'] = package.write('indices.bin', package.read(draw['index_buffer']))
    if 'reference_triangle_indices' in draw:
        draw['reference_triangle_indices'] = dict(draw['reference_triangle_indices'],
            **package.write('reference-triangle-indices.bin', package.read(draw['reference_triangle_indices'])))
    textures = []
    require(len(capture['textures']) == 4, 'Draw must capture all four texture slots')
    for slot, record in enumerate(capture['textures']):
        if key.sampler_type[slot] == 0:
            textures.append(None)
            continue
        textures.append(import_texture(package, slot, record, key.sampler_type[slot], key.border_axes[slot]))
    target = copy.deepcopy(capture['target'])
    require(target.get('orientation') == 'top_left', 'Capture target orientation must be explicit top_left')
    for field in ('initial_color', 'initial_depth', 'initial_stencil'):
        if field in target:
            target[field] = dict(target[field], **package.write(field+'.bin', package.read(target[field])))
    reference = copy.deepcopy(capture.get('reference', {}))
    if 'raw_capture' in capture:
        package.read(capture['raw_capture'])
    if 'raw_reference' in capture:
        package.read(capture['raw_reference'])
    for field in ('color', 'depth', 'stencil'):
        if field in reference:
            reference[field] = dict(reference[field], **package.write('reference-'+field+'.bin', package.read(reference[field])))
    require(prepared_sources == source_hashes(), 'Emitter/importer sources changed during preparation')
    package.hashes.update(corpus_hashes)
    package.hashes[str(capture_path)] = sha256(data)
    fixed_attributes = capture['fixed_attributes']
    if isinstance(fixed_attributes, dict):
        raw_fixed = package.read(fixed_attributes)
        require(len(raw_fixed) == 256, 'Fixed vertex attributes must be exactly 256 bytes')
        fixed_attributes = list(map(list, struct.iter_unpack('<4f', raw_fixed)))
    require(isinstance(fixed_attributes, list) and len(fixed_attributes) == 16 and
            all(isinstance(a, list) and len(a) == 4 and
                all(type(v) in (float, int) and math.isfinite(v) for v in a)
                for a in fixed_attributes), 'Invalid fixed vertex attributes')
    manifest = dict(schema_version=1, kind='nv2a_draw_replay', source_capture=dict(
        file=str(capture_path), sha256=sha256(data), frame=capture['frame'], use=capture['use'],
        vertex_id=use['vertex_id'], pixel_id=use['pixel_id'], program_id=use['program_id'],
        declaration_id=use['declaration_id'], input_sha256=package.hashes,
        inputs=[dict(file=path, sha256=expected) for path, expected in package.hashes.items()]),
        source_sha256=prepared_sources, target=target, shaders=shaders, uniforms=uniforms,
        vertex_declaration=copy.deepcopy(capture['vertex_declaration']), vertex_streams=streams,
        fixed_attributes=copy.deepcopy(fixed_attributes), draw=draw, textures=textures,
        render_state=copy.deepcopy(capture['render_state']), reference=reference,
        limitations=['one captured draw; no complete game frame',
                     'ANGLE reference is not a physical Xbox reference',
                     'volume/depth/YUV sampled resources not yet validated'])
    if 'state_sha256' in capture:
        manifest['source_capture']['state_sha256'] = capture['state_sha256']
    if 'reference_target' in capture:
        manifest['reference_target'] = capture['reference_target']
    if depth_contract is not None:
        manifest['pixel_depth_contract'] = depth_contract
        manifest['limitations'].extend(depth_contract['limitations'])
    if vertex_compiler_evidence is not None:
        manifest['limitations'].append('Vertex fast math contract is inferred from the pinned ANGLE source and shader flags; physical Xbox precision is unverified')
    if fragment_compiler_evidence is not None:
        manifest['limitations'].append('Fragment fast math contract is inferred per shader from the pinned ANGLE source and original GLSL flags; physical Xbox precision is unverified')
    (output/'replay.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--freeze-raw', action='store_true')
    parser.add_argument('--reference-runner', type=Path)
    parser.add_argument('--vertex-compiler-evidence', type=Path,
                        help='Opt in to the source-proven original ANGLE invariant fast vertex compiler contract')
    parser.add_argument('--fragment-compiler-evidence', type=Path,
                        help='Opt each original fragment key into the pinned ANGLE noninvariant fast policy')
    args = parser.parse_args()
    capture = args.capture
    if args.freeze_raw:
        if args.reference_runner is None:
            parser.error('--freeze-raw requires --reference-runner')
        capture = freeze_raw_capture(capture, args.reference_runner)
    manifest = prepare(capture, args.output.resolve(), args.corpus, args.vertex_compiler_evidence,
                       args.fragment_compiler_evidence)
    print(json.dumps(dict(manifest=str(args.output.resolve()/'replay.json'),
                         frame=manifest['source_capture']['frame'],
                         use=manifest['source_capture']['use'],
                         active_textures=sum(t is not None for t in manifest['textures'])), indent=2))


if __name__ == '__main__':
    main()
