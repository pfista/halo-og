#!/usr/bin/env python3
"""Reviewable local multiplayer checks for a converted community cache.

Snapshot copies an existing native app; prepare never launches. Run uses two
owned peers, isolated saves, a reviewed LAN or private-invite transport, and an
explicitly hash-bound cache. Private invites use the application's established
MQTT brokers; their external signalling destinations need launch authorization.
Profiles are diagnostic fixtures: host console positioning and child-local SDL
input exercise ordinary game rules without changing the cache or engine.
Synthetic network_test_shoot/kill are disabled and cannot establish damage,
objective, score or match-transition coverage. No publishing or installation.
"""
import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time

from community_maps import cache_header
from macos_benchmark import Console, FAULT
from macos_multiplayer_smoke import ROOT, prepare, read_log
from macos_performance_smoke import free_port

MODES = ('slayer', 'team_slayer', 'ctf', 'oddball', 'team_oddball',
         'king', 'team_king', 'race', 'team_race')
TEAM_MODES = {'team_slayer', 'ctf', 'team_oddball', 'team_king', 'team_race'}
TICKS = re.compile(r'network test: tick (\d+)([^\n]*)')
PLAYERS = re.compile(r'player (\d+): (.*?)(?= player \d+:| \||$)')
AMMO = re.compile(r'(?:^| )([0-9a-f]+):(\d+)(?= |$)')
VITALITY = re.compile(r' h([\d.-]+)/([\d.-]+)')
STATS = re.compile(r' s(-?\d+) k(\d+) d(\d+) f(\d+) t(-?\d+) m(-?\d+)')
POSITION = re.compile(r'^\(([-\d.]+) ([-\d.]+) ([-\d.]+)\)')
AIM = re.compile(r' a([-\d.]+)/([-\d.]+) ')
WARNINGS = re.compile(r'YOU GOT STABBED|SOUND CACHE.*BLOWN|attempt to play a sound that was not|NETGAME MAP FAILURE', re.I)
PREDICATES = {'ammo_decrease', 'weapon_acquired', 'damage', 'death_respawn',
              'credited_kill', 'score_increase', 'objective_score', 'race_lap', 'game_over', 'rematch', 'position'}
COUNT_PREDICATES = {'ammo_decrease', 'credited_kill', 'score_increase', 'objective_score', 'race_lap'}


def reviewed_minimum(value):
    """A count must represent a real positive change, never unchanged state."""
    if type(value) is not int or value < 1:
        raise ValueError('Count assertions require a strict positive integer minimum')
    return value


def reviewed_position(target, tolerance):
    """Position evidence must measure all three axes and a reviewed radius."""
    if (not isinstance(target, list) or len(target) != 3 or
            any(type(value) not in {int, float} or not math.isfinite(value) for value in target) or
            type(tolerance) not in {int, float} or not math.isfinite(tolerance) or
            not .05 <= tolerance <= 2):
        raise ValueError('Position assertions need finite targetXYZ and tolerance between .05 and 2')


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def samples(text):
    result = []
    for match in TICKS.finditer(text):
        line = match[0]
        players = {}
        for player in PLAYERS.finditer(line):
            details = player[2]
            stats = STATS.search(details)
            vitality = VITALITY.search(details)
            position = POSITION.search(details)
            aim = AIM.search(details)
            players[int(player[1])] = dict(
                dead=details.startswith('dead'),
                health=float(vitality[1]) if vitality else None,
                shield=float(vitality[2]) if vitality else None,
                position=list(map(float, position.groups())) if position else None,
                aim_yaw=float(aim[1]) if aim else None,
                aim_pitch=float(aim[2]) if aim else None,
                weapons={tag.lower(): int(rounds) for tag, rounds in AMMO.findall(details)},
                score=int(stats[1]) if stats else None,
                kills=int(stats[2]) if stats else None,
                deaths=int(stats[3]) if stats else None,
                friendly_kills=int(stats[4]) if stats else None,
                team=int(stats[5]) if stats else None,
                machine=int(stats[6]) if stats else None)
        received = re.search(r' received (\d+)', line)
        local = re.search(r' \| local (-?\d+) ', line)
        result.append(dict(tick=int(match[1]), players=players,
                           playing=' | playing to ' in line,
                           game_over=' | game over to ' in line,
                           received=int(received[1]) if received else 0,
                           local_player=int(local[1]) if local else None, line=line))
    return result


def native_stream(folder):
    """Select one coherent stream; native logging can move to debug.txt.

    Never concatenate mirrored tick streams: that could manufacture a tick
    reset and falsely establish a rematch. Original files remain the evidence.
    """
    paths = (folder / 'game.log', folder / 'saves/halo.log', folder / 'data/debug.txt')
    streams = [(path, samples(path.read_text(errors='replace'))) for path in paths if path.exists()]
    return max(streams, key=lambda value: len(value[1]), default=(None, []))


def native_samples(folder):
    return native_stream(folder)[1]


def transition(predicate, before, later, player=1, tag=None, minimum=1, target=None, tolerance=.5, target_player=None):
    """Return observed state evidence, never infer success from input alone."""
    if predicate in COUNT_PREDICATES:
        reviewed_minimum(minimum)
    if predicate == 'position':
        reviewed_position(target, tolerance)
    prior = before['players'].get(player)
    if predicate == 'rematch':
        previous = before['tick']
        saw_game_over = before['game_over']
        reset = False
        live_tick = None
        live_received = None
        for sample in later:
            saw_game_over |= sample['game_over']
            if sample['tick'] < previous:
                if not saw_game_over:
                    return None
                reset = True
                live_tick = live_received = None
            live = (reset and sample['playing'] and not sample['game_over'] and
                    sample['received'] > 0 and len(sample['players']) >= 2 and
                    all(not value['dead'] and value['weapons'] for value in sample['players'].values()))
            if live:
                if (live_tick is not None and sample['tick'] > live_tick and
                        sample['received'] > live_received):
                    return sample
                live_tick, live_received = sample['tick'], sample['received']
            else:
                live_tick = live_received = None
            previous = sample['tick']
        return None
    saw_dead = bool(prior and prior['dead'])
    previous = before['tick']
    for sample in later:
        # Match-local counters, ammo and vitality cannot qualify an action in
        # a later game. Only the explicit rematch predicate crosses a reset.
        if sample['tick'] < previous:
            return None
        previous = sample['tick']
        current = sample['players'].get(player)
        if predicate == 'game_over' and sample['game_over']:
            return sample
        if not current:
            continue
        if predicate == 'credited_kill' and prior:
            victim_before = before['players'].get(target_player)
            victim_now = sample['players'].get(target_player)
            if victim_before and victim_now and all(value is not None for value in
                    (prior['kills'], current['kills'], victim_before['deaths'], victim_now['deaths'])):
                if (current['kills'] - prior['kills'] >= minimum and
                        victim_now['deaths'] - victim_before['deaths'] >= minimum and
                        current['friendly_kills'] == prior['friendly_kills']):
                    return sample
        if predicate == 'death_respawn':
            saw_dead |= current['dead']
            if saw_dead and not current['dead'] and current['weapons']:
                return sample
        if (predicate == 'weapon_acquired' and prior and not prior['dead'] and not current['dead'] and
                tag in current['weapons'] and tag not in prior['weapons']):
            return sample
        if predicate == 'position' and target and current['position'] and sum(
                (a - b) ** 2 for a, b in zip(current['position'], target)) <= tolerance ** 2:
            return sample
        # Native end-of-match logs retain player score statistics even when
        # their unit is already removed. A real lap/capture must remain visible
        # in that same match; ammo and vitality still require a live unit.
        if predicate == 'race_lap' and prior and prior['score'] is not None and current['score'] is not None:
            # Stock Race individual score = laps * 33 + touched flags (0..12
            # on this authored course). Team Race native ticks also log the
            # individual score, so checkpoint progress alone is not a lap.
            if prior['score'] >= 0 and current['score'] >= 0 and current['score'] // 33 - prior['score'] // 33 >= minimum:
                return sample
        if predicate in {'score_increase', 'objective_score'} and prior and prior['score'] is not None and current['score'] is not None:
            if current['score'] - prior['score'] >= minimum:
                # An objective score must increase without a credited kill.
                if predicate != 'objective_score' or current['kills'] == prior['kills']:
                    return sample
        if not prior or current['dead'] or prior['dead']:
            continue
        if predicate == 'ammo_decrease':
            common = set(prior['weapons']) & set(current['weapons'])
            if tag is not None:
                common &= {tag}
            if any(prior['weapons'][key] - current['weapons'][key] >= minimum for key in common):
                return sample
        if predicate == 'damage' and prior['health'] is not None and current['health'] is not None:
            if current['health'] + current['shield'] < prior['health'] + prior['shield'] - .005:
                return sample
    return None


def profile(path, mode, map_sha256=None):
    value = json.loads(Path(path).read_text()) if path else {'schema_version': 1, 'mode': mode, 'actions': []}
    if value.get('schema_version') != 1 or value.get('mode') != mode:
        raise ValueError('Profile schema_version=1 and mode must match the requested game')
    if 'map_sha256' in value and (not re.fullmatch('[0-9a-f]{64}', str(value['map_sha256'])) or
                                  map_sha256 is not None and value['map_sha256'] != map_sha256):
        raise ValueError('Profile map_sha256 must match the reviewed candidate cache')
    if not isinstance(value.get('actions'), list):
        raise ValueError('Profile actions must be an ordered list')
    if 'player_roles' in value:
        roles = value['player_roles']
        if (not isinstance(roles, dict) or set(roles) != {'host', 'client'} or
                any(not isinstance(index, int) or not 0 <= index < 16 for index in roles.values()) or
                roles['host'] == roles['client']):
            raise ValueError('Profile player_roles needs distinct host/client player indices')
    if value.get('hs_player_indices', 'native_list') not in {'native_list', 'absolute'}:
        raise ValueError('hs_player_indices must be native_list or absolute')
    for action in value['actions']:
        kind = action.get('kind')
        if kind not in {'host_command', 'input', 'wait', 'checkpoint', 'assert_transition', 'capture', 'navigate_waypoint'}:
            raise ValueError('Unsupported profile action: ' + str(kind))
        if kind == 'host_command':
            command = action.get('expression', '')
            if not isinstance(command, str) or not 0 < len(command.encode('ascii')) < 128 or '\n' in command or '\r' in command:
                raise ValueError('Host commands must fit the 127-byte native console buffer')
            if re.search(r'cheat|game_speed|game_won|game_lost|game_variant|object_cause_damage|damage_|current_vitality|object_set_shield|unit_kill', command, re.I):
                raise ValueError('Cheats, direct damage and forced match results cannot be qualification fixtures')
        if kind in {'input', 'capture', 'navigate_waypoint'} and action.get('role') not in {'host', 'client'}:
            raise ValueError('Input/capture must name an owned peer')
        if kind == 'navigate_waypoint':
            target = action.get('target')
            bounds = (action.get('tolerance', .22), action.get('arrival_tolerance', .75),
                      action.get('vertical_tolerance', .55), action.get('max_seconds', 30))
            if (not isinstance(target, list) or len(target) != 3 or
                    any(type(value) not in {int, float} or not math.isfinite(value) for value in target) or
                    any(type(value) not in {int, float} or not math.isfinite(value) for value in bounds) or
                    any(not .05 <= value <= 2 for value in bounds[:3]) or
                    not 1 <= bounds[3] <= 60):
                raise ValueError('Navigation needs a finite targetXYZ, bounded tolerance and timeout')
            if type(action.get('allow_game_over', False)) is not bool:
                raise ValueError('Navigation allow_game_over must be an explicit boolean')
            if 'arrival_target' in action:
                arrival = action['arrival_target']
                if (not isinstance(arrival, list) or len(arrival) != 3 or
                        any(type(value) not in {int, float} or not math.isfinite(value) for value in arrival)):
                    raise ValueError('Reviewed portal arrival needs a finite targetXYZ and bounded tolerance')
        if kind == 'input':
            event = action.get('event')
            code, duration = action.get('code'), action.get('hold_ms', 150)
            if not isinstance(code, int) or event not in {'key', 'mouse', 'look_x', 'look_y'}:
                raise ValueError('Input needs a supported event and integer code')
            if not 50 <= duration <= 4000 or not (
                    (event == 'key' and 0 < code < 512) or
                    (event == 'mouse' and 1 <= code <= 5) or
                    (event.startswith('look_') and -1000 <= code <= 1000)):
                raise ValueError('Input must be a bounded native pulse or relative look delta')
        if kind == 'wait' and not 0 <= action.get('seconds', -1) <= 60:
            raise ValueError('Fixture waits must be between zero and 60 seconds')
        if kind == 'assert_transition':
            if action.get('predicate') not in PREDICATES or not 1 <= action.get('timeout', 15) <= 60:
                raise ValueError('Assertions need a supported predicate and bounded timeout')
            if action['predicate'] in COUNT_PREDICATES:
                reviewed_minimum(action.get('minimum', 1))
            if action['predicate'] == 'position':
                reviewed_position(action.get('target'), action.get('tolerance', .5))
            if action['predicate'] == 'objective_score' and mode in {'slayer', 'team_slayer'}:
                raise ValueError('Slayer kills cannot establish objective scoring')
            if action['predicate'] == 'race_lap' and mode not in {'race', 'team_race'}:
                raise ValueError('Race lap evidence needs a Race mode')
            if 'tag' in action and not re.fullmatch('[0-9a-f]{1,4}', action['tag']):
                raise ValueError('Weapon tags must be lowercase cache-index hex')
            if not action.get('from') or not set(action.get('roles', ['host', 'client'])) <= {'host', 'client'} or not action.get('roles', ['host', 'client']):
                raise ValueError('Assertions require a named checkpoint and owned peer roles')
            if action['predicate'] == 'weapon_acquired' and 'tag' not in action:
                raise ValueError('Weapon acquisition needs the reviewed cache tag index')
            if action['predicate'] == 'credited_kill' and (
                    not isinstance(action.get('target_player'), int) or
                    not 0 <= action['target_player'] < 16 or action['target_player'] == action.get('player', 1)):
                raise ValueError('Credited kills require a distinct target_player index')
    return value


def clean_native_environment(environment):
    """Drop inherited native/debug overrides before installing owned fixtures."""
    return {key: value for key, value in environment.items()
            if not key.startswith(('DYLD_', 'HALO_')) and key != 'POC_DIAG_EVENT_FILE'}


def validated_addresses(host, client, configured, transport):
    addresses = tuple(str(ipaddress.IPv4Address(value)) for value in (host, client))
    if addresses[0] == addresses[1] or any(value not in configured for value in addresses):
        raise ValueError('Tests need two distinct, already configured IPv4 addresses')
    # The native XNet shim reserves only 127.0.0.1 for the host joining itself.
    # Existing Darwin loopback aliases can be paired via explicit unicast
    # network.broadcast. Never create aliases or assume arbitrary 127.x binds.
    if transport == 'lan' and '127.0.0.1' in addresses:
        raise ValueError('LAN reserves 127.0.0.1 for native self traffic; use other configured addresses')
    return addresses


def bind_player_expression(expression, players):
    """Bind absolute player selectors to stock HS's reversed live unit list.

    hs_players iterates ascending data indices and object_list_add prepends.
    The diagnostic fixture changes only the selector, never the engine order.
    """
    order = sorted((index for index, value in players.items() if not value['dead']), reverse=True)
    mapping = {index: position for position, index in enumerate(order)}
    def replace(match):
        absolute = int(match[1])
        if absolute not in mapping:
            raise ValueError('Fixture selected a missing/dead absolute player: ' + str(absolute))
        return '(list_get (players) ' + str(mapping[absolute]) + ')'
    return re.sub(r'\(list_get\s+\(players\)\s+(\d+)\s*\)', replace, expression), mapping


def snapshot(args):
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    app = args.source_app.resolve(strict=True)
    source_files = [app / 'Contents/MacOS/halo', app / 'Contents/Resources/halo_guest.elf']
    original = {str(path.relative_to(app)): digest(path) for path in source_files}
    bundle = destination / 'engine/runtime-bundle'
    shutil.copytree(app, bundle, symlinks=True)
    copied = {name: digest(bundle / name) for name in original}
    if original != copied or original != {str(path.relative_to(app)): digest(path) for path in source_files}:
        raise RuntimeError('Installed app changed while copying; preserve this failed snapshot and retry in a new folder')
    source = args.input_source.resolve(strict=True)
    local_source = destination / 'community_multiplayer_input.c'
    shutil.copyfile(source, local_source)
    library = destination / 'community_multiplayer_input.dylib'
    command = ['clang', '-dynamiclib', '-O2', '-Wall', '-Wextra', '-Werror',
               '-I' + str(args.sdl_include), str(local_source),
               '-L' + str(bundle / 'Contents/Frameworks'), '-lSDL3.0',
               '-Wl,-rpath,@loader_path/engine/runtime-bundle/Contents/Frameworks', '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    hashes = {str(path.relative_to(destination)): digest(path) for path in
              [bundle / name for name in original] + [local_source, library,
               bundle / 'Contents/Frameworks/libSDL3.0.dylib', bundle / 'Contents/Resources/BuildInfo.txt']}
    record = dict(schema_version=1, source_app=str(app), app_source_unchanged=True,
                  files=hashes, input_compile_command=command,
                  build_info=(bundle / 'Contents/Resources/BuildInfo.txt').read_text(),
                  scope='Frozen native app; diagnostic-only SDL event helper; no engine rebuild')
    write_json(destination / 'snapshot.json', record)
    print(json.dumps(record, indent=2))


def verify_snapshot(folder):
    value = json.loads((folder / 'snapshot.json').read_text())
    if value.get('schema_version') != 1 or not value.get('files'):
        raise ValueError('Expected a complete frozen runtime snapshot')
    for name, expected in value['files'].items():
        path = folder / name
        if '..' in Path(name).parts or Path(name).is_absolute() or digest(path) != expected:
            raise ValueError('Frozen runtime hash mismatch: ' + name)
    return value


def prepare_pair(args):
    runtime = args.runtime.resolve(strict=True)
    engine = verify_snapshot(runtime)
    source = args.map_source.resolve(strict=True)
    header = cache_header(source)
    if header['version'] != 5 or header['type'] != 1 or header['name'] != source.stem:
        raise ValueError('Expected an Xbox v5 multiplayer cache whose name matches its filename')
    actual = digest(source)
    if actual != args.map_sha256:
        raise ValueError('Candidate map checksum differs from reviewed --map-sha256')
    configured = re.findall(r'\binet (\d+\.\d+\.\d+\.\d+)\b', subprocess.check_output(['ifconfig'], text=True))
    host_ip, client_ip = validated_addresses(args.host_address, args.client_address, configured, args.transport)
    fixture = profile(args.profile, args.mode, actual)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Pin private cache bytes as well as the app so another compilation cannot
    # mutate a currently running test. Personal maps are only read as symlinks.
    map_copy = output / source.name
    shutil.copyfile(source, map_copy)
    if digest(map_copy) != actual:
        raise RuntimeError('Candidate changed while preparing its local snapshot')
    write_json(output / 'profile.json', fixture)
    environments, consoles = {}, {}
    for role in ('host', 'client'):
        folder = output / role
        environments[role] = prepare(folder, role, 'invite' if args.transport == 'local-invite' else 'lan', args.seconds, host_ip, client_ip,
                                     ','.join([args.mode] * (2 if args.rematch else 1)), args.score,
                                     source.stem, map_copy, True, args.screenshot_every)
        environment = clean_native_environment(environments[role])
        environments[role] = environment
        environment.update(HALO_DATA_ROOT=str(folder / 'data'), HALO_SAVE_ROOT=str(folder / 'saves'),
                           HALO_WINDOWED='1', HALO_SCREEN_WIDTH='640', HALO_WINDOW_SCALE='1', HALO_VOLUME='0')
        environment['DYLD_INSERT_LIBRARIES'] = str(runtime / 'community_multiplayer_input.dylib')
        environment['POC_DIAG_EVENT_FILE'] = str(folder / 'events.txt')
        (folder / 'events.txt').write_text('')
        (folder / 'data/sounds').symlink_to((ROOT / 'assets/sounds').resolve(strict=True))
        port = free_port()
        consoles[role] = port
        configuration = (folder / 'saves/config.toml').read_text()
        brokers = 'broker.emqx.io:1883,broker.hivemq.com:1883,test.mosquitto.org:1883' if args.transport == 'local-invite' else ''
        configuration = configuration.replace('[network]\n', '[network]\npublic_games = false\ndirectory_url = ""\nsignalling_brokers = "' + brokers + '"\nstun_servers = ""\n')
        configuration = configuration.replace('network_test_shoot = 3.0', 'network_test_shoot = 0.0')
        configuration = configuration.replace('network_test_kill = 12.0', 'network_test_kill = 0.0')
        configuration = re.sub(r'test_input = "bot:\d+"', 'test_input = ""', configuration)
        configuration = configuration.replace('[debug]\n', f'[debug]\ntelnet_console = true\ntelnet_console_port = {port}\n')
        configuration += ('\n[game]\nconsole_log = "all"\n[update]\nauto = false\n'
                          '\n[audio]\nenabled = true\nvolume = 0.0\n'
                          '\n[bindings]\nzoom = "Z"\nb = "F"\nblack = "X"\n')
        (folder / 'saves/config.toml').write_text(configuration)
        write_json(folder / 'saves/macos-settings.json', {
            'data_path': str(folder / 'data'), 'windowed': True,
            'community_downloads': False, 'timer_audio_downloads': False,
            'release_checks': False})
    record = dict(schema_version=1, scope='Two native local peers on one Mac; no NAT or physical-device certification',
                  map=header, map_sha256=actual, source_map=str(source), map_snapshot=str(map_copy),
                  runtime=str(runtime), runtime_hashes=engine['files'], mode=args.mode, transport=args.transport, profile=fixture,
                  peer_commands={role: [str(runtime / 'engine/runtime-bundle/Contents/MacOS/halo')] +
                                 (['<private host invite obtained at launch>'] if role == 'client' and args.transport == 'local-invite' else [])
                                 for role in ('host', 'client')},
                  console_ports=consoles, addresses={'host': host_ip, 'client': client_ip},
                  audio_pipeline_enabled=True, audio_master_gain=0,
                  synthetic_damage_disabled=True, synthetic_kills_disabled=True,
                  deathless_disabled=True, downloads_disabled=True, public_directory_disabled=True,
                  signalling_scope='Existing production MQTT brokers for two private peers' if args.transport == 'local-invite' else 'No external signalling',
                  expected_coverage=fixture.get('required_coverage', []), actions=[],
                  checks={}, coverage=[], qualification_complete=False, passed=False)
    write_json(output / 'launch.json', record)
    return output, environments, record


class Pair:
    def __init__(self, folder, environments, record):
        self.folder, self.environments, self.record = folder, environments, record
        self.processes, self.consoles, self.streams, self.connections = {}, {}, [], []
        self.sequences, self.checkpoints = {'host': 0, 'client': 0}, {}
        self.state_streams = {}

    def alive(self):
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(role + ' exited during native validation: ' + str(process.returncode))

    def wait(self, predicate, message, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.alive()
            result = predicate()
            if result:
                return result
            time.sleep(.1)
        raise TimeoutError(message)

    def log(self, role):
        return read_log(self.folder / role) + '\n' + self.debug(role)

    def debug(self, role):
        path = self.folder / role / 'data/debug.txt'
        return path.read_text(errors='replace') if path.exists() else ''

    def state(self, role):
        if role in self.state_streams:
            return samples(self.state_streams[role].read_text(errors='replace'))
        return native_samples(self.folder / role)

    def pin_state_streams(self):
        """Checkpoint offsets stay within the same original native log file."""
        selected = {role: native_stream(self.folder / role) for role in ('host', 'client')}
        if not all(path is not None and rows and rows[-1]['playing'] and
                   len(rows[-1]['players']) >= 2 and rows[-1]['received'] > 0
                   for path, rows in selected.values()):
            raise RuntimeError('Only active paired gameplay streams can be pinned')
        self.state_streams = {role: path for role, (path, _) in selected.items()}
        self.record['network_state_streams'] = {role: str(path) for role, path in self.state_streams.items()}
        return {role: rows for role, (_, rows) in selected.items()}

    def launch(self, role):
        log = (self.folder / role / 'game.log').open('w')
        self.streams.append(log)
        executable = Path(self.record['runtime']) / 'engine/runtime-bundle/Contents/MacOS/halo'
        command = [str(executable)]
        if role == 'client':
            # A fast client can join before the host's local controller and
            # reverse player indices. Wait on stock lobby evidence rather than
            # assuming process order is the player order.
            self.wait(lambda: 'server added player from machine #0 at controller index #0 to the game'
                      in self.debug('host'), 'Host local controller did not join its own lobby', 25)
        if role == 'client' and self.record['transport'] == 'local-invite':
            # Keep the ephemeral invite in private logs/argv only. Never print
            # it or place it on the real clipboard or in the validation report.
            invite = self.wait(lambda: re.search(r'halo-og://join/[0-9a-fA-F]{64}(?![0-9a-fA-F])', self.log('host')),
                               'Host did not produce its private local invite', 30)
            command.append(invite[0])
        self.processes[role] = subprocess.Popen(command, cwd=ROOT, env=self.environments[role],
                                                stdout=log, stderr=subprocess.STDOUT)
        port = self.record['console_ports'][role]
        def connect():
            try:
                return socket.create_connection(('127.0.0.1', port), timeout=.2)
            except OSError:
                return None
        connection = self.wait(connect, role + ' diagnostic console did not open', 25)
        self.connections.append(connection)
        transcript = (self.folder / role / 'console.log').open('w')
        self.streams.append(transcript)
        self.consoles[role] = Console(connection, transcript)
        self.record.setdefault('owned_pids', {})[role] = self.processes[role].pid
        print('Started owned ' + role + ' for ' + self.record['mode'], flush=True)

    def ready(self):
        def connected():
            states = {role: self.state(role) for role in ('host', 'client')}
            return all(rows and len(rows[-1]['players']) >= 2 and rows[-1]['playing'] and rows[-1]['received'] > 0
                       for rows in states.values()) and states
        self.wait(connected, 'Both native peers did not exchange gameplay updates', 70)
        states = self.pin_state_streams()
        self.record['initial_native_states'] = {role: rows[-1] for role, rows in states.items()}
        actual_roles = {role: rows[-1]['local_player'] for role, rows in states.items()}
        if any(index is None or index < 0 for index in actual_roles.values()) or len(set(actual_roles.values())) != 2:
            raise RuntimeError('Native peers did not identify distinct owned local players')
        self.record['player_roles'] = actual_roles
        if self.record['profile']['actions']:
            expected_roles = self.record['profile'].get('player_roles', {'host': 0, 'client': 1})
            if actual_roles != expected_roles:
                raise RuntimeError('Profile player roles do not match observed native local player indices')
        if self.record['mode'] in TEAM_MODES:
            for role, rows in states.items():
                teams = {player['team'] for player in rows[-1]['players'].values()}
                if len(teams) < 2 or -1 in teams:
                    raise RuntimeError(role + ' did not assign opposing teams')
        self.record['checks']['both_native_peers_playing'] = True
        if self.record['transport'] == 'local-invite':
            self.record['checks']['private_encrypted_peers_connected'] = all(
                'Internet play: connected to' in self.log(role) for role in ('host', 'client'))
        self.record['joined_checkpoint'] = self.checkpoint('joined')
        for role in ('host', 'client'):
            self.input(role, 'key', 69, 150)  # F12 recaptures this hidden peer's input.

    def checkpoint(self, name):
        if set(self.state_streams) != {'host', 'client'}:
            raise RuntimeError('Paired native log streams must be pinned before checkpoint offsets')
        values = {role: self.state(role) for role in ('host', 'client')}
        if not all(values.values()):
            raise RuntimeError('A checkpoint requires network-state samples from both peers')
        self.checkpoints[name] = {role: {'offset': len(rows), 'sample': rows[-1]} for role, rows in values.items()}
        return self.checkpoints[name]

    def input(self, role, event, code, hold_ms):
        self.sequences[role] += 1
        sequence = self.sequences[role]
        destination = self.folder / role / 'events.txt'
        pending = destination.with_suffix('.next')
        pending.write_text(f'{sequence} {event} {code} {hold_ms}\n')
        pending.replace(destination)
        marker = f'pid={self.processes[role].pid} seq={sequence} code={code} mouse={int(event == "mouse")} down=0'
        if event.startswith('look_'):
            marker += ' type=' + event
        self.wait(lambda: marker in self.log(role), 'Owned SDL input was not acknowledged and released', hold_ms / 1000 + 3)
        return dict(role=role, sequence=sequence, event=event, code=code, hold_ms=hold_ms,
                    acknowledged=True, evidence_scope='Input delivery; resulting gameplay asserted separately')

    def capture(self, role, name):
        frames = self.folder / role / 'frames'
        choices = sorted(frames.glob('*.bmp'))
        if not choices:
            raise RuntimeError('Native peer produced no screenshots')
        destination = self.folder / role / (re.sub('[^a-zA-Z0-9_-]', '_', name) + '.bmp')
        shutil.copyfile(choices[-1], destination)
        return dict(path=str(destination), sha256=digest(destination), source_frame=choices[-1].name)

    def action(self, action):
        result = dict(action=action)
        kind = action['kind']
        if kind == 'host_command':
            expression = action['expression']
            if self.record['profile'].get('hs_player_indices') == 'absolute':
                expression, mapping = bind_player_expression(expression, self.state('host')[-1]['players'])
                result['bound_hs_expression'] = expression
                result['absolute_to_hs_list_indices'] = mapping
            response = self.consoles['host'].command(expression)
            if action.get('expect') and action['expect'] not in response.replace('\r', ''):
                raise AssertionError('Host fixture command did not acknowledge its expected output')
            result['response'] = response
            result['fixture_scope'] = 'Host-only diagnostic command; candidate and game rules unchanged'
        elif kind == 'input':
            result['delivery'] = self.input(action['role'], action['event'], action['code'], action.get('hold_ms', 150))
        elif kind == 'navigate_waypoint':
            from community_multiplayer_navigation import navigate_waypoint
            result['navigation'] = navigate_waypoint(self, action)
        elif kind == 'wait':
            until = time.monotonic() + action['seconds']
            self.wait(lambda: time.monotonic() >= until, 'Bounded fixture wait failed', action['seconds'] + 1)
        elif kind == 'checkpoint':
            result['state'] = self.checkpoint(action['name'])
        elif kind == 'capture':
            result['capture'] = self.capture(action['role'], action['name'])
        elif kind == 'assert_transition':
            before = self.checkpoints[action['from']]
            roles = action.get('roles', ['host', 'client'])
            evidence = {}
            def observed():
                for role in roles:
                    state = self.state(role)
                    match = transition(action['predicate'], before[role]['sample'], state[before[role]['offset']:],
                                       player=action.get('player', 1), tag=action.get('tag'),
                                       minimum=action.get('minimum', 1), target=action.get('target'),
                                       tolerance=action.get('tolerance', .5), target_player=action.get('target_player'))
                    if not match:
                        return False
                    evidence[role] = match
                return bool(evidence)
            self.wait(observed, 'Observed state did not satisfy ' + action['predicate'], action.get('timeout', 15))
            result['evidence'] = evidence
            if action.get('coverage') and action['coverage'] not in self.record['coverage']:
                self.record['coverage'].append(action['coverage'])
        result['passed'] = True
        self.record['actions'].append(result)
        write_json(self.folder / 'validation-progress.json', self.record)

    def close(self):
        for connection in self.connections:
            connection.close()
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self.record['cleanup'] = {
            'scope': 'Only the two owned native children; expected diagnostic termination',
            'exit_codes': {role: process.returncode for role, process in self.processes.items()}}
        for stream in self.streams:
            stream.close()


def run(args, post_profile=None):
    output, environments, record = prepare_pair(args)
    if not args.run:
        print(json.dumps({'prepared': str(output), 'launch_performed': False, 'map_sha256': record['map_sha256']}, indent=2))
        return
    pair = Pair(output, environments, record)
    try:
        pair.launch('host')
        pair.launch('client')
        pair.ready()
        for action in record['profile']['actions']:
            pair.action(action)
        if post_profile is not None:
            post_profile(pair)
        record['checks']['all_reviewed_actions_passed'] = True
    except BaseException as error:
        record['error'] = str(error)
        raise
    finally:
        pair.close()
        diagnostic = {}
        for role in ('host', 'client'):
            text = pair.log(role)
            diagnostic[role] = dict(faults=sorted(set(FAULT.findall(text))),
                                    warnings=[line for line in text.splitlines() if WARNINGS.search(line)],
                                    network_samples=len(pair.state(role)))
        record['diagnostics'] = diagnostic
        record['checks']['no_runtime_faults'] = all(not value['faults'] for value in diagnostic.values())
        record['checks']['no_cache_sound_or_mode_warnings'] = all(not value['warnings'] for value in diagnostic.values())
        record['checks']['synthetic_damage_never_ran'] = all(' shoots player ' not in pair.log(role) for role in ('host', 'client'))
        record['checks']['synthetic_kill_never_ran'] = all('first player kills the last' not in pair.log(role) for role in ('host', 'client'))
        record['checks']['map_snapshot_unchanged'] = digest(record['map_snapshot']) == record['map_sha256']
        try:
            verify_snapshot(Path(record['runtime']))
            record['checks']['runtime_snapshot_unchanged'] = True
        except (OSError, ValueError):
            record['checks']['runtime_snapshot_unchanged'] = False
        record['coverage_complete'] = bool(record['expected_coverage']) and all(
            kind in record['coverage'] for kind in record['expected_coverage'])
        record['passed'] = 'error' not in record and all(record['checks'].values())
        record['qualification_complete'] = record['passed'] and record['coverage_complete']
        write_json(output / 'validation.json', record)
    print(json.dumps({'passed': record['passed'], 'qualification_complete': record['qualification_complete'],
                      'coverage': record['coverage'], 'validation': str(output / 'validation.json')}, indent=2))
    if not record['passed']:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    freeze = commands.add_parser('snapshot', help='Copy an app and compile only the test input helper')
    freeze.add_argument('--source-app', type=Path, default=Path('/Applications/Halo OG.app'))
    freeze.add_argument('--input-source', type=Path, default=ROOT / 'tools/community_multiplayer_input.c')
    freeze.add_argument('--sdl-include', type=Path, default=Path('/opt/homebrew/include'))
    freeze.add_argument('--output', type=Path, required=True)
    test = commands.add_parser('test', help='Prepare two isolated peers; only --run launches them')
    test.add_argument('--runtime', type=Path, required=True)
    test.add_argument('--map-source', type=Path, required=True)
    test.add_argument('--map-sha256', required=True)
    test.add_argument('--mode', choices=MODES, required=True)
    test.add_argument('--transport', choices=('lan', 'local-invite'), default='lan')
    test.add_argument('--profile', type=Path)
    test.add_argument('--host-address', required=True)
    test.add_argument('--client-address', required=True)
    test.add_argument('--seconds', type=int, default=150)
    test.add_argument('--score', type=int, default=0)
    test.add_argument('--screenshot-every', type=int, default=30)
    test.add_argument('--rematch', action='store_true')
    test.add_argument('--output', type=Path, required=True)
    test.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.command == 'snapshot':
        snapshot(args)
    else:
        if not re.fullmatch('[0-9a-f]{64}', args.map_sha256) or not 60 <= args.seconds <= 600 or args.score < 0 or args.screenshot_every < 1:
            parser.error('Use a reviewed SHA-256, 60-600 second lifetime, nonnegative score and positive capture interval')
        run(args)


if __name__ == '__main__':
    main()
