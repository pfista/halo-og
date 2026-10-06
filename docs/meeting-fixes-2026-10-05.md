# Meeting feedback implementation

The first pass implements the changes supported by the current native engine
and reviewed assets. Each fix or feature has its own local commit. Pre-existing
reliability and map-conversion changes remain uncommitted; no release is implied.

| Feedback | Result |
| --- | --- |
| Controller bumpers reversed | Left bumper switches grenade type; right bumper toggles flashlight. Shared SDL mapping and iOS touch equivalents agree. Keyboard bindings retain their choices. |
| Controller dead zones | Game Settings → Controller has independent Left Stick Deadzone and Right Stick Deadzone presets. Xbox defaults preserve the original 9000 filter; keyboard movement stays separate. |
| Controller look acceleration | Game Settings → Controller → Look Acceleration offers Xbox / Off. Xbox retains the original held-stick horizontal turning boost; Off removes that timed boost. |
| PB Options label | Game-type editor entry and heading use Performance with the original regular font. Pause uses Performance Options with its resident small font; selection cards identify active performance options. |
| Map-set settings | Game Settings → Multiplayer has OG Maps and Community Maps. Both default On. Filters affect hosting choices; hidden caches remain usable for joining and approved downloads. Empty lists fall back to OG maps. |
| Disable joining during a match | Game Settings → Multiplayer → Join In Progress, default On. Off closes the shared running-game admission/advertisement gate while preserving pregame joining and existing players. |
| Hardcore precision spread | Edit Gametypes → Performance → Hardcore, default Off. Pistol and unscoped sniper initial spread becomes zero; maximum spread, buildup, recovery and firing RNG calls remain. Campaign, AI, secondary triggers and other weapon roles retain their original behavior. |
| Fiesta | Edit Gametypes → Item Options → Starting Equipment → Fiesta adds two distinct random original Xbox weapons on each spawn. Custom and Generic remain available. The saved host-selected rule is checked for every joining player's capability. |
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

Fiesta uses bit 128 in the same signed variant. Its original eight-weapon pool
is independent of the map's world Weapon Set, and the normal grenade rules
remain. Performance presets, pause changes and saved variant copies preserve
the selected starting equipment. See [Fiesta starting equipment](fiesta.md).

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
- Expanded Fiesta pools and a separate Random policy need reviewed weapon
  roles, excluding objective and vehicle weapons. The first Fiesta choice
  uses only the original eight Xbox weapon identities.
- Full imported weapon names belong in reviewed HUD/string tags. The new native
  options use full labels; there is no generic acronym rewrite of authored assets.
- Battle rifles and other precision weapons need reviewed role metadata before
  Hardcore applies to them.
- Dig Site integration needs source tags, the collaborator's scenario cleanup,
  reviewed conversion profiles and Xbox-v5 rebuilds. The supplied MCC cache is
  not directly loadable; this pass does not share or publish a converted build.
- Frag placement and the looping overshield sound need a reproducible input/map
  case before choosing an implementation.

## Validation

Production-function fixtures cover the firing cone, first-shot zero spread,
sustained spread, stock/campaign/AI/scoped paths, retained cone calls, shared
join gate, save format, old/new capability generations, host locking, asset
mutation scope, authored replacements and repeated map initialization.
Existing settings fixtures cover real TOML persistence, draft/cancel/save
rollback, host-only map filters, menu layouts, original font widths and runtime
tag registry lifetime. These checks do not establish physical-controller,
cross-platform multiplayer or reference-Xbox parity.

The first-pass targeted suite passed 107 tests, and `git diff --check` passed.
The native Mac guest and app built with the documented LLVM 22
toolchain. For that handoff, `/Applications/Halo OG.app` was installed through
the existing backup procedure and passed strict signature verification; its
guest hash matched the built guest:
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

The Controller follow-up adds the fourth Game Settings category, ordered
Audio, Video, Controller, Multiplayer. Its preferences save locally through
Accept/Cancel and remain outside player profiles and host-selected game rules.
Production fixtures check every signed stick value at all presets, unchanged
keyboard diagonal response, all four profile look layouts, settings persistence
and failed saves. Acceleration fixtures compare the original timed yaw ramp
bit for bit, check Off/Xbox transitions, and preserve pitch, sensitivity, zoom,
stun scaling and direct mouse input. Widget fixtures cover main, pause, split-screen and campaign
layouts; actual Xbox font metrics cover every valid custom dead-zone value.
Controller feel and native interactive navigation still need physical
playtesting. See [native settings](native-settings.md#controller).

The Fiesta follow-up adds the third Starting Equipment choice without changing
the original Custom/Generic choices. Production fixtures cover all 56 ordered
original-weapon pairs, deterministic host selection, unchanged non-Fiesta RNG,
normal weapon ammo, grenade rules, failed creation/attachment rollback, world
Weapon Set independence and resource prediction. UI fixtures preserve the
authored fonts, navigation and help; save/network fixtures cover every flags
byte, older capability generations, normal and late-join full records, and
fixed match rules. Performance editor, pause and console changes preserve
Fiesta. Live multiplayer gameplay still needs playtesting.

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
| `3208fbeb` | `fix(ui): shorten game-type editor label to Performance at regular size` |
| `833ab78d` | `feat(input): add Controller settings for stick dead zones` |
| `20c459f4` | `feat(input): add Xbox/off controller look acceleration` |

`33444412` adds the focused-commit and Conventional Commit subject convention
to `AGENTS.md`. Release changelogs already preserve these subjects directly.
Each intermediate code commit was tested from an exported staged tree before
commit, with later features absent. The complete committed meeting-feature
tree also passes the targeted 107-test suite. The first-pass installed app's
BuildInfo identified the pre-commit build described above.
