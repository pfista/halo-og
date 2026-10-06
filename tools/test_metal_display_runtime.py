"""CPU-only collector checks; process observations and assets are fixtures."""
import json
from pathlib import Path
import struct
import tomllib
import unittest
from unittest import mock
import zlib

try:
    from tools import metal_display_runtime as runtime
    from tools import test_metal_playtest_profiles as profile_fixture
except ImportError:
    import metal_display_runtime as runtime
    import test_metal_playtest_profiles as profile_fixture


def bmp(path, width, height, rgb=(12, 34, 56), alpha=255, positive_height=False):
    size = width * height * 4
    header = bytearray(54)
    header[:2] = b'BM'
    struct.pack_into('<I', header, 2, 54 + size)
    struct.pack_into('<I', header, 10, 54)
    struct.pack_into('<IiiHHII', header, 14, 40, width, height if positive_height else -height, 1, 32, 0, size)
    path.write_bytes(header + bytes((rgb[2], rgb[1], rgb[0], alpha)) * (width * height))


def log_line(values, fps=60.0, hz=30.0, first=30, last=60):
    width,height=runtime.profiles.physical_size(values)
    return (f'Native display: {fps:.3f} FPS, {hz:.3f} simulation Hz, '
            f'{width}x{height} storage, '
            f'{values["logical_width"]}x480 logical, cap {values["frame_limit"]}, interpolation {int(values["interpolation"])}, '
            f'ticks {first}-{last}\n'
            f'Native anti-aliasing: requested {values["anti_aliasing"]}, applied {max(0,last) if values["anti_aliasing"] == "fxaa" else 0}, stage pre-HUD\n')


HOST_LINE = ('Native Metal host metrics: 60 frames, 900 submits, 5000 draws, 1000000 bytes; '
             'packet-copy 100 us, prepare 200 us, encode 300 us, drawable-wait 400 us, commit 500 us, '
             'completion-wait 600 us, gpu 700 us/900 samples; packet-buffers 1, sampler-hits 4900, '
             'sampler-misses 100, sampler-allocations 100, sampler-cache 100, upload-buffers 200, visibility-buffers 300\n')


class DisplayRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing complete profile/build fixture, including its
        # source/object/link/snapshot checks. It is never an executable game.
        self.fixture = profile_fixture.ProfileTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.profile = self.fixture.folder
        self.output = self.fixture.base / 'separate runtime with spaces'
        self.fixture.draft(cap=60, height=1080)
        self.proof = self.fixture.build()
        self.values = runtime.profiles.verify_profile(self.profile)['profile']
        self.calls = []

    def fake_runner(self, command, cwd, environment, log_path, timeout):
        self.calls.append(dict(command=command, cwd=cwd, environment=environment, timeout=timeout))
        width,height=runtime.profiles.physical_size(self.values)
        text = 'Metal API Validation Enabled\n'
        if self.values.get('native_fullscreen',False):
            text += (f'Metal drawable {width}x{height} (borderless fullscreen)\n'
                     f'Native resolution: {width}x{height} storage, {self.values["logical_width"]}x480 logical, '
                     f'{width}x{height} drawable, startup aspect native\n')
        text += log_line(self.values, hz=0, first=0, last=0)
        text += log_line(self.values) + log_line(self.values, first=60, last=90) + 'Game exited (0)\n'
        text += HOST_LINE
        text += ('Native timing: frame 301, monotonic 1000000000 ns, tick 150, initialized 1\n'
                 'Native timing: frame 302, monotonic 1016000000 ns, tick 150, initialized 1\n'
                 'Native timing: frame 303, monotonic 1033000000 ns, tick 151, initialized 1\n')
        Path(log_path).write_text(text)
        configuration=tomllib.loads((Path(cwd)/'saves/config.toml').read_text())
        if configuration['debug']['screenshot_every']:
            bmp(Path(cwd) / 'captures/frame00300.bmp', width,height)
        return dict(returncode=0, elapsed_seconds=20.5, timed_out=False)

    def run_fixture(self, runner=None, **options):
        with mock.patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('CPU test must never launch')):
            return runtime.run(self.output, self.profile, self.proof, runner=runner or self.fake_runner, **options)

    def native_fixture(self):
        self.fixture.folder=self.fixture.base/'native full resolution profile'
        self.profile=self.fixture.folder
        self.fixture.draft(cap=60,height=0,native_fullscreen=True,native_size=(3600,2338))
        self.proof=self.fixture.build(native_resolution=True)
        self.values=runtime.profiles.verify_profile(self.profile)['profile']

    def fxaa_fixture(self):
        self.fixture.folder = self.fixture.base/'fxaa human profile'
        self.profile = self.fixture.folder
        self.fixture.draft(cap=60,height=1080,anti_aliasing='fxaa')
        self.values = runtime.profiles.verify_profile(self.profile)['profile']

    def test_fxaa_runtime_keeps_identity_requires_actual_passes_and_binds_post_hud_capture(self):
        self.fxaa_fixture()
        result = self.run_fixture()
        self.assertTrue(result['bounded_runtime_gate'])
        self.assertEqual(result['display']['anti_aliasing'],'fxaa')
        self.assertEqual(result['anti_aliasing'],dict(requested='fxaa',applied=90,stage='pre-HUD',records=3))
        self.assertEqual(result['capture_stage'],'post-world-AA/post-HUD')
        self.assertFalse(result['original_xbox_fidelity_gate'])
        saved = tomllib.loads(Path(result['test_config']['file']).read_text())
        self.assertEqual(saved['display']['anti_aliasing'],'fxaa')
        self.assertFalse(saved['display']['high_res_hud'])
        ready = runtime.profiles.promote(self.profile,self.proof,self.output/'runtime.json')
        self.assertTrue(ready['experiment_ready'])

    def test_missing_wrong_or_zero_applied_aa_execution_cannot_pass(self):
        self.fxaa_fixture()
        def runner(*args):
            observation = self.fake_runner(*args)
            path = Path(args[3])
            path.write_text(path.read_text().replace('applied 60','applied 0').replace('applied 90','applied 0'))
            return observation
        result = self.run_fixture(runner)
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertTrue(any('execution count' in error for error in result['validation_failures']))
        original = log_line(self.values)
        for log in ('\n'.join(line for line in original.splitlines() if 'Native anti-aliasing:' not in line),
                    original.replace('requested fxaa','requested off'),original.replace('stage pre-HUD','stage post-HUD')):
            with self.subTest(log=log), self.assertRaises(ValueError):
                runtime.profiles.checked_anti_aliasing(log,self.values)

    def test_saved_aa_change_cannot_relabel_the_runtime_input(self):
        self.fxaa_fixture()
        def runner(*args):
            observation = self.fake_runner(*args)
            path = Path(args[1])/'saves/config.toml'
            path.write_text(runtime.profiles.set_key(path.read_text(),'display','anti_aliasing','"off"'))
            return observation
        result = self.run_fixture(runner)
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertEqual(result['display']['anti_aliasing'],'off')
        self.assertEqual(tomllib.loads(Path(result['input_config']['file']).read_text())['display']['anti_aliasing'],'fxaa')
        self.assertTrue(any('anti_aliasing' in error for error in result['validation_failures']))

    def test_config_preserves_every_display_key_across_caps_heights_and_vsync(self):
        template = self.fixture.template.read_text()
        for cap in runtime.profiles.CAPS:
            for height in runtime.profiles.HEIGHTS:
                for vsync in (False, True):
                    values = runtime.profiles.profile_values('bloodgulch', cap, height, vsync)
                    human = runtime.profiles.controlled_config(template, values)
                    result = tomllib.loads(runtime.controlled_config(human, values, self.output, 20))
                    self.assertEqual(result['display'], tomllib.loads(human)['display'])
                    self.assertEqual(result['debug']['screenshot_every'], (cap or 120) * 5)
                    self.assertEqual(result['debug']['test_input'], 'bot:0')
                    self.assertEqual(result['debug']['exit_after'], 20.0)
                    self.assertFalse(result['audio']['enabled'])
                    self.assertTrue(all(value == '' for value in result['bindings'].values()))
                    self.assertEqual(result['input']['mouse_sensitivity'], 1e-20)

    def test_complete_fake_run_proves_exact_bound_files_and_can_promote_human_profile(self):
        before = runtime.profiles.descriptor(self.profile / 'saves/config.toml')
        with mock.patch.dict(runtime.os.environ, {'HALO_FRAME_LIMIT': '120', 'HALO_NO_AUDIO': '1', 'MTL_DEBUG_LAYER': '0'}):
            result = self.run_fixture()
        self.assertTrue(result['bounded_runtime_gate'])
        self.assertEqual(before, runtime.profiles.descriptor(self.profile / 'saves/config.toml'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]['timeout'], 40)
        self.assertEqual(self.calls[0]['environment']['MTL_DEBUG_LAYER'], '1')
        self.assertNotIn('HALO_FRAME_LIMIT', self.calls[0]['environment'])
        self.assertNotIn('HALO_NO_AUDIO', self.calls[0]['environment'])
        self.assertTrue((self.output / 'data/maps').is_symlink())
        self.assertEqual((self.output / 'data/init.txt').read_bytes(), (self.profile / 'data/init.txt').read_bytes())
        self.assertEqual(result['test_config'], runtime.profiles.descriptor(self.output / 'saves/config.toml'))
        self.assertEqual(result['launch_log'], runtime.profiles.descriptor(self.output / 'launch.log'))
        self.assertEqual(result['execution'], runtime.profiles.descriptor(self.output / 'execution.json'))
        self.assertEqual(result['image']['width'], 1440)
        self.assertEqual(result['image']['height'], 1080)
        self.assertTrue(result['awaiting_image_review'])
        self.assertFalse(result['world_weapon_hud_pixels_visually_inspected'])
        for key in ('manual_input_audio_gate', 'achieved_render_fps_gate', 'performance_improvement_gate',
                    'original_xbox_fidelity_gate', 'full_game_gate'):
            self.assertFalse(result[key])
        ready = runtime.profiles.promote(self.profile, self.proof, self.output / 'runtime.json')
        self.assertTrue(ready['experiment_ready'])
        self.assertFalse(ready['original_xbox_fidelity_gate'])

    def test_native_fullscreen_measured_startup_capture_and_statistics_binding(self):
        self.native_fixture()
        with mock.patch.dict(runtime.os.environ,{'HALO_WINDOWED':'1','HALO_GPU_STATS':'0'}):
            result=self.run_fixture()
        self.assertTrue(result['bounded_runtime_gate'])
        self.assertEqual((result['image']['width'],result['image']['height']),(3600,2338))
        self.assertEqual(result['native_resolution']['drawable_width'],3600)
        self.assertEqual(result['native_resolution']['logical_width'],738)
        self.assertEqual(result['host_metrics'][0]['gpu_samples'],900)
        self.assertEqual(self.calls[0]['environment']['HALO_WINDOWED'],'0')
        self.assertEqual(self.calls[0]['environment']['HALO_GPU_STATS'],'1')
        config=tomllib.loads((self.output/'saves/config.toml').read_text())
        self.assertTrue(config['display']['fullscreen'])
        self.assertEqual(config['display']['screen_width'],0)
        self.assertEqual(config['display']['render_height'],0)
        self.assertTrue(config['debug']['gpu_stats'])
        ready=runtime.profiles.promote(self.profile,self.proof,self.output/'runtime.json')
        self.assertTrue(ready['experiment_ready'])

    def test_native_wrong_startup_drawable_cannot_pass_even_with_correct_capture(self):
        self.native_fixture()
        def wrong(*arguments):
            observation=self.fake_runner(*arguments)
            path=Path(arguments[3]);path.write_text(path.read_text().replace('3600x2338 drawable','3595x2338 drawable'))
            return observation
        result=self.run_fixture(wrong)
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertTrue(any('Measured native' in error for error in result['validation_failures']))

    def test_unmeasured_native_probe_records_pixels_without_ready_promotion(self):
        self.fixture.folder=self.fixture.base/'unmeasured native profile';self.profile=self.fixture.folder
        self.fixture.draft(height=0,native_fullscreen=True)
        self.proof=self.fixture.build(native_resolution=True)
        self.values=runtime.profiles.profile_values('bloodgulch',60,0,False,True,(3600,2338))
        result=self.run_fixture()
        self.assertEqual(len(self.calls),1)
        self.assertTrue(result['native_probe'])
        self.assertTrue(result['diagnostic_execution_gate'])
        self.assertFalse(result['native_size_expectation_bound'])
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertEqual(result['observed_native_size'],[3600,2338])
        self.assertIsNone(runtime.profiles.verify_profile(self.profile)['profile']['native_size'])
        with self.assertRaises(ValueError): runtime.profiles.promote(self.profile,self.proof,self.output/'runtime.json')

    def test_timing_only_disables_all_captures_and_cannot_promote(self):
        self.native_fixture()
        result=self.run_fixture(timing_only=True,api_validation=False)
        self.assertTrue(result['timing_execution_gate'])
        self.assertFalse(result['diagnostic_execution_gate'])
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertFalse(result['passed'])
        self.assertIsNone(result['render_capture'])
        self.assertIsNone(result['image'])
        self.assertEqual(list((self.output/'captures').iterdir()),[])
        self.assertFalse((self.output/'inspection.png').exists())
        config=tomllib.loads((self.output/'saves/config.toml').read_text())
        self.assertEqual(config['debug']['screenshot_every'],0)
        self.assertEqual(config['debug']['screenshot_directory'],'')
        self.assertEqual(len(result['host_metrics']),1)
        self.assertEqual(len(result['metrics']),3)
        self.assertEqual(self.calls[0]['environment']['HALO_GPU_STATS'],'1')
        with self.assertRaises(ValueError): runtime.profiles.promote(self.profile,self.proof,self.output/'runtime.json')

    def test_timing_only_missing_host_metrics_or_unexpected_capture_fails(self):
        for problem in ('host','capture'):
            self.output=self.fixture.base/('timing-'+problem)
            def wrong(*arguments):
                observation=self.fake_runner(*arguments)
                if problem=='host':
                    path=Path(arguments[3]);path.write_text(path.read_text().replace(HOST_LINE,''))
                else: bmp(Path(arguments[1])/'captures/frame00300.bmp',1440,1080)
                return observation
            result=self.run_fixture(wrong,timing_only=True)
            self.assertFalse(result['timing_execution_gate'])
            self.assertFalse(result['bounded_runtime_gate'])

    def test_statistics_environment_override_requires_matching_bound_debug_setting(self):
        self.run_fixture()
        execution_path=self.output/'execution.json';execution=json.loads(execution_path.read_text())
        execution['environment_overrides']['HALO_GPU_STATS']='1';execution_path.write_text(json.dumps(execution))
        record_path=self.output/'runtime.json';record=json.loads(record_path.read_text())
        record['execution']=runtime.descriptor(execution_path);record_path.write_text(json.dumps(record))
        build=runtime.profiles.checked_build(self.proof,self.fixture.repo)
        runtime.profiles.checked_runtime(record_path,self.values,build)
        config=self.output/'saves/config.toml'
        config.write_text(runtime.profiles.set_key(config.read_text(),'debug','gpu_stats','false'))
        record['test_config']=runtime.descriptor(config);record_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'statistics override'):
            runtime.profiles.checked_runtime(record_path,self.values,build)

    def test_frame_timing_parser_and_steady_percentiles_include_logging_cost(self):
        text=('Native timing: frame 10, monotonic 1000000000 ns, tick 149, initialized 1\n'
              'Native timing: frame 11, monotonic 1008000000 ns, tick 150, initialized 1\n'
              'Native timing: frame 12, monotonic 1016000000 ns, tick 150, initialized 1\n'
              'Native timing: frame 13, monotonic 1032000000 ns, tick 151, initialized 1\n'
              'Native timing: frame 14, monotonic 1072000000 ns, tick 152, initialized 1\n')
        state=runtime.parse_log(text)
        self.assertEqual(len(state['frame_timing']),5)
        summary=runtime.summarize_frame_timing(state['frame_timing'])
        self.assertEqual(summary['interval_count'],3)
        self.assertEqual(summary['p50_ms'],16.0)
        self.assertAlmostEqual(summary['p95_ms'],37.6)
        self.assertAlmostEqual(summary['p99_ms'],39.52)
        self.assertEqual(summary['max_ms'],40.0)
        self.assertEqual(summary['over_16_67_ms'],1)
        self.assertEqual(summary['over_8_33_ms'],2)
        self.assertTrue(summary['logging_cost_included'])
        self.assertIn('cap waits',summary['scope'])
        self.assertIsNone(runtime.summarize_frame_timing(state['frame_timing'][:2]))
        broken=list(state['frame_timing'])
        broken[3]=dict(broken[3],frame=20)
        summary=runtime.summarize_frame_timing(broken)
        self.assertEqual(summary['interval_count'],1)
        self.assertEqual(summary['discarded_nonconsecutive_intervals'],2)
        malformed=runtime.parse_log('Native timing: frame10 malformed\n')
        self.assertTrue(malformed['telemetry_errors'])

    def test_stale_build_or_human_profile_rejected_before_runner_and_output_creation(self):
        current = self.fixture.repo / 'port/linux/src/halo_frame_pacing.c'
        current.write_text('changed CPU fixture')
        with self.assertRaisesRegex(ValueError, 'drift'):
            self.run_fixture()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_existing_output_and_invalid_duration_never_launch_or_overwrite(self):
        self.output.mkdir()
        existing = self.output / 'save.bin'
        existing.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'Fresh output'):
            self.run_fixture()
        self.assertEqual(existing.read_bytes(), b'keep')
        self.assertEqual(self.calls, [])
        for value in (True, 0, 14.9, 581, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                runtime.validate_duration(value)

    def test_timeout_nonzero_host_and_guest_codes_are_retained(self):
        def failed(*arguments):
            observation = self.fake_runner(*arguments)
            path = Path(arguments[3])
            path.write_text(path.read_text().replace('Game exited (0)', 'Game exited (7)'))
            return dict(observation, returncode=-15, timed_out=True, elapsed_seconds=40.2)
        result = self.run_fixture(failed)
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertEqual(result['actual_host_returncode'], -15)
        self.assertEqual(result['actual_guest_returncode'], 7)
        execution = json.loads((self.output / 'execution.json').read_text())
        self.assertTrue(execution['timed_out'])
        self.assertEqual(execution['returncode'], -15)

    def test_missing_telemetry_and_physical_dimension_mismatch_fail_gate(self):
        for text in ('Metal API Validation Enabled\nGame exited (0)\n',
                     'Metal API Validation Enabled\n' + log_line(self.values).replace('1440x1080', '640x480')
                     + log_line(self.values, first=60, last=90) + 'Game exited (0)\n'):
            with self.subTest(text=text):
                path = self.fixture.base / ('case-' + str(len(list(self.fixture.base.glob('case-*')))))
                def altered(*arguments):
                    observation = self.fake_runner(*arguments)
                    Path(arguments[3]).write_text(text)
                    return observation
                with mock.patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('No launch')):
                    result = runtime.run(path, self.profile, self.proof, runner=altered)
                self.assertFalse(result['bounded_runtime_gate'])
                self.assertTrue(result['validation_failures'])

    def test_telemetry_startup_zero_is_allowed_but_multiple_advancing_tick_intervals_required(self):
        state = runtime.parse_log(log_line(self.values, hz=0, first=0, last=0)
                                  + log_line(self.values) + log_line(self.values, first=60, last=90))
        runtime.validate_telemetry(state['telemetry'], self.values)
        for rows in (state['telemetry'][:1], state['telemetry'][:2]):
            with self.assertRaisesRegex(ValueError, 'tick intervals'):
                runtime.validate_telemetry(rows, self.values)
        for replacement in (dict(frame_limit=120), dict(interpolation=False), dict(logical_width=1440)):
            rows = [dict(row, **replacement) for row in state['telemetry']]
            with self.assertRaises(ValueError):
                runtime.validate_telemetry(rows, self.values)

    def test_api_or_native_errors_and_missing_validation_marker_fail_gate(self):
        def failed(*arguments):
            observation = self.fake_runner(*arguments)
            path = Path(arguments[3])
            path.write_text(path.read_text().replace('Metal API Validation Enabled\n', '')
                            + 'Native Metal: draw failed (-2)\nfailed assertion color attachment\n')
            return observation
        result = self.run_fixture(failed)
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertFalse(result['api_validation_enabled'])
        self.assertEqual(len(result['renderer_api_errors']), 2)

    def test_early_clean_exit_cannot_pass_bounded_runtime(self):
        def early(*arguments):
            return dict(self.fake_runner(*arguments), elapsed_seconds=3.0)
        self.assertFalse(self.run_fixture(early)['bounded_runtime_gate'])

    def test_validation_off_records_diagnostics_but_cannot_promote(self):
        def diagnostic(*arguments):
            observation = self.fake_runner(*arguments)
            path = Path(arguments[3])
            path.write_text(path.read_text().replace('Metal API Validation Enabled\n', ''))
            return observation
        with mock.patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('No launch')):
            with mock.patch.dict(runtime.os.environ, {'MTL_DEBUG_LAYER': '1'}):
                result = runtime.run(self.output, self.profile, self.proof, runner=diagnostic, api_validation=False)
        self.assertTrue(result['diagnostic_execution_gate'])
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertFalse(result['api_validation_requested'])
        self.assertFalse(result['api_validation_enabled'])
        self.assertNotIn('MTL_DEBUG_LAYER', self.calls[0]['environment'])
        execution = json.loads((self.output / 'execution.json').read_text())
        self.assertNotIn('MTL_DEBUG_LAYER', execution['environment_overrides'])
        self.assertFalse(execution['api_validation_requested'])
        with self.assertRaises(ValueError):
            runtime.profiles.promote(self.profile, self.proof, self.output / 'runtime.json')

    def test_post_launch_display_change_cannot_substitute_the_initial_input_digest(self):
        def changed(*arguments):
            observation = self.fake_runner(*arguments)
            path = Path(arguments[1]) / 'saves/config.toml'
            path.write_text(runtime.profiles.set_key(path.read_text(), 'display', 'frame_limit', '120'))
            return observation
        result = self.run_fixture(changed)
        self.assertFalse(result['bounded_runtime_gate'])
        self.assertEqual(result['test_config']['sha256'], runtime.sha(self.output / 'saves/config.toml'))
        self.assertNotEqual(result['input_config']['sha256'], result['test_config']['sha256'])
        self.assertTrue(any('initial setting: display.frame_limit' in error for error in result['validation_failures']))

    def test_benign_saved_defaults_and_formatting_preserve_exact_initial_input(self):
        source = self.fixture.repo / 'port/linux/src/port_config.c'
        source.write_text(source.read_text() + '\n{"network.public_games", _config_boolean, "true", NULL, x},\n')
        frozen = self.fixture.repo / 'frozen-build/port/linux/src/port_config.c'
        frozen.write_bytes(source.read_bytes())
        proof = json.loads(self.proof.read_text())
        for binding in proof['source_bindings']:
            if binding['path'] == 'port/linux/src/port_config.c':
                binding['sha256'] = runtime.sha(source)
        self.proof.write_text(json.dumps(proof))
        def saved(*arguments):
            observation = self.fake_runner(*arguments)
            path = Path(arguments[1]) / 'saves/config.toml'
            path.write_text(runtime.profiles.set_key(path.read_text(), 'network', 'public_games', 'true')
                            + '\n# routine save formatting\n')
            return observation
        result = self.run_fixture(saved)
        self.assertTrue(result['bounded_runtime_gate'])
        self.assertEqual(result['saved_default_insertions'], {'network.public_games': True})
        self.assertNotEqual(result['input_config']['sha256'], result['test_config']['sha256'])
        initial = runtime.profiles.checked_descriptor(result['input_config'])
        self.assertNotIn('public_games', tomllib.loads(initial.read_text())['network'])
        execution = json.loads((self.output / 'execution.json').read_text())
        self.assertEqual(execution['input_config'], result['input_config'])
        self.assertEqual(execution['test_config'], result['test_config'])
        runtime.profiles.checked_runtime(self.output / 'runtime.json', self.values,
                                         runtime.profiles.checked_build(self.proof, self.fixture.repo))

    def test_unknown_or_nondefault_insertions_are_rejected(self):
        initial = {'network': {'online': False}, 'display': {'frame_limit': 60}}
        for saved in ({'network': {'online': False, 'public_games': False}, 'display': {'frame_limit': 60}},
                      {'network': {'online': False, 'unregistered': True}, 'display': {'frame_limit': 60}}):
            with self.assertRaisesRegex(ValueError, 'unknown or nondefault'):
                runtime.validate_saved_config(initial, saved, {'network.public_games': True})
        with self.assertRaisesRegex(ValueError, 'initial setting'):
            runtime.validate_saved_config(initial, {'network': {'online': False}, 'display': {'frame_limit': True}}, {})

    def test_capture_truncation_wrong_dimensions_and_alpha_only_black_rejected(self):
        path = self.fixture.base / 'capture.bmp'
        width, height = self.values['expected_physical_width'], self.values['render_height']
        bmp(path, width, height)
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            runtime.read_bmp(path, self.values)
        bmp(path, 640, 480)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            runtime.read_bmp(path, self.values)
        bmp(path, width, height, rgb=(0, 0, 0), alpha=255)
        with self.assertRaisesRegex(ValueError, 'entirely black'):
            runtime.read_bmp(path, self.values)

    def test_png_conversion_preserves_bmp_rgb_and_bottom_up_orientation(self):
        values = dict(expected_physical_width=2, render_height=2)
        path = self.fixture.base / 'small.bmp'
        bmp(path, 2, 2, rgb=(1, 2, 3), positive_height=True)
        raw = bytearray(path.read_bytes())
        raw[54:62] = bytes((6, 5, 4, 255)) * 2
        path.write_bytes(raw)
        width, height, rgb = runtime.read_bmp(path, values)
        self.assertEqual(rgb, bytes((1, 2, 3)) * 2 + bytes((4, 5, 6)) * 2)
        png = self.fixture.base / 'inspection.png'
        runtime.write_png(png, width, height, rgb)
        raw = png.read_bytes()
        self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
        position, compressed = 8, bytearray()
        while position < len(raw):
            size = struct.unpack_from('>I', raw, position)[0]
            kind, payload = raw[position+4:position+8], raw[position+8:position+8+size]
            self.assertEqual(zlib.crc32(kind + payload), struct.unpack_from('>I', raw, position+8+size)[0])
            if kind == b'IDAT':
                compressed.extend(payload)
            position += size + 12
        self.assertEqual(zlib.decompress(compressed), b'\0' + rgb[:6] + b'\0' + rgb[6:])

    def test_last_capture_selected_by_numeric_frame_and_checked_runtime_rejects_later_log_tamper(self):
        def ordered(*arguments):
            observation = self.fake_runner(*arguments)
            directory = Path(arguments[1]) / 'captures'
            bmp(directory / 'frame99999.bmp', 1440, 1080, rgb=(1, 2, 3))
            bmp(directory / 'frame100000.bmp', 1440, 1080, rgb=(4, 5, 6))
            return observation
        result = self.run_fixture(ordered)
        self.assertEqual(result['image']['capture_frame'], 100000)
        self.assertEqual(Path(result['render_capture']['file']).name, 'frame100000.bmp')
        original = (self.output / 'launch.log').read_bytes()
        (self.output / 'launch.log').write_bytes(original + b'changed\n')
        with self.assertRaises(ValueError):
            runtime.profiles.checked_descriptor(result['launch_log'])


if __name__ == '__main__':
    unittest.main()
