# Direct Xbox rendering on Metal

The target is the existing Xbox-derived Halo engine driving native Metal on
macOS, with original gameplay, assets, lighting and presentation. The 30 Hz
simulation remains the reference. Higher resolution and render frequency are
separate performance experiments; they must preserve animation, input/camera
timing, weapon behavior and network behavior.

The current game path is Xbox D3D8/NV2A state → GLES → ANGLE → Metal. This branch
adds direct NV2A vertex-program and pixel-combiner generation in Metal Shading
Language. Both emitters share the existing instruction/state decoding with the
GLES emitters. There is no OpenGL context or ANGLE linkage in the native shader
validation executable. The game's renderer selection has not changed.

## Current experiment

The `tools/metal_poc.py` scene viewer remains a separate preview. It
extracts static map geometry and approximates materials; its captures and timing
cannot establish full-game fidelity or a gameplay performance improvement.
Blood Gulch ground relies on diffuse sand, grass and micro-detail layers, at
material scales 100, 60 and 12; its bump-map reference is empty. The initial
base-texture/lightmap-only preview omitted those layers, making the ground
look smooth. The viewer now binds all three detail layers and follows the
original material blend masks, functions and per-axis scales. Thirty-three
independent native GPU material cases passed, and matched-camera captures show
the restored grass/sand grain. Original screenshots remain preserved;
`ground-details-first-person.png` and `ground-details-overview.png` contain the
new captures. The subsequent wall-pattern comparison found that regenerating
mipmaps lost Halo's authored detail fade. The exporter and native uploader now
preserve the original hardware-visible mip levels. See
[the ANGLE comparison](metal-reference-comparison.md) for captures, evidence
and remaining differences. Cliff bump lighting remains a separate requirement,
and BSP cutouts still approximate the original lightmap/depth pass.

The viewer now also extracts Blood Gulch's actual sky model and its five
material parts, including the moon and surrounding background. Atmospheric fog
uses the original sky distances, packed warm color/density and the game's AY8
density lookup. Permanent red/blue Forerunner base signs are projected and
clipped against the map's collision surfaces with the original additive blend.
The two active-BSP scenario teleporters use the original model, textures and placement
rotations, including their animated plasma and dust material combiners. Their
P8 bump texture supplies the original opaque alpha-test mask. All these assets
come from the same Xbox map; no replacement artwork is used.

The visible glowing base symbols are separate transparent BSP materials, not
the permanent ring decals. An isolated ANGLE capture with all decal draws
disabled still contains those symbols. The viewer now includes all 44 authored
transparent BSP sections: base lights, moss/green lights and teleporter shields.
They preserve the original bitmap permutations, additive blending, view/fog
fade, culling and authored decal bias. Independent GPU checks passed 192
selector/fade cases and 24 render compositions.

The integrated scene contains 41 opaque, five sky, eight decal, 44 transparent
BSP and four transparent teleporter draws, with 59 textures and 312 authored mip
levels. All Blood Gulch BSP material sections are supported in this subset.
Preview 0.6 samples the original compressed blocks for 22 BC1 textures and
writes ANGLE's Apple fragment sample-mask workaround. Painted-decal culling
and inactive teleporter filtering remain corrected. Eight settled roof views
match the visible symbol shape; intermittent user-reported clipping is still
unreproduced. See `docs/metal-reference-comparison.md` for the scoped evidence.
The static viewer still simplifies BSP bump/radiosity and object lighting, and
does not include the remaining scenery, gameplay objects, particles or HUD.
Its interactive teleporter animation advances with elapsed time; captures can
freeze it with `--time SECONDS`.

Build the local viewer with a user-owned Xbox map:

```sh
python3 tools/metal_poc.py --map /path/to/bloodgulch.map --open
```

Drag to look, use WASD to move and Q/E to change height. Hold Shift for faster
movement. T jumps to the teleporter inspection camera; R resets to spawn.
The native executable also accepts `--teleporter` for repeatable close captures.
For matched camera comparisons, use `--camera X Y Z YAW PITCH`; angles are
radians. The camera is recorded in the capture's JSON sidecar.
Press F5 in the interactive preview to save the current image, camera, drawable
dimensions and frozen animation time to the `captures` folder beside the app.
Each capture has a unique filename and a JSON sidecar for replay.

### Native game guest/host transport

`port/macos/include/halo_metal_abi.h` defines a GL-independent fixed-width
command ABI for the existing ILP32 guest. The Mac host now builds and resolves
its four native Metal imports. Packet-relative data is copied before encoding;
resource IDs carry monotonic lifetime generations. Validation rejects an
unsupported batch before GPU mutation. GPU execution failure invalidates the
context until shutdown.

The executor supports native RGBA8/BGRA8 and float32 depth/stencil targets,
padded uploads, ordered copies, full/scissored clears and aspect readbacks.
It also accepts generated NV2A programs and immutable original draw inputs via
the shared draw encoder. Extended uploads retain every authored mip and cube
face, including BC1 blocks and separate initial depth/stencil seeds. Original
BC2/BC3 blocks and authored mips are supported for 2D and cube sampled textures;
their real ILP32 upload/draw fixtures match pinned ANGLE exactly. The cube
fixture covers all six faces at five authored mip levels, including alpha
selectors and both RGB endpoint orders. Compressed volumes still reject. Each used
subresource must be initialized; unsupported formats remain explicit failures.
SDL layer ownership is exclusive with EGL. Its exact-size BGRA presentation
path compiles but has not been tested by the offscreen transport probe.

```sh
python3 tools/metal_host_validate.py --rebase-plugin /path/to/guest_rebase.dylib
```

The probe compiles a real 32-bit guest, generates the production import stubs,
enters it on a rebased guest stack, and checks native GPU outputs against
independent CPU expectations. Seventeen cases cover row pitch, channel order,
scissor bounds, attachment-aspect preservation, sequential resource versions,
generation reuse, undefined content, invalid batches and inaccessible memory.
Source/binary hashes and limitations are saved with the result.

The draw capability is now exercised by a captured original opaque draw through
real rebased imports: all 307,200 color/depth/stencil pixels match the independent
ANGLE reference exactly, including 41,738 visible pixels. The expected
after-target images are comparisons only; they are never native GPU uploads.
See [the encoder contract](metal-native-draw-encoder.md) for state, compiler
policy, attachment history and remaining query/format limitations.

The transport also supports typed Boolean/counting visibility queries. Native
results accumulate across queried draws without changing the attachments, and
26 actual ILP32 lifecycle, aggregation and atomic-validation cases pass. These
raw completed GPU values do not establish the game's cached polling behavior.

A frozen attachment-only replay has executed all 126 original Blood Gulch
draws and two clears with persistent target aliases. It compares 377 actual
color/depth/stencil checkpoints. The first difference appears at event7/use4:
six pixels differ by one channel value. Later color and depth differences also
remain; stencil is exact. Its strict attachment and full-frame gates fail.
Visibility events were excluded explicitly from that first diagnostic. A later
native-query run includes the original query geometry and Begin/End/result
events: its Boolean0 matches exactly, for 378 total checkpoints. Attachment
differences remain, and original CPU query timing/presentation are unverified.
The latest source-bound replay includes the separate original fragment compiler
policy and staged native vertex MAD arithmetic. It matches every depth/stencil
checkpoint and query result, plus the first 26 color draws. Remaining color
differences begin at use25/program17; final color differs at 307 of 307,200
pixels, so the strict attachment gate still fails. The live native game adapter
has not yet replaced the game's frontend; see [the adapter requirements](metal-game-adapter.md).

The game's D3D frontend still draws through ANGLE. Native completion remains
synchronous, presentation is unverified, and physical Xbox D24/F24 storage
precision is not established by these float32 attachment tests. One imported
draw and an executed diagnostic frame are not complete native gameplay.

World clipping matches the Xbox camera's near 1/16 and far 1024, with clockwise
front faces, back-face culling and LEQUAL depth. Captures record executable,
scene and shader hashes, clip ranges and pass state.

Hang 'Em High is also supported as a separate static preview. Its original
sky uses the same supported material shapes, and its 176 blue-light BSP sections
retain the original additive shader and authored mip chain. Region selection
checks the actual sky permutations and all five LOD references; unsupported
alternates cannot silently render extra geometry. Build it without replacing
the Blood Gulch bundle:

```sh
python3 tools/metal_poc.py --map /path/to/hangemhigh.map \
  --output-directory build/metal-poc/hangemhigh --open
```

Battle Creek's planar fog/water and Sidewinder's four-map Chicago sky remain
unsupported in this viewer. Full world/object lighting remains a requirement
for both supported preview maps.

`tools/metal_shader_validate.py` validates the shader foundation:

- Compile all 67 immutable checked-in Xbox vertex programs, with unpacked and
  packed normal attribute variants.
- Check that existing generated GLES sources remain byte-for-byte identical.
- Render independent combiner, texture sampling, alpha and fog expectations on
  the Metal GPU, with full float output so numerical differences remain visible.
- Compile optional shader keys captured from a running game frame.
- Reject unsupported instructions/states instead of substituting an approximate
  result. Report those rejections separately from successfully compiled keys.

Vertex output preserves the Xbox half-pixel correction and signed viewport
scale. Native Metal depth is 0–1, so the GLES depth conversion is omitted. The
Metal path uses invariant vertex position and disables fast math in validation;
invariance matters to multipass depth comparisons. See Apple's
[viewport coordinate description](https://developer.apple.com/library/archive/documentation/Miscellaneous/Conceptual/MetalProgrammingGuide/Render-Ctx/Render-Ctx.html)
and [compiler invariance option](https://developer.apple.com/documentation/Metal/MTLCompileOptions/preserveInvariance).

Existing GLES semantics are a regression reference, not a retail Xbox oracle.
The independent [xemu NV2A implementation](https://github.com/xemu-project/xemu/blob/478b4f496102379c7eaa7f3ec10e714a703c4300/hw/xbox/nv2a/pgraph/glsl/psh.c)
also informs checks of texture-stage behavior. Differences identified during
this experiment require explicit native-path tests and eventual reference
captures. No emulator code is copied into the emitter. Native-only corrections
include NONE texture alpha, unclamped passthrough, texture-stage selection and
signed B/G bump offsets, R-channel bump luminance across RGBA, final-combiner
SUM/clamp behavior and truncation for the LSB mux.

The emitter rejects BRDF, DOT_ZW depth replacement, constant-eye reflection,
HILO dot mappings, missing/mismatched texture types and unsupported stage
ordering. Signed dot inputs, uncertain signed bump-luminance combinations and
sample counting also fail explicitly pending numerical/reference coverage.

## Verified on Apple M5 Max

The native validation run compiled 269 shader sources: 134 variants from all
67 checked-in vertex programs, 69 fixture pixel keys and 66 configurations from
an actual offline Blood Gulch frame. All 22 captured vertex variants and 44
pixel keys compiled, covering the shader pairings of all 262 captured draws.
Capture import verified its complete status, counts and draw references.
This validates shader coverage, not replayed game pixels.

159 independent pixel cases passed (15 discards); maximum float error was
`5.9604645e-8`. Separate vertex validation passed 32 arithmetic and two native
render cases, with 640 compared components, no nonfinite values and maximum
absolute error `1.1920929e-7`. These include screen orientation, pixel centers,
0–1 depth and the near-camera RCC path. Existing GLES generation was unchanged
for 203 fixture/program variants and the 66 actual captured configurations.
Malformed/incomplete capture tests and stale GPU-result rejection also passed.

Reports:

- `build/metal-poc/shader-validation/result.json`
- `build/metal-poc/vertex-validation/result.json`
- `build/metal-poc/corpus-regression/result.json`
- `build/macos-capture/provenance.json`
- `build/macos-capture/live-bloodgulch-complete/run.json`

The capture guest combines the already-built primary game object cache with
isolated rebuilt shim objects. Its object/binary/source provenance is retained;
it is not a fresh full engine rebuild. Runtime data and saves are isolated with
read-only map symlinks. The first diagnostic run appended to the primary asset
`debug.txt`; subsequent runs write only under the experiment's build directory.
No primary source, installed app or renderer selection was changed.

## Running the shader checks

```sh
python3 tools/test_metal_pixel_shader.py
python3 tools/test_metal_vertex_shader.py
python3 tools/test_metal_shader_capture.py
python3 tools/metal_vertex_validate.py
python3 tools/metal_shader_validate.py
```

The last command needs GPU access. It uses Apple's runtime Metal compiler, so
the optional command-line Metal Toolchain is not required. Results and generated
shader sources live in `build/metal-poc/shader-validation`. No game data is needed.
For a restricted shell, prepare first, then run the native executable in a
GPU-enabled session and consume its JSON:

```sh
python3 tools/metal_shader_validate.py --prepare-only
build/metal-poc/shader-validation/shader_validate \
  build/metal-poc/shader-validation/manifest.json \
  > build/metal-poc/shader-validation/gpu-result.json
python3 tools/metal_shader_validate.py \
  --gpu-result build/metal-poc/shader-validation/gpu-result.json
```

The native runner verifies hashes of the generated shader sources and its own
executable. The report verifies that the GPU result belongs to the current
manifest; an older result cannot validate newly generated sources.

## Capturing shaders from the game

`HALO_MACOS_METAL_SHADER_CAPTURE` is a compile-time switch, defaulting to zero
in `d3d8_gl.c`. Enable it only for the guest build in this experiment. It is not
an application environment variable. Existing `debug.gpu_trace_frame` selects
one frame at runtime. Captures go beneath the isolated save root:

```text
metal-shaders/frameN/vertex-NNNN.json
metal-shaders/frameN/pixel-NNNN.json
metal-shaders/frameN/uses.jsonl
metal-shaders/frameN/status.json
```

The capture records original vertex instruction words, packed attribute masks,
complete normalized pixel shader keys and the actual program/declaration pairing
of each draw. Fields are serialized as numbers with explicit 32-bit shader words;
guest pointers and native structs are not written across the ABI boundary.
Repeated runs preserve earlier captures. The completion record is committed
only after shader/use writes close successfully. The importer requires complete
status, exact shader/use counts, matching ids and fixed-width input ranges;
truncated or malformed instruction arrays cannot cross the native boundary.
Shader capture deliberately omits
texture/geometry bytes and uniform values; it validates shader coverage, not
rendered frame equivalence.

```sh
python3 tools/metal_shader_validate.py --corpus /path/to/metal-shaders/frameN
```

## Remaining work and acceptance gates

The [full port verification ledger](metal-port-progress.md) keeps implementation
and verification status for the complete native-game goal. The static viewer
and shader fixtures do not close the gameplay, full-frame or Xbox-reference gates.

One actual game draw now runs directly through generated NV2A Metal shaders:
the captured program2/declaration2 decal, 12 packed vertices and seven authored
BC1 mip levels. Independent ANGLE and native color readbacks match exactly over
all 307,200 pixels, including 3,868 visible pixels. The scoped target is cleared
before the draw; previous frame history is omitted. The ANGLE capture does not
yet supply depth/stencil readbacks, and native depth precision needs separate
verification. This is a color replay milestone, not complete-frame or Xbox parity.

The importer and replay commands are:

```sh
python3 tools/metal_draw_replay.py /path/to/captured_draw.json \
  --output build/metal-poc/draw-replay
clang++ -std=c++17 -O2 -fobjc-arc -Wall -Wextra \
  port/macos/metal-poc/draw_replay.mm -framework Foundation -framework Metal \
  -o build/metal-poc/draw-replay/draw_replay
build/metal-poc/draw-replay/draw_replay \
  build/metal-poc/draw-replay/replay.json build/metal-poc/draw-replay/native
python3 tools/metal_draw_compare.py \
  --manifest build/metal-poc/draw-replay/replay.json \
  --reference /path/to/reference-result.json \
  --native build/metal-poc/draw-replay/native/result.json \
  --out build/metal-poc/draw-replay/comparison.json
```

The comparison rehashes capture, corpus, sources, executable and payloads,
compares spatial coverage and every RGBA byte, and rejects blank-only references
as visible-draw proof. All attachment comparisons and nominal depth format
differences remain explicit in the report. The first failed reference-row
metadata attempt is preserved alongside the source-backed correction; shader
output and original raw pixels were unchanged.

The next rendering milestone adds original opaque depth writes and independent
attachment readbacks. Then
replay a complete ordered frame, including clear/target changes, first-person
weapons, HUD, effects, shadows and water. Texture/render-target aliases and
resource changes at the same physical address must be versioned correctly.
The active program and vertex declaration are separate inputs.

Complete-frame checks must cover depth/stencil, blend/color masks, pixel centers,
winding/scissors, mipmaps, texture formats/swizzling, cube/volume textures,
dependent reads, signed channels, fog, alpha and render-to-texture passes.
Sample-count visibility and its result timing need their own checks: the current
Mac fallback approximates some lens-flare counts, so preserving that fallback
does not establish Xbox accuracy. Present/vblank pacing must also be preserved.

Use matched cameras and settings at 640×480 for reference comparison. Add stock
multiplayer maps and representative campaign scenes, then split-screen and
effects. Compare against the current backend first and original Xbox NTSC
captures before claiming complete original appearance or feel. Record any
remaining differences, rather than relaxing the fidelity target silently.

Measure complete-frame CPU/GPU times, upload bytes, memory, sustained frame
delivery and input age for identical workloads after correctness passes. Shader
compile success or isolated preview timings do not prove a game speedup. Higher
resolution/refresh trials follow the reference comparison and retain the
original simulation. This branch has not replaced the installed game.
