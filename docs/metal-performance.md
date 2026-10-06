# Native Metal performance checks

Keep the original assets and 30 Hz gameplay simulation. Compare rendering work
at an explicit resolution, with the same interpolation, frame cap, VSync and
anti-aliasing settings. A fullscreen ANGLE run renders its original logical
picture and upscales it; its drawable size is not an equal native-resolution
workload.

The packet builder initializes only alignment and trailing padding before
copying a payload. It still owns an immediate copy of transient guest geometry
and preserves every wire byte, bound and rejection. It does not change resource
lifetimes or submit packets asynchronously.

The native host reuses a render pass for consecutive draws with blending
disabled, no visibility query, and the same color and depth/stencil attachments.
Every original draw state is rebound. Resource operations, clears, copies,
queries, presentation, attachment changes and packet completion end the pass.
Blended draws preserve their original per-draw store boundary: the broader
reuse experiment changed captured color bytes and was rejected. Atomic packet
validation and synchronous completion remain in place.

## Repeatable game measurements

`tools/macos_renderer_benchmark.py` freezes a selected host/guest pair and its
bundled dependencies into a fresh output directory. It uses isolated offline
settings and saves, original stock maps, scripted camera input, no screenshots
and no Metal API validation. Diagnostic logging is included in the timings.
It verifies map/player readiness, the actual foreground game PID, requested
settings and a clean game exit. Native sampling excludes the first 150 gameplay
ticks. ANGLE excludes startup and five seconds after player readiness.

```sh
python3 tools/macos_renderer_benchmark.py \
  --assets /path/to/original/assets \
  --host /path/to/halo-metal --guest /path/to/halo_guest.elf \
  --renderer metal --level chillout \
  --output build/performance/chillout-attempt1 \
  --seconds 40 --render-height 0 --fps-limit 0 \
  --vsync off --anti-aliasing fxaa
```

Use `--level b30` for Silent Cartographer. For ANGLE select its matching host and
guest and `--renderer angle`. Each run needs a fresh output directory. The Mac
must be unlocked and the game must stay in front; run measurements sequentially
without concurrent builds or GPU tests. Camera input follows elapsed time, so
loading and spawn timing can shift its phase. Compare draw and submission counts
alongside frame timings and repeat runs before generalizing gains.

For motion comparisons, `--interpolation off --fps-limit 30` requests the
original rendering reference. Native Metal's `--interpolation on --fps-limit 60`
requests smooth rendering with a 60 FPS cap. ANGLE ignores the native-only cap;
with interpolation enabled it uses its existing VSync/display pacing. These
setting comparisons do not establish image or cinematic motion parity.

The output binds binary/map hashes, exact configuration, environment override
names, activation observations and logs. Native results report completed-present
intervals, observed simulation Hz, physical/logical target sizes and host phase
totals. GPU duration overlaps completion wait; do not add them together. The
optional `render-passes` metric counts original-draw passes, excluding separate
clear, filter and presentation passes.

### Private benchmark launcher identity

Earlier frozen app copies retained the normal app's bundle identifier and
`CFBundleExecutable=halo` while a benchmark directly launched `halo-metal`.
Cocoa activation could open the copied primary executable, creating an extra
Halo instance and moving foreground ownership away from the measured PID.
Affected runs cannot establish gameplay performance.

Each frozen pair now uses a private `Halo Renderer Benchmark.app` with a unique
bundle identifier and `CFBundleExecutable` set to the selected host's exact
filename. It contains only that selected executable and registers no URL
handlers. Packaged Frameworks and Resources retain their relative paths; raw
hosts retain their existing external library paths. Host and guest bytes remain
identical to their selected sources, with no resigning or claim that the private
wrapper preserves the original whole-app signature. Existing data/save
environment overrides also bind OS relaunches to the isolated run directory.
CPU tests check the private identity, executable metadata, omitted URL handlers,
relative dependencies and unchanged binary hashes.

The optional `--interpolation on|off` argument uses the existing Smooth Motion
setting, defaulting to on. Native frame caps apply only to native Metal. ANGLE
with interpolation off retains original 30 FPS pacing; ANGLE with it on uses
its existing VSync pacing rather than the native cap.

## Rendering checks

`tools/test_metal_render_pass_reuse.py` compares intermediate color, depth,
stencil and query bytes between isolated and reused passes with Metal API
validation enabled. It covers attachment and command-buffer changes, copy/clear
boundaries, rejection cleanup and fractional blended UNorm results.

The production ILP32 ordered-frame replay retains all 378 recorded checkpoints;
the coalesced replay checks six final outputs from 126 original draws in one
submission. Both are needed: per-draw readbacks alone prevent reuse and would
miss a difference introduced by combining draws. These captured-frame proofs
do not establish all-scene retail parity or achieved gameplay FPS.

## October 5 performance pass

The blend-disabled-only implementation preserves all 378 ordered checkpoints
and all six coalesced final outputs with API validation enabled. The focused
GPU fixture produces 13,608 identical checkpoint bytes with 32 isolated draw
passes versus 25 reused passes. All 80 targeted CPU tests and 103 production
FXAA readbacks also pass.

A warmed headless A/B/B/A comparison uses the same ILP32 guest, the same 126
recorded draws at 640x480, and fresh original target seed uploads before every
iteration. Five warmups precede 30 measured iterations in each of four runs.
The pooled median host cost is 5.386 ms before and 4.006 ms after, a 25.6%
reduction across 60 samples per variant. All six final attachment/query outputs
match exactly in all four runs. Individual medians are 5.810, 4.047, 3.939 and
4.593 ms; baseline drift limits the precision of the pooled percentage.

This measures host packet copy, preflight, encoding and GPU completion. It
excludes live gameplay packet building and presentation, uses the captured
resolution, and does not establish native-resolution gameplay FPS. Evidence:
`build/metal-poc/performance-pass-headless-timing-attempt1/result.json`, SHA256
`1bc96661d97908313c980092f2255af98c65911221ccacf8424ff7da1490eeb6`.

The reported 15–30 FPS cases are multiplayer Chill Out and campaign Silent
Cartographer. A baseline Chill Out camera run at 3600x2338, interpolation on,
uncapped, VSync off and FXAA averaged 116.37 FPS with 30.007 simulation Hz. This
path did not reproduce the reported drops. Its original harness record remains
failed because a focus check raced the natural timer exit; separate recollected
timing/exit evidence retains that limitation rather than rewriting the result.
The harness now checks process exit after a foreground observation. Earlier
locked sessions, launcher identity failures and lost-focus runs remain invalid.

### Completed fullscreen comparison

All ten cases in `build/macos-metal/performance-pass-attempt1/matrix-attempt5/`
passed foreground, configuration, binary and clean-exit checks. Its `matrix.json`
SHA256 is `5ee5bb8bb61f94e81c4eba557da49575c7710551a91fc0527f616c86680b2395`.
Native runs render at 3600x2338 with FXAA, interpolation enabled and no frame cap.
Both native variants use the same new guest, so these pairs measure host pass
reuse rather than isolating the guest payload-copy change.

| Stationary scene | VSync | Original host FPS | Pass-reuse host FPS | Original / reuse p95 ms |
| --- | --- | ---: | ---: | ---: |
| Silent Cartographer opening | Off | 35.59 | 38.98 | 44.80 / 40.49 |
| Silent Cartographer opening | On | 34.48 | 39.03 | 49.65 / 40.26 |
| Chill Out, offline solo | Off | 147.32 | 153.71 | 10.12 / 9.83 |
| Chill Out, offline solo | On | 118.79 | 118.73 | 9.64 / 9.63 |

The campaign opening reproduces severe slowdown and long stalls; the solo
Chill Out path does not reproduce the reported multiplayer drops. Campaign
frames still reach 182–252 ms, and observed simulation progress averages about
29.2–29.3 Hz despite the unchanged 30 Hz simulation schedule. VSync does not
explain that campaign slowdown. This is one before/after pair per setting;
camera phase, scene activity and thermal drift limit causal/general claims.

ANGLE references average 313.21 FPS in the campaign opening and 463.61 FPS in
solo Chill Out. Their original rendered picture is 738x480, substantially fewer
pixels than native Metal. Those swap measurements do not prove equal-resolution
renderer performance or actual display refresh. Both references also retain
their own shader/asset-loading stalls.

These are 40-second stationary `look:0` runs with audio disabled and diagnostic
logging included. They exclude multiplayer peers, combat, campaign traversal
and input-latency validation. Original map/UI hashes are bound in each record;
the player-readiness check confirms a player, rather than a complete scenario
or all participants. Idle physical controllers are assumed. The private launcher
identity correction is commit `de52b60a`; its 16 focused CPU tests pass.

### Final merged-main validation

The dual renderer build succeeds at
`7ad3151071a23565ae38d41b9de1ddda6519558e` after merging current main. All 95
targeted renderer/transport/benchmark/interpolation CPU checks pass, as do 36
presentation, controller/input, camouflage, Overshield and solo-start
compatibility checks. The installed app passes strict signature verification;
its BuildInfo source and both guest hashes match the build. An initial personal
settings checksum changed during installation, so that comparison is not
reported as unchanged. The subsequent isolated content checks leave the current
personal configuration untouched.

Four 30-second original Silent Cartographer loading checks pass with Metal and
ANGLE, each with Smooth Motion off/on. All use isolated settings/saves and exit
cleanly with original draw activity and no recorded runtime faults. Metal API
validation is observed, including native 3600x2338 storage/drawables and
advancing gameplay ticks. Evidence:
`build/macos-metal/performance-pass-attempt1/final-motion-content-smoke-attempt1/motion-content-smoke.json`,
SHA256 `b1791f4ba8c8e2a42609b9c518e8873f8a26ae6f16bc738c3ba23238b6fb5edb`.
These have no foreground, FPS, visual-motion or image-parity gate. The earlier
foreground motion attempt lost focus and remains failed, with its timings
discarded. The reported Pelican jump still needs a focused visual playtest.
