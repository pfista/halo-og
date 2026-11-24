# Adopting OpenCE work in Halo OG

Halo OG stays its own build and takes OpenCE's engine work in ordered batches.
The native Metal renderer, the original menus and Halo OG's own network
protocol stay as they are. This page records what was decided after the
November 23, 2026 player meeting, the rules for taking a change, and where
each batch stands. Per-commit decisions are in
[the fidelity policy](xbox-fidelity.md#november-24-adoption-for-07).

## Decisions

| Question | Decision (November 24, 2026) |
| --- | --- |
| Re-fork from OpenCE or pull selectively | Pull selectively and be more permissive about what is pulled. No online co-op, no OpenCE netcode or services, no PC menus. |
| Release | These changes are Halo OG 0.7. 0.7 builds play with 0.7 builds. |
| Picture defaults | A new installation uses the display's resolution, Upres assets and Smooth Motion. The original Xbox picture stays selectable. |
| Player cap | A host admits 32 players. |
| MCC maps | Fix Halo OG's own converter so converted maps are correct, then add self-service import. OpenCE's runtime loader is not ported. |
| Licence | Take code from OpenCE's CC0-era commits first. Changing Halo OG to AGPL, which opens the rest, is a later change of its own. |
| Non-original weapons | The Sentinel Beam is the only exception to "Halo 1 weapons only". |

## Rules for taking a change

An OpenCE engine improvement is a candidate by default when it passes all four
tests. Review each change on its own and never merge wholesale.

1. **Stock behavior is unchanged**, or the change is an option that defaults to
   the original. A fix to an original Xbox quirk is a change to stock behavior.
2. **It needs none of OpenCE's protocol, co-op, online services or PC menus.**
3. **It works on Metal**, or its Metal half ships in the same pull request.
4. **Its licence era is stated.** OpenCE is CC0 up to commit `4b09168e`
   (October 19, 2026) and AGPL-3.0-or-later from it. Check with
   `git merge-base --is-ancestor <commit> 4b09168e && echo CC0 || echo AGPL`.
   Until Halo OG's licence changes, AGPL-era code is described and written
   fresh, or waits.

OpenCE changes no file under `port/macos` or `port/ios`, so it cannot overwrite
the Metal renderer. The exposure is narrower:

- Five shared files that both projects rewrote: `nv2a_psh.c`, `nv2a_vsh.c`,
  `xbox_textures.c`, `xgpu.h` and `hud_hires.c`. Merge these by hand.
- A change to `d3d8_gl.c` reaches Windows, Linux and Android only. Mac and
  iPhone need the same behavior written in `d3d8_metal.c`.
- Metal stops the game on render state it does not recognise, so a renderer
  change needs a live Metal run, not only a build.

`d3d8_gl.c` is not compiled by the Mac build. To compile it on a Mac, configure
the guest-only OpenGL build and build its object, then configure for Mac again:

```sh
python3 configure.py --android-guest-only --pgo off \
  --android-guest-llvm-bin build/macos/toolchain/bin \
  --android-guest-gl-include <checkout with tools/macos_setup.py --gl-reference>/build/macos/toolchain/gl
ninja build/android/guest/obj/port/linux/src/d3d8_gl.o
python3 configure.py --macos --android-guest-llvm-bin build/macos/toolchain/bin --pgo off
```

## Licence

Halo OG is CC0. Everything adopted for 0.7 so far comes from OpenCE's CC0-era
commits or is new work. OpenCE's MCC map support, dedicated servers, measured
Xbox audio and most of its later fixes are AGPL.

Moving Halo OG to AGPL-3.0-or-later is compatible with being open source. What
it changes:

- Every build that contains AGPL code is distributed under the AGPL, with
  OpenCE's copyright and licence notices kept and the exact source of each
  release available. The public repository and release tags already do that.
- Everyone who forks or redistributes Halo OG must publish their changes under
  the AGPL too. Someone who runs a modified build as a network service, such
  as a dedicated server, must offer its source to the players who connect.
- It is one-way. AGPL code cannot later be offered as CC0, and contributions
  made after the change arrive under the AGPL.
- The App Store's terms have historically conflicted with GPL-family licences,
  and only OpenCE's authors can grant an exception for their code. iPhone
  builds are sideloaded today, so nothing changes now. An App Store or
  TestFlight release would need that permission first.
- Bundled libraries (SDL3, Sparkle, mbedTLS, miniupnpc, KCP, tomlc17, stb,
  musl) have licences compatible with the AGPL. Game data is never distributed.

Halo OG 0.5.2 and later already contain adaptations of a few AGPL-era fixes
(split-screen fog, looping sounds, lens flares, turning in midair). The licence
change settles those too. This is a description of the history and of the
licences, not legal advice.

When the change is made, make it one commit: replace `LICENSE.md`, add the
notices, and update the README. AGPL-era ports land only after it.

## Batches

### 1. Small fixes

Done for 0.7: eleven CC0-era fixes, listed in
[the fidelity policy](xbox-fidelity.md#november-24-adoption-for-07).

Still open:

| Item | Source | Why it waits |
| --- | --- | --- |
| Bounds checks on network and map input | `761210d4`, `76addf66`, `54abd344` (CC0) | Large, with 26 files to merge by hand. Do it with the map import, which is what exposes the game to untrusted maps. |
| Lens flares out of view are not tested | `744040c87` (CC0) | Changes when a flare's brightness fades. Needs a comparison on both renderers. |
| Pregame keep-alive width, held buttons after an input stall, a name ending in `\|`, Running Riot at zero kills, Team Oddball setup | `904fbbfc`, `9ed134a5`, `2dea8f6c`, `2223f945`, `8453be8d` (AGPL) | After the licence change. |

### 2. MCC maps

The converter already accepts MCC maps, and it is where the original weapons
and the Xbox HUD are installed. A review of OpenCE's runtime fix-ups against
the converter found these gaps. The first group affects every MCC-sourced map,
including the published Digsite maps; the second affects weapons a map keeps
that are not Halo 1 originals.

| # | Defect in converted maps | Converter change |
| --- | --- | --- |
| 1 | Radar blips sit at half their distance: the converter halves `motion_sensor_scale` (32 to 16), but the Xbox value and the MCC value are both 32 | Stop treating it as a 960-line pixel value in `normalize_mcc_hud.cpp` |
| 2 | The indicator over a teammate is twice the Xbox size (128x64 against 64x32) | Install the Xbox `hud_multiplayer` bitmap, as `hud_digits.py` does for digits |
| 3 | Button prompt icons shift one to three pixels: the MCC tag already holds the Xbox offsets and the converter halves them | Leave offsets that equal the Xbox value |
| 4 | A texture or sound is replaced or dropped when the 22 MiB texture cache or 4 MiB sound cache fills | Add a budget rule to the mip stage, or give converted maps the larger arena Fiesta maps use |
| 5 | Player armour and kept custom weapons shine and colour wrongly: their multipurpose maps are in Gearbox channel order (15 shaders in converted Chillout) | New bitmap stage that reorders the channels and sets the Xbox-order flag |
| 6 | A kept custom weapon's meter fills wrongly: HUD meter channels are in Gearbox order | Exchange colour and alpha in the meter bitmap in `normalize_mcc_hud.cpp` |
| 7 | Scope masks of kept custom zoom weapons are the wrong size | Treat `screen_effect` masks as fixed-size consumers |
| 8 | A tick at the loop point of kept looping sounds: sounds are padded with silence | Pad with the last sample in `convert_audio.cpp` |

Weapons the profile replaces with Halo 1 originals use Xbox tags, so their own
models, effects, sounds and HUD are not converted. Items 1 to 4 are what still
reaches them. Some MCC behavior needs the engine and cannot be converted:
first-person particle streams, camera-relative projectile origins, 3D damage
acceleration, and models above 42 nodes. The converter should report these.

Each converter change needs a profile version bump, a rebuilt helper, a
reconversion of the published maps and an in-game check before republishing.

Then, in order:

1. Convert 10 to 20 popular Workshop multiplayer maps and tally what stops each.
2. Teach the converter the Workshop folder layout and MCC's shared resource maps.
3. Add **Import MCC Map…** to the Mac app, running the bundled converter.
4. Add a map hash to the join handshake so imported maps can be played together.

Campaign, Firefight and UI maps stay out of scope: the profile omits scripts.

### 3. Menus

Done for 0.7: horizontal and vertical look sensitivity in Game Settings, from
the main menu and from Pause. A menu walk, `tools/menu_layout_check.py`, now
fails on any text that does not fit its box; it covers the multiplayer and
Game Settings screens from the main menu and the one-player Pause pages of a
hosted game, and found the locked game type dialog and one Game Settings
description. Split-screen Pause is not in it: it presses one controller.

Done since (November 24, 2026): one Pause panel. The walk had shown the Pause
list mixing two font sizes because "PERFORMANCE OPTIONS" did not fit the
202-pixel button, Video's rows packed at a 20-pixel pitch and touching the
selection box, empty bands above the legend, two Performance Options rows
without spaces around their arrows, and titles in two sizes. Now every native
Pause page takes its row size, font, spacing and frame from one table
(`native_pause_styles`); [native settings](native-settings.md) describes the
layout. One player gets a panel 82 pixels wider with every row in the large
font at the original 27-pixel pitch. Split screen keeps a smaller panel with
one font on each page. A setting shows its name at the left of its row and
its value at the right. The frame and the selection box are drawn in pieces, so
they can be any size without stretching their corners. The walk now covers the
split-screen layouts too (`--tour pause-2p`, `--tour pause-4p`), by showing
player one's Pause in a half or a quarter of the screen.

Still open:

- The menu kit covers Pause only. The main menu's Game Settings and the
  gametype editor still clone stock widgets with numbers typed into each page,
  and campaign's Pause list is still the authored one with a fifth row at a
  24-pixel pitch.
- The overflow rule, more options means a sub-page, is enforced for Pause
  (eight rows a page). The main menu pages have no such limit yet.
- One **Advanced** level under Game Settings and under the gametype editor,
  with a single **Reset to Original**.
- The menu walk checks each text against its own box. It does not yet catch
  rows that overlap each other, which is how Video's packed rows passed.
- Upres text is moving from a substitute typeface to fonts rebuilt from the
  maps' own letters (`tools/og_font.py`). The game does not draw them yet:
  their weight and a letter-by-letter review come first.
- A linear look response curve as an option beside the Xbox curve.

### 4. Picture and sound

Done for 0.7: the new picture defaults on Mac, Windows and Linux, active
camouflage at screen resolution on both renderers, three Smooth Motion fixes,
and Detail Distance for model pop-in, shadows and particle culling
(`display.detail_distance`, following the resolution by default).

Still open, all CC0-era unless noted: a menu row for Detail Distance (the
Video page is full on every desktop, so it waits for the Advanced page), scope
blur at high resolution (`f815e1ccb`), fuller Upres HUD (`9da2a45ff`,
`3ae09c3d2`, `f8b3eecb3`, `f38d526e8`, `c72962a73`), mixer quality (27
commits), room reverb as an option
(`8a8e70599`, `4afb59660`), and a Resolution setting on iPhone so it can take
the native default. Measured Xbox spatial audio (`176b10c5`) is AGPL.

### 5. Competitive rules

Done for 0.7: the 32-player cap.

- **Bullet spread.** Precision Spread is already a game-type rule (Edit
  Gametypes → Performance), agreed by every player and locked for the match.
  It removes the first-shot spread of the pistol and the unscoped sniper rifle
  only; sustained fire still spreads and other weapons are unchanged. Players
  asked for no spread at all. That would be a third choice, Xbox / First Shot /
  None, with a new capability bit.
- **Sandbox toggles.** A host choosing which weapons, grenades, powerups and
  vehicles a game type places on the map, item by item. Xbox offers only
  preset weapon sets. This needs new storage in the saved game type and is the
  largest item here.
- **Lead.** Halo OG and OpenCE share the same hit model: the shooter's machine
  decides the hit and the host accepts it if the target was close enough.
  Measure before changing it.
- The 180-degree grenade behavior is original Xbox simulation. The fix exists
  as **Player Turning: Follow Aim**.

## Not taking

Online co-op and campaign sync, OpenCE's protocol versions and services, PC
menus, new modes and bots, the runtime Custom Edition and MCC loaders, vehicle
riding, the elevator timing change, client-reported fire origins, HDR and
per-pixel lighting, larger object pools, and reuse of a departed player's slot.
The antenna and flag two-unit jump threshold (`f2a0f91e4`) is an original Xbox
quirk and stays.
