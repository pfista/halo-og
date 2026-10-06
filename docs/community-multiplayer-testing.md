# Native community-map multiplayer checks

`tools/macos_community_multiplayer.py` freezes an existing native app and checks
an explicitly reviewed Xbox v5 multiplayer cache using two native peers on one
Mac. It never builds the engine, installs an app, edits the candidate, or changes
personal saves. Its console positioning and SDL event helper are diagnostic
fixtures, separate from stock Xbox gameplay and from community conversion code.
The helper is loaded only into the two owned test children and is not packaged
into a release or normal play launcher.

Freeze the installed runtime once so other builds cannot change a test halfway
through:

```sh
python3 tools/macos_community_multiplayer.py snapshot \
  --source-app '/Applications/Halo OG.app' \
  --output build/community-test/runtime-snapshot
```

The snapshot copies the app and compiles only the diagnostic SDL helper. Its
manifest binds the native host, guest, SDL library, helper source and library,
and build metadata by SHA-256. Source host/guest hashes must remain unchanged
throughout the copy.

Prepare a pair using the reviewed cache checksum. Preparation is safe to run
without starting either game:

```sh
python3 tools/macos_community_multiplayer.py test \
  --runtime build/community-test/runtime-snapshot \
  --map-source build/community-test/maps/example.map \
  --map-sha256 REVIEWED_64_CHARACTER_SHA256 \
  --mode slayer --transport lan \
  --host-address HOST_CONFIGURED_IPV4 --client-address CLIENT_CONFIGURED_IPV4 \
  --seconds 180 --screenshot-every 30 \
  --output build/community-test/slayer-prepared
```

Add `--run` only when the native test launch is authorized and no other owned
test runner is active. Each output directory must be new. The cache name must
match its filename and must not replace a stock map. Both addresses must already
be configured; the tool creates no aliases. `lan` uses no external signalling.
Two configured loopback aliases such as `127.0.0.2` and `127.0.0.3` can provide
a local pair; `127.0.0.1` remains reserved for Halo's own-host addressing.
`local-invite` uses the application's existing private encrypted peer protocol
and configured production MQTT signalling brokers (`broker.emqx.io:1883`,
`broker.hivemq.com:1883`, `test.mosquitto.org:1883`). Obtain launch authorization
for these destinations before using this transport. Invites remain private and
are never printed, copied to the clipboard, or included in validation reports.
Raw logs and child process arguments can contain the ephemeral invite and remain
private ignored build artifacts.

Both transports disable public directory/listing, STUN, UPnP, Discord presence,
automatic map/audio downloads and update checks. The harness removes inherited
`HALO_*` and `DYLD_*` overrides, then sets isolated data and saves, hidden windows,
and an enabled audio pipeline with zero master gain. It does not kill other games.
Owned children are terminated after checks; their cleanup exit codes describe
that deliberate diagnostic termination rather than a normal menu exit.

## Mode and fixture coverage

The mode names are `slayer`, `team_slayer`, `ctf`, `oddball`, `team_oddball`,
`king`, `team_king`, `race` and `team_race`. Team checks require opposing teams.
An empty action profile establishes only that both native peers joined, loaded
the bound map, and exchanged gameplay updates. It never establishes weapons,
objective behavior, scoring or a release qualification.

A JSON profile has `schema_version: 1`, a matching `mode`, `actions`, and optional
`required_coverage` labels. When included, `map_sha256` must match the reviewed
cache, so weapon tag indices and objective fixtures cannot refer to an older
candidate. Actions execute in order:

For action profiles, include the expected absolute `player_roles`, usually
`{"host": 0, "client": 1}`. The harness confirms those roles from each peer's
local-player log. Script `(players)` list indices differ from absolute player
indices: the stock reference list prepends alive units. Set
`hs_player_indices: "absolute"` to resolve literal `(list_get (players) N)`
operands from the current alive-player list before each host command. The report
records the original and bound expression; assertions always use absolute
player indices. Avoid assuming that script index 0 names the host.

- `host_command`: a reviewed Halo script expression below 128 ASCII bytes.
  Host-owned positioning/facing is a fixture. Cheats, direct damage, vitality
  changes and forced game results are rejected.
- `input`: an owned `host` or `client`, event `key`, `mouse`, `look_x` or `look_y`,
  integer `code`, and `hold_ms` from 50 to 4000. Delivery is acknowledged by the
  diagnostic helper; gameplay must be asserted separately.
- `navigate_waypoint`: ordinary WASD input to a reviewed `target: [x,y,z]` for
  an owned peer. The bounded controller uses observed heading and checks fresh
  position samples after key release. `tolerance` and `vertical_tolerance`
  distinguish arrival from reaching the same horizontal position on another
  floor. An authored teleporter can specify `arrival_target` and
  `arrival_tolerance`; arrival must be observed at its destination. Set the
  boolean `allow_game_over` only where natural scoring can end the match before
  the waypoint center. That interruption does not count as arrival or award
  coverage. Blocked movement fails instead of changing the player's position.
- `wait`: a bounded delay up to 60 seconds.
- `checkpoint`: save both peer states under `name`.
- `capture`: copy the latest native BMP for the named peer. The screenshot
  interval is measured in simulation ticks: `30` captures once per second at
  the Xbox rate. Wait at least that interval after an action to obtain current
  evidence. A value of `1` writes every frame and can consume substantial disk
  space. The report records the source frame and checksum.
- `assert_transition`: compare state after the named `from` checkpoint using
  `predicate`, optional `player` (default 1), optional `roles` (default both), and
  bounded `timeout`. A successful reviewed assertion can add a `coverage` label.

The transition predicates are `weapon_acquired` (requires a reviewed hexadecimal
cache tag), `ammo_decrease`, `damage`, `credited_kill`, `death_respawn`, `score_increase`,
`objective_score`, `race_lap`, `game_over`, `rematch` and `position`. `objective_score`
requires score growth without credited kills and is rejected for Slayer modes.
Position checks use `target: [x,y,z]` and optional `tolerance`.
`credited_kill` requires distinct killer `player` and `target_player`, with an
increase in the killer's credited kills and the target's deaths in the same
observed sample. It must accompany the actual fire/melee and held-weapon
evidence; it is not inferred from input delivery.
`race_lap` is available only in Race presets and requires an increase in the
native completed-lap portion of the individual score, not merely one checkpoint.
`rematch` requires an observed native game-over followed by a simulation tick
reset in the same coherent log stream. Duplicate log mirrors are never joined
to manufacture a score or match transition.

Weapon qualification must tie ordinary fire input to the correct held weapon,
ammo use, a target's measured damage or death, credited kills, and respawn. Stable
source health and suitable floor positions help exclude falling or environmental
damage. A received input or ammo change alone does not establish a hit. Melee
needs its own ordinary input and credited damage evidence. The synthetic
`network_test_shoot` and `network_test_kill` paths are disabled and their log
markers fail the run if encountered.

Objective qualification must prove the appropriate pickup/hold/navigation and
score transition on both peers, then natural match end and rematch when requested.
KOTH and Oddball stock score units are minutes: `--score 1` needs 60 seconds of
continuous scoring (1800 Xbox ticks), not one second. Race requires ordered
checkpoint traversal and a completed lap; static marker presence is insufficient.
Use `--rematch` to configure two consecutive instances of the requested mode.

`validation.json` records the map/runtime hashes, owned PIDs, actions, samples,
captures, faults and targeted cache/sound/mode warnings. `passed` describes the
actions actually requested and requires no recorded runtime faults or targeted
warnings. `coverage_complete` describes the requested labels;
`qualification_complete` additionally requires a passing run, a nonempty
reviewed coverage list and every listed label. These trusted diagnostic
profiles must be reviewed; a label alone is not independent proof of its scope.

This is two-process testing on one Mac. It does not certify physical devices,
Internet/NAT traversal, high player counts, actual audible sound quality at zero
gain, or catalog download/install behavior. Run catalog integrity and native
download tests separately against the same published candidate checksum.

Run the fixture/parser checks separately from native gameplay evidence:

```sh
python3 tools/test_community_multiplayer.py
python3 tools/test_community_multiplayer_navigation.py
```

## Chillout Digsite release candidate

The multiplayer candidate has cache identity `chillout_digsite` and menu name
**Chillout Digsite**. It preserves the reviewed POC's custom weapon, HUD, bitmap
and sound conversions, while replacing its one-player validation loadout with
the authored multiplayer starting equipment. Its script subset and restored
stock Xbox Race course are described in the
[conversion guide](community-map-conversion.md).

All players must use the same candidate bytes. Current native join checks do
not negotiate a map SHA-256, and network object references include cache tag
indices. Different revisions under one filename are unsafe. Automatic
downloaders also preserve existing files with a different checksum. The new
identity keeps the multiplayer revision distinct from the published
`chillout_dig` proof of concept; do not rename that older cache to join a new
host.

The existing download integration can distribute this complete embedded cache
without a map-specific runtime flag. Mac can prioritize a missing map during
join; Windows and Linux currently prefetch the collection and should finish
downloading before joining. Retiring the POC catalog entry does not delete
previously downloaded or user-supplied POC files. Select **Chillout Digsite**
for the multiplayer candidate and record its checksum on every test peer.

The required acceptance matrix covers the following presets. Every row needs
both peers to load the exact candidate and exchange gameplay updates; marker
presence alone establishes only static eligibility.

| Presets | Gameplay evidence required |
|---|---|
| Slayer, Team Slayer | Authored starting equipment, pickup, ordinary custom-weapon fire, attributed kill, normal respawn, scoring and consecutive matches |
| CTF | Opposing-team spawns, enemy flag pickup, native capture at the home base, replicated score, natural match end and rematch |
| Oddball, Team Oddball | Ball pickup, holding-time score on both peers, natural match end and rematch |
| King, Team King | Reach the authored hill, replicate hill-time score, natural match end and rematch |
| Race, Team Race | Traverse the restored course in order, complete a lap, replicate the appropriate individual/team score, natural match end and rematch |

Special variant settings need additional checks where they change the content
path, including pro-mode sword filtering and alternative Race scoring. A local
mode matrix does not imply physical Mac/Windows/Linux interoperability or
split-screen acceptance. Record those independently against the release build.

As of 2026-10-05, the multiplayer cache passes static limits, script/reference
checks, embedded-resource checks and exact restored checkpoint verification.
Native testing found two further map-local compatibility issues: MCC score-screen
strings bypassed Xbox fallback wording, and the missile launcher's 2048-pixel
first-person texture exceeded available Xbox texture-cache pages during a match
transition. The reviewed candidate restores three Xbox strings and selects the
texture's authored 1024-pixel mip without recompression. Both operations retain
source hashes and byte-preservation evidence.

The published R04 cache has SHA-256
`93d966f3e191cb3f0506d8c31b2d0d3641e3530fac063387b6f4d2c435b6631d`
and transfer size 35,586,048 bytes. Five presets passed on two native peers using
a frozen runtime and private LAN: CTF, Oddball, Team Oddball, King and Team King.
The runs verified objective scoring on both peers, natural match end and rematch,
with no recorded faults or targeted cache/sound warnings. Team King also checked
renewed scoring at a moved hill. CTF used ordinary movement through an authored
teleporter for the pickup and diagnostic positioning for the return; it does
not prove a complete walking return route.

The user accepted testing-catalog publication with that coverage. Slayer,
Team Slayer, Race and Team Race runtime qualification remains pending, as does
representative network damage/kill coverage for the custom weapon families.
All nine presets have static layout eligibility; this is not full nine-mode
runtime certification. The complete cache replaced the old POC catalog entry
on 2026-10-05; see the [distribution record](map-publishing.md). Keep the full
private candidate manifest, profiles, compiler warnings, runtime reports and
hashes under ignored `build/`.
