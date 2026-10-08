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

The host retains one shared draw-input buffer up to 16 MiB, matching the guest's
normal soft batch size. It copies guest bytes directly into that storage once
under the host mutex, after the prior submission has completed. An immutable
view carries the current packet extent through validation and execution; no
zero-filled intermediate vector or second full packet copy is needed. Larger valid
packets use temporary exact-size buffers. Command-local payload bounds still
reject offsets into unused retained capacity. Shutdown releases the buffer.

Pipeline entries cache immutable shader binding requirements and texture masks.
Each public prepare/encode call still validates the current geometry, textures,
samplers and border companions. Encoding uses the pipeline and depth state from
that validation without looking them up again. Draw order, state rebinding,
blended pass boundaries, shader compiler flags and synchronous completion are
unchanged.

Native Metal decodes compact vertex input on the GPU by default. To compare with
the CPU input path, set this in the local configuration and restart:

```ini
[debug]
metal_gpu_vertex_decode = false
```

The default is `true`. Eligible draws snapshot their original compact streams
into owned packet storage, and the vertex shader decodes the input registers.
The original NV2A instruction translation then runs unchanged. Immediate draws
and draws whose compact payload would be larger retain CPU expansion. There is
no environment-variable override, geometry cache or asynchronous submission in
this path. With `gpu_stats = true`, `Native vertex input` records the
selected draw counts and compact/uploaded/reference vertex bytes per frame.

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

New renderer benchmarks, Mac benchmark/multiplayer/map-collection checks and Metal playtest
profiles enable the original on-screen FPS counter with `display_framerate true`
in their isolated `init.txt`. Display runtime and native benchmark runs inherit
the profile startup script. The counter appears at the bottom right and averages
rendered frames over half a second; it is separate from the 30 Hz gameplay tick.
Use the same command for any ad-hoc visible game test. Existing frozen evidence
and pixel-comparison fixtures retain their recorded startup scripts. Earlier
performance measurements below did not include this counter; new measurements
include its small HUD rendering cost.

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

## October 8 allocation and preparation pass

`tools/test_metal_packet_buffer.py` exercises the production host with Metal API
validation enabled: changing packet payloads produce exact expected color bytes;
late-invalid commands leave attachments and submission sequences unchanged;
growth, smaller packets, oversized temporary allocations, command-local bounds
and context reset are checked. The draw-encoder fixture also checks cached
requirements against changed textures/samplers, sparse stage masks, unsupported
shader bindings and cache eviction.

A headless A/B/B/A sequence repeated twice compares frozen pre-change host and
encoder sources with both optimizations. Each run warms five packets, then
measures 100 synchronous submissions of 32 untextured draws to a 4x4 target,
with 512 KiB of extra packet padding. Median-of-run-medians falls from 0.382 ms
to 0.317 ms (17.2%). Warm measured packet-buffer allocations fall from 100 to
zero per run. All eight runs complete and the final expected color bytes match.
Evidence: `build/renderer-pass-20261008/result.json`, with source/binary hashes
and individual run timings. This isolates allocation/preparation overhead on a
controlled workload; it does not establish gameplay FPS or smoother motion.

Two 40-second Silent Cartographer opening runs use the rebuilt native host with
the same existing guest, original assets, isolated settings/saves, stationary
camera, Smooth Motion on, uncapped rendering, VSync off and AA off. Both pass
foreground, settings and clean-exit checks; timing excludes the first 150
gameplay ticks and includes diagnostics and the FPS counter.

| Internal render height | FPS | Median / p95 frame ms | Max frame ms | Observed simulation Hz |
| --- | ---: | ---: | ---: | ---: |
| Native | 42.10 | 21.50 / 36.85 | 163.66 | 29.37 |
| 720p | 52.75 | 16.83 / 30.70 | 170.48 | 29.48 |

These compare resolutions on the updated host, not pre/post gameplay
performance. GPU cost falls from 5.90 to 2.40 ms/frame and completion wait from
8.47 to 4.56 ms/frame, while packet copy remains about 2.35 ms/frame. Each frame
still submits about 5.2--5.3 synchronous packets containing about 19 MB in total
and allocates roughly 20 visibility-result buffers. Both runs have zero warmed
packet-buffer allocations, but long stalls remain; neither establishes steady
60/120 FPS. Evidence is in `campaign-native/benchmark.json` and
`campaign-720p/benchmark.json` under `build/renderer-pass-20261008/`.

The planned follow-up for this allocation pass was a live comparison of original
Chill Out and Silent Cartographer at matching internal resolutions, recording
median/p95 frame intervals, simulation progress, preparation/GPU/completion waits
and allocation counts. Combat, traversal and multiplayer observations are needed
before claiming a general gain. Native resolution can be much more expensive
than 720p/1080p.

At this stage, the next investigation was to attribute campaign waits to the
then-current 4 MiB batch limit, visibility collection,
texture-cache `KickPushBuffer`, profiling callbacks and presentation. Native
visibility collection flushes and waits; changing its availability policy can
change lens-flare timing.

Other optimization candidates are guest geometry scratch allocations,
upload staging buffers and preflight resource-map copies. Asynchronous submits
need separate in-flight ownership, retirement, query/readback and input-latency
validation. Broader blended pass reuse remains rejected by the earlier captured
byte comparison. Keep the 30 Hz simulation and original shader math unchanged.

## Silent Cartographer cutscene stall attribution

The October 8 diagnostic pass records every real guest flush reason and wire
sequence, individual source-library compilations, host packet phase counters,
pipeline creation time and the original cinematic/input flags. Enable the
existing `debug.gpu_stats` / `HALO_GPU_STATS` diagnostics; no new setting is
required. `tools/metal_cutscene_analyze.py LOG --output analysis.json` joins
host and guest packets by sequence and maps guest frame N to completed frame
N+1. Host and guest timestamps have different epochs. GPU time overlaps
completion waiting; shader/pipeline creation is contained in packet preparation.
These attribution counters must not be added as independent frame phases.

Two isolated 40-second 720p captures remain in the cinematic throughout their
initialized frames. A player existing is therefore insufficient evidence that
gameplay has begun. Both preserve original stock assets, Smooth Motion, the
30 Hz simulation, uncapped rendering, VSync off and AA off, with foreground and
clean-exit checks passing. Diagnostics/FPS-counter overhead is included.
Only the native frontend object is rebuilt for these diagnostic guests; all
other guest objects are frozen and reused equally. They are not full builds of
the concurrent dirty checkout. Frozen object and binary manifests are under
`build/metal-cutscene-20261008/`.

The baseline has 15 post-tick-150 present gaps over 50 ms; every one contains
first-use source compilation or pipeline creation. Its cache-warm subset has
no gap over 50 ms (58.93 FPS, p95 29.88 ms, maximum 41.20 ms). One cinematic
frame at tick 845 takes 272.96 ms, including 236.64 ms preparation, 193.68 ms
source compilation and 39.37 ms pipeline creation; GPU execution is 3.26 ms.
An earlier tick-96 frame takes 634.45 ms, including 575.41 ms preparation and
9.05 ms GPU execution. This directly identifies large CPU compiler stalls;
water may contribute to sustained GPU work, but these counters do not isolate
its cost.

### Larger batches and concurrent source compilation

Three further captures run sequentially, with GPU tests/builds stopped. They
compare serial compilation with 4 MiB batches, serial compilation with 16 MiB
batches, and concurrent compilation with the same 16 MiB guest. The serial
host variants differ only in retained packet capacity. All three pass their
foreground/clean-exit checks and sequence joins, and remain cinematic. The
table compares matching simulation ticks 150--1040.

| Variant | Post-tick-150 FPS | p95 frame ms | Warm submits/frame | Warm completion wait ms/frame |
| --- | ---: | ---: | ---: | ---: |
| Serial / 4 MiB | 54.91 | 30.60 | 5.345 | 4.490 |
| Serial / 16 MiB | 58.48 | 27.90 | 1.552 | 3.345 |
| Concurrent / 16 MiB | 58.55 | 28.21 | 1.557 | 3.356 |

The 16 MiB soft limit and matching bounded reusable input buffer reduce small
synchronous submission cycles. The 64 MiB hard limit, explicit visibility,
callback, `KickPushBuffer`, readback, settings, resize and presentation barriers
are retained. Oversized valid packets still receive temporary exact-size
storage; command-local bounds remain independent of retained capacity. These
captures support a scoped batching improvement (about 6.5% average FPS), not a
general gameplay or latency guarantee. Seven production buffer-policy CPU
checks cover growth, exact limits, oversized/fallback allocation and failure;
the updated GPU ownership fixture passes.

Concurrent compilation is bounded to the two missing stages of one program.
Exact source/compiler contracts are preserved; cache hits and single missing
stages use the serial path. Callbacks own only retained request results; both
finish before caller-side function validation and packet-local cache staging.
Publication still waits for complete packet validation. Failure, retry, partial
hit, duplicate, malformed-source and exact-pixel GPU checks pass.

The concurrent capture records 224.02 ms of overlapping source-library
intervals across 14 packets, with at most two requests active. Its first
initialized-frame preparation is 1301.00 ms versus 1454.71 ms for serial
16 MiB; whole-run FPS is effectively unchanged. Source-compile durations can
overlap each other and exceed preparation wall time. Most later misses are
single-stage or pipeline creation, so this does not remove their first-use
hitches: the concurrent capture still has 15 gaps above 50 ms. More complete
prewarming/offline shader work needed separate design and evidence, described
in the later Pelican investigation below.

Evidence: `clean-run-protocol.json`, `clean-comparison.json`, `run-serial-4m-clean-720p/`,
`run-serial-16m-clean-720p/` and `run-async-16m-clean-720p/` under
`build/metal-cutscene-20261008/`. The diagnostics include logging/FPS-counter
overhead, stationary input and a single Mac at 720p. Native-resolution,
combat, multiplayer and visual/retail comparisons remain outside this result.

Water retains independently authored 128/64/32/16 bumpmap levels, original
uniform animation, destination-alpha dependencies, cubemap reflection and
blended draw order. A bounded per-composite signature cache skips only copies
whose source identity, generation, content version, dimensions and mip/slice
coordinates all match. Complete mip planning still validates every binding,
and freshness publishes only after ordered commands append. Eight extracted
production CPU tests exercise invalidation and failures under ASan/UBSan. The
GPU copy fixture passes 254 exact readbacks and 25 invalid-packet cases.

The earlier mip-cache-only intro captures show no useful reduction: 4.927 versus 4.925
subresource copies/frame and 56.24 versus 54.37 post-startup FPS in the two
runs. Both have 15 gaps over 50 ms. Individual compiler timings vary between
runs; this is not evidence of an intro FPS or hitch improvement. Evidence:
`run-baseline-720p/analysis.json` and `run-candidate-720p/analysis.json` under
`build/metal-cutscene-20261008/`.

Scripted camera updates occur per render frame, while interpolation snapshots
are captured once per simulation tick. The B30 intro uses camera-point
transitions and a Pelican-relative point, rather than the separate authored
camera-animation path. Its animation-frame quantization therefore does not
explain this intro. Compilation stalls can trigger the existing multi-tick
interpolation fallback and expose a catch-up jump; camera timing remains
unchanged.

## Pelican pan and beach arrival investigation, October 8

The full fixed-720p 90-second capture covers the intro and combat, with complete
packet/frame joins and a clean exit. A later capture with working camera markers,
`run-final-camera-markers/`, records the actual original camera requests:

| Simulation tick | Original point | Name | Transition ticks |
| --- | ---: | --- | ---: |
| 0 | 14 | `insertion_1b` | 0 |
| 60 | 18 | `insertion_2a` | 120 |
| 120 | 16 | `insertion_2b` | 90 |
| 210 | 17 | `insertion_3`, relative to the Pelican | 0 |

These request ticks are distinct from the first rendered frame after control
returns, around tick 1,067, following the 1,031-tick Pelican recording and dialogue
waits. The repeatable tick-97 hitch occurs during the pan, not at an authored
camera cut.

The 90-second capture records a 252 ms frame at tick 1,074 just after control
returns. Three fragment-library compilations take 194 ms, PSO creation 20 ms,
and GPU work only 4.46 ms. These particular vertex objects map to the original
screen/HUD shader family (table 3/4), distinct from the water shader families.
The runtime function cache finishes with 91 entries and 575,830 source bytes;
its 256-entry/8 MiB limits are not evicting these variants.

An equal-settings replay resets the original map inside the same process,
retaining shader and PSO caches. The user also observed that the replay removed
the large stutters while heavy-scene FPS drops remained. Maximum completed-frame
gaps in the matching original tick windows were:

| Window | First pass | Warm replay | Replay shader/PSO misses |
| --- | ---: | ---: | ---: |
| Initial pan, ticks 60--125 | 566.60 ms | 55.57 ms | 0 / 0 |
| Control return, ticks 1066--1080 | 224.95 ms | 35.58 ms | 0 / 0 |

Both columns come from the first and replay segments of
`run-fixed-720p-warm-replay/`, rather than the separate 90-second capture above.
These are window maxima from one Mac, with logging overhead and changing combat
workloads; they are not a universal frame-rate guarantee. Replay tick reset is
explicitly excluded from interval comparisons. No simulation, camera, shader
math, blend rounding or draw ordering was changed.

The replay's 79 warm frames with at least 800 draws average 926 original draws,
four submissions and 56.50 MB of packet bytes per frame. Their average frame
gap is 47.98 ms, with 20.50 ms host submission wall time, including 7.30 ms
packet-copy time, 4.13 ms preparation and 6.86 ms completion wait. GPU time is
4.46 ms and overlaps that wait. The corresponding heavy block allocates only
one visibility buffer per frame. Query allocation volume is low in that block;
packet copies and draw work are stronger measured candidates. Draw
expansion/emission and command data volume are
the next CPU costs to measure; the GPU remains another part of the budget.

Evidence: `run-fixed-720p-intro-90s/` and
`run-fixed-720p-warm-replay/replay-comparison.json` under
`build/metal-cutscene-20261008/`. Diagnostic camera requests now record original
point names, transition ticks and a separate original render counter. Exact
source fingerprints and full PSO miss keys disambiguate same-length variants.
Guest draw-phase timings exclude nested synchronous host submissions; optional
records are distinguished from zero costs by the analyzer. Diagnostic timing
calls/logging are included in subsequent captures.

### Learned startup warmup and one host packet copy

The host now saves exact emitted source, compiler contracts and successful PSO
descriptors to `Cache/MetalWarmup-v1.bin` under the existing save root. It prepares
those functions and pipelines at renderer startup, before gameplay. Full source
bytes and state authorize reuse; diagnostic fingerprints do not. The manifest
is bounded to 256 functions, 8 MiB of source and 1,024 pipelines. FIFO retirement
keeps learning new maps and drops dependent pipelines. Invalid or unavailable
cache entries use ordinary compilation. Only successfully completed packets
teach the manifest; rejected packets do not. Dirty data is saved atomically on
normal shutdown, with no per-frame disk writes.

Three fresh-process B30 captures use the same frozen diagnostic guest, original
assets, 720p, FXAA, interpolation, uncapped rendering and VSync off on an Apple
M5 Max. These captures enable audio. Each passes foreground, settings, complete
unique packet joins and clean-exit checks. The cold run learns 91 functions and
77 pipelines in a 580,278-byte manifest. Both warm launches prepare all of them
and record zero source compilations or PSO creations throughout gameplay.

| Original tick window, maximum frame gap | Cold | Startup warmup | Warmup and single copy |
| --- | ---: | ---: | ---: |
| Pan, 60--125 | 602.78 ms | 57.18 ms | 56.12 ms |
| Arrival, 1066--1080 | 225.27 ms | 38.70 ms | 34.83 ms |

The baseline warmup takes 4.30 seconds before gameplay. This moves learned
compilation work to startup; the first encounter with an unseen variant still
compiles normally. No source math, camera, simulation or draw ordering changes
are involved.

The single-copy host owns the same shared Metal buffer from the complete guest
copy through preflight, upload, geometry encoding and synchronous completion.
Bounds always use current packet bytes, including record and command-local
payload ranges. Partial guest copies reject before validation or execution.
Oversized valid packets retain the exact-size temporary-buffer path.

The two warm runs have 92 and 96 heavy-pan frames respectively (at least 800
draws, original ticks 3--125), averaging about 56 MB per frame. Combined copy and
preparation time falls from 9.88 to 7.83 ms, about 21%; accounting for packet
bytes gives a similar reduction. Average heavy-frame time changes from 44.93 to
43.00 ms. Post-tick-150 whole-capture FPS is 62.44 and 62.93, with different combat
draw counts; this does not establish a broad steady-FPS gain. These are one
paired capture on one Mac, with diagnostic timing overhead. Allocation moves
into the copy phase, so preparation alone is not an equal before/after metric.

The candidate's warm heavy frames still spend 11.22 ms expanding vertices and
6.30 ms emitting commands, out of 20.05 ms measured guest draw work. GPU work
averages 7.40 ms and overlaps completion waiting. These CPU costs remain useful
optimization targets; reducing packet copies does not eliminate every heavy
scene drop.

Headless tests with Metal validation preserve exact rendered bytes across cache
load, pipeline reuse, rejection and corrupt-cache fallback. The packet fixture
also mutates guest bytes after preflight and proves that execution uses the
owned host snapshot. Eight sanitizer checks cover logical extent, overflow,
retention and oversized allocation behavior.

Evidence is in `run-learned-cache-cold/`, `run-learned-cache-warm-baseline/` and
`run-learned-cache-warm-single-copy/` under `build/metal-cutscene-20261008/`.
Each contains binary/configuration provenance, the full log, `analysis.json`
and `cache-summary.json`. These captures predate the corrected camera-log
compile guard; their camera point timing is derived from the original script,
not camera marker records. The actual marker rows above come from
`run-final-camera-markers/launch.log`.

### Aligned vertex output and the A/B/A bracket

The CPU vertex-fetch helper now expands vertices directly into float-aligned
caller-owned expanded storage. This avoids one 256-byte stack-to-output copy per
vertex while retaining the fixed-register initialization and exact attribute conversions.
Arbitrarily unaligned output retains the stack-copy fallback. Source loads remain
safe for unaligned streams, and bounds and overlap checks complete before any
output is written. Simulation timing, camera updates and draw order are unchanged.

Three 60-second warm-cache captures bracket the aligned-output candidate with the
previous single-copy guest before and after it. They retain the same host,
settings and diagnostic scope described above. Each records zero runtime source
compilations and PSO creations. The matched heavy-pan window uses original ticks
3--125 and at least 800 draws per frame:

| Mean per heavy frame | Single copy, A | Aligned output, B | Single copy repeat, A |
| --- | ---: | ---: | ---: |
| Frames sampled | 96 | 102 | 99 |
| Original draws | 1,071 | 1,084 | 1,067 |
| Frame interval | 43.00 ms | 40.32 ms | 41.68 ms |
| Guest draw CPU work, excluding host submissions | 20.05 ms | 17.76 ms | 19.01 ms |
| Host packet copy plus preparation | 7.83 ms | 7.86 ms | 8.00 ms |

The improvement is concentrated in guest vertex work; the combined host copy and
preparation cost remains similar. Post-tick-150 FPS in these 60-second captures
is 62.93, 68.76 and 61.64 respectively. Combat draw counts and work vary, so those
whole-capture figures do not establish a universal 9--12% FPS improvement. The
bracket supports a narrower reduction in the measured heavy-pan CPU cost on this
Mac, with diagnostic logging included.

Nine CPU tests pass, covering exact conversions, aligned and unaligned output,
multi-stream strides, bounds, overlap rejection and sanitizer checks. The existing
126-draw captured-wire oracle is skipped because its frozen fixtures are missing;
there is no full-frame 126-draw parity proof for this change. The production helper
was compiled and linked with the actual ILP32 guest toolchain. These checks do not
establish complete visual fidelity.

The user confirmed that the white horizon line appears in the original intro and
is expected. No rendering behavior change was made for it. Screenshot captures
with readback overhead are excluded from the performance evidence above.

Evidence: `run-learned-cache-warm-single-copy/`,
`run-learned-cache-vertex-output/` and
`run-learned-cache-warm-single-copy-repeat/`, including their `analysis.json`,
`cache-summary.json` and frozen binary provenance, under
`build/metal-cutscene-20261008/`. The scoped guest rebuild is recorded in
`hitch-diagnostics-vertex-output/build.json`.

### GPU vertex decoding

The compact path copies each active stream's required original byte span once,
including its stride, and carries a 528-byte input description with fixed
register values. Indices retain the existing primitive conversion and rebasing.
The host validates the immutable command-local spans before encoding; raw packed
normal bits remain integers until the original shader unpack operation. Shader
and pipeline keys distinguish compact and expanded input, and warmup skips
compact-only entries when the experiment is disabled. Reading older version-1
warmup files remains supported; new files use version 2.

`tools/test_metal_vertex_decode.py` compares the production GPU decoder against
CPU fetch for all 20 declaration formats, all 65,536 signed-short values and all
256 byte values, unaligned streams, zero strides, fixed and missing attributes,
negative zero, subnormals and NaN-shaped packed normal words. Under the original
fast vertex compiler contract, 33,880,250 register comparisons match exactly.
All 67 original vertex programs compile with both zero and full packed masks
(134 compact shader libraries).

The same fixture packs production guest inputs, converts and rebases original
indices, and renders with original NV2A program 37 through the production host
encoder. RGBA8/BGRA8 color and Depth32 outputs match the CPU path byte for byte:
65,536 identical readback bytes with nonempty, varying coverage. Metal API
validation is clean. Focused pack, guest transport/ILP32, packet, draw-encoder,
function-cache and warmup-cache checks pass, including atomic malformed-packet
rejection and compact-only cache filtering. Scoped production guest and host
compile/link checks also pass.

These proofs cover the decoder and one original-program render comparison;
they do not establish complete retail-frame fidelity across maps. GPU input is
the default; setting `metal_gpu_vertex_decode = false` retains the CPU comparison
path while that coverage grows. This changes vertex input
preparation only; original shader instructions, 30 Hz simulation, draw ordering,
queries and synchronous packet completion retain their existing behavior.

Frozen binaries, build provenance and sequential Silent Cartographer captures
are under `build/gpu-vertex-20261008/` in the isolated
`codex/gpu-vertex-decode` worktree. Each accepted game capture includes its
configuration, foreground checks, clean exit, full launch log and joined frame
analysis. The initial cold learning run is excluded from performance comparisons.

The accepted captures use an Apple M5 Max on macOS 27.0.1, the same frozen
candidate host/guest, fullscreen FXAA, interpolation on, audio on, and VSync/frame
cap off. Runs last 75 seconds with isolated offline settings and diagnostic
logging. Source hashes matched the compiled candidate when the sweep completed.
These captures explicitly selected GPU or CPU input before GPU input became
the default. The
matched heavy opening window retains original ticks 3--125, at least 800 draws
per frame, complete packet coverage and warm shader/pipeline caches:

| Mean per heavy frame at 720p | CPU input, two runs | GPU input, two runs |
| --- | ---: | ---: |
| Original draws | 1,065--1,086 | 1,071--1,082 |
| Frame interval | 41.17--42.48 ms | 18.90--29.06 ms |
| Guest vertex preparation | 10.01--10.51 ms | 1.19--1.94 ms |
| Guest draw CPU work, excluding host submissions | 18.34--19.26 ms | 4.96--8.07 ms |
| Uploaded vertex input | 50.44--50.65 MB | 7.17--7.18 MB |
| Host packet copy plus preparation | 7.85--8.01 ms | 2.44--3.83 ms |

About 75% of draws use compact input in that window; smaller and immediate draws
retain CPU input. Host/GPU phases can overlap and should not be added together.
The spread between GPU captures supports reporting a range. Complete gameplay
workload outside the matched opening also varies between runs.

The requested resolution sweep repeats 1440p and includes the full drawable:

| Vertex path and rendered storage | FPS after tick 150 | Matched heavy opening FPS |
| --- | ---: | ---: |
| CPU, 1107x720 (two runs) | 65.99--69.01 | 23.54--24.29 |
| GPU, 1107x720 (two runs) | 98.10--114.86 | 34.41--52.91 |
| CPU, 2214x1440 | 59.25 | 23.24 |
| GPU, 2214x1440 (two runs) | 100.27--109.39 | 51.01--53.04 |
| GPU, native 3600x2338 | 112.27 | 49.61 |

The 1440p runs render four times the 720p pixels; native renders about 10.6 times
as many. Native-resolution gameplay has a 16.11 ms 95th-percentile frame interval
in this sample, but the heavy opening remains around 50 FPS. Whole-run variation
means the higher native average does not establish that native resolution costs
less. These are samples of one original map on one Mac, rather than a universal
FPS guarantee. Observed simulation remains approximately 30 Hz in every run.

`comparison.json` records exact figures and frozen binary provenance. The eight
accepted runs are `run-cpu-warm-a1/`, `run-gpu-warm-b1/`, `run-cpu-warm-a2/`,
`run-gpu-warm-b2/`, `run-cpu-1440/`, `run-gpu-1440/`,
`run-gpu-native/` and `run-gpu-1440-repeat/`. All complete with foreground checks,
clean guest/host exits and no renderer faults. Runtime cache misses outside the
matched window are retained in the evidence; the warmed matched-window filter
does not imply every complete capture has zero misses.
