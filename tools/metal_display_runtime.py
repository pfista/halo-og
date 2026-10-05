#!/usr/bin/env python3
"""Collect one bounded native run of an exact prepared display profile.

This command launches the frozen native host/guest once. Run it sequentially;
each --output must be new. CPU tests replace the process runner and never start
the game. A clean exit and nonblack capture do not establish image fidelity,
manual input/audio, achieved cap, or performance improvement.
--timing-only disables capture work and records host/presentation timing;
those diagnostics cannot promote a ready launcher. Native profiles without a
size expectation can measure the fullscreen drawable but remain unready.
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
DISPLAY_KEYS = ('frame_limit', 'render_height', 'vsync', 'interpolation', 'high_res_hud', 'direct_camera', 'screen_width', 'fullscreen')
TELEMETRY = re.compile(
    r'Native display: ([0-9]+(?:\.[0-9]+)?) FPS, ([0-9]+(?:\.[0-9]+)?) simulation Hz, '
    r'(\d+)x(\d+) storage, (\d+)x(\d+) logical, cap (-?\d+), interpolation ([01]), ticks (-?\d+)-(-?\d+)')
FRAME_TIMING = re.compile(r'Native timing: frame (\d+), monotonic (\d+) ns, tick (-?\d+), initialized ([01])')
FAULT = re.compile(
    r'Validation Error|failed assertion|Assertion failed|command buffer was aborted|'
    r'Native Metal: .* failed|Native unsupported|guest abort|SIGSEGV|EXCEPTION halt in', re.I)
HOST_METRICS = re.compile(
    r'Native Metal host metrics: (\d+) frames, (\d+) submits, (\d+) draws, (\d+) bytes; '
    r'packet-copy (\d+) us, prepare (\d+) us, encode (\d+) us, drawable-wait (\d+) us, commit (\d+) us, '
    r'completion-wait (\d+) us, gpu (\d+) us/(\d+) samples; packet-buffers (\d+), sampler-hits (\d+), '
    r'sampler-misses (\d+), sampler-allocations (\d+), sampler-cache (\d+), upload-buffers (\d+), visibility-buffers (\d+)')
HOST_METRIC_KEYS = ('frames', 'submissions', 'draws', 'bytes', 'packet_copy_us', 'prepare_us', 'encode_us',
                    'drawable_wait_us', 'commit_us', 'completion_wait_us', 'gpu_us', 'gpu_samples',
                    'packet_buffers', 'sampler_hits', 'sampler_misses', 'sampler_allocations', 'sampler_cache',
                    'upload_buffers', 'visibility_buffers')


def validate_duration(duration):
    require(type(duration) in (int, float) and math.isfinite(duration) and 15 <= duration <= 580,
            'Duration must be finite and bounded15..580 seconds')


def controlled_config(template, values, output, duration, timing_only=False):
    validate_duration(duration)
    require(type(timing_only) is bool, 'Timing-only selection must be a boolean')
    original = tomllib.loads(template)
    profiles.validate_config(original, values)
    result = template
    updates = {
        'audio': {'enabled': False},
        'input': {'mouse_sensitivity': 1e-20},
        'bindings': {key: '' for key in original['bindings']},
        'debug': {'test_input': 'bot:0', 'exit_after': float(duration), 'gpu_stats': True,
                  'screenshot_every': 0 if timing_only else (values['frame_limit'] or 120) * 5,
                  'screenshot_directory': '' if timing_only else str(Path(output) / 'captures')}}
    for section, fields in updates.items():
        for key, value in fields.items():
            encoded = str(value).lower() if type(value) is bool else json.dumps(value)
            result = profiles.set_key(result, section, key, encoded)
    current = tomllib.loads(result)
    validate_config(current, values, output, duration, timing_only)
    require(current['display'] == original['display'], 'Runtime changed the human profile display settings')
    return result


def validate_config(config, values, output, duration, timing_only=False):
    profiles.validate_display(config, values)
    require(config['display']['fullscreen'] is values.get('native_fullscreen', False) and config['display']['window_scale'] == 2,
            'Runtime window settings differ')
    require(config['audio']['enabled'] is False and config['input']['mouse_sensitivity'] == 1e-20
            and isinstance(config['bindings'], dict) and config['bindings']
            and all(value == '' for value in config['bindings'].values()), 'Runtime human controls/audio are enabled')
    require(all(config['network'][k] is False for k in ('online', 'allow_upnp', 'join_from_clipboard'))
            and config['update']['auto'] is False, 'Runtime must remain offline with updates off')
    debug = config['debug']
    require(debug['test_input'] == 'bot:0' and debug['exit_after'] == duration and debug['gpu_stats'] is True
            and debug['screenshot_every'] == (0 if timing_only else (values['frame_limit'] or 120) * 5),
            'Runtime scripted diagnostics differ')
    require(debug['screenshot_directory'] == ('' if timing_only else str(Path(output) / 'captures')), 'Capture configuration differs from the isolated run')
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


def sanitized_environment(output, configuration_names, source=None, api_validation=True,
                          native_fullscreen=False, gpu_statistics=False):
    source = os.environ if source is None else source
    environment, removed = {}, []
    for key, value in source.items():
        if (key in configuration_names or key.startswith(('HALO_', 'MTL_', 'METAL_', 'Malloc'))
                or key in ('DYLD_INSERT_LIBRARIES', 'LD_PRELOAD', 'ASAN_OPTIONS', 'UBSAN_OPTIONS', 'LLVM_PROFILE_FILE')):
            removed.append(key)
        else:
            environment[key] = value
    overrides = dict(HALO_DATA_ROOT=str(Path(output) / 'data'), HALO_SAVE_ROOT=str(Path(output) / 'saves'),
                     HALO_WINDOWED='0' if native_fullscreen else '1')
    if gpu_statistics:
        overrides['HALO_GPU_STATS'] = '1'
    if api_validation:
        overrides['MTL_DEBUG_LAYER'] = '1'
    environment.update(overrides)
    return environment, overrides, sorted(removed)


def prepare(output, profile, build_proof, duration, api_validation=True, timing_only=False):
    validate_duration(duration)
    require(type(api_validation) is bool, 'API validation selection must be a boolean')
    require(type(timing_only) is bool, 'Timing-only selection must be a boolean')
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'Fresh output required; preserve previous runs and saves')
    output, profile = output.resolve(), Path(profile).resolve()
    manifest = profiles.verify_profile(profile)
    if not manifest['profile'].get('native_fullscreen',False) or manifest['profile'].get('native_size'):
        profiles.physical_size(manifest['profile'])
    require(manifest['producer'] == descriptor(profiles.__file__), 'Profile was prepared by a different verifier')
    native_fullscreen = manifest['profile'].get('native_fullscreen', False)
    build = profiles.checked_build(build_proof, manifest['repository'], native_fullscreen)
    assets = Path(manifest['original_assets']).resolve()
    require(not output.is_relative_to(profile) and not output.is_relative_to(assets),
            'Run output must be separate from the human profile and original assets')
    configuration = controlled_config(Path(manifest['config']['file']).read_text(), manifest['profile'], output, duration, timing_only)
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
    gpu_statistics = native_fullscreen or timing_only
    _, overrides, removed = sanitized_environment(output, build['configuration_environment_names'], api_validation=api_validation,
                                                native_fullscreen=native_fullscreen, gpu_statistics=gpu_statistics)
    plan = dict(schema_version=1, kind='native_metal_display_runtime_plan', profile=descriptor(profile / 'profile.json'),
        profile_directory=str(profile), values=manifest['profile'], build=build, duration_seconds=duration,
        command=[build['host']['file'], build['guest']['file']], cwd=str(output),
        test_config=descriptor(output / 'saves/config.toml'), initial_config=descriptor(output / 'initial-config.toml'),
        init=descriptor(output / 'data/init.txt'),
        asset_files=manifest['asset_files'], original_assets=str(assets), environment_overrides=overrides,
        removed_environment_names=removed, api_validation_requested=api_validation,
        timing_only=timing_only, gpu_statistics_requested=gpu_statistics,
        producer=descriptor(__file__), frozen_producer=descriptor(frozen),
        fresh_saves_required=True, process_launched=False)
    new_json(output / 'launch-plan.json', plan)
    return plan


def verify_prepared(output, plan, after_execution=False):
    output = Path(output)
    manifest = profiles.verify_profile(plan['profile_directory'])
    require(descriptor(Path(plan['profile_directory']) / 'profile.json') == plan['profile'], 'Profile manifest changed')
    require(manifest['profile'] == plan['values'], 'Requested profile changed')
    require(profiles.checked_build(plan['build']['proof']['file'], manifest['repository'],
                                   plan['values'].get('native_fullscreen', False)) == plan['build'],
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
    validate_config(config, plan['values'], output, plan['duration_seconds'], plan.get('timing_only', False))
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
    host_metrics = []
    host_metrics_errors = []
    frame_timing = []
    for line in log.splitlines():
        if 'Native timing:' in line:
            timing = FRAME_TIMING.search(line)
            if timing:
                frame,ns,tick,initialized = map(int,timing.groups())
                frame_timing.append(dict(frame=frame,monotonic_ns=ns,tick=tick,initialized=bool(initialized)))
            else:
                telemetry_errors.append('Malformed native frame timing: ' + line)
        if 'Native Metal host metrics:' in line:
            host = HOST_METRICS.search(line)
            if host:
                host_metrics.append(dict(zip(HOST_METRIC_KEYS, map(int, host.groups()))))
            else:
                host_metrics_errors.append('Malformed native host metrics: ' + line)
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
    return dict(telemetry=rows, telemetry_errors=telemetry_errors, host_metrics=host_metrics,
        host_metrics_errors=host_metrics_errors, frame_timing=frame_timing,
        actual_guest_returncode=exits[-1] if len(exits) == 1 else None,
        guest_exit_records=exits, api_validation_enabled='Metal API Validation Enabled' in log,
        renderer_api_errors=[line for line in log.splitlines() if FAULT.search(line)])


def summarize_frame_timing(rows, tick_cutoff=150):
    """Adjacent completed-present intervals after five simulation seconds.

    Per-frame diagnostics run on the same guest for each comparison, so their
    logging cost is included. These samples describe presentation intervals,
    including cap waits; they are not isolated CPU/GPU durations.
    """
    intervals = []
    discarded = 0
    for previous,current in zip(rows,rows[1:]):
        if not (previous['initialized'] and current['initialized'] and
                previous['tick']>=tick_cutoff and current['tick']>=tick_cutoff):
            continue
        if (current['frame']!=previous['frame']+1 or current['monotonic_ns']<=previous['monotonic_ns']
                or current['tick']<previous['tick']):
            discarded += 1
            continue
        intervals.append(current['monotonic_ns']-previous['monotonic_ns'])
    if not intervals:
        return None
    ordered = sorted(intervals)
    def percentile(fraction):
        index=(len(ordered)-1)*fraction
        low=math.floor(index);high=math.ceil(index)
        return (ordered[low]+(ordered[high]-ordered[low])*(index-low))/1e6
    return dict(tick_cutoff=tick_cutoff,interval_count=len(intervals),discarded_nonconsecutive_intervals=discarded,
                p50_ms=percentile(0.5),p95_ms=percentile(0.95),p99_ms=percentile(0.99),max_ms=ordered[-1]/1e6,
                over_16_67_ms=sum(ns*60>1000000000 for ns in intervals),over_8_33_ms=sum(ns*120>1000000000 for ns in intervals),
                budget_60_fps_ms=1000/60,budget_120_fps_ms=1000/120,
                percentile_method='linear sorted rank (n-1)*p',logging_cost_included=True,
                scope='Consecutive completed-present intervals with initialized game tick>=150; includes cap waits and diagnostic logging.')


def validate_telemetry(rows, values):
    require(rows, 'Native display FPS/simulation telemetry is missing')
    width, height = profiles.physical_size(values)
    for row in rows:
        require(row['storage_width'] == width and row['storage_height'] == height
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
    require((width, height) == profiles.physical_size(values),
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
    log = (output / 'launch.log').read_text(errors='replace')
    state = parse_log(log)
    errors = list(state['telemetry_errors']) + state['host_metrics_errors']
    saved_defaults = {}
    native_resolution = None
    timing_only = plan.get('timing_only', False)
    unmeasured_native = plan['values'].get('native_fullscreen',False) and not plan['values'].get('native_size')
    measured_values = plan['values']
    try:
        saved_defaults = verify_prepared(output, plan, after_execution=True)
        native_resolution = profiles.checked_native_startup(log, plan['values'], require_expected=not unmeasured_native)
        if unmeasured_native:
            measured_values = dict(plan['values'], logical_width=native_resolution['logical_width'],
                expected_physical_width=native_resolution['storage_width'],
                expected_physical_height=native_resolution['storage_height'])
        validate_telemetry(state['telemetry'], measured_values)
    except (ValueError, OSError, KeyError) as error:
        errors.append(str(error))
    captures = sorted((output / 'captures').glob('frame*.bmp'),
                      key=lambda path: int(path.stem[5:]) if path.stem[5:].isdigit() else -1)
    capture, image = None, None
    try:
        if timing_only:
            require(not captures, 'Timing-only run unexpectedly produced a render capture')
        else:
            require(captures and captures[-1].stem[5:].isdigit(), 'Native render capture is missing')
            last = captures[-1]
            require(not last.is_symlink(), 'Capture must be stored in the isolated run')
            width, height, rgb = read_bmp(last, measured_values)
            capture = descriptor(last)
            inspection = output / 'inspection.png'
            write_png(inspection, width, height, rgb)
            image = dict(width=width, height=height, nonblack=True, capture_frame=int(last.stem[5:]),
                rgb_sha256=hashlib.sha256(rgb).hexdigest(), inspection_image=descriptor(inspection), visually_inspected=False)
    except (ValueError, OSError, struct.error) as error:
        errors.append(str(error))
    elapsed = execution['elapsed_seconds']
    execution_gate = (type(execution['returncode']) is int and execution['returncode'] == 0
            and execution['timed_out'] is False and 15 <= elapsed <= 600
            and type(state['actual_guest_returncode']) is int and state['actual_guest_returncode'] == 0
            and state['renderer_api_errors'] == []
            and not errors)
    diagnostic_gate = execution_gate and capture is not None and not timing_only
    timing_gate = execution_gate and timing_only and bool(state['host_metrics'])
    gate = diagnostic_gate and not unmeasured_native and plan['api_validation_requested'] is True and state['api_validation_enabled'] is True
    actual_config = descriptor(output / 'saves/config.toml')
    actual_display = tomllib.loads((output / 'saves/config.toml').read_text()).get('display', {})
    result = dict(schema_version=1, kind='metal_playtest_profile_runtime', bounded_runtime_gate=gate,
        complete=True, passed=gate, build_proof=plan['build']['proof'], map=plan['values']['map'],
        display={key: actual_display.get(key) for key in DISPLAY_KEYS},
        actual_host_returncode=execution['returncode'], actual_guest_returncode=state['actual_guest_returncode'],
        api_validation_enabled=state['api_validation_enabled'], api_validation_requested=plan['api_validation_requested'],
        diagnostic_execution_gate=diagnostic_gate, renderer_api_errors=state['renderer_api_errors'],
        timing_only=timing_only, timing_execution_gate=timing_gate,
        native_probe=unmeasured_native,
        execution=descriptor(output / 'execution.json'), test_config=actual_config, input_config=plan['initial_config'],
        saved_default_insertions=saved_defaults, render_capture=capture,
        launch_log=descriptor(output / 'launch.log'), launch_plan=descriptor(output / 'launch-plan.json'),
        profile=plan['profile'], producer=plan['producer'], frozen_producer=plan['frozen_producer'],
        metrics=state['telemetry'], host_metrics=state['host_metrics'], native_resolution=native_resolution,
        frame_timing=state['frame_timing'], frame_timing_summary=summarize_frame_timing(state['frame_timing']),
        observed_native_size=([native_resolution['drawable_width'],native_resolution['drawable_height']]
                              if native_resolution else None), native_size_expectation_bound=not unmeasured_native,
        guest_exit_records=state['guest_exit_records'], validation_failures=errors, image=image,
        awaiting_image_review=gate, world_weapon_hud_pixels_visually_inspected=False,
        simulation_source_modified=False, requested_simulation_hz=30,
        manual_input_audio_gate=False, achieved_render_fps_gate=False, performance_improvement_gate=False,
        original_xbox_fidelity_gate=False, full_game_gate=False,
        scope=('One timing-only native display-profile run with captures disabled; no ready promotion. ' if timing_only else
               'One bounded native display-profile run with API validation and complete nonblack physical capture. ')
              +
              'Telemetry is diagnostic; world/weapon/HUD image review, manual input/audio, achieved cap, '
              'performance improvement, original Xbox fidelity and full-game completion are unverified.')
    new_json(output / 'runtime.json', result)
    if gate:
        profiles.checked_runtime(output / 'runtime.json', plan['values'], plan['build'])
    return result


def run(output, profile, build_proof, duration=20, runner=None, api_validation=True, timing_only=False):
    plan = prepare(output, profile, build_proof, duration, api_validation, timing_only)
    output = Path(plan['cwd'])
    verify_prepared(output, plan)
    require(list((output / 'saves').iterdir()) == [output / 'saves/config.toml'], 'Runtime save state is not fresh')
    environment, overrides, removed = sanitized_environment(output, plan['build']['configuration_environment_names'],
        api_validation=api_validation, native_fullscreen=plan['values'].get('native_fullscreen', False),
        gpu_statistics=plan['gpu_statistics_requested'])
    require(overrides == plan['environment_overrides'], 'Runtime environment changed')
    runner = execute_process if runner is None else runner
    observation = runner(plan['command'], plan['cwd'], environment, output / 'launch.log', duration + 20)
    execution = dict(schema_version=1, kind='observed_native_metal_display_execution', **observation,
        command=plan['command'], cwd=plan['cwd'], environment_overrides=overrides,
        removed_environment_names=removed, api_validation_requested=api_validation,
        timing_only=timing_only, gpu_statistics_requested=plan['gpu_statistics_requested'],
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
    parser.add_argument('--timing-only', action='store_true',
                        help='Disable all captures and record timing/host diagnostics; cannot promote a ready profile')
    args = parser.parse_args()
    try:
        result = run(args.output, args.profile, args.build_proof, args.duration,
                     api_validation=args.api_validation == 'on', timing_only=args.timing_only)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(dict(runtime=descriptor(args.output / 'runtime.json'), passed=result['passed'],
        host_exit=result['actual_host_returncode'], guest_exit=result['actual_guest_returncode'],
        last_metrics=result['metrics'][-1] if result['metrics'] else None,
        validation_failures=result['validation_failures'], renderer_api_errors=result['renderer_api_errors'],
        timing_execution_gate=result['timing_execution_gate'], native_resolution=result['native_resolution'],
        host_metrics=result['host_metrics'],
        frame_timing_summary=result['frame_timing_summary'],
        inspection_image=result['image']['inspection_image'] if result['image'] else None), indent=2))
    return 0 if (result['passed'] or (args.timing_only and result['timing_execution_gate'])
                 or (result['native_probe'] and result['diagnostic_execution_gate'])) else 1


if __name__ == '__main__':
    sys.exit(main())
