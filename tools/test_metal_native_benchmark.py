"""CPU-only host-swap provenance and diagnostic timing guards; no game starts."""
import copy
import json
from pathlib import Path
import shutil
import tomllib
import unittest
from unittest import mock

try:
    from tools import metal_native_benchmark as benchmark
    from tools import test_metal_playtest_profiles as fixture_module
    from tools import test_metal_display_runtime as runtime_fixture
except ImportError:
    import metal_native_benchmark as benchmark
    import test_metal_playtest_profiles as fixture_module
    import test_metal_display_runtime as runtime_fixture

profiles = benchmark.profiles


class NativeBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ProfileTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.draft(height=0, native_fullscreen=True, native_size=(3600, 2338))
        self.profile = self.fixture.folder
        minimal_proof = self.fixture.build(native_resolution=True)
        self.repo = self.fixture.repo
        current = json.loads(minimal_proof.read_text())
        current['kind'] = 'native_batched_guest_host_build'
        snapshot = self.repo / current['source_snapshot']
        for name in (*benchmark.COMPATIBILITY_PATHS, 'port/macos/host/host_metal.mm', 'tools/metal_live_build_proof.py'):
            if name in {item['path'] for item in current['source_bindings']}:
                continue
            source, target = self.repo / name, snapshot / name
            source.parent.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('CPU source fixture: ' + name)
            shutil.copy2(source, target)
            current['source_bindings'].append(dict(path=name, sha256=profiles.sha(source)))
        current['producer'] = next(item for item in current['source_bindings'] if item['path'] == 'tools/metal_live_build_proof.py')
        baseline = copy.deepcopy(current)
        baseline['source_snapshot'] = 'baseline-snapshot'
        baseline['native_resolution'] = False
        old_snapshot = self.repo / baseline['source_snapshot']
        shutil.copytree(snapshot, old_snapshot)
        # A genuine host swap keeps the NEW guest even though the old proof
        # independently describes a different historical guest.
        old_host = old_snapshot / profiles.HOST
        old_host.write_bytes(old_host.read_bytes() + b' historical CPU host')
        old_host.chmod(0o755)
        old_guest = old_snapshot / profiles.GUEST
        old_guest.write_bytes(old_guest.read_bytes() + b' old guest must not run')
        old_transport = old_snapshot / 'port/macos/host/host_metal.mm'
        old_transport.write_text('CPU historical Metal host transport')
        for item in baseline['source_bindings']:
            item['sha256'] = profiles.sha(old_snapshot / item['path'])
        baseline['producer'] = next(item for item in baseline['source_bindings'] if item['path'] == 'tools/metal_live_build_proof.py')
        self.new_proof = self.observed_proof(current, 'current-proof')
        self.old_proof = self.observed_proof(baseline, 'baseline-proof')
        self.output = self.fixture.base / 'benchmark output with spaces'
        self.values = profiles.verify_profile(self.profile)['profile']
        self.calls = []

    def observed_proof(self, proof, name):
        folder, observed = self.repo / name, self.repo / (name + '-observer')
        folder.mkdir()
        observed.mkdir()
        log = observed / 'build.log'
        log.write_text('CPU observer fixture: no actual binary build was executed\n')
        execution = dict(command=['python3', 'tools/macos_build.py', '--renderer', 'metal', '--build-only'],
                         returncode=0, timed_out=False,
                         log=dict(path=str(log.relative_to(self.repo)), sha256=profiles.sha(log)))
        observer = observed / 'execution.json'
        observer.write_text(json.dumps(execution))
        shutil.copy2(observer, folder / 'execution.json')
        shutil.copy2(log, folder / 'build.log')
        proof['execution'] = dict(path=str(observer.relative_to(self.repo)), sha256=profiles.sha(observer))
        proof['build_log_sha256'] = profiles.sha(log)
        path = folder / 'result.json'
        path.write_text(json.dumps(proof))
        return path

    def fake_runner(self, command, cwd, environment, log_path, timeout):
        self.calls.append(dict(command=command, cwd=cwd, environment=environment, timeout=timeout))
        text = ('Metal drawable 3600x2338 (borderless fullscreen)\n'
                'Native resolution: 3600x2338 storage, 738x480 logical, 3600x2338 drawable, startup aspect native\n')
        for frame in range(1, 181):
            ns, tick = 1_000_000_000 + (frame - 1) * 16_666_667, 150 + (frame - 1) // 2
            if frame % 60 == 0:
                text += f'Native frame {frame}: {frame * 100} original draws, 20 texture resources, 10 programs\n'
                text += (f'Native submissions frames {frame - 59}-{frame}: 600 batches, 700 commands, '
                         '1000000 bytes, 20000 host-submit us, largest 5000 bytes\n')
                if command[0] == str((self.repo / 'frozen-build' / profiles.HOST).resolve()):
                    text += runtime_fixture.HOST_LINE
            text += f'Native timing: frame {frame}, monotonic {ns} ns, tick {tick}, initialized 1\n'
            if frame % 60 == 0:
                text += runtime_fixture.log_line(self.values, first=tick - 30, last=tick)
        text += 'Game exited (0)\n'
        Path(log_path).write_text(text)
        return dict(returncode=0, elapsed_seconds=30.5, timed_out=False)

    def run_fixture(self, host='baseline', runner=None, output=None):
        with mock.patch.object(benchmark.runtime.subprocess, 'Popen', side_effect=AssertionError('CPU test must never launch a game')):
            return benchmark.run(output or self.output, self.profile, self.new_proof, self.old_proof,
                                 host, runner=runner or self.fake_runner)

    def test_baseline_uses_exact_old_host_same_new_guest_and_preserves_profiles(self):
        before = profiles.descriptor(self.profile / 'saves/config.toml')
        with mock.patch.dict(benchmark.runtime.os.environ, {'MTL_DEBUG_LAYER': '1', 'HALO_GPU_STATS': '0',
                                                           'HALO_NO_AUDIO': '1', 'HALO_WINDOWED': '1'}):
            result = self.run_fixture()
        self.assertTrue(result['measurement_valid'])
        self.assertEqual(result['host_selection'], 'baseline')
        expected = [str((self.repo / 'baseline-snapshot' / profiles.HOST).resolve()),
                    str((self.repo / 'frozen-build' / profiles.GUEST).resolve())]
        self.assertEqual(result['actual_command'], expected)
        self.assertEqual(self.calls[0]['command'], expected)
        self.assertEqual(before, profiles.descriptor(self.profile / 'saves/config.toml'))
        self.assertNotIn('MTL_DEBUG_LAYER', self.calls[0]['environment'])
        self.assertNotIn('HALO_NO_AUDIO', self.calls[0]['environment'])
        self.assertEqual(self.calls[0]['environment']['HALO_WINDOWED'], '0')
        self.assertEqual(self.calls[0]['environment']['HALO_GPU_STATS'], '1')
        self.assertEqual(self.calls[0]['timeout'], 50)
        self.assertFalse(result['host_metrics_available'])
        self.assertEqual(result['observed_native_size'], [3600, 2338])
        self.assertEqual(result['native_resolution']['logical_width'], 738)
        config = tomllib.loads((self.output / 'initial-config.toml').read_text())
        self.assertTrue(config['display']['fullscreen'])
        self.assertEqual(config['debug']['test_input'], 'bot:0')
        self.assertEqual(config['debug']['screenshot_every'], 0)
        self.assertEqual(config['debug']['screenshot_directory'], '')
        self.assertFalse(list((self.output / 'captures').iterdir()))
        self.assertAlmostEqual(result['steady_frame_timing_summary']['render_fps'], 60, places=4)
        self.assertAlmostEqual(result['steady_frame_timing_summary']['observed_simulation_hz'],
                               74 * 1e9 / (149 * 16_666_667), places=4)
        self.assertEqual(result['steady_workload']['summary']['frames'], 120)
        self.assertEqual(result['steady_workload']['summary']['original_draws'], 12000)
        self.assertEqual(result['steady_workload']['summary']['original_draws_per_frame'], 100)
        for key in ('passed', 'experiment_ready', 'bounded_runtime_gate', 'original_xbox_fidelity_gate',
                    'performance_improvement_gate', 'achieved_render_fps_gate', 'manual_input_audio_gate', 'full_game_gate'):
            self.assertFalse(result[key])
        with self.assertRaisesRegex(ValueError, 'Explicit profile runtime evidence'):
            profiles.checked_runtime(self.output / 'benchmark.json', self.values,
                                     profiles.checked_build(self.new_proof, self.repo, True))

    def test_current_and_baseline_have_same_initial_config_guest_and_workload(self):
        old = self.run_fixture()
        current_output = self.fixture.base / 'current benchmark'
        new = self.run_fixture(host='current', output=current_output)
        self.assertTrue(new['measurement_valid'])
        self.assertTrue(new['host_metrics_available'])
        self.assertEqual(len(new['host_metrics']), 3)
        self.assertEqual(old['input_config']['sha256'], new['input_config']['sha256'])
        self.assertEqual(old['shared_new_guest'], new['shared_new_guest'])
        self.assertEqual(old['steady_workload']['summary'], new['steady_workload']['summary'])
        self.assertNotEqual(old['selected_host'], new['selected_host'])

    def test_historical_tree_drift_is_allowed_but_frozen_drift_fails(self):
        old = benchmark.frozen_build(self.old_proof, self.repo)
        self.assertNotEqual(profiles.sha(self.repo / 'port/macos/host/host_metal.mm'),
                            old['source_hashes']['port/macos/host/host_metal.mm'])
        frozen = Path(old['snapshot']) / 'port/macos/host/host_metal.mm'
        frozen.write_text('corrupted old snapshot')
        with self.assertRaisesRegex(ValueError, 'Stale file'):
            self.run_fixture()
        self.assertFalse(self.calls)

    def test_changed_abi_or_draw_encoder_rejects_even_with_updated_old_hash(self):
        for name in ('port/macos/include/halo_metal_abi.h', 'port/macos/host/metal_draw_encoder.mm'):
            proof = json.loads(self.old_proof.read_text())
            path = self.repo / 'baseline-snapshot' / name
            original = path.read_bytes()
            path.write_bytes(original + b' contract mismatch')
            item = next(row for row in proof['source_bindings'] if row['path'] == name)
            original_hash = item['sha256']
            item['sha256'] = profiles.sha(path)
            self.old_proof.write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, 'source contract differs'):
                self.run_fixture()
            path.write_bytes(original)
            item['sha256'] = original_hash
            self.old_proof.write_text(json.dumps(proof))
        self.assertFalse(self.calls)

    def test_observed_build_record_and_log_must_remain_bound(self):
        proof = json.loads(self.old_proof.read_text())
        log = self.repo / 'baseline-proof-observer/build.log'
        log.write_text('changed observed build log')
        with self.assertRaisesRegex(ValueError, 'Stale file'):
            self.run_fixture()
        self.assertFalse(self.calls)
        self.assertFalse(self.output.exists())
        self.assertTrue(proof['passed'])

    def test_measured_native_profile_required_and_fresh_outputs_preserved(self):
        self.run_fixture()
        original = (self.output / 'benchmark.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Fresh output'):
            self.run_fixture()
        self.assertEqual((self.output / 'benchmark.json').read_bytes(), original)
        self.fixture.folder = self.fixture.base / 'unmeasured profile'
        self.fixture.draft(height=0, native_fullscreen=True)
        self.profile = self.fixture.folder
        with self.assertRaisesRegex(ValueError, 'measured native fullscreen'):
            self.run_fixture(output=self.fixture.base / 'unmeasured run')

    def test_actual_wrong_drawable_fault_api_validation_and_timeout_cannot_validate(self):
        mutations = (
            lambda text: text.replace('3600x2338 drawable', '3599x2338 drawable'),
            lambda text: text + 'Validation Error: bad vertex-buffer offset\n',
            lambda text: text + 'Metal API Validation Enabled\n',
        )
        for index, mutate in enumerate(mutations):
            def changed(command, cwd, environment, log, timeout):
                observation = self.fake_runner(command, cwd, environment, log, timeout)
                Path(log).write_text(mutate(Path(log).read_text()))
                return observation
            result = self.run_fixture(runner=changed, output=self.fixture.base / f'failure{index}')
            self.assertFalse(result['measurement_valid'])
            self.assertFalse(result['bounded_runtime_gate'])
        def timeout(*args):
            return dict(self.fake_runner(*args), returncode=-15, timed_out=True)
        self.assertFalse(self.run_fixture(runner=timeout, output=self.fixture.base / 'timeout')['measurement_valid'])

    def test_steady_cutoff_excludes_500ms_and_loading_and_skips_missing_frames(self):
        rows = [dict(frame=frame, monotonic_ns=1_000_000_000 + frame * 100_000_000,
                     tick=149 if frame < 4 else 150 + frame, initialized=frame > 0) for frame in range(10)]
        self.assertEqual([row['frame'] for row in benchmark.steady_rows(rows)], [5, 6, 7, 8, 9])
        summary = benchmark.presentation_summary(rows)
        self.assertEqual(summary['interval_count'], 4)
        self.assertEqual(summary['exclude_first_timing_ns'], 500_000_000)
        self.assertTrue(summary['logging_cost_included'])
        del rows[7]
        summary = benchmark.presentation_summary(rows)
        self.assertEqual(summary['interval_count'], 2)
        self.assertEqual(summary['discarded_nonconsecutive_intervals'], 1)

    def test_missing_workload_and_malformed_huge_frame_range_fail_without_expansion(self):
        def missing(*args):
            observation = self.fake_runner(*args)
            path = Path(args[3])
            path.write_text('\n'.join(line for line in path.read_text().splitlines() if 'Native submissions' not in line))
            return observation
        result = self.run_fixture(runner=missing)
        self.assertFalse(result['measurement_valid'])
        self.assertIn('Steady original submission/draw workload is missing', result['validation_failures'])
        parsed = benchmark.workload_records('Native submissions frames 1-4294967295: 1 batches, 2 commands, 3 bytes, 4 host-submit us, largest 5 bytes')
        self.assertTrue(parsed['errors'])
        self.assertEqual(parsed['submissions'], [])


if __name__ == '__main__':
    unittest.main()
