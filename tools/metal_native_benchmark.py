#!/usr/bin/env python3
"""Measure one native fullscreen run with an old or current frozen host.

Both selections use the same NEW guest, measured native profile, scripted
bot:0 input and fresh isolated saves. Run selections sequentially, preferably
alternating A/B/B/A. The baseline proof is checked against its frozen snapshot;
it is never rewritten or required to match today's source tree. No captures or
Metal API validation run here, and no ready, fidelity or improvement gate can
be produced by these timing observations.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tomllib

try:
    from tools import metal_display_runtime as runtime
except ImportError:
    import metal_display_runtime as runtime

profiles = runtime.profiles
require, sha, descriptor, new_json = profiles.require, profiles.sha, profiles.descriptor, profiles.new_json

# These unchanged boundaries establish that the old host accepts the new
# guest's command/import contract. Only the host Metal transport is swapped.
COMPATIBILITY_PATHS = (
    'port/macos/include/halo_metal_abi.h', 'port/macos/metal_imports.list',
    'build/macos-metal/guest/gen/native_host_imports.list',
    'build/macos-metal/guest/gen/imports.s', 'build/macos-metal/host/host_import_table.c',
    'port/linux/src/metal_guest_transport.c', 'port/linux/src/metal_guest_transport.h',
    'port/macos/host/host.h', 'port/macos/host/host_loader.c', 'port/macos/host/host_sdl.c',
    'port/macos/host/metal_draw_encoder.h', 'port/macos/host/metal_draw_encoder.mm',
    'tools/macos_metal_imports.py',
)
SUBMISSIONS = re.compile(r'Native submissions frames (\d+)-(\d+): (\d+) batches, (\d+) commands, '
                         r'(\d+) bytes, (\d+) host-submit us, largest (\d+) bytes')
ORIGINAL_DRAWS = re.compile(r'Native frame (\d+): (\d+) original draws, (\d+) texture resources, (\d+) programs')
TICK_CUTOFF = 150
STARTUP_EXCLUSION_NS = 500_000_000


def relative_path(value):
    require(isinstance(value, str), 'Build binding path must be a string')
    path = Path(value)
    require(value and not path.is_absolute() and '..' not in path.parts, 'Unsafe build binding path')
    return path


def proof_file(root, record):
    require(isinstance(record, dict) and set(record) == {'path', 'sha256'}, 'Malformed frozen proof descriptor')
    path = Path(root) / relative_path(record['path'])
    profiles.checked_descriptor(dict(file=str(path.resolve()), sha256=record['sha256']))
    return path.resolve()


def frozen_build(path, root):
    """Verify historical proof bytes and observed build, without current drift checks."""
    path, root = Path(path).resolve(), Path(root).resolve()
    build = json.loads(path.read_text())
    require(build.get('schema_version') == 1 and build.get('kind') == 'native_batched_guest_host_build',
            'Observed native guest/host build proof required')
    require(build.get('passed') is True and type(build.get('actual_build_tool_exit')) is int
            and build['actual_build_tool_exit'] == 0 and build.get('no_angle_gl_linkage_or_imports') is True,
            'Successful observed no-GL native build required')
    snapshot_path = Path(build['source_snapshot'])
    snapshot = (snapshot_path if snapshot_path.is_absolute() else root / snapshot_path).resolve()
    require(snapshot.is_dir(), 'Frozen build snapshot is missing')
    by_path = {}
    sources, evidence = build.get('source_bindings'), build.get('evidence_bindings')
    require(isinstance(sources, list) and isinstance(evidence, list) and sources,
            'Frozen build bindings are missing')
    bindings = sources + evidence
    for item in bindings:
        require(isinstance(item, dict) and set(item) == {'path', 'sha256'}, 'Malformed frozen build binding')
        relative = relative_path(item['path'])
        require(str(relative) not in by_path, 'Duplicate frozen build binding')
        target = snapshot / relative
        require(not target.is_symlink() and target.resolve().is_relative_to(snapshot), 'Frozen binding escapes snapshot')
        profiles.checked_descriptor(dict(file=str(target.resolve()), sha256=item['sha256']))
        by_path[str(relative)] = item['sha256']
    required = {profiles.HOST, profiles.GUEST, 'port/macos/host/host_metal.mm', *COMPATIBILITY_PATHS}
    require(required <= by_path.keys(), 'Frozen host/guest compatibility bindings are incomplete')
    producer = build.get('producer')
    require(isinstance(producer, dict) and producer.get('path') in by_path
            and producer.get('sha256') == by_path[producer['path']], 'Frozen build producer binding is missing or stale')
    execution_path = proof_file(root, build['execution'])
    require(execution_path.read_bytes() == (path.parent / 'execution.json').read_bytes(),
            'Build execution snapshot differs from observed record')
    execution = json.loads(execution_path.read_text())
    require(type(execution.get('returncode')) is int and execution['returncode'] == 0
            and execution.get('timed_out', False) is False,
            'Build execution did not observe exit0 without timeout')
    command = execution.get('command')
    require(isinstance(command, list) and command and all(isinstance(word, str) for word in command)
            and '--renderer' in command and command[command.index('--renderer') + 1:command.index('--renderer') + 2] == ['metal']
            and '--build-only' in command, 'Observed native build command is missing')
    build_log = proof_file(root, execution['log'])
    require(sha(build_log) == build.get('build_log_sha256') == sha(path.parent / 'build.log'),
            'Frozen/observed build log identity differs')
    host, guest = snapshot / profiles.HOST, snapshot / profiles.GUEST
    require(stat.S_IMODE(host.stat().st_mode) == 0o755, 'Frozen host must retain mode0755')
    with host.open('rb') as stream:
        require(stream.read(8) == struct.pack('<II', 0xfeedfacf, 0x0100000c), 'ARM64 Mach-O host required')
    with guest.open('rb') as stream:
        header = stream.read(20)
    require(len(header) == 20 and header[:6] == b'\x7fELF\x02\x01'
            and struct.unpack_from('<H', header, 18)[0] == 183, 'Native AArch64 guest container required')
    return dict(proof=descriptor(path), snapshot=str(snapshot), bindings=bindings,
                host=descriptor(host), guest=descriptor(guest),
                execution=descriptor(execution_path), observed_build_log=descriptor(build_log),
                frozen_build_log=descriptor(path.parent / 'build.log'),
                producer=dict(file=str(snapshot / producer['path']), sha256=producer['sha256']),
                source_hashes=by_path)


def compatible_hosts(baseline, current):
    boundaries = []
    for path in COMPATIBILITY_PATHS:
        require(baseline['source_hashes'][path] == current['source_hashes'][path],
                'Old/new host source contract differs: ' + path)
        old, new = Path(baseline['snapshot']) / path, Path(current['snapshot']) / path
        require(old.read_bytes() == new.read_bytes(), 'Old/new host source bytes differ: ' + path)
        boundaries.append(dict(path=path, baseline=descriptor(old), current=descriptor(new), identical_bytes=True))
    require(baseline['host']['sha256'] != current['host']['sha256'], 'A/B requires distinct frozen host binaries')
    return dict(identical_boundaries=boundaries, abi_imports_draw_encoder_source_compatible=True,
                scope='Frozen ABI, imports, guest transport, loader, SDL and original draw encoder source bytes agree; execution still requires runtime observation.')


def prepare(output, profile, build_proof, baseline_build_proof, host, duration=30):
    require(host in ('baseline', 'current'), 'Host selection must be baseline or current')
    runtime.validate_duration(duration)
    manifest = profiles.verify_profile(profile)
    values = manifest['profile']
    require(values.get('native_fullscreen') is True and values.get('native_size'),
            'Benchmark requires a measured native fullscreen profile with --native-size')
    profiles.physical_size(values)
    root = manifest['repository']
    current = frozen_build(build_proof, root)
    baseline = frozen_build(baseline_build_proof, root)
    compatibility = compatible_hosts(baseline, current)
    runtime_plan = runtime.prepare(output, profile, build_proof, duration, api_validation=False, timing_only=True)
    require(runtime_plan['build']['host'] == current['host'] and runtime_plan['build']['guest'] == current['guest'],
            'Current/frozen runtime build identity differs')
    output = Path(runtime_plan['cwd'])
    selected = baseline if host == 'baseline' else current
    frozen = output / 'benchmark-producer.py'
    shutil.copy2(__file__, frozen)
    require(sha(__file__) == sha(frozen), 'Benchmark producer changed during freeze')
    plan = dict(schema_version=1, kind='native_metal_host_benchmark_plan', host_selection=host,
                command=[selected['host']['file'], current['guest']['file']], cwd=str(output),
                selected_host=selected['host'], shared_new_guest=current['guest'],
                baseline_build=baseline, current_build=current, compatibility=compatibility,
                runtime_plan=runtime_plan, runtime_preparation_plan=descriptor(output / 'launch-plan.json'),
                duration_seconds=duration, producer=descriptor(__file__), frozen_producer=descriptor(frozen),
                measurement=dict(tick_cutoff=TICK_CUTOFF, exclude_first_timing_ns=STARTUP_EXCLUSION_NS,
                                 clock='guest CLOCK_MONOTONIC after completed present and cap wait',
                                 logging_cost_included=True),
                process_launched=False,
                scope='The runtime preparation plan supplies isolated config/assets only; this benchmark plan binds the actual selected host and shared new guest command.')
    new_json(output / 'benchmark-plan.json', plan)
    return plan


def verify_prepared(output, plan, after_execution=False):
    saved_defaults = runtime.verify_prepared(output, plan['runtime_plan'], after_execution)
    for key in ('producer', 'frozen_producer', 'runtime_preparation_plan', 'selected_host', 'shared_new_guest'):
        profiles.checked_descriptor(plan[key])
    root = profiles.verify_profile(plan['runtime_plan']['profile_directory'])['repository']
    for key in ('current_build', 'baseline_build'):
        require(frozen_build(plan[key]['proof']['file'], root) == plan[key], 'Frozen benchmark build changed')
    require(compatible_hosts(plan['baseline_build'], plan['current_build']) == plan['compatibility'],
            'Benchmark host compatibility changed')
    selected = plan['baseline_build'] if plan['host_selection'] == 'baseline' else plan['current_build']
    require(plan['command'] == [selected['host']['file'], plan['current_build']['guest']['file']],
            'Benchmark changed the selected host/shared new guest command')
    require(plan['selected_host'] == selected['host'] and plan['shared_new_guest'] == plan['current_build']['guest'],
            'Selected benchmark binary descriptors differ')
    return saved_defaults


def steady_rows(rows):
    if not rows:
        return []
    first_ns = rows[0]['monotonic_ns']
    return [row for row in rows if row['monotonic_ns'] >= first_ns + STARTUP_EXCLUSION_NS
            and row['initialized'] and row['tick'] >= TICK_CUTOFF]


def workload_records(log):
    submissions, draws, telemetry_times, host_times, errors = [], [], [], [], []
    last_timing = None
    for number, line in enumerate(log.splitlines(), 1):
        match = runtime.FRAME_TIMING.search(line)
        if match:
            frame, ns, tick, initialized = map(int, match.groups())
            last_timing = dict(frame=frame, monotonic_ns=ns, tick=tick, initialized=bool(initialized))
        if 'Native submissions frames ' in line:
            match = SUBMISSIONS.search(line)
            if not match:
                errors.append('Malformed native submission statistics: ' + line)
            else:
                keys = ('first_frame', 'last_frame', 'batches', 'commands', 'bytes', 'host_submit_us', 'largest_batch_bytes')
                row = dict(zip(keys, map(int, match.groups())), log_line=number)
                if row['first_frame'] < 1 or row['last_frame'] - row['first_frame'] != 59:
                    errors.append('Native submission statistics must cover exactly60 positive frames')
                else:
                    submissions.append(row)
        if ' original draws, ' in line:
            match = ORIGINAL_DRAWS.search(line)
            if not match:
                errors.append('Malformed native original-draw statistics: ' + line)
            else:
                keys = ('frame', 'cumulative_original_draws', 'texture_resources', 'programs')
                draws.append(dict(zip(keys, map(int, match.groups())), log_line=number))
        if runtime.TELEMETRY.search(line):
            telemetry_times.append(last_timing)
        if runtime.HOST_METRICS.search(line):
            host_times.append(last_timing)
    return dict(submissions=submissions, original_draws=draws, telemetry_timings=telemetry_times,
                host_metric_preceding_timings=host_times, errors=errors)


def steady_workload(records, timings):
    eligible = {row['frame']: row for row in steady_rows(timings)}
    draws = {row['frame']: row for row in records['original_draws']}
    blocks = []
    for row in records['submissions']:
        first, last = row['first_frame'], row['last_frame']
        if not all(frame in eligible for frame in range(first, last + 1)):
            continue
        item = dict(row, frames=last - first + 1, first_tick=eligible[first]['tick'], last_tick=eligible[last]['tick'])
        previous = draws.get(first - 1)
        current = draws.get(last)
        item['original_draws'] = (current['cumulative_original_draws'] - previous['cumulative_original_draws']
                                  if previous and current and current['cumulative_original_draws'] >= previous['cumulative_original_draws'] else None)
        blocks.append(item)
    if not blocks:
        return dict(blocks=[], summary=None)
    totals = {key: sum(row[key] for row in blocks) for key in ('frames', 'batches', 'commands', 'bytes', 'host_submit_us')}
    totals['original_draws'] = sum(row['original_draws'] for row in blocks) if all(row['original_draws'] is not None for row in blocks) else None
    totals['largest_batch_bytes'] = max(row['largest_batch_bytes'] for row in blocks)
    for key in ('batches', 'commands', 'bytes', 'host_submit_us', 'original_draws'):
        totals[key + '_per_frame'] = totals[key] / totals['frames'] if totals[key] is not None else None
    totals['scope'] = 'Complete original 60-frame submission blocks whose every present sample passes the steady timing cutoff; original draws are differences of cumulative guest counts.'
    return dict(blocks=blocks, summary=totals)


def presentation_summary(rows):
    steady = steady_rows(rows)
    summary = runtime.summarize_frame_timing(steady, TICK_CUTOFF)
    if summary is None:
        return None
    elapsed_ns, ticks = 0, 0
    for previous, current in zip(steady, steady[1:]):
        if (current['frame'] == previous['frame'] + 1 and current['monotonic_ns'] > previous['monotonic_ns']
                and current['tick'] >= previous['tick']):
            elapsed_ns += current['monotonic_ns'] - previous['monotonic_ns']
            ticks += current['tick'] - previous['tick']
    summary.update(exclude_first_timing_ns=STARTUP_EXCLUSION_NS,
                   elapsed_seconds=elapsed_ns / 1e9, render_fps=summary['interval_count'] * 1e9 / elapsed_ns,
                   observed_simulation_hz=ticks * 1e9 / elapsed_ns, simulation_ticks=ticks,
                   requested_simulation_hz=30, first_tick=steady[0]['tick'], last_tick=steady[-1]['tick'])
    return summary


def collect(output, plan, execution):
    output = Path(output)
    log = (output / 'launch.log').read_text(errors='replace')
    state, saved_defaults, native_resolution = runtime.parse_log(log), {}, None
    records = workload_records(log)
    errors = state['telemetry_errors'] + state['host_metrics_errors'] + records['errors']
    try:
        saved_defaults = verify_prepared(output, plan, after_execution=True)
        native_resolution = profiles.checked_native_startup(log, plan['runtime_plan']['values'])
        runtime.validate_telemetry(state['telemetry'], plan['runtime_plan']['values'])
        require(not state['api_validation_enabled'], 'Timing benchmark unexpectedly enabled Metal API validation')
        require(not list((output / 'captures').iterdir()), 'Timing benchmark unexpectedly produced a capture')
    except (ValueError, OSError, KeyError) as error:
        errors.append(str(error))
    summary = presentation_summary(state['frame_timing'])
    workload = steady_workload(records, state['frame_timing'])
    if summary is None:
        errors.append('Steady completed-present intervals are missing')
    if workload['summary'] is None or workload['summary']['original_draws'] is None:
        errors.append('Steady original submission/draw workload is missing')
    steady_telemetry = [row for row, timing in zip(state['telemetry'], records['telemetry_timings'])
                        if timing is not None and timing in steady_rows(state['frame_timing'])
                        and row['first_tick'] >= TICK_CUTOFF and row['last_tick'] > row['first_tick']]
    elapsed = execution['elapsed_seconds']
    valid = (type(execution['returncode']) is int and execution['returncode'] == 0
             and execution['timed_out'] is False and type(elapsed) in (int, float) and math.isfinite(elapsed)
             and 15 <= elapsed <= 600 and state['actual_guest_returncode'] == 0
             and state['renderer_api_errors'] == [] and not errors)
    result = dict(schema_version=1, kind='native_metal_host_benchmark', complete=True, passed=False,
                  measurement_valid=valid, host_selection=plan['host_selection'],
                  selected_host=plan['selected_host'], shared_new_guest=plan['shared_new_guest'],
                  actual_command=execution['command'], new_build_proof=plan['current_build']['proof'],
                  baseline_build_proof=plan['baseline_build']['proof'], compatibility=plan['compatibility'],
                  benchmark_plan=descriptor(output / 'benchmark-plan.json'),
                  runtime_preparation_plan=plan['runtime_preparation_plan'], profile=plan['runtime_plan']['profile'],
                  producer=plan['producer'], frozen_producer=plan['frozen_producer'],
                  execution=descriptor(output / 'execution.json'), launch_log=descriptor(output / 'launch.log'),
                  input_config=plan['runtime_plan']['initial_config'], test_config=descriptor(output / 'saves/config.toml'),
                  saved_default_insertions=saved_defaults, display=tomllib.loads((output / 'saves/config.toml').read_text())['display'],
                  native_resolution=native_resolution, observed_native_size=([native_resolution['drawable_width'], native_resolution['drawable_height']] if native_resolution else None),
                  actual_host_returncode=execution['returncode'], actual_guest_returncode=state['actual_guest_returncode'],
                  guest_exit_records=state['guest_exit_records'], api_validation_enabled=state['api_validation_enabled'],
                  renderer_api_errors=state['renderer_api_errors'], validation_failures=errors,
                  frame_timing=state['frame_timing'], steady_frame_timing_summary=summary,
                  fps_simulation_telemetry=state['telemetry'], steady_fps_simulation_telemetry=steady_telemetry,
                  original_submission_stats=records['submissions'], original_draw_stats=records['original_draws'],
                  steady_workload=workload, host_metrics=state['host_metrics'],
                  host_metrics_available=bool(state['host_metrics']), host_metric_preceding_timings=records['host_metric_preceding_timings'],
                  host_metrics_scope='Whole bounded run, including startup; the old host may not emit this optional instrumentation.',
                  requested_simulation_hz=30, test_input='bot:0', timing_only=True, captures_enabled=False,
                  logging_cost_included=True, experiment_ready=False, bounded_runtime_gate=False,
                  original_xbox_fidelity_gate=False, performance_improvement_gate=False, achieved_render_fps_gate=False,
                  manual_input_audio_gate=False, full_game_gate=False,
                  scope='One controlled host-swap timing observation. Same new guest and measured native profile; original workload counts permit comparison. No capture/API validation, ready promotion, fidelity or performance-improvement claim.')
    new_json(output / 'benchmark.json', result)
    return result


def run(output, profile, build_proof, baseline_build_proof, host, duration=30, runner=None):
    plan = prepare(output, profile, build_proof, baseline_build_proof, host, duration)
    output = Path(plan['cwd'])
    verify_prepared(output, plan)
    require(list((output / 'saves').iterdir()) == [output / 'saves/config.toml'], 'Benchmark saves must be fresh')
    base_plan = plan['runtime_plan']
    environment, overrides, removed = runtime.sanitized_environment(output, base_plan['build']['configuration_environment_names'],
        api_validation=False, native_fullscreen=True, gpu_statistics=True)
    require(overrides == base_plan['environment_overrides'], 'Benchmark environment changed')
    observation = (runtime.execute_process if runner is None else runner)(plan['command'], plan['cwd'], environment,
                                                                        output / 'launch.log', duration + 20)
    execution = dict(schema_version=1, kind='observed_native_metal_host_benchmark_execution', **observation,
                     command=plan['command'], cwd=plan['cwd'], environment_overrides=overrides,
                     removed_environment_names=removed, api_validation_requested=False, timing_only=True,
                     benchmark_plan=descriptor(output / 'benchmark-plan.json'),
                     input_config=base_plan['initial_config'], test_config=descriptor(output / 'saves/config.toml'),
                     producer=plan['producer'], fresh_save_state_verified_before_launch=True,
                     log=descriptor(output / 'launch.log'))
    new_json(output / 'execution.json', execution)
    return collect(output, plan, execution)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--build-proof', type=Path, required=True, help='New native fullscreen proof; its guest is shared by both selections')
    parser.add_argument('--baseline-build-proof', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--host', choices=('baseline', 'current'), required=True)
    args = parser.parse_args()
    try:
        result = run(args.output, args.profile, args.build_proof, args.baseline_build_proof, args.host, args.duration)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(dict(result=descriptor(args.output / 'benchmark.json'), host_selection=result['host_selection'],
                          measurement_valid=result['measurement_valid'], steady_timing=result['steady_frame_timing_summary'],
                          steady_workload=result['steady_workload']['summary'], validation_failures=result['validation_failures']), indent=2))
    return 0 if result['measurement_valid'] else 1


if __name__ == '__main__':
    sys.exit(main())
