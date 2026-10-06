# Automated netcode timing comparison

`tools/halo_fidelity.py` compiles and runs the actual historical and current game
engines. It measures controlled inputs, consumed actions, projectile directions,
and the camera submitted for drawing. It does not derive an expected 33 ms delay
from a formula and then treat that formula as a measurement.

The [October 2 measured results](netcode-fidelity-results-2026-10-02.md) include
valid historical/current host and client captures and reference repeatability.
Those captures predate the October 4 optional
[Input Delay: Off / 33ms](performance-options.md#input-delay) implementation.
This runner's fresh Slayer fixture uses the default Off setting; the recorded
October 2 measurements do not validate the enabled option.

## Reference and scope

The pinned historical reference is
`f538f7f6692f7ce42c95c94a3aff48ddb0e77fb8` (the first integrated native Mac
multiplayer revision). It retains `network.netcode = "lockstep"`; the probe
checks `network_game_distributed()` at runtime to confirm that path is active.
The candidate defaults to a snapshot of the current working source, including
uncommitted source changes. A Git revision can be supplied instead.

This reference is a native reconstruction of the earlier lockstep code. It is
**not a retail Xbox executable or a physical Xbox measurement**. It contains
the portability changes already present at that revision. Matching it is a
useful regression gate, not certification of retail input, graphics or LAN
parity. See the [assessment](xbox-feel-pb-assessment-2026-10-02.md) for that
distinction and the remaining movement, assist and hardware experiments.

Each run starts two actual game processes with isolated profiles and an
encrypted local connection. One runs the spin fixture; the other stands still.
The original lobby's requirement for two machines and players remains intact.
`--role host` measures host input; `--role client` measures the joining player.
These are two processes on one Mac, not two physical machines over wired LAN.

The default `--transport auto` selects direct LAN only if two local IPv4
interfaces can exchange test datagrams. Otherwise it uses `local-relay`: the
game's encrypted peer transport with a temporary MQTT signalling fixture bound
to loopback. Public signalling brokers, STUN, UPnP, Discord, public game-directory
discovery/advertising, update checks and community-map downloads are disabled.
The fixture writes connection counts, not signalling payloads. Diagnostic
game sockets use ports 56150/56151, separate from the normal game.

The historical snapshot receives one explicitly recorded portability patch:
its pre-match socket connection wait also waits on `WSAEWOULDBLOCK`, which the
Mac socket emulation can return while connecting. Its in-match queues, packet
formats and simulation timing are unchanged. Instrumented source and binary
hashes identify the exact diagnostic build, including this patch.

The fixture enters immediately before `update_client_queue`, after controller
processing, and keeps the live control facing in agreement with the injected
action. That boundary isolates action delivery and later engine behavior from
controller response. It deliberately does **not** claim to calibrate a real
controller to 100 degrees per second or measure USB polling latency.

## Build and run

Prerequisites are Python **3.11+** (`tomllib` is in the standard library), the
repository's [usual Apple Silicon build dependencies](apple-build.md),
local Git history containing the reference, independently supplied
Xbox maps in `assets/maps`, an active LAN IPv4 interface, and access to macOS's
display server. A sandbox without display access cannot run the live test.
No game data is downloaded. The Python harness uses only the standard library.

Use a full clone of `pfista/halo-og`; the pinned reference remains in its main
history. If an existing checkout is shallow, fetch the full history first with
`git fetch --unshallow origin`, then confirm
`git cat-file -e f538f7f6692f7ce42c95c94a3aff48ddb0e77fb8^{commit}`.
Run `python3 tools/macos_setup.py` with the documented LLVM 22 environment before
building. The harness copies the prepared `build/macos/toolchain` and ANGLE
frameworks into its snapshots. The build graph prepares the usual public
SDL3/musl dependencies if they are not already cached; no private Xbox SDK or
PB source checkout is required.

From the repository root:

```sh
python3 tools/halo_fidelity.py build \
  --revision f538f7f6692f7ce42c95c94a3aff48ddb0e77fb8 --legacy \
  --output build/fidelity/reference
python3 tools/halo_fidelity.py build --output build/fidelity/candidate

python3 tools/halo_fidelity.py suite \
  --reference-build build/fidelity/reference \
  --candidate-build build/fidelity/candidate \
  --output build/fidelity/host-suite
```

The default suite tests 48 presses per engine per case, both directions at
100 degrees/second, and phases of 0, 8.333, 16.667 and 25 ms. This takes
about 30 minutes. Engines are compared sequentially, so two measurement pairs do not
compete with each other. Use a fresh output directory for every build or run.

For a shorter capture or an individual case:

```sh
python3 tools/halo_fidelity.py run --build build/fidelity/reference \
  --shots 12 --role host --rate 100 --phase-ms 0 \
  --output build/fidelity/reference-host
python3 tools/halo_fidelity.py run --build build/fidelity/candidate \
  --shots 12 --role host --rate 100 --phase-ms 0 \
  --output build/fidelity/candidate-host
python3 tools/halo_fidelity.py compare \
  build/fidelity/reference-host build/fidelity/candidate-host \
  --output build/fidelity/host-comparison.json
```

Repeat with `--role client` for the joining player. `--interpolation` runs the
high-refresh presentation path, with the simulation still at 30 Hz; the output
records actual frame intervals. It does not assert that a requested display
rate was achieved. `--tap-ms` allows short taps to be tested. A tap that falls
entirely between sampled frames is rejected as unobserved instead of silently
counted as a successful shot.

Builds live under their requested output directories. The normal game source,
installed app, personal settings and saves are untouched. The harness produces
diagnostic host/guest executables, not an `.app` bundle. No new application
environment variables are introduced. Existing `HALO_*` runtime overrides are
cleared for the subprocesses and only the existing data/save/display isolation
keys are supplied.

## Measurements and acceptance

The script turns at the requested angular rate, taps the stock pistol once per
second, and requests reloads between magazines of 12. It retains the stock
weapon rules and spread. Buffering the trace avoids logging every frame while
the experiment is running.

Both simulations receive the same controlled starting inventory and fixed
Blood Gulch positions. The distant idle player avoids contaminating the spin
measurement with aim assist. A twenty-second warmup exercises firing, impacts,
reload and rendering around a full turn. Starting ammo is restored on both
simulations before capture; ammo and weapon rules are then left alone for all
48 measured shots. The experiment measures this fixture, not retail spawn
equipment or spawn selection. Any missing press, extra shot or detected
autoaim target still rejects the capture.

| Trace event | Meaning |
| --- | --- |
| `a` | Injected packed action, sample ID, time, tick, facing, throttle and trigger |
| `p` | First observed sample of a scripted trigger press |
| `c` | Action consumed by the measured local player's simulation |
| `b` | Shot ray after the unit's aiming calculation, before projectile autoaim |
| `s` | Ray after autoaim and weapon offset, before random spread |
| `f` | Final projectile direction and the created projectile ID |
| `v` | Final camera returned to the renderer for the measured viewport |

The analyzer reports press-to-shot time, age of the facing sample consumed for
the shot, shot direction relative to the camera on the shot's frame, shot
direction relative to the camera on the press's frame, and direction relative
to the injected press action. The latter is useful when camera interpolation
means that live facing and drawn facing differ.
Both latency measurements include simulation ticks as well as milliseconds,
so ordinary frame scheduling jitter does not obscure a one-tick queue delay.

The trigger press and consumed facing retain separate provenance. Accumulated
buttons can come from an older sample than the facing. Legacy packet angle
quantization is allowed only within a small, recorded matching error; a missing
action match invalidates the capture. Camera values are taken from actual
render calls, not substituted with unit aim. Scanout and physical display
latency are outside this measurement.

A comparison is eligible only when both captures pass their integrity checks:
correct role and netcode, two simulated players, connected endpoints, completed
trace, no overflow or faults, every requested press and projectile, stock pistol,
no reported autoaim target, paired actions/cameras, approximately 30 Hz simulation,
unchanged build/config evidence, and equal scenario and map hashes.

Each metric includes every shot, count, mean, median, standard deviation, 5th and
95th percentiles, and minimum/maximum. The gate compares the median **and tails**.
For camera alignment it uses `shot_camera_residual_deg`: the observed shot/camera
angle minus the actual input rotation between the consumed sample and the sample
on the drawing frame. Both input angles come from the trace. No nominal 33 ms
delay or ideal frame time is substituted for a measurement.

The raw shot/camera angle remains reported and compared, with
`gates_result: false`. At 100 degrees/second, a 3 ms scheduling difference alone
changes that angle by 0.3 degrees. Requiring identical raw angle extremes made
two runs of the same historical binary fail despite identical one-tick queues.
The residual detects changed camera/weapon alignment, while the separate exact
tick and millisecond checks still reject removal of the queue delay. Raw
presentation timing remains visible rather than being mistaken for a change to
the input path.

Tick counts must match exactly. Default wall-time and angle tolerances are
provisional engineering values of 0.25 degrees and 5 ms,
adjustable through `--angle-tolerance` and `--time-tolerance-ms`. Establish
repeatability and a hardware reference before treating any tolerance as retail
acceptance. Do not loosen a tolerance solely to turn a failing candidate green.

Exit codes: `0` means the requested check passed; `1` means a capture is invalid
or a candidate differs beyond tolerance; `2` means setup/build/input failed.
Invalid captures cannot establish either matching behavior or a gameplay defect.

## Evidence and regression checks

Every build saves source file hashes, Git identity, probe hashes, compiler
identity, instrumented file hashes, final executable hashes and its build log.
Every run saves requested and normalized effective configurations, map hashes,
both game logs, an `analysis.json`, and a `shots.csv` containing all shots and
unmatched events. `comparison.json` and `suite.json` carry the acceptance result.
Raw `FTRACE` lines remain available in the measured game's log. Comparisons
reanalyze those raw logs and recheck integrity, so a cached passing report
cannot conceal a subsequently truncated trace or modified configuration.

```sh
python3 -m unittest tools.test_halo_fidelity -v
python3 tools/halo_fidelity.py analyze build/fidelity/reference-host
```

The regression checks cover a removed tick of delay, a changed tail with an
unchanged median, missing/empty metrics, truncated traces, missing projectiles,
peer faults, invalid press IDs, mismatched assets/phases, angle wraparound,
secret exclusion, signalling framing and ambiguous instrumentation anchors. They
test the analyzer; the live runs separately test the game. Instrumentation fails
on source-anchor drift rather than silently omitting a measurement.
