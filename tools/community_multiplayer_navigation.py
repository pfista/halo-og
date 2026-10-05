#!/usr/bin/env python3
"""Bounded ordinary-input navigation for owned multiplayer test peers.

Waypoints belong to a separately reviewed map profile. This diagnostic helper
does not change positions, velocity, health, objectives or native game rules.
Reaching a waypoint does not establish objective scoring or a completed route.
"""
import json
import math
import time


def control_for_delta(dx, dy, yaw):
    """Choose one horizontal native key from the measured heading, in degrees."""
    radians = math.radians(yaw)
    forward = (math.cos(radians), math.sin(radians))
    left = (-forward[1], forward[0])
    # These are diagnostic estimates from the reviewed native movement globals.
    # Actual progress, rather than these speeds, decides whether a point is met.
    candidates = ((26, forward, 2.25), (22, tuple(-v for v in forward), 2.0),
                  (4, left, 2.0), (7, tuple(-v for v in left), 2.0))
    code, direction, speed = max(candidates, key=lambda item: dx * item[1][0] + dy * item[1][1])
    projected = dx * direction[0] + dy * direction[1]
    duration = max(50, min(600, round(projected / speed * 1000)))
    return code, duration


def navigate_waypoint(pair, action):
    role = action.get('role')
    target = action.get('target')
    arrival = action.get('arrival_target')
    tolerance = action.get('tolerance', .22)
    arrival_tolerance = action.get('arrival_tolerance', .75)
    allow_end = action.get('allow_game_over', False)
    vertical = action.get('vertical_tolerance', .55)
    maximum = action.get('max_seconds', 30)
    if (role not in {'host', 'client'} or not isinstance(target, list) or len(target) != 3
            or any(type(value) not in {int, float} or not math.isfinite(value) for value in target)
            or (arrival is not None and (not isinstance(arrival, list) or len(arrival) != 3
                or any(type(value) not in {int, float} or not math.isfinite(value) for value in arrival)))
            or any(type(value) not in {int, float} or not math.isfinite(value)
                   for value in (tolerance, arrival_tolerance, vertical, maximum))
            or type(allow_end) is not bool
            or not .05 <= tolerance <= 2 or not .05 <= arrival_tolerance <= 2
            or not .05 <= vertical <= 2 or not 1 <= maximum <= 60):
        raise ValueError('Navigation needs an owned peer, finite target, bounded tolerance and lifetime')
    player = pair.record['player_roles'][role]
    started = time.monotonic()
    deadline = started + maximum
    result = dict(role=role, player=player, target=target, tolerance=tolerance,
                  vertical_tolerance=vertical, pulses=[], reached=False,
                  scope='Observed position from ordinary native WASD input; no objective coverage inferred')
    if arrival is not None:
        result.update(arrival_target=arrival, arrival_tolerance=arrival_tolerance)
    pair.record.setdefault('navigation_attempts', []).append(result)

    def persist():
        (pair.folder / 'navigation-progress.json').write_text(json.dumps(
            pair.record['navigation_attempts'], indent=2) + '\n')

    def state():
        rows = pair.state(role)
        if not rows or player not in rows[-1]['players']:
            raise RuntimeError('Owned player has no current navigation state')
        sample = rows[-1]
        current = sample['players'][player]
        if not (allow_end and sample.get('game_over')) and (
                current['dead'] or current['position'] is None or current.get('aim_yaw') is None):
            raise RuntimeError('Navigation requires an alive owned player with position and heading')
        return sample, current

    def ended(sample):
        if allow_end and sample.get('game_over'):
            result.update(interrupted_by_match_end=True, final_sample=sample,
                          elapsed_seconds=time.monotonic() - started)
            persist()
            return True
        return False

    def observed_after(tick):
        sample, current = state()
        if sample['tick'] < tick:
            raise RuntimeError('Match changed during a navigation waypoint')
        return (sample, current) if sample['tick'] > tick else None

    stalled = 0
    try:
        while time.monotonic() < deadline:
            pair.alive()
            before_sample, before = state()
            if ended(before_sample):
                return result
            position = before['position']
            dx, dy = target[0] - position[0], target[1] - position[1]
            horizontal = math.hypot(dx, dy)
            if arrival is not None and math.dist(position, arrival) <= arrival_tolerance:
                if not result['pulses']:
                    raise RuntimeError('Portal arrival must follow observed ordinary movement, not start at its destination')
                result.update(reached=True, observed_transition_arrival=True, final_sample=before_sample,
                              elapsed_seconds=time.monotonic() - started)
                persist()
                return result
            if horizontal <= tolerance:
                if arrival is not None:
                    raise RuntimeError('Entry waypoint reached without its reviewed transition arrival')
                if abs(target[2] - position[2]) > vertical:
                    raise RuntimeError('Planar waypoint reached on a different floor; route needs review')
                result.update(reached=True, final_sample=before_sample,
                              elapsed_seconds=time.monotonic() - started)
                persist()
                return result
            code, duration = control_for_delta(dx, dy, before['aim_yaw'])
            delivery = pair.input(role, 'key', code, duration)
            # Wait for a sample after key release; an input acknowledgement or
            # an in-flight position cannot establish arrival.
            released_tick = state()[0]['tick']
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            after_sample, after = pair.wait(lambda: observed_after(released_tick),
                                             'No post-input navigation sample', min(3, remaining))
            if ended(after_sample):
                return result
            movement = math.dist(position, after['position'])
            stalled = stalled + 1 if movement < .025 else 0
            result['pulses'].append(dict(delivery=delivery, before=before_sample,
                                         after=after_sample, measured_movement=movement))
            persist()
            if stalled >= 3:
                raise RuntimeError('Ordinary movement is blocked; waypoint route needs review')
        raise TimeoutError('Owned player did not reach the waypoint within its bounded lifetime')
    except BaseException as error:
        result.update(error=str(error), elapsed_seconds=time.monotonic() - started)
        persist()
        raise
