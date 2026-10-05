#!/usr/bin/env python3
"""Collect one bounded native run of an exact prepared display profile.

This command launches the frozen native host/guest once. Run it sequentially;
each --output must be new. CPU tests replace the process runner and never start
the game. A clean exit and nonblack capture do not establish image fidelity,
manual input/audio, achieved cap, or performance improvement.
"""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import tomllib
import zlib

try:
    from tools import metal_playtest_profiles as profiles
except ImportError:
    import metal_playtest_profiles as profiles

require, sha, descriptor, new_json = profiles.require, profiles.sha, profiles.descriptor, profiles.new_json
DISPLAY_KEYS = ('frame_limit', 'render_height', 'vsync', 'interpolation', 'high_res_hud', 'direct_camera', 'screen_width')
TELEMETRY = re.compile(
    r'Native display: ([0-9]+(?:\.[0-9]+)?) FPS, ([0-9]+(?:\.[0-9]+)?) simulation Hz, '
    r'(\d+)x(\d+) storage, (\d+)x(\d+) logical, cap (-?\d+), interpolation ([01]), ticks (-?\d+)-(-?\d+)')
FAULT = re.compile(
    r'Validation Error|failed assertion|Assertion failed|command buffer was aborted|'
    r'Native Metal: .* failed|Native unsupported|guest abort|SIGSEGV|EXCEPTION halt in', re.I)


def validate_duration(duration):
    require(type(duration) in (int, float) and math.isfinite(duration) and 15 <= duration <= 580,
            'Duration must be finite and bounded15..580 seconds')


def controlled_config(template, values, output, duration):
    validate_duration(duration)
    original = tomllib.loads(template)
    profiles.validate_config(original, values)
    result = template
    updates = {
        'audio': {'enabled': False},
        'input': {'mouse_sensitivity': 1e-20},
        'bindings': {key: '' for key in original['bindings']},
        'debug': {'test_input': 'bot:0', 'exit_after': float(duration), 'gpu_stats': True,
                  'screenshot_every': (values['frame_limit'] or 120) * 5,
                  'screenshot_directory': str(Path(output) / 'captures')}}
    for section, fields in updates.items():
        for key, value in fields.items():
            encoded = str(value).lower() if type(value) is bool else json.dumps(value)
            result = profiles.set_key(result, section, key, encoded)
    current = tomllib.loads(result)
    validate_config(current, values, output, duration)
    require(current['display'] == original['display'], 'Runtime changed the human profile display settings')
    return result


def validate_config(config, values, output, duration):
    profiles.validate_display(config, values)
    require(config['display']['fullscreen'] is False and config['display']['window_scale'] == 2,
            'Runtime window settings differ')
    require(config['audio']['enabled'] is False and config['input']['mouse_sensitivity'] == 1e-20
            and isinstance(config['bindings'], dict) and config['bindings']
            and all(value == '' for value in config['bindings'].values()), 'Runtime human controls/audio are enabled')
    require(all(config['network'][k] is False for k in ('online', 'allow_upnp', 'join_from_clipboard'))
            and config['update']['auto'] is False, 'Runtime must remain offline with updates off')
    debug = config['debug']
    require(debug['test_input'] == 'bot:0' and debug['exit_after'] == duration and debug['gpu_stats'] is True
            and debug['screenshot_every'] == (values['frame_limit'] or 120) * 5,
            'Runtime scripted diagnostics differ')
    require(debug['screenshot_directory'] == str(Path(output) / 'captures'), 'Captures escape the isolated run')
    require(all(debug[k] is False for k in ('hidden_window', 'null_renderer', 'telnet_console',
                                           'gpu_debug_texture0', 'gpu_debug_flat')), 'Runtime renderer/debug override enabled')
    require(all(debug[k] == '' for k in ('texture_dump_directory', 'gpu_skip_vertex_shaders', 'gpu_dump_shaders',
                                        'gpu_debug_expression', 'network_test')), 'Runtime debug replacement enabled')
    require(debug['network_latency'] == debug['network_loss'] == 0, 'Runtime artificial networking enabled')


def flattened_config(config, prefix=()):
    result = {}
    for key, value in config.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            result.update(flattened_config(value, path))
        else:
            result['.'.join(path)] = value
    return result


def same_value(expected, actual):
    # The real-valued config parser also accepts integral TOML numbers.
    if type(expected) is float:
        return type(actual) in (int, float) and expected == actual
    return type(actual) is type(expected) and actual == expected


def compiled_defaults(build):
    """Read literal defaults from the exact source bound to the compiled guest."""
    text = (Path(build['snapshot']) / 'port/linux/src/port_config.c').read_text()
    entries = re.findall(r'\{\s*"([a-zA-Z0-9_.]+)"\s*,\s*_config_(boolean|integer|real|string)\s*,\s*'
                         r'("(?:[^"\\]|\\.)*")\s*,', text)
    result = {}
    for name, _, literal in entries:
        encoded = ast.literal_eval(literal)
        value = tomllib.loads('value = ' + encoded)['value']
        require(name not in result, 'Duplicate compiled config default: ' + name)
        result[name] = value
    return result


def validate_saved_config(initial, saved, defaults):
    expected, actual = flattened_config(initial), flattened_config(saved)
    for name, value in expected.items():
        require(name in actual and same_value(value, actual[name]), 'Runtime changed an initial setting: ' + name)
    additions = {}
    for name in actual.keys() - expected.keys():
        require(name in defaults and same_value(defaults[name], actual[name]),
                'Runtime inserted an unknown or nondefault setting: ' + name)
        additions[name] = actual[name]
    return additions


def sanitized_environment(output, configuration_names, source=None, api_validation=True):
    source = os.environ if source is None else source
    environment, removed = {}, []
    for key, value in source.items():
        if (key in configuration_names or key.startswith(('HALO_', 'MTL_', 'METAL_', 'Malloc'))
                or key in ('DYLD_INSERT_LIBRARIES', 'LD_PRELOAD', 'ASAN_OPTIONS', 'UBSAN_OPTIONS', 'LLVM_PROFILE_FILE')):
            removed.append(key)
        else:
            environment[key] = value
    overrides = dict(HALO_DATA_ROOT=str(Path(output) / 'data'), HALO_SAVE_ROOT=str(Path(output) / 'saves'),
                     HALO_WINDOWED='1')
    if api_validation:
        overrides['MTL_DEBUG_LAYER'] = '1'
    environment.update(overrides)
    return environment, overrides, sorted(removed)


def prepare(output, profile, build_proof, duration, api_validation=True):
    validate_duration(duration)
    require(type(api_validation) is bool, 'API validation selection must be a boolean')
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'Fresh output required; preserve previous runs and saves')
    output, profile = output.resolve(), Path(profile).resolve()
    manifest = profiles.verify_profile(profile)
    require(manifest['producer'] == descriptor(profiles.__file__), 'Profile was prepared by a different verifier')
    build = profiles.checked_build(build_proof, manifest['repository'])
    assets = Path(manifest['original_assets']).resolve()
    require(not output.is_relative_to(profile) and not output.is_relative_to(assets),
            'Run output must be separate from the human profile and original assets')
    configuration = controlled_config(Path(manifest['config']['file']).read_text(), manifest['profile'], output, duration)
    output.mkdir(parents=True)
    for name in ('data', 'saves', 'captures'):
        (output / name).mkdir()
    for name in ('maps', 'sounds'):
        (output / 'data' / name).symlink_to(assets / name, target_is_directory=True)
    (output / 'data/init.txt').write_bytes(Path(manifest['init']['file']).read_bytes())
    (output / 'saves/config.toml').write_text(configuration)
    (output / 'initial-config.toml').write_text(configuration)
    frozen = output / 'producer.py'
    shutil.copy2(__file__, frozen)
    require(sha(__file__) == sha(frozen), 'Runtime producer changed during preparation')
    _, overrides, removed = sanitized_environment(output, build['configuration_environment_names'], api_validation=api_validation)
    plan = dict(schema_version=1, kind='native_metal_display_runtime_plan', profile=descriptor(profile / 'profile.json'),
        profile_directory=str(profile), values=manifest['profile'], build=build, duration_seconds=duration,
        command=[build['host']['file'], build['guest']['file']], cwd=str(output),
        test_config=descriptor(output / 'saves/config.toml'), initial_config=descriptor(output / 'initial-config.toml'),
        init=descriptor(output / 'data/init.txt'),
        asset_files=manifest['asset_files'], original_assets=str(assets), environment_overrides=overrides,
        removed_environment_names=removed, api_validation_requested=api_validation,
        producer=descriptor(__file__), frozen_producer=descriptor(frozen),
        fresh_saves_required=True, process_launched=False)
    new_json(output / 'launch-plan.json', plan)
    return plan


def verify_prepared(output, plan, after_execution=False):
    output = Path(output)
    manifest = profiles.verify_profile(plan['profile_directory'])
    require(descriptor(Path(plan['profile_directory']) / 'profile.json') == plan['profile'], 'Profile manifest changed')
    require(manifest['profile'] == plan['values'], 'Requested profile changed')
    require(profiles.checked_build(plan['build']['proof']['file'], manifest['repository']) == plan['build'],
            'Frozen/current build changed after preparation')
    for key in ('initial_config', 'init', 'producer', 'frozen_producer'):
        profiles.checked_descriptor(plan[key])
    if not after_execution:
        profiles.checked_descriptor(plan['test_config'])
        require(plan['test_config']['sha256'] == plan['initial_config']['sha256'], 'Initial runtime bytes differ')
    for item in plan['asset_files']:
        profiles.checked_descriptor(item)
    config = tomllib.loads((output / 'saves/config.toml').read_text())
    initial = tomllib.loads(Path(plan['initial_config']['file']).read_text())
    additions = validate_saved_config(initial, config, compiled_defaults(plan['build']))
    validate_config(config, plan['values'], output, plan['duration_seconds'])
    require((output / 'data/init.txt').read_text() == 'game_variant slayer\nmap_name ' + plan['values']['map'] + '\n',
            'Runtime initialization changed')
    for name in ('maps', 'sounds'):
        link = output / 'data' / name
        require(link.is_symlink() and link.resolve() == (Path(plan['original_assets']) / name).resolve(),
                'Runtime asset symlink changed')
    return additions


def execute_process(command, cwd, environment, log_path, timeout_seconds):
    """One actual process; record its return code even after bounded termination."""
    start, timed_out = time.monotonic(), False
    with Path(log_path).open('xb') as log:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return dict(returncode=process.returncode, elapsed_seconds=time.monotonic() - start, timed_out=timed_out)


def parse_log(log):
    rows = []
    telemetry_errors = []
    for line in log.splitlines():
        if 'Native display:' not in line:
            continue
        match = TELEMETRY.search(line)
        if not match:
            telemetry_errors.append('Malformed native display telemetry: ' + line)
            continue
        fps, hz = map(float, match.group(1, 2))
        numbers = list(map(int, match.group(*range(3, 11))))
        rows.append(dict(render_fps=fps, simulation_hz=hz,
            storage_width=numbers[0], storage_height=numbers[1], logical_width=numbers[2], logical_height=numbers[3],
            frame_limit=numbers[4], interpolation=bool(numbers[5]), first_tick=numbers[6], last_tick=numbers[7]))
    exits = list(map(int, re.findall(r'Game exited \((-?\d+)\)', log)))
    return dict(telemetry=rows, telemetry_errors=telemetry_errors,
        actual_guest_returncode=exits[-1] if len(exits) == 1 else None,
        guest_exit_records=exits, api_validation_enabled='Metal API Validation Enabled' in log,
        renderer_api_errors=[line for line in log.splitlines() if FAULT.search(line)])


def validate_telemetry(rows, values):
    require(rows, 'Native display FPS/simulation telemetry is missing')
    for row in rows:
        require(row['storage_width'] == values['expected_physical_width']
                and row['storage_height'] == values['render_height']
                and row['logical_width'] == values['logical_width'] and row['logical_height'] == values['logical_height'],
                'Native telemetry storage/logical dimensions do not match requested profile')
        require(row['frame_limit'] == values['frame_limit'] and row['interpolation'] is values['interpolation'],
                'Native telemetry cap/interpolation do not match requested profile')
        require(math.isfinite(row['render_fps']) and row['render_fps'] > 0
                and math.isfinite(row['simulation_hz']) and row['simulation_hz'] >= 0,
                'Invalid native FPS/simulation telemetry')
    require(sum(row['simulation_hz'] > 0 and row['first_tick'] >= 0 and row['last_tick'] > row['first_tick']
                for row in rows) >= 2, 'Several positive original simulation tick intervals are required')


def read_bmp(path, values):
    """Validate every stored byte and decode RGB; alpha alone is not nonblack."""
    raw = Path(path).read_bytes()
    require(len(raw) >= 54 and raw[:2] == b'BM', 'Capture is not a complete BMP')
    length, offset, dib = struct.unpack_from('<I', raw, 2)[0], struct.unpack_from('<I', raw, 10)[0], struct.unpack_from('<I', raw, 14)[0]
    width, signed_height, planes, bits, compression, image_size = struct.unpack_from('<iiHHII', raw, 18)
    height = abs(signed_height)
    require((width, height) == (values['expected_physical_width'], values['render_height']),
            'Capture physical dimensions do not match requested profile')
    require(dib == 40 and planes == 1 and bits in (24, 32) and compression == 0 and offset == 54,
            'Unsupported native BMP layout')
    stride = ((width * bits + 31) // 32) * 4
    require(length == len(raw) == offset + stride * height and image_size == stride * height,
            'Truncated or inconsistent BMP payload')
    rows = []
    for y in range(height):
        row = raw[offset + y * stride:offset + y * stride + width * (bits // 8)]
        rgb = bytearray(width * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::bits // 8], row[1::bits // 8], row[0::bits // 8]
        rows.append(bytes(rgb))
    if signed_height > 0:
        rows.reverse()
    rgb = b''.join(rows)
    require(any(rgb), 'Capture RGB is entirely black')
    return width, height, rgb


def write_png(path, width, height, rgb):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    rows = b''.join(b'\0' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    encoded = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    with Path(path).open('xb') as handle:
        handle.write(encoded)


def collect(output, plan, execution):
    output = Path(output)
    state = parse_log((output / 'launch.log').read_text(errors='replace'))
    errors = list(state['telemetry_errors'])
    saved_defaults = {}
    try:
        saved_defaults = verify_prepared(output, plan, after_execution=True)
        validate_telemetry(state['telemetry'], plan['values'])
    except (ValueError, OSError, KeyError) as error:
        errors.append(str(error))
    captures = sorted((output / 'captures').glob('frame*.bmp'),
                      key=lambda path: int(path.stem[5:]) if path.stem[5:].isdigit() else -1)
    capture, image = None, None
    try:
        require(captures and captures[-1].stem[5:].isdigit(), 'Native render capture is missing')
        last = captures[-1]
        require(not last.is_symlink(), 'Capture must be stored in the isolated run')
        width, height, rgb = read_bmp(last, plan['values'])
        capture = descriptor(last)
        inspection = output / 'inspection.png'
        write_png(inspection, width, height, rgb)
        image = dict(width=width, height=height, nonblack=True, capture_frame=int(last.stem[5:]),
            rgb_sha256=hashlib.sha256(rgb).hexdigest(), inspection_image=descriptor(inspection), visually_inspected=False)
    except (ValueError, OSError, struct.error) as error:
        errors.append(str(error))
    elapsed = execution['elapsed_seconds']
    diagnostic_gate = (type(execution['returncode']) is int and execution['returncode'] == 0
            and execution['timed_out'] is False and 15 <= elapsed <= 600
            and type(state['actual_guest_returncode']) is int and state['actual_guest_returncode'] == 0
            and state['renderer_api_errors'] == []
            and not errors and capture is not None)
    gate = diagnostic_gate and plan['api_validation_requested'] is True and state['api_validation_enabled'] is True
    actual_config = descriptor(output / 'saves/config.toml')
    actual_display = tomllib.loads((output / 'saves/config.toml').read_text()).get('display', {})
    result = dict(schema_version=1, kind='metal_playtest_profile_runtime', bounded_runtime_gate=gate,
        complete=True, passed=gate, build_proof=plan['build']['proof'], map=plan['values']['map'],
        display={key: actual_display.get(key) for key in DISPLAY_KEYS},
        actual_host_returncode=execution['returncode'], actual_guest_returncode=state['actual_guest_returncode'],
        api_validation_enabled=state['api_validation_enabled'], api_validation_requested=plan['api_validation_requested'],
        diagnostic_execution_gate=diagnostic_gate, renderer_api_errors=state['renderer_api_errors'],
        execution=descriptor(output / 'execution.json'), test_config=actual_config, input_config=plan['initial_config'],
        saved_default_insertions=saved_defaults, render_capture=capture,
        launch_log=descriptor(output / 'launch.log'), launch_plan=descriptor(output / 'launch-plan.json'),
        profile=plan['profile'], producer=plan['producer'], frozen_producer=plan['frozen_producer'],
        metrics=state['telemetry'], guest_exit_records=state['guest_exit_records'], validation_failures=errors, image=image,
        awaiting_image_review=gate, world_weapon_hud_pixels_visually_inspected=False,
        simulation_source_modified=False, requested_simulation_hz=30,
        manual_input_audio_gate=False, achieved_render_fps_gate=False, performance_improvement_gate=False,
        original_xbox_fidelity_gate=False, full_game_gate=False,
        scope='One bounded native display-profile run with API validation and complete nonblack physical capture. '
              'Telemetry is diagnostic; world/weapon/HUD image review, manual input/audio, achieved cap, '
              'performance improvement, original Xbox fidelity and full-game completion are unverified.')
    new_json(output / 'runtime.json', result)
    if gate:
        profiles.checked_runtime(output / 'runtime.json', plan['values'], plan['build'])
    return result


def run(output, profile, build_proof, duration=20, runner=None, api_validation=True):
    plan = prepare(output, profile, build_proof, duration, api_validation)
    output = Path(plan['cwd'])
    verify_prepared(output, plan)
    require(list((output / 'saves').iterdir()) == [output / 'saves/config.toml'], 'Runtime save state is not fresh')
    environment, overrides, removed = sanitized_environment(output, plan['build']['configuration_environment_names'],
                                                           api_validation=api_validation)
    require(overrides == plan['environment_overrides'], 'Runtime environment changed')
    runner = execute_process if runner is None else runner
    observation = runner(plan['command'], plan['cwd'], environment, output / 'launch.log', duration + 20)
    execution = dict(schema_version=1, kind='observed_native_metal_display_execution', **observation,
        command=plan['command'], cwd=plan['cwd'], environment_overrides=overrides,
        removed_environment_names=removed, api_validation_requested=api_validation,
        launch_plan=descriptor(output / 'launch-plan.json'),
        input_config=plan['initial_config'], test_config=descriptor(output / 'saves/config.toml'),
        producer=plan['producer'], fresh_save_state_verified_before_launch=True,
        log=descriptor(output / 'launch.log'))
    new_json(output / 'execution.json', execution)
    return collect(output, plan, execution)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-proof', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=20)
    parser.add_argument('--api-validation', choices=('on', 'off'), default='on',
                        help='Defaulton is required for profile promotion; off records diagnostics with the bounded gate false')
    args = parser.parse_args()
    try:
        result = run(args.output, args.profile, args.build_proof, args.duration, api_validation=args.api_validation == 'on')
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(dict(runtime=descriptor(args.output / 'runtime.json'), passed=result['passed'],
        host_exit=result['actual_host_returncode'], guest_exit=result['actual_guest_returncode'],
        last_metrics=result['metrics'][-1] if result['metrics'] else None,
        validation_failures=result['validation_failures'], renderer_api_errors=result['renderer_api_errors'],
        inspection_image=result['image']['inspection_image'] if result['image'] else None), indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
