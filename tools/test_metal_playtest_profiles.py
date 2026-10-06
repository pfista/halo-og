"""CPU profile/handoff guards; synthetic build/runtime records never run a game."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import tomllib
import unittest
from unittest import mock

try:
    from tools import metal_playtest_profiles as profiles
except ImportError:
    import metal_playtest_profiles as profiles


TEMPLATE = '''[display]
screen_width = 640
window_scale = 2
fullscreen = false
vsync = false
interpolation = false
high_res_hud = false
direct_camera = false
[audio]
enabled = true
volume = 1.0
[input]
mouse_sensitivity = 1.0
invert_mouse = false
[bindings]
move_forward = "W"
fire = "Mouse1"
[network]
online = false
allow_upnp = false
join_from_clipboard = false
[update]
auto = false
[game]
console_log = "important"
language = ""
[debug]
test_input = ""
exit_after = 0.0
hidden_window = false
null_renderer = false
telnet_console = false
screenshot_every = 0
screenshot_directory = ""
texture_dump_directory = ""
gpu_skip_vertex_shaders = ""
gpu_dump_shaders = ""
gpu_debug_expression = ""
gpu_debug_texture0 = false
gpu_debug_flat = false
network_test = ""
network_latency = 0.0
network_loss = 0.0
'''


def write_json(path, value):
    Path(path).write_text(json.dumps(value))


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='metal-profile-cpu-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repository'
        self.repo.mkdir()
        self.assets = self.base / 'original-assets'
        (self.assets / 'maps').mkdir(parents=True)
        (self.assets / 'sounds').mkdir()
        for name in profiles.MAPS + ('ui',):
            header = bytearray(2048)
            header[:4], header[2044:] = b'daeh', b'toof'
            struct.pack_into('<I', header, 4, 5)
            header[32:32+len(name)] = name.encode()
            header[64:64+len('01.10.12.2276')] = b'01.10.12.2276'
            struct.pack_into('<H', header, 96, 2 if name == 'ui' else 1)
            (self.assets / 'maps' / (name + '.map')).write_bytes(header)
        self.template = self.base / 'normal.toml'
        self.template.write_text(TEMPLATE)
        self.folder = self.base / 'profile with spaces'

    def draft(self, cap=60, height=720, vsync=False, output=None, native_fullscreen=False, native_size=None, anti_aliasing='off'):
        return profiles.prepare(output or self.folder, 'bloodgulch', cap, height, vsync,
                                self.assets, self.template, self.repo,
                                native_fullscreen=native_fullscreen, native_size=native_size, anti_aliasing=anti_aliasing)

    def build(self, options=True, native_resolution=False):
        snapshot = self.repo / 'frozen-build'
        graph, compiled, bindings = {}, {}, []
        for relative in sorted(profiles.REQUIRED_BUILD_PATHS | profiles.AA_BUILD_PATHS):
            p = self.repo / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            if relative == profiles.HOST:
                data = struct.pack('<II', 0xfeedfacf, 0x0100000c) + b'CPU fixture only'
            elif relative == profiles.GUEST:
                data = bytearray(52)
                data[:6] = b'\x7fELF\x02\x01'
                struct.pack_into('<H', data, 18, 183)
                data = bytes(data)
            elif relative.endswith('port_config.c'):
                data = b'{"display.frame_limit", _config_integer, "0", NULL, x},\n'
                data += b'{"display.render_height", _config_integer, "480", NULL, x},\n'
                data += b'{"display.anti_aliasing", _config_string, "\\"off\\"", NULL, x},\n'
                data += b'{"audio.enabled", b, "true", "HALO_NO_AUDIO", x},\n'
                data += b'getenv("HALO_DATA_ROOT"); getenv("HALO_SAVE_ROOT");\n'
            elif relative.endswith('halo_metal_abi.h'):
                data = b'enum { HALO_METAL_CAP_FXAA = 32768u, HALO_METAL_FXAA = 22, HALO_METAL_ENABLE_FXAA = 2u };'
            else:
                data = ('CPU fake proof payload ' + relative).encode()
            p.write_bytes(data)
            if relative == profiles.HOST:
                p.chmod(0o755)
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            bindings.append(dict(path=relative, sha256=profiles.sha(p)))
        by_path = {x['path']: x['sha256'] for x in bindings}
        for name in profiles.HELPERS:
            obj = f'build/macos-metal/guest/obj/port/linux/src/{name}.o'
            graph[name] = f'build {obj}: android_guest_cc port/linux/src/{name}.c'
            symbols = sorted(profiles.HELPER_SYMBOLS[name])
            if name == 'metal_render_scale' and native_resolution:
                symbols.append(profiles.NATIVE_RESOLUTION_SYMBOL)
            compiled[name] = dict(object={'path': obj, 'sha256': by_path[obj]}, symbol=symbols[0],
                                  additional_linked_symbols=symbols[1:], linked_in_guest=True, native_ilp32_flags=True)
        aa_object = 'build/macos-metal/guest/obj/port/linux/src/d3d8_metal.o'
        compiled['d3d8_metal'] = dict(object={'path': aa_object, 'sha256': by_path[aa_object]}, symbol='halo_metal_flush_pending',
            additional_linked_symbols=[profiles.AA_SYMBOL], linked_in_guest=True, native_ilp32_flags=True)
        render_object = 'build/macos-metal/guest/obj/source/render/render.o'
        graph['render'] = f'build {render_object}: android_guest_cc source/render/render.c'
        build = dict(schema_version=1, passed=True, actual_build_tool_exit=0, display_options=options,
            anti_aliasing=True,
            anti_aliasing_contract=dict(capability=32768, opcode=22, enable_flag=2, stage='pre-HUD', modes=['off','fxaa']),
            anti_aliasing_world_hook=dict(object={'path': render_object, 'sha256': by_path[render_object]}, symbol=profiles.AA_SYMBOL,
                compiled_call=True, linked_in_guest=True, native_ilp32_flags=True),
            native_resolution=native_resolution,
            no_angle_gl_linkage_or_imports=True, source_snapshot='frozen-build',
            source_bindings=bindings, evidence_bindings=[], native_compiled_objects=compiled,
            native_guest_graph=dict(source_edges=graph, no_gl_native_edges=True,
                guest_link_edge='build build/macos-metal/halo_guest.elf: android_guest_link '
                + ' '.join(f'build/macos-metal/guest/obj/port/linux/src/{h}.o' for h in profiles.HELPERS)
                + ' ' + aa_object + ' ' + render_object))
        path = self.base / 'new-build.json'
        write_json(path, build)
        return path

    def runtime(self, build_path):
        manifest = json.loads((self.folder / 'profile.json').read_text())
        v = manifest['profile']
        build = profiles.checked_build(build_path, self.repo, v.get('native_fullscreen', False))
        runtime_saves = self.base / 'runtime-saves'
        runtime_saves.mkdir(exist_ok=True)
        config = runtime_saves / 'config.toml'
        config.write_bytes((self.folder / 'saves/config.toml').read_bytes())
        log = self.base / 'launch.log'
        log_text = 'CPU fixture only; no native process was launched\n'
        log_text += f'Native anti-aliasing: requested {v["anti_aliasing"]}, applied {50 if v["anti_aliasing"] == "fxaa" else 0}, stage pre-HUD\n'
        if v.get('native_fullscreen', False):
            width, height = profiles.physical_size(v)
            log_text += (f'Metal API Validation Enabled\nMetal drawable {width}x{height} (borderless fullscreen)\n'
                         f'Native resolution: {width}x{height} storage, {v["logical_width"]}x480 logical, '
                         f'{width}x{height} drawable, startup aspect native\n')
        log.write_text(log_text)
        execution = self.base / 'execution.json'
        write_json(execution, dict(returncode=0, elapsed_seconds=15.5,
                                  log=profiles.descriptor(log),
                                  command=[build['host']['file'], build['guest']['file']],
                                  environment_overrides=dict(HALO_SAVE_ROOT=str(runtime_saves.resolve()),
                                      HALO_DATA_ROOT=str((self.folder / 'data').resolve()), HALO_WINDOWED=profiles.windowed_environment(v))))
        capture = self.base / 'native.bmp'
        width, height = profiles.physical_size(v)
        size = width * height * 4
        header = bytearray(54)
        header[:2] = b'BM'
        struct.pack_into('<I', header, 2, 54 + size)
        struct.pack_into('<I', header, 10, 54)
        struct.pack_into('<IiiHHI', header, 14, 40, width, -height, 1, 32, 0)
        capture.write_bytes(header + (bytes((1,2,3,255))*(width*height) if v.get('native_fullscreen', False) else bytes(size)))
        runtime = dict(schema_version=1, kind='metal_playtest_profile_runtime', bounded_runtime_gate=True,
            build_proof=build['proof'], map=v['map'], display=tomllib.loads((self.folder / 'saves/config.toml').read_text())['display'],
            actual_host_returncode=0, actual_guest_returncode=0, api_validation_enabled=True, renderer_api_errors=[],
            test_config=profiles.descriptor(config), execution=profiles.descriptor(execution),
            launch_log=profiles.descriptor(log),
            anti_aliasing=profiles.checked_anti_aliasing(log_text, v), capture_stage='post-world-AA/post-HUD',
            render_capture=profiles.descriptor(capture))
        if v.get('native_fullscreen', False):
            runtime['native_resolution'] = profiles.checked_native_startup(log_text, v)
        path = self.base / 'runtime.json'
        write_json(path, runtime)
        return path

    def test_aa_choice_is_immutable_and_does_not_change_original_assets_or_human_controls(self):
        original = tomllib.loads(TEMPLATE)
        for mode in profiles.ANTI_ALIASING:
            for native in (False, True):
                values = profiles.profile_values('bloodgulch', 30, 0 if native else 480, False,
                    native, (3600,2338) if native else None, mode)
                config = tomllib.loads(profiles.controlled_config(TEMPLATE, values))
                self.assertEqual(config['display']['anti_aliasing'], mode)
                self.assertFalse(config['display']['high_res_hud'])
                self.assertFalse(config['display']['direct_camera'])
                for section in ('input', 'bindings', 'game'):
                    self.assertEqual(config[section], original[section])
                self.assertEqual(values['reference_30'], not native and mode == 'off')
        for invalid in (None, True, 1, 'FXAA', 'msaa', ''):
            with self.subTest(mode=invalid), self.assertRaises(ValueError):
                profiles.profile_values('bloodgulch',60,1080,False,anti_aliasing=invalid)
        self.draft(anti_aliasing='fxaa')
        manifest = profiles.verify_profile(self.folder)
        self.assertIs(manifest['simulation_source_modified'], False)
        self.assertEqual((self.folder/'data/maps').resolve(), (self.assets/'maps').resolve())
        config = self.folder/'saves/config.toml'
        config.write_text(profiles.set_key(config.read_text(), 'display', 'anti_aliasing', '"off"'))
        with self.assertRaisesRegex(ValueError, 'display mismatch: anti_aliasing'):
            profiles.verify_profile(self.folder)

    def test_new_build_requires_aa_marker_abi_compiled_hook_and_world_link(self):
        self.draft()
        path = self.build()
        original = json.loads(path.read_text())
        for mutation in (
            lambda b: b.pop('anti_aliasing'),
            lambda b: b.__setitem__('anti_aliasing', 1),
            lambda b: b['anti_aliasing_contract'].__setitem__('enable_flag', 0),
            lambda b: b['anti_aliasing_world_hook'].__setitem__('compiled_call', False),
            lambda b: b['native_compiled_objects']['d3d8_metal'].__setitem__('additional_linked_symbols', []),
            lambda b: b['native_guest_graph']['source_edges'].__setitem__('render', ''),
            lambda b: b['native_guest_graph'].__setitem__('guest_link_edge',
                b['native_guest_graph']['guest_link_edge'].replace('build/macos-metal/guest/obj/source/render/render.o','')),
        ):
            bad = json.loads(json.dumps(original)); mutation(bad); write_json(path,bad)
            with self.assertRaises(ValueError): profiles.checked_build(path,self.repo)
        write_json(path,original)
        self.assertTrue(profiles.checked_build(path,self.repo)['anti_aliasing'])

    def test_runtime_aa_mode_and_capture_stage_must_match_bound_log(self):
        self.draft(anti_aliasing='fxaa')
        build_path = self.build()
        runtime_path = self.runtime(build_path)
        build = profiles.checked_build(build_path,self.repo)
        values = profiles.verify_profile(self.folder)['profile']
        profiles.checked_runtime(runtime_path,values,build)
        original = json.loads(runtime_path.read_text())
        for mutation in (
            lambda r: r['display'].__setitem__('anti_aliasing','off'),
            lambda r: r['anti_aliasing'].__setitem__('requested','off'),
            lambda r: r['anti_aliasing'].__setitem__('applied',0),
            lambda r: r.__setitem__('capture_stage','pre-AA'),
        ):
            bad = json.loads(json.dumps(original)); mutation(bad); write_json(runtime_path,bad)
            with self.assertRaises(ValueError): profiles.checked_runtime(runtime_path,values,build)

    def test_aa_execution_parser_rejects_missing_wrong_mode_no_passes_and_counter_debt(self):
        off = profiles.profile_values('bloodgulch',60,1080,False)
        fxaa = dict(off,anti_aliasing='fxaa')
        def line(mode,count,stage='pre-HUD'):
            return f'Native anti-aliasing: requested {mode}, applied {count}, stage {stage}\n'
        self.assertEqual(profiles.checked_anti_aliasing(line('fxaa',0)+line('fxaa',5),fxaa)['applied'],5)
        for log,values in (('',off),(line('fxaa',1),off),(line('off',1),off),(line('fxaa',0),fxaa),
                           (line('fxaa',5)+line('fxaa',4),fxaa),(line('fxaa',1,'post-HUD'),fxaa),
                           (line('fxaa',1<<64),fxaa),(line('FXAA',1),fxaa)):
            with self.subTest(log=log), self.assertRaises(ValueError): profiles.checked_anti_aliasing(log,values)

    def test_chooser_distinguishes_off_and_fxaa_for_the_same_display_profile(self):
        folders = []
        manifests = {}
        for mode in profiles.ANTI_ALIASING:
            folder = self.base/mode
            manifest = self.draft(output=folder, anti_aliasing=mode)
            (folder/'ready.json').write_text('CPU chooser identity fixture')
            (folder/'Launch Native Metal.command').write_text('CPU fixture; never executed')
            folders.append(folder)
            manifests[folder.resolve()] = manifest
        with mock.patch.object(profiles,'verify_profile',side_effect=lambda folder,ready: manifests[Path(folder).resolve()]):
            result = profiles.chooser(self.base/'choose-aa',folders)
            text = Path(result['launcher']['file']).read_text()
            self.assertIn('AA OFF',text)
            self.assertIn('AA FXAA',text)
            self.assertEqual(len(result['ready_profiles']),2)
            with self.assertRaisesRegex(ValueError,'Duplicate chooser'):
                profiles.chooser(self.base/'choose-duplicate-aa',[folders[0],folders[0]])

    def test_all_cap_height_vsync_profiles_keep_30hz_baseline_controls(self):
        base = tomllib.loads(TEMPLATE)
        for map_name in profiles.MAPS:
            for cap in profiles.CAPS:
                for height in profiles.HEIGHTS:
                    for vsync in (False, True):
                        v = profiles.profile_values(map_name, cap, height, vsync)
                        config = tomllib.loads(profiles.controlled_config(TEMPLATE, v))
                        self.assertEqual(config['display']['interpolation'], cap != 30)
                        self.assertEqual(config['display']['frame_limit'], cap)
                        self.assertEqual(config['display']['render_height'], height)
                        self.assertEqual(config['display']['vsync'], vsync)
                        self.assertFalse(config['display']['direct_camera'])
                        self.assertFalse(config['display']['high_res_hud'])
                        self.assertEqual(config['input'], base['input'])
                        self.assertEqual(config['bindings'], base['bindings'])
                        self.assertEqual(config['game'], base['game'])
        for bad in (True, 1, 59, 240):
            with self.assertRaises(ValueError):
                profiles.profile_values('bloodgulch', bad, 480, False)

    def test_native_fullscreen_values_use_measured_pixels_and_independent_caps_vsync(self):
        for cap in (60,120,0):
            for vsync in (False,True):
                values = profiles.profile_values('bloodgulch', cap, 0, vsync, True, (3600,2338))
                self.assertEqual(profiles.physical_size(values), (3600,2338))
                self.assertEqual(values['logical_width'], 738)
                config = tomllib.loads(profiles.controlled_config(TEMPLATE, values))
                self.assertTrue(config['display']['fullscreen'])
                self.assertEqual(config['display']['screen_width'], 0)
                self.assertEqual(config['display']['render_height'], 0)
                self.assertEqual(config['display']['frame_limit'], cap)
                self.assertIs(config['display']['vsync'], vsync)
                self.assertEqual(config['game'], tomllib.loads(TEMPLATE)['game'])
        self.assertEqual(profiles.parse_native_size('3600x2338'), (3600,2338))
        for invalid in ('0x2338', '8193x2160', '3600', '3600x2338extra', (True,2338), (3600,0), (8192,8192)):
            with self.assertRaises(ValueError): profiles.parse_native_size(invalid)
        with self.assertRaises(ValueError): profiles.profile_values('bloodgulch', 60, 2160, False, True, (3600,2338))
        with self.assertRaises(ValueError): profiles.profile_values('bloodgulch', 60, 2160, False, False, (3600,2338))

    def test_native_profile_without_measured_expectation_stays_unready(self):
        manifest = self.draft(height=0, native_fullscreen=True)
        self.assertIsNone(manifest['profile']['native_size'])
        self.assertFalse(manifest['experiment_ready'])
        profiles.verify_profile(self.folder)
        with self.assertRaisesRegex(ValueError, 'measured native size'):
            profiles.physical_size(manifest['profile'])
        self.assertEqual(manifest['launch_environment']['HALO_WINDOWED'], '0')

    def test_native_build_guard_startup_capture_and_fullscreen_launcher(self):
        self.draft(height=0, native_fullscreen=True, native_size=(3600,2338))
        old = self.build()
        with self.assertRaisesRegex(ValueError, 'Pre-native-resolution'):
            profiles.checked_build(old, self.repo, True)
        build = self.build(native_resolution=True)
        proof = self.runtime(build)
        profiles.promote(self.folder, build, proof)
        profiles.verify_profile(self.folder, True)
        launcher = self.folder / 'Launch Native Metal.command'
        text = launcher.read_text()
        self.assertIn('HALO_WINDOWED=0', text)
        self.assertNotIn('HALO_WINDOWED=1', text)
        self.assertIn('-u HALO_GPU_STATS', text)
        subprocess.run(['zsh','-n',str(launcher)],check=True,capture_output=True)

    def test_native_startup_wrong_pixels_windowed_or_fitted_cannot_promote(self):
        self.draft(height=0, native_fullscreen=True, native_size=(3600,2338))
        proof = self.build(native_resolution=True)
        path = self.runtime(proof)
        original = json.loads(path.read_text())
        log = Path(original['launch_log']['file']); text = log.read_text()
        for changed in (text.replace('3600x2338 drawable','3595x2338 drawable'),
                        text.replace('borderless fullscreen','windowed'),
                        text.replace('aspect native','aspect fitted'),
                        text.replace('Metal API Validation Enabled\n','')):
            log.write_text(changed)
            evidence = dict(original,launch_log=profiles.descriptor(log))
            execution = Path(original['execution']['file']); observed=json.loads(execution.read_text())
            observed['log']=evidence['launch_log'];write_json(execution,observed)
            evidence['execution']=profiles.descriptor(execution);write_json(path,evidence)
            with self.assertRaises(ValueError): profiles.promote(self.folder,proof,path)
            self.assertFalse((self.folder/'ready.json').exists())
        log.write_text(text)

    def test_native_black_or_truncated_capture_and_timing_records_cannot_promote(self):
        self.draft(height=0, native_fullscreen=True, native_size=(3600,2338))
        proof=self.build(native_resolution=True);path=self.runtime(proof)
        original=json.loads(path.read_text());capture=Path(original['render_capture']['file']);raw=capture.read_bytes()
        for pixels in (raw[:54]+bytes((0,0,0,255))*(3600*2338),raw[:-4]):
            capture.write_bytes(pixels);evidence=dict(original,render_capture=profiles.descriptor(capture));write_json(path,evidence)
            with self.assertRaises(ValueError): profiles.promote(self.folder,proof,path)
            self.assertFalse((self.folder/'ready.json').exists())
        capture.write_bytes(raw);write_json(path,dict(original,timing_only=True))
        with self.assertRaisesRegex(ValueError,'Timing-only'): profiles.promote(self.folder,proof,path)

    def test_draft_is_fresh_isolated_and_cannot_be_used_as_ready(self):
        before = profiles.sha(self.assets / 'maps/bloodgulch.map')
        manifest = self.draft(cap=30, height=480)
        self.assertFalse(manifest['experiment_ready'])
        self.assertTrue(manifest['profile']['reference_30'])
        self.assertEqual(manifest['simulation_hz'], 30)
        self.assertEqual((self.folder / 'data/init.txt').read_bytes(),
                         b'display_framerate true\ngame_variant slayer\nmap_name bloodgulch\n')
        self.assertTrue((self.folder / 'data/maps').is_symlink())
        self.assertEqual(before, profiles.sha(self.assets / 'maps/bloodgulch.map'))
        self.assertFalse((self.folder / 'Launch Native Metal.command').exists())
        self.assertEqual((self.folder / 'initial-config.toml').read_bytes(),
                         (self.folder / 'saves/config.toml').read_bytes())
        profiles.verify_profile(self.folder)
        with self.assertRaises(FileNotFoundError):
            profiles.verify_profile(self.folder, True)

    def test_existing_destination_config_and_saves_never_overwritten(self):
        self.folder.mkdir()
        (self.folder / 'saves').mkdir()
        config = self.folder / 'saves/config.toml'
        save = self.folder / 'saves/player.bin'
        config.write_bytes(b'keep user config')
        save.write_bytes(b'keep player')
        with self.assertRaises(ValueError):
            self.draft()
        self.assertEqual(config.read_bytes(), b'keep user config')
        self.assertEqual(save.read_bytes(), b'keep player')
        self.assertFalse((self.folder / 'profile.json').exists())

    def test_old_build_cannot_be_promoted_even_with_a_passed_build_flag(self):
        self.draft()
        path = self.build(options=False)
        with self.assertRaisesRegex(ValueError, 'Pre-option'):
            profiles.checked_build(path, self.repo)
        self.assertFalse((self.folder / 'ready.json').exists())

    def test_source_object_link_and_new_environment_guards(self):
        self.draft()
        path = self.build()
        original = json.loads(path.read_text())
        for mutate in (
            lambda b: b['native_guest_graph'].__setitem__('guest_link_edge', ''),
            lambda b: b['native_compiled_objects']['halo_frame_pacing'].__setitem__('native_ilp32_flags', False),
            lambda b: b['native_compiled_objects']['metal_render_scale'].__setitem__('additional_linked_symbols', []),
            lambda b: b.__setitem__('no_angle_gl_linkage_or_imports', False),
            lambda b: b.__setitem__('display_options', 1),
        ):
            bad = json.loads(json.dumps(original)); mutate(bad); write_json(path, bad)
            with self.assertRaises(ValueError):
                profiles.checked_build(path, self.repo)
        write_json(path, original)
        current = self.repo / 'port/linux/src/halo_frame_pacing.c'
        current.write_text('changed after build')
        with self.assertRaisesRegex(ValueError, 'drift'):
            profiles.checked_build(path, self.repo)

    def test_exact_ready_proof_and_launcher_no_game_is_executed(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        ready = profiles.promote(self.folder, build, runtime)
        self.assertTrue(ready['experiment_ready'])
        self.assertFalse(ready['manual_input_audio_gate'])
        self.assertFalse(ready['achieved_render_fps_gate'])
        self.assertFalse(ready['performance_improvement_gate'])
        profiles.verify_profile(self.folder, True)
        launcher = self.folder / 'Launch Native Metal.command'
        subprocess.run(['zsh', '-n', str(launcher)], check=True, capture_output=True)
        text = launcher.read_text()
        self.assertIn('--require-ready', text)
        self.assertIn('-u HALO_NO_AUDIO', text)
        self.assertNotIn('MTL_DEBUG_LAYER=', text)
        self.assertIn('HALO_WINDOWED=1', text)
        self.assertIn("'" + str((self.folder / 'saves').resolve()) + "'", text)
        launcher.write_text(text + '\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'Launcher changed'):
            profiles.verify_profile(self.folder, True)

    def test_runtime_wrong_map_cap_height_exit_or_short_run_reject_atomically(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        base = json.loads(runtime.read_text())
        cases = [
            ('map', 'damnation'), ('actual_host_returncode', 1), ('actual_guest_returncode', False),
            ('api_validation_enabled', False), ('renderer_api_errors', ['validation error']),
        ]
        for key, value in cases:
            bad = json.loads(json.dumps(base)); bad[key] = value; write_json(runtime, bad)
            with self.assertRaises(ValueError):
                profiles.promote(self.folder, build, runtime)
            self.assertFalse((self.folder / 'ready.json').exists())
            self.assertFalse((self.folder / 'Launch Native Metal.command').exists())
        bad = json.loads(json.dumps(base)); bad['display']['frame_limit'] = 120; write_json(runtime, bad)
        with self.assertRaises(ValueError): profiles.promote(self.folder, build, runtime)
        write_json(runtime, base)
        execution = Path(base['execution']['file'])
        e = json.loads(execution.read_text()); e['elapsed_seconds'] = 1; write_json(execution, e)
        base['execution'] = profiles.descriptor(execution); write_json(runtime, base)
        with self.assertRaisesRegex(ValueError, 'at least15'): profiles.promote(self.folder, build, runtime)

    def test_runtime_capture_proves_physical_dimensions(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        r = json.loads(runtime.read_text())
        capture = Path(r['render_capture']['file']); raw = bytearray(capture.read_bytes())
        struct.pack_into('<i', raw, 22, -480); capture.write_bytes(raw)
        r['render_capture'] = profiles.descriptor(capture); write_json(runtime, r)
        with self.assertRaisesRegex(ValueError, 'physical render dimensions'):
            profiles.promote(self.folder, build, runtime)

    def test_runtime_environment_override_or_truncated_capture_cannot_be_ready(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        record = json.loads(runtime.read_text())
        capture = Path(record['render_capture']['file'])
        capture.write_bytes(capture.read_bytes()[:54])
        record['render_capture'] = profiles.descriptor(capture); write_json(runtime, record)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            profiles.promote(self.folder, build, runtime)
        runtime = self.runtime(build)
        record = json.loads(runtime.read_text())
        execution = Path(record['execution']['file'])
        e = json.loads(execution.read_text())
        e['environment_overrides']['HALO_NO_AUDIO'] = '1'
        write_json(execution, e)
        record['execution'] = profiles.descriptor(execution); write_json(runtime, record)
        with self.assertRaisesRegex(ValueError, 'via environment'):
            profiles.promote(self.folder, build, runtime)
        self.assertFalse((self.folder / 'ready.json').exists())

    def test_new_application_environment_variable_in_proof_is_rejected(self):
        self.draft()
        path = self.build()
        proof = json.loads(path.read_text())
        relative = 'port/linux/src/port_config.c'
        current, frozen = self.repo / relative, self.repo / proof['source_snapshot'] / relative
        changed = current.read_text().replace('"0", NULL', '"0", "HALO_FRAME_LIMIT"')
        current.write_text(changed); frozen.write_text(changed)
        for item in proof['source_bindings']:
            if item['path'] == relative: item['sha256'] = profiles.sha(current)
        write_json(path, proof)
        with self.assertRaisesRegex(ValueError, 'new environment variable'):
            profiles.checked_build(path, self.repo)

    def test_user_changed_profile_config_is_preserved_and_verification_stops(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        profiles.promote(self.folder, build, runtime)
        config = self.folder / 'saves/config.toml'
        changed = config.read_text().replace('frame_limit = 60', 'frame_limit = 120')
        config.write_text(changed)
        with self.assertRaisesRegex(ValueError, 'display mismatch'):
            profiles.verify_profile(self.folder, True)
        self.assertEqual(config.read_text(), changed)

    def test_game_default_insertion_and_human_preferences_do_not_block_second_launch(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        profiles.promote(self.folder, build, runtime)
        initial = self.folder / 'initial-config.toml'
        before_initial = initial.read_bytes()
        ready_before = (self.folder / 'ready.json').read_bytes()
        config = self.folder / 'saves/config.toml'
        text = config.read_text()
        text = profiles.set_key(text, 'audio', 'music_volume', '0.25')
        text = profiles.set_key(text, 'audio', 'volume', '0.0')
        text = profiles.set_key(text, 'display', 'timer_scale', '1.0')
        text = profiles.set_key(text, 'input', 'mouse_sensitivity', '2.5')
        text = profiles.set_key(text, 'input', 'invert_mouse', 'true')
        text = profiles.set_key(text, 'bindings', 'move_forward', '"Up"')
        text = profiles.set_key(text, 'bindings', 'fire', '""')
        config.write_text('# retained game-owned settings\n' + text)
        self.assertNotEqual(profiles.sha(config), profiles.sha(initial))
        profiles.verify_profile(self.folder, True)
        profiles.verify_profile(self.folder, True)
        self.assertEqual(initial.read_bytes(), before_initial)
        self.assertEqual((self.folder / 'ready.json').read_bytes(), ready_before)
        self.assertEqual(config.read_text(), '# retained game-owned settings\n' + text)

    def test_mutable_config_rejects_changed_display_debug_network_and_bad_human_values(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        profiles.promote(self.folder, build, runtime)
        config = self.folder / 'saves/config.toml'
        text = config.read_text()
        mutations = (
            ('display', 'frame_limit', '120'), ('display', 'render_height', '1080'),
            ('display', 'interpolation', 'false'), ('display', 'vsync', 'true'),
            ('debug', 'test_input', '"bot:0"'), ('debug', 'exit_after', '20.0'),
            ('network', 'online', 'true'), ('update', 'auto', 'true'),
            ('audio', 'enabled', 'false'), ('audio', 'volume', '-1.0'),
            ('audio', 'music_volume', 'nan'), ('input', 'mouse_sensitivity', '1e-20'),
            ('input', 'invert_mouse', '"yes"'), ('bindings', 'fire', '42'))
        for section, key, value in mutations:
            changed = profiles.set_key(text, section, key, value)
            config.write_text(changed)
            with self.assertRaises(ValueError, msg=(section, key)):
                profiles.verify_profile(self.folder, True)
            self.assertEqual(config.read_text(), changed)
        config.write_text(text)
        profiles.verify_profile(self.folder, True)

    def test_initial_config_provenance_and_isolated_active_path_are_still_strict(self):
        self.template.write_text(TEMPLATE + '[paths]\ndata = ""\nsaves = ""\n')
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        profiles.promote(self.folder, build, runtime)
        config = self.folder / 'saves/config.toml'
        text = config.read_text()
        for key in ('data', 'saves'):
            config.write_text(profiles.set_key(text, 'paths', key, '"/different/path"'))
            with self.assertRaisesRegex(ValueError, 'path setting changed'):
                profiles.verify_profile(self.folder, True)
        config.unlink()
        config.symlink_to(self.folder / 'initial-config.toml')
        with self.assertRaisesRegex(ValueError, 'escapes isolated saves'):
            profiles.verify_profile(self.folder, True)
        config.unlink(); config.write_text(text)
        (self.folder / 'initial-config.toml').write_text(text + '\n# changed provenance\n')
        with self.assertRaisesRegex(ValueError, 'Stale file'):
            profiles.verify_profile(self.folder, True)

    def test_runtime_evidence_cannot_share_mutable_human_config(self):
        self.draft()
        build = self.build(); runtime = self.runtime(build)
        evidence = json.loads(runtime.read_text())
        evidence['test_config'] = profiles.descriptor(self.folder / 'saves/config.toml')
        execution = Path(evidence['execution']['file'])
        observed = json.loads(execution.read_text())
        observed['environment_overrides']['HALO_SAVE_ROOT'] = str((self.folder / 'saves').resolve())
        write_json(execution, observed)
        evidence['execution'] = profiles.descriptor(execution)
        write_json(runtime, evidence)
        with self.assertRaisesRegex(ValueError, 'isolated from mutable'):
            profiles.promote(self.folder, build, runtime)
        self.assertFalse((self.folder / 'ready.json').exists())
        self.assertFalse((self.folder / 'Launch Native Metal.command').exists())

    def test_runtime_launch_log_tampering_or_identity_mismatch_rejects_atomically(self):
        self.draft()
        build_path = self.build(); runtime_path = self.runtime(build_path)
        build = profiles.checked_build(build_path, self.repo)
        values = json.loads((self.folder / 'profile.json').read_text())['profile']
        evidence = json.loads(runtime_path.read_text())
        log = Path(evidence['launch_log']['file'])
        original_log = log.read_bytes()
        log.write_bytes(original_log + b'changed after proof\n')
        for validate in (
                lambda: profiles.checked_runtime(runtime_path, values, build),
                lambda: profiles.promote(self.folder, build_path, runtime_path)):
            with self.assertRaisesRegex(ValueError, 'Stale file'):
                validate()
        log.write_bytes(original_log)
        other = self.base / 'different-valid.log'
        other.write_bytes(original_log)
        evidence['launch_log'] = profiles.descriptor(other)
        write_json(runtime_path, evidence)
        profiles.checked_descriptor(evidence['launch_log'])
        for validate in (
                lambda: profiles.checked_runtime(runtime_path, values, build),
                lambda: profiles.promote(self.folder, build_path, runtime_path)):
            with self.assertRaisesRegex(ValueError, 'launch log identity mismatch'):
                validate()
        self.assertFalse((self.folder / 'ready.json').exists())
        self.assertFalse((self.folder / 'Launch Native Metal.command').exists())

    def test_chooser_uses_only_ready_exact_profiles_and_never_overwrites(self):
        self.draft()
        output = self.base / 'human chooser'
        with self.assertRaises(FileNotFoundError): profiles.chooser(output, [self.folder])
        self.assertFalse(output.exists())
        build = self.build(); runtime = self.runtime(build)
        profiles.promote(self.folder, build, runtime)
        with self.assertRaisesRegex(ValueError, 'Duplicate'): profiles.chooser(output, [self.folder, self.folder])
        self.assertFalse(output.exists())
        menu = profiles.chooser(output, [self.folder])
        self.assertFalse(menu['process_launched'])
        path = output / 'Choose Native Metal Playtest.command'
        subprocess.run(['zsh', '-n', str(path)], check=True, capture_output=True)
        before = path.read_bytes()
        with self.assertRaises(ValueError): profiles.chooser(output, [self.folder])
        self.assertEqual(path.read_bytes(), before)

    def test_missing_asset_or_muted_template_rejected_before_destination_creation(self):
        self.template.write_text(TEMPLATE.replace('mouse_sensitivity = 1.0', 'mouse_sensitivity = 1e-20'))
        with self.assertRaises(ValueError): self.draft()
        self.assertFalse(self.folder.exists())
        self.template.write_text(TEMPLATE)
        (self.assets / 'maps/ui.map').unlink()
        with self.assertRaises(FileNotFoundError): self.draft()
        self.assertFalse(self.folder.exists())


if __name__ == '__main__':
    unittest.main()
