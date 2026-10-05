"""Original permanent painted-sign decals for the isolated Xbox BSP preview.

This intentionally supports a narrow deterministic subset: one collision BSP,
regular 2D bitmap, fixed radius/color/intensity, no chain, primary painted-sign
layer, axis-snapped placement, additive blend, and no surface wrapping. It uses
the BSP runtime placements and collision polygons, not scenario approximations.
Unsupported definitions are reported and never replaced by synthetic artwork.
Offsets and projection rules follow structure_runtime_decals.c, effects/decals.c,
collision_bsp.c, and rasterizer_xbox_decals.c in the original ILP32 source.
"""
import collections
import math
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def scale(a, s):
    return tuple(x * s for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def normalize(a):
    length = math.sqrt(dot(a, a))
    require(length > 1e-8, 'Degenerate decal basis')
    return scale(a, 1 / length)


def dominant(a):
    # real_math.h: ties select Z, then Y, then X.
    return max(range(3), key=lambda axis: (abs(a[axis]), axis))


def projection_axes(normal):
    axis = dominant(normal)
    mappings = (((2, 1), (1, 2)), ((0, 2), (2, 0)), ((1, 0), (0, 1)))
    return axis, mappings[axis][normal[axis] > 0]


def project(point, axes):
    return tuple(point[axis] for axis in axes)


def unproject(point, plane, axis, axes):
    result = [0., 0., 0.]
    result[axes[0]], result[axes[1]] = point
    require(abs(plane[axis]) > 1e-8, 'Degenerate decal projection')
    result[axis] = (plane[3] - dot(result, plane[:3])) / plane[axis]
    return tuple(result)


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def signed_area(polygon):
    return sum(cross2(polygon[i - 1], p) for i, p in enumerate(polygon)) / 2


def inside(point, polygon, epsilon=1e-6):
    sign = 1 if signed_area(polygon) > 0 else -1
    return all(sign * cross2(sub(p, polygon[i - 1]), sub(point, polygon[i - 1]))
               >= -epsilon for i, p in enumerate(polygon))


def clip_edge(points, edge_start, edge_end, sign):
    """Sutherland-Hodgman clipping, retaining original/intersection flags."""
    if len(points) < 3:
        return [], False
    edge = sub(edge_end, edge_start)
    distances = [sign * cross2(edge, sub(p, edge_start)) for p, _ in points]
    result, clipped = [], False
    previous, previous_distance = points[-1], distances[-1]
    for current, distance in zip(points, distances):
        if (distance >= 0) != (previous_distance >= 0):
            t = previous_distance / (previous_distance - distance)
            result.append((add(previous[0], scale(sub(current[0], previous[0]), t)), True))
            clipped = True
        if distance >= 0:
            result.append(current)
        previous, previous_distance = current, distance
    # Original epsilon=0 discards a polygon entirely on a clipping plane.
    if len(result) < 3 or not any(d > 0 for d in distances):
        return [], clipped
    require(len(result) <= 12, 'Decal clip polygon exceeds original limit')
    return result, clipped


def vector_intersects_sphere(start, end, center, radius):
    # Exact branch structure of real_math.c:fast_vector_intersects_sphere.
    p, direction = sub(start, center), sub(end, start)
    c = dot(p, p) - radius * radius
    if c < 0:
        return True
    b = dot(direction, p)
    if b >= 0:
        return False
    a = dot(direction, direction)
    disc = b * b - a * c
    if disc <= 0:
        return False
    remaining = -a - b
    return remaining < 0 or remaining * remaining < disc


class Collision:
    def __init__(self, cache, bsp, bsp_ptr):
        count, pointer = cache.unpack('<II', bsp + 0xb0)
        require(count == 1, 'Permanent decals require one collision BSP')
        collision = bsp_ptr(pointer, 96)
        self.planes, self.surfaces, self.edges, self.vertices = [], [], [], []
        for offset, stride, fmt, target in (
                (12, 16, '<4f', self.planes), (60, 12, '<iiBBh', self.surfaces),
                (72, 24, '<6i', self.edges), (84, 16, '<3fi', self.vertices)):
            count, pointer = cache.unpack('<II', collision + offset)
            require(0 < count <= 65536, 'Invalid collision decal block count')
            data = bsp_ptr(pointer, count * stride)
            target.extend(cache.unpack(fmt, data + i * stride) for i in range(count))
        self.polygons = [self.polygon(i) for i in range(len(self.surfaces))]

    def plane(self, surface):
        designator = self.surfaces[surface][0] & 0xffffffff
        index = designator & 0x7fffffff
        require(index < len(self.planes), 'Invalid collision plane designator')
        plane = self.planes[index]
        require(all(math.isfinite(x) for x in plane), 'Non-finite collision plane')
        return scale(plane, -1) if designator & 0x80000000 else plane

    def polygon(self, surface):
        first = self.surfaces[surface][1]
        edge_index, result, seen = first, [], set()
        while True:
            require(0 <= edge_index < len(self.edges) and edge_index not in seen,
                    'Invalid collision edge loop')
            seen.add(edge_index)
            require(len(seen) <= 8, 'Collision polygon exceeds original edge limit')
            edge = self.edges[edge_index]
            require(surface in edge[4:6], 'Collision edge does not own surface')
            right = int(edge[5] == surface)
            vertex = edge[right]
            require(0 <= vertex < len(self.vertices), 'Invalid collision vertex index')
            point = self.vertices[vertex][:3]
            require(all(math.isfinite(x) for x in point), 'Non-finite collision vertex')
            result.append((point, edge_index, edge[5 - right]))
            edge_index = edge[2 + right]
            if edge_index == first:
                break
        require(len(result) >= 3, 'Degenerate collision polygon')
        return result

    def raycast(self, origin, direction):
        closest = None
        for surface, polygon in enumerate(self.polygons):
            plane = self.plane(surface)
            denominator = dot(plane[:3], direction)
            if denominator >= -1e-8:
                continue  # Original _collision_test_front_facing_surfaces_bit.
            t = (plane[3] - dot(plane[:3], origin)) / denominator
            if not 0 <= t <= 1 or (closest is not None and t >= closest[0]):
                continue
            point = add(origin, scale(direction, t))
            _, axes = projection_axes(plane[:3])
            if inside(project(point, axes), [project(p[0], axes) for p in polygon]):
                closest = (t, surface, point, plane)
        return closest


def decal_basis(normal, direction):
    require(dot(normal, direction) < -1e-6, 'Decal direction is not front facing')
    axis = dominant(direction)
    axis_vector = tuple((1 if direction[axis] > 0 else -1) if i == axis else 0
                        for i in range(3))
    axis_vector = normalize(sub(axis_vector, normal))
    tangent = cross(normal, axis_vector)
    bitangent = cross(normal, tangent)
    if min(dot(tangent, tangent), dot(bitangent, bitangent)) < 1e-6:
        projected_direction = sub(direction, scale(normal, dot(direction, normal)))
        axis = dominant(projected_direction)
        axis_vector = tuple((1 if projected_direction[axis] > 0 else -1) if i == axis else 0
                            for i in range(3))
        axis_vector = normalize(add(axis_vector, normal) if dot(axis_vector, normal) > 0
                                else sub(axis_vector, normal))
        tangent = cross(normal, axis_vector)
        bitangent = cross(normal, tangent)
    # no_random_rotation: cosine=-1 and sine=0, not an arbitrary upright basis.
    return scale(normalize(bitangent), -1), scale(normalize(tangent), -1)


def geometry(collision, hit, direction, radius, aspect):
    _, start_surface, origin, plane = hit
    normal = plane[:3]
    forward, left = decal_basis(normal, direction)
    quad = [add(origin, add(scale(forward, x), scale(left, y)))
            for x, y in ((-radius, -radius * aspect), (radius, -radius * aspect),
                         (radius, radius * aspect), (-radius, radius * aspect))]
    axis, axes = projection_axes(normal)
    projected_quad = [project(p, axes) for p in quad]
    u_axis, v_axis = sub(projected_quad[1], projected_quad[0]), sub(projected_quad[3], projected_quad[0])
    uv_scale = 1 / cross2(u_axis, v_axis)
    queue, emitted = [start_surface], []
    for surface in queue:
        require(len(queue) <= 1024, 'Decal surface queue exceeds original limit')
        surface_plane = collision.plane(surface)
        polygon = collision.polygons[surface]
        eligible_angle = dot(surface_plane[:3], normal) >= math.cos(math.radians(10))
        points = [(p, False) for p in projected_quad]
        projected_polygon = [project(p[0], axes) for p in polygon]
        sign = 1 if signed_area(projected_polygon) > 0 else -1
        for i, (start, edge_index, adjacent) in enumerate(polygon):
            end = polygon[(i + 1) % len(polygon)][0]
            clipped = True
            if eligible_angle:
                points, clipped = clip_edge(points, project(start, axes), project(end, axes), sign)
            if clipped and adjacent != -1 and adjacent not in queue and \
                    vector_intersects_sphere(start, end, origin, radius * 1.5):
                require(0 <= adjacent < len(collision.surfaces), 'Invalid adjacent surface index')
                queue.append(adjacent)
            if eligible_angle and not points:
                break
        if not eligible_angle or len(points) < 3 or collision.surfaces[surface][2] & 0xb:
            continue
        result = []
        for point, clipped in points:
            relative = sub(point, projected_quad[0])
            uv = (cross2(relative, v_axis) * uv_scale, -cross2(relative, u_axis) * uv_scale)
            # effects/decals.c packs at 32768 with a 32767 upper clamp. Its
            # D3DVSDT_NORMSHORT2 declaration then normalizes the stored short
            # by 32767 (d3d8_gl.c:attribute_format), so maximum UV is exactly 1.
            uv = tuple(math.floor(min(32767., max(0., v * 32768)) + .5) / 32767 for v in uv)
            position = unproject(point, surface_plane, axis, axes)
            # effects/decals.c adds the common normal offset to all vertices,
            # plus a surface normal offset to vertices not created by clipping.
            position = add(position, scale(normal, 1 / 256))
            if not clipped:
                position = add(position, scale(surface_plane[:3], 1 / 256))
            result.append(position + uv)
        emitted.append((surface, result))
    require(sum(len(p) for _, p in emitted) <= 1024, 'Decal vertices exceed original limit')
    return emitted, origin, forward, left


def export_static_decals(cache, scenario, bsp, bsp_ptr, texture, vertices, indices):
    """Append original static signs; return (mesh metadata, skipped counts).

    texture(tag_id, image_index) is the exporter's existing bitmap/mip callback.
    vertices and indices use the preview's <7f> and little-endian uint32 ABI.
    This pass deliberately does not export dynamic impact/blood/effect decals.
    """
    count, pointer = cache.unpack('<II', bsp + 0x258)
    if not count:
        return [], {}
    require(0 < count <= 2048, 'Invalid runtime decal count')
    runtime = bsp_ptr(pointer, count * 16)
    palette_count, palette_pointer = cache.unpack('<II', scenario + 0x3b4)
    require(0 < palette_count <= 256, 'Invalid decal palette count')
    palette = cache.pointer(palette_pointer, palette_count * 16)
    collision, meshes, skipped = Collision(cache, bsp, bsp_ptr), [], collections.Counter()
    for ordinal in range(count):
        origin = cache.unpack('<3f', runtime + ordinal * 16)
        pi, unused, yaw_byte, pitch_byte = cache.unpack('<BBbb', runtime + ordinal * 16 + 12)
        require(pi < palette_count and all(math.isfinite(x) for x in origin),
                'Invalid runtime decal placement')
        tag_id = cache.u32(palette + pi * 16 + 12)
        cls, definition, name = cache.tag(tag_id)
        require(cls == 'deca', 'Expected decal definition')
        flags, kind, layer = cache.unpack('<3H', definition)
        radius_bounds = cache.unpack('<2f', definition + 0x18)
        intensity_bounds = cache.unpack('<2f', definition + 0x2c)
        lower, upper = cache.unpack('<3f', definition + 0x34), cache.unpack('<3f', definition + 0x40)
        blend = cache.unpack('<H', definition + 0xc0)[0]
        bitmap_tag = cache.u32(definition + 0xe4)
        if kind != 3 or layer != 0 or blend != 3 or flags != 0x168 or \
                cache.u32(definition + 0x14) != 0xffffffff:
            skipped['unsupported_definition_or_blend'] += 1
            continue
        if radius_bounds[0] != radius_bounds[1] or intensity_bounds[0] != intensity_bounds[1] or lower != upper:
            skipped['random_radius_color_or_intensity'] += 1
            continue
        radius, intensity = radius_bounds[0], intensity_bounds[0]
        require(math.isfinite(radius) and 0 < radius <= 10 and math.isfinite(intensity) and
                0 <= intensity <= 1 and all(math.isfinite(x) and 0 <= x <= 1 for x in lower),
                'Invalid deterministic decal appearance')
        cls, bitmap, bitmap_name = cache.tag(bitmap_tag)
        require(cls == 'bitm', 'Expected decal bitmap')
        bitmap_count, bitmap_pointer = cache.unpack('<II', bitmap + 96)
        if cache.unpack('<H', bitmap)[0] != 0 or bitmap_count != 1:
            skipped['sprite_or_multiple_bitmap'] += 1
            continue
        bitmap_data = cache.pointer(bitmap_pointer, 48)
        width, height, depth, bitmap_type = cache.unpack('<4H', bitmap_data + 4)
        require(width > 0 and height > 0 and depth == 1 and bitmap_type == 0, 'Invalid decal bitmap dimensions')
        yaw, pitch = yaw_byte * math.pi / 127, pitch_byte * math.pi / 254
        direction = (math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch))
        hit = collision.raycast(origin, direction)
        if hit is None:
            skipped['no_original_collision_hit'] += 1
            continue
        pieces, hit_point, forward, left = geometry(collision, hit, direction, radius, height / width)
        if not pieces:
            skipped['no_supported_collision_geometry'] += 1
            continue
        base_texture = texture(bitmap_tag, 0)
        first_index, source_surfaces, quad_count = len(indices) // 4, [], 0
        for surface, polygon in pieces:
            start = len(vertices) // 28
            for vertex in polygon:
                vertices.extend(struct.pack('<7f', *vertex, 0., 0.))
            for i in range(1, len(polygon) - 1):
                indices.extend(struct.pack('<3I', start, start + i, start + i + 1))
            source_surfaces.append(surface)
            quad_count += (len(polygon) - 1) // 2
        tint = tuple(math.floor(v * 255 + .5) / 255 for v in lower)
        packed_alpha = math.floor(intensity * 255 + .5)
        effective_intensity = ((255 * packed_alpha + 127) >> 8) / 255
        meshes.append(dict(name=name, runtime_index=ordinal, palette_index=pi,
                           definition_tag=tag_id, bitmap_tag=bitmap_tag, bitmap_name=bitmap_name,
                           first_index=first_index, index_count=len(indices) // 4 - first_index,
                           base_texture=base_texture, tint_intensity=list(tint) + [effective_intensity],
                           collision_surfaces=source_surfaces, original_quad_count=quad_count,
                           runtime_origin=origin, collision_position=hit_point, direction=direction,
                           forward=forward, left=left, radius=radius, permanent=True,
                           placement='bsp_runtime_decal', framebuffer_blend='add_one_one',
                           depth_compare='less_equal', depth_write=False, xbox_zbias=8,
                           xbox_zoffset=1 / 256, game_variant_condition=None))
    return meshes, dict(skipped)
