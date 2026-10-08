# Blood Gulch: ANGLE reference versus native preview

The installed game and this preview both run on Metal. The installed game's
runtime reports OpenGL ES 3.0 through ANGLE's Apple M5 Max Metal renderer. It
preserves the game's Xbox-derived material and draw passes; this static viewer
extracts BSP geometry and uses a simplified diffuse/lightmap shader. Shader
arithmetic tests alone cannot establish appearance equivalence between them.

Preview checks are opt-in, outside ordinary `test_*.py` discovery. Select the
relevant modules below; GPU cases require macOS/Metal, native-loader checks need
the Mac toolchain, and stock-asset cases require user-owned maps. The separate
ILP32 check needs LLVM 22 and configured guest musl headers but uses no GPU.

```sh
PYTHONPATH=tools python3 -m unittest \
  check_metal_scene_loader check_metal_scene_materials check_metal_sky \
  check_metal_fog check_metal_teleporters check_metal_transparent_bsp
python3 tools/check_metal_vertex_fetch_ilp32.py
```

Historical source-preservation audits require their original retained `build/`
evidence; the fixed-loading audit also requires NumPy. Their hashes deliberately
bind old investigations and must not be refreshed to accommodate current source
changes. Run one explicitly when auditing that evidence:

```sh
python3 tools/audit_metal_fixed_function_validate.py
python3 tools/audit_metal_roof_angle_prepare.py
python3 tools/audit_metal_roof_depth_validate.py
```

## Reference and camera

The reference is the user's installed `/Applications/Halo OG.app`, build 16,
source `41c4aa82f67d7934488439c14dee39934ab6fe7f` with local changes. Its guest
hash is `815483ed0e453d7406e2af6f2fa6af53a8f1fda8719c878cf24438b9d3c45ae1`.
The exact installed host/guest were run with isolated logs and saves; the app,
primary checkout and game map were not modified.

Both spawn and overview references use the same map hash, camera position,
forward/up vectors, 640×480 image dimensions and 65-degree effective vertical
field of view. Saved game camera values and frame-240 GPU projection constants
confirm the match within the game's float/trigonometry approximation. Xbox
observer FOV is 80.69094 degrees for this comparison; its projection makes the
effective vertical FOV 65 degrees. Setting both APIs to a raw FOV of 65 would
produce different cameras.

Full camera, matrix, configuration and binary/image hashes are retained in
`build/metal-reference-20261004/clean/comparison.json`. There are residual
occlusion/framing differences, and the ANGLE score-help overlay remains. These
captures demonstrate material differences, not pixel-identical frame parity.

## Proven texture defect and correction

The cliff's `cap_cliff01b` material uses primary cliff detail at scale 8 and
micro detail at scale 60. Its blend functions, masks and UV scales agree with
the original packed environment combiner state and emitted GLSL. Independent
checks across 27,000 sample combinations found no RGB equation difference.
Bitmap selection also agrees for the cliff: permutation zero, one bitmap per
group. The ground has different detail layers and no bump-map reference.

The preview initially decoded only mip zero, then used Metal's mip generation.
That replaced Halo's deliberately authored distance fade with ordinary image
reduction. Original primary cliff detail fades toward neutral: red-channel mean
about 160.77 at mip zero, 138.06 at mip five and 133.44 at mip six. Generated
reductions retain approximately the original mean. Original micro detail is
spatially flat by mip five, while generated mips retain visible noise. This
kept repetitive wall patterns and extra brightness at a distance.

The original fade is described in `source/bitmaps/bitmap_extract.c:1677`, and
the working renderer uploads the authored chain in
`port/linux/src/xbox_textures.c:606`. Ablations at an unchanged camera showed
that removing micro detail barely affected the coarse wall pattern; removing
primary detail changed it strongly. Uploading the original chain reduced the
excessive repetition while retaining both original detail layers.

The exporter now decodes every hardware-visible authored level, including
Morton layouts, DXT blocks and linear row padding. It respects the original
compressed mip cap, including rectangular levels: cliff base ends at 2×4,
primary/micro detail at 4×4. The native uploader validates each level and uploads
the exact bytes/count; it never generates replacements. BSP bitmap permutations
are also propagated correctly, with lightmap selection kept separate.

The rebuilt preview loaded 43 textures and 210 mip levels on the M5 Max.
Twelve exporter tests and nine native-loader tests passed, including a level
whose bytes intentionally differ from any reduction of mip zero and rejection
of incomplete chains. GPU captures completed at both 640×480 and 1280×720.

## Sky, haze, base signs and teleporters

The missing moon and background were the omitted sky-model pass. The viewer now
loads the five original sky parts, preserves their material combiners and alpha
blend, and follows the original camera-relative model transform. Blood Gulch's
haze is atmospheric fog: warm packed color, density 102/255 and distances 3–100,
sampled through the original 16×16 AY8 density texture. It is based on camera
forward distance rather than Euclidean distance. This map has no planar fog.
The original clear color `(255,230,196)` is also preserved for uncovered sky
pixels; a matched overview capture verifies the same color in both renderers.

Eight permanent scenario ring decals use original red/blue textures. They are
projected onto and clipped against collision surfaces, then added to the
framebuffer with fog attenuation. The prominent white/red base glyph is a
different material: an emissive transparent BSP light. Disabling all permanent
decal draws in the original ANGLE renderer leaves that glyph unchanged.

The viewer now includes all 44 transparent BSP sections previously skipped:
base lights, moss, green lights and two teleporter shields. The base lights use
the original one-map/no-explicit-stage passthrough and additive blending. BSP
shields use the seven-stage plasma selectors with their original upper colors;
scenery's outgoing-animation input instead selects lower colors. Moss/green
decal materials additionally receive the original later atmospheric fog
attenuation. Independent GPU checks cover 192 selector/fade cases and 24 native
render compositions. The restored native spawn capture displays the original
bright base symbol.

The active
teleporters are scenario scenery placements using the original model and its
opaque environment, animated plasma and dust materials. The plasma uses the
original seven combiner stages, animation periods and rotation scale; its
transparent contribution uses the original view-angle and fog fade. The opaque
alpha-test mask comes from the model's P8 bump texture rather than its base map.

The rebuilt scene has 107 draws, 6,279 triangles, 59 textures and 312 authored mip
levels. Full-scene PNG captures and their `.png.json` provenance files use the
`sky-fog-decals-teleporters-` prefix in `build/metal-poc`. These show the integrated
passes; separate shader arithmetic checks also cover fog, sky and teleporters.
Two close teleporter captures at animation times 0 and 2 change 4,539 pixels
within the teleporter's glow, with the rest of the image unchanged. T in the
interactive viewer selects this camera.

Resource capture verified all 11 observed original opaque vertex streams against
the exact cache bytes and their index lists against cache surface subsets.
The original base-wall and ring-decal support surfaces are both drawn; they
share a visible subcluster and material with alpha testing disabled. Neither
PVS changes, replacement artwork nor moving a decal through the wall is needed
to restore the visible glyph. The missing transparent BSP pass explains it.
World projection now uses the original near 0.0625/far 1024 and LEQUAL depth;
capture metadata records these values and the native executable hash.

## Preview 0.4 placement and decal corrections

The 0.2 preview incorrectly included scenery placement 24, a tilted teleporter
stored at `(65.905907, -121.437584, -0.237021)`. Its active-BSP membership is
zero. The original runtime recomputes membership by testing the placement and
transformed bounding-offset point against the collision BSP before creating
scenery. An independent float32 traversal returns no leaf for placement 24;
the bounding offset is zero, so its second test is identical. Placements 27
and 28 return valid leaves and remain unchanged. The exporter now respects
the active BSP bit and renders those two placements only. The audit, map hash,
original source contracts and traversal evidence are in
`build/metal-reference-20261004/teleporter-membership-report.json`.

Permanent decals previously used no face culling. The original decal pass
discards counterclockwise faces, so the preview now uses clockwise fronts
and back-face culling. The exported polygon fan's winding agrees with the
independent original captured decal geometry. The original texture, additive
blend, depth comparison, normal offsets and depth bias are retained.

The glowing white/red base symbols are transparent BSP geometry, not the
permanent decal pass. Their source specifies zero bias, LEQUAL, no depth
writes and additive RGB. A position-invariance ablation across seven camera
poses produced byte-identical images; it did not reproduce or resolve the
reported intermittent clipping. Do not treat the permanent-decal culling
correction as proof that this separate clipping issue is fixed.

An independent GPU texture probe sampled all nine red-atlas mips using nearest,
bilinear and trilinear filtering. The preview's CPU-decoded RGBA differs from
native sampling of the original BC1 blocks by at most 3/255 in RGB, with average
errors below 0.6/255; alpha is exact. This small decoding difference cannot
explain disappearing geometry. The hashed input and 419,156-sample results are
in `build/metal-poc/bc1-decoder-probe/comparison.json`.

Preview 0.4 captures at spawn, overview and the teleporter inspection camera
completed on the M5 Max with two placements, 102 draws and 6,095 triangles.
The seven teleporter tests passed, including independent collision membership,
240 original shader/animation cases and 24 additive render compositions.

A separate matched roof-camera test through the unchanged installed ANGLE
renderer and a frozen 0.4 native bundle preserves the same full glowing symbol
shape. It does not visibly reproduce additional native clipping at that pose.
An analytical intersection between one glyph corner and its slightly nonplanar
support wall falls outside the bright texture region in this view. Camera
rounding and a small residual roll limit subpixel comparison, so this is not
an exact GPU coverage or depth-parity claim. The paired images, source hashes
and camera provenance are in
`build/metal-reference-20261004/glyph-clipping-pair`.

Preview 0.5 adds F5 capture of the current image, full drawable dimensions,
camera position/yaw/pitch and frozen animation time. PNG and JSON files go into
the `captures` folder beside the app, preserving the precise user view needed
to reproduce an intermittent clipping report.

## Preview 0.6 texture and Apple derivative corrections

Preview 0.6 uploads the original BC1 blocks for all 22 DXT1 textures, including
the base-sign atlases. The decoded RGBA files remain diagnostic assets; Metal
samples the authored compressed blocks and all 312 authored/fallback mip levels
are retained. Geometry, UVs, placements, blend/depth state and depth offsets
match preview 0.5. The exporter/loader's 28 CPU tests and 20 preview GPU tests
passed. The bundle is `build/metal-poc-0.6/Halo Metal POC.app`, with source and
artifact hashes in that directory's `source-closure.json`.

The fragment outputs now write an all-ones sample mask, matching pinned ANGLE's
Apple GPU workaround. ANGLE's `mtl_features.json` explains that some GPUs produce
incorrect derivatives unless this output is written. Independent original-draw
tests locate a real native sampling discrepancy resolved by this change;
the general NV2A emitter and all five preview fragment passes use it. This is
not evidence that the user's intermittent base clipping is fixed.

The roof report was narrowed to looking down from the base. Eight further
original ANGLE/native comparisons allow the original camera 2.5 seconds to
settle and replay its saved position, direction and FOV. The independent bright
symbol audit finds no substantial native-only interior holes; residual edge
differences, rounded camera vectors and small roll differences remain explicit.
The all-ones mask ablation is pixel-identical in those eight preview views.
No geometry or depth-bias change is justified by this unreproduced report.
Retained evidence is in `build/metal-poc-0.6/roof-settled-comparison`, including
`coverage-audit.json` and `sample-mask-ab.json`. The initial shorter-settling
comparison is preserved separately and documents its camera/provenance limits.
F5 continues to record the exact current view for an intermittent reproduction.

The later roof probe measures actual stored glyph and opaque depth at a synthetic
downward pose. It finds 20 dim-red edge losses at 640×480 and six at 1280×720;
position invariance changes no measured bytes. A fresh original ANGLE frame 480
then supplies the exact camera, frustum and vertex constants for a ten-case
static replay. At that exact matrix neither static control has depth rejection.
Adding the original captured viewport/pixel-center stages makes the contribution
mask match all 724 original glyph pixels; direct static matrix arithmetic differs
at 67 pixels. Rounded composition still differs at one pixel/channel byte, so
this is not exact color parity or a clipping fix. No production geometry, bias or
shader change was made. The closed pair and its limitations are retained in
`build/metal-poc-0.6/roof-actual-camera-replay-prepared-attempt1/independent-comparison-attempt1/`
(`closure.json` SHA `6cc6a468…`).

The subsequent human native-game playtest reports a visibly speckled base glyph
through the sniper's 10× zoom. This is a separate actual-game reproduction from
the static roof controls and remains unresolved. F5 capture currently belongs to
the scene viewer; it is not wired into the native game playtest. A matching live
camera/draw capture is still needed before attributing the speckling to depth,
sampling or another render stage.

## Remaining appearance differences

The cliff has an active bump map at scale 40×40. The original lightmap pass
uses that normal and an incident-direction lookup to modulate radiosity before
the diffuse pass. Multiplying diffuse color by the raw lightmap does not
reproduce this lighting. This cliff's specular/reflection brightness is zero;
those terms are not the explanation for this particular comparison.

The preview still omits other scenery/objects, dynamic decals and effects,
and other ordered lighting/depth operations. Object lighting remains simplified,
and the sky's cloud/UV animation is not yet active. Authored mips and the restored
sky/fog/decal/teleporter passes do not make the static viewer a complete original
renderer.
The earlier material tests covered arithmetic, not mip chains or complete
lighting/fog, and therefore did not catch this image discrepancy.

Further fidelity work must use the engine's actual streams, textures, uniforms,
shader programs, blend/depth state and ordered passes in Metal, with ANGLE frame
comparisons. Hand-adjusting brightness or texture strength would obscure the
missing original behavior. Performance comparisons follow matched complete
frames rather than these static-preview timings.

## Saved comparison artifacts

- `build/metal-poc/authored-mips-reference-comparison.png`: columns show ANGLE,
  the earlier generated-mip preview and the corrected authored-mip preview;
  rows show spawn and overview.
- `build/metal-poc/authored-mips-spawn-640x480.png` and
  `authored-mips-overview-640x480.png`: corrected matched captures.
- Corresponding `.png.json` files record camera, map/scene/shader hashes,
  resolution and mip-level counts.
- `build/metal-reference-20261004/opaque-runtime/resource-report.json` and
  `opaque-runtime/run/frame420-no-decals.png` prove original opaque resource
  identity and the visible glyph's independence from permanent decals.
- `build/metal-reference-20261004/decal-runtime/resource-report.json` records
  actual decal textures, geometry, UVs and draw state.
- `build/metal-poc/camera-transparent-state-audit.json` records camera and
  transparent pass state evidence.
- `build/metal-poc/authored-mips-spawn-1280x720.png` and
  `authored-mips-overview-1280x720.png`: higher-resolution preview captures.
- `build/metal-poc/before-authored-mips-20261004/Halo Metal POC.app`: preserved
  previous preview app. Earlier screenshots and reference artifacts are intact.
