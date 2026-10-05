#!/usr/bin/env python3
"""Extract an opaque BSP preview from a user-owned Xbox v5 cache. No SDK needed.

Offsets follow source/{cache,scenario,structures,bitmaps} ILP32 cache layouts.
Environment diffuse textures and their authored Xbox mip chains are exported;
this is deliberately not a playable engine backend or full lighting renderer.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib


def require(condition, message):
    if not condition:
        raise ValueError(message)


def rgb565(value):
    return ((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63,
            (value & 31) * 255 // 31, 255)


def decode_bitmap(raw, width, height, fmt, swizzled):
    """Decode one mip. DXT blocks are linear; swizzled texels use Morton order."""
    require(0 < width <= 4096 and 0 < height <= 4096, "Invalid bitmap dimensions")
    out = bytearray(width * height * 4)
    if fmt in (14, 15, 16):
        require(not swizzled, "Compressed + swizzled bitmap is unsupported")
        step = 8 if fmt == 14 else 16
        require(len(raw) >= ((width + 3) // 4) * ((height + 3) // 4) * step,
                "Truncated DXT bitmap")
        offset = 0
        for by in range(0, height, 4):
            for bx in range(0, width, 4):
                block = raw[offset:offset + step]
                offset += step
                a, b, bits = struct.unpack_from('<HHI', block, step - 8)
                colors = [rgb565(a), rgb565(b)]
                if a > b or fmt != 14:
                    colors += [tuple((2 * colors[0][i] + colors[1][i]) // 3 for i in range(4)),
                               tuple((colors[0][i] + 2 * colors[1][i]) // 3 for i in range(4))]
                else:
                    colors += [tuple((colors[0][i] + colors[1][i]) // 2 for i in range(4)), (0, 0, 0, 0)]
                alpha = [255] * 16
                if fmt == 15:
                    abits = int.from_bytes(block[:8], 'little')
                    alpha = [((abits >> (i * 4)) & 15) * 17 for i in range(16)]
                elif fmt == 16:
                    a0, a1 = block[:2]
                    ramp = [a0, a1]
                    ramp += ([(a0 * (7 - i) + a1 * i) // 7 for i in range(1, 7)] if a0 > a1
                             else [(a0 * (5 - i) + a1 * i) // 5 for i in range(1, 5)] + [0, 255])
                    abits = int.from_bytes(block[2:8], 'little')
                    alpha = [ramp[(abits >> (i * 3)) & 7] for i in range(16)]
                for i in range(16):
                    x, y = bx + i % 4, by + i // 4
                    if x < width and y < height:
                        color = colors[(bits >> (i * 2)) & 3]
                        target = (y * width + x) * 4
                        out[target:target + 4] = bytes(color[:3] + (color[3] if fmt == 14 else alpha[i],))
    elif fmt in (0, 1, 2, 6, 8, 9, 10, 11):
        stride = 4 if fmt in (10, 11) else (1 if fmt in (0, 1, 2) else 2)
        require(len(raw) >= width * height * stride, "Truncated raw bitmap")
        if swizzled:
            require(width & (width - 1) == height & (height - 1) == 0,
                    "Swizzled dimensions must be powers of two")
        for y in range(height):
            for x in range(width):
                source = y * width + x
                if swizzled:
                    source, destbit, bit = 0, 1, 1
                    while bit < max(width, height):
                        if bit < width:
                            if x & bit:
                                source |= destbit
                            destbit <<= 1
                        if bit < height:
                            if y & bit:
                                source |= destbit
                            destbit <<= 1
                        bit <<= 1
                value = int.from_bytes(raw[source * stride:(source + 1) * stride], 'little')
                if fmt == 0:
                    color = (255, 255, 255, value)
                elif fmt == 1:
                    color = (value, value, value, 255)
                elif fmt == 2:
                    # AY8 stores the same eight-bit value in alpha and luminance.
                    color = (value, value, value, value)
                elif fmt == 6:
                    color = rgb565(value)
                elif fmt == 8:
                    color = (((value >> 10) & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31,
                             (value & 31) * 255 // 31, 255 if value & 32768 else 0)
                elif fmt == 9:
                    color = (((value >> 8) & 15) * 17, ((value >> 4) & 15) * 17,
                             (value & 15) * 17, ((value >> 12) & 15) * 17)
                else:
                    color = ((value >> 16) & 255, (value >> 8) & 255, value & 255,
                             (value >> 24) & 255 if fmt == 11 else 255)
                target = (y * width + x) * 4
                out[target:target + 4] = bytes(color)
    else:
        raise ValueError(f"Unsupported bitmap format {fmt}")
    return out


def bitmap_mipmap_layout(width, height, fmt, flags, mipmap_count):
    """Return hardware-visible levels as (width, height, offset, size, pitch).

    Halo's rasterizer_swizzle.c caps compressed mip indices at the largest
    dimension divided by four. The remaining bytes are cache allocation
    padding, not extra 2x2/1x1 levels. Linear textures have one level with
    64-byte-aligned rows; DXT and Morton levels follow each other directly.
    """
    require(0 < width <= 4096 and 0 < height <= 4096, 'Invalid bitmap dimensions')
    require(fmt in (0, 1, 2, 6, 8, 9, 10, 11, 14, 15, 16),
            f'Unsupported bitmap format {fmt}')
    compressed = fmt in (14, 15, 16)
    require(bool(flags & 2) == compressed, 'Bitmap compression flag disagrees with format')
    require(not (flags & 8 and (compressed or flags & 16)), 'Invalid swizzled bitmap layout')
    require(not (compressed and flags & 16), 'Compressed linear bitmap is unsupported')
    power_of_two = width & (width - 1) == 0 and height & (height - 1) == 0
    require(not flags & 1 or power_of_two, 'Invalid power-of-two bitmap flag')
    require(not flags & 8 or power_of_two, 'Swizzled dimensions must be powers of two')
    require(0 <= mipmap_count <= max(width, height).bit_length() - 1,
            'Invalid bitmap mipmap count')
    maximum = 0
    if flags & 1 and not flags & 16:
        maximum = min(mipmap_count, max(width // 4, height // 4, 1).bit_length() - 1
                      if compressed else max(width, height).bit_length() - 1)
    stride = 4 if fmt in (10, 11) else (1 if fmt in (0, 1, 2) else 2)
    offset, levels = 0, []
    for level in range(maximum + 1):
        w, h = max(1, width >> level), max(1, height >> level)
        if compressed:
            pitch = ((w + 3) // 4) * (8 if fmt == 14 else 16)
            size = pitch * ((h + 3) // 4)
        else:
            pitch = w * stride
            if flags & 16:
                pitch = (pitch + 63) & ~63
            size = pitch * h
        levels.append((w, h, offset, size, pitch))
        offset += size
    return levels


def decode_bitmap_mipmaps(raw, width, height, fmt, flags, mipmap_count):
    """Decode every authored level visible to the original Xbox texture."""
    layout = bitmap_mipmap_layout(width, height, fmt, flags, mipmap_count)
    require(len(raw) >= sum(level[3] for level in layout), 'Truncated bitmap mip chain')
    levels = []
    for w, h, offset, size, pitch in layout:
        pixels = raw[offset:offset + size]
        if flags & 16:
            stride = 4 if fmt in (10, 11) else (1 if fmt in (0, 1, 2) else 2)
            pixels = b''.join(pixels[y * pitch:y * pitch + w * stride] for y in range(h))
        levels.append(dict(width=w, height=h,
                           rgba=decode_bitmap(pixels, w, h, fmt, bool(flags & 8))))
    return levels


class Cache:
    def __init__(self, path):
        require(path.stat().st_size <= 128 * 1024 * 1024, "Cache exceeds POC size limit")
        raw = path.read_bytes()
        require(len(raw) >= 2048 and raw[:4] == b'daeh' and raw[2044:2048] == b'toof',
                "Not a Halo cache")
        self.sha256 = hashlib.sha256(raw).hexdigest()
        version, size = struct.unpack_from('<II', raw, 4)
        require(version == 5, "POC supports Xbox version 5 caches only")
        require(2048 <= size <= 128 * 1024 * 1024, "Invalid cache size")
        if len(raw) != size:
            decoder = zlib.decompressobj()
            body = decoder.decompress(raw[2048:], size - 2048 + 1)
            require(decoder.eof and len(body) == size - 2048, "Invalid compressed cache size")
            raw = raw[:2048] + body
        self.data = raw
        self.tag_offset = self.u32(16)
        self.tag_base = self.u32(self.tag_offset) - 36
        self.tag_size = self.u32(20)
        self.span(self.tag_offset, self.tag_size)
        self.tag_count = self.u32(self.tag_offset + 12)
        require(0 < self.tag_count <= 65535, "Invalid tag count")
        self.span(self.tag_offset + 36, self.tag_count * 32)
        self.name = raw[32:64].split(b'\0')[0].decode('ascii')

    def span(self, offset, size):
        require(offset >= 0 and size >= 0 and offset + size <= len(self.data), "Cache range out of bounds")
        return self.data[offset:offset + size]

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.span(offset, struct.calcsize(fmt)))

    def u32(self, offset):
        return self.unpack('<I', offset)[0]

    def pointer(self, pointer, size=1):
        relative = pointer - self.tag_base
        require(0 <= relative and relative + size <= self.tag_size, "Tag pointer out of bounds")
        return self.tag_offset + relative

    def tag(self, tag_id):
        index = tag_id & 65535
        require(index < self.tag_count, "Invalid tag reference")
        offset = self.tag_offset + 36 + index * 32
        require(self.u32(offset + 12) == tag_id, "Tag ID salt mismatch")
        name_offset = self.pointer(self.u32(offset + 16))
        name = self.span(name_offset, min(512, len(self.data) - name_offset)).split(b'\0')[0].decode('ascii')
        return self.span(offset, 4)[::-1].decode('ascii'), self.pointer(self.u32(offset + 20)), name


def sky_geometry_indices(cache, model, geometry_count):
    """Select authored sky region geometries only when permutation/LOD is unambiguous.

    models.c renders the region's selected permutation, not every geometry in
    the tag. These static sky models use one permutation with identical geometry
    at all five detail levels. Reject alternate/LOD/animation selection rather
    than letting a new map silently draw extra geometry.
    """
    count, pointer = cache.unpack('<II', model + 0xc4)
    require(0 < count <= 32, 'Unsupported sky region count')
    regions = cache.pointer(pointer, count * 76)
    selected = []
    for index in range(count):
        region = regions + index * 76
        permutations, address = cache.unpack('<II', region + 64)
        require(permutations == 1, 'Sky alternate permutations are not supported')
        permutation = cache.pointer(address, 88)
        require(cache.u32(permutation + 32) == 0, 'Unsupported sky permutation flags')
        levels = cache.unpack('<5h', permutation + 64)
        require(len(set(levels)) == 1, 'Sky LOD selection is not supported')
        geometry = levels[0]
        require(geometry == -1 or 0 <= geometry < geometry_count, 'Sky region geometry out of bounds')
        if geometry != -1:
            selected.append(geometry)
    require(selected, 'Sky model has no selected region geometry')
    return selected


def export(map_path, output):
    cache = Cache(map_path)
    u32 = cache.u32
    _, scenario, _ = cache.tag(u32(cache.tag_offset + 4))
    count, pointer = cache.unpack('<II', scenario + 0x5a4)
    require(count == 1, "POC currently supports single-BSP maps")
    bsp_offset, bsp_size, bsp_address = cache.unpack('<III', cache.pointer(pointer, 32))
    cache.span(bsp_offset, bsp_size)

    def bsp_ptr(pointer, size=1):
        relative = pointer - bsp_address
        require(0 <= relative and relative + size <= bsp_size, "BSP pointer out of bounds")
        return bsp_offset + relative

    bsp = bsp_ptr(u32(bsp_offset), 648)
    bounds = cache.unpack('<6f', bsp + 0xc8)
    require(all(math.isfinite(x) for x in bounds), "Invalid world bounds")
    surface_count, surface_pointer = cache.unpack('<II', bsp + 0xf8)
    surfaces = bsp_ptr(surface_pointer, surface_count * 6)
    lm_count, lm_pointer = cache.unpack('<II', bsp + 0x104)
    lm_start = bsp_ptr(lm_pointer, lm_count * 32)
    output.mkdir(parents=True, exist_ok=True)
    textures, texture_indices = [], {}
    # White fallback is explicit for materials without baked lighting.
    (output / 'texture-0.rgba').write_bytes(bytes([255] * 4))
    textures.append(dict(file='texture-0.rgba', width=1, height=1, name='white',
                         mipmaps=[dict(file='texture-0.rgba', width=1, height=1)]))
    (output / 'texture-1.rgba').write_bytes(bytes([128, 128, 128, 255]))
    textures.append(dict(file='texture-1.rgba', width=1, height=1, name='neutral detail',
                         mipmaps=[dict(file='texture-1.rgba', width=1, height=1)]))

    def texture(tag_id, image_index=0, permutation=False):
        if tag_id == 0xffffffff or image_index < 0:
            return 0
        cls, bitmap, name = cache.tag(tag_id)
        require(cls == 'bitm', "Expected bitmap tag")
        n, p = cache.unpack('<II', bitmap + 96)
        require(n > 0, 'Bitmap group has no images')
        if permutation:
            image_index %= n
        require(image_index < n, "Invalid bitmap index")
        key = (tag_id, image_index)
        if key in texture_indices:
            return texture_indices[key]
        data = cache.pointer(p, n * 48) + image_index * 48
        w, h, depth, kind, fmt, flags = cache.unpack('<6H', data + 4)
        require(depth == 1 and kind == 0 and not flags & 256, "Only internal 2D textures supported")
        pixels = cache.span(u32(data + 24), u32(data + 28))
        if fmt == 17:
            from metal_poc_teleporters import decode_p8_bump_mipmaps
            levels = decode_p8_bump_mipmaps(pixels, w, h, flags, cache.unpack('<h', data + 20)[0])
        else:
            levels = decode_bitmap_mipmaps(pixels, w, h, fmt, flags,
                                          cache.unpack('<h', data + 20)[0])
        index = len(textures)
        filename = f'texture-{index}.rgba'
        mipmaps = []
        for level, mip in enumerate(levels):
            mipfile = filename if level == 0 else f'texture-{index}-mip-{level}.rgba'
            (output / mipfile).write_bytes(mip['rgba'])
            mipmaps.append(dict(file=mipfile, width=mip['width'], height=mip['height']))
        record = dict(file=filename, width=w, height=h, name=name, bitmap_index=image_index,
                      source_format=fmt, swizzled=bool(flags & 8), mipmaps=mipmaps)
        if fmt == 14:
            # Preserve Xbox DXT1 blocks for native BC1 sampling. The decoded
            # files remain available for inspection and older preview tools.
            layout = bitmap_mipmap_layout(w, h, fmt, flags, cache.unpack('<h', data + 20)[0])
            native_mipmaps = []
            for level, (mw, mh, offset, size, _pitch) in enumerate(layout):
                blockfile = f'texture-{index}-mip-{level}.bc1'
                (output / blockfile).write_bytes(pixels[offset:offset + size])
                native_mipmaps.append(dict(file=blockfile, width=mw, height=mh))
            record.update(native_format='bc1_rgba', native_file=native_mipmaps[0]['file'],
                          native_mipmaps=native_mipmaps)
        textures.append(record)
        texture_indices[key] = index
        return index

    vertices, indices = bytearray(), bytearray()
    meshes, skipped = [], collections.Counter()
    for lightmap_index in range(lm_count):
        lightmap = lm_start + lightmap_index * 32
        bitmap_index = cache.unpack('<h', lightmap)[0]
        n, p = cache.unpack('<II', lightmap + 20)
        materials = bsp_ptr(p, n * 256)
        for i in range(n):
            material = materials + i * 256
            cls, shader, name = cache.tag(u32(material + 12))
            if cls != 'senv':
                skipped[cls] += 1
                continue
            permutation = cache.unpack('<h', material + 16)[0]
            require(permutation >= 0, 'Invalid material bitmap permutation')
            first, count = cache.unpack('<II', material + 20)
            require(first + count <= surface_count, "Material surfaces out of bounds")
            vc, lc = u32(material + 0xb4), u32(material + 0xc8)
            require(vc > 0 and lc in (0, vc), "Unsupported vertex/lightmap counts")
            data = bsp_ptr(u32(material + 0xec + 12), vc * 32 + lc * 8)
            vertex_start = len(vertices) // 28
            for v in range(vc):
                position = cache.unpack('<3f', data + v * 32)
                uv = cache.unpack('<2f', data + v * 32 + 24)
                lmuv = (0.5, 0.5)
                if lc:
                    packed_uv = cache.unpack('<2h', data + vc * 32 + v * 8 + 4)
                    lmuv = tuple((value * 2 + 1) / 65535 for value in packed_uv)
                values = position + uv + lmuv
                require(all(math.isfinite(x) for x in values), "Non-finite vertex")
                vertices.extend(struct.pack('<7f', *values))
            index_start = len(indices) // 4
            for triangle in range(first, first + count):
                for index in cache.unpack('<3H', surfaces + triangle * 6):
                    require(index < vc, "Triangle vertex index out of range")
                    indices.extend(struct.pack('<I', vertex_start + index))
            base = texture(u32(shader + 0x88 + 12), permutation, True)
            detail_indices, detail_scales = [], []
            rescale = cache.unpack('<H', shader + 0x6c)[0] & 1
            for offset in (0xb8, 0xcc, 0xfc):
                tag = u32(shader + offset + 12)
                detail = texture(tag, permutation, True) if tag != 0xffffffff else 1
                scale = cache.unpack('<f', shader + offset - 4)[0]
                require(math.isfinite(scale), 'Invalid detail scale')
                detail_indices.append(detail)
                detail_scales += [scale * textures[base][dimension] / textures[detail][dimension]
                                  if rescale else scale for dimension in ('width', 'height')]
            meshes.append(dict(name=name, first_index=index_start, index_count=count * 3,
                               base_texture=base, detail_textures=detail_indices, detail_scales=detail_scales,
                               bitmap_permutation=permutation,
                               shader_type=cache.unpack('<H', shader + 0x2a)[0],
                               detail_function=cache.unpack('<H', shader + 0xb0)[0],
                               micro_function=cache.unpack('<H', shader + 0xf4)[0],
                               lightmap_texture=texture(u32(bsp + 12), bitmap_index) if lc else 0,
                               alpha_test=bool(cache.unpack('<H', shader + 0x28)[0] & 1)))
    require(meshes, "No supported environment materials found")
    bsp_triangles = len(indices) // 12
    sky_meshes, fog = [], dict(color=[0., 0., 0.], density=0., start=0., end=0.,
                              enabled=False, density_texture=0, planar_mode=0)
    sky_count, sky_pointer = cache.unpack('<II', scenario + 0x30)
    if sky_count:
        cls, sky, sky_name = cache.tag(u32(cache.pointer(sky_pointer, sky_count * 16) + 12))
        require(cls == 'sky ' and sky_count == 1, 'Fog preview requires one outdoor sky')
        require(all(u32(bsp + offset) == 0 for offset in (0x178, 0x184, 0x190)),
                'Planar fog is not supported by this preview')
        cluster_count, cluster_pointer = cache.unpack('<II', bsp + 0x134)
        clusters = bsp_ptr(cluster_pointer, cluster_count * 104) if cluster_count else 0
        require(cluster_count > 0 and all(cache.unpack('<2h', clusters + ci * 104) == (0, -1)
                                         for ci in range(cluster_count)),
                'Fog preview requires outdoor clusters without planar fog')
        require(u32(sky + 0xa4) == 0xffffffff, 'Indoor fog screens are not supported by this preview')
        source_color = cache.unpack('<3f', sky + 0x58)
        source_density, source_start, source_end = cache.unpack('<3f', sky + 0x6c)
        require(all(math.isfinite(v) for v in source_color + (source_density, source_start, source_end)) and
                all(0 <= v <= 1 for v in source_color) and source_density <= 1,
                'Invalid atmospheric fog settings')
        # scenario.c:1453 and rasterizer_xbox.c:888-898 normalize these values.
        enabled = source_end != 0
        density = (source_density if source_density > 0 else 1.) if enabled else 0.
        end = max(source_end, source_start + .0001) if enabled else 0.
        globals_tags = [u32(cache.tag_offset + 36 + ti * 32 + 12) for ti in range(cache.tag_count)
                        if cache.span(cache.tag_offset + 36 + ti * 32, 4) == b'gtam']
        require(len(globals_tags) == 1, 'Expected one game globals tag for atmospheric fog')
        _, globals_data, _ = cache.tag(globals_tags[0])
        rasterizer_count, rasterizer_pointer = cache.unpack('<II', globals_data + 0x134)
        require(rasterizer_count == 1, 'Expected one rasterizer globals block')
        rasterizer = cache.pointer(rasterizer_pointer, 48)
        density_tag = u32(rasterizer + 32 + 12)
        require(density_tag != 0xffffffff, 'Missing atmospheric fog density lookup')
        fog = dict(color=[round(v * 255) / 255 for v in source_color],
                   density=round(density * 255) / 255, start=source_start, end=end, enabled=enabled,
                   density_texture=texture(density_tag), planar_mode=0, source_sky=sky_name,
                   source_color=source_color, source_density=source_density,
                   source_start=source_start, source_end=source_end,
                   scope='Outdoor atmospheric fog; no planar fog or indoor transitions')
        cls, model, _ = cache.tag(u32(sky + 12))
        require(cls == 'mode', 'Only Xbox sky models supported')
        node_count, node_pointer = cache.unpack('<II', model + 0xb8)
        require(node_count == 1 and cache.unpack('<7f', cache.pointer(node_pointer) + 40) ==
                (0., 0., 0., 0., 0., 0., 1.), 'POC sky requires one identity node')
        model_scale = cache.unpack('<2f', model + 0x30)
        shader_count, shader_pointer = cache.unpack('<II', model + 0xdc)
        shaders = cache.pointer(shader_pointer, shader_count * 32)
        geometry_count, geometry_pointer = cache.unpack('<II', model + 0xd0)
        geometries = cache.pointer(geometry_pointer, geometry_count * 48)
        selected_sky_geometry = sky_geometry_indices(cache, model, geometry_count)
        for gi in selected_sky_geometry:
            part_count, part_pointer = cache.unpack('<II', geometries + gi * 48 + 36)
            parts = cache.pointer(part_pointer, part_count * 104)
            for pi in range(part_count):
                part = parts + pi * 104
                si = cache.unpack('<H', part + 4)[0]
                require(si < shader_count, 'Invalid sky shader index')
                cls, shader, name = cache.tag(u32(shaders + si * 32 + 12))
                require(cls in ('sotr', 'schi') and cache.unpack('<H', shader + 0x2c)[0] == 0,
                        'Unsupported sky shader/blend mode')
                n, p = cache.unpack('<II', shader + 0x54)
                require(1 <= n <= 3, 'Unsupported sky texture count')
                if cls == 'sotr':
                    require(n == 1 and u32(shader + 0x60) == 0, 'Unsupported generic sky combiner')
                sky_textures, sky_scales = [], []
                for mi in range(n):
                    m = cache.pointer(p, n * (100 if cls == 'sotr' else 220)) + mi * (100 if cls == 'sotr' else 220)
                    map_offset, scale_offset = (0x1c, 4) if cls == 'sotr' else (0x6c, 0x54)
                    sky_textures.append(texture(u32(m + map_offset + 12)))
                    scale = cache.unpack('<5f', m + scale_offset)
                    require(scale[2:] == (0., 0., 0.), 'Unsupported sky UV transform')
                    sky_scales += scale[:2]
                    if cls == 'schi':
                        expected = ((2, 2), (0, 0)) if n == 2 else ((2, 0), (4, 0), (0, 0))
                        require(cache.unpack('<2H', m + 44) == expected[mi], 'Unsupported Chicago sky combiner')
                sky_textures += [0] * (3 - n)
                sky_scales += [1.] * (6 - len(sky_scales))
                vc, ic = u32(part + 88), u32(part + 72) + 2
                vertex_header = cache.pointer(u32(part + 100), 12)
                data = cache.pointer(u32(vertex_header + 4), vc * 32)
                vertex_start = len(vertices) // 28
                for vi in range(vc):
                    pos = cache.unpack('<3f', data + vi * 32)
                    uv = cache.unpack('<2h', data + vi * 32 + 24)
                    uv = tuple((uv[j] * 2 + 1) / 65535 * model_scale[j] for j in range(2))
                    require(all(math.isfinite(v) for v in pos + uv), 'Non-finite sky vertex')
                    vertices.extend(struct.pack('<7f', *pos, *uv, 0, 0))
                strip = cache.unpack('<' + 'H' * ic, cache.pointer(u32(part + 76), ic * 2))
                require(all(i < vc for i in strip), 'Invalid sky index')
                first = len(indices) // 4
                for ti in range(ic - 2):
                    triangle = list(strip[ti:ti + 3])
                    if len(set(triangle)) < 3:
                        continue
                    if ti & 1:
                        triangle[0], triangle[1] = triangle[1], triangle[0]
                    indices.extend(struct.pack('<3I', *(vertex_start + v for v in triangle)))
                sky_meshes.append(dict(name=name, first_index=first, index_count=len(indices) // 4 - first,
                                       textures=sky_textures, scales=sky_scales, kind=n))
    decal_meshes, decal_skipped, teleporter_meshes, teleporter_placements = [], {}, [], []
    transparent_bsp_meshes = []
    if cache.name == 'bloodgulch':
        from metal_poc_decals import export_static_decals
        from metal_poc_teleporters import append_teleporters
        from metal_poc_transparent_bsp import append_transparent_bsp
        decal_meshes, decal_skipped = export_static_decals(cache, scenario, bsp, bsp_ptr, texture, vertices, indices)
        teleporters = append_teleporters(cache, scenario, vertices, indices, texture)
        teleporter_meshes, teleporter_placements = teleporters['meshes'], teleporters['placements']
        normal_data = teleporters['normal_data']
        transparent = append_transparent_bsp(cache, bsp, bsp_ptr, texture, vertices, indices)
        require(len(normal_data) == transparent['first_vertex'] * 12,
                'Transparent BSP normal stream does not follow scenery')
        normal_data = bytes(normal_data) + bytes(transparent['normal_data'])
        transparent_bsp_meshes = transparent['meshes']
        bsp_triangles += sum(m['index_count'] // 3 for m in transparent_bsp_meshes)
        skipped['sotr'] -= len(transparent_bsp_meshes)
        require(skipped['sotr'] == 0, 'Incomplete transparent BSP export')
        del skipped['sotr']
    else:
        normal_data = bytes(len(vertices) // 28 * 12)
        if cache.name == 'hangemhigh':
            from metal_poc_transparent_bsp import append_transparent_bsp
            transparent = append_transparent_bsp(cache, bsp, bsp_ptr, texture, vertices, indices)
            require(len(normal_data) == transparent['first_vertex'] * 12,
                    'Transparent BSP normal stream does not follow sky geometry')
            normal_data += bytes(transparent['normal_data'])
            transparent_bsp_meshes = transparent['meshes']
            bsp_triangles += sum(m['index_count'] // 3 for m in transparent_bsp_meshes)
            skipped['sotr'] -= len(transparent_bsp_meshes)
            require(skipped['sotr'] == 0, 'Incomplete transparent BSP export')
            del skipped['sotr']
    require(len(normal_data) == len(vertices) // 28 * 12, 'Invalid shared normal stream')
    (output / 'teleporter_normals.bin').write_bytes(normal_data)
    (output / 'vertices.bin').write_bytes(vertices)
    (output / 'indices.bin').write_bytes(indices)
    spawn_count, spawn_pointer = cache.unpack('<II', scenario + 0x354)
    spawn = cache.unpack('<4f', cache.pointer(spawn_pointer, 52)) if spawn_count else (
        (bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, bounds[5], 0)
    require(all(math.isfinite(x) for x in spawn), "Invalid spawn")
    # rasterizer_xbox.c:1707 clears to the current atmospheric fog color.
    # real_rgb_color_to_pixel32 uses rint(channel*255), ties to even, just
    # like Python round; retain the actual cache color rather than a tint.
    clear_color = [round(v * 255) / 255 for v in fog.get('source_color', fog['color'])]
    manifest = dict(version=1, map=cache.name, source_sha256=cache.sha256,
                    clear_color=clear_color,
                    bounds=bounds, camera=[spawn[0], spawn[1], spawn[2] + 1.5, spawn[3]],
                    vertex_count=len(vertices) // 28, triangle_count=len(indices) // 12,
                    meshes=meshes, sky_meshes=sky_meshes, fog=fog, bsp_triangles=bsp_triangles,
                    decal_meshes=decal_meshes, decal_skipped=decal_skipped,
                    teleporter_meshes=teleporter_meshes, teleporter_placements=teleporter_placements,
                    transparent_bsp_meshes=transparent_bsp_meshes,
                    textures=textures, skipped_materials=dict(skipped),
                    limitations=['static BSP with original sky, outdoor fog, decals and selected scenery',
                                 'full BSP/object bump, radiosity and cube/specular lighting not implemented',
                                 'no gameplay, activation effects, sky UV animation or water'])
    (output / 'scene.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f"{cache.name}: {len(meshes)} draws, {manifest['triangle_count']} triangles, "
          f"{len(textures)} textures; skipped materials: {dict(skipped)}")
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('map', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    export(args.map, args.output)
