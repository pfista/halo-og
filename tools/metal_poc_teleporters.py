"""Export Blood Gulch's authored teleporter scenery for the isolated Metal POC.

The scenario placements, model permutation, triangle strips, compressed UVs,
and material references come from the v5 cache. Unsupported state is rejected;
there is no generated substitute mesh, image, glow or animation. Texture export
uses the caller's authored-mipmap callback, including bitmap permutations.

ILP32 layouts: scenario_definitions.h, scenery.c, object_definitions.h,
model_definitions.h, shader_transparent_generic_preprocessor.c and
rasterizer_xbox_transparent_geometry.c. This adds visual scenery only; netgame
teleporter flags and all simulation state are deliberately outside this module.
"""
import math
from functools import lru_cache
from pathlib import Path
import re
import struct

from metal_poc_export import require


TELEPORTER_BASE = r'scenery\teleporter_base\teleporter_base'
PLASMA_SHADER = r'scenery\teleporter_shield\shaders\teleporter_shield'
CONE_SHADER = r'scenery\teleporter_base\shaders\teleporter_cone'

# The exact 26 signed-short input/output selectors in the authored seven-stage
# generic shader. Comparing every selector prevents silently broadening this
# specialized shader to a different material with the same tag name.
PLASMA_STAGES = (
    (23,1,17,0,23,0,15,0,0,0,0,0,1,0,23,1,2,0,23,0,6,0,0,0,1,0),
    (18,0,2,0,18,1,11,0,0,0,0,0,1,0,8,0,2,0,8,1,11,0,0,0,1,0),
    (11,0,1,0,21,5,1,0,0,0,0,0,1,0,11,0,1,0,21,5,1,0,0,0,1,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,11,0,11,0,21,0,21,0,0,0,1,3),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,11,2,11,2,0,0,1,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,11,0,1,0,11,0,11,1,0,0,1,0),
    (21,0,8,0,13,0,8,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0),
)


@lru_cache(maxsize=1)
def original_bump_palette():
    """The original 256-entry shared Xbox vector palette, including alpha."""
    source = (Path(__file__).resolve().parents[1]/'source/bitmaps/bitmaps.c').read_text()
    declaration = source.index('pixel32 global_vector_palette[')
    start = source.index('{',declaration)
    end = source.index('};',start)
    palette = tuple(int(value,16) for value in re.findall(r'0x[\da-fA-F]+',source[start:end]))
    require(len(palette) == 256, 'Invalid original Xbox bump palette')
    return palette


def decode_p8_bump_mipmaps(raw,width,height,flags,mipmap_count):
    """Exact P8_BUMP expansion; reuse the existing byte-texel mip/swizzle path.

    A8 and P8 have identical one-byte storage. The temporary A8 alpha contains
    each unswizzled palette index; expand it through the original ARGB table.
    This also preserves the seven transparent palette entries used by the
    original teleporter cutout instead of testing its unrelated base alpha.
    """
    from metal_poc_export import decode_bitmap_mipmaps
    require(flags&128 and not flags&2, 'Invalid palettized Xbox bump flags')
    palette = original_bump_palette()
    levels = decode_bitmap_mipmaps(raw,width,height,0,flags,mipmap_count)
    for level in levels:
        pixels = bytearray()
        for index in level['rgba'][3::4]:
            color = palette[index]
            pixels.extend(((color>>16)&255,(color>>8)&255,color&255,color>>24))
        level['rgba'] = pixels
    return levels


def rotation_basis(angles):
    """Original matrix4x3_rotation_from_angles, in column-vector order."""
    yaw, pitch, roll = angles
    cy, sy, cp, sp, cr, sr = (math.cos(yaw), math.sin(yaw), math.cos(pitch),
                             math.sin(pitch), math.cos(roll), math.sin(roll))
    # The C n[4][3] rows are forward/left/up/position, not conventional
    # matrix rows. Each vector below is a column in the point transform.
    return ((cy*cp, sy*cr-cy*sp*sr, cy*sp*cr+sy*sr),
            (-sy*cp, sy*sp*sr+cy*cr, cy*sr-sy*sp*cr),
            (-sp, -cp*sr, cp*cr))


def transform_vector(vector, basis):
    return tuple(sum(vector[j]*basis[j][i] for j in range(3)) for i in range(3))


def unpack_normal(word):
    # NV2A D3DVSDT_NORMPACKED3 input, followed by normalization in original
    # model generic vertex program47. Do not normalize before node rotation.
    values = []
    for shift, bits in ((0,11), (11,11), (22,10)):
        value = (word >> shift) & ((1 << bits)-1)
        if value & (1 << (bits-1)):
            value -= 1 << bits
        values.append(value / ((1 << (bits-1))-1))
    return tuple(values)


def packed_color(argb):
    # Original real_argb_color_to_pixel32 rounds to nearest, ties to even.
    require(all(math.isfinite(x) and 0 <= x <= 1 for x in argb),
            'Invalid teleporter combiner color')
    return [round(x*255)/255 for x in (*argb[1:], argb[0])]


def texture_animation(cache, offset):
    result = []
    for axis in range(3):
        source, function, period, phase, scale = cache.unpack('<hhfff', offset+axis*16)
        require(source == 0 and function in (0,6), 'Unsupported teleporter animation source/function')
        require(all(math.isfinite(x) for x in (period, phase, scale)),
                'Non-finite teleporter animation')
        result.append([function, period, phase, scale])
    center = cache.unpack('<2f', offset+48)
    require(all(math.isfinite(x) for x in center), 'Non-finite teleporter rotation center')
    return result, center


def transparent_material(cache, shader_id, permutation, texture):
    cls, shader, name = cache.tag(shader_id)
    require((cls, name) in (('sotr',PLASMA_SHADER), ('schi',CONE_SHADER)),
            'Unsupported teleporter transparent shader')
    require(cache.unpack('<BB4h', shader+0x28) == (0,4,0,3,2,0),
            'Unsupported teleporter flags/type/blend/fade')
    require(cache.u32(shader) == 0 and cache.u32(shader+0x48) == 0,
            'Unsupported teleporter lighting/extra layer')
    count, pointer = cache.unpack('<II', shader+0x54)
    kind = 1 if cls == 'sotr' else 2
    require(count == (4 if kind == 1 else 3), 'Unsupported teleporter map count')
    stride = 100 if kind == 1 else 220
    maps, textures = [], []
    for i in range(count):
        m = cache.pointer(pointer, count*stride)+i*stride
        map_offset, scale_offset, animation_offset = (28,4,44) if kind == 1 else (108,84,164)
        require(cache.unpack('<H',m)[0] == 0, 'Unsupported teleporter sampler flags')
        sx, sy, ox, oy, rotation, bias = cache.unpack('<6f', m+scale_offset)
        require(all(math.isfinite(x) for x in (sx,sy,ox,oy,rotation,bias)) and bias == 0,
                'Unsupported teleporter map transform/bias')
        if kind == 2:
            require(cache.unpack('<2h',m+44) == ((2,2) if i < 2 else (0,0)),
                    'Unsupported teleporter Chicago function')
        animation, center = texture_animation(cache, m+animation_offset)
        textures.append(texture(cache.u32(m+map_offset+12), permutation, True))
        maps.append(dict(scale_offset=[sx,sy,ox,oy], u_animation=animation[0],
                         v_animation=animation[1], r_animation=animation[2],
                         rotation_center=[rotation,*center,0]))
    constants = [[0.,0.,0.,0.], [0.,0.,0.,0.]]
    if kind == 1:
        n, p = cache.unpack('<II',shader+0x60)
        require(n == 7, 'Unsupported teleporter generic stage count')
        for i in range(n):
            stage = cache.pointer(p,n*112)+i*112
            require(cache.unpack('<4h',stage) == ((4,0,0,0) if i in (0,6) else
                                               (2,0,0,0) if i in (3,4) else (0,0,0,0)),
                    'Unsupported teleporter generic stage flags/animation')
            require(cache.unpack('<f',stage+8)[0] == 1 and
                    cache.unpack('<26h',stage+60) == PLASMA_STAGES[i],
                    'Unsupported teleporter generic combiner')
            lower = cache.unpack('<4f',stage+12)
            # Object outgoing function A is zero: these tags have no object
            # functions. Flag4 selects A, so animated color0 stays at lower.
            if i in (0,6):
                constants[int(i == 6)] = packed_color(lower)
            else:
                require(lower == (0.,0.,0.,0.), 'Unsupported teleporter constant color0')
            require(cache.unpack('<4f',stage+44) == (0.,0.,0.,0.),
                    'Unsupported teleporter constant color1')
    return dict(kind=kind, textures=textures+[0]*(4-count), maps=maps,
                constant_colors=constants, blend='add', two_sided=True,
                fade_mode=2, name=name)


def environment_material(cache, shader_id, permutation, texture):
    cls, shader, name = cache.tag(shader_id)
    require(cls == 'senv', 'Unsupported teleporter opaque shader')
    require(cache.unpack('<H',shader+0x6c)[0] == 0,
            'Unsupported teleporter environment detail rescale')
    # Scenery senv uses _model_environment_part_draw, not the BSP's three
    # detail-map diffuse pass. It binds PRIMARY only; secondary/micro are
    # ignored. Neutral detail128 and white RGB are exact original default2D
    # usages2/1, confirmed in the cache's rasterizer\default 2d bitmap group.
    tag = cache.u32(shader+0xc4)
    primary = texture(tag,permutation,True) if tag != 0xffffffff else 1
    scale = cache.unpack('<f',shader+0xb4)[0]
    require(math.isfinite(scale), 'Non-finite teleporter detail scale')
    alpha_test = bool(cache.unpack('<H',shader+0x28)[0]&1)
    alpha_texture = texture(cache.u32(shader+0x134),permutation,True) if alpha_test else 0
    return dict(kind=0, name=name, base_texture=texture(cache.u32(shader+0x94),permutation,True),
                detail_textures=[primary,0,0], detail_scales=[scale,scale,1.,1.,1.,1.],
                shader_type=cache.unpack('<H',shader+0x2a)[0],
                detail_function=cache.unpack('<H',shader+0xb0)[0],
                micro_function=1, alpha_test=alpha_test, alpha_test_texture=alpha_texture,
                model_environment=True, lightmap_texture=0, object_lighting=True,
                bitmap_permutation=permutation)


def append_teleporters(cache, scenario, vertices, indices, texture):
    """Append authored scenery; return JSON meshes plus packed normal_data.

    Vertex/index buffers retain the existing 28B/uint32 ABI. normal_data is
    packed3f per GLOBAL vertex, padded with zeros for previous BSP/sky vertices.
    The caller writes it to teleporter_normals.bin separately from scene JSON.
    `texture(tag_id, bitmap_index, permutation)` must preserve authored mips.
    """
    require(cache.name == 'bloodgulch', 'Teleporter path validated only for Blood Gulch')
    require(len(vertices)%28 == 0 and len(indices)%4 == 0, 'Invalid shared geometry ABI')
    normal_data = bytearray(len(vertices)//28*12)
    palette_count, palette_pointer = cache.unpack('<II',scenario+0x21c)
    count, pointer = cache.unpack('<II',scenario+0x210)
    palette = cache.pointer(palette_pointer,palette_count*48)
    placements = cache.pointer(pointer,count*72)
    meshes, exported_placements = [], []
    materials = {}
    for placement_index in range(count):
        placement = placements+placement_index*72
        palette_index, _, flags, variant = cache.unpack('<4h',placement)
        if palette_index < 0:
            continue
        require(palette_index < palette_count, 'Invalid scenery palette index')
        cls, obj, name = cache.tag(cache.u32(palette+palette_index*48+12))
        if name != TELEPORTER_BASE:
            continue
        # object_types.c:1127 only places scenery belonging to the current BSP.
        # The caller validates one BSP, whose scenario index is zero. In
        # particular, zero is not a fallback: Blood Gulch contains an unused,
        # tilted teleporter placement with no BSP membership.
        if not cache.unpack('<H', placement+32)[0] & 1:
            continue
        require(cls == 'scen' and flags == 0 and variant == 0,
                'Unsupported teleporter placement type/flags/variant')
        require(cache.unpack('<3f',obj+20) == (0.,0.,0.) and
                cache.u32(obj+0x44) == 0xffffffff and cache.u32(obj+0x158) == 0 and
                cache.unpack('<4h',obj+0x108) == (0,0,0,0) and
                cache.unpack('<h',obj+0x13e)[0] == 0,
                'Unsupported teleporter object origin/animation/functions/permutation')
        require(cache.span(placement+56,8) == bytes(8), 'Unsupported teleporter region permutation')
        position = cache.unpack('<3f',placement+8)
        angles = cache.unpack('<3f',placement+20)
        require(all(math.isfinite(x) for x in position+angles), 'Non-finite teleporter placement')
        basis = rotation_basis(angles)
        cls, model, model_name = cache.tag(cache.u32(obj+0x34))
        require(cls == 'mode' and model_name == TELEPORTER_BASE, 'Unsupported teleporter model')
        nc,np = cache.unpack('<II',model+0xb8)
        require(nc == 1 and cache.unpack('<7f',cache.pointer(np)+40) == (0.,0.,0.,0.,0.,0.,1.),
                'Teleporter requires one identity model node')
        rc,rp = cache.unpack('<II',model+0xc4)
        require(rc == 1, 'Unsupported teleporter model region count')
        pc,pp = cache.unpack('<II',cache.pointer(rp)+64)
        require(pc == 1 and cache.unpack('<h',cache.pointer(pp)+36)[0] == 0 and
                cache.unpack('<5h',cache.pointer(pp)+64) == (0,0,0,0,0),
                'Unsupported teleporter model permutation/LOD')
        gc,gp = cache.unpack('<II',model+0xd0)
        require(gc == 1, 'Unsupported teleporter geometry count')
        part_count,part_pointer = cache.unpack('<II',cache.pointer(gp)+36)
        require(part_count == 5, 'Unsupported teleporter model parts')
        sc,sp = cache.unpack('<II',model+0xdc)
        require(sc == 5, 'Unsupported teleporter model shaders')
        shaders = cache.pointer(sp,sc*32)
        base_scale = cache.unpack('<2f',model+0x30)
        require(all(math.isfinite(x) for x in base_scale), 'Non-finite teleporter model UV scale')
        for part_index in range(part_count):
            part = cache.pointer(part_pointer,part_count*104)+part_index*104
            si = cache.unpack('<H',part+4)[0]
            require(si < sc, 'Invalid teleporter shader index')
            shader_id = cache.u32(shaders+si*32+12)
            permutation = cache.unpack('<h',shaders+si*32+16)[0]
            require(permutation == 0, 'Unsupported teleporter bitmap permutation')
            if shader_id not in materials:
                cls,_,_ = cache.tag(shader_id)
                materials[shader_id] = (environment_material if cls == 'senv' else transparent_material)(
                    cache,shader_id,permutation,texture)
            material = materials[shader_id]
            vc,ic = cache.u32(part+88),cache.u32(part+72)+2
            require(0 < vc <= 65535 and 3 <= ic <= 65537, 'Invalid teleporter geometry counts')
            header = cache.pointer(cache.u32(part+100),12)
            data = cache.pointer(cache.u32(header+4),vc*32)
            first_vertex = len(vertices)//28
            for vi in range(vc):
                v = data+vi*32
                require(cache.span(v+28,4) == b'\x00\xfd\xff\x7f',
                        'Unsupported teleporter skin weights/nodes')
                local = cache.unpack('<3f',v)
                pos = tuple(a+b for a,b in zip(transform_vector(local,basis),position))
                uv = cache.unpack('<2h',v+24)
                uv = tuple((uv[j]*2+1)/65535*base_scale[j] for j in range(2))
                normal = transform_vector(unpack_normal(cache.u32(v+12)),basis)
                require(all(math.isfinite(x) for x in pos+uv+normal), 'Non-finite teleporter vertex')
                vertices.extend(struct.pack('<7f',*pos,*uv,.5,.5))
                normal_data.extend(struct.pack('<3f',*normal))
            strip = cache.unpack('<'+'H'*ic,cache.pointer(cache.u32(part+76),ic*2))
            require(all(i < vc for i in strip), 'Invalid teleporter triangle strip')
            first_index = len(indices)//4
            for ti in range(ic-2):
                triangle = list(strip[ti:ti+3])
                if len(set(triangle)) < 3:
                    continue
                if ti&1:
                    triangle[0],triangle[1] = triangle[1],triangle[0]
                indices.extend(struct.pack('<3I',*(first_vertex+i for i in triangle)))
            meshes.append(dict(material, first_index=first_index,
                               index_count=len(indices)//4-first_index, first_vertex=first_vertex,
                               vertex_count=vc, placement_index=placement_index,
                               position=position, rotation=angles, model=model_name,
                               model_scale=1, permutation='teleporter_base', part_index=part_index))
        exported_placements.append(placement_index)
    return dict(meshes=meshes, placements=exported_placements, normal_data=normal_data)
