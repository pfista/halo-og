#!/usr/bin/env python3
"""Freeze and validate a complete ordered original-renderer frame capture.

This is a resource/command importer, not a tag-based scene exporter. It preserves
raw payloads and logical Xbox top-first GPU readbacks. No game or GPU is run.
Failed raw captures remain intact and are never upgraded into complete frames.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from metal_shader_validate import load_corpus


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def checked_path(base, value):
    require(isinstance(value, str), 'Resource path is not a string')
    path = (base / value).resolve()
    require(path.is_relative_to(base.resolve()), 'Resource escapes the frame package')
    require(path.is_file(), f'Missing captured resource: {value}')
    return path


def hash_payloads(base, value, hashes):
    """Attach cryptographic hashes recursively without changing the raw record."""
    if isinstance(value, list):
        return [hash_payloads(base, item, hashes) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: hash_payloads(base, item, hashes) for key, item in value.items()}
    if 'file' in value and 'bytes' in value:
        path = checked_path(base, value['file'])
        data = path.read_bytes()
        require(type(value['bytes']) is int and len(data) == value['bytes'],
                f'Payload byte count mismatch: {value["file"]}')
        result['sha256'] = sha256(data)
        hashes[value['file']] = dict(bytes=len(data), sha256=result['sha256'])
    return result


def target_key(ref):
    require(isinstance(ref, dict) and type(ref.get('target_id')) is int and
            type(ref.get('version')) is int and ref['version'] >= 0,
            'Invalid target version reference')
    return ref['target_id'], ref['version']


def validate_sequence(status, events, draws, targets, uses):
    """Check shader pairing and per-target history, including offscreen aliases."""
    require(status.get('schema_version') == 1 and status.get('kind') == 'captured_frame'
            and status.get('complete') is True, 'Original frame collector did not complete')
    require(status.get('orientation') == 'top_left', 'Unverified readback orientation')
    require(status['event_count'] == len(events), 'Event count differs from final marker')
    require(events and events[-1].get('kind') == 'present', 'Frame did not end in Present')
    counts = dict(draw=0, clear=0, target_bind=0, texture_copy=0, generate_mipmaps=0)
    history = {}
    seen_uses = set()
    query_open = False
    for index, event in enumerate(events):
        require(event.get('event') == index and event.get('frame') == status['frame'],
                'Frame commands are missing or out of order')
        kind = event.get('kind')
        require(kind in {*counts, 'present', 'visibility_begin', 'visibility_end',
                         'visibility_cpu_result', 'visibility_gpu_result'},
                f'Unsupported frame operation {kind}')
        if kind in counts:
            counts[kind] += 1
        # Collectors currently reject GPU mip-copy output/version gaps. Do not
        # silently replay those operations from stale source texture bytes.
        require(kind not in ('texture_copy', 'generate_mipmaps'),
                'GPU copy/mipmap version capture is not yet complete')
        if kind == 'visibility_begin':
            require(not query_open and not event['atomic_counters'],
                    'Unsupported nested/atomic visibility query')
            query_open = True
        elif kind == 'visibility_end':
            require(query_open and not event['atomic_counters'], 'Visibility query end mismatch')
            query_open = False
        elif kind == 'visibility_gpu_result':
            require(event.get('available') is True and
                    event.get('any_samples_passed') in (0, 1),
                    'Visibility GPU result is unavailable')
        if kind == 'draw':
            require(event.get('draw') in draws, 'Ordered draw record is missing')
            draw = draws[event['draw']]
            require(draw.get('complete') is True and draw.get('frame') == status['frame'],
                    'Original draw record is incomplete')
            use_id = draw.get('use')
            require(type(use_id) is int and use_id == event.get('use') and
                    0 <= use_id < len(uses) and use_id not in seen_uses,
                    'Draw use is missing, repeated, or mismatched')
            use = uses[use_id]
            require(draw['program_id'] == use['program_id'] and
                    draw['declaration_id'] == use['declaration_id'] and
                    bool(draw['immediate']) == bool(use['immediate']),
                    'Draw is not paired to its original shader use')
            require(draw['before'] == event['before'], 'Draw before-target references disagree')
            require(draw['vertex_constants']['bytes'] == 3072 and
                    draw['draw_uniforms']['bytes'] == 636 and
                    draw['fixed_attributes']['bytes'] == 256,
                    'Captured guest uniform ABI differs from the validated ABI')
            if draw['indices']:
                require(draw['indices']['bytes'] == draw['index_count'] * 2,
                        'Original uint16 index payload is truncated')
            for stream in draw['streams']:
                expected = draw['vertex_count'] * stream['stride'] if stream['stride'] else 64
                require(stream['payload']['bytes'] == expected, 'Vertex stream payload is truncated')
            require(len(draw['textures']) == 4, 'Four original texture stages are required')
            for texture in draw['textures']:
                if texture is None:
                    continue
                require(('payload' in texture) != ('render_target_aliases' in texture),
                        'Texture must have CPU bytes or GPU target versions')
                for ref in texture.get('render_target_aliases', []):
                    require(target_key(ref) in targets, 'Sampled GPU alias version is missing')
                    require(history.get(ref['target_id'], ref['version']) == ref['version'],
                            'Sampled alias refers to a stale or future GPU version')
            seen_uses.add(use_id)
        if kind in ('draw', 'clear'):
            for attachment in ('color', 'depth_stencil'):
                before, after = event['before'][attachment], event['after'][attachment]
                require((before is None) == (after is None), 'Attachment changes inside a draw/clear')
                if before is None:
                    continue
                require(target_key(before) in targets and target_key(after) in targets,
                        'Before/after GPU attachment version is missing')
                require(before['target_id'] == after['target_id'], 'Attachment identity changed during operation')
                identity = before['target_id']
                require(history.get(identity, 0) == before['version'], 'Attachment version history has a gap')
                if query_open:
                    require(kind == 'draw' and event.get('readonly_visibility_query') is True
                            and before == after, 'Readback or attachment mutation inside active visibility query')
                else:
                    require(after['version'] == before['version'] + 1, 'GPU mutation version was not advanced')
                history[identity] = after['version']
        elif kind == 'present':
            require(not query_open, 'Frame ended inside an occlusion query')
            for ref in event['targets'].values():
                if ref is not None:
                    require(target_key(ref) in targets and history.get(ref['target_id'], 0) == ref['version'],
                            'Final target does not match ordered history')
            require(target_key(event['back_buffer']) in targets, 'Presented back buffer version is missing')
    require(counts['draw'] == status['draw_count'] == len(draws), 'Draw count differs from final marker')
    require(counts['clear'] == status['clear_count'], 'Clear count differs from final marker')
    require(counts['target_bind'] == status['target_bind_count'], 'Target-bind count differs from final marker')
    require(counts['texture_copy'] + counts['generate_mipmaps'] == status['copy_count'],
            'Texture-copy count differs from final marker')
    require(seen_uses == set(range(len(uses))), 'Not every original shader use has a captured draw')
    return history


def freeze_frame(directory, runner):
    directory, runner = directory.resolve(), runner.resolve()
    output = directory / 'captured_frame.json'
    require(not output.exists(), 'Frame is already frozen; preserve its existing identity')
    status = json.loads((directory / 'status.json').read_bytes())
    require(status.get('complete') is True, 'Raw capture is incomplete; preserve it for diagnosis')
    records, uses, corpus_status, corpus_hashes = load_corpus(Path(status['shader_corpus']))
    require(corpus_status['frame'] == status['frame'], 'Shader corpus belongs to another frame')
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines() if line]
    draws = {path.name: json.loads(path.read_bytes()) for path in sorted(directory.glob('draw-*.json'))}
    targets = {}
    target_files = {}
    for path in sorted(directory.glob('target-*.json')):
        value = json.loads(path.read_bytes())
        require(value.get('kind') == 'target_version' and value.get('complete') is True,
                f'GPU target readback incomplete: {path.name}')
        key = target_key(value)
        require(key not in targets, 'GPU target version identity duplicated')
        require(value['orientation'] == 'top_left', 'GPU attachment orientation changed')
        pixels = value['width'] * value['height']
        if value['depth']:
            require(value['depth_values']['bytes'] == pixels * 4 and
                    value['stencil_values']['bytes'] == pixels and
                    value['stencil_control']['bytes'] == pixels,
                    'Depth/stencil payload size is invalid')
            control = checked_path(directory, value['stencil_control']['file']).read_bytes()
            require(all(x == 165 for x in control), 'GPU stencil readback control failed')
        else:
            require(value['color']['bytes'] == pixels * 4, 'Color readback payload size is invalid')
        targets[key] = value
        target_files[key] = path.name
    history = validate_sequence(status, events, draws, targets, uses)
    hashes = {}
    for name, value in draws.items():
        value = hash_payloads(directory, value, hashes)
        use = uses[value['use']]
        value.update(vertex_id=use['vertex_id'], pixel_id=use['pixel_id'])
        draws[name] = value
    targets = {target_files[key]: hash_payloads(directory, value, hashes) for key, value in targets.items()}
    raw_names = ['status.json', 'events.jsonl', *draws, *targets]
    raw_hashes = {name: sha256((directory / name).read_bytes()) for name in raw_names}
    capture = dict(schema_version=1, kind='captured_frame', complete=True, frame=status['frame'],
                   status=status, events=events, draws=draws, targets=targets,
                   shader_corpus=status['shader_corpus'],
                   shader_corpus_sha256={Path(name).name: digest for name, digest in corpus_hashes.items()},
                   raw_sha256=raw_hashes, payloads=hashes,
                   runner=dict(file=str(runner), sha256=sha256(runner.read_bytes())),
                   collector=dict(file=str(Path(__file__).resolve()), sha256=sha256(Path(__file__).read_bytes())),
                   orientation='top_left', transformed_readbacks=False,
                   limits=status['limits'] + ['Diagnostic GPU readbacks synchronize this captured frame; original asynchronous query timing is not established.'])
    # All validation and hashing finish before publishing the immutable marker.
    data = encoded(capture)
    with output.open('xb') as file:
        file.write(data)
    return output


def verify_frame(path):
    path = path.resolve()
    value = json.loads(path.read_bytes())
    require(value.get('schema_version') == 1 and value.get('kind') == 'captured_frame'
            and value.get('complete') is True, 'Frozen frame is incomplete')
    base = path.parent
    for name, digest in value['raw_sha256'].items():
        require(sha256(checked_path(base, name).read_bytes()) == digest, f'Raw record changed: {name}')
    for name, expected in value['payloads'].items():
        data = checked_path(base, name).read_bytes()
        require(len(data) == expected['bytes'] and sha256(data) == expected['sha256'],
                f'Captured payload changed: {name}')
    _, uses, status, corpus_hashes = load_corpus(Path(value['shader_corpus']))
    require(value['shader_corpus_sha256'] == {Path(name).name: digest for name, digest in corpus_hashes.items()},
            'Original shader corpus changed after frame capture')
    targets = {target_key(record): record for record in value['targets'].values()}
    validate_sequence(value['status'], value['events'], value['draws'], targets, uses)
    require(value['frame'] == status['frame'], 'Frame/corpus identity mismatch')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    freeze = commands.add_parser('freeze')
    freeze.add_argument('directory', type=Path)
    freeze.add_argument('--runner', type=Path, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('capture', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        print(freeze_frame(args.directory, args.runner))
    else:
        frame = verify_frame(args.capture)
        print(json.dumps(dict(complete=True, frame=frame['frame'], events=len(frame['events']),
                              draws=len(frame['draws']), payloads=len(frame['payloads']))))


if __name__ == '__main__':
    main()
