# Meeting feedback implementation

The first pass implements the changes supported by the current native engine
and reviewed assets. Each fix or feature has its own local commit. Pre-existing
reliability and map-conversion changes remain uncommitted; no release is implied.

| Feedback | Result |
| --- | --- |
| Controller bumpers reversed | Left bumper switches grenade type; right bumper toggles flashlight. Shared SDL mapping and iOS touch equivalents agree. Keyboard bindings retain their choices. |
| PB Options label | Game-type editor entry and heading use Performance with the original regular font. Pause uses Performance Options with its resident small font; selection cards identify active performance options. |
| Map-set settings | Game Settings → Multiplayer has OG Maps and Community Maps. Both default On. Filters affect hosting choices; hidden caches remain usable for joining and approved downloads. Empty lists fall back to OG maps. |
| Disable joining during a match | Game Settings → Multiplayer → Join In Progress, default On. Off closes the shared running-game admission/advertisement gate while preserving pregame joining and existing players. |
| Hardcore precision spread | Edit Gametypes → Performance → Hardcore, default Off. Pistol and unscoped sniper initial spread becomes zero; maximum spread, buildup, recovery and firing RNG calls remain. Campaign, AI, secondary triggers and other weapon roles retain their original behavior. |
| Pistol hollow-metal impact | Canonical loaded pistol projectile replaces only its stock hollow-metal default effect reference with the existing thick-metal reference. Custom authored replacements are preserved. |
| Overshield collision material | Canonical loaded overshield collision changes dirt materials to Engineer Force Field; existing fixes and other materials are preserved. |
| One-tick delay | Already implemented as Input Delay: Off / 33ms; retained. |
| Menu music | Existing default On is retained. |

Hardcore is saved in the existing signed 104-byte variant, using option bit 64.
It is fixed before each match. Stock/Practice presets and live aid changes
preserve it independently of their aid selections. A host checks every peer's
capability, and clients require the selected host's acknowledgement before
applying saved Hardcore bytes. Capability announcements include each older
generation, and host acknowledgements omit unknown bits for older clients.
See [Performance Options](performance-options.md) and
[native settings](native-settings.md) for the controls.

The two tag changes are explicitly requested content refinements of retail
quirks, not claims of original-Xbox corrections. They operate on loaded native
tags without rewriting cache files. Verified installed NTSC Chill Out and
community Downrush samples contain the identified pistol hollow-metal effect.
Both sampled overshields already use Engineer Force Field, so that correction
is a no-op there. The meeting's comparison to camo was not corroborated: those
sampled camo collision materials are dirt.

## Remaining work

- Separate original-community, alternate and refined map categories need
  reviewed catalog metadata. The present catalog does not encode these roles.
- Fiesta/Random need a persisted loadout/pool contract, deterministic spawn
  selection and network/inventory verification. The reviewed original weapon
  pool can use globals slots 0, 3, 4, 5, 6, 7, 8 and 9; expanded pools require
  explicit weapon roles, excluding objective and vehicle weapons.
- Full imported weapon names belong in reviewed HUD/string tags. The new native
  options use full labels; there is no generic acronym rewrite of authored assets.
- Battle rifles and other precision weapons need reviewed role metadata before
  Hardcore applies to them.
- Dig Site integration needs source tags, the collaborator's scenario cleanup,
  reviewed conversion profiles and Xbox-v5 rebuilds. The supplied MCC cache is
  not directly loadable; this pass does not share or publish a converted build.
- Controller acceleration/dead-zone controls, frag placement and the looping
  overshield sound need separate implementation or a reproducible input/map case.

## Validation

Production-function fixtures cover the firing cone, first-shot zero spread,
sustained spread, stock/campaign/AI/scoped paths, retained cone calls, shared
join gate, save format, old/new capability generations, host locking, asset
mutation scope, authored replacements and repeated map initialization.
Existing settings fixtures cover real TOML persistence, draft/cancel/save
rollback, host-only map filters, menu layouts, original font widths and runtime
tag registry lifetime. These checks do not establish physical-controller,
cross-platform multiplayer or reference-Xbox parity.

The final targeted suite passes 107 tests, and `git diff --check` passes.
The native Mac guest and app build successfully with the documented LLVM 22
toolchain. `/Applications/Halo OG.app` is installed through the existing
backup procedure and passes strict signature verification; its guest hash
matches the built guest:
`0e1bf28e886bc13aec58a6e927318b9d8cb9253074f7afcbdf55f7dd00fc3bda`.
BuildInfo identifies source `18f30a0617d9741eecee056328ed8c2d1268d276`
with local changes. Pending pre-existing reliability/conversion work is retained.

Isolated offline 20-second menu and Chill Out smoke runs render 598 and 594
frames and exit cleanly. After the review added a queue-consumption guard for
extra split-screen seats, the app was rebuilt/reinstalled and Chill Out was
rerun: 594 frames, four captures, clean exit and no detected assertions/crashes.
Generated logs/captures are under `build/macos/meeting-*`. The smoke checks
startup, map loading and rendering; the new gameplay, controller and live
multiplayer behavior still need physical playtesting. Nothing was pushed,
tagged or released.

## Commit boundaries

| Commit | Change |
| --- | --- |
| `2fa3333b` | `fix(input): map left bumper to grenades and right bumper to flashlight` |
| `90c4c106` | `fix(ui): rename PB Options to Performance Options without clipping` |
| `4ac49ec7` | `feat(maps): add OG and community map-set toggles` |
| `d5e3bf53` | `feat(network): let hosts disable joining matches in progress` |
| `f2d618f5` | `feat(gameplay): add optional Hardcore precision spread` |
| `8d871809` | `fix(effects): correct pistol hollow-metal impact effect` |
| `9a944f8a` | `fix(effects): use force-field material for dirt-tagged overshields` |

`33444412` adds the focused-commit and Conventional Commit subject convention
to `AGENTS.md`. Release changelogs already preserve these subjects directly.
Each intermediate code commit was tested from an exported staged tree before
commit, with later features absent. The complete committed meeting-feature
tree also passes the targeted 107-test suite. The first-pass installed app's
BuildInfo identified the pre-commit build described above.
