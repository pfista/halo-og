"""Reject false fidelity passes: truncated capture, lost shots, drift and tails."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

from tools.halo_fidelity import (MEASUREMENT_FIELDS, REFERENCE, ROOT, analyze, compare_reports,
                                digest, instrument, replace_once, run_configuration, save,
                                signed_degrees, source_allowed, stats)
from tools.fidelity.local_broker import packet, take_packet


class FidelityComparatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = self.root / "reference"
        self.candidate = self.root / "candidate"
        self.capture = {"valid": True, "metrics": {
            "action_age_ms": stats([33, 33, 34, 33]),
            "shot_minus_drawn_camera_deg": stats([-3.3, -3.3, -3.4, -3.3]),
        }}
        for key in MEASUREMENT_FIELDS:
            self.capture["metrics"].setdefault(key, stats([0, 0, 0, 0]))
        self.run = {"scenario": {"shots": 4, "rate_dps": 100, "phase_ms": 0},
                    "map_sha256": {"bloodgulch.map": "stock-map-hash"}}
        for folder in (self.reference, self.candidate):
            folder.mkdir()
            save(folder / "analysis.json", self.capture)
            save(folder / "run.json", self.run)

    def result(self):
        a, b = (json.loads((p / "analysis.json").read_text()) for p in (self.reference, self.candidate))
        ra, rb = (json.loads((p / "run.json").read_text()) for p in (self.reference, self.candidate))
        return compare_reports(a, b, ra, rb)

    def test_identical_valid_runs_match(self):
        self.assertTrue(self.result()["passed"])

    def test_removed_tick_delay_fails(self):
        capture = copy.deepcopy(self.capture)
        capture["metrics"]["action_age_ms"] = stats([0, 0, 1, 0])
        capture["metrics"]["shot_minus_drawn_camera_deg"] = stats([0, 0, -0.1, 0])
        save(self.candidate / "analysis.json", capture)
        self.assertFalse(self.result()["passed"])

    def test_same_median_does_not_hide_bad_shot(self):
        capture = copy.deepcopy(self.capture)
        capture["metrics"]["action_age_ms"] = stats([33, 33, 33, 100])
        save(self.candidate / "analysis.json", capture)
        self.assertFalse(self.result()["passed"])

    def test_removed_tick_is_rejected_even_if_wall_times_are_unchanged(self):
        capture = copy.deepcopy(self.capture)
        capture["metrics"]["action_age_ticks"] = stats([1, 1, 1, 1])
        save(self.reference / "analysis.json", capture)
        self.assertFalse(self.result()["passed"])

    def test_camera_offset_regression_is_rejected(self):
        capture = copy.deepcopy(self.capture)
        capture["metrics"]["shot_camera_residual_deg"] = stats([1.5] * 4)
        save(self.candidate / "analysis.json", capture)
        self.assertFalse(self.result()["passed"])

    def test_raw_frame_cadence_variation_is_visible_without_false_mismatch(self):
        capture = copy.deepcopy(self.capture)
        capture["metrics"]["shot_minus_drawn_camera_deg"] = stats([-3.0] * 4)
        save(self.candidate / "analysis.json", capture)
        result = self.result()
        self.assertTrue(result["passed"])
        self.assertFalse(result["metrics"]["shot_minus_drawn_camera_deg"]["within_tolerance"])

    def test_invalid_capture_cannot_pass_even_with_matching_metrics(self):
        for folder in (self.reference, self.candidate):
            capture = copy.deepcopy(self.capture)
            capture["valid"] = False
            save(folder / "analysis.json", capture)
            self.assertFalse(self.result()["passed"])

    def test_different_map_or_phase_cannot_pass(self):
        for part, key, value in (("map_sha256", "bloodgulch.map", "different-map"),
                                 ("scenario", "phase_ms", 16.667)):
            run = copy.deepcopy(self.run)
            run[part][key] = value
            save(self.candidate / "run.json", run)
            self.assertFalse(self.result()["passed"])

    def test_missing_metrics_cannot_pass(self):
        capture = copy.deepcopy(self.capture)
        capture["metrics"]["action_age_ms"] = None
        save(self.candidate / "analysis.json", capture)
        self.assertFalse(self.result()["passed"])

    def test_empty_metrics_cannot_pass(self):
        for p in (self.reference, self.candidate):
            save(p / "analysis.json", {"valid": True, "metrics": {}})
        self.assertFalse(self.result()["passed"])

    def test_wraparound_uses_shortest_signed_angle(self):
        import math
        self.assertAlmostEqual(signed_degrees(math.radians(1), math.radians(359)), 2)
        self.assertAlmostEqual(signed_degrees(math.radians(359), math.radians(1)), -2)

    def test_ambiguous_patch_anchor_fails_without_changing_file(self):
        path = self.root / "engine.c"
        path.write_text("hook();\nhook();\n")
        before = digest(path)
        with self.assertRaises(ValueError):
            replace_once(path, "hook();", "instrumented();")
        self.assertEqual(digest(path), before)

    def test_snapshot_excludes_secrets_and_runtime_data(self):
        for name in ("", ".env", "port/.env.local", "assets/maps/bloodgulch.map", "build/macos/halo",
                     "tools/__pycache__/secret.pyc", ".git/config", "../source/game/players.c",
                     "/source/game/players.c"):
            self.assertFalse(source_allowed(name), name)
        self.assertTrue(source_allowed("source/game/player_queues_new.c"))


class DiagnosticBuildTests(unittest.TestCase):
    def test_current_and_historical_sources_accept_probe_anchors(self):
        files = ("source/game/player_control.c", "source/game/players.c", "source/items/weapons.c",
                 "source/game/game_engine.c", "port/linux/game/render_interpolation.c",
                 "source/networking/network_game_protocol.h", "port/linux/src/p2p.c",
                 "source/bungie_net/network/transport_endpoint_winsock.c")
        revisions = [("working", False)]
        if subprocess.run(["git", "cat-file", "-e", REFERENCE + "^{commit}"], cwd=ROOT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            revisions.append((REFERENCE, True))
        for revision, legacy in revisions:
            with self.subTest(revision=revision), tempfile.TemporaryDirectory() as temporary:
                tree = Path(temporary)
                for name in files:
                    target = tree / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = (ROOT / name).read_bytes() if revision == "working" else subprocess.check_output(
                        ["git", "show", f"{revision}:{name}"], cwd=ROOT)
                    target.write_bytes(data)
                instrumented = instrument(tree, legacy)
                self.assertIn("source/game/player_control.c", instrumented)
                self.assertIn("source/networking/network_game_protocol.h", instrumented)

    def test_runtime_config_disables_public_services_for_both_transports(self):
        for transport in ("lan", "local-relay"):
            for endpoint in ("host", "client"):
                with self.subTest(transport=transport, endpoint=endpoint):
                    config = tomllib.loads(run_configuration(address="192.0.2.2", other_address="192.0.2.3",
                        transport=transport, broker_port=45678, legacy=True, endpoint=endpoint, role="host",
                        shots=12, rate=100, phase=0, tap=70, interpolation=False, duration=73))
                    network = config["network"]
                    self.assertEqual(network["directory_url"], "")
                    self.assertFalse(network["public_games"])
                    self.assertFalse(network["allow_upnp"])
                    self.assertFalse(network["join_from_clipboard"])
                    self.assertEqual(network["stun_servers"], "")
                    self.assertEqual(network["signalling_brokers"],
                                     "127.0.0.1:45678" if transport == "local-relay" else "")
                    self.assertEqual(network["online"], transport == "local-relay")
                    self.assertEqual(config["discord"]["application_id"], "")
                    self.assertFalse(config["update"]["auto"])
                    self.assertFalse(config["community_maps"]["auto_download"])
                    self.assertEqual(config["debug"]["test_input"],
                                     "fidelity:12:100:0:70" if endpoint == "host" else "fidelity_idle")


class RawCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "saves").mkdir()
        (self.root / "peer").mkdir()
        (self.root / "build").mkdir()
        (self.root / "saves/config.toml").write_text('[display]\ninterpolation = false\n')
        save(self.root / "build/manifest.json", {"legacy_lockstep": True})
        save(self.root / "run.json", {
            "build": str(self.root / "build"),
            "build_manifest_sha256": digest(self.root / "build/manifest.json"),
            "config_sha256": digest(self.root / "saves/config.toml"),
            "exit_code": 0, "peer_exit_code": 0, "timed_out": False,
            "local_signalling": {"deliveries": 2},
            "scenario": {"shots": 1, "role": "host", "transport": "local-relay",
                         "rate_dps": 100, "phase_ms": 0, "tap_ms": 70},
        })
        self.prefix = ('Internet play: connected to local\nnetwork test: tick 330 player 0: idle player 1: idle\n'
                       'FIDELITY_READY tick=240 player=0 loaded=12 total=48\n'
                       'FIDELITY_READY tick=240 player=1 loaded=12 total=48\n')
        (self.root / "peer/game.log").write_text(self.prefix)
        self.records = [
            {"event": "meta", "role": 2, "legacy_lockstep": 1, "overflow": 0,
             "requested_shots": 1, "rate_dps": 100, "phase_ms": 0, "tap_ms": 70},
            self.record('c', 0, 300, 1), self.record('a', 1000, 330, 2),
            self.record('p', 1000, 330, 2, object=0), self.record('c', 1000, 330, 2),
            self.record('b', 1000, 330, 2), self.record('s', 1000, 330, 2),
            self.record('f', 1000, 330, 2, target=42), self.record('v', 1000, 330, 2),
        ]
        self.write()

    @staticmethod
    def record(kind, ms, tick, sample, **values):
        return dict(event=kind, ms=ms, tick=tick, sample=sample, x=0, i=1, j=0,
                    **({"object": -1, "target": -1} | values))

    def write(self, complete=True):
        records = self.records + ([{"event": "end", "records": len(self.records) - 1}] if complete else [])
        (self.root / "game.log").write_text(self.prefix + 'FIDELITY_WEAPON 1 weapons\\pistol\\pistol\n' +
            ''.join('FTRACE ' + json.dumps(r) + '\n' for r in records))

    def test_valid_trace_then_truncation_is_rejected(self):
        self.assertTrue(analyze(self.root)["valid"])
        self.write(complete=False)
        result = analyze(self.root)
        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["complete_trace"])

    def test_missing_projectile_rejected_even_if_end_count_matches(self):
        self.records = [r for r in self.records if r["event"] != 'f']
        self.write()
        result = analyze(self.root)
        self.assertTrue(result["checks"]["complete_trace"])
        self.assertFalse(result["valid"])

    def test_fault_in_peer_diagnostic_log_invalidates_capture(self):
        (self.root / 'peer/data').mkdir()
        (self.root / 'peer/data/debug.txt').write_text('ASSERTION FAILED during simulation')
        self.assertFalse(analyze(self.root)["checks"]["no_fault"])

    def test_fabricated_press_id_does_not_count_as_requested_press(self):
        next(r for r in self.records if r["event"] == 'p')["object"] = 17
        self.write()
        self.assertFalse(analyze(self.root)["checks"]["all_presses_observed"])

    def test_long_stall_is_measured_instead_of_discarded(self):
        for row in self.records:
            if row["event"] in ('a', 'p'):
                row["ms"] = 250
        self.write()
        result = analyze(self.root)
        self.assertTrue(result["valid"])
        self.assertEqual(result["metrics"]["action_age_ms"]["max"], 750)


class LocalSignallingTests(unittest.TestCase):
    def test_fragmented_packets_and_multiple_packets(self):
        encoded = packet(0x30, b'x' * 130)
        buffer = bytearray(encoded[:2])
        self.assertIsNone(take_packet(buffer))
        buffer.extend(encoded[2:] + packet(0xC0, b''))
        self.assertEqual(take_packet(buffer), (0x30, b'x' * 130))
        self.assertEqual(take_packet(buffer), (0xC0, b''))
        self.assertEqual(buffer, b'')

    def test_invalid_or_unbounded_length_rejected(self):
        for value in (b'\x30\xff\xff\xff\x7f', b'\x30\x80\x80\x80\x80'):
            with self.assertRaises(ValueError):
                take_packet(bytearray(value))


if __name__ == "__main__":
    unittest.main()
