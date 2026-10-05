#!/usr/bin/env python3
"""Read-only geometric diagnostic for static-preview roof glyph occlusion.

This is a double-precision ray/decoded-mip0 diagnostic, not GPU coverage or a
pixel-parity oracle. It never changes a shader, geometry, or application bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directions(yaw: float, pitch: float):
    forward = np.array([math.cos(pitch)*math.cos(yaw),
                        math.cos(pitch)*math.sin(yaw), math.sin(pitch)])
    right = np.array([math.sin(yaw), -math.cos(yaw), 0.0])
    up = np.cross(right, forward)
    return forward, right, up


def sample_mip0(texture, uv):
    """Decoded UNORM bilinear repeat sampling solely to select colored points."""
    h, w, _ = texture.shape
    xy = uv*np.array([w, h])-0.5
    base = np.floor(xy).astype(int)
    weight = xy-base
    result = np.zeros((len(uv), 4))
    for dy in (0, 1):
        for dx in (0, 1):
            factor = (weight[:, 0] if dx else 1-weight[:, 0]) * (
                weight[:, 1] if dy else 1-weight[:, 1])
            result += texture[(base[:, 1]+dy) % h, (base[:, 0]+dx) % w]*factor[:, None]
    return result


def nearest_hits(eye, points, triangles):
    """Moller-Trumbore finite rays; native CW front faces have det < 0."""
    a, e1, e2 = triangles[:, 0], triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]
    start = eye-a
    q = np.cross(start, e1)
    numerator = np.einsum('ij,ij->i', e2, q)
    nearest, indices = [], []
    for begin in range(0, len(points), 64):
        ray = points[begin:begin+64]-eye
        p = np.cross(ray[:, None, :], e2[None, :, :])
        det = np.einsum('ij,kij->ki', e1, p)
        with np.errstate(divide='ignore', invalid='ignore'):
            u = np.einsum('ij,kij->ki', start, p)/det
            v = np.einsum('ki,ji->kj', ray, q)/det
            t = numerator[None, :]/det
        valid = (det < -1e-11) & (u >= 0) & (v >= 0) & (u+v <= 1) & (t > 0)
        t = np.where(valid, t, np.inf)
        index = np.argmin(t, axis=1)
        nearest.extend(t[np.arange(len(index)), index].tolist())
        indices.extend(index.tolist())
    return np.asarray(nearest), np.asarray(indices)


def audit(scene_dir: Path, roof_report: Path):
    scene_path = scene_dir/'scene.json'
    scene = json.loads(scene_path.read_bytes())
    vertices = np.frombuffer((scene_dir/'vertices.bin').read_bytes(), '<f4').reshape(-1, 7).astype(float)
    indices = np.frombuffer((scene_dir/'indices.bin').read_bytes(), '<u4')
    opaque_triangles, opaque_meta = [], []
    for mesh in scene['meshes']:
        start = mesh['first_index']
        for offset in range(start, start+mesh['index_count'], 3):
            opaque_triangles.append(vertices[indices[offset:offset+3], :3])
            opaque_meta.append({'source_triangle': offset//3, 'material': mesh['name'],
                                'alpha_test': mesh.get('alpha_test', False)})
    opaque_triangles = np.asarray(opaque_triangles)
    roof = json.loads(roof_report.read_bytes())
    cameras = [{'name': row['name'], 'pose': row['native_saved_camera'],
                'fov': row['native_vertical_fov'], 'recorded': True} for row in roof['cameras']]
    glyphs = [m for m in scene['transparent_bsp_meshes']
              if m['name'] == 'levels\\test\\bloodgulch\\shaders\\bloodgulch light red']
    for z in (3.25, 4.0, 6.5):
        for glyph in glyphs:
            g = vertices[indices[glyph['first_index']:glyph['first_index']+6], :3]
            center = (np.min(g, axis=0)+np.max(g, axis=0))/2
            eye = np.array([95.5, -159.5, z])
            delta = center-eye
            cameras.append({'name': f"center-z{z}-surface{glyph['source_surface_first']}",
                            'pose': [*eye.tolist(), math.atan2(delta[1], delta[0]),
                                     math.atan2(delta[2], math.hypot(delta[0], delta[1]))],
                            'fov': 65.0, 'recorded': False})
    texture_files = set()
    rows = []
    for glyph in glyphs:
        texture_desc = scene['textures'][glyph['textures'][0]]
        texture_path = scene_dir/texture_desc['file']
        texture_files.add(texture_path)
        texture = np.frombuffer(texture_path.read_bytes(), np.uint8).reshape(
            texture_desc['height'], texture_desc['width'], 4).astype(float)
        points, colors, point_normals = [], [], []
        for offset in range(glyph['first_index'], glyph['first_index']+6, 3):
            v = vertices[indices[offset:offset+3]]
            normal = np.cross(v[1, :3]-v[0, :3], v[2, :3]-v[0, :3])
            # Interior barycentric lattice excludes triangle edge ownership.
            weights = np.array([[1-(a+b)/24, a/24, b/24]
                                for a in range(1, 23) for b in range(1, 24-a)])
            xyz, uv = weights@v[:, :3], weights@v[:, 3:5]
            rgb = sample_mip0(texture, uv)[:, :3]
            keep = np.max(rgb, axis=1) >= 64
            points.extend(xyz[keep]); colors.extend(rgb[keep])
            point_normals.extend([normal]*np.count_nonzero(keep))
        points, colors, point_normals = map(np.asarray, (points, colors, point_normals))
        for camera in cameras:
            eye = np.array(camera['pose'][:3]); f, right, up = directions(*camera['pose'][3:])
            delta = points-eye
            view_depth = delta@f
            ndc_y = (delta@up)/(view_depth*math.tan(math.radians(camera['fov'])/2))
            ndc_x = (delta@right)/(view_depth*math.tan(math.radians(camera['fov'])/2)*(640/480))
            front = np.einsum('ij,ij->i', point_normals, eye-points) < 0
            selected = front & (view_depth >= .0625) & (view_depth <= 1024) & (np.abs(ndc_x) <= 1) & (np.abs(ndc_y) <= 1)
            if not np.count_nonzero(selected):
                continue
            selected_points = points[selected]
            t, hits = nearest_hits(eye, selected_points, opaque_triangles)
            blocked = t < 1-1e-10
            finite = np.isfinite(t)
            separated = finite & ~blocked
            depth = view_depth[selected]
            depth_separation = np.full(len(t), np.inf)
            depth_separation[finite] = .0625*1024/(1024-.0625)/depth[finite]*(1-1/t[finite])
            close = separated & (depth_separation < 6*2**-24)
            examples = []
            for n in np.flatnonzero(blocked | close)[:4]:
                examples.append({'position': selected_points[n].tolist(), 'mip0_rgb': colors[selected][n].tolist(),
                                 'nearest_ray_parameter': float(t[n]),
                                 'opaque': opaque_meta[hits[n]],
                                 'depth_separation_float32_ulps': float(depth_separation[n]/2**-24)})
            rows.append({'camera': camera, 'surface': glyph['source_surface_first'],
                         'colored_sample_count': int(np.count_nonzero(selected)),
                         'geometrically_occluded_count': int(np.count_nonzero(blocked)),
                         'within_six_float32_depth_ulps_count': int(np.count_nonzero(close)),
                         'minimum_depth_separation_float32_ulps': float(np.min(depth_separation[finite])/2**-24) if np.any(finite) else None,
                         'occluders': sorted(set(opaque_meta[n]['source_triangle'] for n in hits[blocked])),
                         'examples': examples})
    bound = [scene_path, scene_dir/'vertices.bin', scene_dir/'indices.bin', roof_report,
             Path(__file__).resolve(), *sorted(texture_files)]
    root = Path(__file__).resolve().parents[1]
    bound.extend(root/relative for relative in (
        'port/macos/metal-poc/main.mm', 'port/macos/metal-poc/Scene.metal',
        'port/macos/metal-poc/TransparentBsp.metal', 'port/macos/metal-poc/Decal.metal',
        'source/rasterizer/xbox/rasterizer_xbox_transparent_geometry.c',
        'source/rasterizer/xbox/rasterizer_xbox_decals.c', 'port/linux/src/d3d8_gl.c'))
    return {'kind': 'roof_glyph_geometric_occlusion_audit', 'complete': True,
            'source_sha256': {str(p.resolve()): sha(p) for p in bound},
            'recorded_cameras': 8, 'synthetic_cameras': len(cameras)-8,
            'summary': {'cases': len(rows),
                        'selected_colored_samples': sum(r['colored_sample_count'] for r in rows),
                        'cases_with_geometric_occlusion': sum(r['geometrically_occluded_count'] > 0 for r in rows),
                        'cases_with_depth_separation_under_six_ulps': sum(r['within_six_float32_depth_ulps_count'] > 0 for r in rows)},
            'limitations': ['Double ray intersections are not GPU arithmetic or coverage.',
                           'Colored point selection uses decoded mip0 bilinear RGB; it is not an implicit-LOD pixel oracle.',
                           'Opaque alpha-tested triangles are reported but their fragment discard is not simulated.',
                           'Synthetic poses predict authored geometric occlusion only; they are not original/native paired captures.'],
            'rows': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--roof-report', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error('output already exists')
    result = audit(a.scene.resolve(), a.roof_report.resolve())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
