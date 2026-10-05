# Native Metal build selection

The Mac renderer is fixed at build time. `tools/macos_build.py --renderer angle`
is the default and keeps `build/macos`, the GLES guest bridge and ANGLE libraries.
`--renderer metal` selects `HALO_MACOS_NATIVE_METAL=1` and writes to
`build/macos-metal`. There is no new application environment variable.

The native guest selects `d3d8_metal.c` and omits `d3d8_gl.c`, `gl_functions.c`,
generated GL stubs, GL imports and Khronos headers. Its import table keeps SDL
input, audio and event services, the existing system services and the native
Metal command interface. The native host omits the GL resolver, GL bridge and
GL performance wrappers, EGL/GLES linking, ANGLE rpaths and ANGLE packaging.
SDL, Cocoa, Metal, QuartzCore and Sparkle remain.

Native playtest configurations now have two additional integer settings. They
use config files, with no environment overrides:

```toml
[display]
frame_limit = 60       # 0 (uncapped), 30, 60 or 120
render_height = 0      # Native drawable pixels; fixed-height presets also remain available
fullscreen = true
screen_width = 0       # Use the display aspect at startup
interpolation = true
vsync = false
high_res_hud = false
direct_camera = false
```

The focused fullscreen playtests use `render_height=0`, `screen_width=0` and
`fullscreen=true`. Native color/depth backing is resolved after SDL creates and
synchronizes the Retina window, using its actual drawable pixels. Independent
X/Y scale ratios cover the complete drawable despite rounding the logical
screen width. Display aspect uses the existing wider-screen game path; authored
textures, shader constants and gameplay remain logical. Restart after changing
resolution or moving to another display. The backing remains fixed until restart.

On this Mac the measured fullscreen drawable is **3600x2338**, with the original
logical vertical canvas of 480 lines and a logical width of 738. That is about
35% more pixels than the previous 2880x2160 preset. It describes the current
macOS drawable, not a forced system display mode. The new focused chooser offers
native 60/120 caps with VSync independently on/off, plus native uncapped; lower
presets and the original 30 FPS reference remain available for internal comparisons.

The host caches exact validated sampler states, including raw float LOD bits and
border companion states, with a bounded 256-entry fallback. Draw input slices
share one immutable packet buffer per synchronous submission. Texture uploads and
visibility result words keep separate lifetimes. Original command order, shader
code, atomic packet validation and synchronous completion remain unchanged.

`debug.gpu_stats=true` enables completed-present intervals and host aggregate
metrics. Performance runs use `--timing-only --api-validation off`, disabling
screenshots and explicitly recording diagnostic logging cost. These runs cannot
promote playtest launchers; separate API-validation runs with full-size captures
are required. GPU duration overlaps completion wait and must not be added to it.

The reference profile uses interpolation=false, frame_limit=30 and
render_height=480. The original throttle owns that mode. Other profiles enable
the existing presentation interpolation and apply a monotonic deadline cap
after native submission, before pumping the next frame's input. Lateness below
one period retains the absolute phase, allowing a light interpolation frame to
recover after a heavier simulation frame. A whole period of lateness starts
fresh; loading pauses do not accumulate catch-up frames.
Vsync is independent: cap0/vsync=true follows display pacing, while
cap0/vsync=false applies no additional software wait. These settings do not
change TICKS_PER_SECOND or the original gameplay tick queue.

Render height changes actual color/depth allocation, raster viewports, scissors,
clears, history copies and screenshot readbacks. D3D surface metadata, original
shader constants, texture dimensions and menu/input coordinates remain logical.
Only targets matching the logical screen dimensions are enlarged; authored
textures and smaller water/offscreen targets retain their original dimensions.
Fractional scaling rounds shared rectangle edges once, so adjacent split-screen
rectangles agree. The render height is chosen at startup, avoiding live backing
replacement. At the original 4:3 shape the five presets allocate 640x480,
960x720, 1440x1080, 1920x1440 and 2880x2160. These are rendering presets;
they do not replace original HUD artwork.

`tools/metal_playtest_profiles.py` prepares fresh isolated human playtest saves,
promotes exact profiles against a new `--display-options --fixed-function` build
proof and bounded runtime evidence, and creates a Terminal chooser over those
profiles. Each launcher verifies its frozen binaries/config/evidence before
running. Original asset directories are referenced without modification.
Bounded runtime success is distinct from achieved FPS, manual input/audio,
original pixel fidelity and a performance improvement.

The current native fullscreen checkpoint is
`build/macos-metal/native-fullscreen-build-proof-attempt3/result.json`
(SHA256 `5104e543b18e91a459702a8891aa2298cae2d8598e98f31be0675a14dd5bbb9b`).
The observed build binds 41 source/binary inputs and 26 evidence files, including
the actual ILP32 native-size and pacing objects and their final guest exports.
All 154 targeted CPU tests pass. The 13 pacing fake-clock cases also pass in an
actual 32-bit-pointer guest (`frame-pacing-ilp32-attempt6`), including alternating
22 ms/7 ms work at 60 FPS and long-stall reset boundaries.

Host cache validation preserves all 378 ordered original color/depth/stencil/query
checkpoints, all 1,050 volume-color readbacks and 20 atomic rejection cases,
26 history readbacks, and the 26 visibility-query cases. Alpha-border attachment
bytes match the frozen baseline exactly, with 13 atomic rejections. Its existing
ideal-rounding oracle still reports 246 color-component differences; this is
preserved separately and is not reported as passing. The host validation outputs
are under `build/metal-poc/*native-cache-attempt1/` and bind the unchanged host
implementation used by the final pacing build.

The focused ready chooser is generated under
`build/macos-metal/native-fullscreen-playtests-attempt2/chooser/`. Each profile
requires a separate API-validation run and a complete 3600x2338 physical capture
under `native-fullscreen-runtime-attempt2`; the initial unmeasured native probe
cannot be promoted. Older profile folders and evidence are preserved.

Timing observations use the same native aspect, original assets and scripted
`bot:0` input with fresh saves, no screenshots, API validation off and diagnostic
logging included. `tools/metal_native_benchmark.py` independently verifies the old
host's frozen build, swaps only that host while sharing the new guest, and records
original submission/draw counts. It does not produce readiness or fidelity proof.

| Native 3600x2338 observation | Render FPS | Median / p95 frame time |
| --- | ---: | ---: |
| Previous host, original cap planner, two runs | 49.89 / 50.16 | 19.98 / 24.24 ms; 19.39 / 25.04 ms |
| Cached host, original cap planner, repeated 60-cap run | 54.26 | 16.87 / 24.02 ms |
| Cached host, revised cap planner, 60 cap | 58.29 | 16.69 / 20.09 ms |
| Cached host, revised cap planner, 120 cap | 59.96 | 15.66 / 22.90 ms |

The first host comparison is retained in `native-fullscreen-benchmark-attempt1`;
the revised planner observation is `native-fullscreen-pacing-benchmark-attempt1`.
The final 120-cap observation is `native-fullscreen-final-120-benchmark-attempt1`:
59.96 render FPS, 29.98 simulation Hz and a 60.83 ms maximum interval. The cap
does not establish sustained 120 FPS.
An additional cached-host run with the old planner averaged 51.52 FPS including
a 1,026.70 ms interval. That interval correlated with about one second blocked
in CAMetalLayer `nextDrawable`; its underlying compositor/availability cause is
unresolved. The final planner run retains a 198.37 ms maximum interval. These
outliers are included, and smooth sustained 60/120 FPS is not established.
Healthy host-comparison runs observed 29.98-30.00 simulation Hz; pauses lower the
measured wall-clock average without changing the original 30 Hz simulation step.
The original-planner 120-cap/uncapped native observations averaged 65.33/64.47 FPS
under `native-fullscreen-benchmark-modes-attempt1`, not 120 FPS.

The remaining per-draw LOAD/STORE render passes and synchronous GPU waits are
measured costs. Any future adjacent-draw pass grouping requires separate grouped
state/boundary tests; the 378-checkpoint replay alone submits one draw per packet
and would not exercise that optimization.

The display-options build checkpoint is
`build/macos-metal/display-options-build-proof-attempt1/result.json`
(SHA256 `449e8dcd8f1f7994c4cad9774a71f85a09f7e5b7f80c7bce56f0c7e95eee3208`).
Its successful incremental native build binds 41 source/binary inputs and 23
additional evidence files, including both actual ILP32 helper objects, config
registration and final guest exports. Existing older proof contracts remain
unchanged when `--display-options` is omitted.

Fourteen independent 20-second API-validation runs under
`build/macos-metal/display-runtime-attempt3/` completed with host and guest
exit 0, no renderer/API errors, the requested physical capture dimensions and
positive original simulation ticks. The runs cover Blood Gulch's reference
30 FPS, 30 FPS at 1080 lines, 60 FPS at all five heights, 120 FPS at 480/1080
lines, uncapped at 480/1080 lines and display pacing at 1080 lines, plus
Damnation and Hang 'Em High at 60 FPS and 1080 lines. Their saved
world/weapon/HUD images were inspected for presence and alignment. This is
bounded coverage, not original pixel parity or a full gameplay test. Simulation
telemetry after startup averaged approximately 29.84-30.00 Hz across these runs.

The ready human chooser is generated separately under
`build/macos-metal/display-playtests-attempt3/chooser/`. It keeps initial config
bytes as provenance while allowing normal preference saves/default insertion;
display/offline/diagnostic controls remain fixed to the tested profile. Runtime
logs, configs, executions and captures remain separate immutable evidence.
Original proprietary assets and these local build artifacts are not distributed
as source changes.

Additional validation-off diagnostics preserve their own results under
`build/macos-metal/display-runtime-without-validation-attempt1/`. For the
13 one-second intervals beginning at original tick 150 or later, Blood Gulch's
60 cap at 1440x1080 averaged 59.776 render FPS and 30.003 simulation Hz. The
120 cap at 640x480 averaged 64.485 render FPS and 29.955 simulation Hz on this
Mac. Uncapped 1440x1080 averaged 65.577 render FPS and 30.004 simulation Hz
over the same interval selection. These movement/firing runs include screenshots and shader warmup; they
are not a controlled renderer-performance comparison. The 120 setting is a cap,
and sustaining 120 requires further optimization. Validation-off diagnostics
cannot promote a profile into readiness.

The SDL guest creates the window and exposes its handle through
`platform_video_native_window()`. Device `Present` owns native submission and
presentation. `halo_video_apply_settings()` calls the frontend's
`halo_metal_apply_video_settings()` and resets interpolation only when that
callback succeeds. The callback must report only settings that presentation
actually applies. The high resolution HUD's CPU metrics remain available;
its GL upload API is absent in the native build, so native GPU use requires
an explicit backend upload implementation.

For an isolated host integration check after the native import table exists:

```sh
python3 tools/macos_build.py --renderer metal --host-only --build-only
```

`--build-only` avoids app packaging and cannot be combined with `--install`.
Compiler dependencies may be reused from the existing local toolchain.
The native compiler wrapper uses a separate `build/macos-metal/guest_rebase.dylib`.

The live batched build is frozen under
`build/macos-metal/live-batched-build-proof/`. Its 32 source/binary bindings
include the complete-command reservation helper and normal exit flush paths.
Original commands are queued until a capacity or explicit sync boundary;
the host remains synchronous for each submitted batch. Batching does not
establish cached query timing, frame pacing or a gameplay performance gain.

The additive texture build is frozen separately under
`build/macos-metal/live-volume-linear-build-proof/`. It binds 34 source/binary
inputs, the rendered-mip planner and volume extraction objects, their actual
ILP32 compile commands, exported implementations and final guest linkage.
`tools/metal_live_build_proof.py --texture-contract copy-volume` records the
changed backend/ABI/transport hashes explicitly. Its successful build gate
does not close GPU sampling, original water, manual gameplay or fidelity gates.
The original build proof and binaries remain preserved.

Native shader-read volumes use explicit texture type3/cap8192 and existing
CREATE_EX/UPLOAD_EX records with depth and image pitch. The native CPU frontend
extracts each authored 3D mip from original guest memory and uploads it without
mip generation. The original Blood Gulch distance-attenuation allocation has
six 32³-to-1³ levels; a real failing runtime dump matches all 37,449 authored
bytes of that original asset. The native border contract accepts literal RGBA0
and anisotropy1 with point min/mip plus linear mag, or linear min/mag/mip.
Volume render targets, compression and copies remain unsupported. The later
RGBA border extension is a separate explicit contract.

The volume-colour milestone is frozen under `build/macos-metal/live-volume-colour-build-proof/`.
`--texture-contract copy-volume-depth-border` binds the same 34 primary inputs
and 16 supporting inputs, including the original linked `rasterizer_globals`
object and its asserted floating-Z field offset. The source-backed D24 path
requires original integer-D24 request/current-target metadata, floating-Z off
and original viewport depth units before opting into fragment depth replacement.
The cache includes its effective depth contract, and the fragment compiler keeps
the safe floating-point policy for its finite guards.

Capability16384/opcode21 adds authored RGBA volume borders with an identical
transparent-black/opaque-white pair of native samplers on the same original
volume. Optionsv3 reconstructs `black + borderRGBA * (white - black)` before
the original pixel operations. The two validated volume footprints remain
point min/mip plus linear mag, or all-linear, with anisotropy1 and authored
mips. Legacy opcode19 and optionsv1/v2 retain their contracts and read limits.
CPU packer and independent GPU proofs are in
`build/metal-poc/volume-colored-border-source-ready/closure.json` and
`build/metal-poc/volume-colour-gpu-current-attempt4/independent-closure.json`.
The GPU fixture passed 1,050 exact readbacks and 20 atomic rejection cases;
the fresh original-draw regression passed all 378 checkpoints under API
validation in `build/metal-poc/host-frame-volume-colored-current-attempt2/`.
These component checks do not establish original dynamic-light draw parity,
physical Xbox sampling precision or a completed playable game.

The later campaign-state build is frozen under
`build/macos-metal/campaign-original-state-build-proof/` (proof SHA
`125be740c94210434d269ed13a42ec3e9c35fab3887a8263b9aa1835d8aee86f`).
It retains the same wire ABI and all 50 build bindings. Actual Keyes and The
Maw failures exposed an original lighting pad lane, `c[-73].w = 0xffffffff`:
the captured vertex program uses XYZ in a DP3 and does not use that padding.
Both CPU packer and native host now preserve all 3,072 raw constant-bank bytes.
Viewport, the remaining 48 vertex-uniform bytes, pixel uniforms, expanded
vertex inputs and raster state retain their numeric validation. No padding is
rewritten and no shader compiler policy changed. The actual ILP32 CPU proof
passes 193 cases, including both captured campaign banks, at
`build/metal-poc/native-draw-state-raw-bank-ilp32-current/closure.json`.

Two Betrayals exposed the original mirror pass: a 320×240 secondary color
target reuses the primary depth buffer. Native passes now explicitly use the
color footprint and accept a larger depth attachment; a smaller depth
attachment remains unsupported. Whole-attachment clear optimization requires
the rectangle to fill every selected attachment. Otherwise the partial clear
loads existing depth/stencil and preserves pixels outside the color footprint.
The independent real ILP32 GPU fixture verifies 45 exact readbacks, seven late
atomic rejections and 28 saved byte/version checks at
`build/metal-poc/unequal-attachment-current-attempt1/independent-closure.json`.

All three formerly failing campaign openings completed fresh 30-second,
unskipped Normal runs on this build with host/guest exit0, API validation and
scene-reviewed captures under `build/macos-metal/campaign-original-state-attempt1/`.
These are bounded cinematic checks, not completed missions. The fresh original
frame regression also preserves all 378 color/depth/stencil/query checkpoints,
versions and sequences at
`build/metal-poc/host-frame-original-state-current/independent-closure.json`.
That frame does not itself exercise nonfinite campaign padding or unequal
attachment sizes; those have the separate CPU, GPU and campaign evidence above.

The subsequent complete stock-content check is retained at
`build/macos-metal/stock-content-original-state-23-current/result.json`:
13 fresh multiplayer maps passed 15-second scripted movement/firing runs and
10 fresh campaign openings passed 30-second unskipped Normal runs, all on the
same frozen build with API validation and scene-reviewed images. A30 uses an
explicit earlier same-run cockpit image; its final white cinematic frame is
preserved and is not counted as visible world evidence. These fresh starts do
not establish successful map changes within one process.

The historical same-process Blood Gulch→Damnation probe fails during the original loading
screen blur. Its `GetBackBuffer(0)` and `GetBackBuffer(-1)` return the same
surface, causing all four sampled textures to alias the draw color attachment.
The native encoder correctly rejects that feedback. The failed run and source
contract are retained under `build/macos-metal/map-transition-125-attempt2/`.
The original experimental launchers in
`build/macos-metal/native-metal-playtest-original-state/` start Blood Gulch,
Damnation or Hang Em High separately with normal input/audio and isolated saves;
their ready flag applies only to initial-map playtesting on that frozen build.

The indexed-history build is retained at
`build/macos-metal/indexed-history-build-proof/result.json` (SHA `4b240709…`).
It keeps the primary surface stable and uses a distinct history surface. Each
`Present` copies the completed primary color image into history after the
primary screenshot/readback boundary. Seven CPU checks and 26 exact GPU
readbacks cover identity, copy order, retained history and atomic rejection.
The actual game completed four Blood Gulch/Damnation changes with host/guest0
and API validation in `map-transition-indexed-history-attempt1`; all five
post-load images show their respective world, weapon and HUD. Physical Xbox
swap timing, exact stale-resource readbacks and full-game parity remain open.
Synthetic resize checks do not cover the actual guest's disabled resize branch.

That history fixture preserves an inherited defect: `SetVertexShader(0)` was
ignored, retaining a UI shader that reads the wrong immediate registers and
draws only a one-pixel footprint. Its captured-route success proves transport
and history ordering, not the intended fullscreen loading fade. The later
`fixed-loading-build-proof/result.json` (SHA `1fc22efa…`) adds the original
unlit immediate route with World/View/Projection, diffuse v3 and texture
registers v9–v12. Programmable slots and the original constant bank are retained.
Other FVF/lighting/generated-coordinate modes remain explicitly unsupported.

The build proof's opt-in `--fixed-function` binds the helper C/header and actual
linked ILP32 object: 36 primary plus 17 supporting inputs. Defaults retain the
historical 50-input contract. The source/guest CPU proof checks 288 packing
cases, eight selection controls and 8,191 handle lookups. The GPU fixture at
`build/metal-poc/intended-fixed-loading-current-attempt3/independent-closure.json`
(SHA `fe8f0260…`) executes 16 production ILP32 helper calls and passes 28 exact
controls plus three gradient checkpoints within a predefined one-byte filtering
bound. Actual GPU history-copy bytes remain exact; 21 successful submissions and
one late rejected packet preserve five saved byte/version baselines. Expected
after-images are never uploaded. These proofs do not establish physical Xbox
filtering precision, original loading-animation pixel parity or gameplay
performance. The later `map-transition-fixed-loading-attempt1` run completes
four alternating map changes on this same build with host/guest0 after
240.502354459 seconds and API validation. Its five post-load gameplay images
are reviewed separately; the producer's global `passed=false` remains intact.
An additional current-build Hang Em High 15-second opening is retained at
`fixed-loading-hang-em-high-smoke-attempt1`, with its world/pistol/HUD image
reviewed. This does not re-test the older build's 23-map opening ledger.
Manual input/audio, full missions and roof glyph clipping remain open; the
new fixed-loading handoff has its own per-map readiness proof.

The static viewer's copied, instrumented roof probe retains unchanged original
production rendering. Its six RGB baselines match byte-for-byte; one synthetic
roof pose shows depth-dependent loss of 20 dim-red pixels at640 and six at1280.
The two recorded roof poses show no loss. A focused glyph-depth follow-up stores
the actual raster depth and matches it against independent MRT output and opaque
depth reads. The failed pixels are 1–24 float32 ULPs farther; invariant
A/B changes no color, depth or query bytes. These results are in
`build/metal-poc-0.6/roof-depth-focused-prepared-attempt3/independent-audit/`.
They justify neither a depth-bias change nor an original-clipping fix claim.
The exact user roof/downward case remains open. A later ten-case replay uses a
fresh original ANGLE frame's exact matrix, geometry, UVs and compressed mips.
Neither static control rejects glyph depth at that matrix; the original viewport
bridge matches the 724 visible contribution pixels, with one rounded composition
byte still unequal. It does not establish a production clipping fix. The actual
human native-game playtest also exposes a speckled base glyph at sniper 10× zoom;
that live-game rendering bug remains open. Prior mip0-only CPU ray checks are not
GPU depth proofs, and F5 capture is currently limited to the static viewer.

Independently rendered water levels use cap4096/COPY_SUBRESOURCE20. Aliases are
planned using original physical mip offsets, then every requested level is
copied before current attachment binding. A source-bound initial volume build
ran original Damnation for 15.34 seconds with host/guest exit0, API validation,
73,014 original draws by frame420 and the actual 128×128 four-level composite
logged in `build/macos-metal/live-volume-water/damnation/result.json`.
That startup proof preserves its own earlier backend snapshot; it is not
rebound to the later all-linear build. Pixel parity, missing-tail generation
and broader gameplay still require separate evidence.

`build/macos-metal/live-game-bloodgulch-batched-attempt2/result.json` records
an actual controlled startup of that frozen build: host/guest exit zero,
93,780 original draws by frame360, 640×480 game and a 2560×1920 windowed
drawable with API validation. The preceding uncontrolled attempt retains an
unsupported texture-layout failure at frame70; broader gameplay stays open.

`tools/test_macos_renderer_build.py` checks default and native guest graphs,
host source/link graphs and retained SDL/system imports. The first native host
and ILP32 SDL/HUD boundary checks are recorded in
`build/macos-metal/native-build-proof`. A host link and boundary compilation
do not establish a playable native game. The complete guest and host now
compile and link; `build/macos-metal/live-menu-current/result.json` records
actual original menu rendering with no GL/ANGLE imports or linkage and exit zero.
The subsequent source-bound
`build/macos-metal/live-game-bloodgulch-alpha-attempt4/result.json` passes actual
Blood Gulch startup with weapon/HUD/radar after the narrow alpha-border extension.
Its strict ideal-byte sampler oracle still fails at rounding ties.
Gameplay, timing, presentation fidelity and performance gates remain open; no
experimental native app was packaged or installed. See
[the live adapter ledger](metal-game-adapter.md).

## Integration with the current main branch

After the source-only renderer checkpoint `54c6276b`, the branch integrates
`main` revision `18f30a0617d9741eecee056328ed8c2d1268d276`. The build-tool merge
retains both default ANGLE/native Metal selection and the current version,
release-discovery and CI metadata contracts. The new incomplete-data exit uses
the native pending-command flush helper. The first-run C fixture includes that
production helper; its focused 26-test integration run passes. The separate
build/dependency/version/release/content suite passes 86 tests with one skipped.

The complete native rebuild exits zero in 153.83 seconds. Its new source/object/
binary freeze is `build/macos-metal/main-integrated-build-proof/result.json`
(SHA `1e1f4911…`), with 36 primary and 17 evidence bindings and no GL/ANGLE
imports or linkage. The observer's original execution record is preserved;
only a copied log-path descriptor is normalized for the existing proof schema.
This is build/link evidence. The earlier gameplay and GPU results retain their
own frozen binaries and are not rebound to this integrated build. No new live
game test, FPS limiter or render-resolution setting is established here.
