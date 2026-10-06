"""Pure data tests for performance sampling; never launch Halo or change settings."""

import csv
import json
import subprocess
from types import SimpleNamespace
import tempfile
from pathlib import Path
import plistlib
import tomllib
import unittest
from unittest.mock import patch

try:
    from tools import macos_renderer_benchmark as benchmark
except ImportError:
    import macos_renderer_benchmark as benchmark


class SamplingTests(unittest.TestCase):
    def test_exit_during_foreground_observation_is_not_focus_loss(self):
        process = SimpleNamespace(pid=123, returncode=None)
        process.poll = lambda: process.returncode
        def observe(pid):
            self.assertEqual(pid, process.pid)
            self.assertIsNone(process.poll())
            process.returncode = 0
            return dict(active=False, frontmost_name="Codex", target_active=None)
        samples = []
        with patch.object(benchmark, "foreground", side_effect=observe):
            self.assertFalse(benchmark.record_foreground_check(process, 0, samples))
        self.assertEqual(samples, [])

    def test_focus_loss_while_game_is_alive_still_fails(self):
        process = SimpleNamespace(pid=123, poll=lambda: None)
        samples = []
        with patch.object(benchmark, "foreground", return_value=dict(active=False, frontmost_name="Codex")):
            with self.assertRaisesRegex(RuntimeError, "lost foreground"):
                benchmark.record_foreground_check(process, 0, samples)
        self.assertEqual(len(samples), 1)

    def test_foreground_identity_requires_the_selected_pid(self):
        for app_active, frontmost_pid, expected in ((True, 617, False), (False, 123, True)):
            response = dict(target_active=app_active, frontmost_pid=frontmost_pid,
                            frontmost_name="loginwindow" if frontmost_pid == 617 else "Halo OG",
                            activation_returned=None)
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(response), stderr="")
            with patch.object(benchmark.subprocess, "run", return_value=completed):
                result = benchmark.foreground_observation(123)
            self.assertIs(result["active"], expected)
            self.assertIs(result["target_active"], app_active)
            self.assertEqual(result["frontmost_pid"], frontmost_pid)
            self.assertEqual(json.loads(result["stdout"]), response)

    def test_locked_session_error_is_specific_and_does_not_assume_a_renderer_failure(self):
        observation = dict(active=False, frontmost_pid=617, frontmost_name="loginwindow")
        self.assertIn("unlock the active user session", benchmark.foreground_error(observation, startup=True))
        self.assertIn("unlock the active user session", benchmark.foreground_error(observation))
        self.assertIn("lost foreground", benchmark.foreground_error(dict(frontmost_name="Codex")))

    def test_activation_waits_for_asynchronous_foreground_transition(self):
        pending = dict(active=False, activation_returned=True, stdout='{"active":false}',
                       command_returncode=0, stderr="")
        active = dict(active=True, activation_returned=None, stdout='{"active":true}',
                      command_returncode=0, stderr="")
        with patch.object(benchmark, "foreground_observation", side_effect=[pending, active]) as observer, \
                patch.object(benchmark.time, "sleep"):
            result = benchmark.foreground(123, activate=True)
        self.assertTrue(result["active"])
        self.assertTrue(result["activation_returned"])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(observer.call_args_list[0].args, (123, True))
        self.assertEqual(observer.call_args_list[1].args, (123,))

    def test_regular_foreground_check_does_not_reactivate_lost_focus(self):
        inactive = dict(active=False, activation_returned=None, stdout='{"active":false}',
                        command_returncode=0, stderr="")
        with patch.object(benchmark, "foreground_observation", return_value=inactive) as observer:
            result = benchmark.foreground(123)
        self.assertFalse(result["active"])
        self.assertEqual(observer.call_count, 1)

    def test_native_excludes_startup_and_discontinuous_or_backwards_samples(self):
        rows = [dict(frame=1, ns=1_000_000_000, tick=149, initialized=True),
                dict(frame=2, ns=2_000_000_000, tick=150, initialized=True),
                dict(frame=3, ns=2_010_000_000, tick=150, initialized=True),
                dict(frame=4, ns=2_030_000_000, tick=151, initialized=True),
                dict(frame=6, ns=2_040_000_000, tick=151, initialized=True),
                dict(frame=7, ns=2_020_000_000, tick=152, initialized=True)]
        result = benchmark.native_summary(rows)
        self.assertEqual(result["interval_count"], 2)
        self.assertEqual(result["discarded_nonconsecutive_intervals"], 2)
        self.assertAlmostEqual(result["render_fps"], 2000 / 30)
        self.assertAlmostEqual(result["observed_simulation_hz"], 1000 / 30)
        self.assertEqual(result["p50_ms"], 15)
        self.assertEqual(result["p95_ms"], 19.5)

    def test_native_empty_or_uninitialized_samples_are_not_success(self):
        rows = [dict(frame=1, ns=1, tick=151, initialized=False),
                dict(frame=2, ns=2, tick=152, initialized=False)]
        with self.assertRaisesRegex(ValueError, "No valid"):
            benchmark.native_summary(rows)

    def test_angle_excludes_wall_warmup_and_empty_draws(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "frames.csv"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["frame_ms", "draws", "upload_bytes", "draw_ms", "swap_ms", "footprint_mb"])
                writer.writeheader()
                for interval, draws in ((1000, 1), (1000, 0), (10, 5), (20, 6)):
                    writer.writerow(dict(frame_ms=interval, draws=draws, upload_bytes=100, draw_ms=2,
                                         swap_ms=4, footprint_mb=30))
            result = benchmark.angle_summary(path, 2)
        self.assertEqual(result["interval_count"], 2)
        self.assertEqual(result["p50_ms"], 15)
        self.assertIsNone(result["observed_simulation_hz"])
        self.assertEqual(result["mean_draws"], 5.5)

    def test_parse_old_and_new_host_fields_and_resolution(self):
        metric = ("Native Metal host metrics: 60 frames, 180 submits, 300 draws, 400 bytes; "
                  "packet-copy 5 us, prepare 6 us, encode 7 us, drawable-wait 8 us, commit 9 us, "
                  "completion-wait 10 us, gpu 11 us/12 samples; packet-buffers 13, sampler-hits 14, "
                  "sampler-misses 15, sampler-allocations 16, sampler-cache 17, upload-buffers 18, visibility-buffers 19")
        log = ("Renderer active: Native Metal; changes apply on next launch\n"
               "Native timing: frame 100, monotonic 1000000000 ns, tick 200, initialized 1\n"
               + metric + "\n" + metric + "; render-passes 20\n"
               + metric + ", render-passes 21\n"
               "Native display: 60.000 FPS, 30.000 simulation Hz, 3600x2338 storage, 738x480 logical, cap 0, interpolation 1, ticks 200-230\n"
               "screen: 738x480 drawn at 3600x2338\nGame exited (0)\n")
        parsed = benchmark.parse_log(log)
        self.assertEqual(parsed["parse_errors"], [])
        self.assertEqual([row["render_passes"] for row in parsed["host_metrics"]], [None, 20, 21])
        self.assertEqual(parsed["display_telemetry"][0]["storage_height"], 2338)
        self.assertEqual(parsed["angle_sizes"][0]["logical_height"], 480)
        self.assertEqual(parsed["guest_exit_records"], [0])

    def test_optional_shader_metrics_preserve_old_prefix_and_render_pass_suffix(self):
        prefix = ("Native Metal host metrics: 60 frames, 180 submits, 300 draws, 400 bytes; "
                  "packet-copy 5 us, prepare 6 us, encode 7 us, drawable-wait 8 us, commit 9 us, "
                  "completion-wait 10 us, gpu 11 us/12 samples; packet-buffers 13, sampler-hits 14, "
                  "sampler-misses 15, sampler-allocations 16, sampler-cache 17, upload-buffers 18, visibility-buffers 19")
        suffix = (", shader-compile-hits 21, shader-compile-misses 22, shader-compile-us 23, "
                  "shader-function-cache 24, shader-function-source-bytes 2500")
        parsed = benchmark.parse_log("\n".join((prefix, prefix + ", render-passes 20", prefix + ", render-passes 20" + suffix)))
        self.assertEqual(parsed["parse_errors"], [])
        self.assertEqual(len(parsed["host_metrics"]), 3)
        for row in parsed["host_metrics"][:2]:
            self.assertIsNone(row["shader_compile_hits"])
            self.assertIsNone(row["shader_function_cache"])
        row = parsed["host_metrics"][2]
        self.assertEqual(row["render_passes"], 20)
        self.assertEqual(row["shader_compile_hits"], 21)
        self.assertEqual(row["shader_compile_misses"], 22)
        self.assertEqual(row["shader_compile_us"], 23)
        self.assertEqual(row["shader_function_cache"], 24)
        self.assertEqual(row["shader_function_source_bytes"], 2500)

    def test_shader_counters_sum_intervals_while_cache_gauges_keep_last_and_max(self):
        timings = [dict(frame=frame, ns=frame * 16_666_667, tick=frame, initialized=True)
                   for frame in range(1, 401)]
        rows = []
        for frame, hits, misses, compile_us, entries, source_bytes in (
                (250, 3, 1, 100, 40, 4000), (350, 5, 2, 300, 20, 2500)):
            row = {key: 60 for key in benchmark.HOST_KEYS}
            row.update(preceding_timing=timings[frame - 1], shader_compile_hits=hits,
                       shader_compile_misses=misses, shader_compile_us=compile_us,
                       shader_function_cache=entries, shader_function_source_bytes=source_bytes)
            rows.append(row)
        totals = benchmark.aggregate_host_metrics(rows, timings)
        self.assertEqual(totals["shader_compile_hits"], 8)
        self.assertEqual(totals["shader_compile_misses"], 3)
        self.assertEqual(totals["shader_compile_us"], 400)
        self.assertAlmostEqual(totals["shader_compile_hits_per_frame"], 8 / 120)
        self.assertAlmostEqual(totals["shader_compile_us_per_frame"], 400 / 120)
        self.assertEqual(totals["shader_function_cache_last"], 20)
        self.assertEqual(totals["shader_function_cache_max"], 40)
        self.assertEqual(totals["shader_function_source_bytes_last"], 2500)
        self.assertEqual(totals["shader_function_source_bytes_max"], 4000)
        self.assertNotIn("shader_function_cache", totals)
        self.assertNotIn("shader_function_source_bytes", totals)
        self.assertNotIn("shader_function_cache_per_frame", totals)

    def test_malformed_timings_and_faults_survive_collection(self):
        result = benchmark.parse_log("Native timing: broken\nNative unsupported opcode\nGame exited (1)\n")
        self.assertEqual(len(result["parse_errors"]), 1)
        self.assertEqual(result["faults"], ["Native unsupported opcode"])
        self.assertEqual(result["guest_exit_records"], [1])

    def test_host_block_warmup_is_frame_based_even_at_fifteen_fps(self):
        rows = [dict(frame=frame, ns=frame * 66_666_667, tick=frame * 2, initialized=True)
                for frame in range(1, 201)]
        def block(frame):
            value = {key: 60 for key in benchmark.HOST_KEYS}
            value["preceding_timing"] = rows[frame - 1]
            return value
        result = benchmark.aggregate_host_metrics([block(100), block(200)], rows)
        self.assertEqual(result["blocks"], 1)
        self.assertEqual(result["frames"], 60)
        self.assertEqual(result["render_passes_per_frame"], 1)

    def test_isolated_config_keeps_gameplay_and_original_assets(self):
        config = tomllib.loads(benchmark.controlled_config("metal", 40, 2323, 0, 120, True, "fxaa", "look:0"))
        self.assertFalse(config["network"]["online"])
        self.assertFalse(config["update"]["auto"])
        self.assertFalse(config["display"]["high_res_hud"])
        self.assertTrue(config["display"]["interpolation"])
        self.assertEqual(config["display"]["render_height"], 0)
        self.assertEqual(config["debug"]["screenshot_every"], 0)
        self.assertEqual(config["debug"]["test_input"], "look:0")
        self.assertTrue(config["bindings"])
        self.assertTrue(all(value == "" for value in config["bindings"].values()))

    def test_original_rendering_reference_can_disable_existing_interpolation_for_either_renderer(self):
        for renderer in ("metal", "angle"):
            original = tomllib.loads(benchmark.controlled_config(renderer, 30, 2323, 0, 30,
                                                                 True, "off", "look:0", interpolation=False))
            smooth = tomllib.loads(benchmark.controlled_config(renderer, 30, 2323, 0, 60,
                                                               True, "off", "look:0", interpolation=True))
            self.assertIs(original["display"]["interpolation"], False)
            self.assertEqual(original["display"]["frame_limit"], 30)
            self.assertIs(smooth["display"]["interpolation"], True)
            self.assertEqual(smooth["display"]["frame_limit"], 60)
            for config in (original, smooth):
                self.assertEqual(config["display"]["renderer"], renderer)
                self.assertFalse(config["network"]["online"])
                self.assertFalse(config["display"]["high_res_hud"])
                self.assertEqual(config["debug"]["screenshot_every"], 0)

    def test_launch_overrides_remove_inherited_debug_keys_without_recording_secrets(self):
        environment, overrides, removed = benchmark.sanitized_environment(Path("/tmp/bench"), "metal",
            {"HALO_NETWORK_TEST": "inherited", "MTL_DEBUG_LAYER": "1", "DYLD_INSERT_LIBRARIES": "inherited",
             "MallocStackLogging": "1", "PATH": "/bin", "TOKEN": "private"})
        self.assertEqual(removed, ["DYLD_INSERT_LIBRARIES", "HALO_NETWORK_TEST", "MTL_DEBUG_LAYER", "MallocStackLogging"])
        self.assertEqual(environment["TOKEN"], "private")
        self.assertEqual(overrides["HALO_SAVE_ROOT"], "/tmp/bench/saves")
        self.assertNotIn("HALO_PERF_LOG", overrides)
        self.assertNotIn("TOKEN", overrides)

    def test_freeze_packaged_pair_preserves_relative_library_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            app = folder / "Halo OG.app"
            host = app / "Contents/MacOS/halo-metal"
            library = app / "Contents/Frameworks/libSDL3.0.dylib"
            guest = app / "Contents/Resources/halo_metal_guest.elf"
            for path, data in ((host, b"host"), (library, b"library"), (guest, b"guest")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            primary = host.parent / "halo"
            primary.write_bytes(b"unselected primary")
            with (app / "Contents/Info.plist").open("wb") as stream:
                plistlib.dump(dict(CFBundleIdentifier="original.halo", CFBundleExecutable="halo",
                                  CFBundleURLTypes=[dict(CFBundleURLSchemes=["halo-og"])]), stream)
            host.chmod(0o755)
            output = folder / "output"
            output.mkdir()
            result = benchmark.freeze_pair(output, host, guest)
            frozen_host = Path(result["host"]["file"])
            self.assertEqual((frozen_host.parent.parent / "Frameworks/libSDL3.0.dylib").read_bytes(), b"library")
            self.assertEqual(result["source_host"]["sha256"], result["host"]["sha256"])
            self.assertEqual(result["source_guest"]["sha256"], result["guest"]["sha256"])
            self.assertEqual(len(result["bundled_dependencies"]), 1)
            info = plistlib.loads((frozen_host.parent.parent / "Info.plist").read_bytes())
            self.assertEqual(info["CFBundleExecutable"], "halo-metal")
            self.assertTrue(info["CFBundleIdentifier"].startswith("local.halo.renderer-benchmark."))
            self.assertNotIn("CFBundleURLTypes", info)
            self.assertFalse((frozen_host.parent / "halo").exists())
            self.assertFalse(result["whole_app_signature_preserved"])
            self.assertFalse(result["binary_resigned"])
            self.assertEqual(info["LSEnvironment"]["HALO_SAVE_ROOT"], str(output.resolve() / "saves"))
            self.assertEqual((frozen_host.parent.parent / "Resources/halo_guest-metal.elf").read_bytes(), b"guest")
            host.write_bytes(b"changed")
            self.assertEqual(frozen_host.read_bytes(), b"host")

    def test_raw_hosts_have_distinct_private_identities_and_exact_executable_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            host, guest = folder / "halo", folder / "halo_guest.elf"
            host.write_bytes(b"unchanged executable")
            host.chmod(0o755)
            guest.write_bytes(b"selected guest")
            identifiers = []
            for name in ("before", "after"):
                output = folder / name
                output.mkdir()
                result = benchmark.freeze_pair(output, host, guest)
                frozen_host = Path(result["host"]["file"])
                info = plistlib.loads((frozen_host.parent.parent / "Info.plist").read_bytes())
                self.assertEqual(frozen_host.relative_to(output.resolve()).parts[:3],
                                 ("frozen", "Halo Renderer Benchmark.app", "Contents"))
                self.assertEqual(info["CFBundleExecutable"], host.name)
                self.assertEqual(info["CFBundlePackageType"], "APPL")
                self.assertTrue(info["NSHighResolutionCapable"])
                self.assertNotIn("CFBundleURLTypes", info)
                self.assertEqual(result["source_host"]["sha256"], result["host"]["sha256"])
                self.assertEqual(result["source_guest"]["sha256"], result["guest"]["sha256"])
                self.assertIn("External libraries were not frozen", result["dependency_scope"])
                identifiers.append(info["CFBundleIdentifier"])
            self.assertNotEqual(identifiers[0], identifiers[1])


if __name__ == "__main__":
    unittest.main()
