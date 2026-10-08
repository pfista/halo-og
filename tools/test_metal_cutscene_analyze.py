"""Synthetic diagnostic tests. Never launch Halo or write game settings."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

try:
    from tools import metal_cutscene_analyze as analyzer
except ImportError:
    import metal_cutscene_analyze as analyzer


def timing(frame, ns, tick=150, initialized=1):
    return f"Native timing: frame {frame}, monotonic {ns} ns, tick {tick}, initialized {initialized}"


def scene(frame, cinematic=1, player_input=0):
    return f"Native scene: frame {frame}, cinematic {cinematic}, player-input {player_input}"


def guest_work(frame, draws=5, expansion=10, textures=20, state=30, program_ns=40, emit=50, submit=100):
    return (f"Native guest work: frame {frame}, draws {draws}, expansion {expansion} ns, textures {textures} ns, "
            f"state {state} ns, program {program_ns} ns, emit {emit} ns, submit {submit} ns")


def flush(frame, sequence, reason="present", commands=10, size=100, start=1000, duration=100):
    return (f"Native flush: frame {frame}, sequence {sequence}, reason {reason}, commands {commands}, bytes {size}, "
            f"start {start} ns, end {start + duration} ns, submit {duration} ns")


def packet(sequence, **changes):
    values = dict(commands=10, size=100, start=9_000_000_000_000_000_001, duration=100,
                  copy=2, prepare=90, encode=3, drawable=1, commit=1, completion=80, gpu=70,
                  shader_misses=0, shader_compile=0, pipelines=0, pipeline_create=0,
                  draws=5, passes=2, copies=1)
    values.update(changes)
    return (f"Native Metal packet: sequence {sequence}, commands {values['commands']}, bytes {values['size']}, "
            f"start {values['start']} ns, end {values['start'] + values['duration']} ns, copy {values['copy']} ns, "
            f"prepare {values['prepare']} ns, encode {values['encode']} ns, drawable {values['drawable']} ns, "
            f"commit {values['commit']} ns, completion {values['completion']} ns, gpu {values['gpu']} ns, "
            f"shader-misses {values['shader_misses']}, shader-compile {values['shader_compile']} ns, "
            f"pipelines {values['pipelines']}, pipeline-create {values['pipeline_create']} ns, "
            f"draws {values['draws']}, passes {values['passes']}, subresource-copies {values['copies']}")


def compile_event(sequence, stage="vertex", success=1, start=900, duration=80):
    return (f"Native Metal compile: sequence {sequence}, stage {stage}, source-bytes 220, fast 1, invariant 0, "
            f"start {start} ns, end {start + duration} ns, duration {duration} ns, success {success}")


def compile_identity(sequence, stage="vertex", start=900, program_id=12, command_index=0, source_hash="ffffffffffffffff"):
    return (f"Native Metal compile identity: sequence {sequence}, command-index {command_index}, "
            f"program {program_id}, generation 1, stage {stage}, source-hash {source_hash}, start {start} ns")


def pipeline_event(sequence, command_index=1, start=400, duration=60, success=1):
    return (f"Native Metal pipeline: sequence {sequence}, command-index {command_index}, program 12, generation 1, "
            "vertex-hash ffffffffffffffff, fragment-hash abcdef0123456789, packed 0000ff00, "
            "color-format 80, depth-format 260, color-mask 7, blend 1/7/2/1, "
            f"start {start} ns, end {start + duration} ns, duration {duration} ns, success {success}")


def camera_point(tick=150, render_frame=9999, name="pelican, initial pan"):
    return (f"Native camera: tick {tick}, render-frame {render_frame}, kind point, point 7, "
            f"name {name}, transition 30, relative -1")


def camera_animation(tick=151):
    return (f"Native camera: tick {tick}, render-frame 10000, kind animation, graph 123, animation 2, "
            "name beach arrival, frames 120")


def program(frame, sequence, command_index=0, texture_modes="00abcdef"):
    return (f"Native program: frame {frame}, sequence {sequence}, command-index {command_index}, program 12, "
            "vertex-object 4, vertex-handle 00000000, declaration-object 8, loaded-slot 9, instructions 11, "
            f"packed 000000ff, texture-modes {texture_modes}, samplers 0/1/2/3, alpha-border 2, volume-border 4, "
            "depth-contract 1, compilers 0/1, sources 220/330 bytes, translation 30 ns")


class CutsceneLogTests(unittest.TestCase):
    def analyze(self, *lines, **options):
        return analyzer.analyze_log("\n".join(lines), include_frames=True, **options)

    def test_sequence_join_offset_multiple_packets_and_overlapping_counters(self):
        result = self.analyze(timing(1, 8_000_000_000_000_000_001, tick=149),
            packet(42, shader_misses=1, shader_compile=80, pipelines=1, pipeline_create=20),
            compile_event(42), program(1, 42), flush(1, 42, "visibility-collect"),
            packet(43), flush(1, 43), timing(2, 8_000_000_000_060_000_001, tick=151), scene(2))
        frame = result["frames"][1]
        self.assertEqual(frame["present_gap_ns"], 60_000_000)
        self.assertEqual(frame["frame"], 2)
        self.assertEqual(frame["guest_frame"], 1)
        self.assertEqual(frame["reasons"], {"visibility-collect": 1, "present": 1})
        self.assertEqual([row["sequence"] for row in frame["packets"]], [42, 43])
        self.assertEqual(frame["packets"][0]["host"]["start_ns"], 9_000_000_000_000_000_001)
        self.assertEqual(frame["packets"][0]["programs"][0]["texture_modes"], 0xABCDEF)
        self.assertEqual(frame["totals"]["prepare_ns"], 180)
        self.assertEqual(frame["totals"]["completion_wait_ns"], 160)
        self.assertEqual(frame["totals"]["gpu_ns"], 140)
        self.assertEqual(frame["totals"]["host_packet_ns"], 200)
        self.assertEqual(frame["totals"]["shader_compile_ns"], 80)
        self.assertEqual(frame["totals"]["pipeline_create_ns"], 20)
        self.assertNotIn("exclusive_ns", frame["totals"])
        self.assertFalse(frame["after_startup"])
        self.assertEqual(frame["tick_delta"], 2)
        self.assertEqual(frame["scene_state"], "cinematic")
        self.assertEqual(result["summary"]["all_gaps"]["catchup_intervals"], 1)

    def test_cache_warmth_is_independent_of_tick_startup_and_scene_state(self):
        result = self.analyze(timing(1, 100_000_000), packet(1), flush(0, 1), scene(1),
            timing(2, 120_000_000), packet(2, pipelines=1, pipeline_create=90), flush(1, 2), scene(2),
            timing(3, 130_000_000), packet(3), flush(2, 3), scene(3, 0, 1),
            timing(4, 200_000_000), flush(3, 4), scene(4, 0, 0))
        self.assertEqual([row["cache_state"] for row in result["frames"]], ["warm", "cold", "warm", "unknown"])
        self.assertTrue(result["frames"][1]["cold_pipeline"])
        self.assertFalse(result["frames"][1]["cold_shader"])
        self.assertEqual(result["summary"]["post_startup_by_cache_state"]["cold"]["gaps"]["interval_count"], 1)
        self.assertEqual(result["summary"]["by_scene"]["input-enabled"]["frame_count"], 1)
        self.assertEqual(result["summary"]["by_scene"]["input-disabled"]["frame_count"], 1)
        self.assertEqual(result["diagnostics"]["missing_host_sequences"], [4])

    def test_duplicates_are_not_silently_joined(self):
        result = self.analyze(timing(1, 10), timing(2, 20), packet(5), packet(5), flush(1, 5),
            packet(6), flush(1, 6), flush(1, 6), packet(7), flush(1, 7))
        frame = result["frames"][1]
        self.assertEqual(frame["cache_state"], "unknown")
        self.assertFalse(frame["packet_coverage_complete"])
        self.assertEqual(len(result["diagnostics"]["duplicate_sequences"]), 2)
        self.assertIsNone(frame["packets"][0]["host"])
        self.assertEqual(result["diagnostics"]["orphan_host_sequences"], [6])
        self.assertIn(6, result["diagnostics"]["unattributed_flush_sequences"])

    def test_mismatched_packet_and_program_records_are_explicit(self):
        result = self.analyze(timing(1, 10), packet(1, size=101, commands=9), flush(0, 1),
                              program(1, 1), program(0, 1, command_index=10))
        self.assertEqual(len(result["diagnostics"]["packet_mismatches"]), 2)
        self.assertEqual(len(result["diagnostics"]["record_errors"]), 2)
        self.assertEqual(result["frames"][0]["cache_state"], "unknown")
        self.assertEqual(result["frames"][0]["totals"]["programs"], 0)
        self.assertEqual(len(result["diagnostics"]["unattributed_program_lines"]), 2)

    def test_malformed_and_incomplete_evidence_survives(self):
        result = self.analyze("halo-linux: " + timing(1, 10), "Native Metal packet: broken",
            "Native flush totals: unrelated block", packet(7), compile_event(7, success=0), program(8, 7),
            flush(8, 7), scene(9), "Native program: truncated", "Native Metal compile: malformed")
        self.assertEqual(len(result["diagnostics"]["parse_errors"]), 3)
        self.assertEqual(result["counts"]["timings"], 1)
        self.assertEqual(result["diagnostics"]["unattributed_flush_sequences"], [7])
        self.assertEqual(len(result["diagnostics"]["unattributed_compile_lines"]), 1)
        self.assertEqual(len(result["diagnostics"]["unattributed_program_lines"]), 1)
        self.assertEqual(len(result["diagnostics"]["unattributed_scene_lines"]), 1)
        self.assertEqual(result["frames"][0]["cache_state"], "unknown")

    def test_discontinuous_duplicate_and_backwards_timings_do_not_become_gaps(self):
        result = self.analyze(timing(1, 10), timing(3, 20), timing(4, 15), timing(5, 30, tick=149),
            timing(6, 40), timing(6, 40), timing(7, 50), timing(8, 60))
        self.assertEqual([row["error"] for row in result["diagnostics"]["discarded_intervals"]],
                         ["nonconsecutive frame", "nonincreasing monotonic time", "backwards simulation tick"])
        self.assertEqual(len(result["diagnostics"]["duplicate_frames"]), 1)
        self.assertEqual(result["summary"]["all_gaps"]["interval_count"], 1)
        self.assertEqual(result["top_gaps"][0]["frame"], 8)

    def test_scene_false_before_initialization_is_unknown_and_top_limit_applies(self):
        result = self.analyze(timing(1, 10, initialized=0), scene(1, 0, 0),
            timing(2, 30), scene(2), timing(3, 60), scene(3, 0, 1), timing(4, 70), top=1)
        self.assertEqual(result["frames"][0]["scene_state"], "unknown")
        self.assertEqual(len(result["top_gaps"]), 1)
        self.assertEqual(result["top_gaps"][0]["frame"], 3)
        self.assertEqual(result["post_startup_top_gaps"][0]["frame"], 3)
        self.assertEqual(result["summary"]["all_gaps"]["p50_ms"], .00002)

    def test_invalid_durations_do_not_prove_warmth_and_compile_failures_remain_visible(self):
        bad_flush = flush(0, 1).replace("submit 100 ns", "submit 99 ns")
        result = self.analyze(timing(1, 100), bad_flush, packet(1))
        self.assertEqual(result["frames"][0]["cache_state"], "unknown")
        self.assertEqual(result["diagnostics"]["record_errors"][0]["error"], "invalid duration")
        cold = self.analyze(timing(1, 100), flush(0, 1), compile_event(1, success=0))
        self.assertEqual(cold["frames"][0]["cache_state"], "cold")
        self.assertEqual(cold["frames"][0]["totals"]["compile_failures"], 1)
        self.assertFalse(cold["frames"][0]["packet_coverage_complete"])

    def test_cli_reads_only_input_and_emits_json_and_refuses_input_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "host.log"
            original = "\n".join((timing(1, 10), timing(2, 20), flush(1, 1), packet(1)))
            path.write_text(original)
            command = [sys.executable, str(Path(analyzer.__file__)), str(path)]
            completed = subprocess.run(command, check=True, capture_output=True, text=True)
            result = json.loads(completed.stdout)
            self.assertEqual(result["top_gaps"][0]["frame"], 2)
            self.assertEqual(path.read_text(), original)
            self.assertNotIn("frames", result)
            output = Path(folder) / "analysis.json"
            subprocess.run(command + ["--output", str(output), "--include-frames"], check=True, capture_output=True)
            self.assertIn("frames", json.loads(output.read_text()))
            refused = subprocess.run(command + ["--output", str(path)], capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("cannot overwrite", refused.stderr)
            self.assertEqual(path.read_text(), original)
            alias = Path(folder) / "alias.log"
            os.link(path, alias)
            refused = subprocess.run(command + ["--output", str(alias)], capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(path.read_text(), original)

    def test_actual_engine_printf_formats_match_parser_contract(self):
        root = Path(analyzer.__file__).resolve().parents[1]
        guest = (root / "port/linux/src/d3d8_metal.c").read_text()
        host = (root / "port/macos/host/host_metal.mm").read_text()
        camera = (root / "source/camera/camera_scripting.c").read_text()
        for name, (marker, _) in analyzer.PATTERNS.items():
            source = (host if name in ("packets", "compiles", "compile_identities", "pipeline_events")
                      else camera if name.startswith("camera_") else guest)
            formats = re.findall(r'"(' + re.escape(marker) + r'[^"\n]+)"', source)
            if name.startswith("camera_"):
                kind = "point" if name == "camera_points" else "animation"
                formats = [text for text in formats if "kind " + kind in text]
            match = formats[0] if formats else None
            self.assertIsNotNone(match, marker)
            text = re.sub(r"%[0-9.]*s", "vertex" if name in ("compiles", "compile_identities") else "Present", match)
            text = re.sub(r"%[0-9]*(?:ll|l)?[udx]", "1", text)
            parsed = analyzer.parse_log(text)
            self.assertEqual(parsed["parse_errors"], [], marker)
            self.assertEqual(len(parsed[name]), 1, marker)
        names = re.search(r"names\[NATIVE_FLUSH_REASON_COUNT\]=\{([^}]+)\}", guest).group(1)
        for reason in re.findall(r'"([^"\n]+)"', names):
            parsed = analyzer.parse_log(flush(0, 1, reason))
            self.assertEqual(parsed["parse_errors"], [], reason)
            self.assertEqual(parsed["flushes"][0]["reason"], reason)

    def test_baseline_capture_camel_case_flush_reason_joins_exact_real_rows(self):
        # Unmodified rows from metal-cutscene-20261008/run-baseline-720p/launch.log.
        log = "\n".join((
            "Native Metal packet: sequence 1, commands 6, bytes 360, start 604712791665500 ns, end 604712861454458 ns, copy 1333 ns, prepare 59750 ns, encode 59877292 ns, drawable 973083 ns, commit 24875 ns, completion 8797958 ns, gpu 4065708 ns, shader-misses 0, shader-compile 0 ns, pipelines 0, pipeline-create 0 ns, draws 0, passes 0, subresource-copies 1",
            "halo-linux: Native flush: frame 0, sequence 1, reason Present, commands 6, bytes 360, start 604708049927000 ns, end 604708119773000 ns, submit 69846000 ns",
            "halo-linux: Native timing: frame 1, monotonic 604708119809000 ns, tick 0, initialized 0",
            "halo-linux: Native scene: frame 1, cinematic 0, player-input 0",
        ))
        result = analyzer.analyze_log(log, include_frames=True)
        self.assertEqual(result["counts"]["flushes"], 1)
        self.assertEqual(result["diagnostics"]["parse_errors"], [])
        self.assertEqual(result["diagnostics"]["orphan_host_sequences"], [])
        frame = result["frames"][0]
        self.assertEqual(frame["reasons"], {"Present": 1})
        self.assertEqual(frame["totals"]["guest_submit_ns"], 69846000)
        self.assertEqual(frame["totals"]["host_packet_ns"], 69788958)
        self.assertTrue(frame["packet_coverage_complete"])
        self.assertEqual(frame["cache_state"], "warm")
        self.assertEqual(frame["scene_state"], "unknown")

    def test_overlapping_shader_stage_durations_are_raw_attribution(self):
        result = self.analyze(timing(1, 100), flush(0, 1),
            packet(1, prepare=150, duration=200, shader_misses=2, shader_compile=200),
            compile_event(1, start=900, duration=100),
            compile_event(1, stage="fragment", start=950, duration=100))
        totals = result["frames"][0]["totals"]
        self.assertEqual(totals["compile_event_ns"], 200)
        self.assertEqual(totals["shader_compile_ns"], 200)
        self.assertEqual(totals["prepare_ns"], 150)
        self.assertEqual(result["diagnostics"]["record_errors"], [])

    def test_optional_compile_identity_joins_by_interval_without_line_order_or_length_guess(self):
        result = self.analyze(timing(1, 100), flush(0, 1), packet(1, shader_misses=2),
            compile_identity(1, start=1000, program_id=44, source_hash="abcdef0123456789"),
            compile_event(1, start=900), compile_event(1, start=1000),
            compile_identity(1, start=900, program_id=12))
        compiles = result["frames"][0]["packets"][0]["compiles"]
        self.assertEqual([row["identity"]["program"] for row in compiles], [12, 44])
        self.assertEqual(compiles[0]["identity"]["source_hash"], 2**64 - 1)
        self.assertEqual(compiles[1]["identity"]["source_hash"], 0xABCDEF0123456789)
        self.assertEqual(result["diagnostics"]["unmatched_compile_identity_lines"], [])
        old = self.analyze(timing(1, 100), flush(0, 1), packet(1), compile_event(1))
        self.assertIsNone(old["frames"][0]["packets"][0]["compiles"][0]["identity"])
        self.assertEqual(old["camera_markers"], [])

    def test_duplicate_or_unmatched_compile_identity_is_explicit_and_never_guessed(self):
        result = self.analyze(timing(1, 100), flush(0, 1), packet(1), compile_event(1),
            compile_identity(1), compile_identity(1, program_id=99), compile_identity(1, start=901),
            compile_identity(2), compile_identity(1, command_index=10))
        self.assertIsNone(result["frames"][0]["packets"][0]["compiles"][0]["identity"])
        self.assertEqual(len(result["diagnostics"]["duplicate_compile_identities"]), 1)
        self.assertEqual(len(result["diagnostics"]["unmatched_compile_identity_lines"]), 3)
        self.assertEqual(len(result["diagnostics"]["unattributed_compile_identity_lines"]), 2)
        repeated = self.analyze(timing(1, 100), flush(0, 1), packet(1), compile_event(1),
                               compile_event(1), compile_identity(1))
        self.assertTrue(all(row["identity"] is None for row in repeated["frames"][0]["packets"][0]["compiles"]))
        self.assertEqual(len(repeated["diagnostics"]["duplicate_compile_records"]), 1)

    def test_pipeline_key_identity_and_duration_are_independent_attribution(self):
        result = self.analyze(timing(1, 100), flush(0, 1), packet(1, pipelines=1, pipeline_create=60),
                              pipeline_event(1))
        frame = result["frames"][0]
        key = frame["packets"][0]["pipeline_events"][0]
        self.assertEqual((key["program"], key["generation"], key["packed"], key["color_format"], key["depth_format"]),
                         (12, 1, 0xFF00, 80, 260))
        self.assertEqual((key["color_mask"], key["blend_enabled"], key["blend_source"], key["blend_destination"], key["blend_operation"]),
                         (7, True, 7, 2, 1))
        self.assertEqual(frame["totals"]["pipeline_event_ns"], 60)
        self.assertEqual(frame["totals"]["pipeline_create_ns"], 60)
        self.assertEqual(frame["totals"]["host_packet_ns"], 100)
        self.assertEqual(frame["cache_state"], "cold")

    def test_invalid_pipeline_rows_and_missing_packet_are_visible(self):
        bad = pipeline_event(1).replace("duration 60 ns", "duration 59 ns")
        result = self.analyze(timing(1, 100), flush(0, 1), bad, pipeline_event(1, command_index=10), pipeline_event(2))
        self.assertFalse(result["frames"][0]["packet_coverage_complete"])
        self.assertEqual(len(result["diagnostics"]["record_errors"]), 2)
        self.assertEqual(len(result["diagnostics"]["unattributed_pipeline_lines"]), 2)
        self.assertEqual(result["frames"][0]["cache_state"], "cold")

    def test_camera_kinds_preserve_raw_names_and_separate_render_counter(self):
        result = self.analyze(camera_point(), timing(1, 100), timing(2, 200),
                              timing(3, 300, tick=151), camera_animation(), camera_point(tick=999))
        self.assertEqual(result["diagnostics"]["parse_errors"], [])
        cameras = result["camera_markers"]
        self.assertEqual(cameras[0]["name"], "pelican, initial pan")
        self.assertEqual(cameras[0]["render_frame"], 9999)
        self.assertEqual(cameras[0]["candidate_native_frames"], [1, 2])
        self.assertEqual(cameras[1]["kind"], "animation")
        self.assertEqual(cameras[1]["animation_frames"], 120)
        self.assertEqual(cameras[1]["candidate_native_frames"], [3])
        self.assertEqual(cameras[2]["candidate_native_frames"], [])
        malformed = analyzer.parse_log("Native camera: malformed")
        self.assertEqual(len(malformed["parse_errors"]), 1)

    def test_optional_guest_work_uses_completed_frame_and_keeps_submit_separate(self):
        result = self.analyze(guest_work(2, expansion=9_000_000_000_000_000_001),
            timing(1, 10), flush(0, 1), packet(1), timing(2, 20), flush(1, 2), packet(2))
        first, second = result["frames"]
        self.assertIsNone(first["guest_work"])
        self.assertNotIn("guest_cpu_ns", first["totals"])
        self.assertEqual(second["guest_work"]["frame"], 2)
        self.assertEqual(second["totals"]["guest_expansion_ns"], 9_000_000_000_000_000_001)
        self.assertEqual(second["totals"]["guest_cpu_ns"], 9_000_000_000_000_000_141)
        self.assertEqual(second["totals"]["guest_draw_submit_ns"], 100)
        self.assertEqual(second["totals"]["guest_submit_ns"], 100)
        self.assertEqual(second["totals"]["guest_work_draws"], 5)
        self.assertEqual(result["summary"]["totals"]["guest_work_frames"], 1)
        self.assertEqual(result["diagnostics"]["unattributed_guest_work_lines"], [])
        self.assertEqual(second["cache_state"], "warm")

    def test_duplicate_unattributed_and_malformed_guest_work_remain_explicit(self):
        result = self.analyze(timing(1, 10), packet(1), flush(0, 1), guest_work(1),
                              guest_work(1), guest_work(2), "Native guest work: malformed")
        frame = result["frames"][0]
        self.assertIsNone(frame["guest_work"])
        self.assertNotIn("guest_cpu_ns", frame["totals"])
        self.assertEqual(frame["cache_state"], "warm")
        self.assertEqual(result["diagnostics"]["duplicate_frames"],
                         [dict(source="guest_work", frame=1, lines=[4, 5])])
        self.assertEqual(result["diagnostics"]["unattributed_guest_work_lines"], [4, 5, 6])
        self.assertEqual(len(result["diagnostics"]["parse_errors"]), 1)


if __name__ == "__main__":
    unittest.main()
