"""Authored Blood Gulch/Hang 'Em High transparent BSP for the Metal POC.

These sections are distinct from permanent decals and scenery models.
Only the cache's observed one-map/no-stage shaders and seven-stage teleporter
shield are supported. Geometry, bitmap permutations, sampler state and authored
animation are preserved; no replacement artwork or generated geometry is used.
"""
import math
import struct

from metal_poc_export import require
from metal_poc_teleporters import (PLASMA_SHADER, packed_color, texture_animation,
                                   transparent_material, unpack_normal)


SIMPLE_SHADERS = {
    r'levels\test\hangemhigh\shaders\hangemhigh blue light',
    r'levels\test\bloodgulch\shaders\cap_moss01b',
    r'levels\test\bloodgulch\shaders\greenlight',
    *(rf'levels\test\bloodgulch\shaders\bloodgulch light {color}'
      for color in ('red', 'yellow', 'blue', 'black')),
}


def bsp_transparent_material(cache, shader_id, permutation, texture):
    cls, shader, name = cache.tag(shader_id)
    require(cls == 'sotr', 'Expected generic transparent BSP shader')
    if name == PLASMA_SHADER:
        result = transparent_material(cache, shader_id, permutation, texture)
        # BSP groups have no shader animation object. In the source's stage
        # color0 evaluation, A_out only overrides the periodic function when
        # group->animation exists. Function ONE therefore selects UPPER colors
        # here, rather than the teleporter scenery's outgoing A=0 lower colors.
        count, pointer = cache.unpack('<II', shader+0x60)
        stages = cache.pointer(pointer, count*112)
        for output, index in enumerate((0, 6)):
            stage = stages+index*112
            require(cache.unpack('<3h', stage+2) == (0, 0, 0),
                    'Unsupported BSP plasma color animation')
            result['constant_colors'][output] = packed_color(cache.unpack('<4f', stage+28))
        result['is_decal'] = False
        result['alpha_test'] = False
        return result
    require(name in SIMPLE_SHADERS, 'Unsupported generic transparent BSP shader')
    _counter, flags, kind, blend, fade, source = cache.unpack('<BB4h', shader+0x28)
    # Source generic branch1850 reads numeric_counter_limit only with numeric
    # flag8 and group animation. A nonzero inactive counter has no runtime
    # meaning here. Numeric shaders remain outside this exact subset.
    require(not flags&8, 'Unsupported numeric transparent BSP shader')
    require(flags in (0, 2) and (kind, blend, fade, source) == (0, 3, 0, 0),
            'Unsupported simple BSP flags/type/blend/fade')
    # Radiosity flags and emitted color are baking metadata. Lit flag4 would
    # select a different runtime vertex program and is deliberately rejected.
    require(not cache.unpack('<H', shader)[0]&4, 'Unsupported lit transparent BSP shader')
    require(cache.u32(shader+0x48) == 0 and cache.unpack('<II', shader+0x60) == (0, 0),
            'Unsupported BSP extra layers or explicit combiner stages')
    count, pointer = cache.unpack('<II', shader+0x54)
    require(count == 1, 'Unsupported simple BSP map count')
    m = cache.pointer(pointer, 100)
    require(cache.unpack('<H', m)[0] == 0, 'Unsupported BSP map sampler flags')
    sx, sy, ox, oy, rotation, bias = cache.unpack('<6f', m+4)
    require(all(math.isfinite(x) for x in (sx, sy, ox, oy, rotation, bias)) and bias == 0,
            'Unsupported BSP map transform or mip bias')
    animation, center = texture_animation(cache, m+44)
    bitmap = cache.u32(m+40)
    require(bitmap != 0xffffffff, 'Missing BSP transparent bitmap')
    record = dict(scale_offset=[sx, sy, ox, oy], u_animation=animation[0],
                  v_animation=animation[1], r_animation=animation[2],
                  rotation_center=[rotation, *center, 0])
    return dict(kind=3, textures=[texture(bitmap, permutation, True), 0, 0, 0],
                maps=[record], constant_colors=[[0.]*4, [0.]*4],
                blend='add', two_sided=False, fade_mode=0,
                is_decal=bool(flags&2), alpha_test=False, name=name)


def append_transparent_bsp(cache, bsp, bsp_ptr, texture, vertices, indices):
    """Append authored triangles; return meshes, normal tail and first_vertex.

    Shared vertex/index ABIs remain <7f>/uint32. `texture` has the exporter's
    (tag_id, bitmap_permutation, is_permutation) signature and owns mip export.
    normal_data contains ONLY newly appended packed3f normals, so the caller
    can retain the preceding scenery normals in its shared normal stream.
    """
    require(cache.name in ('bloodgulch', 'hangemhigh'),
            'Transparent BSP subset is Blood Gulch/Hang Em High only')
    require(len(vertices)%28 == 0 and len(indices)%4 == 0, 'Invalid shared BSP geometry ABI')
    first_vertex = len(vertices)//28
    normal_data, meshes, materials = bytearray(), [], {}
    surface_count, surface_pointer = cache.unpack('<II', bsp+0xf8)
    surfaces = bsp_ptr(surface_pointer, surface_count*6)
    lm_count, lm_pointer = cache.unpack('<II', bsp+0x104)
    lightmaps = bsp_ptr(lm_pointer, lm_count*32)
    for li in range(lm_count):
        count, pointer = cache.unpack('<II', lightmaps+li*32+20)
        material_start = bsp_ptr(pointer, count*256)
        for mi in range(count):
            material = material_start+mi*256
            shader_id = cache.u32(material+12)
            cls, _, _ = cache.tag(shader_id)
            if cls != 'sotr':
                continue
            permutation = cache.unpack('<h', material+16)[0]
            require(permutation >= 0, 'Invalid transparent BSP bitmap permutation')
            key = shader_id, permutation
            if key not in materials:
                materials[key] = bsp_transparent_material(cache, shader_id, permutation, texture)
            first, triangles = cache.unpack('<II', material+20)
            vc, lc = cache.u32(material+0xb4), cache.u32(material+0xc8)
            require(vc > 0 and lc == 0 and first+triangles <= surface_count,
                    'Unsupported transparent BSP geometry or lightmap')
            data = bsp_ptr(cache.u32(material+0xf8), vc*32)
            vertex_base = len(vertices)//28
            for index in range(vc):
                v = data+index*32
                position, uv = cache.unpack('<3f', v), cache.unpack('<2f', v+24)
                # Original BSP generic vertex program24 does not normalize the
                # decoded normal before its abs(dot(normal,-camera.forward)).
                normal = unpack_normal(cache.u32(v+12))
                require(all(math.isfinite(x) for x in position+uv+normal),
                        'Non-finite transparent BSP vertex')
                vertices.extend(struct.pack('<7f', *position, *uv, .5, .5))
                normal_data.extend(struct.pack('<3f', *normal))
            index_base = len(indices)//4
            for triangle in range(first, first+triangles):
                for index in cache.unpack('<3H', surfaces+triangle*6):
                    require(index < vc, 'Transparent BSP triangle index out of bounds')
                    indices.extend(struct.pack('<I', vertex_base+index))
            meshes.append(dict(materials[key], first_index=index_base, index_count=triangles*3,
                               bitmap_permutation=permutation, shader_tag=shader_id,
                               lightmap_index=li, material_index=mi,
                               source_surface_first=first, source_surface_count=triangles))
    return dict(meshes=meshes, normal_data=normal_data, first_vertex=first_vertex)
