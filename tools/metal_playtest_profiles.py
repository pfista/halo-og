#!/usr/bin/env python3
"""Prepare isolated native Metal playtest profiles without launching the game.

Examples (each output must be new):
  python3 tools/metal_playtest_profiles.py prepare --map bloodgulch \
    --render-cap 30 --render-height 480 --vsync off --assets /path/to/assets \
    --template /path/to/normal/config.toml --output /path/to/new-profile
  python3 tools/metal_playtest_profiles.py promote --profile /path/to/new-profile \
    --build-proof /path/to/NEW/result.json --runtime-proof /path/to/runtime.json
  python3 tools/metal_playtest_profiles.py prepare --map bloodgulch \
    --render-cap 60 --native-fullscreen --native-size 3600x2338 --vsync on \
    --assets /path/to/assets --template /path/to/config.toml --output /path/to/new-native-profile

Promotion requires exact profile-specific bounded runtime evidence. Neither
preparation nor promotion proves achieved FPS, manual input/audio or fidelity.
Original assets are referenced by symlinks, never copied or modified.
Native size is a measured expectation, never a display-mode override. Omit it
for an unready measurement probe, then prepare a new profile with its result.
The initial configuration is immutable provenance. The live configuration can
retain ordinary audio/input preferences while its tested display preset stays
fixed; launch verification never rewrites either configuration.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import stat
import struct
import sys
import tomllib
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAPS = ('bloodgulch', 'damnation', 'hangemhigh')
CAPS = (30, 60, 120, 0)
HEIGHTS = (480, 720, 1080, 1440, 2160)
ANTI_ALIASING = ('off', 'fxaa')
NATIVE_MAX_DIMENSION = 8192
NATIVE_RESOLUTION_SYMBOL = 'halo_metal_render_native_target_dimensions'
HOST = 'build/macos-metal/halo'
GUEST = 'build/macos-metal/halo_guest.elf'
HELPERS = ('halo_frame_pacing', 'metal_render_scale')
HELPER_SYMBOLS = {
    'halo_frame_pacing': {'halo_frame_pacing_deadline', 'halo_frame_pacing_reset'},
    'metal_render_scale': {'halo_metal_render_target_dimensions', 'halo_metal_render_scale_rectangle'},
}
REQUIRED_BUILD_PATHS = {
    HOST, GUEST, 'build.ninja', 'port/linux/src/port_config.c',
    'port/linux/src/sdl_platform.c', 'port/linux/src/d3d8_metal.c',
    *(f'port/linux/src/{name}.{ext}' for name in HELPERS for ext in ('c', 'h')),
    *(f'build/macos-metal/guest/obj/port/linux/src/{name}.o' for name in HELPERS),
}
AA_BUILD_PATHS = {'source/render/render.c', 'port/macos/include/halo_metal_abi.h',
                  'port/macos/host/host_metal.mm',
                  'build/macos-metal/guest/obj/port/linux/src/d3d8_metal.o',
                  'build/macos-metal/guest/obj/source/render/render.o'}
AA_SYMBOL = 'halo_metal_antialias_before_hud'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def descriptor(path):
    path = Path(path).resolve()
    return {'file': str(path), 'sha256': sha(path)}


def checked_descriptor(record):
    require(isinstance(record, dict) and isinstance(record.get('file'), str), 'Missing file descriptor')
    require(isinstance(record.get('sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', record['sha256']) is not None, 'Invalid file digest')
    path = Path(record['file'])
    require(path.is_absolute() and path.is_file(), 'Descriptor must name an existing absolute file')
    require(sha(path) == record['sha256'], 'Stale file: ' + str(path))
    return path


def new_json(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def parse_native_size(value):
    if isinstance(value, str):
        match = re.fullmatch(r'([1-9][0-9]*)[xX]([1-9][0-9]*)', value)
        require(match is not None, 'Native size must be measured physical pixels in WxH form')
        value = tuple(map(int, match.groups()))
    require(isinstance(value, (tuple, list)) and len(value) == 2
            and all(type(axis) is int and 0 < axis <= NATIVE_MAX_DIMENSION for axis in value),
            'Native size must have two positive physical axes no larger than8192')
    logical_width = (480 * value[0] // value[1]) & ~1
    require(640 <= logical_width <= 1600, 'Native fullscreen aspect exceeds the supported logical canvas')
    return tuple(value)


def profile_values(map_name, cap, height, vsync, native_fullscreen=False, native_size=None, anti_aliasing='off'):
    require(map_name in MAPS, 'Unsupported playtest map')
    require(type(cap) is int and cap in CAPS, 'Render cap must be 30, 60, 120 or 0')
    require(type(vsync) is bool, 'Vsync must be a boolean independent of render cap')
    require(type(native_fullscreen) is bool, 'Native fullscreen selection must be a boolean')
    require(type(anti_aliasing) is str and anti_aliasing in ANTI_ALIASING, 'Anti-aliasing must be off or fxaa')
    if native_fullscreen:
        require(height is None or (type(height) is int and height == 0), 'Native fullscreen must use render height0')
        size = parse_native_size(native_size) if native_size is not None else None
        return dict(map=map_name, frame_limit=cap, render_height=0, vsync=vsync, anti_aliasing=anti_aliasing,
                    interpolation=cap != 30, high_res_hud=False, direct_camera=False, reference_30=False,
                    native_fullscreen=True, native_size=list(size) if size else None,
                    logical_width=((480 * size[0] // size[1]) & ~1) if size else None, logical_height=480,
                    expected_physical_width=size[0] if size else None, expected_physical_height=size[1] if size else None)
    require(native_size is None, 'Native size expectation requires native fullscreen')
    require(type(height) is int and height in HEIGHTS, 'Unsupported actual render height')
    return dict(map=map_name, frame_limit=cap, render_height=height, vsync=vsync, anti_aliasing=anti_aliasing,
                interpolation=cap != 30, high_res_hud=False, direct_camera=False,
                reference_30=cap == 30 and height == 480 and anti_aliasing == 'off',
                logical_width=640, logical_height=480, expected_physical_width=height * 4 // 3)


def physical_size(values):
    width, height = values['expected_physical_width'], values.get('expected_physical_height', values['render_height'])
    require(type(width) is int and type(height) is int and 0 < width <= NATIVE_MAX_DIMENSION
            and 0 < height <= NATIVE_MAX_DIMENSION, 'An explicit measured native size is required for runtime validation/promotion')
    return width, height


def windowed_environment(values):
    return '0' if values.get('native_fullscreen', False) else '1'


def checked_native_startup(log, values, require_expected=True):
    """Match measured SDL pixels, renderer backing and logical startup units."""
    if not values.get('native_fullscreen', False):
        return None
    lines = re.findall(r'Native resolution: (\d+)x(\d+) storage, (\d+)x(\d+) logical, '
                       r'(\d+)x(\d+) drawable, startup aspect (native|fitted)', log)
    require(len(lines) == 1, 'Exactly one measured native resolution startup record is required')
    sw, sh, lw, lh, dw, dh = map(int, lines[0][:6])
    width, height = physical_size(values) if require_expected or values.get('native_size') else parse_native_size((dw,dh))
    logical_width = values['logical_width'] if values.get('native_size') else ((480*width//height)&~1)
    require((sw, sh) == (dw, dh) == (width, height) and (lw, lh) ==
            (logical_width, values['logical_height']) and lines[0][6] == 'native',
            'Measured native storage/logical/drawable dimensions differ from the profile expectation')
    drawables = re.findall(r'Metal drawable (\d+)x(\d+) \((borderless fullscreen|windowed)\)', log)
    require(len(drawables) == 1 and tuple(map(int, drawables[0][:2])) == (width, height)
            and drawables[0][2] == 'borderless fullscreen', 'SDL native fullscreen drawable differs from measured expectation')
    return dict(storage_width=sw, storage_height=sh, logical_width=lw, logical_height=lh,
                drawable_width=dw, drawable_height=dh, aspect='native', fullscreen=True)


def checked_anti_aliasing(log, values):
    """Bind requested smoothing to passes actually reported by the native hook."""
    records = []
    for line in log.splitlines():
        if 'Native anti-aliasing:' not in line:
            continue
        match = re.search(r'Native anti-aliasing: requested (off|fxaa), applied ([0-9]+), stage pre-HUD$', line)
        require(match is not None, 'Malformed native anti-aliasing execution record')
        mode, count = match.groups()
        require(mode == values['anti_aliasing'], 'Native applied anti-aliasing mode differs from profile')
        records.append(int(count))
    require(records, 'Native anti-aliasing execution telemetry is missing')
    require(all(previous <= current for previous, current in zip(records, records[1:])),
            'Native anti-aliasing pass counter decreased')
    require(records[-1] <= (1 << 64) - 1, 'Native anti-aliasing pass counter exceeds uint64')
    require(records[-1] == 0 if values['anti_aliasing'] == 'off' else records[-1] > 0,
            'Native anti-aliasing execution count does not prove the requested mode')
    return dict(requested=values['anti_aliasing'], applied=records[-1], stage='pre-HUD', records=len(records))


def set_key(text, section, key, value):
    pattern = re.compile(r'(?ms)(^\[' + re.escape(section) + r'\]\s*\n)(.*?)(?=^\[|\Z)')
    matches = list(pattern.finditer(text))
    require(len(matches) == 1, 'Missing or ambiguous config section: ' + section)
    match = matches[0]
    body = match[2]
    item = re.compile(r'(?m)^' + re.escape(key) + r'\s*=.*$')
    require(len(item.findall(body)) <= 1, 'Ambiguous config key: ' + key)
    line = key + ' = ' + value
    body = item.sub(line, body) if item.search(body) else body + line + '\n'
    return text[:match.start()] + match[1] + body + text[match.end():]


def controlled_config(template, values):
    original = tomllib.loads(template)
    sensitivity = original.get('input', {}).get('mouse_sensitivity', 0)
    volume = original.get('audio', {}).get('volume', 0)
    require(type(sensitivity) in (int, float) and math.isfinite(sensitivity) and sensitivity >= 0.01,
            'Provide a normal human-input template, not a scripted smoke config')
    require(type(volume) in (int, float) and math.isfinite(volume) and volume > 0,
            'Provide a normal audible audio template')
    require(isinstance(original.get('bindings'), dict) and all(original['bindings'].values()),
            'Provide normal nonempty human input bindings')
    result = template
    updates = {
        'display': {'fullscreen': values.get('native_fullscreen', False),
                    'screen_width': 0 if values.get('native_fullscreen', False) else 640, 'window_scale': 2,
                    **{k: values[k] for k in ('frame_limit', 'render_height', 'vsync',
                                             'interpolation', 'high_res_hud', 'direct_camera', 'anti_aliasing')}},
        'audio': {'enabled': True},
        'network': {'online': False, 'allow_upnp': False, 'join_from_clipboard': False},
        'update': {'auto': False},
        'debug': {'test_input': '', 'exit_after': 0.0, 'hidden_window': False, 'null_renderer': False,
                  'telnet_console': False, 'screenshot_every': 0, 'screenshot_directory': '',
                  'texture_dump_directory': '', 'gpu_skip_vertex_shaders': '', 'gpu_dump_shaders': '',
                  'gpu_debug_expression': '', 'gpu_debug_texture0': False, 'gpu_debug_flat': False,
                  'network_test': '', 'network_latency': 0.0, 'network_loss': 0.0}}
    for section, fields in updates.items():
        for key, value in fields.items():
            encoded = str(value).lower() if type(value) is bool else json.dumps(value)
            result = set_key(result, section, key, encoded)
    current = tomllib.loads(result)
    require(current['bindings'] == original['bindings'] and current['input'] == original['input'],
            'Human input changed while preparing profile')
    validate_config(current, values)
    return result


def validate_display(config, values):
    display = config.get('display', {})
    for key in ('frame_limit', 'render_height', 'vsync', 'interpolation', 'high_res_hud', 'direct_camera', 'anti_aliasing'):
        require(type(display.get(key)) is type(values[key]) and display[key] == values[key],
                'Profile display mismatch: ' + key)
    require(type(display.get('screen_width')) is int and display['screen_width'] ==
            (0 if values.get('native_fullscreen', False) else 640), 'Profile logical aspect selection differs')
    if values.get('native_fullscreen', False):
        require(display.get('fullscreen') is True, 'Native profile must start fullscreen')


def validate_config(config, values, initial=None):
    validate_display(config, values)
    require(config['display']['fullscreen'] is values.get('native_fullscreen', False)
            and config['display']['window_scale'] == 2,
            'Unexpected window presentation')
    volume = config['audio'].get('volume', 0)
    sensitivity = config['input'].get('mouse_sensitivity', 0)
    require(config['audio']['enabled'] is True and type(volume) in (int, float) and math.isfinite(volume) and 0 <= volume <= 1
            and type(sensitivity) in (int, float) and math.isfinite(sensitivity) and sensitivity >= 0.01,
            'Normal audio and mouse input required')
    bindings = config['bindings']
    require(isinstance(bindings, dict) and bindings
            and all(isinstance(value, str) for value in bindings.values()), 'Invalid input bindings')
    if initial is None:
        require(all(value.strip() for value in bindings.values()), 'Human template bindings missing')
    for key, value in config['audio'].items():
        if key.endswith('volume'):
            require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
                    'Invalid audio preference: ' + key)
    for key, value in config['input'].items():
        require(type(value) in (bool, int, float) and (type(value) is bool or math.isfinite(value)),
                'Invalid input preference: ' + key)
    if initial is not None:
        # HALO_* launch paths override these settings, but preserve the user's
        # original path intent as well rather than silently accepting redirects.
        for key in ('data', 'saves'):
            require(config.get('paths', {}).get(key, '') == initial.get('paths', {}).get(key, ''),
                    'Profile path setting changed: ' + key)
    require(all(config['network'][k] is False for k in ('online', 'allow_upnp', 'join_from_clipboard'))
            and config['update']['auto'] is False, 'Offline/update-off configuration required')
    debug = config['debug']
    require(debug['exit_after'] == 0 and debug['test_input'] == '' and debug['screenshot_every'] == 0,
            'Scripted input, automatic exit or screenshots are enabled')
    require(all(debug[k] is False for k in ('hidden_window', 'null_renderer', 'telnet_console',
                                           'gpu_debug_texture0', 'gpu_debug_flat')), 'Debug override enabled')
    require(all(debug[k] == '' for k in ('screenshot_directory', 'texture_dump_directory',
                                        'gpu_skip_vertex_shaders', 'gpu_dump_shaders',
                                        'gpu_debug_expression', 'network_test')), 'Debug replacement enabled')
    require(debug['network_latency'] == debug['network_loss'] == 0, 'Artificial networking enabled')


def cache_header(path, expected, scenario_type):
    with Path(path).open('rb') as handle:
        raw = handle.read(2048)
    require(len(raw) == 2048 and raw[:4] == b'daeh' and raw[2044:] == b'toof', 'Invalid Xbox cache header')
    require(struct.unpack_from('<I', raw, 4)[0] == 5, 'Original Xbox v5 cache required')
    require(raw[32:64].split(b'\0')[0].decode('ascii') == expected, 'Map/header name mismatch')
    require(raw[64:96].split(b'\0')[0] == b'01.10.12.2276', 'Original NTSC cache build required')
    require(struct.unpack_from('<H', raw, 96)[0] == scenario_type, 'Wrong cache scenario type')


def prepare(output, map_name, cap, height, vsync, assets, template, root=ROOT,
            native_fullscreen=False, native_size=None, anti_aliasing='off'):
    output, assets, template, root = map(lambda p: Path(p).resolve(), (output, assets, template, root))
    require(not output.exists(), 'Output already exists; saves and config are preserved. Choose a new profile path.')
    values = profile_values(map_name, cap, height, vsync, native_fullscreen, native_size, anti_aliasing)
    configuration = controlled_config(template.read_text(), values)
    require((assets / 'maps').is_dir() and (assets / 'sounds').is_dir(), 'Original maps and sounds directories required')
    asset_records = []
    for name, category in ((map_name, 1), ('ui', 2)):
        path = assets / 'maps' / (name + '.map')
        cache_header(path, name, category)
        asset_records.append(descriptor(path))
    tool = Path(__file__).resolve()
    before = dict(tool=descriptor(tool), template=descriptor(template))
    output.mkdir(parents=True)
    (output / 'data').mkdir()
    (output / 'saves').mkdir()
    (output / 'data/maps').symlink_to(assets / 'maps', target_is_directory=True)
    (output / 'data/sounds').symlink_to(assets / 'sounds', target_is_directory=True)
    (output / 'data/init.txt').write_text('game_variant slayer\nmap_name ' + map_name + '\n')
    (output / 'saves/config.toml').write_text(configuration)
    (output / 'initial-config.toml').write_text(configuration)
    frozen = output / 'producer.py'
    shutil.copy2(tool, frozen)
    require(sha(tool) == before['tool']['sha256'] == sha(frozen), 'Producer changed during preparation')
    require(sha(template) == before['template']['sha256'], 'Template changed during preparation')
    manifest = dict(schema_version=1, kind='native_metal_playtest_profile', repository=str(root),
        profile=values, profile_directory=str(output), original_assets=str(assets),
        asset_files=asset_records, asset_access='read-only by this tool; original directories referenced by symlinks',
        template=before['template'], producer=before['tool'], frozen_producer=descriptor(frozen),
        config=descriptor(output / 'saves/config.toml'), init=descriptor(output / 'data/init.txt'),
        initial_config=descriptor(output / 'initial-config.toml'),
        configuration_policy='immutable-display-mutable-human-aa-v2',
        launch_environment=dict(HALO_DATA_ROOT=str(output / 'data'), HALO_SAVE_ROOT=str(output / 'saves'),
                                HALO_WINDOWED=windowed_environment(values)),
        prepared=True, experiment_ready=False, simulation_hz=30,
        simulation_source_modified=False, runtime_options_verified=False,
        manual_input_audio_gate=False, achieved_render_fps_gate=False, performance_improvement_gate=False,
        original_xbox_fidelity_gate=False, full_game_gate=False,
        scope='New isolated human playtest config only. Render cap and physical height requests do not prove achieved FPS or original pixels.')
    new_json(output / 'profile.json', manifest)
    return manifest


def checked_build(path, root, require_native_resolution=False):
    path, root = Path(path).resolve(), Path(root).resolve()
    build = json.loads(path.read_text())
    require(build.get('passed') is True and type(build.get('actual_build_tool_exit')) is int
            and build['actual_build_tool_exit'] == 0, 'Successful observed native build required')
    require(build.get('display_options') is True, 'Pre-option build is ineligible; require NEW --display-options proof')
    require(build.get('anti_aliasing') is True, 'Pre-AA build is ineligible; require NEW --anti-aliasing proof')
    if require_native_resolution:
        require(build.get('native_resolution') is True, 'Pre-native-resolution build; require NEW --native-fullscreen build proof')
    require(build.get('no_angle_gl_linkage_or_imports') is True, 'Native no-GL/ANGLE build proof required')
    bindings = build.get('source_bindings', []) + build.get('evidence_bindings', [])
    require(isinstance(bindings, list) and all(isinstance(b, dict) for b in bindings), 'Malformed build bindings')
    by_path = {}
    snapshot = Path(build['source_snapshot'])
    snapshot = snapshot if snapshot.is_absolute() else root / snapshot
    snapshot = snapshot.resolve()
    for item in bindings:
        relative = Path(item['path'])
        require(not relative.is_absolute() and '..' not in relative.parts and str(relative) not in by_path,
                'Unsafe or duplicate build binding')
        require(sha(root / relative) == item['sha256'] == sha(snapshot / relative),
                'Current/frozen build source drift: ' + str(relative))
        by_path[str(relative)] = item['sha256']
    require(REQUIRED_BUILD_PATHS <= by_path.keys(), 'Display helper source/object bindings are incomplete')
    require(AA_BUILD_PATHS <= by_path.keys(), 'AA world hook/backend/compiled object bindings are incomplete')
    graph = build.get('native_guest_graph', {})
    require(graph.get('no_gl_native_edges') is True, 'Missing no-GL native graph guard')
    for helper in HELPERS:
        obj = f'build/macos-metal/guest/obj/port/linux/src/{helper}.o'
        edge = graph.get('source_edges', {}).get(helper, '').split()
        require(obj + ':' in edge and f'port/linux/src/{helper}.c' in edge,
                'Missing exact guest helper source edge: ' + helper)
        require(obj in graph.get('guest_link_edge', '').split(), 'Helper is not linked into actual guest')
        compiled = build.get('native_compiled_objects', {}).get(helper)
        require(isinstance(compiled, dict) and compiled.get('linked_in_guest') is True
                and compiled.get('native_ilp32_flags') is True,
                'Missing actual compiled ILP32 helper symbol guard')
        require(compiled.get('object') == {'path': obj, 'sha256': by_path[obj]}
                and isinstance(compiled.get('symbol'), str) and compiled['symbol'],
                'Compiled helper/object identity mismatch')
        symbols = {compiled['symbol'], *compiled.get('additional_linked_symbols', [])}
        require(HELPER_SYMBOLS[helper] <= symbols, 'Missing required actual linked display helper symbols')
        if helper == 'metal_render_scale' and require_native_resolution:
            require(NATIVE_RESOLUTION_SYMBOL in symbols, 'Pre-native-resolution build cannot validate a native fullscreen profile')
    text = (snapshot / 'port/linux/src/port_config.c').read_text()
    for key, default in (('frame_limit', 0), ('render_height', 480)):
        pattern = r'\{\s*"display\.' + key + r'"\s*,\s*_config_integer\s*,\s*"' + str(default) + r'"\s*,\s*NULL\s*,'
        require(re.search(pattern, text) is not None, 'New display option is absent, mistyped or uses a new environment variable')
    require(re.search(r'\{\s*"display\.anti_aliasing"\s*,\s*_config_string\s*,\s*"\\"off\\""\s*,\s*NULL\s*,', text),
            'Native AA option must be a string defaulting off without an environment variable')
    abi = (snapshot / 'port/macos/include/halo_metal_abi.h').read_text()
    for symbol, value in (('HALO_METAL_CAP_FXAA', 32768), ('HALO_METAL_FXAA', 22), ('HALO_METAL_ENABLE_FXAA', 2)):
        require(re.search(r'\b' + symbol + r'\s*=\s*' + str(value) + r'u?\b', abi), 'Native AA ABI contract is missing: ' + symbol)
    require(build.get('anti_aliasing_contract') == {'capability': 32768, 'opcode': 22, 'enable_flag': 2,
            'stage': 'pre-HUD', 'modes': ['off', 'fxaa']}, 'Native AA proof capability/stage contract changed')
    compiled_aa = build.get('native_compiled_objects', {}).get('d3d8_metal', {})
    aa_object = 'build/macos-metal/guest/obj/port/linux/src/d3d8_metal.o'
    require(compiled_aa.get('object') == {'path': aa_object, 'sha256': by_path[aa_object]}
            and compiled_aa.get('linked_in_guest') is True and compiled_aa.get('native_ilp32_flags') is True
            and AA_SYMBOL in {compiled_aa.get('symbol'), *compiled_aa.get('additional_linked_symbols', [])},
            'Native AA hook is not bound to the actual compiled guest')
    world_hook = build.get('anti_aliasing_world_hook', {})
    render_object = 'build/macos-metal/guest/obj/source/render/render.o'
    world_edge = graph.get('source_edges', {}).get('render', '').split()
    require(render_object + ':' in world_edge and 'source/render/render.c' in world_edge
            and render_object in graph.get('guest_link_edge', '').split(), 'Native AA compiled world source/link edge is missing')
    require(world_hook.get('object') == {'path': render_object, 'sha256': by_path[render_object]}
            and world_hook.get('symbol') == AA_SYMBOL and world_hook.get('compiled_call') is True
            and world_hook.get('linked_in_guest') is True and world_hook.get('native_ilp32_flags') is True,
            'Native AA pre-HUD compiled call is missing')
    host, guest = snapshot / HOST, snapshot / GUEST
    require(stat.S_IMODE(host.stat().st_mode) == 0o755, 'Frozen host must retain executable mode0755')
    with host.open('rb') as h: header = h.read(8)
    require(header == struct.pack('<II', 0xfeedfacf, 0x0100000c), 'ARM64 Mach-O host required')
    with guest.open('rb') as h: header = h.read(20)
    # The existing loader uses an ELF64 AArch64 container; ILP32 pointer/data
    # semantics are established by the real compiled-object/guest guards.
    require(header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183,
            'Native loader AArch64 guest container required')
    environment_names = sorted(set(re.findall(r'"(HALO_[A-Z0-9_]+)"', text))
                               - {'HALO_DATA_ROOT', 'HALO_SAVE_ROOT', 'HALO_WINDOWED'})
    result = dict(proof=descriptor(path), snapshot=str(snapshot), bindings=bindings,
                configuration_environment_names=environment_names,
                host=descriptor(host), guest=descriptor(guest), display_options=True, anti_aliasing=True)
    if require_native_resolution:
        result['native_resolution_api_verified'] = True
    return result


def checked_runtime(path, values, build):
    path = Path(path).resolve()
    runtime = json.loads(path.read_text())
    require(runtime.get('schema_version') == 1 and runtime.get('kind') == 'metal_playtest_profile_runtime',
            'Explicit profile runtime evidence required')
    require(runtime.get('bounded_runtime_gate') is True and runtime.get('map') == values['map'],
            'Runtime evidence is incomplete or for a different map')
    require(runtime.get('timing_only') is not True, 'Timing-only evidence cannot promote a ready profile')
    require(runtime.get('build_proof') == build['proof'], 'Runtime/build proof identity mismatch')
    require(type(runtime.get('actual_host_returncode')) is int and runtime['actual_host_returncode'] == 0
            and type(runtime.get('actual_guest_returncode')) is int and runtime['actual_guest_returncode'] == 0,
            'Observed host and guest exit0 required')
    require(runtime.get('api_validation_enabled') is True and runtime.get('renderer_api_errors') == [],
            'Bounded API-validation run required')
    validate_display({'display': runtime.get('display', {})}, values)
    config_path = checked_descriptor(runtime['test_config'])
    config = tomllib.loads(config_path.read_text())
    validate_display(config, values)
    launch_log = runtime.get('launch_log')
    log_path = checked_descriptor(launch_log)
    aa = checked_anti_aliasing(log_path.read_text(errors='replace'), values)
    require(runtime.get('anti_aliasing') == aa and runtime.get('capture_stage') == 'post-world-AA/post-HUD',
            'Runtime AA execution/capture stage is not bound to the actual log')
    if values.get('native_fullscreen', False):
        require(build.get('native_resolution_api_verified') is True, 'Native resolution helper guard is missing')
        log_text = log_path.read_text(errors='replace')
        require('Metal API Validation Enabled' in log_text, 'Native runtime lacks the actual API validation startup marker')
        startup = checked_native_startup(log_text, values)
        require(runtime.get('native_resolution') == startup, 'Runtime native startup binding differs from the actual log')
    execution = json.loads(checked_descriptor(runtime['execution']).read_text())
    require(execution.get('log') == launch_log, 'Execution/runtime launch log identity mismatch')
    require(type(execution.get('returncode')) is int and execution['returncode'] == 0,
            'Execution record must bind observed exit0')
    require(execution.get('command') == [build['host']['file'], build['guest']['file']],
            'Execution is not the exact frozen host/guest command')
    environment = execution.get('environment_overrides', {})
    require(environment.get('HALO_SAVE_ROOT') == str(config_path.parent)
            and environment.get('HALO_WINDOWED') == windowed_environment(values),
            'Execution does not bind the tested config/window')
    require(isinstance(environment.get('HALO_DATA_ROOT'), str)
            and Path(environment['HALO_DATA_ROOT']).is_absolute(), 'Execution data root is not bound')
    allowed_diagnostics = {'HALO_GPU_STATS'} if environment.get('HALO_GPU_STATS') == '1' and config.get('debug', {}).get('gpu_stats') is True else set()
    require(not ((set(environment) & set(build['configuration_environment_names'])) - allowed_diagnostics),
            'Execution overrides presentation or normal configuration via environment')
    require('HALO_GPU_STATS' not in environment or 'HALO_GPU_STATS' in allowed_diagnostics,
            'GPU statistics override does not match the tested configuration')
    elapsed = execution.get('elapsed_seconds')
    require(type(elapsed) in (int, float) and 15 <= elapsed <= 600,
            'Bounded runtime evidence must observe at least15 seconds')
    capture = checked_descriptor(runtime['render_capture'])
    raw = capture.read_bytes()
    header = raw[:54]
    require(len(header) == 54, 'Truncated runtime capture header')
    if values.get('native_fullscreen', False):
        require(header[:2] == b'BM', 'Native runtime requires the original physical Metal BMP capture')
    if header[:8] == b'\x89PNG\r\n\x1a\n' and header[12:16] == b'IHDR':
        width, height = struct.unpack_from('>II', header, 16)
    elif header[:2] == b'BM' and len(header) == 54 and struct.unpack_from('<I', header, 14)[0] >= 40:
        width, height = struct.unpack_from('<ii', header, 18)
        height = abs(height)
    else:
        raise ValueError('Runtime capture must be an actual BMP or PNG')
    require((width, height) == physical_size(values),
            'Runtime capture does not prove requested physical render dimensions')
    if header[:2] == b'BM':
        offset = struct.unpack_from('<I', header, 10)[0]
        planes, bits, compression = struct.unpack_from('<HHI', header, 26)
        require(planes == 1 and bits in (24, 32) and compression == 0
                and offset >= 54 and len(raw) == offset + ((width * bits + 31) // 32) * 4 * height
                and struct.unpack_from('<I', header, 2)[0] == len(raw), 'Truncated/unsupported BMP capture')
        if values.get('native_fullscreen', False):
            require(bits == 32 and offset == 54 and any(any(raw[offset+channel::4]) for channel in (0,1,2)),
                    'Native physical capture must contain complete nonblack original BGRA pixels')
    else:
        require(header[24] == 8 and header[25] in (2, 6) and header[26:29] == bytes(3),
                'Unsupported PNG pixel layout')
        position, compressed, ended = 8, bytearray(), False
        while position < len(raw):
            require(position + 12 <= len(raw), 'Truncated PNG chunk')
            size = struct.unpack_from('>I', raw, position)[0]
            end = position + size + 12
            require(end <= len(raw), 'Truncated PNG payload')
            kind = raw[position+4:position+8]
            payload = raw[position+8:position+8+size]
            require(zlib.crc32(kind + payload) == struct.unpack_from('>I', raw, end-4)[0], 'PNG CRC mismatch')
            if kind == b'IDAT': compressed.extend(payload)
            if kind == b'IEND':
                require(size == 0 and end == len(raw), 'Invalid PNG ending')
                ended = True
            position = end
        expected = height * (1 + width * (3 if header[25] == 2 else 4))
        inflater = zlib.decompressobj()
        try:
            decoded = inflater.decompress(compressed, expected + 1)
        except zlib.error as error:
            raise ValueError('Invalid PNG compressed pixels') from error
        require(ended and inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail
                and len(decoded) == expected, 'Truncated/invalid PNG pixels')
    return descriptor(path)


def verify_profile(folder, require_ready=False):
    folder = Path(folder).resolve()
    manifest_path = folder / 'profile.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get('kind') == 'native_metal_playtest_profile' and manifest.get('schema_version') == 1,
            'Invalid profile manifest')
    require(manifest['profile_directory'] == str(folder), 'Profile was moved; create a new profile')
    values = manifest['profile']
    require(values == profile_values(values['map'], values['frame_limit'], values['render_height'], values['vsync'],
                                    values.get('native_fullscreen', False), values.get('native_size'), values.get('anti_aliasing')),
            'Profile values were altered')
    require(manifest.get('configuration_policy') == 'immutable-display-mutable-human-aa-v2',
            'Profile uses an older configuration policy; preserve it and prepare a fresh profile')
    for key in ('initial_config', 'init', 'producer', 'frozen_producer', 'template'):
        checked_descriptor(manifest[key])
    require(manifest['config']['file'] == str(folder / 'saves/config.toml')
            and manifest['initial_config']['file'] == str(folder / 'initial-config.toml')
            and manifest['init']['file'] == str(folder / 'data/init.txt'), 'Profile paths escape isolated saves/data')
    require(manifest['config']['sha256'] == manifest['initial_config']['sha256'],
            'Initial active configuration provenance changed')
    require(not (folder / 'initial-config.toml').is_symlink(), 'Initial configuration must remain an isolated immutable file')
    config_path = folder / 'saves/config.toml'
    require(config_path.is_file() and not config_path.is_symlink() and config_path.resolve() == config_path,
            'Active configuration escapes isolated saves')
    initial = tomllib.loads((folder / 'initial-config.toml').read_text())
    validate_config(initial, values)
    validate_config(tomllib.loads(config_path.read_text()), values, initial=initial)
    require((folder / 'data/init.txt').read_text() == 'game_variant slayer\nmap_name ' + values['map'] + '\n',
            'Unexpected original game initialization')
    assets = Path(manifest['original_assets'])
    require((folder / 'data/maps').is_symlink() and (folder / 'data/maps').resolve() == (assets / 'maps').resolve()
            and (folder / 'data/sounds').is_symlink() and (folder / 'data/sounds').resolve() == (assets / 'sounds').resolve(),
            'Original asset symlinks changed')
    for item in manifest['asset_files']:
        checked_descriptor(item)
    require({item['file'] for item in manifest['asset_files']} == {
        str((assets / 'maps' / (values['map'] + '.map')).resolve()),
        str((assets / 'maps/ui.map').resolve())}, 'Asset identities do not match the requested map/UI')
    require(manifest['launch_environment'] == dict(HALO_DATA_ROOT=str(folder / 'data'),
            HALO_SAVE_ROOT=str(folder / 'saves'), HALO_WINDOWED=windowed_environment(values)), 'Unexpected application environment')
    if require_ready:
        ready = json.loads((folder / 'ready.json').read_text())
        require(ready.get('experiment_ready') is True and ready['profile'] == descriptor(manifest_path),
                'Prepared profile lacks a valid ready promotion')
        build = checked_build(checked_descriptor(ready['build']['proof']), manifest['repository'], values.get('native_fullscreen', False))
        require(build == ready['build'], 'Build promotion changed')
        checked_runtime(checked_descriptor(ready['runtime_proof']), values, build)
        python = checked_descriptor(ready['verifier_python'])
        launcher = folder / 'Launch Native Metal.command'
        require(ready['launcher_file'] == str(launcher)
                and sha(launcher) == ready['launcher_sha256']
                and stat.S_IMODE(launcher.stat().st_mode) == 0o755,
                'Launcher changed or is not executable')
        require(launcher.read_text() == launcher_text(folder, build, python), 'Launcher command changed')
    return manifest


def launcher_text(folder, build, python):
    folder = Path(folder).resolve()
    quote = shlex.quote
    removals = ' '.join('-u ' + name for name in sorted(set(build['configuration_environment_names']) | {'HALO_GPU_STATS'}))
    values = json.loads((folder / 'profile.json').read_text())['profile']
    return ('#!/bin/zsh\nset -eu\n' + quote(str(python)) + ' ' + quote(str(folder / 'producer.py'))
            + ' verify --profile ' + quote(str(folder)) + ' --require-ready\n'
            + 'cd ' + quote(str(folder)) + '\nexec env ' + removals
            + ' HALO_DATA_ROOT=' + quote(str(folder / 'data'))
            + ' HALO_SAVE_ROOT=' + quote(str(folder / 'saves')) + ' HALO_WINDOWED=' + windowed_environment(values) + ' '
            + quote(build['host']['file']) + ' ' + quote(build['guest']['file']) + '\n')


def promote(folder, build_proof, runtime_proof):
    folder = Path(folder).resolve()
    require(not (folder / 'ready.json').exists(), 'Ready record exists; preserve it and choose a new profile')
    manifest = verify_profile(folder)
    build = checked_build(build_proof, manifest['repository'], manifest['profile'].get('native_fullscreen', False))
    runtime = checked_runtime(runtime_proof, manifest['profile'], build)
    # Runtime bytes remain immutable evidence, separate from preferences the
    # human game is allowed to save during later launches.
    tested_config = Path(json.loads(Path(runtime['file']).read_text())['test_config']['file']).resolve()
    require(not tested_config.is_relative_to(folder), 'Runtime config must be isolated from mutable human saves')
    launcher = folder / 'Launch Native Metal.command'
    require(not launcher.exists(), 'Launcher exists; preserve existing destination')
    python = Path(sys.executable).resolve()
    text = launcher_text(folder, build, python)
    ready = dict(schema_version=1, kind='native_metal_playtest_ready', experiment_ready=True,
        profile=descriptor(folder / 'profile.json'), build=build, runtime_proof=runtime,
        launcher_file=str(launcher), launcher_sha256=hashlib.sha256(text.encode()).hexdigest(),
        verifier_python=descriptor(python), simulation_hz=30,
        manual_input_audio_gate=False, achieved_render_fps_gate=False, performance_improvement_gate=False,
        original_xbox_fidelity_gate=False, full_game_gate=False,
        scope='Experimental human launcher for this exact bounded runtime-tested presentation profile; no manual input/audio, achieved FPS, performance or full-game claim.')
    with launcher.open('x') as handle:
        handle.write(text)
    launcher.chmod(0o755)
    new_json(folder / 'ready.json', ready)
    verify_profile(folder, True)
    return ready


def chooser(output, profiles):
    """Generate a Terminal chooser over ready profiles; never execute it."""
    output = Path(output).resolve()
    require(not output.exists(), 'Chooser destination exists; preserve it and choose a new path')
    require(profiles, 'At least one ready profile required')
    records, labels, identities = [], [], set()
    for folder in profiles:
        folder = Path(folder).resolve()
        manifest = verify_profile(folder, True)
        v = manifest['profile']
        identity = tuple(v[k] for k in ('map', 'frame_limit', 'render_height', 'vsync', 'anti_aliasing')) + (v.get('native_fullscreen', False),)
        require(identity not in identities, 'Duplicate chooser presentation profile')
        identities.add(identity)
        cap = str(v['frame_limit']) + ' FPS cap' if v['frame_limit'] else ('Display paced' if v['vsync'] else 'Uncapped')
        label = {'bloodgulch': 'Blood Gulch', 'damnation': 'Damnation', 'hangemhigh': 'Hang Em High'}[v['map']]
        width, height = physical_size(v)
        presentation = 'native fullscreen' if v.get('native_fullscreen', False) else 'pixels'
        labels.append(f'{label} | {cap} | {width}x{height} {presentation} | AA {v["anti_aliasing"].upper()} | vsync {"on" if v["vsync"] else "off"}')
        records.append(dict(directory=str(folder), profile=descriptor(folder / 'profile.json'),
                            ready=descriptor(folder / 'ready.json'), launcher=descriptor(folder / 'Launch Native Metal.command')))
    quote = shlex.quote
    text = '#!/bin/zsh\nset -eu\nprint -r -- "Native Metal experimental playtest: choose a tested profile."\n'
    text += 'print -r -- "Caps are requests; achieved FPS, manual input/audio and original fidelity remain unverified."\n'
    text += 'select choice in ' + ' '.join(quote(label) for label in labels + ['Cancel']) + '; do\ncase "$REPLY" in\n'
    for index, record in enumerate(records, 1):
        text += str(index) + ') exec ' + quote(record['launcher']['file']) + ' ;;\n'
    text += str(len(records) + 1) + ') exit 0 ;;\n*) print -r -- "Choose a listed number." ;;\nesac\ndone\n'
    output.mkdir(parents=True)
    path = output / 'Choose Native Metal Playtest.command'
    with path.open('x') as handle:
        handle.write(text)
    path.chmod(0o755)
    menu = dict(schema_version=1, kind='native_metal_ready_profile_chooser', experiment_ready=True, ready_profiles=records,
                producer=descriptor(Path(__file__)), launcher=descriptor(path), process_launched=False,
                scope='Chooser references exact previously ready profiles; their launchers revalidate source/build/runtime before launch.')
    new_json(output / 'chooser.json', menu)
    return menu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    draft = commands.add_parser('prepare', help='Create a new isolated unready profile; never launch')
    draft.add_argument('--map', choices=MAPS, required=True)
    draft.add_argument('--render-cap', choices=CAPS, type=int, required=True)
    resolution = draft.add_mutually_exclusive_group(required=True)
    resolution.add_argument('--render-height', choices=HEIGHTS, type=int)
    resolution.add_argument('--native-fullscreen', action='store_true', help='Render at actual fullscreen Retina drawable pixels')
    draft.add_argument('--native-size', type=parse_native_size, help='Measured expected drawable WxH; an expectation, not a resolution override')
    draft.add_argument('--vsync', choices=('on', 'off'), required=True)
    draft.add_argument('--anti-aliasing', choices=ANTI_ALIASING, default='off')
    draft.add_argument('--assets', type=Path, required=True)
    draft.add_argument('--template', type=Path, required=True)
    draft.add_argument('--output', type=Path, required=True)
    ready = commands.add_parser('promote', help='Bind NEW build and exact-profile runtime proof; create launcher only')
    ready.add_argument('--profile', type=Path, required=True)
    ready.add_argument('--build-proof', type=Path, required=True)
    ready.add_argument('--runtime-proof', type=Path, required=True)
    check = commands.add_parser('verify', help='Read-only profile/build/runtime integrity check')
    check.add_argument('--profile', type=Path, required=True)
    check.add_argument('--require-ready', action='store_true')
    menu = commands.add_parser('chooser', help='Create a human Terminal menu over exact ready profiles; never run')
    menu.add_argument('--output', type=Path, required=True)
    menu.add_argument('--profiles', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.output, args.map, args.render_cap, args.render_height,
                         args.vsync == 'on', args.assets, args.template,
                         native_fullscreen=args.native_fullscreen, native_size=args.native_size,
                         anti_aliasing=args.anti_aliasing)
    elif args.command == 'promote':
        result = promote(args.profile, args.build_proof, args.runtime_proof)
    elif args.command == 'verify':
        result = verify_profile(args.profile, args.require_ready)
    else:
        result = chooser(args.output, args.profiles)
    verified_ready = args.command == 'verify' and args.require_ready
    print(json.dumps({'profile': str(Path(args.output if args.command in ('prepare', 'chooser') else args.profile).resolve()),
                      'experiment_ready': verified_ready or result.get('experiment_ready', False), 'command': args.command}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Profile rejected: ' + str(error), file=sys.stderr)
        sys.exit(1)
