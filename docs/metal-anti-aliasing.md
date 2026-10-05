# Optional world anti-aliasing

Native Metal can apply an optional spatial edge filter to the original world
before drawing the original HUD. `display.anti_aliasing="off"` is the default;
`"fxaa"` enables a conservative FXAA-style directional filter. Restart to change
the mode, because its host capability is negotiated during initialization.
No application environment variable is added.

```toml
[display]
fullscreen = true
screen_width = 0
render_height = 0
frame_limit = 60
vsync = false
interpolation = true
anti_aliasing = "fxaa"
high_res_hud = false
direct_camera = false
```

The mode uses the existing maps, textures, mipmaps, geometry, shaders and HUD
bitmaps. It changes rendered edge pixels, rather than replacing or upscaling
an asset. The original fixed 30 Hz simulation and input/gameplay rules remain.
The render cap is a target, not a promise of achieved FPS.

The hook runs in `render_window` after world fog and lens flares, immediately
before `interface_draw_screen`. Primary player views are filtered; reflection
targets, loading/menu frames and Bink playback keep their existing paths.
HUD, scope effects, counters, reticles and subsequent UI are drawn afterward.
This follows the pre-HUD placement recommended in
[NVIDIA's FXAA integration paper](https://developer.download.nvidia.com/assets/gamedev/files/sdk/11/FXAA_WhitePaper.pdf).
This implementation does not claim to reproduce a numbered NVIDIA quality preset.

The guest converts the camera's logical viewport boundaries into physical
attachment pixels and adds one optional command. The host takes a private copy
and filters back into that rectangle, with every sample clamped to the player's
own pixel centers. This avoids reading an attachment while writing it and prevents
split-screen views from sampling another player's already-rendered HUD. Alpha,
depth, stencil and original visibility-query results are preserved. Subsequent
original commands retain their state and order.

With AA enabled, the original backbuffer and later history copies contain the
filtered world. Existing screenshots therefore capture the world after AA and
the unfiltered HUD. This is not a display-only effect, and original history-based
screen effects may consequently sample the smoothed world. Off adds no filter
command. The optional initialization flag advertises the new capability only to
guests requesting it, preserving the older guest's capability contract.

This spatial filter can soften fine world details. It has no temporal history,
camera jitter, motion vectors, asset replacement or sharpening pass. It does not
promise to eliminate every form of moving texture shimmer. Stronger filtering
and MSAA remain separate experiments requiring their own image and performance
checks. Original authored anisotropy is already supported; a forced anisotropy
option would need to exclude the special border and volume sampling contracts.

## Validation and local playtests

The build/profile/runtime tools require a fresh `--anti-aliasing` build proof
for AA-aware profiles. Requested configuration alone cannot establish that AA
ran: runtime evidence binds the actual pre-HUD pass count and captured stage.
GPU validation separately checks filter behavior, viewport isolation, alpha and
atomic rejection. These checks do not establish retail Xbox pixel parity.

The observed native build completed with exit 0. Its no-ANGLE proof is
`build/macos-metal/native-aa-build-proof-attempt1/result.json`, SHA256
`982f1726a6b99f60531621afcae741c9dac1fea0fbf4c9313fcede82035f21e3`.
It binds 42 source/binary inputs and 32 evidence files, including the actual
ILP32 world object, compiled pre-HUD call and final guest export.

Validation completed on this Mac:

- 185 targeted CPU tests pass, including viewport scaling, hook placement,
  capability negotiation, configuration, profile identity and runtime evidence.
- AA Off preserves all 378 ordered original attachment/query checkpoints with
  zero missing checkpoints or byte differences (`host-frame-world-aa-off-attempt2`).
  This retains the replay's limited attachment/query scope, rather than claiming
  full-frame Xbox parity or original CPU query timing.
- The isolated FXAA GPU fixture passes all 103 readbacks and 15 atomic rejection
  cases (`fxaa-gpu-attempt3`). Sloped edges gain intermediate pixels; alpha,
  flat interiors, viewport boundaries and independent depth/stencil/query
  baselines are preserved. Same-shape scratch reuse, opposite inputs and adjacent
  viewports are covered. All 90 rollback comparisons match their actual GPU
  baselines. The fixture uses Metal API validation and actual ILP32 transport.
- Eight independent 20-second fullscreen runs pass API validation, with host
  and guest exit 0, no renderer/API errors, and complete 3600x2338 captures.
  Positive pre-HUD pass counts are bound for FXAA; Off records zero. One image
  per profile was reviewed for world/weapon/HUD presence. This is not pixel
  parity certification or a complete gameplay test.

The refreshed ready chooser is
`build/macos-metal/native-aa-playtests-attempt1/chooser/Choose Native Metal Playtest.command`.
It retains the five native Blood Gulch cap/VSync choices and adds FXAA at the
60/120 caps, plus Damnation with FXAA at the 60 cap. Lower-resolution presets are
not in this focused chooser. Original assets are referenced without modification.
Earlier playtest folders and evidence retain their original binaries.

## Native-resolution timing observations

Four sequential 30-second Blood Gulch runs use the same frozen build and fresh
saves in Off/FXAA/FXAA/Off order. All use 3600x2338, a 120 render cap, VSync off,
scripted solo input, no captures and API validation off. Diagnostic logging is
included. Consecutive completed-present intervals after original tick 150 retain
every outlier; the separate timing runs cannot promote human launchers.

| Order / AA | Render FPS | Simulation Hz | Median / p95 interval | Largest interval |
| --- | ---: | ---: | ---: | ---: |
| 1 / Off | 54.44 | 29.989 | 18.52 / 21.41 ms | 25.54 ms |
| 2 / FXAA | 59.88 | 30.002 | 15.47 / 22.40 ms | 25.20 ms |
| 3 / FXAA | 52.06 | 29.974 | 20.12 / 24.95 ms | 36.12 ms |
| 4 / Off | 63.86 | 29.987 | 14.50 / 20.94 ms | 23.94 ms |

The run-to-run variation exceeds the mean difference between modes, so this
does not establish an isolated AA cost or a performance gain. Neither mode
reaches sustained 120 FPS here. The fixed 30 Hz simulation step remains intact;
the slight measured wall-clock variation includes observation boundaries.
Raw timings, host aggregates and every interval are retained under
`build/macos-metal/native-aa-timing-abba-attempt1/`.

Local proprietary assets, captures, binaries, saves and generated evidence remain
outside source control. The installed ANGLE app was not replaced.
