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
