"""Check that the real-instance smoke validator rejects false 2v2 evidence."""
from pathlib import Path
import tempfile
import unittest

from tools.macos_teammate_view_smoke import (
    ROLES, TEAM_VIEW_MARKER, default_addresses, parse_invite, parse_tick, validate_logs,
)


def tick(local, enabled=True, target=None, time=30):
    if target is None:
        target = (1, 0, 3, 2)[local] if enabled else -1
    players = " ".join(
        f"player {index}: (1.000 2.000 3.000) h1.00/1.00 g2/2 w a0/0 f0 l0/0 as0/0 st0 thr0 "
        f"s0 k0 d0 f0 t{index // 2} m{index} lp{0 if index == local else -1} c0"
        for index in range(4))
    return (f"network test: tick {time} {players} | sent 30 received 30 corrected 0"
            f" | variant_flags 0x{(TEAM_VIEW_MARKER if enabled else 0) | 3:08x}"
            f" team_view {int(enabled)} windows {2 if enabled else 1} local_count 1 view_target {target}\n")


class TeammateViewSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-team-view-validator-")
        self.addCleanup(self.temp.cleanup)
        self.folders = {}
        for role, _ in ROLES:
            folder = Path(self.temp.name) / role
            (folder / "frames").mkdir(parents=True)
            (folder / "frames/frame.png").write_bytes(b"frame fixture")
            self.folders[role] = folder

    def logs(self, enabled=True):
        return {role: "Internet play: connected to test peer\n" +
                "".join(tick(index, enabled, time=time) for time in range(30, 180, 30))
                for index, (role, _) in enumerate(ROLES)}

    def validate(self, logs, enabled=True):
        return validate_logs(logs, logs, {role: 0 for role, _ in ROLES}, enabled, self.folders)

    def test_current_invite_format_accepts_exact_token_and_rejects_bad_lengths(self):
        for token in ("a1" * 32, "AF" * 32):
            invite = "halo-og://join/" + token
            self.assertEqual(parse_invite("Invite: " + invite + "\n"), invite)
            self.assertIsNone(parse_invite(invite + "a"))
            self.assertIsNone(parse_invite(invite[:-1]))
        self.assertIsNone(parse_invite("halo://old-invite"))

    def test_parse_tick_keeps_ownership_and_view_target(self):
        record = parse_tick(tick(1))
        self.assertEqual(len(record["players"]), 4)
        self.assertEqual(record["players"][1]["local_index"], 0)
        self.assertEqual(record["players"][0]["local_index"], -1)
        self.assertEqual(record["view_target"], 0)
        self.assertEqual(record["flags"], TEAM_VIEW_MARKER | 3)
        self.assertIsNone(parse_tick(tick(0).replace("player 3:", "removed 3:")))

    def test_four_distinct_roles_and_both_teams_pass_enabled(self):
        self.assertEqual([team for _, team in ROLES], [0, 0, 1, 1])
        records, checks = self.validate(self.logs())
        self.assertTrue(all(checks.values()), checks)
        self.assertTrue(all(len(lines) == 5 for lines in records.values()))

    def test_disabled_control_has_one_window_and_no_target(self):
        _, checks = self.validate(self.logs(False), False)
        self.assertTrue(all(checks.values()), checks)
        logs = self.logs(False)
        logs["red_host"] = logs["red_host"].replace("windows 1", "windows 2").replace("view_target -1", "view_target 1")
        _, checks = self.validate(logs, False)
        self.assertFalse(checks["red_host_expected_window_count"])

    def test_remote_player_marked_local_and_duplicate_machine_are_rejected(self):
        logs = self.logs()
        logs["red_host"] = logs["red_host"].replace("m1 lp-1 c0", "m0 lp0 c0")
        _, checks = self.validate(logs)
        self.assertFalse(checks["red_host_separate_machine_ownership"])
        self.assertFalse(checks["red_host_one_local_player"])

    def test_owner_change_during_match_is_rejected(self):
        logs = self.logs()
        logs["red_host"] = logs["red_host"].replace("m1 lp-1 c0", "m7 lp-1 c0", 1)
        _, checks = self.validate(logs)
        self.assertTrue(checks["red_host_separate_machine_ownership"])
        self.assertFalse(checks["red_host_stable_player_ownership"])

    def test_enemy_or_self_camera_target_is_rejected(self):
        for target in (0, 2, 99):
            with self.subTest(target=target):
                logs = self.logs()
                logs["red_host"] = logs["red_host"].replace("view_target 1", f"view_target {target}")
                _, checks = self.validate(logs)
                self.assertFalse(checks["red_host_same_team_remote_view"])

    def test_three_on_one_team_and_missing_role_are_rejected(self):
        logs = self.logs()
        logs["red_host"] = logs["red_host"].replace("t0 m1", "t1 m1")
        _, checks = self.validate(logs)
        self.assertFalse(checks["red_host_two_red_two_blue"])
        logs = self.logs()
        del logs["blue_client_2"]
        _, checks = self.validate(logs)
        self.assertFalse(checks["all_four_roles_present"])
        self.assertFalse(checks["four_players_on_every_machine"])

    def test_wrong_client_option_and_controller_assignment_are_rejected(self):
        logs = self.logs()
        logs["blue_client_1"] = logs["blue_client_1"].replace("0x53535003", "0x00000003").replace("team_view 1", "team_view 0")
        logs["red_client"] = logs["red_client"].replace("m1 lp0 c0", "m1 lp0 c1")
        _, checks = self.validate(logs)
        self.assertFalse(checks["blue_client_1_received_host_option"])
        self.assertFalse(checks["red_client_separate_machine_ownership"])

    def test_addresses_use_only_supplied_configured_interfaces(self):
        addresses = ["127.0.0.1", "127.0.0.2", "127.0.0.3", "192.168.0.4", "100.64.0.1"]
        self.assertEqual(default_addresses(addresses), ["192.168.0.4", "127.0.0.1", "127.0.0.2", "127.0.0.3"])
        self.assertEqual(default_addresses(["192.168.0.4", "127.0.0.1"]), [])

    def test_requested_metal_must_be_reported_by_all_four_instances(self):
        logs = {role: "Renderer active: Native Metal; hardware test\n" + log for role, log in self.logs().items()}
        _, checks = validate_logs(logs, logs, {role: 0 for role, _ in ROLES}, True, self.folders, "metal")
        self.assertTrue(all(checks.values()), checks)
        logs["red_client"] = logs["red_client"].replace("Renderer active: Native Metal", "Renderer active: ANGLE")
        _, checks = validate_logs(logs, logs, {role: 0 for role, _ in ROLES}, True, self.folders, "metal")
        self.assertFalse(checks["all_four_used_requested_renderer"])


if __name__ == "__main__":
    unittest.main()
