#!/usr/bin/env python3
"""State and fixture-boundary checks; native peers remain separate evidence."""
import json
from pathlib import Path
import tempfile
import unittest

from macos_community_multiplayer import COUNT_PREDICATES, Pair, bind_player_expression, clean_native_environment, native_samples, profile, samples, transition, validated_addresses


def line(tick, player, score=0, kills=0, deaths=0, rounds=30, health=1, shield=1, dead=False, over=False):
    state = 'dead' if dead else f'(1.000 2.000 3.000) h{health:.2f}/{shield:.2f} g2/2 w a0/0 f0 l0/0 as1/1 st0 thr0.00 1a:{rounds}'
    return f'network test: tick {tick} player {player}: {state} s{score} k{kills} d{deaths} f0 t1 m1 | items 3 (+0 -0 !0 x0) | {"game over" if over else "playing"} to 5 | sent 7 received 8 corrected 0\n'


class NativeEvidence(unittest.TestCase):
    def test_parser_preserves_dead_player_statistics_and_cache_inventory(self):
        alive = samples(line(30, 1))[0]
        self.assertEqual(alive['players'][1]['weapons'], {'1a': 30})
        self.assertEqual(alive['players'][1]['position'], [1, 2, 3])
        self.assertEqual(alive['players'][1]['aim_yaw'], 0)
        self.assertEqual(alive['players'][1]['aim_pitch'], 0)
        dead = samples(line(60, 1, kills=2, deaths=3, dead=True))[0]
        self.assertTrue(dead['players'][1]['dead'])
        self.assertEqual(dead['players'][1]['deaths'], 3)
        self.assertEqual(dead['players'][1]['kills'], 2)
        local = samples(line(90, 1).strip() + ' | local 1 camera (1.0 2.0 3.0) respawn 0\n')[0]
        self.assertEqual(local['local_player'], 1)

    def test_fire_input_or_unchanged_ammo_cannot_establish_damage(self):
        before = samples(line(30, 1))[0]
        after = samples(line(60, 1, rounds=29))[0]
        self.assertIsNotNone(transition('ammo_decrease', before, [after], tag='1a'))
        self.assertIsNone(transition('damage', before, [after]))
        wounded = samples(line(90, 1, health=.9, shield=.5))[0]
        self.assertIsNotNone(transition('damage', before, [wounded]))

    def test_death_respawn_requires_same_player_observed_dead_then_alive(self):
        before = samples(line(30, 1))[0]
        unrelated = samples(line(60, 0, dead=True))[0]
        alive = samples(line(90, 1, deaths=1))[0]
        self.assertIsNone(transition('death_respawn', before, [unrelated, alive]))
        dead = samples(line(60, 1, dead=True, deaths=1))[0]
        self.assertIsNotNone(transition('death_respawn', before, [dead, alive]))

    def test_attributed_kill_needs_selected_killer_and_selected_target(self):
        def pair(tick, kills, deaths):
            victim = f' player 1: dead s0 k0 d{deaths} f0 t1 m1 | items'
            return samples(line(tick, 0, kills=kills).replace(' | items', victim, 1))[0]
        before = pair(30, 0, 0)
        self.assertIsNone(transition('credited_kill', before, [pair(60, 0, 1)], player=0, target_player=1))
        self.assertIsNone(transition('credited_kill', before, [pair(60, 1, 0)], player=0, target_player=1))
        self.assertIsNotNone(transition('credited_kill', before, [pair(60, 1, 1)], player=0, target_player=1))

    def test_objective_score_rejects_kill_score(self):
        before = samples(line(30, 1))[0]
        kill = samples(line(60, 1, score=1, kills=1))[0]
        objective = samples(line(90, 1, score=1))[0]
        self.assertIsNone(transition('objective_score', before, [kill]))
        self.assertIsNotNone(transition('objective_score', before, [objective]))
        self.assertIsNotNone(transition('score_increase', before, [kill]))

    def test_race_checkpoint_progress_cannot_establish_a_completed_lap(self):
        before = samples(line(30, 1))[0]
        checkpoints = samples(line(60, 1, score=12))[0]
        lap = samples(line(90, 1, score=33))[0]
        self.assertIsNone(transition('race_lap', before, [checkpoints]))
        self.assertIsNotNone(transition('race_lap', before, [lap]))

    def test_same_match_winning_score_survives_native_unit_removal(self):
        before = samples(line(30, 1))[0]
        removed_after_lap = samples(line(60, 1, score=33, dead=True, over=True))[0]
        self.assertIsNotNone(transition('race_lap', before, [removed_after_lap]))
        capture = samples(line(60, 1, score=1, dead=True, over=True))[0]
        self.assertIsNotNone(transition('objective_score', before, [capture]))
        self.assertIsNotNone(transition('score_increase', before, [capture]))
        self.assertIsNone(transition('ammo_decrease', before, [capture], tag='1a'))
        self.assertIsNone(transition('damage', before, [capture]))
        reset = samples(line(15, 1, score=33, dead=True, over=True))[0]
        self.assertIsNone(transition('race_lap', before, [reset]))
        dead_before_assignment = samples(line(30, 1, dead=True))[0]
        live_initial_inventory = samples(line(60, 1))[0]
        self.assertIsNone(transition('weapon_acquired', dead_before_assignment, [live_initial_inventory], tag='1a'))

    def test_reusable_count_predicates_reject_nonpositive_noninteger_and_bool_thresholds(self):
        before = samples(line(30, 1))[0]
        unchanged = samples(line(60, 1))[0]
        for predicate in COUNT_PREDICATES:
            for minimum in (0, -1, True, False, 1.0, float('nan'), float('inf'), '1'):
                with self.subTest(predicate=predicate, minimum=minimum), self.assertRaises(ValueError):
                    transition(predicate, before, [unchanged], minimum=minimum)
            self.assertIsNone(transition(predicate, before, [unchanged], minimum=1))
        # Respawn evidence still needs the actual death transition; it never
        # qualifies merely because an unrelated count threshold is zero.
        self.assertIsNone(transition('death_respawn', before, [unchanged], minimum=0))

    def test_match_end_and_rematch_need_live_network_state(self):
        before = samples(line(300, 1))[0]
        over = samples(line(330, 1, over=True))[0]
        alone = samples(line(30, 1))[0]
        def joined(tick, dead=False, empty=False, received=8):
            details = 'dead' if dead else '(1.000 2.000 3.000) h1.0/1.0 a0/0 1a:30'
            text = line(tick, 0, dead=dead).replace(' | items', f' player 1: {details} s0 k0 d0 f0 t1 m1 | items', 1)
            if empty:
                text = text.replace('1a:30', '')
            return samples(text.replace('received 8', 'received ' + str(received)))[0]
        self.assertIsNotNone(transition('game_over', before, [over]))
        self.assertIsNone(transition('rematch', before, [alone]))
        self.assertIsNone(transition('rematch', before, [joined(30), joined(60, received=9)]))
        self.assertIsNone(transition('rematch', before, [over, joined(30)]))
        for invalid in ({'dead': True}, {'empty': True}, {'received': 0}):
            with self.subTest(invalid=invalid):
                self.assertIsNone(transition('rematch', before, [over, joined(30, **invalid), joined(60, **invalid)]))
        self.assertIsNone(transition('rematch', before, [over, joined(30), joined(60)]))
        self.assertIsNotNone(transition('rematch', before, [over, joined(30), joined(60, received=9)]))

    def test_match_local_evidence_never_crosses_a_native_tick_reset(self):
        before = samples(line(90, 1))[0]
        after_reset = samples(line(30, 1, score=33, kills=1, rounds=1, health=.1, shield=.1, over=True))[0]
        for predicate in ('ammo_decrease', 'damage', 'score_increase', 'race_lap', 'game_over', 'position'):
            with self.subTest(predicate=predicate):
                self.assertIsNone(transition(predicate, before, [after_reset], target=[1, 2, 3]))
        def pair(tick, kills, deaths):
            victim = f' player 1: dead s0 k0 d{deaths} f0 t1 m1 | items'
            return samples(line(tick, 0, kills=kills).replace(' | items', victim, 1))[0]
        self.assertIsNone(transition('credited_kill', pair(90, 0, 0), [pair(30, 1, 1)],
                                     player=0, target_player=1))
        # Also catch a reset to the checkpoint's own tick after progress.
        progressed = samples(line(120, 1))[0]
        reset_to_checkpoint = samples(line(90, 1, score=1))[0]
        self.assertIsNone(transition('objective_score', before, [progressed, reset_to_checkpoint]))

    def test_native_debug_fallback_never_concatenates_mirrors_into_false_tick_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'saves').mkdir()
            (folder / 'data').mkdir()
            (folder / 'saves/halo.log').write_text('Native host startup only\n')
            (folder / 'data/debug.txt').write_text(line(30, 1) + line(60, 1))
            self.assertEqual([row['tick'] for row in native_samples(folder)], [30, 60])
            (folder / 'saves/halo.log').write_text(line(30, 1) + line(60, 1))
            self.assertEqual([row['tick'] for row in native_samples(folder)], [30, 60])

    def test_position_evidence_checks_exact_finite_xyz_and_bounded_radius(self):
        before = samples(line(30, 1))[0]
        later = samples(line(60, 1))[0]
        for target, tolerance in (([1, 2], .5), ([1, 2, 3, 4], .5), ([1, 2, float('nan')], .5),
                                  ([1, 2, 3], 0), ([1, 2, 3], 3), ([1, 2, 3], float('inf')), ([1, 2, 3], True)):
            with self.subTest(target=target, tolerance=tolerance), self.assertRaises(ValueError):
                transition('position', before, [later], target=target, tolerance=tolerance)
        self.assertIsNone(transition('position', before, [later], target=[1, 2, 9], tolerance=.5))
        self.assertIsNotNone(transition('position', before, [later], target=[1, 2, 3], tolerance=.5))

    def test_pair_pins_original_tick_stream_before_offsets_and_never_switches_to_longer_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            def paired(tick):
                return line(tick, 0).replace(' | items', ' player 1: (1.000 2.000 3.000) h1.0/1.0 a0/0 1a:30 s0 k0 d0 f0 t1 m1 | items', 1)
            for role in ('host', 'client'):
                (folder / role / 'saves').mkdir(parents=True)
                (folder / role / 'data').mkdir()
                (folder / role / 'saves/halo.log').write_text(paired(30) + paired(60))
                (folder / role / 'data/debug.txt').write_text(paired(30))
            pair = Pair(folder, {}, {})
            with self.assertRaises(RuntimeError):
                pair.checkpoint('unbound')
            pair.pin_state_streams()
            checkpoint = pair.checkpoint('bound')
            self.assertEqual(checkpoint['host']['offset'], 2)
            (folder / 'host/data/debug.txt').write_text(paired(300) + paired(330) + paired(30))
            self.assertEqual([row['tick'] for row in pair.state('host')], [30, 60])
            self.assertTrue(pair.record['network_state_streams']['host'].endswith('saves/halo.log'))


class ReviewedProfiles(unittest.TestCase):
    def load(self, action, mode='slayer'):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            path.write_text(json.dumps({'schema_version': 1, 'mode': mode, 'actions': [action]}))
            return profile(path, mode)

    def test_direct_damage_and_cheats_cannot_create_qualification(self):
        for command in ('(set cheat_deathless_player true)', '(unit_set_current_vitality none .1 .1)', '(game_won)'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.load({'kind': 'host_command', 'expression': command})

    def test_ordinary_host_positioning_and_bounded_native_input_are_allowed(self):
        self.load({'kind': 'host_command', 'expression': '(object_teleport (unit (list_get (players) 1)) camo_flag)'})
        self.load({'kind': 'input', 'role': 'client', 'event': 'mouse', 'code': 1, 'hold_ms': 1000})
        with self.assertRaises(ValueError):
            self.load({'kind': 'input', 'role': 'client', 'event': 'mouse', 'code': 1, 'hold_ms': 5000})

    def test_slayer_and_missing_tag_cannot_claim_objective_or_pickup(self):
        with self.assertRaises(ValueError):
            self.load({'kind': 'assert_transition', 'from': 'joined', 'predicate': 'objective_score'})
        with self.assertRaises(ValueError):
            self.load({'kind': 'assert_transition', 'from': 'joined', 'predicate': 'weapon_acquired'})

    def test_profiles_require_positive_integer_counts_for_observed_changes(self):
        for predicate in COUNT_PREDICATES:
            mode = 'race' if predicate == 'race_lap' else 'king'
            action = {'kind': 'assert_transition', 'from': 'joined', 'predicate': predicate,
                      'player': 0, 'target_player': 1}
            self.load({**action, 'minimum': 1}, mode)
            for minimum in (0, -1, True, False, 1.0, float('nan'), float('inf'), '1'):
                with self.subTest(predicate=predicate, minimum=minimum), self.assertRaises(ValueError):
                    self.load({**action, 'minimum': minimum}, mode)

    def test_profile_positions_cannot_drop_z_or_use_invalid_tolerances(self):
        action = {'kind': 'assert_transition', 'from': 'joined', 'predicate': 'position'}
        self.load({**action, 'target': [1, 2, 3], 'tolerance': .5})
        for fields in ({'target': [1, 2]}, {'target': [1, 2, float('nan')]},
                       {'target': [1, 2, 3], 'tolerance': 0}, {'target': [1, 2, 3], 'tolerance': 3}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.load({**action, **fields})

    def test_profile_cache_binding_rejects_another_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            path.write_text(json.dumps({'schema_version': 1, 'mode': 'slayer',
                                        'map_sha256': 'a' * 64, 'actions': []}))
            profile(path, 'slayer', 'a' * 64)
            with self.assertRaises(ValueError):
                profile(path, 'slayer', 'b' * 64)

    def test_inherited_native_cheat_transport_and_library_overrides_are_removed(self):
        environment = clean_native_environment({'PATH': '/usr/bin', 'HALO_CHEATS': 'true',
                                               'HALO_NETWORK_PUBLIC_GAMES': 'true',
                                               'DYLD_INSERT_LIBRARIES': '/unrelated/library.dylib',
                                               'POC_DIAG_EVENT_FILE': '/unrelated/events.txt'})
        self.assertEqual(environment, {'PATH': '/usr/bin'})

    def test_attributed_kills_need_a_distinct_reviewed_target(self):
        with self.assertRaises(ValueError):
            self.load({'kind': 'assert_transition', 'from': 'joined', 'predicate': 'credited_kill', 'player': 0})
        with self.assertRaises(ValueError):
            self.load({'kind': 'assert_transition', 'from': 'joined', 'predicate': 'credited_kill', 'player': 0, 'target_player': 0})
        self.load({'kind': 'assert_transition', 'from': 'joined', 'predicate': 'credited_kill', 'player': 0, 'target_player': 1})

    def test_lan_uses_only_configured_distinct_addresses_and_preserves_native_self_sentinel(self):
        configured = ['127.0.0.1', '127.0.0.2', '127.0.0.3']
        self.assertEqual(validated_addresses('127.0.0.2', '127.0.0.3', configured, 'lan'),
                         ('127.0.0.2', '127.0.0.3'))
        for host, client in [('127.0.0.1', '127.0.0.2'), ('127.0.0.2', '127.0.0.2'), ('127.0.0.2', '127.0.0.4')]:
            with self.subTest(host=host, client=client), self.assertRaises(ValueError):
                validated_addresses(host, client, configured, 'lan')

    def test_hs_selectors_follow_stock_reverse_live_player_order(self):
        expression = '(object_teleport (unit (list_get (players) 0)) delete_flame)'
        bound, mapping = bind_player_expression(expression, {0: {'dead': False}, 1: {'dead': False}})
        self.assertIn('(list_get (players) 1)', bound)
        self.assertEqual(mapping, {1: 0, 0: 1})
        expression = '(object_teleport (unit (list_get (players) 1)) delete_flame)'
        bound, mapping = bind_player_expression(expression, {0: {'dead': True}, 1: {'dead': False}})
        self.assertIn('(list_get (players) 0)', bound)
        with self.assertRaises(ValueError):
            bind_player_expression('(list_get (players) 0)', {0: {'dead': True}, 1: {'dead': False}})

    def test_navigation_only_accepts_bounded_owned_finite_targets(self):
        self.load({'kind': 'navigate_waypoint', 'role': 'host', 'target': [1, 2, 3], 'max_seconds': 20})
        self.load({'kind': 'navigate_waypoint', 'role': 'host', 'target': [1, 2, 3], 'allow_game_over': True})
        for target in ([1, 2], [1, 2, float('nan')], [1, 2, True]):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.load({'kind': 'navigate_waypoint', 'role': 'host', 'target': target})
        with self.assertRaises(ValueError):
            self.load({'kind': 'navigate_waypoint', 'role': 'host', 'target': [1, 2, 3], 'max_seconds': 90})
        with self.assertRaises(ValueError):
            self.load({'kind': 'navigate_waypoint', 'role': 'host', 'target': [1, 2, 3], 'allow_game_over': 'true'})
        for field in ('tolerance', 'arrival_tolerance', 'vertical_tolerance', 'max_seconds'):
            for value in (True, float('nan'), float('inf'), '1'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.load({'kind': 'navigate_waypoint', 'role': 'host', 'target': [1, 2, 3], field: value})

    def test_lap_assertions_only_qualify_reviewed_race_modes(self):
        action = {'kind': 'assert_transition', 'from': 'joined', 'predicate': 'race_lap'}
        with self.assertRaises(ValueError):
            self.load(action)
        self.load(action, mode='race')
        self.load(action, mode='team_race')


if __name__ == '__main__':
    unittest.main()
