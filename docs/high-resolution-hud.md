# Optional high-resolution HUD

Choose **Settings → Game Settings → Video → HUD**, then select **Original** or
**High Resolution**. The same control is available through Game Settings in
Pause. Accept saves the choice; Cancel discards it. Quit and reopen Halo to apply
the saved choice. Original is the default.

The setting reuses `display.high_res_hud` in `config.toml`. Both ANGLE and native
Metal on Mac, plus Linux, Windows, Android and iOS, use the same embedded assets
and shared menu/save boundary. This
changes local presentation, without changing simulation, gameplay or networking.

High Resolution uses the existing 69 embedded HUD sheets in `port/assets/hud`:
66 are eight times their original dimensions and three are four times. They
cover shield/health and ammo meters, counters, panels, radar, reticles, waypoints,
damage arrows and scope artwork. The game retains the original tag-based size,
position and texture layout. Larger textures use linear filtering and mipmaps.

These assets are hand-drawn SVG reconstructions of Halo PC HUD artwork, remapped
and aligned to the Xbox sheets by `tools/hud_assets.py`. They are authored
redraws, rather than recovered high-resolution Bungie originals. The original
bitmap font and message artwork remain: enabling this setting does not sharpen
all menus, scoreboards or text. PC scope labels that differ from Xbox and
language-specific message artwork are deliberately excluded.

Only a bitmap with the expected original dimensions and pixel checksum can use
its replacement. Modified or localized bitmaps retain their own artwork. A
decode failure also retains the original bitmap. Native Metal caches each
replacement on first use, uploads a full RGBA mip chain, and preserves the
original meter thresholds while using the redraw's edge-coverage channel.

The shared GLES path also forces unbiased linear mip filtering for redraws.
On drivers without native border clamp, it corrects each selected mip's border
footprint before trilinear interpolation. Original texture filtering and border
behavior remain unchanged.

## Render resolution

Asset resolution and framebuffer resolution are separate. Native Metal uses
the selected physical render size. Linux/Windows fullscreen OpenGL uses the
display resolution, while their windowed mode uses the original 640×480 target.
Mac ANGLE, iOS and Android currently render the world and HUD into a 480-line
target, then enlarge it to the drawable. Redraws improve outlines/filtering in
those targets, but cannot provide the same display-resolution detail as native
Metal. This option does not raise their world-rendering resolution. A separate
HUD presentation pass would need to preserve world-dependent blending,
split-screen viewports and overlay order before removing that limit.

For artwork review, `tools/hud_assets.py check` creates original / reduced redraw
/ full-resolution redraw comparisons from a user-supplied Xbox map. Compare
reticle centers, silhouettes, line thickness, transparency, meter fill and scope
alignment at both original and higher resolutions. A successful upload or smoke
test does not establish Xbox artwork parity. Keep Original available for those
comparisons.

## Local validation

October 5, 2026 checks on Apple M5 Max passed both renderer builds, menu
save/cancel/rollback and layout checks, and exact decoding of all 69 PNGs.
The Metal GPU fixture passed 269 meter, alpha-test, blend and authored-border
cases, including fractional mip levels. The CPU draw packer also retained all
126 original captured draw outputs byte-for-byte.

Separate nine-second Blood Gulch runs passed Metal API validation in Original
and High Resolution at 1440×1080. Original uploaded no replacement textures;
High Resolution uploaded 16 sheets once each. A further High Resolution run
passed at the actual 3600×2338 native fullscreen drawable. All runs exited
normally and produced five captures. Counter, meter, radar and reticle artwork
was inspected; this is bounded local coverage, not a complete weapon/scope,
split-screen, campaign or retail Xbox appearance certification.

Local evidence is retained under `build/hud-hires-20261005-runtime-attempt3`,
`build/hud-hires-20261005-native-runtime-attempt1` and
`build/metal-poc/hud-hires-validation-20261005-border`. Captures, game data and
binaries stay outside source control.

The cross-platform follow-up passes 25 asset/menu/settings tests, including all
five menu platform variants and six build graphs (the two Mac renderers).
The portable decoder fixture uses the game's bundled zlib and compares all 69
sheets against Pillow. It needs no host zlib library or shared-library exports.

Mac ANGLE passes 279 production GLSL/sampler GPU cases: 192 meter cases, 77
forced border-fallback mip cases, eight point/linear controls and two mip-bias
controls. The earlier 36,504 original border comparisons also pass. Two isolated
nine-second Blood Gulch runs exit normally with five captures each: Original
uploads no replacement sheets, High Resolution uploads 16 sheets once each,
with no GL or Metal API validation errors. Captured ANGLE targets are 640×480,
presented to a 2560×1920 window drawable. The iOS shared game image compiles and
embeds successfully; no iOS device was played in this validation.

Evidence: `build/hud-cross-platform-20261005-angle-runtime`,
`build/hud-glsl-validation-20261005` and
`build/hud-cross-platform-20261005-metal-gpu`. CI now checks asset decoding and
menu/build wiring on Linux, Windows, Android and Apple, runs the GLES pixel
fixture on Linux and Mac, and compiles the iOS guest. The Linux/Windows/Android
full builds already run in their respective jobs. These new CI changes have
not been run remotely; other-platform GPU/device playtests remain unverified.
