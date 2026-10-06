# Xbox System Link feel: Performance Build settings and the Mac fork

Investigated October 2, 2026. This is a source review and measurement plan; it
contains no new Mac gameplay measurements and does not change gameplay code.

Follow-up: the [automated framework](netcode-fidelity-testing.md) is now built.
Its [native host/client measurements](netcode-fidelity-results-2026-10-02.md)
confirm a one-tick shooting-delay difference between historical lockstep and the
tested current snapshot. The source review below remains the original assessment;
the linked results record the later measurements and their narrower scope.

October 4 update: commit `6875d18a` added the optional, host-selected
[Input Delay: Off / 33ms](performance-options.md#input-delay), defaulting to Off.
That change and its validation are separate from this dated assessment. Mentions
of "current" source or unimplemented corrections below refer to the October 2
snapshot, not the latest main branch. They do not establish retail Xbox parity.

The supplied PDF, addendum, diagram and PB source were external research inputs;
they are not distributed with this repository. PB file locations below identify
the inspected inputs rather than prerequisites for building Halo OG or running
the native fidelity harness.

## Decision

Use **original retail Xbox Halo CE NTSC multiplayer at 30 Hz** as the primary
behavioral reference, including local split screen and both sides of System
Link. PB 1.1 with its 60 FPS patch, Pro Edition 2.0, and PB2 are useful comparison
builds, but none establishes retail behavior by itself. LAN is the reference;
internet transport is a separate condition in which we want to preserve that
feel as closely as possible.

Adopt a PB feature only when it corrects a demonstrated difference from that
reference. A feature's availability, popularity, or name does not establish that
we need it. Existing, separately authorized timer/announcement/spawn-marker
options remain optional exceptions, not evidence of retail fidelity.

**The most consequential finding is that our Xbox-derived engine already has
different networking and input delivery.** Its host and client consume their
own recent local actions without the old client-to-server frame boundary. We
therefore cannot assume the original multiplayer input delay remains merely
because the engine came from Xbox. This is a strong reason to measure the
pipeline; it is not yet proof that adding exactly 33.3 ms everywhere is correct.

Recommended order: measure input/action timing and camera timing first, then
compare host/client combat outcomes, then audit controller response and map
weapon tags. The older optional-feature priority list is not the adoption order
for a fidelity-only project.

## Evidence and version boundaries

| Evidence | What it establishes | Limit |
| --- | --- | --- |
| User-supplied `Spin Lead PB2 vs PB 1.1.pdf`, September 30, 2026, attributed to @JP | Instrumented constant-turn pistol comparisons, including the chart on page 4 and limitations on page 5. All five pages were inspected. | PB 1.1 is a 60 FPS patched build in xemu 0.8.136, not retail Xbox hardware. PB2 is the report's Beta 3 executable identified as `F8FECB4B`. |
| User-supplied 30 FPS addendum | Reports Pro Edition 2.0 in xemu at 30 FPS: 48 shots, four magazines, identical shot lead, no camera shake, one drawn frame per tick. | This is a pasted result, absent from the PDF. Raw logs, scripts, exact executable hash, and physical retail confirmation were not supplied. |
| User-supplied movement diagram and Discord excerpts | Explain the intended movement/shot relationship and the community concern. | A stationary spin test does not measure the diagram's movement and shot-origin behavior. This review did not access the full Discord conversation. |
| Supplied PB2 source in `h1-competitive-macos/upstream` | Actual delay, camera, spread, and menu implementations. | Its external `h1-competitive-macos/research/source-snapshot.json` manifest does not establish identity with the tested Windows executable or Git ancestry. Source comments are design claims; executed expressions provide stronger implementation evidence. |
| Current Mac source | HEAD `408214a23710b87b480c4dc2fbb9743f48561f2d` plus pre-existing local work, including settings and PB Options. Concurrent sound-option edits reached `weapons.c` and `units.c` during review; their diffs were rechecked and do not change the cited shot-direction/origin calculations. | A source finding is not a measured result from the installed executable. None of that existing work was changed by this investigation. |
| Installed Mac bundle metadata | Build 8, version 0.3.0, the same HEAD marked `(local changes)`; guest SHA-256 `5e41d57b17a519ef9551df38968bf4ef2fb51a2e09ef3b12f7f0c75204a33dd8`. | Metadata identifies the installed guest; it does not prove every current uncommitted source edit was built into it. |
| Live cybersecurity upstream check | `main` was `d1c7243cb20eab4488efa1266e259b1f4d5240f6`, matching our last recorded review. | A later upstream revision would need another review. No fetch, merge, or release was performed. |

The reconstruction target itself is Xbox build 2342; the local retail map set is
build 2276. As the [existing fidelity policy](xbox-fidelity.md) explains, matching
the reconstruction target is distinct from proving native retail parity.

## What the spin measurements mean

At a steady 100 degrees per second, 33.333 ms of aim age corresponds to 3.333
degrees. The report defines two different comparisons:

- **At the shot:** firing direction minus the camera direction in the first
  rendered frame containing the shot. Negative means the shot trails the reticle.
- **At the press:** firing direction minus the camera direction in the first
  frame that reads the trigger press.

These are angular relationships. Converting them to milliseconds gives an
equivalent age at that turn speed, not total physical trigger-to-screen latency.
Controller polling, trigger thresholds, frame presentation, and display latency
are additional measurements.

| Build / condition | Lead at shot | Lead at press | Interpretation |
| --- | --- | --- | --- |
| Pro Edition 2.0, xemu, 30 FPS / 30 Hz; supplied addendum | **-3.33 degrees on all 48 shots** | **0.00 degrees** | Supports a whole-action delay with live camera aim in this tested configuration. Provisional comparator for retail 30 FPS. |
| PB 1.1, xemu, 60 FPS / 30 Hz; PDF | -1.08 degrees on 45/48; -2.75 on 3/48; mean -1.19 | +0.58 or +2.25 degrees, depending on press phase | The report attributes the usual result to 16.7 ms aim age minus camera lag; the rare older shots may involve emulator pacing. |
| PB2, XBOX camera, 33 ms Input Delay, 0 Aim Direction Delay | -3.33 degrees | 0.00 degrees | Matches the supplied 30 FPS spin numbers. This PB2 mode still runs at 120 Hz; it is not an Xbox engine or a 30 FPS mode. |
| PB2 fresh-profile default: MCC camera, 17 ms Input Delay, 0 Aim Direction Delay | -2.00 degrees | Approximately -0.31 to -0.39 degrees | Neither the 30 FPS comparator nor an exact PB 1.1 match. |
| PB2, SMOOTHED camera, 17 ms Input Delay, 0 Aim Direction Delay | -1.18 degrees | Approximately +0.43 to +0.51 degrees | Close to PB 1.1's common 60 FPS result; the wrong primary target for retail 30 FPS. |
| Our Mac fork | **Not measured in this investigation** | **Not measured** | Source predicts a changed input-delivery boundary; camera and weapon execution must be measured together. |

The PDF reports 20 PB2 test arms with 12 shots per arm and 48 PB 1.1 shots. Its
PB2 figures remove camera shake; it reports shake of up to 0.16 degrees over
roughly ten frames. The 30 FPS addendum reports no shake. All quoted shot
directions concern the aim before pistol spread: “zero spread” in the repeated
lead measurements does **not** establish that the weapon has zero bullet spread.

The added 30 FPS result resolves why tuning toward -1.08 degrees would be the
wrong starting point here. It does not establish that every retail weapon,
frame phase, controller, split-screen seat, or System Link role behaves exactly
like that one Pro Edition test.

### Whole-action delay versus an older firing direction

Under the whole-action model, input sample A contains aim A, movement A, trigger
A, and the other buttons. Camera look can show aim A immediately while the
simulation receives that action later. A tapped shot consequently uses aim A
when it finally fires, even though the camera has continued turning.

PB implements this by storing and later delivering the entire `player_action`:
`upstream/host/blampc_input_pipeline.c:209` applies the pipeline, called before
the input queue at `upstream/engine/blam/handle_one_player_input.c:238` in the
external PB checkout.
The live control angles are separate from this record.

PB's Aim Direction Delay instead rotates the firing vector using aim history:
`upstream/host/blampc_shotdelay.c:510` in that checkout.
It does not reproduce the same delay for movement, trigger, and weapon choices.
Both approaches can produce a similar angle during steady turning while behaving
differently on a sudden turn, a reversal, a stop, or a trigger tap.

For a simplified constant-turn example with a live camera:

| Mechanism | When the trigger action fires | Aim selected | Expected relationship to press-time aim |
| --- | --- | --- | --- |
| Whole action held for D | D later | Aim carried by that action | Same aim, absent other engine effects |
| Only firing direction aged by D | Without that added trigger delay | Aim from before the trigger | Behind the press-time aim by about turn speed times D |

The PB2 delay preset named **PB2** means 0 pipeline delay plus 17 ms aim-direction
delay. It is different from the fresh-profile **XBOX 60 FPS** delay preset,
which means approximately 17 ms pipeline delay and zero aim-direction delay.
Camera mode is another independent choice. The preset table is at
`upstream/host/blampc_menu.c:8507` in the external PB checkout.

At 120 Hz, four ticks are 33.333 ms and two are 16.667 ms. At our 30 Hz, one tick
is 33.333 ms and two are 66.667 ms. Copying a PB tick count would be incorrect.
Copying an artificial delay on top of an already delayed path could also be
incorrect. Specify the intended end-to-end action age and measure existing age
before choosing an implementation.

The PB ring advances on calls to its apply function; our control packing runs
each frame, including frames without a simulation tick. A future adaptation must
explicitly define capture and release timing rather than paste that ring into
our per-frame caller and assume its slots represent 30 Hz ticks. Apply a shared
multiplayer rule once, consistently to local simulation and outgoing actions;
do not delay an already aged remote action again. Verify host agreement and hit
timestamps, and keep campaign behavior outside a multiplayer-specific fix.

### Why the movement diagram needs another test

A delay of a whole action does not freeze the player's position at trigger press.
Earlier movement actions can continue advancing the player before the firing
action executes. We must distinguish the camera's look direction, the player's
simulated position, and the actual projectile origin at the firing instant.

Our engine reads the unit's aiming vector and current camera position in
[`unit_adjust_projectile_ray`](../source/units/units.c#L4723), then applies weapon
offsets and aim assistance in
[`trigger_create_projectiles`](../source/items/weapons.c#L2194). It also obtains
a component of the shooter's velocity. A matched spin angle while standing still
does not establish that these spatial relationships match during strafing.

The attached drawing describes a particular movement sequence. It should not be
generalized into a universal instruction to aim a fixed distance ahead. Target
motion, player motion, range, projectile travel, and aim assistance also matter.

## What our current Mac source actually does

### The original multiplayer input route is no longer preserved

The current main loop reads controls and builds local actions before advancing
simulation: [`main.c`](../source/main/main.c#L3249).

1. [`player_control.c`](../source/game/player_control.c#L801) packs current facing,
   throttle, trigger, and weapon/grenade/zoom choices into an action.
2. [`update_client_queue`](../source/game/player_queues_new.c#L580) saves that
   action. Between simulation ticks it retains pressed buttons and maximum
   trigger pressure while other fields take the latest sample.
3. The host's [`update_server_next_update`](../source/game/player_queues_new.c#L371)
   calls [`update_server_take_local_actions`](../source/game/player_queues_new.c#L1023),
   which copies those saved local actions directly into the snapshot.
4. A remote client's own player takes the saved local action through
   [`update_client_dequeue_distributed`](../source/game/player_queues_new.c#L656),
   without waiting for the host's action round trip.
5. [`players_update_before_game`](../source/game/players.c#L3620) consumes actions
   and supplies aim, throttle, and trigger to `unit_control` before object updates.

This establishes removal of the old input-delivery boundary for local players,
including host-local seats. The separate `_game_connection_local` route also
builds from current actions; its name must not be treated as proof that a test
ran the retail multiplayer loop. Record the actual connection role in each test.

It does **not** establish a measured Mac lead of zero: unit aiming limits, weapon
execution, button accumulation, observer updates, frame phase, and presentation
still intervene. In particular, a sub-tick trigger tap may be retained while a
newer facing sample replaces its original facing. Record which input sample
provided each field; do not assume all accumulated fields share one timestamp.

The relevant upstream history is already in our ancestry:

| Commit | Relevant change | Review implication |
| --- | --- | --- |
| [`391e83b11f195721b6c3dd919bc9be295936e68d`](https://github.com/cybersecurity/halo-ce-universal/commit/391e83b11f195721b6c3dd919bc9be295936e68d) | Introduces distributed local prediction and the client dequeue path. | Client input no longer needs the original lockstep return path. |
| [`a3ed50c56d8cd0f3b0d6db2d3e523efead4e88a4`](https://github.com/cybersecurity/halo-ce-universal/commit/a3ed50c56d8cd0f3b0d6db2d3e523efead4e88a4) | Removes the optional lockstep networking path. | There is no current configuration switch that restores original System Link networking. |
| [`e7d1ed3a6732b7e334d923eb4595f0deeb83cb4c`](https://github.com/cybersecurity/halo-ce-universal/commit/e7d1ed3a6732b7e334d923eb4595f0deeb83cb4c) | Adds the current direct host-local action handoff, among substantial network corrections. | Split screen on the host needs timing measurement too. This cannot be reduced to a remote-client-only concern. |
| [`d1c7243cb20eab4488efa1266e259b1f4d5240f6`](https://github.com/cybersecurity/halo-ce-universal/commit/d1c7243cb20eab4488efa1266e259b1f4d5240f6), selectively integrated as `ea4dec3c28fcb4975ad36718c344bf5205b4c5eb` | v10 ping telemetry; this fork excludes the associated replacement scoreboard. | It does not add an Xbox input delay or replace the existing prediction/hit logic. |

### Camera behavior must be checked independently

Our first-person camera obtains the local control's facing directly:
[`first_person_camera_update`](../source/camera/first_person_camera.c#L133).
With render interpolation enabled, the native port blends the previous and
latest observer positions and directions:
[`render_interpolation_blended_camera`](../port/linux/game/render_interpolation.c#L710).
This changes the visible relation between the reticle and a simulation shot.

The reference profile has interpolation and direct camera off. That preserves a
useful comparison configuration; it does not restore a removed network delay.
High-refresh rendering can remain a goal with 30 Hz simulation, but its effect on
aim presentation needs a separate result.

**Mac-specific finding:** the `display.direct_camera` implementation returns
unchanged under `#ifdef HALO_ANDROID`:
[`render_interpolation_direct_camera`](../port/linux/game/render_interpolation.c#L667).
The Mac guest uses the shared
[`GUEST_ABI_FLAGS`](../tools/android_build.py#L53), which define that symbol, and
[`macos_guest_cc.py`](../tools/macos_guest_cc.py#L22) additionally defines
`HALO_MACOS`. Existing generated Mac guest IR also lacks the direct-camera config
read and facing call. Thus setting the current TOML key to true is not evidence
that the Mac is exercising that override. This does not mean the ordinary
first-person camera ignores live controls.

PB's XBOX/MCC/SMOOTHED labels are descriptions of its own implementation. In PB,
camera position remains interpolated in all these modes; only first-person
rotation switches paths. A matching label or TOML value in another engine would
not prove matching behavior.

### Networking changes more than input age

The current native stack advances peers independently, predicts the local
player, relays remote actions, corrects positions, and gives the host authority
over damage and other outcomes. A shooter reports hits, which the host validates
against weapon rules and position history. The implementation is in
[`network_distributed.c`](../port/linux/game/network_distributed.c) and
[`network_damage.c`](../port/linux/game/network_damage.c); the
[upstream description](https://github.com/cybersecurity/halo-ce-universal/blob/d1c7243cb20eab4488efa1266e259b1f4d5240f6/port/linux/NETCODE.md)
explicitly distinguishes it from Xbox lockstep.

Adding a local action delay would not by itself restore lockstep authority,
remote-player timing, corrections, or historical hit acceptance. Those can
affect cover interactions, trades, moving targets, and host/client differences;
the size and direction of the differences need runtime evidence.

The prior v10 tests establish packet handling, compatibility rejection, and two
same-Mac matches. They do not establish retail LAN combat parity. See the
[recorded validation boundary](xbox-fidelity.md#reconstruction-target-and-validation).
The public PB Mac exploration currently has no network implementation to adopt
as a proven replacement.

## Feature decisions under the fidelity criterion

“Measure first” means there is a plausible discrepancy, not approval to port the
whole feature. “Keep existing” means retain the Xbox-derived baseline pending a
specific failure, not a claim that hardware parity has already been demonstrated.

| PB setting or feature group | Effect | Recommendation for our Xbox baseline |
| --- | --- | --- |
| Whole-action Input Delay | Ages movement, facing, trigger, and action choices together while look can remain live. | **Highest-priority measurement.** The old route has changed. If reference tests expose missing action age, implement the narrow correction at a shared input boundary; avoid stacking delays. |
| Aim Direction Delay / PB2 delay preset | Uses older firing aim without the corresponding trigger/movement delay. | **Do not adopt as the Xbox restoration.** A similar steady-spin angle is insufficient evidence. |
| XBOX / SMOOTHED / MCC camera choices | Change reticle freshness relative to simulation; also retain PB's position interpolation. | **Measure current camera first.** Correct a demonstrated presentation difference; do not import all modes for fidelity or assume `direct_camera` works on Mac. |
| 120 Hz simulation | Changes the timing grid for movement, weapons, physics, and action sampling. | **Do not port.** Preserve 30 Hz. Rendering at 60/120 FPS is a separate choice and comparison. |
| Aim-update-rate experiments | Hold or update aiming at a cadence independent of rendering. | **No default import.** Our simulation is already 30 Hz; an extra hold could duplicate aging. |
| Per-seat input compensation / ping equalization | Adds different input ages to participants. | **Do not infer a fidelity benefit from equal ping.** Compare host and clients first; measured LAN behavior is the target. |
| Controller sensitivity, deadzones, response curves, acceleration, trigger rules | Change physical input-to-action mapping. | **Keep and measure the existing Xbox-derived path.** Modern-controller calibration may be necessary, but alternate curves and fine sliders do not themselves restore Xbox behavior. Include diagonals, small inputs, reversal and trigger release/repress. |
| Friction, adhesion, autoaim and magnetism tuning | Change tracking assistance and projectile correction. | **Keep reference tag values and existing logic first.** Measure with aim assist both absent and active; avoid importing Precision or custom values without an identified mismatch. Mouse behavior is not a controller baseline. |
| Pistol STOCK / NHE / MCC HARDCORE spread | PB can restore a 0.2-degree floor over its modified tags, retain map-authored spread, or force zero spread. | **Audit map tags before porting a switch.** Original stock tags may need no executable change; imported maps may carry different rules even with every menu toggle off. Separate tap, hold, recovery and cadence tests. |
| Pistol camera shake | Alters the reticle during/after firing, independently of the shot path. | **Measure and correct only if different from the reference.** Preserve raw and stabilized measurements; do not tune input delay to cancel shake. |
| Footstep/jump/landing suppression; silent weapon ready sounds | Remove audible cues, sometimes through map assets. | **No fidelity justification for silencing original sounds.** Restore missing original cues if imported content removed them. A silent-ready asset is separate from faster weapon readiness. |
| Skip First Weapon Draw | Changes when a spawned weapon can fire. | **Do not adopt for retail fidelity.** Test normal readiness against the reference instead. |
| Fixed shotgun spread, plasma mechanics, grenade attachment choices | Change hit distributions or weapon/collision behavior. | **Keep existing rules; audit individual discrepancies.** PB defaults are not evidence of original rules. |
| Camo/overshield appearance controls | Change visibility and visual cues. | **Fix demonstrated rendering differences.** Avoid arbitrary tint/brightness/custom presets as the baseline. |
| Camo/overshield drops and altered lifetimes | Change rewards and powerup availability. | **Do not adopt.** Separate competitive rules. |
| Timers, announcements, visible spawns and random-spawn readouts | Add information; markers can help test spawn placements. | **Not required for retail feel.** Keep already authorized PB Options as explicit optional aids; disable them for reference measurements. |
| Faster item spawns, infinite ammo, kill restoration, custom loadouts and practice presets | Change match rules or shorten practice cycles. | **Not fidelity additions.** Diagnostics can use controlled fixtures, but final acceptance must use the retail rules. |
| Fireteams, teammate outlines, extra tracking information | Change team organization or information available. | **Do not adopt for the baseline.** Retain original teammate and objective behavior. |
| FOV, aspect ratio, reticles, HUD and graphics-detail choices | Change framing, visual scale, visibility, or content. | **Use original framing/assets for comparison.** Fix genuine renderer errors; do not replace art or remove smoke/debris simply because PB exposes it. Check split-screen FOV separately. |
| Display frame cap, vsync, high-refresh rendering, CRT simulation | Change presentation cadence, motion clarity and display latency. | **Measure separately from simulation.** Keep a 30 FPS comparator without imposing it on normal play. A CRT shader is not proof of CRT latency/scanout equivalence. |
| Audio devices, volume groups, vibration, remapping, profiles, two displays | Platform support and player convenience; some choices affect cues or control feel. | **Reuse existing support.** Fix missing or incorrect original feedback/routing as needed. Extra controls do not require PB engine adoption. |
| Lobby favorites, statistics, Theater/replay tools and visualizers | Workflow and analysis tools. | **No direct fidelity requirement.** Narrow visualizers or trace capture can help measure a discrepancy without adopting the whole subsystem. |
| PB networking | A separate networking implementation/research direction. | **No wholesale port.** First quantify our existing stack against LAN references, then identify the smallest timing/authority correction. |

These decisions qualify the broader external research inventory at
`h1-competitive-macos/docs/pb-feature-inventory-and-porting-priorities.md`.
They do not revoke existing optional features or authorize changing them.

## Reproducible measurement plan

### A. Freeze the reference and the run metadata

Record executable/guest hashes, map hashes, active loaded weapon/global tag
values, retail/Pro/PB identity, region, controller/connection, sensitivity,
viewport count, resolution/aspect/FOV, tick rate, actual rendered frame times,
vsync, camera settings, assist settings, host/client role, and all optional rules.
Use separate saves/configs. Do not overwrite the user's normal profile.

Compare like-for-like stock maps first. The PDF uses different maps across its
engines, so separately verify common relevant tag values. Only then repeat on
the desired imported community maps. Reference “default” settings by saved
values, not by a menu label.

| Run group | Purpose |
| --- | --- |
| Retail NTSC Xbox, 30 FPS, local split screen; physical console where available | Primary local behavior. Emulator replication is useful but labeled separately. |
| Retail NTSC Xbox System Link: host and remote console, including multiple local seats | Primary network behavior and host/client comparison. |
| Pro Edition 2.0 xemu at 30 FPS and PB 1.1 xemu at 60 FPS | Reproduce the supplied observations without substituting them for retail. |
| Current Mac, 30 Hz / 30 FPS reference presentation: split screen, host and client | Isolate input delivery and shot behavior in the current fork. |
| Current Mac, 30 Hz with 60/120 FPS rendering | Isolate frame sampling, interpolation and reticle presentation. Record achieved rates, not just requested rates. |
| PB2 with the three camera modes and the published delay conditions | A secondary comparison of mechanisms; preserve 120 Hz identity. |

### B. Repeat the spin test, then vary phase

1. Stand still with the pistol. Calibrate a constant turn to 100 degrees/second
   below acceleration, using each build's measured response. Do not reuse its
   raw stick number in a different input pipeline.
2. Tap 12 times, one second apart; repeat for four magazines. Verify actual turn
   rate, action timing, ammunition changes, tick counts and frame intervals.
3. Remove target-driven assist from this first experiment and verify that it
   stayed inactive. Log firing direction before randomized spread, then also
   retain the final direction. Do not alter the stock weapon merely to hide
   spread or camera shake.
4. Record the shot-time and press-time comparisons exactly as the report does.
   Also log the final drawn camera, any camera-effect contribution, and the
   first displayed frame with the shot. A unit aim value alone is not a camera
   measurement; a tracer or impact screenshot alone is not the pre-spread ray.
5. Repeat with controlled starting offsets within the 33.333 ms tick. One-second
   intervals are an exact multiple of both 30 and 120 Hz and can keep testing
   the same phase. Add short taps, sustained holds and irregular press timing.
6. Repeat in both turn directions and with start/stop/reversal. Keep every shot,
   including outliers; report the distribution, common values, minimum, maximum,
   and frame/tick anomalies rather than only a mean.

Treat -3.33 degrees at firing and 0 at press as the **reported Pro 30 FPS
comparison**, not an already validated hard retail acceptance threshold. Set
retail tolerances from repeatability and measurement precision before evaluating
a candidate patch.

### C. Measure the stages, not just the final angle

The required trace should link one input sample, one consumed action, one shot,
and its rendered frame. Record separate sample IDs where button accumulation
mixes a retained press with newer facing or movement.

| Stage | Required evidence | Existing source location |
| --- | --- | --- |
| Raw controller sample / recognized press | Monotonic time, raw axes/triggers, threshold transition, local seat and sample ID | `xinput_sdl.c`, `input_xbox.c` |
| Live control / packed action | Facing, throttle, trigger, control flags, choices and source sample IDs | `player_control.c` before `update_client_queue` |
| Action consumed by simulation | Game tick, role, action provenance and age | `player_queues_new.c`, `players_update_before_game` |
| Unit movement and rotation | Pre/post tick position, velocity, desired aim, actual aim, model facing | `players.c`, `units.c`, object update boundary |
| Shot created | Shot ID, tick/time, action reference, origin, aim before autoaim, aim after autoaim/before spread, final direction | `weapons.c:trigger_create_projectiles`, `unit_adjust_projectile_ray` |
| View actually drawn | Frame ID/time, interpolation fraction, final camera origin/forward, viewport, shot visibility and effects | `render_interpolation_camera` and `main_game_render` |
| Network decision | Sender/receiver tick and arrival time, reported hit, host validation, damage application and position correction | `network_distributed.c`, `network_damage.c` |

The existing bot/`look:` input and rounded network diagnostics are insufficient
for this test: `look:` varies the sticks sinusoidally and does not fire; the
current aim log rounds to whole degrees. Do not label a generic network smoke
run as Jukus's spin test. The report names `xemu_aim_log.py`, `xemu_spin.py`, and
`spin_lead_pb2.py`; these scripts/raw run logs were not present in the inspected
supplied source snapshot. A Mac trace should implement the same definitions,
not assume those probes are already available.

Any future instrumentation should be a diagnostic build or explicit config
fixture, buffer records to limit timing disturbance, and verify that enabling
capture does not change tick/frame behavior. It does not require a new
application environment variable or a user-facing delay menu.

### D. Test the movement in the diagram

Use a stationary target and repeat: lateral strafe started before the trigger,
start strafe and fire together, stop and fire, reverse and fire, then orbit at
fixed range. Separately test a moving target with a stationary shooter, and both
moving. Capture shot origin, player/camera positions, aim and applied movement
action at press and firing. Repeat near and far, with assist inactive and then
with stock assist active.

This distinguishes a missing full-action delay from an aim-only offset,
interpolated camera position, altered velocity inheritance, ordinary projectile
travel, or changed assistance. Matching a stationary angular result cannot
substitute for these spatial comparisons.

### E. Verify LAN and internet behavior separately

Start with two instances on one Mac as a functional check, then two physical
machines over wired LAN. Swap host and client, repeat split-screen seats, and
compare the same movement and combat scenarios with the retail System Link
reference. Log transport latency and tick phase rather than equating ping to
input delay.

After LAN, use controlled added receive latency and loss for internet-like runs.
Existing `debug.network_latency` and `debug.network_loss` configuration keys
already provide this; the latency setting holds received traffic, so applying D
at each endpoint adds approximately 2D to a round trip. State whether each
reported value is one-way delay or RTT. Test jitter separately rather than
claiming that fixed delay covers it.

Include strafing duels, cover/corner transitions, near-simultaneous lethal shots,
grenades, melee, weapon pickups, and knockback. Compare local firing time,
remote presentation, authoritative damage and correction sizes. This determines
whether a local input fix suffices for the desired feel or whether authority and
hit validation also need changes. A fixed 33 ms delay alone cannot certify this.

## Adoption gate and remaining work

For each proposed change, record: the named reference; the observed discrepancy;
whether it comes from native input, engine code, map tags, rendering or networking;
the smallest correction; before/after traces; and remaining uncertainty. Prefer
one correction at a time. Require the result to improve both the intended metric
and nearby cases, including host/client and frame-phase behavior.

Completed here: full PDF inspection, inclusion of the missing 30 FPS addendum,
PB implementation review, current Mac input/camera/network tracing, upstream
commit provenance and live-head check, and the feature/test decisions above.
No gameplay code, runtime settings, maps, installed application, or network
protocol were changed. No retail hardware comparison, new instrumented spin
run, or physical LAN feel test was performed. Those measurements are the next
evidence needed before choosing or rejecting a timing correction.
