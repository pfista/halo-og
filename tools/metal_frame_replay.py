#!/usr/bin/env python3
"""Import an ordered Xbox frame into native replay resources and commands.

Only original captured draws are translated. Persistent render targets are
seeded once; later ANGLE target versions are comparison checkpoints, never
uploads that replace native rendering. GPU aliases bind those persistent native
targets at their expected generation. The shared native draw encoder executes
the resulting manifest; this module implements no renderer.
"""
import argparse
import copy
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import tempfile

import metal_frame_capture
import metal_shader_validate
from metal_frame_capture import encoded, require, sha256, verify_frame
from metal_draw_replay import (Package, PixelMslOptions, import_texture,
                               normalize_xbox_state, pixel_depth_contract,
                               sampler_state, source_hashes, split_uniforms,
                               vertex_compile_contract)
from metal_shader_validate import PixelKey, build_library, generated, load_corpus


PRIMITIVES = {1: 'point', 2: 'line', 3: 'line_loop', 4: 'line_strip',
              5: 'triangle', 6: 'triangle_strip', 7: 'triangle_fan',
              8: 'quad', 9: 'triangle_strip', 10: 'triangle_fan'}


class FramePackage(Package):
    """Content-address output resources while retaining exact source hashes."""
    def write(self, name, data):
        digest = sha256(data)
        suffix = '.metal' if name.endswith('.metal') else '.bin'
        relative = f'payloads/{digest}{suffix}'
        path = self.output / relative
        if path.exists():
            require(path.read_bytes() == data, 'Output resource hash collision')
        else:
            with path.open('xb') as file:
                file.write(data)
        return dict(file=relative, size=len(data), sha256=digest)


class VerificationPackage(FramePackage):
    """Recompute original resources without writing into the replay package."""
    def write(self, name, data):
        digest = sha256(data)
        suffix = '.metal' if name.endswith('.metal') else '.bin'
        relative = f'payloads/{digest}{suffix}'
        path = self.output / relative
        require(path.is_file() and path.read_bytes() == data,
                'Prepared payload differs from its captured-source derivation')
        return dict(file=relative, size=len(data), sha256=digest)


def frame_source_hashes():
    """Require the exact complete set of translator and frame-reader sources."""
    result = source_hashes()
    for module in (metal_frame_capture, metal_shader_validate):
        path = Path(module.__file__).resolve()
        result[str(path)] = sha256(path.read_bytes())
    path = Path(__file__).resolve()
    result[str(path)] = sha256(path.read_bytes())
    return result


def copy_descriptor(package, value):
    return dict(value, **package.write('resource.bin', package.read(value)))


def geometry(package, raw):
    """Preserve raw indices, stream origins and the actual immediate ABI."""
    require(raw['primitive_d3d'] in PRIMITIVES, 'Unsupported original primitive')
    declaration = copy.deepcopy(raw['vertex_declaration'])
    if raw['immediate']:
        require(declaration['packed_mask'] == 0 and len(raw['streams']) == 1 and
                raw['streams'][0]['stride'] == 256, 'Immediate draw does not use sixteen float4 registers')
        # Original End() supplies every v-register as FLOAT4, independently of
        # the current declaration used for ordinary draws. Keep that original
        # declaration separately rather than misinterpreting immediate bytes.
        declaration = dict(packed_mask=0, elements=[dict(register=reg, stream=0,
            offset=reg*16, type=0x42) for reg in range(16)])
    streams = []
    for value in raw['streams']:
        descriptor = copy_descriptor(package, value['payload'])
        streams.append(dict(descriptor, stream=value['stream'], stride=value['stride'],
                            offset=0, first_vertex=value['source_first_vertex']))
    indexed = raw['indices'] is not None
    draw = dict(primitive=PRIMITIVES[raw['primitive_d3d']], indexed=indexed,
                vertex_start=raw['source_first_vertex'], vertex_count=raw['vertex_count'],
                base_vertex=raw['source_base_vertex'] if indexed else 0)
    if indexed:
        indices = package.read(raw['indices'])
        require(len(indices) == raw['index_count']*2, 'Original index count mismatch')
        values = struct.unpack(f'<{raw["index_count"]}H', indices)
        require(values and min(values)+raw['source_base_vertex'] == raw['source_first_vertex'] and
                max(values)-min(values)+1 == raw['vertex_count'], 'Captured stream/index span mismatch')
        draw.update(index_buffer=package.write('indices.bin', indices), index_type='uint16',
                    index_count=raw['index_count'], index_offset_bytes=0)
    return declaration, streams, draw


def render_state(raw, width, height, has_depth, render_words):
    """Use shared Xbox state conversion and the proven internal-row contract."""
    target = dict(width=width, height=height)
    require(len(render_words) == 576, 'Original render-state word ABI differs')
    xbox = dict(raw['render_state_d3d'], blend_color=struct.unpack('<144I', render_words)[75])
    result = normalize_xbox_state(xbox, target, raw['viewport'], raw['scissor'])
    if raw['scissor']['enabled']:
        x, y, w, h = raw['scissor']['box_gl']
        # apply_raster_state writes D3D viewport.Y directly to glScissor. GL
        # storage row0 is already logical Xbox top; no additional reflection.
        result['scissor'] = dict(x=x, y=y, width=w, height=h)
    # Original GLES suppresses depth testing when no attachment exists. Keep
    # both raw Xbox state and actual effective state for the native encoder.
    if not has_depth:
        result['depth'].update(enabled=False, write=False)
    actual = raw['actual_gl_state']
    result['blend']['color'] = actual['blend_color']
    actual_words = actual['depth_cull_blend_stencil_offset_words']
    require(bool(actual_words[0]) == result['depth']['enabled'] and
            bool(actual_words[6]) == result['blend']['enabled'] and
            bool(actual_words[10]) == result['stencil']['enabled'],
            'Original effective GL enable differs from converted Xbox state')
    return result


def clear_command(event, target_by_id):
    color_ref = event['before']['color']
    depth_ref = event['before']['depth_stencil']
    target = target_by_id[(color_ref or depth_ref)['target_id']]
    viewport = event['viewport']
    # The audited capture runs source-size targets. A scaled clear needs an
    # explicit target_pixel/UI_OFFSET conversion before it can be replayed.
    require(target['width'] == target['source_width'] and target['height'] == target['source_height'],
            'Scaled clear coordinates require an explicit native contract')
    x, y, w, h = viewport
    rectangles = event['rectangles'] or [[x, y, x+w, y+h]]
    clipped = []
    for left, top, right, bottom in rectangles:
        left, top, right, bottom = max(left, x), max(top, y), min(right, x+w), min(bottom, y+h)
        if left < right and top < bottom:
            clipped.append(dict(x=left, y=top, width=right-left, height=bottom-top))
    value, flags = event['color_d3d'], event['flags_d3d']
    # xdk_d3d8.h TARGET channel bits are R0x10,G0x20,B0x40,A0x80.
    color_mask = ((bool(flags & 0x10))*1 | (bool(flags & 0x20))*2 |
                  (bool(flags & 0x40))*4 | (bool(flags & 0x80))*8)
    return dict(event=event['event'], kind='clear', before=event['before'], after=event['after'],
                rectangles=clipped, color_write_mask=color_mask,
                color=[((value >> shift) & 255)/255 for shift in (16, 8, 0, 24)],
                clear_depth=bool(flags & 1) and depth_ref is not None,
                depth=event['depth'], clear_stencil=bool(flags & 2) and depth_ref is not None,
                stencil=event['stencil'], source_flags_d3d=flags)


def compiler_contract(evidence_path, fragment_evidence_path=None):
    if fragment_evidence_path is not None:
        contract=compiler_contract(evidence_path)
        contract['id']='nv2a-stage-compiler-contracts-v1'
        contract['fragment']=dict(contract='angle_metal_fast_fragment_v1',fast_math=True,
            preserve_invariance=False,math_mode='fast',floating_point_functions='fast')
        contract['fragment_compiler_evidence']=dict(file=str(fragment_evidence_path.resolve()),
            sha256=sha256(fragment_evidence_path.read_bytes()))
        contract['limitations'].append('Fragment policy is derived from pinned ANGLE source and independently checked generated GLSL flags for each key; physical Xbox arithmetic remains unverified.')
        return contract
    if evidence_path is None:
        return dict(id='nv2a-direct-default', vertex=dict(fast_math=False, preserve_invariance=True),
                    fragment=dict(fast_math=False, preserve_invariance=True),
                    limitations=['Safe native compiler defaults; original ANGLE vertex fast mode not selected.'])
    # The shared vertex_compile_contract validates pinned policy sources and
    # every generated GLSL baseline before this is attached to an actual VS.
    return dict(id='angle_metal_invariant_fast_v1',
                vertex=dict(contract='angle_metal_invariant_fast_v1', fast_math=True,
                            preserve_invariance=True, math_mode='fast', floating_point_functions='fast'),
                fragment=dict(fast_math=False, preserve_invariance=True),
                compiler_evidence=dict(file=str(evidence_path.resolve()), sha256=sha256(evidence_path.read_bytes())),
                limitations=['Original vertex compiler options are source-derived; full-frame attachment parity still needs native replay.'])


def replay_contents(frame, package, lib, evidence_path=None, fragment_evidence_path=None):
    """Derive every executable field from the verified original capture.

    Preparation and verification share this deterministic conversion. During
    verification, writes only compare bytes with the existing package; no
    captured after-operation attachment is ever uploaded or substituted.
    """
    contract = compiler_contract(evidence_path, fragment_evidence_path)
    records, uses, _, corpus_hashes = load_corpus(Path(frame['shader_corpus']))
    vertices = {r['id']: r for _, r in records if r['kind'] == 'vertex'}
    pixels = {r['id']: r for _, r in records if r['kind'] == 'pixel'}
    shader_sources = {}
    targets, target_by_id, checkpoints = {}, {}, {}
    for record in frame['targets'].values():
        identity, version = record['target_id'], record['version']
        key = f'target-{identity}'
        target_by_id[identity] = record
        if version == 0:
            initial = {field: copy_descriptor(package, record[field]) for field in
                       (('depth_values', 'stencil_values') if record['depth'] else ('color',))}
            targets[key] = dict(id=identity, generation=0, width=record['width'], height=record['height'],
                pixel_format='depth32float_stencil8' if record['depth'] else 'rgba8unorm',
                source_data=record['source_data'], source_width=record['source_width'],
                source_height=record['source_height'], initial=initial)
        checkpoints[f'{identity}:{version}'] = dict(record, **{field: copy_descriptor(package, record[field])
            for field in (('depth_values', 'stencil_values', 'stencil_control') if record['depth'] else ('color',))})
    require(len(targets) == len(target_by_id), 'Every persistent target needs an original initial version')
    static_textures, texture_cache, draws, commands = {}, {}, {}, []
    for event in frame['events']:
        if event['kind'] == 'clear':
            commands.append(clear_command(event, target_by_id))
            continue
        if event['kind'] != 'draw':
            commands.append(copy.deepcopy(event))
            continue
        raw = frame['draws'][event['draw']]
        vertex, pixel = vertices[raw['vertex_id']], pixels[raw['pixel_id']]
        require(raw['vertex_declaration']['packed_mask'] == vertex['packed_mask'], 'Captured VS packed-mask mismatch')
        key = PixelKey()
        for name, _ in PixelKey._fields_:
            if isinstance(pixel[name], list): getattr(key, name)[:] = pixel[name]
            else: setattr(key, name, pixel[name])
        before = raw['before']; target_ref = before['color'] or before['depth_stencil']
        target = target_by_id[target_ref['target_id']]
        state = render_state(raw, target['width'], target['height'], before['depth_stencil'] is not None,
                             package.read(raw['render_state_words']))
        validate_readonly_draw(event, state)
        depth_capture = dict(raw, render_state=state)
        depth_contract = pixel_depth_contract(depth_capture, key)
        vkey, pkey = ('vertex', raw['vertex_id']), ('pixel', raw['pixel_id'], json.dumps(depth_contract, sort_keys=True))
        if vkey not in shader_sources:
            words = (C.c_uint32*len(vertex['instructions']))(*vertex['instructions'])
            text = generated(lib.nv2a_vertex_shader_to_msl, words, vertex['instruction_count'], vertex['packed_mask'])
            require(text is not None, f'Unsupported actual VS use {raw["use"]}')
            shader_sources[vkey] = dict(package.write('vertex.metal', text.encode()), entry='xgpu_vertex')
            if evidence_path is not None:
                options, evidence, baseline = vertex_compile_contract(lib, words, vertex, evidence_path, package)
                shader_sources[vkey].update(compile_options=options, compiler_evidence=evidence,
                                           compiler_baseline=baseline)
        if pkey not in shader_sources:
            if depth_contract is None:
                text = generated(lib.nv2a_pixel_shader_to_msl, C.byref(key))
            else:
                lib.nv2a_pixel_shader_to_msl_with_options.argtypes = [C.POINTER(PixelKey), C.POINTER(PixelMslOptions)]
                lib.nv2a_pixel_shader_to_msl_with_options.restype = C.c_void_p
                options = PixelMslOptions(1, 1)
                text = generated(lib.nv2a_pixel_shader_to_msl_with_options, C.byref(key), C.byref(options))
            require(text is not None, f'Unsupported actual PS use {raw["use"]}')
            shader_sources[pkey] = dict(package.write('fragment.metal', text.encode()), entry='xgpu_fragment')
            if fragment_evidence_path is not None:
                from metal_draw_replay import fragment_compile_contract
                options,evidence,baseline=fragment_compile_contract(lib,key,fragment_evidence_path,package)
                shader_sources[pkey].update(compile_options=options,compiler_evidence=evidence,
                    compiler_baseline=baseline)
        declaration, streams, draw = geometry(package, raw)
        v_uniforms, p_uniforms = split_uniforms(package.read(raw['vertex_constants']),
                                              package.read(raw['draw_uniforms']), depth_contract)
        bindings = []
        for slot, texture in enumerate(raw['textures']):
            if key.sampler_type[slot] == 0:
                bindings.append(None); continue
            mode = key.texture_modes >> (5*slot) & 31
            if texture is None:
                require(mode == 17, 'Missing actually sampled texture resource')
                bindings.append(dict(slot=slot, type='unbound_passthrough', original_mode=mode)); continue
            if 'render_target_aliases' in texture:
                aliases = texture['render_target_aliases']
                require(key.sampler_type[slot] == 1 and len(aliases) == 1 and texture['levels'] == 1,
                        'GPU alias mip/cube/volume layout needs explicit support')
                alias = aliases[0]; require(alias['target_id'] in target_by_id, 'GPU alias target missing')
                source = target_by_id[alias['target_id']]
                require(not source['depth'] and texture['width'] == source['width'] and texture['height'] == source['height'],
                        'Depth/scaled GPU alias is not yet validated')
                bindings.append(dict(slot=slot, type='target_alias', resource=f'target-{alias["target_id"]}',
                    expected_generation=alias['version'],
                    sampler=sampler_state(texture['sampler'], 1, key.border_axes[slot], key.sampler_type[slot]),
                    source_sampler=texture['sampler'],
                    source_header=dict(format_word=texture['format_word'], size_word=texture['size_word'])))
                continue
            adapted = dict(texture, **texture['payload'])
            if 'palette' in adapted:
                adapted['palette'] = dict(adapted['palette'], format='argb32_little_endian')
            texture_key = sha256(encoded(dict(header=[adapted['format_word'], adapted['size_word']],
                 payload=adapted['sha256'], palette=adapted.get('palette', {}).get('sha256'))))
            if texture_key not in texture_cache:
                imported = import_texture(package, slot, adapted, key.sampler_type[slot], key.border_axes[slot])
                resource = f'texture-{texture_key}'
                static_textures[resource] = {name: value for name, value in imported.items() if name not in ('slot', 'sampler')}
                texture_cache[texture_key] = resource
            bindings.append(dict(slot=slot, type='static_texture', resource=texture_cache[texture_key],
                sampler=sampler_state(texture['sampler'], texture['levels'], key.border_axes[slot], key.sampler_type[slot]),
                source_sampler=texture['sampler']))
        item = dict(schema_version=1, kind='nv2a_frame_draw', use=raw['use'],
            source_shader_pair={name: raw[name] for name in ('program_id', 'declaration_id', 'vertex_id', 'pixel_id')},
            shaders=dict(vertex=shader_sources[vkey], fragment=shader_sources[pkey]),
            uniforms=dict(vertex=package.write('vertex-uniforms.bin', v_uniforms),
                          pixel=package.write('pixel-uniforms.bin', p_uniforms)),
            vertex_declaration=declaration, source_vertex_declaration=raw['vertex_declaration'],
            vertex_streams=streams, fixed_attributes=copy_descriptor(package, raw['fixed_attributes']),
            draw=draw, textures=bindings, render_state=state, targets=before,
            original_depth_request=raw['original_depth_request'],
            viewport_bits=copy_descriptor(package, raw['viewport_bits']))
        if depth_contract: item['pixel_depth_contract'] = depth_contract
        if contract.get('compiler_evidence'): item['compiler_evidence'] = contract['compiler_evidence']
        draws[event['draw']] = item
        commands.append(dict(event=event['event'], kind='draw', draw=event['draw'], use=raw['use'],
                             before=event['before'], after=event['after'],
                             readonly_visibility_query=event['readonly_visibility_query']))
    return dict(compiler_contract=contract, targets=targets, static_textures=static_textures,
        draws=draws, commands=commands, reference_checkpoints=checkpoints,
        execution_contract=dict(initial_target_seed_upload='once_before_frame',
            after_operation_gpu_versions='reference_only_never_uploaded',
            target_aliases='bind_persistent_native_target_at_expected_generation',
            visibility='recorded_cpu_and_gpu_results; native query execution remains required',
            orientation='top_left'),
        limitations=frame['limits'] + contract['limitations'] +
            ['Manifest preparation is not native frame execution or complete native gameplay.'])


def validate_readonly_draw(event, state):
    require(type(event.get('readonly_visibility_query')) is bool,
            'Original read-only visibility flag is invalid')
    if event['readonly_visibility_query']:
        require(event['before'] == event['after'] and state['blend']['write_mask'] == 0 and
                not (state['depth']['enabled'] and state['depth']['write']) and
                not (state['stencil']['enabled'] and state['stencil']['write_mask']),
                'Read-only visibility draw would mutate attachment history')


def replay_manifest(capture_path, frame, package, contents, prepared_sources):
    return dict(schema_version=1, kind='nv2a_frame_replay', complete=True,
        source_capture=dict(file=str(capture_path), sha256=sha256(capture_path.read_bytes()), frame=frame['frame'],
                            shader_corpus_sha256=frame['shader_corpus_sha256']),
        source_sha256=prepared_sources, source_inputs=package.hashes,
        **contents)


def prepare_frame(capture_path, output, evidence_path=None, fragment_evidence_path=None):
    capture_path, output = capture_path.resolve(), output.resolve()
    capture_digest = sha256(capture_path.read_bytes())
    frame = verify_frame(capture_path)
    prepared_sources = frame_source_hashes()
    require(sha256(capture_path.read_bytes()) == capture_digest, 'Original frame changed while validating')
    require(not output.exists(), 'Replay output exists; preserve its previous identity')
    output.mkdir(parents=True)
    (output/'payloads').mkdir()
    (output/'translator').mkdir()
    package = FramePackage(capture_path.parent, output)
    lib = build_library(output/'translator')
    contents = replay_contents(frame, package, lib, evidence_path, fragment_evidence_path)
    require(prepared_sources == frame_source_hashes(), 'Emitter/importer sources changed while preparing the frame')
    # Re-verify source capture after reading resources, not only at entry.
    verify_frame(capture_path)
    require(sha256(capture_path.read_bytes()) == capture_digest, 'Original frame changed while preparing')
    manifest = replay_manifest(capture_path, frame, package, contents, prepared_sources)
    with (output/'frame-replay.json').open('xb') as file: file.write(encoded(manifest))
    return manifest


def verify_original_commands(manifest, frame, package):
    """Check state and no-write history before compiling any shader."""
    require(set(manifest['draws']) == set(frame['draws']), 'Prepared draw set differs from the captured frame')
    target_by_id = {record['target_id']: record for record in frame['targets'].values()}
    for command, original in zip(manifest['commands'], frame['events']):
        require(command['event'] == original['event'] and command['kind'] == original['kind'],
                'Prepared commands differ from original order')
        if original['kind'] == 'clear':
            require(command == clear_command(original, target_by_id),
                    'Prepared clear differs from its original state or attachment history')
        elif original['kind'] == 'draw':
            require(command['draw'] == original['draw'] and command['use'] == original['use'] and
                    command['before'] == original['before'] and command['after'] == original['after'],
                    'Prepared command target history or draw identity differs')
            require(type(command.get('readonly_visibility_query')) is bool and
                    command['readonly_visibility_query'] == original['readonly_visibility_query'],
                    'Prepared read-only visibility flag differs from the original query')
            draw, raw = manifest['draws'][command['draw']], frame['draws'][original['draw']]
            target_ref = raw['before']['color'] or raw['before']['depth_stencil']
            target = target_by_id[target_ref['target_id']]
            expected_state = render_state(raw, target['width'], target['height'],
                raw['before']['depth_stencil'] is not None, package.read(raw['render_state_words']))
            require(draw['render_state'] == expected_state,
                    'Prepared normalized render state differs from the captured original draw')
            validate_readonly_draw(command, draw['render_state'])
            require(draw['use'] == raw['use'] and draw['targets'] == raw['before'],
                    'Prepared draw identity/targets differ')
            for binding, texture in zip(draw['textures'], raw['textures']):
                if binding and binding['type'] == 'target_alias':
                    alias = texture['render_target_aliases'][0]
                    require(binding['resource'] == f'target-{alias["target_id"]}' and
                            binding['expected_generation'] == alias['version'],
                            'Prepared GPU alias generation differs from the captured draw')
        else:
            require(command == original, 'Prepared visibility/bind/present command differs from the original')


def verify_replay(path):
    path = path.resolve()
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    require(manifest.get('schema_version') == 1 and manifest.get('kind') == 'nv2a_frame_replay'
            and manifest.get('complete') is True, 'Prepared frame is incomplete')
    verified_sources = frame_source_hashes()
    require(manifest.get('source_sha256') == verified_sources,
            'Prepared frame emitter/importer sources are stale or incomplete; reprepare the frame')
    source = Path(manifest['source_capture']['file'])
    require(sha256(source.read_bytes()) == manifest['source_capture']['sha256'], 'Original frame capture changed')
    frame = verify_frame(source)
    require(manifest['source_capture']['frame'] == frame['frame'] and
            len(manifest['commands']) == len(frame['events']), 'Prepared/source frame identity differs')
    files = {}
    def check(value):
        if isinstance(value, list):
            for item in value: check(item)
        elif isinstance(value, dict):
            if {'file', 'sha256'} <= value.keys():
                location = Path(value['file'])
                if not location.is_absolute():
                    location = (path.parent/location).resolve()
                    require(location.is_relative_to(path.parent), 'Prepared resource escapes the package')
                data = location.read_bytes()
                require(sha256(data) == value['sha256'] and
                        ('size' not in value or len(data) == value['size']), 'Prepared resource hash/size differs')
                files[str(location)] = value['sha256']
            for item in value.values(): check(item)
    check(manifest)
    require(manifest['execution_contract']['initial_target_seed_upload'] == 'once_before_frame' and
            manifest['execution_contract']['after_operation_gpu_versions'] == 'reference_only_never_uploaded',
            'Prepared frame would reset target history')
    package = VerificationPackage(source.parent, path.parent)
    verify_original_commands(manifest, frame, package)
    contract = manifest['compiler_contract']
    evidence_path = None; fragment_evidence_path = None
    require(contract.get('id') in ('nv2a-direct-default', 'angle_metal_invariant_fast_v1','nv2a-stage-compiler-contracts-v1'),
            'Unknown prepared frame compiler contract')
    if 'compiler_evidence' in contract:
        evidence_path = Path(contract['compiler_evidence']['file'])
        require(evidence_path.is_absolute(), 'Original compiler evidence must use its captured absolute path')
    if 'fragment_compiler_evidence' in contract:
        fragment_evidence_path=Path(contract['fragment_compiler_evidence']['file'])
        require(fragment_evidence_path.is_absolute(),'Original fragment compiler evidence must use its captured absolute path')
    # Re-emit from the original microcode and reconvert its resources using the
    # current hashed sources. Existing output bytes must match; this temporary
    # compiler directory never writes to the prepared frame or reference data.
    with tempfile.TemporaryDirectory(prefix='halo-metal-frame-verify-') as directory:
        lib = build_library(Path(directory))
        contents = replay_contents(frame, package, lib, evidence_path, fragment_evidence_path)
    expected = replay_manifest(source, frame, package, contents, verified_sources)
    require(json.dumps(manifest, sort_keys=True, allow_nan=False) ==
            json.dumps(expected, sort_keys=True, allow_nan=False),
            'Prepared frame differs from its verified original-source derivation')
    verify_frame(source)
    for location, digest in package.hashes.items():
        require(sha256(Path(location).read_bytes()) == digest,
                'Original resource or compiler evidence changed during verification')
    require(verified_sources == frame_source_hashes() and path.read_bytes() == manifest_bytes and
            sha256(source.read_bytes()) == manifest['source_capture']['sha256'],
            'Frame manifest, capture or translator sources changed during verification')
    return dict(complete=True, frame=frame['frame'], commands=len(manifest['commands']),
                draws=len(manifest['draws']), resources=len(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compiler-evidence', type=Path)
    parser.add_argument('--fragment-compiler-evidence',type=Path)
    parser.add_argument('--verify', action='store_true', help='Verify an existing frame-replay.json instead of importing')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_replay(args.capture)))
        return
    if args.output is None:
        parser.error('--output is required for frame preparation')
    try:
        result = prepare_frame(args.capture, args.output, args.compiler_evidence,args.fragment_compiler_evidence)
    except Exception as error:
        if args.output.exists() and not (args.output/'frame-replay.json').exists() and not (args.output/'failure.json').exists():
            (args.output/'failure.json').write_bytes(encoded(dict(schema_version=1,
                kind='nv2a_frame_replay', complete=False, error=str(error))))
        raise
    print(json.dumps(dict(complete=True, frame=result['source_capture']['frame'],
        commands=len(result['commands']), draws=len(result['draws']),
        targets=len(result['targets']), textures=len(result['static_textures']),
        manifest=str(args.output.resolve()/'frame-replay.json'))))


if __name__ == '__main__':
    main()
