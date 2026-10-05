"""CPU-only safeguards for the isolated native-game benchmark harness."""
import hashlib
import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools.metal_live_batch_benchmark import (
    Observation, comparison, controlled_config, sanitized_environment,
    tree_hashes, validate_paths, prepare,
)


class LiveBatchBenchmarkTests(unittest.TestCase):
    def test_fixed_settings_round_trip_and_unrelated_values_survive(self):
        original='''[display]
fullscreen=true
window_scale=9
[network]
online=true
address="local-only-value"
[debug]
screenshot_every=30
exit_after=15.0
test_input="look:1"
[input]
mouse_sensitivity=1.75
invert_mouse=true
[bindings]
move_forward="W"
custom_future_key="Q"
'''
        text=controlled_config(original)
        parsed=tomllib.loads(text)
        self.assertFalse(parsed['display']['fullscreen'])
        self.assertEqual(parsed['display']['screen_width'],640)
        self.assertEqual(parsed['display']['window_scale'],2)
        self.assertFalse(parsed['display']['interpolation'])
        self.assertFalse(parsed['display']['vsync'])
        self.assertFalse(parsed['network']['join_from_clipboard'])
        self.assertFalse(parsed['network']['online'])
        self.assertFalse(parsed['network']['allow_upnp'])
        self.assertEqual(parsed['network']['address'],'local-only-value')
        self.assertFalse(parsed['update']['auto'])
        self.assertEqual(parsed['debug']['exit_after'],45.0)
        self.assertEqual(parsed['debug']['screenshot_every'],0)
        self.assertEqual(parsed['debug']['test_input'],'')
        self.assertEqual(parsed['input']['mouse_sensitivity'],1e-20)
        self.assertTrue(parsed['input']['invert_mouse'])
        self.assertEqual(parsed['bindings']['move_forward'],'')
        self.assertEqual(parsed['bindings']['custom_future_key'],'')
        self.assertTrue(all(v=='' for v in parsed['bindings'].values()))
        self.assertEqual(original.splitlines()[1],'fullscreen=true')

    def test_only_existing_approved_environment_overrides_are_added(self):
        env,binding=sanitized_environment(Path('/private/tmp/data'),Path('/private/tmp/saves'),
            dict(HOME='/unchanged/home',HALO_GPU_STATS='1',HALO_NO_VSYNC='1',HALO_TEST_INPUT='look:99',
                 MTL_DEBUG_LAYER='1',METAL_DEVICE_WRAPPER_TYPE='1',DYLD_INSERT_LIBRARIES='fixture.dylib'))
        self.assertEqual(env,dict(HOME='/unchanged/home',HALO_DATA_ROOT='/private/tmp/data',
                                 HALO_SAVE_ROOT='/private/tmp/saves',HALO_WINDOWED='1'))
        self.assertEqual(set(binding['added']),{'HALO_DATA_ROOT','HALO_SAVE_ROOT','HALO_WINDOWED'})
        self.assertNotIn('fixture.dylib',str(binding))

    def test_interval_metrics_and_native_submission_fields_have_real_meanings(self):
        observed=Observation()
        observed.line('Metal drawable 2560x1920 (windowed)',1)
        observed.line('halo-linux: screen: 640x480 drawn at 640x480',2)
        for frame in range(60,601,60):
            observed.line(f'Native frame {frame}: {frame*200} original draws, 135 texture resources, 53 programs',
                          frame*50_000_000)
            observed.line(f'Native submissions frames {frame-59}-{frame}: 180 batches, 15000 commands, '
                          '3000000 bytes, 900000 host-submit us, largest 4194000 bytes',frame*50_000_000+1)
        summary=observed.summary()
        self.assertEqual(summary['wall_seconds'],24)
        self.assertEqual(summary['fps'],20)
        self.assertEqual(summary['original_draws'],96000)
        self.assertEqual(len(summary['intervals']),8)
        self.assertEqual(summary['submission_intervals'][0]['first_frame'],121)
        self.assertEqual(summary['submission_intervals'][0]['host_submit_us'],900000)
        self.assertEqual(len(summary['submission_intervals']),8)

    def test_missing_checkpoint_or_regressed_stats_cannot_silently_pass(self):
        observed=Observation()
        for frame in (120,180,240,300,420,480,540,600):
            observed.line(f'Native frame {frame}: {frame} original draws, 1 texture resources, 1 programs',frame)
        with self.assertRaisesRegex(ValueError,'checkpoints'):
            observed.summary()
        observed.line('Native frame 600: 1 original draws, 1 texture resources, 1 programs',601)
        self.assertTrue(observed.errors)

    def test_workload_mismatch_remains_explicit_even_when_fps_is_higher(self):
        def run(variant,fps,draws):
            return dict(variant=variant,passed=True,drawable=[dict(width=2560,height=1920,mode='windowed')],
                measurement=dict(fps=fps,original_draws=draws,
                    start=dict(textures=135,programs=53),end=dict(textures=135,programs=53)))
        result=comparison([run('A',20,1000),run('B',30,1001)])
        self.assertFalse(result['exact_workload_count_and_resource_parity'])
        self.assertEqual(result['median_throughput_change_percent'],50)

    def test_no_overwrite_nested_output_or_template_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            data=root/'data';(data/'maps').mkdir(parents=True)
            saves=root/'saves';saves.mkdir();config=saves/'config.toml';config.write_text('')
            host=root/'host';host.write_bytes(b'fixture');host.chmod(0o700)
            guest=root/'guest';guest.write_bytes(b'fixture')
            output=root/'new-output'
            validate_paths(host,guest,host,guest,data,saves,config,output)
            output.mkdir()
            with self.assertRaisesRegex(ValueError,'must not exist'):
                validate_paths(host,guest,host,guest,data,saves,config,output)
            with self.assertRaisesRegex(ValueError,'nested'):
                validate_paths(host,guest,host,guest,data,saves,config,data/'new-output')
            (saves/'outside').symlink_to(host)
            with self.assertRaisesRegex(ValueError,'no symlinks'):
                tree_hashes(saves)
            self.assertEqual(hashlib.sha256(host.read_bytes()).hexdigest(),
                             hashlib.sha256(b'fixture').hexdigest())

    def test_preparation_clones_four_independent_saves_and_never_launches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            data=root/'data';(data/'maps').mkdir(parents=True);(data/'sounds').mkdir()
            template=root/'template';template.mkdir();(template/'config.toml').write_text('[bindings]\na="Space"\n')
            (template/'profile.sav').write_bytes(b'unchanged private profile fixture')
            initial=tree_hashes(template)
            host=root/'host';host.write_bytes(b'executable fixture, never executed');host.chmod(0o700)
            guest=root/'guest';guest.write_bytes(b'guest fixture, never executed')
            args=argparse.Namespace(a_host=host,a_guest=guest,b_host=host,b_guest=guest,data_root=data,
                template_saves=template,template_config=None,output=root/'out',repetitions=1,timeout=75,
                a_source_root=None,b_source_root=None)
            with patch('tools.metal_live_batch_benchmark.original_maps',return_value={}), \
                    patch('subprocess.Popen') as launch,contextlib.redirect_stdout(io.StringIO()):
                plan=prepare(args)
            launch.assert_not_called()
            self.assertEqual([r['variant'] for r in plan['runs']],['A','B','B','A'])
            self.assertFalse(plan['executed'])
            self.assertEqual(tree_hashes(template),initial)
            folders=[Path(r['folder']) for r in plan['runs']]
            for folder in folders:
                self.assertEqual((folder/'saves/profile.sav').read_bytes(),b'unchanged private profile fixture')
                self.assertTrue((folder/'data/maps').is_symlink())
                self.assertEqual((folder/'data/maps').resolve(),(data/'maps').resolve())
                self.assertEqual(tomllib.loads((folder/'saves/config.toml').read_text())['bindings']['a'],'')
            (folders[0]/'saves/profile.sav').write_bytes(b'one isolated run changed')
            self.assertEqual((folders[1]/'saves/profile.sav').read_bytes(),b'unchanged private profile fixture')
            self.assertEqual(tree_hashes(template),initial)
            self.assertEqual(json.loads((args.output/'prepared.json').read_text())['kind'],'native_live_batch_benchmark')


if __name__=='__main__':
    unittest.main()
