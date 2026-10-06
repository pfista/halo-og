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

The output binds binary/map hashes, exact configuration, environment override
names, activation observations and logs. Native results report completed-present
intervals, observed simulation Hz, physical/logical target sizes and host phase
totals. GPU duration overlaps completion wait; do not add them together. The
optional `render-passes` metric counts original-draw passes, excluding separate
clear, filter and presentation passes.

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
The harness now checks process exit after a foreground observation. Optimized
fullscreen, VSync-on, ANGLE and campaign comparisons remain pending because the
Mac returned to the login screen before those measurements could run.
