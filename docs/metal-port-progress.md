# Native Metal port: scope and evidence

The goal is the complete Xbox-derived Halo game rendered directly by Metal on
Mac, preserving the original Xbox NTSC style, gameplay and presentation while
enabling native renderer performance improvements. The static Blood Gulch
viewer is an asset/material experiment, not the finished game renderer.

This ledger separates implementation from verification. A compiled shader, a
successful static capture, or an ANGLE comparison alone cannot close the full
game or original-Xbox fidelity requirement. Keep the goal active until every
requirement below has direct evidence at its stated scope.

## Requirements and current evidence

| Requirement | Evidence needed to close it | Current state |
| --- | --- | --- |
| Native backend driven by the existing game | Gameplay executable routes the Xbox D3D8/NV2A API to Metal without GL/ANGLE; verify the loaded libraries and actual GPU command path | **Menus, stock starts and four bounded changes verified; broader gameplay incomplete.** Frozen 125 passes 13 multiplayer starts and ten campaign openings. Later no-GL/ANGLE build `1fc22efa…` binds 53 inputs, completes four alternating Blood Gulch/Damnation changes with original unlit/immediate loading and passes a separate fresh Hang Em High opening. Historical failures remain retained. Complete loading pixels, strict stale content, manual input/audio and full-game fidelity remain unverified. |
| Original vertex programs and declarations | Original instruction words, packed input formats, fixed registers, constants and viewport corrections replay correctly for all game uses | **Partial.** All 67 checked-in programs and captured Blood Gulch variants compile. Corrected inverse-viewport staging with an explicit vertex compiler contract produces an exact actual opaque draw. The bounded original unlit/immediate route passes 288 ILP32 CPU cases and a GPU component with 28 exact/three predefined one-byte gradient checks; its actual copies are exact. These scopes do not establish every vertex use or physical Xbox arithmetic. |
| Original pixel combiners and texture stages | Independent numerical and actual-draw coverage of every used combiner, dependent read, signed-channel, alpha/fog and texture mode | **Partial.** Historical 345 fixtures include 36 integer-D24 depth checks; 116 independent ANGLE texture-stage cases match exactly. Explicit D24 adds 164 ILP32 CPU cases and 284 exact GPU readbacks across 46 synthetic controls under safe compilation. The actual f135 key compiles, but original VS66/resources are not executed in that fixture. Volume-border options v3 add 22 emitter CPU tests with all 126 baseline outputs unchanged; generated PROJECT3D/alpha-kill component cases pass within the 1,050-readback GPU proof. Actual zsprite/lighting parity, BRDF, constant-eye reflection, HILO/some signed mappings and sample counting remain incomplete. |
| Original resources and mutations | Authored mips, swizzled/linear/compressed/palettized textures, cube/volume images, stream/index formats, pitches, palettes and updates match the original; aliases are versioned correctly | **Partial.** P8 palettes, cube faces/mips and BC upload subsets have independent proof. Volume extraction has 244 ILP32 comparisons and proven runtime AL8 asset identity. Cap8192/type3 literal-black borders pass 770 GPU readbacks; cap16384/opcode21 authored RGBA companions pass 1,050 readbacks, 20 atomic guards and six specified RGBA5 half-up controls. Its CPU closure passes 183 ILP32 cases/24 native tests. Near-half nearest-LOD precision, original lighting pixel parity and manual firing remain pending. Cap4096/opcode20 copies pass 254 GPU readbacks; Damnation's four-level composite executes in the new bounded scripted run; the earlier all-linear frame 420/74,044-draw result remains historical. Water pixels, BC2/BC3 cubes, compressed/render-target volumes and missing rendered-mip generation remain open or unsupported as documented below. |
| Complete render state | Depth/stencil, color masks, blending, culling, viewport/scissor, polygon offset, point size, pixel centers and attachment precision verified independently and in game | **Partial.** Actual original opaque color/depth/stencil readbacks are retained. Current unequal-attachment controls pass 45 analytical GPU readbacks and seven atomic guards, preserving outside depth/stencil and partial-clear contents. Raw unused VS constant bank bits are preserved through 193 ILP32 CPU cases; native state/viewport floats remain validated. Original c40 pixel parity and physical D24/F24 precision remain open. |
| One original game draw | Replay a visible captured draw using its exact original streams, shader keys, uniforms, texture bytes, sampler and raster state; compare lossless pixels to an independently rendered ANGLE reference | **Verified for opaque program 17/declaration17 through actual ILP32 imports.** Direct NV2A shaders and immutable original streams/resources exactly match all 307,200 color/depth/stencil pixels, with 41,738 visible pixels and zero tolerance. Earlier replay and decal proofs remain frozen separately. Scope remains one isolated draw against the working ANGLE port. |
| Complete ordered original frame | All clears, attachment changes, draws, resource versions, readbacks and presentation recorded and replayed in order; compare all color/depth/stencil targets | **Captured attachment/query replay exact; live frame gate remains open.** Current original-state backend repeats all 378 frame 420 byte/version/sequence checks through 126 draws/131 submissions, with actual ILP32 host/guest0 and API validation. The replay uses captured finite constants and equal attachments; the live frontend and state packer are provenance only. CPU query timing and presentation remain unverified, so full-frame gate stays false. |
| All original visual passes | BSP detail/bump/radiosity/specular, sky/clouds, fog, scenery, actors/vehicles, first-person weapons, HUD/fonts/menus, decals, particles, shadows, water/reflections and post effects shown in the native game | **Incomplete.** Fresh runs show world/first-person/HUD on all 13 stock multiplayer maps and inspected scenes on all ten campaign openings. A30 uses explicitly selected same-run frame 420 cockpit evidence; its final white frame 540 remains unobserved as a positive scene. Earlier firing runs exercise colored-volume/D24 and Damnation four-level water paths. Matched pass pixels, complete missions and manual effects remain unverified. The separate viewer still simplifies lighting and omits many passes. |
| Visibility and GPU feedback | Original clipping/PVS, stencil composition, render-to-texture, occlusion/sample-count queries and result timing verified | **Partial.** Native queries and 378 frozen frame checkpoints are exact within their scopes. Indexed history adds 26 byte/version/sequence checks; the later intended unlit/loading component has 16 ILP32 helper calls, 21 successful submissions, one atomic guard and five saved byte/version checks. Four actual changes on 1fc22 avoid the prior attachment-alias crash. A focused synthetic roof GPU pose measures a small edge loss, with original/invariant variants identical; original ANGLE/user-pose parity and a fix remain unverified. Complete loading pixels, strict stale content and physical swap/query timing remain open. |
| Gameplay and timing invariants | 30 Hz simulation, weapons/animation, input action age, camera presentation, network and split-screen behavior measured with the native backend | **Unverified.** The live frontend preserves original simulation code and local-game startup runs, but interactive gameplay/timing remains unverified. Higher render frequency must remain separate from simulation timing. |
| Original Xbox appearance | Matched-camera/settings captures from original Xbox NTSC and native game across stock multiplayer and representative campaign scenes, with residual differences recorded | **Incomplete.** Current ANGLE captures are a working-port regression reference, not a retail Xbox oracle. |
| Full content coverage | Native menus, stock multiplayer maps, representative campaign geometry/effects, transitions/loading, vehicles and split-screen exercised with unchanged user-owned game assets | **Bounded fresh starts/four changes verified; full coverage incomplete.** Frozen 125 passes all 13 stock multiplayer starts for at least 15 seconds and all ten campaign openings for at least 30 seconds. Later 1fc22 completes BG→Damnation→BG→Damnation→BG over 240.502354 seconds with five separately reviewed images, plus a fresh 15.268147-second Hang Em High opening. All 23 have not been rerun on 1fc22. Transition producer/global passed remains false; complete missions, strict stale content, original loading pixels, broader transitions, vehicles, split-screen and manual gameplay remain unverified. Historical f69b seven-of-ten and 125 zero-switch results stay false. |
| Performance improvement on Macs | Comparable full-game CPU/GPU frame times, upload volume, memory, sustained frame delivery and input age; higher resolution/refresh tested after fidelity | **Partial measurement; exact workload gate failed.** Twelve controlled original Blood Gulch A/B/B/A runs exit zero. Earlier-build median19.355 FPS versus batched30.002 FPS under original 30 FPS pacing. Timed HUD text and smaller draw-count differences prevent exact workload parity. Full-game CPU/GPU time, sustained memory/input age and high-refresh capacity remain unverified. |
| Reviewable delivery and rollback | Focused source changes, reproducible native build, test/evidence ledger and installed-game verification once the actual game backend is ready | **Partial.** Renderer work remains isolated in `codex/metal-renderer-poc`; recovery archives exist. Three new experimental launchers bind frozen 1fc22 with all 53 current/frozen/snapshot inputs verified, normal audio/input configuration, separate fresh saves and original asset symlinks. Earlier 125/f69b launchers and pending readiness records remain preserved. Manual input/audio remain untested. No install/package operation or installed-app byte comparison is claimed. |

## Evidence already retained

- `build/macos-metal/fixed-loading-build-proof/result.json` (`1fc22efa…`)
  retains the actual successful no-GL/ANGLE build with 36 primary/17 evidence
  bindings. Both fixed-function helper sources and actual linked ILP32 guest
  object (`49d2aa0e…`) are checked in the source graph, link and guest exports.
- `build/metal-poc/fixed-function-ilp32-current-attempt2/result.json`
  (`e7ba8fa0…`) passes 288 cases: 49 positive/239 atomic rejections, eight production
  selection controls and 8,191 small-integer handle lookup controls. The bounded
  original null-handle unlit/immediate route retains original matrices, colors,
  texture coordinates, viewport and half-pixel correction; unsupported states
  fail explicitly without replacing the original NV2A path.
- `build/metal-poc/intended-fixed-loading-current-attempt3/independent-closure.json`
  (`fe8f0260…`) checks 16 actual ILP32 production helper calls, 21 successful GPU
  submissions, one rejected batch and five saved byte/version checks. Of 31
  readbacks, 28 are byte-exact and three gradients use a predefined maximum
  one-byte bound; copies of actual gradient bytes are exact. This component
  proves the bounded requested unlit/fullscreen loading route and order, not
  complete original loading-screen pixels or physical Xbox arithmetic.
- `build/macos-metal/map-transition-fixed-loading-attempt1/independent-execution-closure.json`
  (`5b62165f…`) verifies five phases/four alternating Blood Gulch/Damnation
  changes: load ACKs, player readiness, 15-second holds, host/guest0 after 240.502354
  seconds, API validation, no error/dump, and 53 bindings plus 17 context sources.
  Last logged frame 7020 counts 1,731,566 draws/222 textures/82 programs; these
  diagnostics are not workload parity, cache-lifetime or performance proof.
  Separate root scene sidecar `b6965f08…` binds recognizable world/weapon/HUD
  at frames 360/810/1260/1740/2190. Producer result `53329ceb…` remains globally
  false; strict stale-content readback, physical SDK timing, actual resizing,
  full-game and performance gates remain open.
- `build/macos-metal/fixed-loading-hang-em-high-smoke-attempt1/independent-execution-closure.json`
  (`2ecc3391…`) verifies one fresh 15.268147-second current-build opening with
  host/guest0/API validation, all 53 bindings, no errors/dumps, and independently
  exact BMP/PNG RGB bytes. Reviewed frame 420 shows original gray interior,
  ramp rails, platform supports, pistol/hands and HUD. Last log at frame 420 records 121,757
  draws/129 textures/49 programs; these are diagnostics. Original provisional
  `2aafebf9…` remains preserved before reviewed result `907b4271…`. This is an
  offline, muted, bot0 run with human bindings disabled, not manual playtesting.
- `build/macos-metal/native-metal-playtest-fixed-loading/handoff-all-three-independent-closure-v2.json`
  (`877b6ba8…`) checks all 53 current/build-frozen/promotion-frozen files and
  binaries, mode 0755/`zsh -n`, original map/sound links, separate fresh saves and
  exact normal config `5404c946…`. Prepared `cd52e3e5…`/handoff `5abe0b0a…`
  make Blood Gulch, Damnation and Hang Em High ready for experimental local
  testing. Initial ready=false, pending-HH records and scoped two-map audit are
  preserved. Normal keyboard/mouse/audio are enabled but untested; no bots,
  autoexit, telnet or screenshots. A rerun of all 23 on this build, manual audio/
  input, full game, original pixels and performance remain unverified; no game/GPU/install/package
  operation is performed by this metadata promotion.
- `build/macos-metal/indexed-history-build-proof/result.json` (`4b240709…`)
  retains the successful no-GL/ANGLE native build with 50 bindings and frontend
  `3dfde625…`. Distinct current 0/history-1 storage advances history by queued
  copy only at Present. Later unlit/immediate source changes are outside this
  snapshot and require new evidence.
- `build/metal-poc/backbuffer-history-cpu-validation/closure.json`
  (`a6b55440…`) passes seven ASan/UBSan CPU tests and the actual ILP32 syntax check:
  index/refcount guards, stable aliases, Present order, first use and resize
  preservation through extracted real C functions with mocked GPU effects.
  The actual guest defines `HALO_ANDROID` and excludes the resize branch;
  neither actual-game resizing nor physical Xbox swap behavior is established.
- `build/metal-poc/backbuffer-history-gpu-prepared-attempt1/independent-closure.json`
  (`4c29a7da…`) passes 26 exact GPU byte/version/sequence checks through ten
  submissions, one late atomic guard and five saved byte/version checks, with
  actual ILP32 host/guest0/API validation. The independent raw-packet CPU oracle
  checks distinct history, clears and copies; expected-after bytes never enter
  GPU uploads. Captured inherited program 54 covers only pixel(0,0); separate
  point-center controls and bounded resize copies remain component tests.
  `source-route-clarification.json` (`5afb22bd…`) identifies original
  `SetVertexShader(0)` ignored by both inherited GL and frozen native setters,
  leaving stale UI program 54. This is history transport/ordering proof, not
  the intended fullscreen four-tap loading blur. The bounded original unlit/
  immediate correction has no corresponding GPU proof in that historical
  snapshot; the later intended-route proof above remains separate.
- `build/macos-metal/map-transition-indexed-history-attempt1/independent-execution-closure.json`
  (`4bedd111…`) verifies five phases/four BG→Damnation→BG→Damnation→BG changes:
  exact HS load ACKs, player-ready outputs, at least 15-second holds, host/guest0 after
  240.507699 seconds and API validation without renderer errors or failure dumps.
  All 50 frozen/current bindings and 17 context sources were checked before new
  edits. Last logged frame 7020 records 1,730,571 draws; 222 textures/82 programs
  plateau from frame 540 does not establish retirement, eviction or performance.
  The separate `root-scene-observations.json` (`8cbb1a56…`) and contact sheet
  bind manual review of recognizable map world/weapon/HUD at frames 360/810/1260/1710/
  2160. Their original BMP hashes match the audit. Producer result `e7c5d8e3…`
  remains unchanged with global passed/saved-image-inspection false. Safe native
  history attachment aliasing is verified for these four changes; strict stale
  payload/readback, loading pixel parity, SDK physical timing, actual resizing,
  full-game and performance gates remain false. No newer launcher handoff is
  implied.
- `build/macos-metal/stock-content-original-state-23-current/result.json`
  (SHA256 `ca35aced…`) combines current frozen 125 bounded coverage: all 13
  fresh multiplayer starts and ten fresh Normal campaign openings pass with
  actual host/guest0, API validation and inspected scene evidence. Independent
  campaign/MP closures (`89858868…`/`03ab86ed…`) verify all 50 build bindings,
  350/320 artifact hashes, execution/plan/init/environment/fresh-save identity
  and minimum 30/15-second windows. The unchanged producers retain 16 passing
  CPU guards. Last logged counters total 1,821,977 campaign and 1,207,033 MP
  draws; they are diagnostic counters, not a performance measurement.
  A30 explicitly uses original same-run frame 420 cockpit evidence. Its final
  white frame 540 keeps `image.visually_observed=false`; original pixels,
  provisional result and review metadata corrections remain preserved.
- `build/macos-metal/campaign-original-state-build-proof/result.json`
  (SHA256 `125be740…`) freezes the corrected no-GL/ANGLE native build with 50
  bindings. The 193-case ILP32 raw-bank CPU closure retains original unused
  constants and validates native state/viewport floats. Separately,
  `build/metal-poc/unequal-attachment-current-attempt1/independent-closure.json`
  (`82d0e04e…`) passes 45 analytical GPU readbacks, seven atomic guards and 28
  byte/version checks through actual ILP32 imports with API validation.
  Original attachment identity and outside depth/stencil are retained;
  synthetic controls do not establish original c40 draw pixel parity.
- `build/metal-poc/host-frame-original-state-current/independent-closure.json`
  (`b3856ba6…`) repeats all 378 original frame 420 byte/version/sequence checks,
  126 draws/131 submissions, no missing readbacks and exact packet rederivation,
  with actual ILP32 host/guest0/API validation. The raw-bank state packer and
  live frontend are bound as provenance but not executed in this finite-bank,
  equal-attachment capture. CPU query timing, presentation and full-frame gate
  remain false.
- `build/macos-metal/native-metal-playtest-original-state/independent-closure.json`
  (`cf74b4b1…`) verifies three frozen 125 Blood Gulch/Damnation/Hang Em High
  initial-map launchers: all 50 build bindings, original map/sound symlinks,
  mode 0755, actual `zsh -n` success, exact frozen commands, isolated fresh saves
  and byte-exact normal configuration `5404c946…`. Audio and keyboard/mouse
  are enabled; scripted input, autoexit and screenshots are disabled. The
  original ready=false prepared record remains exact in
  `prepared-before-handoff.json`. `handoff-ready.json` (`34f79d8c…`) promotes
  the three launchers for initial-map use only, independently checked in
  `handoff-promotion-independent-closure.json` (`a3c32119…`): 50 frozen/current
  bindings and unchanged command/config/build identities. Human input/audio
  remains untested. No installed app was referenced or fingerprinted.
- `build/macos-metal/map-transition-125-attempt2/independent-closure.json`
  (`d0a50e44…`) retains actual host/guest-5 at frame 464 in the first Blood Gulch
  to Damnation loading transition, with zero successful switches. The failing
  draw's four sampled textures alias its active color target. The bound
  `indexed-buffer-source-contract.json` (`c71e3535…`) shows original progress
  rendering needs distinct current 0/history-1 storage; that frozen adapter
  collapses those getters. The failed result stays unchanged after the later
  indexed-history proofs above. Physical SDK swap ordering remains unproven.
  Existing frozen 125 ready launchers still cover separate initial-map starts.
- `build/macos-metal/stock-mp-content-f69b-attempt1/independent-closure.json`
  (SHA256 `cb65d30f…`) verifies all 13 original multiplayer scenarios against
  historical frozen build `f69b523b…`: fresh 15-second bot0 runs, host/guest0,
  Metal API validation, no renderer/API failure, and inspected lossless
  640×480 world/first-person/HUD images. All 50 build bindings and 281 run
  artifact descriptors match at this source window; eight CPU guards pass.
  Last logged checkpoints total 1,225,896 draws. Boarding Action logs240 and
  captures270; other cases log/capture420. These are not performance or
  final-frame workload measurements. Campaign/UI/community are excluded.
- `build/macos-metal/stock-campaign-content-f69b-attempt1/independent-closure.json`
  (SHA256 `41c378df…`) retains historical original Normal campaign openings on
  the same frozen build. The successful 30-second cases are
  `a10/a30/a50/b30/b40/c10/c20`; opening cinematics are reviewed as scenes,
  with first-person world/HUD visible in `c10`. Fresh saves, literal HS paths,
  no Slayer/cheats/cinematic skip and empty scripted input are verified.
  `c40` exits host-5 after submission status-1 at frame 41/command2;
  `d20` exits host-5 after nonfinite vertex uniform/viewport state rejection at
  frame 48; `d40` rejects the same state at frame 503 after 62,442 draws logged
  at 480. `c40`/`d20` frame 30 images are black and provide no positive world
  evidence. `d40` frame 480 shows the ship/crash-site cinematic before failure
  but remains failed. Its own files contain no binary failure dump identifying
  the exact offending program/constant/resource. Campaign coverage is
  **false, seven of ten at its frozen source window**.
  The independent audit checks all execution/plan/config/source identities,
  environment, fresh-save markers, actual HS init and positive elapsed windows;
  eight CPU guards pass. Existing producer guard gaps are retained separately
  and checked in this closure without rewriting the executed producer.
  Later diagnostic source edits and rebuilds must retain separate provenance.
- `build/macos-metal/campaign-failure-diagnostic-attempt2/independent-closure.json`
  (SHA256 `58faf6f7…`) verifies failure-only build `4a839107…`, all 50 frozen
  bindings and 179 artifact hashes. Actual `c40/d20/d40` reruns exit host-5
  at frames 40/73/510 after 2.1186/3.5808/17.7368 seconds; outer driver exit0
  means collection completed. The prepared hash actually matches; its absent
  driver prelaunch check is retained. Attempt1 preparation failure and frozen
  f69b results remain unchanged; six later current-source drifts are expected.
  The captured `c40` mirror clear pairs 320×240 color with primary depth ref2
  (640×480 size source-inferred). Equal-size validation rejects it.
  Captured VS9 in `d20/d40` has only `c[23].w` raw `ffffffff` nonfinite:
  unused distant-light padding, while its DP3 reads xyz. The typed source
  route excludes relative reads of that component; exact expanded inputs
  remain uncaptured. The subsequently corrected frozen 125 CPU, GPU and live
  opening proofs are retained separately above. No historical failure result
  is rewritten, and original campaign draw pixel parity remains unverified.
- `build/metal-poc/source-pixel-mode-audit/inventory.json` records 64 original
  checked-in texture-mode assignments with source hashes; reviewed builders
  emit 0/1/2/3/9/10/11/12/17. No BRDF8, constant-eye18, HILO dot mapping4–7 or
  explicit COLORSIGN setter was found in that source scope. This CPU audit
  does not establish every retail/runtime use or relax native rejection.
  `stock-bitmap-metadata-audit.json` (SHA256 `48289a51…`) scans 14,815 bitmap
  records across 24 original Xbox v5 caches, including repeated assets:
  zero BC2/BC3 cubes and zero V16U16 flags; all 572 cubes use admitted formats.
  L16 has no authored cache-format mapping in the reviewed source. General
  BC2/BC3 cube admission and shared V16U16/L16 low-byte precision remain gaps,
  without an affected stock asset established here. No pixel export or GPU
  validation is part of this metadata audit.
- `build/macos-metal/live-volume-colour/bloodgulch/result.json` (SHA256
  `69f6b3c4…`) passes 30.5901 seconds of scripted movement/firing; frame 840
  statistics record 220,223 original draws, 158 textures and 82 programs.
  `damnation/result.json` (`fa0b08d9…`) passes 30.2540 seconds, recording
  161,216 draws, 138 textures and 93 programs at frame 840. Both observed
  host/guest exits are zero with API validation and no validation errors.
  Final frame 870 captures were inspected for world, weapons, bullet decals
  and HUD; Blood Gulch also shows the base/plasma gun. Both logs record modes
  0x18c41 with volume mask 2 and original 0x54421 D24 request 42/current 0x2e21,
  float-Z 0/raw scale 16777215/offset 0/safe compiler 0. Damnation logs its original
  128×128 four-level rendered composite. These muted bot-slot 0 runs disable
  human bindings; counters are not a performance benchmark. Matched pixels,
  manual input/audio, physical Xbox and full-game gates remain false.
- `build/macos-metal/native-metal-gameplay-playtest/prepared.json` binds separate
  historical Blood Gulch/Damnation launchers to the frozen `f69b523b…` build,
  isolated saves and byte-exact original normal input/audio configuration, with
  no scripted input or automatic exit. No installation is part of this handoff.
  Ready-for-handoff does not establish manual controls or audio verification.
- `build/metal-poc/host-frame-volume-colored-current-attempt2/independent-closure.json`
  passes all 378 original frame 420 checkpoint bytes, wire versions and
  submission sequences: 126 draws, 131 submissions, no missing checkpoints,
  exact packet rederivation, API validation and observed host/guest0. The initial
  initialization failure remains preserved. The current state packer is bound
  as integration provenance but is not executed by this captured-state replay.
  CPU query availability/timing, presentation and full-game gates remain false.
- `build/metal-poc/volume-colour-gpu-current-attempt4/independent-closure.json`
  (SHA256 `1034b9f2…`) passes 1,050 byte-exact readbacks, 20 atomic guards and
  100 saved byte/version checks through 803 successful submissions, plus seven
  CPU tests. Actual observed host/guest0 and API validation are retained.
  Production-generated PROJECT3D stage 0/1/2, alpha kill and both validated
  footprints pass using synthetic matching inputs. Six specified RGBA5
  half-up edge controls pass; the prior .51 nearest-LOD precision failure,
  original dynamic-light draw, physical Xbox and full-game gates remain false.
  Oracle-after pixels never enter guest uploads. Initial sandbox GPU failure
  and subsequent fixture query-version/negative-ordering errors in attempts
  1–3 remain preserved separately.
- `build/metal-poc/volume-colored-border-source-ready/closure.json` binds 24
  native CPU tests and 183 ILP32 cases (145 positive/38 atomic reject), with all
  126 prior draw outputs unchanged. `volume-border-emitter-cpu-proof/closure.json`
  binds 22 emitter CPU tests, unchanged baseline MSL/GLSL and guard-page v1/v2/v3
  options read limits. Cap16384/opcode21 has a 424-byte record with disjoint
  volume/alpha masks; auxiliary white/black companions use identical base
  descriptors and exact reflected bindings. Only normalized mipped 3D and
  the two anisotropy1 footprints are admitted.
- `build/macos-metal/live-volume-colour-build-proof/result.json` (SHA256
  `f69b523b…`) records a frozen completed native build with 34 primary/16 evidence
  bindings and no GL/ANGLE linkage/imports. Both scripted results above verify
  their executed binaries against this snapshot; build success remains a
  separate scope from those bounded live passes.
- `build/macos-metal/live-volume-depth-observed/bloodgulch/result.json` and
  `damnation/result.json` retain failures at frames 17 and 65 respectively:
  stage 1 32³/six-mip PROJECT3D, XYZ BORDER, ARGB0x05050505, all-linear/aniso1.
  Neither has a D24 success line. These failures remain distinct from the older
  Blood Gulch frame 20 failure and frame 89 authoritative depth diagnostic.
- `build/metal-poc/native-draw-state-d24-ilp32-final/closure.json` passes 21 native
  tests and 164 actual ILP32 CPU cases (136 positive/28 atomic reject), preserving
  every default output prefix from the 126 frozen original draws. The appended
  RAW_D24 contract requires original D24 request/current format, float-Z 0,
  an attachment and matching finite viewport bounds/scale/offset. Unknown or
  floating units, missing depth, opt-out and malformed metadata reject without
  changing key/output bytes. DEPENDENT_AR 0x0f is correctly independent of the
  DOT_ZW 0x0a depth gate. Depth CPU cases use captured key/constants/provenance
  with explicit fixture-only unrelated render arrays/samplers.
- `build/metal-poc/dot-zw-raw-d24-current-attempt4/independent-closure.json`
  passes 284 raw GPU readbacks across 46 controlled depth cases, 20 typed cases
  (17 reject/3 accept), four atomic backend failures and 96 saved byte/version
  comparisons, with 67 successful submissions and observed host/guest0/API
  validation. Safe fragment contract 0 is mandatory for finite guards. These
  synthetic controls use stage 1 texture RGB; the actual f135 key compiles but
  original VS66/resources are not executed. Original-draw pixel parity and
  physical Xbox D24 quantization remain false. Attempt 3's synthetic buffer 1
  versus required buffer 0 failure is retained in `fixture-binding-failure.json`;
  the optional stage 0 expansion at
  `dot-zw-raw-d24-current-expanded-attempt1/not-executed.json` remains unexecuted.
- `build/macos-metal/live-volume-depth-observed-build-proof/result.json` binds
  the complete new native guest/host build and its `snapshot/`, with build exit0
  and no GL/ANGLE linkage/imports. Its later scripted runs stopped at the
  colored-volume state above; the component depth proof does not make them pass.
- `build/macos-metal/live-volume-linear/damnation/result.json` passes the
  separate all-linear bounded startup: 15.326 seconds, frame 420/74,044 draws,
  host/guest0 and API validation. The earlier frame 420/73,014-draw water run
  remains historical. Neither establishes native water pixels or performance.
- `build/macos-metal/live-volume-linear/bloodgulch/result.json` preserves the
  scripted program failure at frame 20. The distinct frame 89 diagnostic under
  `live-depth-diagnostic/` captures key SHA f13524b3…, original float-Z 0,
  D24 request 42/current LIN_D24 surface 0x2e21, viewport 0/1 with raw 16777215
  scale/offset 0, original 192 constants and exact VS66 words. It does not prove
  the diagnostic is the same draw/time as the frame 20 failure.
- `build/metal-poc-0.6/roof-geometric-occlusion-audit/final-audit.json` retains
  30,714 textured interior CPU samples on eight red glyph sections. Tested
  geometry is not occluded; the user's exact downward-camera GPU behavior
  remains unreproduced. No bias or geometry change was made.

- `build/metal-poc/volume-all-linear-gpu-current-attempt1/independent-closure.json`
  passes 770 exact raw readbacks with API validation and observed host/guest0.
  Both original normalized 3D RGBA0/aniso1 border footprints are tested: point
  min/mip plus linear mag, and linear min/mag/mip. All authored voxels, asymmetric
  XYZ/channels, padded partial updates, 273 rational XYZ-border/mip blends and
  27 production-generated PROJECT3D q/border cases pass. Twenty-nine late
  failures reject atomically with 145 saved byte/version checks. The executed
  sources are frozen (backend `c83427b4`, ABI `6c457f4c`, encoder `6407b120`,
  transport `3118c29a`). Synthetic keys/vertices do not prove an original
  lighting draw's pixels, and volume versions are not exposed by target-only
  readback.
- `build/metal-poc/volume-gpu-current-attempt1/failure-closure.json` retains the
  **failed** near-half nearest-LOD ideal gate: 0.51/1.51/4.51 requests disagree
  with the ideal oracle. Later .25/.75 controls pass separately. The failed
  bytes, expected values and tolerance remain unchanged; full nearest-LOD
  precision is still open.
- `build/metal-poc/host-frame-volume-linear-current/independent-closure.json`
  freshly verifies all 378 original frame 420 color/depth/stencil/query
  checkpoint bytes, wire versions and sequences, with 126 draws, 131
  submissions, explicit API validation and host/guest0. Packets and original
  inputs are rederived exactly. CPU query timing, presentation and the live
  full-frame gate remain false.
- `build/macos-metal/live-volume-water/damnation/result.json` records an
  original native 15.34-second startup: host/guest0, frame 420, 73,014 draws,
  API validation and an actual 128×128 four-level rendered composite in the log.
  Its earlier build/source snapshot is preserved and not rebound to the later
  all-linear source group. Original water execution is demonstrated; matched
  water pixels, original Xbox fidelity and full-game gates remain false.

- `build/metal-poc/copy-subresource-current-attempt2/independent-closure.json`
  verifies cap4096/opcode20 through the real ILP32 transport: 254 exact analytic
  GPU readbacks, 25 atomic invalid-later-copy cases and 125 saved byte/version
  checks, with observed host/guest exit0 and Metal API validation. Four synthetic
  128/64/32/16 rendered levels are copied into a mip chain and sampled. This is
  not an original water capture; the shader-read composite's version is not
  exposed by the target-only readback API. Its copy-only sources/binaries remain
  frozen before volume edits. The original water and refreshed legacy-frame
  regression gates in this closure remain false.
- `build/metal-poc/rendered-mip-planner-validation/closure.json` records 517
  actual ILP32 CPU cases, with separate maximum-chain/alias-count checks in
  `boundary-validation.json`. `metal_mip_composite.c` selects the latest target
  at each original physical mip address. The frontend queues each planned GPU
  copy before sampling; missing/incompatible levels reject rather than receive
  CPU replacement bytes or generated mips. Original four-level water execution
  is recorded by a separate historical Damnation startup; water parity remains
  pending.
- `build/metal-poc/volume-copy-validation-final/closure.json`, `native-suite.json`
  and `assets.json` bind seven native tests with ASan/UBSan, 244 actual ILP32 CPU
  extraction comparisons and the original runtime asset identity. The captured
  37,449 bytes match Blood Gulch `rasterizer\distance attenuation` bitmap
  `0xe6f60582`, Format0x55560139, six 32³→1³ AL8 mips, SHA256
  `0f23edd4a08b58514e0df7e67691da723b0095f74c0d94643747da7491454196`.
  AL8 replicates the entire authored byte into every RGBA component. Allocation
  padding is excluded. The failure-only hybrid diagnostic remains retained at
  `build/macos-metal/live-volume-diagnostic/execution.json`; its exit−5 is not a
  native gameplay pass. CPU extraction does not establish GPU sampling parity.
- `build/metal-poc/volume-implementation-current/implementation.json` freezes
  additive cap8192/type3 resources, existing EX records with XYZ/image pitches,
  strict native/ILP32 compilation and its historical pre-GPU false gate.
  `native-draw-state-volume-ilp32-final/result.json` passes 132 CPU packing
  cases, including all 126 original outputs byte exact. The actual volume pass
  uses U/V/W BORDER, RGBA0, point min/mip, linear mag and anisotropy1. Only that
  explicit hardware-border footprint was initially enabled; the all-linear
  extension and GPU proof are frozen separately. No 2D fallback is used.
  Full-game firing remains pending. Installed ANGLE's 3D edge
  fallback differs from the original border at nonzero lower-mip boundaries;
  an interior ANGLE comparison alone cannot close original border precision.

- `build/macos-metal/live-batch-benchmark-current/result.json` retains all twelve
  observed live runs and their failed exact-workload comparison. Same original
  assets/configuration, isolated saves, window/drawable and no incidental input;
  frame 120–600 timings use monotonic log arrival. Source-bound build proofs are
  separate. Original30 FPS pacing is retained; no maximum-capacity, physical
  Xbox timing or full-game performance claim follows from these observations.
- `build/macos-metal/live-game-bloodgulch-batched-attempt2/result.json` passes
  controlled API-validation startup through frame 360/93,780 original draws;
  the frozen earlier build also passes its controlled startup. The preceding
  uncontrolled run at `live-game-bloodgulch-batched-attempt1/result.json` retains
  an unidentified unsupported texture-layout failure at frame 70. It remains an
  open live-content case alongside roof/downward decal clipping.
- `build/macos-metal/live-batched-build-proof/result.json` freezes the actual
  live batched frontend build: observed exit0, 32 source/binary bindings and
  native ILP32 helper/exit-path link evidence without GL/ANGLE dependencies.
  Immutable original commands are queued with a 4 MiB soft capacity target;
  Present, readback and explicit sync boundaries submit complete packets.
  The host still completes each submission synchronously.
- `build/metal-poc/packet-room-validation/closure.json` verifies 2,862 actual
  ILP32 complete-command capacity comparisons against the production builder.
- `build/metal-poc/host-frame-coalesced-current/closure.json` retains all 795
  commands and 126 draws while coalescing 131 submissions into one. All six
  final attachment/query readbacks and versions match exactly under Metal API
  validation. The earlier 378 intermediate checkpoints remain a separate proof;
  final coalesced equality does not establish their intermediate history,
  CPU query timing, presentation or a performance gain.
- `build/macos-metal/live-game-bloodgulch-alpha-attempt4/result.json` retains
  original local-game startup: world, first-person weapon, sky, base, HUD and
  radar visually inspected; host/guest exit zero after 60,851 native draws by
  frame 240. Twenty-nine source/binary bindings and copied executed sources/
  binaries are retained. Startup only; no input/audio/performance claim.
- `build/metal-poc/host-frame-alpha-border-current/regression-closure.json`
  repeats all 378 exact legacy frame checkpoints with the alpha-capable backend
  and unchanged default generated shaders. Its transport proof passes 45 guards.
- `build/metal-poc/alpha-border-validation-final/diagnostic-closure.json`
  preserves the failed ideal-byte gate (246 half-tie alpha bytes differ by one)
  alongside 8,450 exact float32 reconstruction controls and 13 atomic rejections.
  The new startup pass does not override the failed precision gate.

- `build/macos-metal/live-menu-current/result.json` binds 23 current source/
  executable files and an actual native original-menu run: 29,593 draws by
  frame 300, visually inspected pixels and host/guest exit zero. Gameplay, menu
  pixel parity, CPU query timing and performance remain unverified.
- `build/macos-metal/live-game-bloodgulch-attempt3/result.json` retains the
  explicit original 64×64/five-mip ARGB0x46000000 border failure. It is a failed
  startup gate, not a gameplay pass.
- `build/metal-poc/host-frame-black-border-current/regression-closure.json`
  repeats all 378 exact captured frame checkpoints against the latest native
  backend, with source bindings and observed host/guest exit zero.
- `build/metal-poc/black-border-validation-current/closure.json` verifies
  transparent-black mip footprints: 30 ILP32 draws, 4,806 exact analytic samples,
  eight atomic rejections and Metal API Validation. Arbitrary colored borders
  and elongated anisotropic footprints remain separate requirements.
- `build/metal-poc/channel-clear-validation-current/closure.json` and
  `build/metal-poc/scaled-present-validation-current/closure.json` preserve
  independent actual GPU channel-clear and window/layer presentation proofs.
  Actual refresh timing is unverified. These snapshots precede black-border
  capability support and remain bound to their executed backend.

- `build/metal-poc/host-frame-native-sample-mask-exit-bound/result.json`,
  `execution.json` and `comparison.json` retain the actual ILP32 host execution,
  original 132 ordered steps, all 378 exact readbacks and eleven execution guards.
  `root-independent-verification.json` independently rechecks source/packet/input
  hashes and every raw color/depth/stencil/query byte. Earlier failed frames remain
  unchanged. Query timing, presentation and native gameplay stay separate gates.
- `build/metal-poc/use25-pixel-precision-audit/sample-mask-rationale-proof.json`
  binds the original ANGLE control and native output fix to the pinned Apple's
  derivative workaround. The shader fixture suite retains 287 compiled MSL
  variants, 345 pixel cases and 36 exact depth cases with unchanged GLSL.
- `build/macos-metal/native-build-proof/result.json` freezes a host and seven
  ILP32 boundary objects with no GL/ANGLE imports/dependencies. The fixed
  `--renderer metal` build selection preserves the default renderer. The original boundary-only
  result is historical; the complete live frontend now builds and renders menus
  as recorded in `build/macos-metal/live-menu-current/result.json`.
- `build/metal-poc/texture-copy-api-validation/closure.json` verifies 555 original
  texture face/mips through the new backend-neutral CPU mip-copy API. Live native
  uploads and level-zero aliases are implemented; broader alias/mip coverage
  remains open.

- `build/metal-poc/host-frame-native-stage-policy-mad/result.json` freezes the
  corrected 126-draw native query replay. Its 378 actual checkpoints verify the
  fragment compiler contract and native MAD staging in ordered target history.
  All depth/stencil and query results are exact; 96 color checkpoints still
  differ. Input/reference hashes and strict failed color/full-frame gates remain
  intact. The next arithmetic isolation is original use25/program 17/PS8.
- `build/metal-poc/host-opaque-mad-corrected-validation/closure.json` repeats the
  original opaque draw and five atomic preflight guards with the current sources.
  All attachments are exact, with 41,738 visible pixels. This case explicitly
  retains fragment legacy-safe0; it does not hide the full frame's fast-policy
  PS8 differences by selecting policy per use.
- `build/metal-poc/host-actual-draw-query-capable-current/result.json` passes
  strict original opaque color/depth/stencil and five atomic preflight guards
  with the current query-capable backend. Its immutable proof is retained in
  `build/metal-poc/verified-host-actual-draw-query-capable-snapshot/`.
- `build/metal-poc/host-query-api-validation/result.json` passes 26 actual ILP32
  visibility lifecycle/aggregation cases. Original readonly geometry counts
  41,738 samples; two draws count 83,476, including across packets. Ten complete
  attachment/version invariance checks pass. Original CPU timing is unverified.
  After making both query initializers explicit for strict compilation,
  `build/metal-poc/host-query-api-strict-current/result.json` independently
  repeats all 26 cases and attachment checks with the updated source snapshot.
- `build/metal-poc/host-frame-native-query-current/result.json` executes all
  original draws/clears plus Begin/End visibility and checks the captured query
  result at its original GPU-result event: Boolean0 matches exactly. Its 132
  ordered steps, 131 submissions and 378 checkpoints retain packet rederivation
  and actual raw outputs. Attachment, CPU timing and presentation gates remain
  false; matching transport/query does not override the failed image comparison.
- `build/metal-poc/host-transport-visibility-current/result.json` passes the
  existing 17 upload/copy/clear/aspect/lifetime/range cases against the current
  query-capable backend, with hashes checked before and after GPU execution.
- `build/metal-poc/host-integration-visibility-link/result.json` verifies all
  production Mac host sources and original imports link with the query backend.
  This isolated executable does not execute, package or install native gameplay.
  `build/metal-poc/host-integration-stage-policy-link/result.json` repeats the
  production-host link after the separate fragment compiler contract is added.
- `build/metal-poc/verified-fragment-compiler-contract-snapshot/` freezes
  per-key compiler evidence, typed producer/verification guards and the original
  use4 diagnostic. Pinned ANGLE's fragment Fast/Fast/no-invariance options give
  exact color/depth/stencil; safe options reproduce the first six color errors.
  Default legacy packets remain safe; fast policy requires explicit source-bound
  opt-in. Ordered ILP32 validation of that new policy is a separate result.
- `build/metal-poc/vertex-mad-staging-validation/validation.json` verifies the
  narrow native MAD expression staging correction: all 134 original GLSL corpus
  outputs are unchanged; 268 native variants compile; 32 arithmetic and two
  position fixtures pass. The source-bound original use7 proof at
  `build/metal-poc/frame-depth-first-audit/current-mad-staging/closure.json`
  matches all color/depth/stencil and 10,640 captured vertex-output floats.
  The prior six depth differences had identical coverage and came from arithmetic.
- `build/metal-poc/verified-bc23-ilp32-component-final-snapshot/` freezes strict
  BC2/BC3 2D upload/draw comparison against pinned ANGLE: five authored mips,
  all alpha selector/mode cases and both RGB endpoint orders. All native
  color/depth/stencil bytes match. Synthetic coverage and ideal interpolation
  differences are reported separately from original Xbox precision.
- `build/metal-poc/host-frame-attachments-ready/result.json` retains the failed
  first full attachment diagnostic. All 129 packet hashes were independently
  rederived and all 377 readbacks compared. The exact preparation helper was
  recovered after a compatible build-helper change; every recovered byte is
  SHA-identical to the recorded source. No recorded digest was replaced.
  Both attachment/full-frame gates remain false: 117 of 131 color checkpoints
  and 23 of 123 depth checkpoints differ; all 123 stencil checkpoints match.
- `docs/metal-renderer.md` describes the emitter/viewer, tested scope, commands
  and explicit unsupported behavior.
- `docs/metal-reference-comparison.md` records the authored-mip defect and the
  source-backed sky/fog/base-symbol/teleporter work.
- `build/metal-poc/shader-validation/result.json` and
  `build/metal-poc/vertex-validation/result.json` retain native arithmetic,
  compilation and raster fixture results with source/runner hashes.
- `build/macos-capture/live-bloodgulch-complete/` retains the complete original
  shader/use corpus. Its source and binary provenance is under
  `build/macos-capture/provenance.json`.
- `build/metal-reference-20261004/` retains isolated ANGLE camera references,
  original opaque/decal resource captures and source/binary/map hashes.
- `build/metal-poc/sky-fog-decals-teleporters-spawn-640x480.png` and its JSON
  describe preview 0.2. These pixels use the separate viewer's material shaders.
- `build/metal-poc/verified-decal-before-cube-import/snapshot.json` freezes the
  source/binary/package evidence for the original decal's byte-exact color.
  Subsequent emitter/importer changes require fresh validation; this is a
  historical proof, not a claim that every current shader has passed.
- `build/metal-poc/draw-gpu-state-tests/validation.json` records two independent
  native state cases with exact color, depth and stencil, including packed/fixed
  input registers and seeded viewport/scissor/blend/mask behavior. Eight raw
  vertex-fetch tests and seven capture-import tests also pass.
- `build/metal-reference-20261004/hangemhigh-angle-reference/` retains the
  matched-camera original renderer reference for the second map. Its preview
  includes all 176 authored blue-light sections; full lighting remains simplified.
- `build/metal-reference-20261004/ordered-frame-runtime/verification.json`
  verifies the full original frame capture and its 548 guest link inputs.
  Readbacks synchronize diagnostic capture, so original query-result timing
  is not established. Unsupported copies/mipmap/atomic-query cases explicitly
  invalidate capture rather than supplying stale CPU attachment bytes.
- `build/metal-poc/host-transport-draw-validation-current/result.json` verifies 17 native
  transport cases through actual rebased ILP32 import stubs on the M5 Max.
  It binds the source, compiler plugin, guest image and native host hashes.
  The executable links Metal without GL/ANGLE; these cases exercise resources
  rather than original game draws. SDL presentation remains unverified.
- `build/metal-poc/host-integration-draw-link/result.json` records a successful link
  of the complete production Mac host with the four native services. No app
  was packaged or installed. The existing Homebrew SDL dependency's macOS26
  deployment warning remains a distribution compatibility limit.
- `build/metal-poc/host-actual-draw-preflight-current/result.json` records an
  original opaque draw through the actual rebased guest import boundary and
  shared native encoder. All color/depth/stencil bytes match the independent
  ANGLE reference. Five malformed later draws reject the complete batch before
  an earlier clear can change attachments, versions, resources or sequence.
  Host process exit zero is required. Root independently reran the strict
  comparator; the result is `comparison-root-verified.json` beside the proof.
  Its immutable source/binary/package is preserved under
  `build/metal-poc/verified-host-actual-draw-preflight-snapshot/`.
- `build/metal-poc/shared-draw-encoder-validation.json` verifies synthetic
  LOAD/STORE history, depth/stencil/write masks, scissor, constant blend,
  reflected bindings, invalid state/buffers/indices and cache eviction.
- `build/metal-poc/frame-replay-420-current-verified/` preserves the hardened
  138-command/126-draw package and verifier audit. Root independently verifies
  this package. Forged state, read-only query flags, source hashes and substituted
  shaders reject; after-operation reference bytes remain comparisons only.
- `build/metal-poc/draw-replay-opaque-viewport-corrected/comparison-root-verified.json`
  verifies exact opaque color/depth/stencil with direct NV2A shaders,
  original packed streams, runtime palette/cube resources and the source-bound
  vertex compiler contract. No translated ANGLE shader is used by this replay.
  Its immutable source/binary package is retained under
  `build/metal-poc/verified-opaque-viewport-corrected-snapshot/` before further
  native cube upload work changes source hashes.

The first complete-frame import exposed BC1 cube resources that isolated draws
had not exercised. CPU retention and independent native cube block/face/mip
checks now pass, including exact sampled output against the working ANGLE port.
Unsupported formats remain explicit failures. The hardened frame verifier
reconstructs normalized state, read-only query flags, shaders and resources from
the frozen original capture and rejects forged metadata or stale sources.
Full-frame capture/preparation completeness is not native frame replay completeness.

Build artifacts and the user's game assets remain ignored. Evidence filenames
identify where to inspect a result; the existence of a filename alone is not a
passed gate. Revalidate hashes against current sources before using old results.

## Actual draw result and next acceptance gate

The first original draw uses the runtime's 12 packed vertices, original shader
keys and fixed registers, 192 vertex constants, exact draw uniforms, original
sampler/raster state and seven authored BC1 mip levels. The native executable
links Foundation and Metal, with no GL/ANGLE linkage. A cleared-target draw from
an outside-base camera produces nonzero pixels and passes byte-exact RGBA8
comparison over the complete 640x480 target.

The first failed comparison exposed a reference readback metadata error. The
working renderer's screenshot writer stores GL readback rows directly in a
top-down BMP (`d3d8_gl.c`, comment `rows from the top, as read`); its presentation
blit explicitly accounts for the internal D3D top-left row convention. The
diagnostic adapter had instead labeled those rows as logical bottom-left and
reversed them. The corrected adapter retains the original raw bytes unchanged.
The failed metadata/result attempt remains preserved; no shader or asset change
was used to obtain equality.

This result does not close attachment precision or preceding-frame history. The
opaque capture now exercises original depth writes and retains independent
before/after depth/stencil evidence. Direct safe-math replay exposes small
vertex/compiler differences. A diagnostic using actual ANGLE vertex MSL with
the native fragment shader matches all attachments exactly, isolating the
remaining regression to vertex arithmetic. That diagnostic does not replace
the direct Xbox instruction emitter. The subsequent direct correction stages
the inverse viewport arithmetic explicitly and selects the pinned original
vertex compiler contract per program; it passes the strict opaque attachment
comparison. Fragment/default fixture policy remains separately controlled.

The complete ordered frame capture is also retained. Its native replay now
executes every captured draw and GPU visibility operation through the verified
guest/host transport. Its color/depth/stencil and query checkpoints now match
exactly after the source-backed Apple derivative workaround. The live adapter
has frozen menu and bounded scripted Blood Gulch/Damnation movement/firing passes,
with original world, weapons, bullet decals and HUD. Original volume-lighting
draw comparison and manual firing, matched-camera
water parity, interactive playtesting, alpha-border/nearest-LOD precision and
full missions and content transitions remain open. Corrected frozen 125 now
passes all 23 fresh stock openings with separately bound source/execution and
scene evidence; the earlier f69b seven-of-ten campaign result remains failed.
The historical125 transition failure remains retained. Later fixed-loading
build `1fc22efa…` completes four alternating changes with separately reviewed
gameplay images, while its producer global passed remains false. Its intended
unlit/immediate loading component passes explicit exact/gradient controls;
complete original loading pixels, strict stale payloads, physical SDK timing and
general transition coverage remain open. A separate Hang Em High opening
supports the third current experimental launcher. All 23 openings remain
frozen 125 evidence rather than a full 1fc22 rerun; older launchers stay unchanged.
The current 378-checkpoint replay and 45 synthetic unequal-attachment readbacks
remain bounded correctness proofs, as documented in `docs/metal-game-adapter.md`.
The user's roof/downward base-symbol clipping remains unresolved. The focused 16
GPU closure `build/metal-poc-0.6/roof-depth-focused-prepared-attempt3/independent-audit/closure-v2.json`
(`bafdabfb…`) measures small edge rejection at one synthetic roof pose: 20 nonzero
RGB losses at 640×480 and six at 1280×720. Actual raster/stored glyph depth and
copied/fetched opaque depth agree; LEQUAL query counts match float32 comparisons.
Original static-shader and invariant variants are byte-identical. This does
not establish original ANGLE/Xbox correctness, the user's exact reproduction
or a fix. Earlier 70 recorded-pose controls with zero RGB loss remain separate;
no unsourced geometry/depth-bias/shader change is established.

The later exact-camera static replay closes ten GPU captures against fresh
original ANGLE frame 480 (`roof-actual-camera-replay-prepared-attempt1`, independent
closure SHA `6cc6a468…`). Neither control has glyph depth loss at that exact
matrix. The captured original viewport bridge matches all 724 visible glyph
contribution pixels; direct static matrix arithmetic differs at 67 pixels.
Rounded composition remains unequal at one pixel/channel byte. No production
fix is established. The subsequent human native-game playtest reports a visibly
speckled glyph at sniper 10× zoom, which requires its own live draw/camera
comparison. F5 capture is currently implemented only in the scene viewer.
Complete gameplay, original Xbox precision, visual-pass coverage, asynchronous
query timing, presentation and performance remain distinct requirements above.

Capture one visible original draw on an independently cleared attachment,
retaining the original shader, resource, sampler, uniforms and draw state. State
the isolation scope explicitly: this first comparison does not reproduce the
preceding frame's depth/stencil/color history. Use the same capture package for
the independent ANGLE reference and the generated native NV2A shaders.

The native result must retain the input manifest, source, executable and payload
hashes, dimensions, row orientation and actual attachment formats. Compare all
pixels, report coverage differences and errors without hiding them through
exposure, gamma, UV or asset changes. Record differences in depth attachment
precision explicitly. Then extend the package to complete attachment history
and ordered frame replay; a single passing draw cannot close the full-frame gate.
