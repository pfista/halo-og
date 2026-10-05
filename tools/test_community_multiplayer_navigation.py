#!/usr/bin/env python3
"""Navigation controls and observed-state boundaries, without native gameplay claims."""
import copy
from pathlib import Path
import tempfile
import unittest

from community_multiplayer_navigation import control_for_delta, navigate_waypoint


class PairFixture:
    def __init__(self, folder, yaw=0, blocked=False, z=0):
        self.folder = Path(folder)
        self.record = {'player_roles': {'host': 1, 'client': 0}}
        self.tick, self.yaw, self.blocked = 30, yaw, blocked
        self.position = [0., 0., z]
        self.inputs = []

    def alive(self):
        pass

    def state(self, role):
        return [dict(tick=self.tick, players={1: dict(dead=False,
                    position=copy.copy(self.position), aim_yaw=self.yaw)})]

    def input(self, role, event, code, duration):
        self.inputs.append((role, event, code, duration))
        if not self.blocked:
            import math
            yaw = math.radians(self.yaw)
            vectors = {26: (math.cos(yaw), math.sin(yaw), 2.25),
                       22: (-math.cos(yaw), -math.sin(yaw), 2),
                       4: (-math.sin(yaw), math.cos(yaw), 2),
                       7: (math.sin(yaw), -math.cos(yaw), 2)}
            x, y, speed = vectors[code]
            self.position[0] += x * speed * duration / 1000
            self.position[1] += y * speed * duration / 1000
        return dict(acknowledged=True, code=code)

    def wait(self, predicate, message, timeout):
        self.tick += 30
        result = predicate()
        if not result:
            raise TimeoutError(message)
        return result


class NavigationBoundaries(unittest.TestCase):
    def test_keys_follow_measured_heading_after_teleport(self):
        self.assertEqual(control_for_delta(1, 0, 0)[0], 26)
        self.assertEqual(control_for_delta(-1, 0, 180)[0], 26)
        self.assertEqual(control_for_delta(0, 1, 180)[0], 7)
        self.assertEqual(control_for_delta(0, 1, 90)[0], 26)

    def test_native_pulses_are_bounded_even_for_far_or_near_points(self):
        self.assertEqual(control_for_delta(100, 0, 0)[1], 600)
        self.assertEqual(control_for_delta(.001, 0, 0)[1], 50)

    def test_arrival_uses_actual_owned_player_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            pair = PairFixture(folder, yaw=180)
            result = navigate_waypoint(pair, dict(role='host', target=[-2, .5, 0], max_seconds=10))
            self.assertTrue(result['reached'])
            self.assertEqual(result['player'], 1)
            self.assertTrue(result['pulses'])
            self.assertLessEqual(abs(pair.position[0] + 2), .22)
            self.assertLessEqual(abs(pair.position[1] - .5), .22)
            self.assertNotIn('coverage', result)

    def test_input_acknowledgement_without_movement_cannot_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            pair = PairFixture(folder, blocked=True)
            with self.assertRaisesRegex(RuntimeError, 'movement is blocked'):
                navigate_waypoint(pair, dict(role='host', target=[1, 0, 0], max_seconds=10))
            self.assertEqual(len(pair.inputs), 3)
            self.assertFalse(pair.record['navigation_attempts'][0]['reached'])

    def test_different_floor_cannot_be_accepted_or_automatically_jumped(self):
        with tempfile.TemporaryDirectory() as folder:
            pair = PairFixture(folder, z=3)
            with self.assertRaisesRegex(RuntimeError, 'different floor'):
                navigate_waypoint(pair, dict(role='host', target=[0, 0, 0]))
            self.assertEqual(pair.inputs, [])

    def test_nonfinite_waypoint_cannot_send_input(self):
        with tempfile.TemporaryDirectory() as folder:
            pair = PairFixture(folder)
            with self.assertRaises(ValueError):
                navigate_waypoint(pair, dict(role='host', target=[float('nan'), 0, 0]))
            self.assertEqual(pair.inputs, [])

    def test_unowned_role_cannot_send_input(self):
        with tempfile.TemporaryDirectory() as folder:
            pair = PairFixture(folder)
            with self.assertRaises(ValueError):
                navigate_waypoint(pair, dict(role='other', target=[1, 0, 0]))
            self.assertEqual(pair.inputs, [])

    def test_observed_teleport_stops_input_toward_the_old_entry(self):
        class TeleportFixture(PairFixture):
            def input(self, role, event, code, duration):
                result = super().input(role, event, code, duration)
                if self.position[0] >= .8:
                    self.position = [10, 10, 0]
                    self.yaw = 180
                return result
        with tempfile.TemporaryDirectory() as folder:
            pair = TeleportFixture(folder)
            result = navigate_waypoint(pair, dict(role='host', target=[1, 0, 0],
                                                 arrival_target=[10, 10, 0]))
            self.assertTrue(result['observed_transition_arrival'])
            self.assertEqual(len(pair.inputs), 1)

    def test_match_end_stops_navigation_without_claiming_arrival_or_score(self):
        class EndFixture(PairFixture):
            def state(self, role):
                rows = super().state(role)
                rows[0]['game_over'] = bool(self.inputs)
                return rows
        with tempfile.TemporaryDirectory() as folder:
            pair = EndFixture(folder)
            result = navigate_waypoint(pair, dict(role='host', target=[10, 0, 0],
                                                 allow_game_over=True))
            self.assertTrue(result['interrupted_by_match_end'])
            self.assertFalse(result['reached'])
            self.assertNotIn('coverage', result)
            self.assertEqual(len(pair.inputs), 1)

    def test_starting_at_portal_destination_cannot_claim_a_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            pair = PairFixture(folder)
            with self.assertRaisesRegex(RuntimeError, 'not start at its destination'):
                navigate_waypoint(pair, dict(role='host', target=[10, 0, 0],
                                             arrival_target=[0, 0, 0]))
            self.assertEqual(pair.inputs, [])
            self.assertFalse(pair.record['navigation_attempts'][0]['reached'])
            self.assertNotIn('observed_transition_arrival', pair.record['navigation_attempts'][0])


if __name__ == '__main__':
    unittest.main()
