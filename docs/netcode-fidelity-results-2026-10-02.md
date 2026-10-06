# Netcode timing results, October 2, 2026

**The October 2 candidate snapshot does not preserve the historical one-tick shooting
input delay.** Valid real-engine captures found the same difference for the host
and the joining player. Historical lockstep consumed a one-tick-old firing action
on every measured shot; that candidate snapshot consumed current-tick input.
Both continued to simulate at approximately 30 Hz.

This is a dated result for the exact builds below. The optional, host-selected
[Input Delay: Off / 33ms](performance-options.md#input-delay) was added on October
4 in `6875d18a`; Off remains the default. Its implementation and validation are
separate from these October 2 captures, which do not measure the enabled option.

The automated framework is implemented in [tools/halo_fidelity.py](../tools/halo_fidelity.py).
[Build/run instructions and measurement definitions](netcode-fidelity-testing.md)
explain how to repeat the test or compare a future change.

## Measured results

Each row passed capture validation: every press had exactly one created pistol
projectile, both endpoints were active, no autoaim target was reported, camera
and action records matched, and the expected network path was active. The
48-shot host captures included four magazines and normal reloads.

| Case | Engine | Shots | Action age, ticks | Action age, ms: median (range) | Shot aim minus drawn camera, degrees: median |
| --- | --- | ---: | ---: | ---: | ---: |
| Host, +100 deg/s, phase 0 ms | reference | 48 | 1 | 33 (30-37) | -3.3000 |
| Host, +100 deg/s, phase 0 ms | candidate | 48 | 0 | 0 (0-1) | +0.0000 |
| Client, -100 deg/s, phase 16.667 ms | reference | 12 | 1 | 33 (30-36) | +3.3000 |
| Client, -100 deg/s, phase 16.667 ms | candidate | 12 | 0 | 0 (0-0) | -0.0000 |

For positive rotation, negative shot/camera angle means trailing the reticle.
For negative rotation, positive angle means trailing it. Both historical cases
therefore trailed by about **3.3 degrees**; both current cases were effectively
**zero**. The firing ray matched the camera at the press to within 0.002 degrees
in all four captures. Directions here are measured before random projectile
spread; the final projectile directions are also retained in the trace.

The host reference ran at 30.0005 simulation ticks/s; the candidate at 29.9988.
The one-tick difference is exact in simulation tick counts, despite ordinary
millisecond scheduling variation. These native runs do not reproduce a perfectly
uniform 33.333 ms frame interval or prove a zero-variance retail result.

Both historical/current comparisons return **FAIL with valid captures**, rather
than a setup error. This detects the delay difference; it does not install a
runtime timing fix.

## Controls and acceptance

An independent 48-shot historical repeat also consumed one-tick-old input on
all 48 shots. Its input-timing and camera-alignment comparison passes.
A further 48-shot reference run, captured after the comparator was finalized,
also passes all capture checks and the comparison against the first reference.

An initial comparator checked raw shot/camera angle extremes within 0.25 degrees.
That rejected the same binary against itself: one angle extreme differed by
0.2993 degrees because the actual rotation between sampled frames changed with
scheduling. The raw result is preserved in the local ignored artifact
`build/fidelity/reference-repeatability-strict-raw-angle.json`.

The final gate keeps exact tick counts, millisecond latency bounds, press-camera
alignment, and a camera residual based on the **measured input rotation** between
the consumed and displayed samples. This residual isolates camera/weapon
alignment from frame cadence. It does not assume a one-tick delay: removal of
that delay still fails the independent tick and millisecond checks. Raw angles,
all shots, and minimum/maximum values remain in every report. The provisional
thresholds remain 0 ticks, 5 ms and 0.25 degrees for their respective gate metrics.

Twenty regression tests pass, including missing/truncated evidence, peer faults,
lost projectiles, removed tick delay, camera offset changes, and a bad tail hidden
behind an unchanged median. Early startup captures were rejected for missing
shots or repeated held fire during rendering stalls; those are not timing
reference data. The final fixture warms firing and impacts around the turn and
restores stock starting ammo before measurement.

Two additional synthetic controls used copies of a real captured trace: removing
the end marker was rejected despite its cached passing report, and rotating the
recorded camera by two degrees was rejected by the alignment checks. Original
captures were left intact. The six valid live captures contain 216 measured shots.

## Exact build boundary

- Reference: `f538f7f6692f7ce42c95c94a3aff48ddb0e77fb8`, historical native Mac
  reconstruction with `network.netcode = "lockstep"` verified at runtime.
- Candidate: a working-source snapshot based on
  `408214a23710b87b480c4dc2fbb9743f48561f2d`, including local changes captured at
  20:08 UTC. Source fingerprint:
  `36ee2bd7f8b9d00767cee069048c9b54a199e5f3bfea72639e88765a5a7838c0`.
  Later edits in the shared checkout are outside these measurements.
- Both used the same supplied map files, fixed stock-pistol inventory and
  separated Blood Gulch positions, interpolation disabled, and two native
  processes on one Mac. Signalling stayed on a temporary loopback MQTT fixture;
  no public broker or STUN service was configured.
- The historical diagnostic snapshot includes one pre-match Mac socket-wait
  portability fix (`WSAEWOULDBLOCK`). Its in-match queues and packet formats
  remain historical. Both snapshots use separate diagnostic ports and probe
  hooks; all instrumented file and executable hashes are in the manifests.

This is a measured comparison of native reconstructions, **not retail Xbox
hardware certification**. It does not yet cover the full phase/direction matrix,
high-refresh interpolation, movement and shot origin, real controller processing,
aim assist, packet loss/latency, remote hit adjudication, split screen, or physical
display latency. No normal game source, installed app, personal profile or map
was changed by the test framework.

## Local evidence

These paths are relative to the original checkout and are not present in a fresh
clone. Repeat the documented procedure to generate new evidence; it cannot
recreate the exact uncommitted October 2 candidate from its base commit alone.

- Build manifests: `build/fidelity/reference-v4/manifest.json` and
  `build/fidelity/current-v3/manifest.json`.
- Host evidence: `build/fidelity/host-measured-v2/rate-100-phase-0/`, containing
  `comparison.json`, `reference/shots.csv` and `candidate/shots.csv`.
- Client evidence: `build/fidelity/client-measured-v1/rate--100-phase-16.667/`,
  containing `comparison.json`, `reference/shots.csv` and `candidate/shots.csv`.
- Historical repeat: `build/fidelity/reference-repeatability.json`.
- Fresh independent reference: `build/fidelity/reference-holdout-comparison.json`.
- Negative controls: `build/fidelity/negative-controls.json`.
- Combined summary: `build/fidelity/netcode-fidelity-summary.json`.

Raw logs, requested/effective configuration, asset hashes and signalling counts
are beside each capture. Build/run directories are local ignored artifacts;
this report preserves the findings and build identities in the repository.
