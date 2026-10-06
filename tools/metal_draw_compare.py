#!/usr/bin/env python3
"""Compare independent ANGLE and native Metal draw readbacks without image fixes.

Inputs are hashed replay/result JSON records. Color is compared in the original
UNORM byte domain; decoded UNORM floats are not independent float render output.
This gate proves only the declared isolated draw, never full-game/Xbox parity.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


class ComparisonError(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ComparisonError(message)


def uint(value):
    return type(value) is int and 0 <= value < 2**32


def read_json(path):
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ComparisonError(f'Cannot read JSON {path}: {error}') from error
    require(isinstance(value, dict), f'JSON record must be an object: {path}')
    return value


def file_path(base, name):
    require(isinstance(name, str) and bool(name), 'Missing payload filename')
    return (base / name).resolve()


def checked_payload(base, descriptor):
    require(isinstance(descriptor, dict), 'Invalid payload descriptor')
    path = file_path(base, descriptor.get('file'))
    expected = descriptor.get('sha256')
    require(isinstance(expected, str) and len(expected) == 64,
            f'Missing SHA256 for {path}')
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ComparisonError(f'Missing payload {path}: {error}') from error
    require(hashlib.sha256(data).hexdigest() == expected,
            f'Stale or changed payload: {path}')
    if 'size' in descriptor:
        require(uint(descriptor['size']) and len(data) == descriptor['size'],
                f'Wrong payload size: {path}')
    return path, data


def check_descriptors(base, value):
    """Rehash every replay payload, including original capture and mip levels."""
    if isinstance(value, dict):
        if 'file' in value:
            checked_payload(base, value)
        for item in value.values():
            check_descriptors(base, item)
    elif isinstance(value, list):
        for item in value:
            check_descriptors(base, item)


def load_manifest(path):
    manifest = read_json(path)
    require(manifest.get('schema_version') == 1 and
            manifest.get('kind') == 'nv2a_draw_replay', 'Unsupported replay manifest')
    target = manifest.get('target', {})
    require(isinstance(target, dict), 'Missing target')
    width, height = target.get('width'), target.get('height')
    require(uint(width) and uint(height) and 0 < width <= 16384 and
            0 < height <= 16384, 'Invalid target dimensions')
    require(target.get('orientation') == 'top_left', 'Unknown replay orientation')
    clear = target.get('clear_color')
    require(isinstance(clear, list) and len(clear) == 4 and
            all(type(c) in (float, int) and math.isfinite(c) and 0 <= c <= 1
                for c in clear), 'Invalid clear color')
    capture = manifest.get('source_capture')
    require(isinstance(capture, dict) and uint(capture.get('frame')) and
            uint(capture.get('use')), 'Missing original capture identity')
    check_descriptors(path.parent, manifest)
    sources = manifest.get('source_sha256')
    require(isinstance(sources, dict) and bool(sources), 'Missing source hashes')
    for name, expected in sources.items():
        checked_payload(path.parent, {'file': name, 'sha256': expected})
    return manifest


def identity(capture):
    require(isinstance(capture, dict), 'Missing result capture identity')
    return {key: capture.get(key) for key in ('sha256', 'frame', 'use', 'state_sha256')}


def read_attachment(base, descriptor, target, format_name, pixel_bytes):
    require(descriptor.get('format') == format_name, 'Unsupported readback format')
    width, height = target['width'], target['height']
    require(descriptor.get('width') == width and descriptor.get('height') == height,
            'Readback dimensions differ from replay target')
    orientation = descriptor.get('orientation')
    require(orientation in ('top_left', 'bottom_left'), 'Unknown readback orientation')
    _, data = checked_payload(base, descriptor)
    require(len(data) == width * height * pixel_bytes, 'Readback payload size mismatch')
    if orientation == 'bottom_left':
        stride = width * pixel_bytes
        data = b''.join(data[y*stride:(y+1)*stride] for y in range(height-1, -1, -1))
    return data


def load_result(path, manifest_path, manifest, backend):
    result = read_json(path)
    require(result.get('schema_version') == 1 and
            result.get('kind') == 'nv2a_draw_result' and
            result.get('complete') is True, 'Incomplete or unsupported draw result')
    require(result.get('backend') == backend, f'Expected {backend} result')
    require(identity(result.get('source_capture')) == identity(manifest['source_capture']),
            'Result belongs to a different original draw/state capture')
    if backend == 'native_metal':
        require(result.get('manifest_sha256') == digest(manifest_path),
                'Native result belongs to a stale replay manifest')
    require(isinstance(result.get('limits'), list), 'Result must declare verification limits')
    check_descriptors(path.parent, result)
    checked_payload(path.parent, result.get('runner'))
    attachments = {}
    for name, format_name, pixel_bytes in (('color', 'rgba8unorm', 4),
                                           ('depth', 'float32', 4),
                                           ('stencil', 'uint8', 1)):
        if name in result:
            require(isinstance(result[name], dict), f'Invalid {name} descriptor')
            attachments[name] = read_attachment(path.parent, result[name],
                                                manifest['target'], format_name, pixel_bytes)
    require('color' in attachments, 'Missing color readback')
    return result, attachments


def color_metrics(reference, native, width, height, clear, tolerance):
    require(len(reference) == len(native) == width*height*4, 'Color lengths differ')
    require(uint(tolerance) and tolerance <= 255, 'Invalid color tolerance')
    clear_bytes = bytes(int(math.floor(c*255 + .5)) for c in clear)
    total = [0]*4
    maximum = [0]*4
    histogram = [0]*256
    exact = outside = ref_covered = native_covered = coverage_different = 0
    bounds = [width, height, -1, -1]
    for index in range(width*height):
        offset = index*4
        a, b = reference[offset:offset+4], native[offset:offset+4]
        errors = [abs(x-y) for x,y in zip(a,b)]
        largest = max(errors)
        histogram[largest] += 1
        exact += largest != 0
        if largest > tolerance:
            outside += 1
            x,y = index % width, index // width
            bounds = [min(bounds[0],x),min(bounds[1],y),max(bounds[2],x),max(bounds[3],y)]
        for channel,error in enumerate(errors):
            total[channel] += error
            maximum[channel] = max(maximum[channel],error)
        ac,bc = a != clear_bytes,b != clear_bytes
        ref_covered += ac
        native_covered += bc
        coverage_different += ac != bc
    count = width*height
    return dict(pixels=count,exact_different_pixels=exact,
                outside_tolerance_pixels=outside,max_channel_error=maximum,
                mean_channel_error=[n/count for n in total],
                maximum_error_histogram={str(i):n for i,n in enumerate(histogram) if n},
                difference_bounds=bounds if outside else None,
                reference_nonclear_pixels=ref_covered,native_nonclear_pixels=native_covered,
                nonclear_coverage_difference_pixels=coverage_different,
                tolerance_unorm_units=tolerance,
                visible_reference=ref_covered>0,
                passed=outside==0 and ref_covered>0)


def depth_metrics(reference, native, tolerance):
    require(len(reference) == len(native) and len(reference)%4 == 0, 'Depth lengths differ')
    require(math.isfinite(tolerance) and tolerance >= 0, 'Invalid depth tolerance')
    maximum,total,outside,count = 0.0,0.0,0,len(reference)//4
    for (a,), (b,) in zip(struct.iter_unpack('<f',reference),struct.iter_unpack('<f',native)):
        require(math.isfinite(a) and math.isfinite(b), 'Nonfinite depth readback')
        error = abs(a-b)
        maximum = max(maximum,error)
        total += error
        outside += error > tolerance
    return dict(pixels=count,max_error=maximum,mean_error=total/count,
                outside_tolerance_pixels=outside,tolerance=tolerance,passed=outside==0)


def compare(manifest_path, reference_path, native_path, color_tolerance=0, depth_tolerance=0):
    manifest_path,reference_path,native_path = map(Path,(manifest_path,reference_path,native_path))
    manifest = load_manifest(manifest_path)
    reference,ra = load_result(reference_path,manifest_path,manifest,'angle')
    native,na = load_result(native_path,manifest_path,manifest,'native_metal')
    target = manifest['target']
    color = color_metrics(ra['color'],na['color'],target['width'],target['height'],
                          target['clear_color'],color_tolerance)
    limits = ['One isolated original game draw; not a complete ordered frame.',
              'ANGLE is a working-port reference, not original Xbox NTSC evidence.']
    limits += reference['limits'] + native['limits']
    report = dict(schema_version=1,kind='nv2a_draw_comparison',source_capture=manifest['source_capture'],
                  verifier=dict(file=str(Path(__file__).resolve()),sha256=digest(Path(__file__).resolve())),
                  manifest_sha256=digest(manifest_path),reference_result_sha256=digest(reference_path),
                  native_result_sha256=digest(native_path),target=target,color=color,
                  actual_depth_formats=dict(reference=reference.get('actual_depth_format'),
                                            native=native.get('actual_depth_format')),
                  limits=limits)
    for name in ('depth','stencil'):
        if name in ra and name in na:
            if name == 'depth':
                report[name] = depth_metrics(ra[name],na[name],depth_tolerance)
            else:
                count = sum(a!=b for a,b in zip(ra[name],na[name]))
                report[name] = dict(pixels=len(ra[name]),different_pixels=count,passed=count==0)
        else:
            limits.append(f'{name} comparison missing; attachment parity is unverified.')
    formats = report['actual_depth_formats']
    depth_formats_equal = bool(formats['reference']) and formats['reference'] == formats['native']
    if not depth_formats_equal:
        limits.append('Depth attachment formats differ or are missing; precision parity is unverified.')
    report['color_passed'] = color['passed']
    report['attachment_comparison_passed'] = color['passed'] and depth_formats_equal and all(
        report.get(name,{}).get('passed') is True for name in ('depth','stencil'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--color-tolerance',type=int,default=0,
                        help='Maximum recorded difference in UNORM8 units (default: exact)')
    parser.add_argument('--depth-tolerance',type=float,default=0)
    args = parser.parse_args()
    try:
        result = compare(args.manifest,args.reference,args.native,
                         args.color_tolerance,args.depth_tolerance)
    except (ComparisonError,OSError,ValueError) as error:
        print(f'Draw comparison rejected: {error}',file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['color_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
