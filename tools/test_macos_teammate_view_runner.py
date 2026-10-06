"""Exercise interactive runner preparation and owned-process cleanup.

All game processes, interface queries and socket binds are replaced by fixtures.
These tests never launch Halo, change a network interface or stop an existing app.
"""
import json
import errno
import io
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import macos_teammate_view_runner as runner


ROLES = (("red_host", 0), ("red_client", 0), ("blue_client_1", 1), ("blue_client_2", 1))
ADDRESSES = ["192.168.1.8", "127.0.0.2", "127.0.0.3", "127.0.0.4"]


class FakeProcess:
    """A process handle with an explicit lifetime, without creating a PID."""
    def __init__(self, pid, code=None, timeout=False):
        self.pid, self.returncode, self.timeout = pid, code, timeout
        self.terminations, self.kills, self.waits = 0, 0, []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminations += 1

    def kill(self):
        self.kills += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.timeout and not self.kills:
            raise subprocess.TimeoutExpired(["fixture game"], timeout)
        if self.returncode is None:
            self.returncode = -15
        return self.returncode


class FakeSocket:
    """Capture bind preflights while opening no actual network sockets."""
    def __init__(self, kind, calls, failures):
        self.kind, self.calls, self.failures, self.closed = kind, calls, failures, False
        self.options = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def setsockopt(self, level, option, value):
        self.options.append((level, option, value))

    def bind(self, endpoint):
        self.calls.append((self.kind, endpoint))
        if (self.kind, endpoint) in self.failures:
            raise OSError(errno.EADDRINUSE, "Address already in use")

    def close(self):
        self.closed = True


class InteractiveRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="halo-team-view-runner-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.assets = self.root / "original assets"
        (self.assets / "maps").mkdir(parents=True)
        (self.assets / "sounds").mkdir()
        (self.assets / "maps/bloodgulch.map").write_bytes(b"fixture map, never executed")
        (self.assets / "maps/ui.map").write_bytes(b"fixture menu map, never executed")
        (self.assets / "sounds/readme.txt").write_text("fixture sounds")

    def application(self, metal=True):
        contents = self.root / "Candidate Halo.app/Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        executable = contents / "MacOS/halo"
        executable.write_bytes(b"fixture executable, never executed")
        executable.chmod(0o755)
        (contents / "Resources/halo_guest.elf").write_bytes(b"fixture guest, never executed")
        if metal:
            companion = contents / "MacOS/halo-metal"
            companion.write_bytes(b"fixture executable, never executed")
            companion.chmod(0o755)
            (contents / "Resources/halo_guest-metal.elf").write_bytes(b"fixture guest, never executed")
        return executable

    def assert_interactive_config(self, config, role, team, address, hidden=False):
        parsed = tomllib.loads(config)
        debug, network = parsed["debug"], parsed["network"]
        self.assertEqual(debug["test_input"], "")
        self.assertEqual(debug["exit_after"], 0)
        self.assertEqual(debug["network_test_pickup_weapon"], "")
        for setting in ("network_test_shoot", "network_test_kill", "network_test_vehicle", "network_test_pickup"):
            self.assertEqual(debug[setting], 0, setting)
        # Gathering is gated by the shooting interval in network_test_update.
        self.assertEqual(debug["network_test_shoot"], 0)
        self.assertEqual(debug["hidden_window"], hidden)
        self.assertEqual(debug["network_test_team"], team)
        self.assertIs(debug["network_test_team_view"], role == "red_host")
        self.assertEqual(debug["network_test"], "host:bloodgulch:team_slayer" if role == "red_host" else "join")
        self.assertEqual(network["address"], address)
        self.assertFalse(network["allow_upnp"])
        self.assertFalse(network["public_games"])
        self.assertEqual(network["directory_url"], "")
        self.assertFalse(network["join_from_clipboard"])
        self.assertFalse(parsed["update"]["auto"])
        self.assertFalse(parsed["community_maps"]["auto_download"])
        self.assertFalse(parsed["timer_audio"]["auto_download"])
        self.assertEqual(parsed["discord"]["application_id"], "")
        self.assertIs(parsed["audio"]["enabled"], role == "red_host")
        # Ordinary bindings remain active; the runner supplies no scripted input.
        self.assertNotIn("bindings", parsed)

    def test_scratch_config_has_manual_controls_and_no_gameplay_automation(self):
        for role, team in ROLES:
            with self.subTest(role=role):
                self.assert_interactive_config(
                    runner.make_config(role, team, ADDRESSES[0], "bloodgulch", "metal", False, 35.0),
                    role, team, ADDRESSES[0])

    def test_hiding_clients_does_not_hide_the_controlled_host(self):
        for role, team in ROLES:
            with self.subTest(role=role):
                self.assert_interactive_config(
                    runner.make_config(role, team, ADDRESSES[0], "bloodgulch", "angle", True, 35.0),
                    role, team, ADDRESSES[0], hidden=role != "red_host")

    def test_preparation_is_isolated_and_cleans_inherited_overrides(self):
        polluted = dict(PATH="/fixture/bin", HOME="/fixture/home", HALO_TEST_INPUT="bot:99",
                        HALO_NETWORK_TEST_SHOOT="3", HALO_NETWORK_TEST_KILL="4",
                        HALO_NET_ALLOW_UPNP="true", HALO_UPDATE_AUTO="true",
                        HALO_DATA_ROOT="/personal/data", HALO_SAVE_ROOT="/personal/saves",
                        DYLD_INSERT_LIBRARIES="/fixture/synthetic-input.dylib",
                        POC_DIAG_EVENT_FILE="/personal/events")
        environments = []
        with patch.dict(os.environ, polluted, clear=True):
            for index, (role, team) in enumerate(ROLES):
                folder = self.root / "session" / role
                environment = runner.prepare_instance(folder, role, team, ADDRESSES[index],
                                                      "bloodgulch", "metal", data_root=self.assets)
                environments.append(environment)
                self.assertEqual(environment["HALO_SAVE_ROOT"], str(folder / "saves"))
                self.assertEqual(environment["HALO_DATA_ROOT"], str(folder / "data"))
                self.assertEqual(environment["PATH"], polluted["PATH"])
                self.assertEqual(environment["HOME"], polluted["HOME"])
                for name in polluted:
                    if name.startswith(("HALO_", "DYLD_")) and name not in ("HALO_DATA_ROOT", "HALO_SAVE_ROOT"):
                        self.assertNotEqual(environment.get(name), polluted[name], name)
                self.assertNotIn("DYLD_INSERT_LIBRARIES", environment)
                self.assertNotIn("POC_DIAG_EVENT_FILE", environment)
                self.assert_interactive_config((folder / "saves/config.toml").read_text(),
                                               role, team, ADDRESSES[index])
                settings = json.loads((folder / "saves/macos-settings.json").read_text())
                self.assertFalse(settings["community_downloads"])
                self.assertFalse(settings["timer_audio_downloads"])
                self.assertFalse(settings["release_checks"])
                self.assertNotIn("data_path", settings)
                self.assertTrue((folder / "data/maps/ui.map").is_symlink())
                self.assertEqual((folder / "data/maps/ui.map").resolve(), self.assets / "maps/ui.map")
        self.assertEqual(len({environment["HALO_SAVE_ROOT"] for environment in environments}), 4)
        self.assertEqual(len({environment["HALO_DATA_ROOT"] for environment in environments}), 4)
        self.assertEqual((self.assets / "maps/bloodgulch.map").read_bytes(), b"fixture map, never executed")

    def test_address_assignment_uses_only_distinct_configured_addresses(self):
        configured = ADDRESSES + ["127.0.0.1"]
        resolved = runner.resolve_addresses(None, configured)
        self.assertEqual(len(resolved), 4)
        self.assertEqual(len(set(resolved)), 4)
        self.assertTrue(set(resolved).issubset(configured))
        self.assertEqual(runner.resolve_addresses(",".join(ADDRESSES), configured), ADDRESSES)
        invalid = ("192.168.1.8,127.0.0.2,127.0.0.2,127.0.0.4",
                   "192.168.1.8,127.0.0.2,127.0.0.3,127.0.0.99",
                   "192.168.1.8,127.0.0.2,127.0.0.3", "::1,127.0.0.2,127.0.0.3,127.0.0.4")
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.resolve_addresses(value, configured)
        with self.assertRaises(ValueError):
            runner.resolve_addresses(None, ADDRESSES[:2])

    def test_only_complete_executable_app_bundles_are_accepted(self):
        executable = self.application()
        self.assertEqual(runner.validate_app(executable, "angle"), executable.resolve())
        self.assertEqual(runner.validate_app(executable, "metal"), executable.resolve())
        executable.chmod(0o644)
        with self.assertRaises(ValueError):
            runner.validate_app(executable, "angle")
        executable.chmod(0o755)
        (executable.parent.parent / "Resources/halo_guest.elf").unlink()
        with self.assertRaises(ValueError):
            runner.validate_app(executable, "angle")
        direct = self.root / "halo"
        direct.write_bytes(b"not an app bundle")
        direct.chmod(0o755)
        with self.assertRaises(ValueError):
            runner.validate_app(direct, "angle")

    def test_metal_requires_both_renderer_companions(self):
        executable = self.application()
        native = executable.parent / "halo-metal"
        native.chmod(0o644)
        with self.assertRaises(ValueError):
            runner.validate_app(executable, "metal")
        native.chmod(0o755)
        (executable.parent.parent / "Resources/halo_guest-metal.elf").unlink()
        with self.assertRaises(ValueError):
            runner.validate_app(executable, "metal")

    def test_socket_preflight_checks_reserved_host_and_all_owned_peer_bindings(self):
        calls, sockets = [], []
        def socket(family, kind):
            self.assertEqual(family, runner.socket.AF_INET)
            value = FakeSocket(kind, calls, set())
            sockets.append(value)
            return value
        with patch.object(runner.socket, "socket", side_effect=socket):
            self.assertEqual(runner.check_ports(ADDRESSES), [])
        expected = {(runner.socket.SOCK_STREAM, ("0.0.0.0", 5150)),
                    (runner.socket.SOCK_DGRAM, (ADDRESSES[0], 5150))}
        expected |= {(kind, (address, 5151)) for address in ADDRESSES
                     for kind in (runner.socket.SOCK_STREAM, runner.socket.SOCK_DGRAM)}
        self.assertEqual(set(calls), expected)
        self.assertTrue(all(sock.closed for sock in sockets))
        if hasattr(runner.socket, "SO_REUSEPORT"):
            self.assertTrue(all(option != runner.socket.SO_REUSEPORT
                                for sock in sockets for _, option, _ in sock.options))

    def test_wildcard_conflict_is_reported_without_stopping_any_process(self):
        calls, sockets = [], []
        failure = {(runner.socket.SOCK_STREAM, ("0.0.0.0", 5150))}
        def socket(family, kind):
            value = FakeSocket(kind, calls, failure)
            sockets.append(value)
            return value
        unrelated = FakeProcess(999)
        with patch.object(runner.socket, "socket", side_effect=socket), \
                patch.object(runner.subprocess, "Popen") as launch, \
                patch.object(os, "kill") as kill:
            errors = runner.check_ports(ADDRESSES)
        self.assertTrue(errors)
        self.assertTrue(any("5150" in str(error) for error in errors))
        self.assertTrue(all(sock.closed for sock in sockets))
        self.assertEqual((unrelated.terminations, unrelated.kills), (0, 0))
        launch.assert_not_called()
        kill.assert_not_called()

    def test_fresh_session_writes_four_independent_configs_and_does_not_overwrite(self):
        executable = self.application()
        output = self.root / "new session"
        with patch.object(runner.subprocess, "Popen") as launch:
            plan = runner.prepare_session(output, ADDRESSES, executable, "metal", "bloodgulch",
                                          data_root=self.assets)
        self.assertEqual(len(plan["instances"]), 4)
        for index, ((role, team), instance) in enumerate(zip(ROLES, plan["instances"])):
            self.assertEqual((instance["role"], instance["team"], instance["address"]),
                             (role, team, ADDRESSES[index]))
            self.assertEqual(instance["command"], [str(executable.resolve())])
            folder = output / role
            self.assertEqual(instance["environment"]["HALO_SAVE_ROOT"], str(folder / "saves"))
            self.assert_interactive_config((folder / "saves/config.toml").read_text(), role, team, ADDRESSES[index])
        launch.assert_not_called()
        original = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(ValueError, "exists"):
            runner.prepare_session(output, ADDRESSES, executable, "metal", "bloodgulch", data_root=self.assets)
        self.assertEqual(original, {path.relative_to(output): path.read_bytes()
                                    for path in output.rglob("*") if path.is_file()})

    def test_invalid_assets_and_existing_instance_preserve_destination_files(self):
        executable = self.application()
        output = self.root / "missing-map session"
        with self.assertRaises(ValueError):
            runner.prepare_session(output, ADDRESSES, executable, "angle", "missing_map", data_root=self.assets)
        self.assertFalse(output.exists())
        folder = self.root / "existing role"
        folder.mkdir()
        (folder / "keep.txt").write_text("existing evidence")
        with self.assertRaises(FileExistsError):
            runner.prepare_instance(folder, "red_host", 0, ADDRESSES[0], "bloodgulch", "angle",
                                    data_root=self.assets)
        self.assertEqual((folder / "keep.txt").read_text(), "existing evidence")
        self.assertFalse((folder / "saves").exists())

    def test_dangling_output_symlink_cannot_redirect_preparation(self):
        executable = self.application()
        output, destination = self.root / "existing output link", self.root / "missing destination"
        output.symlink_to(destination, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "exists"):
            runner.prepare_session(output, ADDRESSES, executable, "angle", "bloodgulch", data_root=self.assets)
        self.assertTrue(output.is_symlink())
        self.assertFalse(destination.exists())

    def test_invalid_duration_never_queries_interfaces_or_launches(self):
        for argument, value in (("--seconds", "nan"), ("--seconds", "inf"),
                                ("--start-delay", "nan"), ("--start-delay", "9")):
            with self.subTest(argument=argument, value=value), \
                    patch.object(runner, "configured_addresses") as interfaces, \
                    patch.object(runner.subprocess, "Popen") as launch, \
                    patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as raised:
                    runner.main([argument, value])
                self.assertEqual(raised.exception.code, 2)
                interfaces.assert_not_called()
                launch.assert_not_called()

    def test_busy_port_failure_and_dry_run_never_create_files_or_launch(self):
        executable = self.application()
        output = self.root / "preflight session"
        argv = ["--output", str(output), "--executable", str(executable), "--renderer", "angle",
                "--data-root", str(self.assets), "--addresses", ",".join(ADDRESSES)]
        with patch.object(runner, "configured_addresses", return_value=ADDRESSES), \
                patch.object(runner, "check_ports", return_value=["host TCP 0.0.0.0:5150 is unavailable"]), \
                patch.object(runner.subprocess, "Popen") as launch, \
                patch.object(runner, "stop_processes") as cleanup, \
                patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(runner.main(argv), 1)
            self.assertIn("no apps were launched or stopped", errors.getvalue())
            self.assertEqual(runner.main(argv + ["--dry-run"]), 0)
        self.assertFalse(output.exists())
        launch.assert_not_called()
        cleanup.assert_not_called()

    def test_configuration_write_failure_is_reported_before_any_launch(self):
        executable = self.application()
        output = self.root / "configuration failure"
        argv = ["--output", str(output), "--executable", str(executable), "--renderer", "angle",
                "--data-root", str(self.assets), "--addresses", ",".join(ADDRESSES)]
        with patch.object(runner, "configured_addresses", return_value=ADDRESSES), \
                patch.object(runner, "check_ports", return_value=[]), \
                patch.object(runner, "prepare_instance", side_effect=OSError("fixture configuration write failed")), \
                patch.object(runner.subprocess, "Popen") as launch, \
                patch.object(runner, "stop_processes") as cleanup, \
                patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(runner.main(argv), 1)
        self.assertIn("Team View runner: fixture configuration write failed", errors.getvalue())
        self.assertTrue(output.is_dir())
        self.assertEqual(list(output.iterdir()), [])
        self.assertEqual((self.assets / "maps/bloodgulch.map").read_bytes(), b"fixture map, never executed")
        launch.assert_not_called()
        cleanup.assert_not_called()

    def test_startup_failure_closes_logs_and_cleans_only_started_handles(self):
        executable = self.application()
        plan = runner.prepare_session(self.root / "failed launch", ADDRESSES, executable, "angle",
                                      "bloodgulch", data_root=self.assets)
        host, unrelated = FakeProcess(101), FakeProcess(999)
        calls = []
        def launch(command, **kwargs):
            calls.append((command, kwargs))
            if len(calls) == 1:
                return host
            raise OSError("fixture client startup failed")
        invite = "halo-og://join/" + "a1" * 32
        with patch.object(runner.subprocess, "Popen", side_effect=launch), \
                patch.object(runner, "process_start_time", side_effect=lambda pid: "birth-" + str(pid)), \
                patch.object(runner, "read_log", return_value=invite), \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(OSError, "client startup failed"):
                runner.run_session(plan)
        self.assertEqual((host.terminations, host.kills), (1, 0))
        self.assertEqual((unrelated.terminations, unrelated.kills), (0, 0))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(kwargs["stdout"].closed for _, kwargs in calls))
        manifest = json.loads(runner.manifest_path(plan).read_text())
        self.assertEqual(manifest["state"], "stopped")
        self.assertEqual(manifest["instances"][0]["pid"], host.pid)
        self.assertTrue(all(instance["pid"] is None for instance in manifest["instances"][1:]))
        self.assertTrue(all("environment" not in instance for instance in manifest["instances"]))
        self.assertNotIn(invite, runner.manifest_path(plan).read_text())

    def test_host_failure_before_invite_launches_no_client(self):
        executable = self.application()
        plan = runner.prepare_session(self.root / "host failed", ADDRESSES, executable, "angle",
                                      "bloodgulch", data_root=self.assets)
        host = FakeProcess(101, code=1)
        with patch.object(runner.subprocess, "Popen", return_value=host) as launch, \
                patch.object(runner, "process_start_time", return_value="fixture birth"), \
                patch.object(runner, "read_log", return_value="host startup failure"), \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, "no private invite"):
                runner.run_session(plan)
        self.assertEqual(launch.call_count, 1)
        self.assertEqual((host.terminations, host.kills), (0, 0))
        self.assertTrue(launch.call_args.kwargs["stdout"].closed)
        self.assertEqual(json.loads(runner.manifest_path(plan).read_text())["state"], "stopped")

    def test_manifest_omits_inherited_sensitive_values(self):
        executable = self.application()
        sentinel = "fixture-sensitive-value-never-persisted"
        with patch.dict(os.environ, {"EXAMPLE_SESSION_SECRET": sentinel}):
            plan = runner.prepare_session(self.root / "manifest privacy", ADDRESSES, executable, "angle",
                                          "bloodgulch", data_root=self.assets)
        self.assertEqual(plan["instances"][0]["environment"]["EXAMPLE_SESSION_SECRET"], sentinel)
        runner.write_manifest(plan)
        self.assertNotIn(sentinel, runner.manifest_path(plan).read_text())
        self.assertNotIn("environment", json.loads(runner.manifest_path(plan).read_text())["instances"][0])
        self.assertEqual(runner.manifest_path(plan).stat().st_mode & 0o777, 0o600)

    def test_successful_launch_leaves_controls_manual_until_owned_cleanup(self):
        from tools.test_macos_teammate_view_smoke import tick
        executable = self.application()
        plan = runner.prepare_session(self.root / "interactive session", ADDRESSES, executable, "metal",
                                      "bloodgulch", data_root=self.assets)
        peers = [FakeProcess(100 + index) for index in range(4)]
        invite = "halo-og://join/" + "a1" * 32
        logs = {role: tick(index) + (invite if index == 0 else "")
                for index, (role, _) in enumerate(ROLES)}
        with patch.object(runner.subprocess, "Popen", side_effect=peers) as launch, \
                patch.object(runner, "process_start_time", side_effect=lambda pid: "birth-" + str(pid)), \
                patch.object(runner, "read_log", side_effect=lambda folder: logs[folder.name]), \
                patch.object(runner.time, "sleep", side_effect=KeyboardInterrupt), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(runner.run_session(plan), 0)
        self.assertEqual(launch.call_count, 4)
        self.assertTrue(all(peer.terminations == 1 and peer.kills == 0 for peer in peers))
        for index, call in enumerate(launch.call_args_list):
            self.assertEqual(call.args[0], [str(executable)] + ([invite] if index else []))
            self.assertTrue(call.kwargs["start_new_session"])
            self.assertTrue(call.kwargs["stdout"].closed)
            self.assertNotIn("HALO_TEST_INPUT", call.kwargs["env"])
        manifest = json.loads(runner.manifest_path(plan).read_text())
        self.assertTrue(manifest["observed_2v2_teammate_views"])
        self.assertEqual(manifest["state"], "stopped")

    def test_stop_manifest_preserves_reused_or_unverified_pids(self):
        path = self.root / "session.json"
        path.write_text(json.dumps({"state": "running", "runner": {"pid": 1, "start_time": "old runner"},
                                    "instances": [{"role": "own", "pid": 101, "start_time": "original"},
                                                  {"role": "reused", "pid": 102, "start_time": "old"},
                                                  {"role": "unknown", "pid": 103, "start_time": ""}]}))
        current = {1: "new runner", 101: "original", 102: "new unrelated app", 103: "unknown"}
        with patch.object(runner, "process_start_time", side_effect=lambda pid: current[pid]), \
                patch.object(os, "kill") as kill, patch("sys.stdout", new_callable=io.StringIO):
            runner.stop_session(path)
        kill.assert_called_once_with(101, runner.signal.SIGTERM)

    def test_stop_manifest_requests_live_runner_cleanup_without_signalling_children(self):
        path = self.root / "session.json"
        path.write_text(json.dumps({"state": "running", "runner": {"pid": 50, "start_time": "runner birth"},
                                    "instances": [{"role": "own", "pid": 101, "start_time": "original"}]}))
        with patch.object(runner, "process_start_time", return_value="runner birth"), \
                patch.object(os, "kill") as kill, patch("sys.stdout", new_callable=io.StringIO):
            runner.stop_session(path)
        kill.assert_called_once_with(50, runner.signal.SIGTERM)

    def test_cleanup_only_uses_owned_process_handles(self):
        live = FakeProcess(101)
        finished = FakeProcess(102, code=0)
        stubborn = FakeProcess(103, timeout=True)
        unrelated = FakeProcess(999)
        with patch.object(runner.subprocess, "run") as external, patch.object(os, "kill") as kill:
            runner.stop_processes({"red_host": live, "red_client": finished, "blue_client_1": stubborn})
        self.assertEqual((live.terminations, live.kills), (1, 0))
        self.assertEqual((finished.terminations, finished.kills), (0, 0))
        self.assertEqual((stubborn.terminations, stubborn.kills), (1, 1))
        self.assertEqual((unrelated.terminations, unrelated.kills, unrelated.waits), (0, 0, []))
        external.assert_not_called()
        kill.assert_not_called()

    def test_process_exit_races_do_not_abort_other_owned_cleanup(self):
        class DisappearingProcess(FakeProcess):
            def terminate(self):
                self.terminations += 1
                self.returncode = 0
                raise ProcessLookupError("fixture process already exited")
        class DisappearingAfterTimeout(FakeProcess):
            def kill(self):
                self.kills += 1
                self.returncode = 0
                raise ProcessLookupError("fixture process already exited")
        vanished = DisappearingProcess(101)
        timeout = DisappearingAfterTimeout(102, timeout=True)
        other = FakeProcess(103)
        runner.stop_processes({"vanished": vanished, "timeout": timeout, "other": other})
        self.assertEqual((other.terminations, other.kills), (1, 0))
        self.assertEqual(vanished.returncode, 0)
        self.assertEqual(timeout.returncode, 0)


if __name__ == "__main__":
    unittest.main()
