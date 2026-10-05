# Native Metal adapter for the running game

The actual Xbox-derived game builds and renders through
[d3d8_metal.c](../port/linux/src/d3d8_metal.c), with no GL/ANGLE dependency in
the verified executable or guest imports. This is separate from the static
scene viewer. Corrected frozen build `125be740…` passes fresh, bounded starts
on all 13 original multiplayer maps and all ten original campaign scenarios,
with independently checked execution and saved scene images. Historical
campaign failures remain preserved. Later fixed-loading build `1fc22efa…`
retains 53 bindings, completes four alternating Blood Gulch/Damnation changes
in one process and passes a separate fresh Hang Em High opening. Its bounded
original unlit/immediate loading route has CPU and GPU component proof; complete
original loading pixels, strict stale content and SDK timing remain open.
Three launchers on this frozen build are ready for experimental local testing.
These results verify bounded execution, not complete gameplay, original pixel
parity, manual input/audio, timing or improved performance. The 23 stock openings
belong to frozen 125; they have not all been rerun on 1fc22. Each result retains
its own source snapshot.

## Implemented live path

The fixed `--renderer metal` build retains the original CPU D3D state, selected
vertex program and declaration, constants, streams, palettes, immediate draws,
resource headers, original assets and simulation. It emits MSL directly from
the original NV2A instruction words and pixel-combiner key. The program cache
records explicit vertex and fragment compiler contracts; no GLSL or ANGLE
shader is used at runtime.

- [metal_vertex_fetch.c](../port/linux/src/metal_vertex_fetch.c) expands original
  stream/fixed/immediate inputs into the native register ABI, preserving packed
  integer bits, referenced stream windows and original topology conversion.
  All 126 frozen draw inputs match, including 16,834 vertices and 25,100 indices.
- [metal_fixed_function.c](../port/linux/src/metal_fixed_function.c) handles the
  bounded original `SetVertexShader(0)` unlit/immediate route, preserving the
  original world/view/projection matrices, diffuse/specular inputs, texture
  coordinates, viewport and half-pixel correction. Unsupported fixed-function
  states fail explicitly. This route has separate evidence below; it does not
  replace the original NV2A path.
- [metal_draw_state.c](../port/linux/src/metal_draw_state.c) packs original shader
  keys, uniforms, raster state and samplers. Its default path matches all 126
  captured draws byte for byte. Optional transparent-black hardware borders
  cover authored mip filtering without changing that default path.
- [xbox_textures.c](../port/linux/src/xbox_textures.c) supplies authored mip layout
  and bytes, including a separate CPU extractor for swizzled uncompressed
  volumes that preserves the earlier 2D/cube API. Native caching watches guest
  **virtual** page addresses, protects
  before copying and hashes palettes only for P8. Original compressed blocks
  are uploaded directly. GPU aliases retain native identity and render order.
- [metal_guest_transport.c](../port/linux/src/metal_guest_transport.c) copies
  immutable draw/resource packets through the actual ILP32 host imports and
  validates completion and reply bounds. The host validates a complete batch
  before changing GPU resources or attachments.
- The live frontend queues complete commands in their original order, with a
  4 MiB soft target and the existing 64 MiB hard limit. Draws, texture bytes,
  uniforms and programs are copied immediately. Whole-command reservations
  precede dependent resource preparation; capacity flushes occur between
  complete commands. Present, readback, push-buffer kicks, callbacks, display
  settings and normal exits flush pending work. Each host submission still
  waits synchronously for completion; this is guest batching, not an
  asynchronous host transport.
- [host_metal.mm](../port/macos/host/host_metal.mm) handles native resources,
  draws, channel-masked clears, visibility queries and presentation. The new
  typed copy operation addresses a particular color mip/rectangle; the
  separate volume capability retains XYZ dimensions and authored mip uploads.
  Their validation scopes are recorded below. Partial
  clears preserve unaffected channels/aspects; presentation uses top-left UVs,
  original integer aspect fit, linear scaling, opaque alpha and black bars.
  The settings callback updates the actual layer's vsync property.

New native targets receive deterministic zero initialization of all planes.
That makes undefined fresh attachment contents deterministic; reference
post-draw bytes are never used as initialization. The existing fragment
all-ones `[[sample_mask]]` workaround remains part of the tested Apple sampling
contract. Keep the original 30 Hz simulation independent of render frequency.

## Fixed loading and current experimental launchers on frozen 1fc22

`build/macos-metal/fixed-loading-build-proof/result.json` (`1fc22efa…`)
freezes the successful actual no-GL/ANGLE build with **36 primary and 17 evidence
bindings**. These 53 include both fixed-function helper sources and the actual
linked ILP32 guest object (`49d2aa0e…`); frontend `69c524bc…` and the helper
entry points are checked in the real build graph and guest. The independent
handoff audit rehashes all 53 current files, the original build snapshot and a
second promotion snapshot, including actual host/guest bytes and mode 0755.

`build/metal-poc/fixed-function-ilp32-current-attempt2/result.json`
(`e7ba8fa0…`) passes **288 CPU cases: 49 positive and 239 atomic rejections**,
eight production selection controls and 8,191 small-integer handle lookup
controls. `build/metal-poc/intended-fixed-loading-current-attempt3/independent-closure.json`
(`fe8f0260…`) passes the actual ILP32/API-validation GPU component: 16 production
helper calls, 21 successful submissions, one rejected batch and five saved
byte/version checks. Of 31 analytical readbacks, 28 are exact and three gradient
controls have a predefined maximum one-byte bound. Copies of the actual GPU
gradient bytes are exact. This proves the bounded requested unlit/fullscreen
loading route and copy order within the fixture, not complete original
loading-screen pixels or physical Xbox fixed-function arithmetic. The older
inherited UI-program 54 one-pixel fixture remains history-transport evidence.

`build/macos-metal/map-transition-fixed-loading-attempt1/independent-execution-closure.json`
(`5b62165f…`) checks the actual same-process Blood Gulch→Damnation→Blood Gulch→
Damnation→Blood Gulch run: five phases, four exact load acknowledgements, five
player-ready outputs, 15-second holds and host/guest0 after 240.502354 seconds.
Metal API validation is enabled, with no renderer/API error or failure dump.
All 53 bindings and 17 context sources were checked and frozen. Last logged
frame 7020 records 1,731,566 draws, 222 textures and 82 programs; these are
diagnostics, not workload parity, cache-lifetime or performance measurements.
Root's separate `root-scene-observations.json` (`b6965f08…`) binds five reviewed
world/weapon/HUD images at frames 360/810/1260/1740/2190. The original producer
result (`53329ceb…`) remains globally false. Four bounded switches avoid the old
alias crash, but no strict native stale-content payload/readback oracle or
physical SDK timing proof is added by saved scenes.

`build/macos-metal/fixed-loading-hang-em-high-smoke-attempt1/independent-execution-closure.json`
(`2ecc3391…`) separately verifies a fresh 15.268147-second Hang Em High opening
on this build: host/guest0/API validation, all 53 bindings, no error or dump, and an
independently exact BMP/PNG RGB conversion. Reviewed frame 420 shows the original
gray interior, ramp rails, platform supports, pistol/hands and HUD. Last logged
frame 420 counts 121,757 draws, 129 textures and 49 programs; these are not timing
or performance results. The provisional result (`2aafebf9…`) is preserved before
the explicitly bound image review; reviewed result `907b4271…` closes only this
bounded opening. The run is offline, muted, bot0 with human bindings disabled.

Three launchers for normal human playtesting under
`build/macos-metal/native-metal-playtest-fixed-loading/` now reference the
same frozen 1fc22 host/guest: Blood Gulch, Damnation and Hang Em High. Prepared
`cd52e3e5…`, handoff `5abe0b0a…` and
`handoff-all-three-independent-closure-v2.json` (`877b6ba8…`) bind the separate
execution, root scene review and component proofs. The initial ready=false
record, previous HH-pending metadata and scoped two-map audit remain preserved.
Each script passes `zsh -n`, has mode 0755, uses original map/sound symlinks and
separate fresh saves, and keeps normal configuration `5404c946…` byte-exact.
Keyboard/mouse and audio are enabled; bots, automatic exit, telnet and screenshots
are disabled. These launchers for normal human playtesting have not been executed by the audit.
Their experimental readiness is separate from manual input/audio, full game,
original pixels, performance and a rerun of all 23 on this build, which remain unverified.
Older 125/f69b launchers and proof directories retain their own binaries and
scope. No package/install operation or installed-app byte comparison is claimed.

## Retained failure and current startup result

Blood Gulch startup reaches an original 64×64 texture with five authored mips,
U/V border addressing, ARGB border `0x46000000`, linear min/mag filters, nearest
mip filtering and anisotropy 1. The original native packer rejected this
footprint. The source/map identity report strongly associates it with
`ui\hud\bitmaps\hud_sweeper` and `hud_sweeper_mask`: both are authored BC2
64×64 chains capped at five hardware-visible levels. The actual failed log did
not retain a runtime tag pointer, so that distinction remains explicit.

The optional cap2048/opcode19 draw samples the same original texture twice
with identical descriptors, UVs and LOD bias: transparent-black and opaque-black
borders. The shader retains original RGB and reconstructs authored border
alpha before sign conversion, alpha kill and combiners. This is limited to
normalized mipmapped 2D black-RGB borders, linear min/mag, nearest mip and
anisotropy1; other 2D colored-border states remain unsupported. The two original
radar blend passes and authored mips stay intact.

The strict ideal double/half-up alpha fixture remains failed: 246 bytes differ
by one at half-byte rounding ties. Raw GPU float controls isolate the arithmetic:
8,450 reconstructed samples match float32 FMA of independently observed B/O
inputs, 4,225 safe/Fast pairs are bit identical and all 3,290 interior samples
leave the original alpha unchanged. Thirteen invalid later draws reject
atomically. This explains the ideal oracle discrepancy without establishing
retail pixel parity; original Xbox precision stays open. The retained diagnostic
is `build/metal-poc/alpha-border-validation-final/diagnostic-closure.json`.

The retained failure is
`build/macos-metal/live-game-bloodgulch-attempt3/result.json`; the new source-bound
startup pass is `build/macos-metal/live-game-bloodgulch-alpha-attempt4/result.json`.
An isolated experimental launcher is under `build/macos-metal/native-playtest/`,
using frozen tested binaries and separate saves. Its five-second muted smoke
exited zero. Interactive controls/audio and broader content remain unverified.
No native app was packaged or installed.

The newer batched launcher is
`build/macos-metal/native-batched-playtest/Launch Native Metal Batched.command`.
It uses the frozen batched build, separate save/data roots, ordinary input
bindings and the copied audio setting. Its five-second muted startup exits zero
and restores the normal configuration byte for byte. The older launcher and
installed app are preserved; interactive input/audio and the retained live
texture-layout failure still need validation.

The batched frontend's controlled 15-second startup is recorded in
`build/macos-metal/live-game-bloodgulch-batched-attempt2/result.json`: host and
guest exit zero after 93,780 original draws by frame 360, with Metal API
validation and a 2560×1920 windowed drawable for the 640×480 game. A controlled
run of the frozen earlier build also exits zero. Static base/world placement
looks unchanged; differing weapon animation phases are not a pixel-parity test.
These runs disable incidental keyboard/mouse actions for repeatability.

The separately prepared `build/macos-metal/live-batch-benchmark-current/`
retains twelve 45-second A/B/B/A runs with screenshots/API validation off,
fresh save clones, original assets, the same 640×480 game and 2560×1920 drawable,
and no input actions. All twelve runs exit zero and reach the requested
frame 120–600 measurements. The six earlier-build runs have median19.355 FPS
(range18.766–20.422); the six batched runs have median30.002 FPS
(range30.002–30.004). This is observed frame-loop throughput under original
30 FPS pacing, not maximum Metal capacity or a closed performance gate.

The benchmark result remains **failed for exact workload parity**. The BACK
state prompt disappears at 450 simulation ticks, so different render rates
remove its character/icon draws at different frame numbers; smaller draw-count
differences also remain. The source is `main.c:2245–2254`/`2487` for the original
vblank throttle and `game_engine.c:7722–7729` for prompt timing. A future
comparison must predeclare a steady window and verify pose/state/workload;
do not retrospectively relax the recorded failed gate.

The preceding uncontrolled run is retained separately at
`build/macos-metal/live-game-bloodgulch-batched-attempt1/result.json`: it stops
at frame 70 on an unsupported original texture layout. Its metadata did not
identify the asset or exact unsupported format, so neither batching nor an
asset/shader cause is established. Keep this live-content failure open.

## Rendered mip copies and authored volumes

Cap4096/opcode20 `COPY_SUBRESOURCE` copies an explicit source mip/rectangle into
an explicit destination mip/rectangle. Its 72-byte record preserves ABI version1
and earlier records. It accepts matching RGBA8/BGRA8 color2D resources with
distinct identities, requires initialized source content and initializes a
destination level only on a full-level copy. Partial writes require initialized
destination content. Copy versions advance in order; a bad later copy rejects
the entire packet before an earlier command changes attachments.

`build/metal-poc/copy-subresource-current-attempt2/independent-closure.json`
records 254 byte-exact GPU readbacks, 25 invalid-later-copy guards and 125 saved
byte/version checks through the real ILP32 transport, with Metal API validation
and observed host/guest exit0. Four **synthetic rendered** 128/64/32/16 levels
are copied and sampled independently. They are not an original water capture.
The proof freezes the copy-only sources/binaries; subsequent volume edits do
not change that historical result. The multi-mip destination's version is not
directly exposed by the existing target-only readback API.

[metal_mip_composite.c](../port/linux/src/metal_mip_composite.c) now plans the
live frontend's copies from the latest rendered target at each original
physical mip address. The cache key retains Data, width, height and requested
level count; original physical level offsets determine aliases. Copies are
queued before the sampling draw. Missing levels, incompatible latest aliases
and ambiguous equal-time aliases fail explicitly. No CPU attachment bytes or
generated mips fill missing levels. Its CPU-only closure is
`build/metal-poc/rendered-mip-planner-validation/closure.json`: 517 actual ILP32
cases, plus a separate maximum-chain/alias-count boundary check. The original
Damnation `sky\dusk\shaders\water dusk` requests four rendered ripple levels.
The historical source-bound run at
`build/macos-metal/live-volume-water/damnation/result.json` exits host/guest0
after 15.34 seconds, frame 420 and 73,014 original draws with API validation.
Its log records the actual 128×128 four-level rendered composite. This proves
bounded execution with that earlier frozen build, not native water pixel parity
or a passing run of later sources. Water parity remains open.

The separate all-linear build run at
`build/macos-metal/live-volume-linear/damnation/result.json` also exits
host/guest0 with API validation: 15.326 seconds, frame 420 and 74,044 original
draws. Its source/binary snapshot is `live-volume-linear-build-proof/snapshot`.
The earlier 73,014-draw result remains historical; neither is a matched water
pixel comparison or a performance benchmark.

A later failure-only bot run captured stage2 Data `0x0726c000`, Format
`0x55560139`, modes `0x00018861`: the original 32³ distance-attenuation volume
with six authored 32³→1³ levels. The 37,449-byte runtime blob exactly matches
Blood Gulch bitmap `0xe6f60582`, `rasterizer\distance attenuation`, SHA256
`0f23edd4a08b58514e0df7e67691da723b0095f74c0d94643747da7491454196`.
`build/metal-poc/volume-copy-validation-final/assets.json` binds the map,
decompressed cache offset, allocation padding and runtime dump. Original
format1 is AL8: the whole byte supplies every RGBA channel, not nibble expansion.
The independent XYZ Morton oracle and production CPU extractor match all six
levels; `volume-copy-validation-final/closure.json` records 244 actual ILP32
comparisons and `native-suite.json` records seven native tests with ASan/UBSan.
These are CPU extraction proofs, not GPU sampling or lighting parity.

Cap8192/texture type3 reuses the existing 48-byte CREATE_EX and 72-byte UPLOAD_EX
records for normalized, uncompressed RGBA8/BGRA8 shader-read volumes. XYZ bounds,
mip dimensions, row/image pitches and exact payload size are checked before
execution. Every authored level must be initialized before sampling. Volume
render targets, compression, copies and mip generation remain unsupported.
The original point-filter implementation is frozen at
`build/metal-poc/volume-implementation-current/implementation.json`; the
all-linear extension is frozen separately at
`volume-linear-implementation-current/implementation.json`.
`native-draw-state-volume-linear-ilp32/result.json` passes 133 CPU packing cases,
including all 126 original draw outputs unchanged.

The original diffuse-light pass binds distance attenuation at stage2
(`rasterizer_xbox_environment.c:1353–1387`). Captured U/V/W use BORDER with
literal RGBA0, point min/mip, linear mag and anisotropy1. The second original
lighting path at `rasterizer_xbox_environment.c:1876–1885` and the retained
`live-volume-water/bloodgulch/launch.log` use linear min/mag/mip. Both exact
footprints now use real hardware border addressing on the requested XYZ axes;
mixed min/mip pairs and anisotropy remain rejected. This literal-black contract
does not authorize arbitrary colors; the separate cap16384 path below does.
No 2D shader approximation or fallback is applied. The installed ANGLE port
falls back to edge for 3D borders; authored lower mips have
nonzero boundary voxels, so an ANGLE interior comparison cannot establish this
original border behavior. That earlier literal-black source/proof group did
not validate actual firing, and its old-host/new-guest diagnostic failure is
not a pass. Later bounded scripted firing is recorded separately below;
manual playtesting and broader full-game rendering remain unverified.

`build/metal-poc/volume-all-linear-gpu-current-attempt1/independent-closure.json`
now passes 770 exact raw GPU readbacks, 29 atomic later-failure guards and 145
saved byte/version checks, with host/guest0 and API validation. It samples all
authored voxels under both footprints, tests asymmetric XYZ/channel values and
padded partial subvolume retention, and includes 273 rational XYZ-border/mip
blend cases and 27 production-generated PROJECT3D q/border cases. The synthetic
vertex/key inputs test the pixel translator's resource interface; they do not
establish an actual original lighting draw's output parity. Volume versions
remain unavailable through the target-only readback API.

The preceding near-half nearest-LOD ideal gate remains **false** at
`build/metal-poc/volume-gpu-current-attempt1/failure-closure.json`. Requests
0.51/1.51/4.51 disagreed with the ideal selection oracle. Later .25/.75 controls
pass independently; neither tolerances nor that historical failed result were
changed. Full nearest-LOD precision remains open.

The earlier literal-black volume source group is bound by that GPU closure and
`build/metal-poc/host-frame-volume-linear-current/independent-closure.json`:
backend `c83427b4`, ABI `6c457f4c`, encoder `6407b120`, transport `3118c29a`.
The fresh original frame 420 replay again matches all 378 color/depth/stencil/
query checkpoint bytes, versions and sequences through 126 draws and 131
submissions, with explicit API validation and host/guest0. It retains the
original captured inputs; query timing, presentation and full gameplay stay open.

## Explicit integer-D24 depth replacement

The scripted Blood Gulch run retained at
`build/macos-metal/live-volume-linear/bloodgulch/result.json` fails at frame 20
on an unsupported original program. A **separate** failure-only diagnostic at
`build/macos-metal/live-depth-diagnostic/` captures a frame 89 pixel key, SHA256
`f13524b388b542bc2c4d328e9df265e6acd4265df92dd2916b0d89a52067d0aa`.
Its modes 1/1/17/10 are PROJECT2D/PROJECT2D/DOT_PRODUCT/DOT_ZW, and its paired
35-instruction vertex words exactly match original program 66. The diagnostic
does not establish that its draw/time equals the earlier frame 20 failure.

The authoritative original float-Z byte is 0, presentation requests D24S8,
and active surface Format 0x00002e21 is LIN_D24S8. Viewport MinZ/MaxZ are 0/1,
scale-Z is 16777215 and offset-Z is 0. All 192 original constants and the raw
metadata are hashed in `native-draw-state-d24-ilp32-final/closure.json`.
Original zsprite source selects raw 16777215 or 1e30 using that float-Z flag;
the native attachment's storage format alone cannot establish these units.

The CPU packer now appends an explicit default-zero depth contract. Only
DOT_ZW 0x0a enables RAW_D24 after validating the original request/current format,
float-Z 0, an attached depth target, finite viewport bounds and the exact
original D24 viewport scale/offset. It packs scale 1/16777215 and the near/far
bounds into the existing 608-byte pixel ABI. Other draws retain zero depth fields
and all 126 original outputs unchanged. DEPENDENT_AR 0x0f is no longer incorrectly
rejected as DOT_ZW. The program cache includes the depth contract, and the
extended emitter retains safe fragment compilation for its finite guards.

`build/metal-poc/native-draw-state-d24-ilp32-final/closure.json` passes 21 native
tests and 164 actual ILP32 CPU cases: 136 positives and 28 atomic rejections.
These include the captured key/constants/depth metadata, bounded viewport,
default dependent AR, F24/F16/D16 and missing-target/opt-out/malformed-flag
rejections, and wrong raw-depth scale/offset. Unrelated render arrays/samplers
in the depth CPU fixture are explicit fixture inputs, not a complete captured
original zsprite draw.

`build/metal-poc/dot-zw-raw-d24-current-attempt4/independent-closure.json`
passes 284 exact raw GPU readbacks across 46 controlled depth cases, 20 typed
contract cases (17 reject/3 accept), four atomic backend rejections and 96 saved
byte/version checks through 67 successful submissions. Safe fragment contract 0
and synthetic inputs independently test ratio/range/depth-write behavior;
depth uses stage 1 texture RGB. The actual f135 key compiles, but this fixture
does not execute that key with original VS66, geometry or resources. Physical
Xbox D24 quantization and original zsprite pixel parity remain open. The legacy
GLSL fallback omits depth replacement and cannot be this depth oracle.

The failed attempt 3 remains preserved in
`dot-zw-raw-d24-current-attempt3/fixture-binding-failure.json`: its synthetic
vertex fixture bound buffer 1 while the encoder requires buffer 0. The optional
stage 0 expansion at `dot-zw-raw-d24-current-expanded-attempt1/not-executed.json`
is prepared but unexecuted; it does not widen the passing stage 1 proof.

`build/macos-metal/live-volume-depth-observed-build-proof/result.json` records
a successful complete native guest/host build with no GL/ANGLE linkage or
imports, frozen in its own `snapshot/`. Its subsequent scripted runs are retained
as failures at `live-volume-depth-observed/bloodgulch/result.json` (frame 17)
and `damnation/result.json` (frame 65). Both stop on stage 1 PROJECT3D with a
32³/six-mip volume, BORDER on XYZ and authored ARGB `0x05050505`, all-linear
filtering and anisotropy1. Neither log has a D24 success line. These results
remain distinct from the earlier frame 20 failure and frame 89 diagnostic;
component depth proof does not make a failed live run pass.

## Authored RGBA volume border companion

The additive cap16384/opcode21 contract retains the 416-byte legacy DRAW prefix
and appends volume and alpha masks in a 424-byte record. Masks are bounded to
four stages and disjoint. Existing DRAW and opcode19 keep their semantics.
Only normalized RGBA8/BGRA8 texture3D with more than one authored mip and the
two already tested anisotropy1 footprints is admitted. CPU extraction preserves
the original ARGB border as normalized RGBA in the unchanged 608-byte pixel ABI.

For each selected volume stage, the backend creates transparent-black and
opaque-white samplers from one descriptor, changing only border color. Both
sample the same original texture with identical XYZ coordinates, derivatives,
LOD clamps and filtering. The generated shader reconstructs
`B + authoredBorderRGBA * (W - B)` before signed mappings, alpha kill and the
original combiners. Auxiliary samplers occupy 4+stage, and reflection must
match the exact union of volume and existing 2D alpha masks. Unknown masks,
wrong resource types, missing companions, nonfinite or out-of-range uniform
colors and unverified footprints reject before earlier packet commands execute.

`build/metal-poc/volume-colored-border-source-ready/closure.json` retains 24
native CPU tests and 183 actual ILP32 cases: 145 positives and 38 atomic
rejections, with all 126 default outputs unchanged. The appended input/output
fields preserve the earlier layout prefix. The separate emitter closure at
`volume-border-emitter-cpu-proof/closure.json` passes 22 CPU tests and keeps
all 126 baseline MSL/GLSL outputs unchanged. Guard-page checks verify the v1
two-word, v2 three-word and v3 four-word options read limits.

`build/metal-poc/volume-colour-gpu-current-attempt4/independent-closure.json`
(SHA256 `1034b9f2…`) passes 1,050 byte-exact readbacks, 20 atomic guards and
100 saved byte/version checks through 803 successful submissions, with seven
CPU tests and observed host/guest0/API validation. Synthetic generated PROJECT3D
stage 0/1/2, alpha kill and both footprints pass. Six specified RGBA5 half-up
edge controls also pass. This does not close the separately retained .51
nearest-LOD failure, physical Xbox precision, or an original lighting draw.
Expected-after oracle bytes never enter texture uploads. Attempts 1–3 remain
preserved: initial sandbox GPU unavailability, then fixture query-version and
negative-guard ordering errors; they were not rewritten as passing runs.

The executed source group is frozen in that closure: backend `ddf016b9`, ABI
`abc7dd4b`, encoder `da54c211`, transport `da36338d`, pixel emitter `f233c9e4`
and MSL ABI `79046983`. The complete native build at
`build/macos-metal/live-volume-colour-build-proof/result.json` (SHA256
`f69b523b…`) retains 34 primary and 16 evidence bindings with no GL/ANGLE
linkage/imports. The later live results below bind execution to this frozen
build; component proof alone does not close those live gates.

The fresh regression at
`build/metal-poc/host-frame-volume-colored-current-attempt2/independent-closure.json`
passes all 378 original frame 420 checkpoint bytes, wire versions and submission
sequences through 126 draws and 131 submissions, with API validation and observed
host/guest0. The initial initialization failure remains preserved separately.
This captured-state replay binds the CPU packer as integration provenance but
does not execute it. CPU query availability/timing, live presentation and full
gameplay remain separate gates.

## Historical scripted gameplay and experimental handoff

`build/macos-metal/live-volume-colour/bloodgulch/result.json` (SHA256
`69f6b3c4…`) passes a 30.5901-second scripted movement/firing run with observed
host/guest0 and API validation. Its last statistics at frame 840 record 220,223
original draws, 158 textures and 82 programs. The final frame 870 capture was
visually inspected for the world/red base, bullet decals, plasma gun and HUD.
`damnation/result.json` (SHA256 `fa0b08d9…`) separately passes 30.2540 seconds,
with frame 840 statistics of 161,216 draws, 138 textures and 93 programs;
its frame 870 capture shows world, weapon, bullet decals and HUD. Neither run
reports Metal API validation errors. Draw counters are diagnostics, not a timed
performance comparison.

Both logs record the actual colored-volume path at modes `0x18c41`, volume mask
2, and successful original D24 programs at modes `0x54421`, request 42/current
surface 0x2e21, float-Z 0, raw scale 16777215/offset 0 and safe fragment compiler
0. Damnation also logs the original 128×128 four-level rendered composite.
These runs exercise the previously blocked paths; they do not establish
matched original lighting, zsprite or water pixels, or physical Xbox precision.
The older failed runs and component-scope limitations remain intact.

The tests use scripted bot slot 0, muted audio and disabled human bindings.
Separate launchers under `build/macos-metal/native-metal-gameplay-playtest/`
named `Launch Native Metal Blood Gulch.command` and
`Launch Native Metal Damnation.command` select this frozen build with isolated
saves, normal input/audio configuration and no scripted input or automatic
exit. `prepared.json` marks them ready for
experimental handoff and binds the byte-exact original configuration. These
launchers reference isolated files; no installation step forms part of this
handoff. Manual controls/audio, live query timing,
performance, broader content and full-game fidelity remain unverified.

## Stock openings on frozen 125be740

`build/macos-metal/stock-content-original-state-23-current/result.json`
(SHA256 `ca35aced…`) binds **23 successful fresh starts** to corrected build
`125be740…`: 13 original multiplayer maps for at least 15 seconds and ten
original Normal campaign openings for at least 30 seconds. All actual host and
guest exits are zero, Metal API validation is enabled, and no renderer or
validation error is logged. The build retains 50 frozen/current bindings and
no GL/ANGLE linkage or guest imports. These are isolated startup windows,
not a completed campaign or map-transition result.

The multiplayer independent closure at
`build/macos-metal/stock-mp-original-state-attempt1/independent-closure.json`
(SHA256 `03ab86ed…`) checks 320 run artifact hashes and inspected lossless
world/first-person/HUD images. Last logged counters total 1,207,033 draws;
Sidewinder logs frame 300/captures330 and Boarding Action logs240/captures270.
The other cases log/capture420. The original bot0 movement/firing input,
muted audio and disabled human bindings remain explicit. Counters do not
establish comparable workload or performance.

The campaign independent closure at
`build/macos-metal/campaign-original-state-attempt1/independent-closure.json`
(SHA256 `89858868…`) checks 350 run artifact hashes. The three corrected cases
`c40/d20/d40` and seven remaining openings all pass, using fresh saves, literal
Normal HS init commands, empty scripted input, no cinematic skip and original
assets. Reviewed cinematics provide scene evidence; `c10` shows first-person
world/HUD. Last logged counters total 1,821,977 draws, without a benchmark claim.
For `a30`, final frame 540 is white within the letterbox and its
`image.visually_observed` remains false. Explicit same-run frame 420 cockpit
evidence supplies the positive scene review; its original BMP/PNG identity,
selection source and metadata correction are bound separately. The final white
capture and provisional records remain preserved.

Both closures independently verify execution/prepared/plan identities,
commands, validation environment, source/config/init hashes, original cache
scenario type, fresh-save markers and elapsed windows. The unchanged source
producers retain 16 passing CPU guards. Actual GPU completion sidecars retain
the original driver exits; later image review does not substitute completion.

The current backend regression at
`build/metal-poc/host-frame-original-state-current/independent-closure.json`
(SHA256 `b3856ba6…`) repeats all 378 original frame 420 attachment/query byte,
version and sequence checks through 126 draws/131 submissions with actual
ILP32 host/guest0 and API validation. This captured-state fixture binds the
state packer and live frontend as provenance but executes neither; the frame
has finite constants and equal attachments. Separately,
`build/metal-poc/unequal-attachment-current-attempt1/independent-closure.json`
(SHA256 `82d0e04e…`) passes 45 analytical GPU readbacks and seven atomic guards,
including preservation outside the smaller shared attachment footprint.
Its synthetic draw does not establish original `c40` pixel parity. The
193-case ILP32 raw-bank proof preserves unused original constant bits while
keeping native state/viewport validation. These scopes remain distinct.

Three experimental launchers under
`build/macos-metal/native-metal-playtest-original-state/` select Blood Gulch,
Damnation or Hang Em High using frozen build 125 and separate fresh saves.
Their independent CPU closure (SHA256 `cf74b4b1…`) verifies all 50 build
bindings, original map/sound links, executable permissions, actual `zsh -n`
success, exact host/guest commands and the byte-exact normal input/audio
configuration `5404c946…`. There is no bot, screenshot loop or automatic exit.
The original audit's ready=false prepared record remains byte-exact in
`prepared-before-handoff.json` (`e8a6c395…`). The subsequent ready=true
promotion (`handoff-ready.json`, `34f79d8c…`) is independently checked in
`handoff-promotion-independent-closure.json` (`a3c32119…`): all 50 frozen/current
bindings match, and launcher commands, configuration and build identities
remain unchanged. The three launchers are ready for experimental initial-map
use. Manual controls/audio remain untested. No installation or package
operation forms part of this evidence, and no installed-app byte comparison
is claimed.

`build/macos-metal/map-transition-125-attempt2/independent-closure.json`
(`d0a50e44…`) retains a separate failed same-process test: the first Blood Gulch
to Damnation change exits host/guest-5 at frame 464, with **zero successful map
changes**. The failing loading-screen draw has all four texture slots aliased
to its active color target. Original progress rendering queries current index0
and historical index-1; that frozen native adapter returns the same storage
for both.
The separately bound `indexed-buffer-source-contract.json` (`c71e3535…`)
establishes that those contents must be distinct for loading blur. This
historical failure remains unchanged after the later indexed-history proofs
below. The existing build 125 launchers still require separate processes;
their ready status does not silently move to a newer build.

## Indexed history on frozen 4b240709

`build/macos-metal/indexed-history-build-proof/result.json` (`4b240709…`)
freezes the successful no-GL/ANGLE build with 50 bindings and frontend
`3dfde625…`. Current index0 and history index-1 have distinct, stable storage.
Every queued Present copies current color into history before presentation;
current clears and non-Present callbacks do not advance history. It uses
existing typed copy/presentation commands without a backend or wire change.
Later unlit/immediate source edits must carry their own proof and cannot
retroactively widen this frozen result.

`build/metal-poc/backbuffer-history-cpu-validation/closure.json`
(`a6b55440…`) passes seven ASan/UBSan CPU component tests, plus the actual ILP32
syntax check. They exercise selected-index/refcount behavior, stable aliases,
Present ordering, first-use history, guards and resize preservation through
extracted actual C functions with mocked GPU effects. The production guest
defines `HALO_ANDROID` and excludes that dynamic resize branch. CPU resize
controls do not establish resizing through the actual game or physical Xbox
swap ordering.

`build/metal-poc/backbuffer-history-gpu-prepared-attempt1/independent-closure.json`
(`4c29a7da…`) passes 26 exact byte/version/sequence readbacks through ten
successful submissions, one late-invalid-command atomic guard and five saved
byte/version checks, with actual ILP32 host/guest0 and API validation. A
separate raw-packet CPU interpreter checks allocation, clears, integer copies,
history retention and bounded resize copies; expected-after bytes are never
GPU uploads. The captured inherited program 54 covers only pixel(0,0). Its
one-pixel control and separate point-center controls verify history transport
and ordering, not the intended fullscreen loading effect.

`source-route-clarification.json` (`5afb22bd…`) in that GPU folder records why:
original progress rendering requests `SetVertexShader(0)`, but both inherited
GL and frozen native setters ignore the null handle and retain UI program 54.
The original requested unlit vertex route and fullscreen four-tap blur are
unverified in that historical snapshot. The later 1fc22 CPU/GPU evidence above
checks the bounded intended route without widening this one-pixel proof.

The actual same-process run at
`build/macos-metal/map-transition-indexed-history-attempt1/independent-execution-closure.json`
(`4bedd111…`) completes Blood Gulch→Damnation→Blood Gulch→Damnation→Blood Gulch:
five phases, four exact HS load acknowledgements, five player-ready outputs,
15-second holds and host/guest0 after 240.507699 seconds. Metal API validation
is enabled with no renderer/API error or failure dump. All 50 frozen/current
bindings and 17 context sources were independently checked and frozen before
later edits. Last logged frame 7020 records 1,730,571 draws. Resource/program
counts plateau at 222/82 from frame 540; this is not eviction, exhaustion,
long-term lifetime or performance proof.

The separate `root-scene-observations.json` (`8cbb1a56…`) binds root's manual
review of recognizable map world, first-person weapon and HUD at frames
360/810/1260/1710/2160, with a bound contact sheet. Those hashes match the
audited original BMPs. The producer `result.json` (`e7c5d8e3…`) remains unchanged
with global passed and saved-image-inspection gates false; the scene sidecar
does not rewrite it. The corrected history route's safe-attachment-alias crash
gate is verified for these four changes. Native texture payload/readbacks for
strict stale-content checks are absent, so that gate, loading pixel parity,
SDK physical timing, full game, performance and actual-game resizing stay
false. No newer experimental launcher ready status follows from this run.

## Historical stock content coverage on frozen f69b

`build/macos-metal/stock-mp-content-f69b-attempt1/independent-closure.json`
(SHA256 `cb65d30f…`) passes all 13 source-listed original multiplayer scenarios:
`beavercreek`, `sidewinder`, `damnation`, `ratrace`, `prisoner`, `hangemhigh`,
`chillout`, `carousel`, `boardingaction`, `bloodgulch`, `wizard`, `putput` and
`longest`. Each fresh 15-second bot0 movement/firing run exits
host/guest0 with Metal API validation, no renderer/API error, and an inspected
lossless 640×480 world/first-person/HUD image. The closure checks all 50
frozen/current build bindings at that source window and 281 run artifact
descriptors; eight CPU guards pass. Last logged checkpoints total 1,225,896
original draws. Boarding Action logs frame 240 and captures frame 270; the others
log and capture frame 420. These counters do not define a benchmark or final
frame workload. Campaign, UI and community caches were excluded from this run.

The separate
`build/macos-metal/stock-campaign-content-f69b-attempt1/independent-closure.json`
(SHA256 `41c378df…`) records **seven passes and three failures** across all ten
original campaign scenarios. Each uses fresh saves and the original literal HS
commands `game_difficulty_set normal` and `map_name levels\<name>\<name>`.
No Slayer variant, cheat, cinematic skip or scripted input is supplied. The
30-second passes are `a10`, `a30`, `a50`, `b30`, `b40`, `c10` and `c20`.
Saved scene review identifies opening cinematics where appropriate; `c10`
shows the swamp world, weapon and HUD. Cinematic images do not establish
first-person gameplay or completed missions.

| Frozen f69b campaign failure | Retained execution evidence | Saved image scope |
| --- | --- | --- |
| `c40` — Two Betrayals | Host -5; submission status -1 at frame 41, command2, before the first frame 60 statistics | Frame30 is black; no positive world evidence |
| `d20` — Keyes | Host -5; original state packing rejects nonfinite vertex uniform or viewport at frame 48 | Frame30 is black; no positive world evidence |
| `d40` — The Maw | Host -5; same state rejection at frame 503, after frame 480 records 62,442 draws | Frame480 shows the ship exterior/crash-site cinematic before failure; the run remains failed |

The per-map `result.json`, logs and failed-scene observations preserve these
failures. Existing diagnostics produced no binary shader/resource dump for
these rejection paths, so the f69b artifacts alone do not identify the exact
offending constant, program or resource. The independent closure checks all ten execution
identities, plan/config hashes, environment, fresh-save markers, successful
Normal HS init commands and elapsed windows. Seven positive runs each cover
at least 30 seconds; eight campaign CPU guards pass. The aggregate remains
false. Later failure-only diagnostics and rebuilds must bind their own sources;
they do not rewrite this frozen f69b result.

The separate failure-only build `4a839107…` and
`build/macos-metal/campaign-failure-diagnostic-attempt2/independent-closure.json`
(SHA256 `58faf6f7…`) retain three further host-5 failures: `c40` at frame 40,
`d20` at 73 and `d40` at 510. The audit verifies all 50 frozen bindings, 179
artifact hashes, actual commands/init/environment and observed exits. The
driver's recorded prepared hash matches the actual file; its missing prelaunch
check is recorded. Six later source/build changes are historical drift, not
changes to these inputs. Attempt1's preparation rejection remains retained.

`build/metal-poc/c40-attachment-size-audit/report.json` identifies the original
mirror pass's 320×240 secondary color target paired with primary depth. The
packet records depth ref2; its 640×480 extent is source-inferred, not a captured
resource-table value. Matching-size validation rejects this valid pairing.
The independent nonfinite capture audit identifies VS9's sole nonfinite bank
component in `d20`/`d40`: `c[23].w`, original `c[-73].w`, raw `ffffffff`.
It is distant-light padding; the actual DP3 consumes xyz. Relative addressing
cannot reach that component through the original typed model route, although
expanded streams/declaration were not captured. This is source semantics,
not a successful rerun or physical Xbox comparison.

Corrected build `125be740…` subsequently passes the CPU, GPU and fresh opening
checks described above. The historical seven-of-ten aggregate and all
failure-only diagnostics remain unchanged; a later positive result does not
rewrite their source windows. Original campaign draw pixel parity remains
unverified.

Both inventories derive scenario identity from original source lists plus
Xbox v5 cache headers and `scnr` type. Runs use original read-only map/sound
links, isolated per-map data/saves, muted audio, offline networking, disabled
human bindings and a 2560×1920 windowed drawable for the 640×480 game. No
installed app was referenced, compared, packaged or replaced. Longer gameplay,
transitions, vehicles, split-screen and original pixel parity remain open.

## Shader and stock bitmap metadata scope

`build/metal-poc/source-pixel-mode-audit/inventory.json` retains 64 checked-in
texture-mode assignments with source hashes. Reviewed builders emit modes
0/1/2/3/9/10/11/12/17, including bumped reflection, water, camouflage and
integer-D24 zsprites. No original BRDF8, constant-eye18, HILO dot mapping4–7 or
explicit COLORSIGN setter was found. This is a source inventory, not proof
of every retail draw or externally supplied D3D definition; per-draw resources,
units, arithmetic and pixel parity still require evidence.

The CPU-only `stock-bitmap-metadata-audit.json` in that folder (SHA256
`48289a51…`) scans 14,815 bitmap records across all 24 original local caches:
13 multiplayer, ten campaign and UI. It finds zero BC2/BC3 cubes and zero
V16U16 flags. All 572 cube records use currently admitted formats. L16 has no
authored bitmap/cache-format mapping in the reviewed original source. Counts
include repeated assets across caches; no texture pixels were exported and
this audit ran no GPU work. BC2/BC3 cube admission and shared V16U16/L16
low-byte precision remain general resource gaps, without an affected stock
asset established by this scan. Do not widen native mode/format guards from
enum availability alone; retain actual failure evidence first.

## Remaining live gates

1. Close colored-border precision against an appropriate original reference
   and broaden coverage only with explicit contracts. The narrow radar path
   passes startup but its ideal-byte oracle still fails at ties. Do not silently
   remap other authored colors to transparent black or edge. The new volume
   companion's six specified RGBA5 half-up controls pass independently; they
   do not widen the older 2D radar or nearest-LOD precision gates.
2. Validate the integrated rendered-mip planner/copies on original water,
   including all four Damnation ripple levels and their sampling draw. The
   typed copy GPU fixture is exact and one original Damnation startup executes
   all four levels. Matched-camera water pixels remain unverified. Missing
   rendered levels remain rejected; no generated suffix is implemented.
3. Match cached visibility polling and slot reuse. Native submission/readback
   currently completes synchronously; a correct raw Boolean result does not
   establish the original CPU availability or lens-flare timing.
4. Compare complete original loading-screen pixels after the bounded unlit/
   immediate component proof, then capture native texture payloads/readbacks
   across transitions for strict stale-content evidence. Four alternating
   changes now avoid the old alias crash; the build125 failure remains historical. The 13 multiplayer
   starts, ten campaign openings and four changes do not cover complete missions
   or general transitions. Exercise interactive gameplay and
   compare matched camera/settings and ordered attachment history, then extend
   campaign effects, transitions,
   actors, vehicles, first-person weapons, HUD, decals and split screen.
   The user's roof/downward base-decal clipping remains unresolved.
   The retained 30,714-sample CPU roof audit at
   `build/metal-poc-0.6/roof-geometric-occlusion-audit/final-audit.json` finds no
   geometric occlusion in its tested interior samples, but does not reproduce
   the user's exact camera/GPU coverage. The focused 16 GPU closure at
   `build/metal-poc-0.6/roof-depth-focused-prepared-attempt3/independent-audit/closure-v2.json`
   (`bafdabfb…`) measures a small edge loss at one specified synthetic roof pose:
   20 nonzero RGB pixels at 640×480 and six at 1280×720. Copied opaque depth and
   fragment-fetched depth are exact; actual raster depth matches stored glyph
   depth, and LEQUAL query counts agree with float32 comparisons. Original
   static-shader and invariant variants are byte-identical. This proves native
   rejection at those fragments, not original ANGLE/Xbox correctness or the
   user's exact reproduction. The earlier 70 recorded-pose controls with zero
   RGB loss stay separate. No geometry/depth-bias/shader fix is established.
   Scripted movement/firing now exercises the distance-attenuation resource;
   validate manual firing and compare original lighting/zsprite draws. The
   earlier unidentified texture failure remains a separate retained diagnostic.
5. Validate window/Retina/fullscreen changes and actual frame pacing. The layer
   vsync property and scaling fixture are proven, not refresh timing or latency.
6. Add bounded cache lifetime and asynchronous submission after correctness;
   measure full-game CPU/GPU time, memory, upload traffic and input age before
   reporting a performance improvement.

Volume resource/sampler fixtures and two bounded scripted firing runs pass;
original lighting draw parity and manual firing remain unverified. Rendered
water executes in the bounded Damnation runs, but its native pixel parity
remains unverified. Near-half nearest-LOD selection
and roof/downward glyph clipping remain unresolved.
Compressed/render-target volumes, BC2/BC3 cubes, missing rendered-mip generation,
floating/unknown DOT_ZW depth units, multisample/coverage-alpha paths and native
high-resolution HUD uploads remain explicitly unsupported. Integer-D24 packing
and controlled depth fixtures pass; actual zsprite draw parity remains open. Physical Xbox
D24/F24 and sampling precision remain a separate fidelity gate from matching
the current ANGLE port.

## Validation retained

- `build/macos-metal/fixed-loading-build-proof/result.json`: current frozen 1fc22
  actual no-GL/ANGLE build with 53 bindings, including helper sources and linked
  guest object. Fixed CPU `e7ba8fa0…` and GPU `fe8f0260…` controls have the
  explicit exact/gradient scopes above.
- `build/macos-metal/map-transition-fixed-loading-attempt1/independent-execution-closure.json`:
  five phases/four actual changes, host/guest0/API validation, 53 bindings and
  separately reviewed scenes; original producer/global passed=false retained.
- `build/macos-metal/fixed-loading-hang-em-high-smoke-attempt1/independent-execution-closure.json`:
  fresh same-build 15-second opening with reviewed lossless frame 420; no
  claim that all 23 were rerun on this build, or manual-play extension.
- `build/macos-metal/native-metal-playtest-fixed-loading/handoff-all-three-independent-closure-v2.json`:
  three current experimental launchers, 53 current/frozen/snapshot checks,
  normal configuration and original symlinks; previous pending metadata kept.
- `build/macos-metal/stock-content-original-state-23-current/result.json`:
  current frozen 125 bounded coverage passes 13 multiplayer starts and ten
  campaign openings; independent closures retain all 50 build bindings,
  320/350 run artifact checks, actual exits and 16 CPU guards. A30's selected
  frame 420 scene is explicitly separate from its final white frame 540.
- `build/metal-poc/host-frame-original-state-current/independent-closure.json`:
  current backend repeats all 378 byte/version/sequence checks; captured-state
  scope, CPU query timing and presentation gates remain explicit.
- `build/metal-poc/unequal-attachment-current-attempt1/independent-closure.json`:
  45 analytical GPU readbacks, seven atomic guards and preserved outside
  depth/stencil content; synthetic scope, no original mirror pixel claim.
- `build/macos-metal/native-metal-playtest-original-state/independent-closure.json`:
  three frozen 125 initial-map launchers pass CPU configuration/path/linkage
  audit. `handoff-promotion-independent-closure.json` verifies the ready
  promotion while retaining the exact prior prepared record. Manual input/audio
  remain untested; the separate map-transition proof retains zero switches.
- `build/macos-metal/map-transition-125-attempt2/independent-closure.json`:
  historical host/guest-5 at the first Blood Gulch to Damnation loading draw;
  original failed result and source-backed index0/-1 alias diagnosis retained.
- `build/metal-poc/backbuffer-history-cpu-validation/closure.json` and
  `backbuffer-history-gpu-prepared-attempt1/independent-closure.json`: seven
  CPU tests, 26 exact GPU readbacks/ten submissions, one late atomic guard and
  five saved byte/version checks. Captured program 54 is a one-pixel control;
  original requested fullscreen loading shader is outside that historical
  fixture; later bounded intended-route proof is separate. Physical swap
  timing stays unverified. Actual game excludes the tested CPU resize branch.
- `build/macos-metal/map-transition-indexed-history-attempt1/independent-execution-closure.json`:
  four alternating changes complete with actual host/guest0/API validation and
  all 50 source bindings frozen. `root-scene-observations.json` separately binds
  five recognizable map images; producer result is unchanged and globally false.
  Strict stale texture/pixel/full-game/performance/resize gates remain open.
- `build/macos-metal/stock-mp-content-f69b-attempt1/independent-closure.json`:
  historical all 13 original multiplayer scenarios pass bounded execution and
  saved-image review; 50 build bindings, 281 artifact descriptors and eight CPU
  guards. `independent-closure-observed.json` binds the audit's actual exit0.
- `build/macos-metal/stock-campaign-content-f69b-attempt1/independent-closure.json`:
  all ten original campaign openings attempted on frozen f69b; seven pass and
  `c40`/`d20`/`d40` remain failed. Source, init, execution identity, elapsed and
  scene scope are checked independently. The audit exits0 while coverage is
  deliberately false; no failed image is promoted to a positive world pass.
- `build/metal-poc/source-pixel-mode-audit/{inventory.json,report.md}` and
  `{stock-bitmap-metadata-audit.json,stock-bitmap-findings.md}`: CPU-only source
  and original-cache metadata inventory; no general shader/resource or GPU
  fidelity gate is closed.
- `build/metal-poc/volume-colour-gpu-current-attempt4/independent-closure.json`:
  1,050 exact GPU readbacks, 20 atomic guards and 100 byte/version checks;
  component scope and retained precision failures remain explicit.
- `build/metal-poc/volume-colored-border-source-ready/closure.json` and
  `volume-border-emitter-cpu-proof/closure.json`: appended typed state/options,
  183 ILP32 cases/24 native tests and 22 emitter CPU tests, preserving baseline
  output and options-version bounds.
- `build/macos-metal/live-volume-colour-build-proof/result.json`: frozen f69b
  native build/linkage with 50 frozen bindings, separately tied to the two live
  scripted results below.
- `build/macos-metal/live-volume-colour/{bloodgulch,damnation}/result.json`:
  bounded 30-second scripted movement/firing, host/guest0/API validation,
  original colored-volume/D24 success and visual world/weapon/decal/HUD checks.
  No manual, pixel-parity or performance claim.
- `build/macos-metal/native-metal-gameplay-playtest/prepared.json`: separate
  experimental launchers, frozen build/isolated saves and normal byte-exact
  input/audio configuration; manual input/audio still require playtesting.
- `build/metal-poc/host-frame-volume-colored-current-attempt2/independent-closure.json`:
  fresh 378 byte/version/sequence checks on the colored-volume implementation,
  with original inputs, API validation and host/guest0. CPU packer provenance
  binding is separate from actual packer execution.
- `build/metal-poc/native-draw-state-d24-ilp32-final/closure.json`: 21 native tests
  and 164 actual ILP32 CPU cases with captured original D24 provenance, unchanged
  default outputs and 28 atomic depth rejection cases.
- `build/metal-poc/dot-zw-raw-d24-current-attempt4/independent-closure.json`:
  284 exact GPU readbacks/46 controlled cases under safe fragment compilation;
  actual key compilation is separate from original VS66/resource execution.
- `build/macos-metal/live-volume-depth-observed-build-proof/result.json`:
  complete native build/linkage snapshot; live outcomes require separate proof.
- `build/macos-metal/live-volume-linear/damnation/result.json`: all-linear
  bounded startup, frame 420/74,044 draws; original water pixel parity remains open.
- `build/macos-metal/live-volume-linear/bloodgulch/result.json` and
  `live-depth-diagnostic/`: retained frame 20 failure and distinct frame 89
  authoritative shader/depth diagnostic.
- `build/metal-poc/copy-subresource-current-attempt2/independent-closure.json`:
  exact synthetic rendered-mip GPU copies/sampling and atomic rejection guards,
  bound to its copy-only source/binary snapshot.
- `build/metal-poc/rendered-mip-planner-validation/closure.json` and
  `boundary-validation.json`: CPU alias/mip planning and unchanged outputs on
  failure, with an actual ILP32 source snapshot. Original water execution is
  recorded separately by its historical Damnation startup proof.
- `build/metal-poc/volume-copy-validation-final/closure.json`, `native-suite.json`
  and `assets.json`: CPU authored-volume extraction and proven runtime asset
  identity. GPU sampling is a separate later closure.
- `build/metal-poc/volume-all-linear-gpu-current-attempt1/independent-closure.json`:
  770 exact resource/sampler readbacks, both original footprints, generated
  PROJECT3D components and atomic guards, with a frozen executed source group.
- `build/metal-poc/volume-gpu-current-attempt1/failure-closure.json`: retained
  failed near-half nearest-LOD oracle; independent quarter controls do not
  override it.
- `build/metal-poc/host-frame-volume-linear-current/independent-closure.json`:
  all 378 original checkpoint bytes/versions/sequences exact on the latest
  volume-capable backend, explicit API validation and host/guest0.
- `build/macos-metal/live-volume-water/damnation/result.json`: historical
  original four-level rendered-water execution, with its own earlier frozen
  build. Working-port water pixels and full-game parity remain false.
- `build/metal-poc/volume-linear-implementation-current/implementation.json` and
  `native-draw-state-volume-linear-ilp32/result.json`: additive all-linear
  contract, strict compilation and unchanged original CPU draw outputs.
- `build/macos-metal/live-batched-build-proof/result.json`: the actual batched
  guest and host build exits zero, with 32 frozen source/binary bindings,
  native ILP32/helper/exit-path link evidence and no GL/ANGLE linkage or imports.
- `build/metal-poc/packet-room-validation/closure.json`: 2,862 actual ILP32
  comparisons against the production packet builder verify complete-command
  alignment and capacity bounds, including retained frame extents and overflow.
- `build/metal-poc/host-frame-coalesced-current/closure.json`: all 795 original
  commands and 126 draws are retained when 131 submissions become one packet.
  The six final attachment/query readbacks and versions match the canonical
  result exactly under Metal API validation. Intermediate checkpoints, CPU
  query timing, presentation and performance are separate unverified gates.
- `build/metal-poc/host-frame-alpha-border-current/regression-closure.json`:
  all 378 original color/depth/stencil/query checkpoints are byte exact across
  126 draws and 131 submissions, with actual host/guest exit zero and packet
  rederivation. CPU timing, presentation and full-game gates remain false.
- `build/metal-poc/black-border-validation-current/closure.json`: 30 actual
  ILP32 GPU draws and 4,806 exact analytic sample checks cover authored mips,
  fractional trilinear fringes, corners, mixed address axes and derivative LODs.
  Eight invalid later draws reject atomically. Elongated anisotropic footprints
  and physical Xbox precision are not established by the constant-UV case.
- `build/metal-poc/channel-clear-validation-current/closure.json`: 246 actual
  GPU clear cases, 14 atomic rejection cases and 261 byte/version checks.
- `build/metal-poc/scaled-present-validation-current/closure.json`: 16 actual
  window/layer cases, linear scaling within one UNORM byte, 31,236 exact black-bar
  pixels, source invariance and shader-read/flag preflight rejection checks.
- `build/metal-poc/guest-c-transport-black-border-current/result.json`: 37 actual
  transport and malformed-reply guards. The later
  `guest-c-transport-alpha-border-current/result.json` adds eight typed-record/
  capability guards for 45 total. Native vertex/state helper proofs retain
  original frozen draw bytes, actual ILP32 execution and sanitizer checks.

Every proof retains its executed source/binary snapshot. Clear/presentation
proofs precede the optional black-border backend change and remain historical
results for their bound snapshots. Recheck source bindings when applying a
result to the current executable; do not widen a fixture into gameplay parity.
