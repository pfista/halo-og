# Original Xbox fidelity

Halo OG targets original Xbox Halo: Combat Evolved NTSC gameplay, presentation
and LAN feel across native platforms. Community maps and optional competitive
features extend that baseline without replacing its rules.

## Upstream integration

The full cybersecurity baseline is `c55e4e2b` (build 64), integrated as
`aabe44417431c36e46aaa385a69a89a3c9d685c0`. Selective protocol additions are
v10 (`d1c7243cb20eab4488efa1266e259b1f4d5240f6`, local
`ea4dec3c28fcb4975ad36718c344bf5205b4c5eb`) and v11
(`c9ee319ab5f2964a32372fffdc7756111e39727d`, local
`694cc79d48654d862d3ecda51e71ea559f93bd2d`). These are focused ports, not merges
of intervening upstream changes.

**Reviewed through:** OpenCE
`685bf260a0a648a1d898928a99b17428a2549b92` (October 4, 2026 review).
Review subsequent diffs individually. Keep review and integration boundaries
separate, and record new decisions here with their validation and local commit.

The following decisions still constrain integration. Excluded/deferred changes
were diff-reviewed and remain unintegrated; their runtime behavior is unvalidated.

| Upstream commit | Decision and current boundary |
| --- | --- |
| `0182da817285b67eee8264663ca79f7c32d66b5e` | Selectively adopt fonts and 34 faithful menu title replacements at the user's explicit request, behind Asset Quality: Original / Upres (Original default). Preserve tag-based layout/navigation and original postgame panel. Add a backend-neutral glyph atlas and Native Metal adapter; retain unsupported-font/character and bitmap-CRC fallbacks. See [Upres scope and validation](high-resolution-hud.md). |
| `f2ba71d9af4c6fc65d7419cc22e8f4899b16da88` | Exclude overhead player names. |
| `9f3e8c92de7569a577c3044d05288dbd6590c5bf` | Exclude replacement postgame title/panel. |
| `f0dfb58c94fa1a8f0f46cbd7df97dfda91a3dcb3`, `ab96597321eb50ccb499e5cec540cfdd5aca2d84` | Defer the desktop frame limiter and build fix pending a deliberate platform adaptation. |
| `634b4197f91534625bf99cb9ef0abe88975a7213`, `b438cea47946b2e6471ccc41c7d3da3542fca7f6` | Exclude refinements of overhead labels. |
| `fd3d62f9602870b209b8e0e5cd38d9f90ced6029` | Defer name/ban policy; broader keyboard/profile changes need separate review. |
| `d1c7243cb20eab4488efa1266e259b1f4d5240f6` | Adopt ping protocol only; retain original scoreboard. Integrated as `ea4dec3c`; protocol fixtures cover layout, roles and malformed/stale packets. |
| `80d30410c8db28f4008b92f4e012a1b046ece14e` | Defer Intel/Mesa memory barriers pending GPU comparison and configuration review. |
| `c9ee319ab5f2964a32372fffdc7756111e39727d` | Adopt v11 wire record, original defaults, advertisement metadata and received action-only input. Exclude PC menus, added modes, bindings/save format and associated dependencies. Integrated as `694cc79d`; network fixtures cover wire layout and admission before precache. The client-only host-team attachment correction was selected separately on October 4 and integrated as `6de3e8d221208e85c9340a8b58c70ddcddcbe044`; production-function fixtures cover both teams, invalid team values and free-for-all. The upstream host rebalance algorithm remains unintegrated. |
| `2b0103a0ef2f46f3713d7e045436c5283668f9a6`, `383355381c3f92ae8ce6c9c79cbe84924856aa2f` | Exclude expanded score menus. |
| `e8e0c2215ab6871bbe6f855f67b3459d94817b35` | Defer compiler include-path changes required only by the excluded PC menus. |
| `62b630a2610e7c0df88ffa43d6f03914cb35345e` | Exclude new weapon/loadout policy. |
| `23b542601f2ca505c7a0143703e92fbda6075e18` | Exclude altered infinite-grenade and unarmed-loadout rules; retain existing Xbox behavior. October 4 compatibility changes deliberately remove the v11 gametype-options gate for best-effort mixed-host tests; protocol, PB capability, packet and map checks remain enforced. This admission change does not implement the excluded rules. |
| `133d6a5dc1ea65a00ff6369c16d58d167fcd96f7` | Defer departed-player slot reuse. Unit/death/statistics packets identify players by absolute slot without a generation fence; delayed traffic can affect the replacement occupant. No slot-reuse code is adopted. |
| `601a4c1f506662dcd93d79105e3fe69410397a87` | Adopt loaded-map cleanup before the next network game. A stopped menu clock still leaves a loaded map and texture cache. Committed locally; validation is recorded below. |
| `809408c6635a1434fe4dbe3b64195211ddcbe8cf` | Adopt only invalid full-datum killer/assist guards, retaining valid-player scoring. Defer queue replacement coupled to the excluded slot reuse; guards do not make slot-only packets generation-safe. Committed locally; validation is recorded below. |
| `933aac61754eb5de2c8496dbe9b8278f033e4c1f` | Exclude no-map-weapons and unarmed-grenade rules. |
| `c04765d7f49f49bda706a258826134ef41c566ca` | Defer upstream service/browser adapter as separate discovery work; do not import PC menus or listing dependencies. |
| `3304965653692fc2f4cbea84f1bea2bb7d0f2bdd` | Exclude test-harness repair for the deferred upstream lobby feature. |
| `c3adcfe5bf917922d732f2551341b1ad00977867` | Exclude unrelated release-ZIP compression change from this core-fix port. |
| `46edf53657227837bee89a98d5e25f265f929922` | Exclude PC pause menu/settings artwork and workflow. |
| `2e3841ff7d7fe32647fe71014da51e2566f37f8e` | Exclude optional replacement shotgun-meter artwork alignment from the stock-HUD baseline. |
| `1a15a171ac7e030f108352c88b81d32ba6cccf9b` | Exclude vehicle-seat repair for unadopted unarmed-action rules; its failure mechanism is absent locally. |
| `39350fb81fda3bdf08693961d4ff2cece603e7f3` | Exclude overhead-label/motion-sensor relationship changes. |
| `ce77db8404ba8cbaa102da79c45462edfbfec697` | Exclude cryotube crash repair for unadopted unarmed-melee borrowing; the added helper is absent locally. |
| `c05864b3fc9b6333a071fcb23e186a0dc833e148` | Defer removing departed players from the scoreboard; presentation/ranking behavior is separate from reference safety. |
| `812ffeea3353d748fc4afc801c5758f76416eed4` | Exclude focused-row artwork for the unadopted PC browser. |
| `a227872ccbe4c897f970c0d14648a15287562f3f` | Merge of `ce77db84`; no additional independent fix. |
| `d3fc997fdc2513ee641dba96a5485ecc3d0e0c6a` | Exclude multiplayer second-weapon auto-pickup. Defer selected-slot swap and delayed client readiness pending Xbox timing and manual-selection evidence. |
| `d578f88bd0ef447b9039353a3f04affea55295a5` | Defer name sanitation for the unadopted upstream browser and name-policy helper. |
| `193cbf59c7e483386538fa34e28fb2503ab79a4b` | Defer PC-menu split-screen co-op workflow/controller routing; separate port adaptation. |
| `e3389991ac334ee9772dc04aa2f25d3c6631c629` | Defer PC-menu online split-screen/controller reassignment; separate port adaptation. |
| `88a7c07ec781fde6fe00467b89507918b629d2bb` | Defer MQTT broker-file configuration with the upstream discovery adapter. |
| `ffc1512dcbdc1ec6a3ea1dac400c99cc8ee9f132` | Exclude Android repair for the unadopted broker-file addition. |
| `7e00135d31bf55250c477295279f6625e3e45983` | Adopt null-client connection recovery before frame idle, mirroring the existing end-frame recovery. Committed locally; validation is recorded below. |
| `c115f5292db6d700ad84e8d712d9ae977de3bb3f` | Defer multiple local joiners in the PC preview/lobby workflow. |
| `933ed2b7b8e5a7dc560102bc1d1d13ddaeda0d60` | Exclude updater destination change; Halo OG keeps its own update source. |
| `685bf260a0a648a1d898928a99b17428a2549b92` | Defer either-player co-op menu selection routing with the unadopted PC menu workflow. |

The October 4 safe-fix port leaves the integrated build-64 and selective v11
baselines intact. It changes map/client resource lifetime and invalid full-datum
reference handling, with no wire-layout/version, simulation, weapon-pickup,
movement, balance, scoreboard or platform-renderer change. These are native port
reliability corrections rather than claims that original Xbox quirks are fixed.

Slot reuse remains deferred because `distributed_handle_unit_state` can apply a
dead state to the current occupant of an absolute slot, and the statistics
receiver can overwrite that occupant's counts. `distributed_message_stale`
tracks times per sender/message kind, not identity turnover. The paired upstream
changes provide no generation fence. Full-datum null guards cannot solve this
separate protocol identity problem.

The separate decompilation review reached `bnunu/halo-1`
`1b25ea9a37a4977ee138bd26d6ef441a8c3650f6` (all 11 outstanding commits) and
screened `punpckhdq/halo` through
`acd34e7d6b15e4a51d11b29d790ab058c8793a57` (60 commits after the common
ancestor, with targeted function comparisons). No confirmed missing gameplay
correction was adopted. Helper/codegen/source-storage gains still need native
ABI/floating-point validation, and the spectator fallback needs reference
executable evidence before changing original behavior.

Prioritize verified matching corrections, correctness, stability, performance
and renderer/platform fixes that preserve the baseline. Assess netcode for
simulation timing, input, authority, fairness, compatibility and service
requirements. Split cosmetic or gameplay changes from useful fixes; defer
uncertain effects. The glyph-padding correction preserves original font pixels
and is a renderer fix, not authorization to replace fonts.

## Authored original weapons in converted community maps

The reviewed `og-multiplayer-v5` conversion profile can explicitly select
`weapon_placement_policy: authored-default`. A verified, compiled map capability
preserves authored original Halo 1 weapon placements in Normal, No Grenades,
Uncut and All weapon sets. This is a community compatibility departure from the
retail rule that substitutes a Rocket Launcher for a registered Flamethrower.
Every restricted weapon set retains the complete original remap behavior.
Retail maps and profiles selecting `engine-native` retain the original rule.

The inert `__native_policy/authored_weapon_placements_v1.string_list` marker is
rooted through the Xbox multiplayer Soul collection. The runtime validates its
exact version payload before enabling the capability and resets it on map
unload. The converter verifies original weapon lineage, unchanged placements
and registry, and compiled marker residency. It records substitutions and the
required runtime capability in the builder report. All participants using this
map policy need a Halo OG build supporting that capability.

Source and offline production-function fixtures cover map capability lifetime,
marker validation and weapon-set remapping. This does not establish gameplay
or mixed-build network validation.

## Optional sound audience

Movement and weapon equip/switch sounds offer Normal, Just Me and Silent.
Normal retains the original sound mix and is the default for custom rules;
Just Me retains the acting player's feedback while suppressing those events
for other audio listeners. Silent retains the earlier mute for all listeners.
These are explicit host-selected departures from original audibility rules.
The optional Pro preset selects Just Me. Sound occurrences keep their authored
samples, effects, RNG consumption and weapon timing. Pickup chimes retain their
existing local-only feedback. Offline ownership and listener fixtures do not
establish gameplay listening results or retail parity.

## Protocol compatibility

Interoperability with cybersecurity clients and discovery services is a goal,
alongside Halo OG's original presentation and local feel. Review network and
discovery protocols separately from upstream menus and gameplay additions.
Shared sessions must respect the host's authoritative rules; a local client
cannot impose different movement or weapon rules while claiming a consistent
match. Keep Halo OG hosting defaults original and validate received host options
individually. See [the current interoperability review](network-interoperability.md).
Game-discovery UI requires a user check-in before implementation and should map
to original Xbox-style Multiplayer/System Link menus; upstream's PC-style
server browser UI is not adopted.

Protocol 11 retains host authority and 30 Hz simulation. Its 28-byte PC options
record does not introduce a new prediction or transport algorithm. Halo OG
hosts original-rule defaults. At the user's request, the October 4 compatibility
changes admit differing v11 gametype options for best-effort live testing,
including options with unimplemented local behavior. The diagnostic helper
still classifies unsupported options, but no longer controls admission. Host
time limits and other authoritative state can be replicated, while radar,
initial vehicle placement, custom loadouts and weapon rules may still differ.
This is not a claim of supported mixed-host gameplay. See
[host settings compatibility](host-time-limit-compatibility.md).

Protocol/version and PB capability checks, packet reassembly, machine/player
counts, difficulty, map-name and map compatibility checks remain enforced
before the received settings can change state or start precaching. Use matching
Halo OG builds and map revisions for the baseline playtest.

PB capability flag `0x04` is separate from the in-progress flag `0x02`.
Options-off games advertise stock v11; enabled PB games advertise `0x800B` and
require supporting peers. Input Delay: 33ms also requires peers that confirm
the delay capability; older PB builds cannot join an enabled-delay match.
v10/PB-v10 builds must update. For mixed cybersecurity tests, leave Performance
Options Stock, Input Delay Off and Hardcore Off. Games with five or more players should leave
Infinite Grenades off because the native Xbox rule still differs even though
the best-effort gate admits that setting.
See [networking](../port/linux/NETCODE.md), [Performance Options](performance-options.md)
and [playtesting](playtesting.md) for implementation and player guidance.

### Overshield drain audio

The reconstructed local drain (`c8d001ee2`) lowers the shield and calls
`hud_tick_shield` with the same loss. This keeps passive decay out of the
original HUD's vitality-decrease damage cue. Distributed clients introduced
by `8fcfe9e65` skip that local shield update and previously replaced vitality
without its HUD compensation, causing harmless Overshield decay to play
`shield_hit`.

The correction restores that compensation for local client HUDs using the
existing host tick and packed vitality/damage values. It accepts only a
same-unit interval of at most one second whose loss matches the original
per-tick float drain within the existing packing interval. New damage markers,
explicit damage aftermaths, charging transitions, independent vitality changes
and ambiguous losses retain damage feedback. Packet contents, version, host
authority, damage amounts and the 30 Hz simulation are unchanged.

Production-function fixtures cover complete local/client drains, quantized
snapshot intervals, real and repeated hits, event ordering, final depletion,
split-screen isolation and reset/sentinel handling. Sub-quantum damage whose
aftermath is also lost cannot always be distinguished from decay with the
existing protocol. Host/solo decay is quiet in those fixtures; the reported
host/solo sound still needs a runtime reproduction and is not established as
fixed by the client correction.

## Optional competitive features

The October 5 meeting-feedback implementation adds an explicit Hardcore
precision rule, default Off, independent of Stock/Practice aid presets. It
changes pistol/unscoped-sniper initial spread and retains maximum spread,
buildup, recovery and firing RNG calls. Precision Spread also applies the
requested PB beta 2.1 pistol aim-reticle offset `(1, 1)` while drawing the
original pistol HUD, including converter-owned stock copies. Stock placement
returns when the option is off; custom HUDs, authored nonzero offsets and zoom
overlays are preserved. This is an optional competitive correction, not a
change to the original Xbox baseline. Enabled matches require peer support
and a host acknowledgement; active match rules are locked. Local map filters
do not restrict joining, and Join In Progress defaults On to retain the prior
host behavior. These are requested options, not reference-Xbox corrections.

The original pistol reticle sprite is 28 by 28 texels, with aiming ticks at
`(13, 13)` and a draw center at `(14, 14)`, supporting the single-view `(1, 1)`
correction. Production draw fixtures cover both bitmap paths, rule gating,
converted tag identities and immutable map tags. In-game aiming still needs
validation; split screen halves reticle size while keeping integer HUD offsets,
so exact split-screen alignment is not established by these fixtures.

Camo: Normal / Hardcore is a separate requested gametype rule, default Normal.
Hardcore neutralizes the interpolated active-camouflage RGB tint in the shared
ANGLE/Native Metal draw path; refraction, visibility, duration, reveal and
regrowth retain their existing behavior. Campaign remains unchanged. Saved
variants use a version-2 extension only when Hardcore camo is selected, and
enabled matches require camo capability confirmation from every player.

The requested pistol hollow-metal effect and dirt-only overshield material
changes are intentional content refinements of retail quirks. Loaded native
tags are changed selectively; source caches and custom authored effects remain
intact. See [the meeting implementation record](meeting-fixes-2026-10-05.md)
for exact boundaries, evidence and remaining work.

Performance Options permits host-selected match timers, timer announcements,
spawn markers, silent movement/weapon-ready sounds, fixed 33ms input delay
and Hardcore precision spread and camo.
All modifications default off; sounds default Normal. Timer audio/display
preferences are local. These limited
options do not authorize other Performance Build mechanics, weapon changes or
a different tick rate. Original PC v7 caches remain unsupported.

## Defaults and comparison profile

At the user's request, native Split Screen and System Link hosts may explicitly
start a match with one joined local player, including a team game with only one
team occupied. The existing **START GAME** action begins the normal countdown.
This is an intentional extension to original Xbox lobby rules, selected by the
host's action each match. Waiting alone still leaves the countdown stopped;
normal automatic countdowns and two-team requirements for multiple players
remain in place. System Link uses the existing Join In Progress setting for
later arrivals. The lobby retains its original widgets, fonts and countdown,
with a short solo-start directions prompt.

The production-function fixture `tools/test_solo_multiplayer_start.py` checks
solo and team countdowns in both modes, host request authorization, readiness,
pause and precache gates, the start-message transition, and the unchanged
legacy two-player requirement; it does not establish native gameplay or Xbox parity.

Local Mac validation passes 42 focused network tests, the dual-renderer build
and strict app-signature verification. Isolated native UI playtests on Battle
Creek/Slayer observed one-player lobbies remaining idle, then the existing
START action beginning 10-second Split Screen and 30-second System Link
countdowns and spawning into gameplay. Both instances exited cleanly. Evidence
is in `build/macos/solo-multiplayer-validation/runtime/result.json`; physical
controllers, cross-platform late joining and reference-Xbox comparisons were
not exercised by these runs.

Controller settings offer **Menu Repeat: Original / Faster** as an intentional
local UI preference. Original retains the reconstructed 250 ms cadence and its
existing event-queue and stick-edge behavior. Faster moves once immediately,
waits for a 500 ms hold, then repeats every 100 ms for arrows, D-pad directions
and sticks in menus and the on-screen keyboard. Its separate keyboard edges
preserve discrete taps; release, stick neutral or a new stick direction resets
the hold timer. It defaults Original and applies only after Accept, with no
simulation, gameplay-button or network-rule change. See
[menu repeat](menu-repeat.md) for the option and validation boundaries.

New configurations set `display.high_res_hud`, `display.interpolation` and
`display.direct_camera` to `false`. Existing choices are preserved. Simulation
stays at 30 Hz; high-refresh rendering can be appropriate, with interpolation
and input response assessed separately.

At the user's explicit request, Video exposes optional replacements as
**Asset Quality: Original / Upres**, with Original as the default. Native Metal now
supports the same optional assets as ANGLE, including meter coverage blending.
These are hand-authored PC-derived reconstructions in Xbox layout, not a new
stock-artwork baseline. Upres also enables font substitutes and 34 menu title
images from the selectively ported upstream font work. Menu layout/navigation
and postgame panel artwork remain original. Original mode and unsupported-text
or localized/modified bitmap fallbacks remain available. See
[asset provenance and comparison](high-resolution-hud.md).

### Native Metal presentation experiment

Local commit `1dc7043f58b6a1d9a2be3fb02ae9bb7e66db88de` adds optional pre-HUD world
anti-aliasing. Decision: adopt for testing on `codex/metal-renderer-poc`, with
`display.anti_aliasing="off"` as the native default. The opt-in `"fxaa"` mode
intentionally changes world edge pixels and subsequent frame-history colors.
It preserves the authored textures, geometry, shaders and HUD assets, and the
original 30 Hz simulation. This permits a native-resolution smoothing comparison
without replacing original artwork.

Validation: 185 targeted CPU tests, 103 isolated GPU readbacks and 15 atomic
rejections pass. Off preserves all 378 ordered original replay checkpoints.
Eight bounded fullscreen profiles pass API validation and full-size captures;
timing observations range from 52.06 to 63.86 render FPS at 3600x2338, with
approximately 30 simulation Hz. The observations do not establish retail pixel
parity, a reliable isolated AA cost or sustained 120 FPS. See
[the experiment and evidence](metal-anti-aliasing.md).

Historical status at the AA checkpoint: experimental branch and draft PR #4,
pending review; the installed ANGLE app then retained its existing build. The
normal Mac app integration below supersedes that installation status. The
upstream reviewed-through and integrated baseline above remain separate.

### Native Metal in the normal Mac app

Integration commit `b4f6ee72b85edaa11afb17647ce40b56398610be` bundles both Mac renderer pairs, with
ANGLE as the default and Native Metal as an experimental option. The original
**Settings → Game Settings → Video** menu and macOS **Settings…** share
`display.renderer` in the saves folder's `config.toml`. Native Metal reveals
resolution, FPS limit and anti-aliasing controls; VSync and Smooth Motion remain
available for both renderers. Renderer, resolution and anti-aliasing choices
apply on the next launch. Original assets, HUD and 30 Hz simulation remain
intact. See [renderer settings and ANGLE recovery](metal-native-build.md).

Validation: 124 focused CPU tests pass (the final run is recorded in
`build/macos/dual-renderer-tests-attempt1/execution.json`). Local dual build
`build/macos/dual-renderer-build-attempt1` and installation
`build/macos/dual-renderer-install-attempt1` both exited 0; strict codesign
verification passed. Native startup at 3600x2338, the four-row ANGLE and seven-row
Native Metal Video layouts, Cancel/Accept staging and saved choices, and macOS
pending-renderer status were visually checked. A focused isolated-copy check
confirmed macOS changes appear on reopening Video and restart switches in both
directions; the final native launch used a 3600x2338 drawable and exited 0.
`build/macos/dual-renderer-runtime-attempt1/result.json` binds those observations
and logs (SHA-256 `64d08cd250a28f3dab0b45a26839c4b366b77a66206096d2f0d0ffa4bace23cb`).
The test copy has its own app identity, isolated saves and no game URL handlers;
no unrelated multiplayer process was stopped. These functionality checks do not
establish full gameplay coverage, retail fidelity or sustained 60/120 FPS.
The prior AA GPU/replay proof remains a separate historical checkpoint.

Integration status: merged into main through [PR #4](https://github.com/pfista/halo-og/pull/4)
at commit `4dab1a0f6028e3ecd139d5a9be67c269011b7c65`, following user approval.
ANGLE remains the default; Native Metal remains selectable and experimental.
Release publication is pending separate authorization.

The merge preparation retains main's Controller and Multiplayer settings,
Original/Faster menu repeat, current invite handling and shared Apple service
imports alongside Mac renderer controls. Integration merge `b9ef6717` passes
166 focused renderer/settings checks (three platform-specific skips) and the
216-test desktop CI fixture suite (one platform-specific skip). Fixture fix
`24d3131f` removes the duplicate cursor enum that failed the previous Linux and
Windows jobs after their builds succeeded. These checks cover merge compatibility;
they do not resolve the newly reported tearing or establish new performance results.

After the merge, the delayed Windows CI build exposed a header omission already
present on main: shared input/menu sources could not find `controller_settings.h`.
Follow-up fix `4507185a` adds the existing-style Windows forwarding header and
extends the generated-search-path probe to every affected consumer. Both Windows
header tests pass, producing a real i686 MSVC COFF object and preserving Windows
CRT isolation. This build correction changes no gameplay or rendering behavior.

Windows URI registration follow-up `d5ea36de1e8cae23c16de5baf973da84de7c8c7d`
corrects a second compilation error: the production
`_CRT_NON_CONFORMING_SWPRINTFS` flag selects the older `swprintf` signature,
while the URI registration calls supplied a buffer size. The three calls now
use the explicitly bounded `swprintf_s` entry point and check formatting failure
before using registry paths or labels. The shared legacy CRT flag remains intact.
See [Microsoft's CRT signature documentation](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/sprintf-sprintf-l-swprintf-swprintf-l-swprintf-l?view=msvc-170).

Validation: the 43-check invite, presence and Windows-header suite passes with
two native OS checks skipped on Mac. Both portable and native Windows URI fixtures
consume the actual build macro; the portable fixture models the old declaration
and exercises failures in all three formatting operations. A negative control
against the prior source reproduces all three size-to-format pointer errors.
The real Windows registry/launcher exercise remains in Windows CI. This correction
preserves URI names, Unicode executable paths and command quoting; it changes no
gameplay or Metal rendering behavior.

Use [xbox-ntsc.toml](../port/macos/profiles/xbox-ntsc.toml) with the existing
`HALO_SCREEN_WIDTH=640` override for an isolated 4:3 comparison. This 30 FPS
reference is separate from normal-play performance choices. Native maps can use
128 MiB disk caches; the original 22 MiB tag arena and Xbox build limits remain.

## Reconstruction target and validation

### Public System Link discovery

The October 4, 2026 integration adds Halo OG's own HTTPS directory in the existing
Xbox-style System Link list on all three desktop ports. It does not import an
upstream UI, alter simulation or gameplay packets, or add a gameplay relay.
LAN/private invites retain their original native paths. Public hosting is on
by default with a config opt-out; a different compatible HTTPS directory can
replace the default. Upstream-only MQTT discovery remains a separate adapter task.

The listing is display data. Joining uses the existing authenticated P2P peer,
matches its real advertisement by identity/address, then applies the existing
protocol and options checks. Fixtures cover those guards, expiry, deduplication,
timeout, and cancelled/stale events. A local Mac build and live host listing/
renewal passed. A two-instance invite match was not established; physical Mac,
Windows and Linux/NAT playtests remain necessary. See [discovery](system-link-directory.md).

### Native gameplay corrections

The native inventory receiver retains a spawn snapshot until its unit and
weapons exist. Weapon/slot/grenade changes use the existing reliable stream
after object creation; ammunition keeps its 10 Hz cadence. This corrects a
reproduced client ordering failure that otherwise waits for the next refresh.
It does not change loadouts or the original weapon-ready animation. A prolonged
host-side spawn delay has not yet been reproduced.

Teleports split native prediction history and clear pre-jump host prediction
anchors. Corrections following an actual scenario source/target pair restore
the original destination latch. Fixtures reproduce the doubled displacement
and immediate return trip, and preserve ordinary movement corrections plus
the original 0.5-unit trigger and 1-unit destination search.

Weapon creation and ready/equip request their projectile trail textures through
the existing nonblocking cache. A production-function fixture demonstrates
that a cold texture suppresses the first draw and that an early completed read
permits it. The reported first-shot visual symptom still needs physical
playtesting; an early request cannot guarantee immediate disk completion.

These are native integration corrections, with no wire-layout/version change
and no change to the 30 Hz simulation, trail tags/lifetimes, ammunition rules,
or original teleport cooldown. Regression fixtures run on Mac, Windows and
Linux; they do not establish reference-Xbox or cross-platform gameplay parity.

### Safe upstream reliability corrections (October 4, 2026)

The selective OpenCE port adopts loaded-map cleanup (`601a4c1f`), null-client
frame recovery (`7e00135d`) and only the invalid full-datum killer/assist guards
from `809408c6`. Valid-player credit, betrayal penalties and message behavior
remain covered by the existing production functions. Slot reuse, queue replacement
and weapon-pickup rule changes remain excluded.

Local commits: loaded-map cleanup `26654de7`; null-client recovery
`15fdbf00`; stale killer/assist guards are included in the commit
containing this ledger (`fix(game): ignore stale players in kill and assist scoring`).
The same 81 targeted tests pass again during October 5 commit preparation.

The three new production-function fixture suites pass 31 tests. They reproduce
the original stopped-map and missing-client failures with negative controls,
exercise deleted and generation-mismatched attacker references, and cover valid
scoring, load failures and consecutive transitions. Combined with the targeted
network, inventory, teleport and timing suites, 81 tests pass locally on macOS.
The new suites are also wired into Mac, Linux and Windows CI; those remote runs
have not been executed for this port.

In the October 4 pre-commit validation, the native Mac guest/app built successfully
and the installed app passed strict signature verification. The installed guest
hash matched the built guest and `BuildInfo.txt` identified the source as
containing local changes. An isolated 75-second native map-cycle smoke passed,
with one acknowledged transition from Prisoner to Chill Out, 3,660 rendered frames
and a clean exit. The two-instance LAN smoke exited cleanly without assertions,
but the client remained in discovery and no match started. Consecutive-match
network behavior is therefore unverified;
these fixtures and build results do not certify original-Xbox parity. Generated
evidence is under `build/macos/safe-upstream-*`.

### Native Metal packet-copy performance (October 5, 2026)

Decision: adopt on the local `codex/metal-performance-pass` branch. Payload
appends initialize alignment and trailing padding, then copy every payload byte,
avoiding the redundant full-payload zero write. Immediate packet ownership,
resource lifetimes, rejection behavior and all wire bytes remain unchanged.
The original assets and 30 Hz simulation are unaffected; ANGLE stays the default.

Validation: ten focused CPU tests pass. The actual ILP32 mocked-import fixture
passes 2,862 room/builder cases and 56 exact payload/padding cases. Its closure is
`build/metal-poc/payload-padding-ilp32-attempt1/closure.json`
(SHA256 `da8cab138eed341685b8140bfd157211a8f58525742556a540a5df4b2310d293`).
This verifies byte preservation and rejection boundaries, not achieved FPS.
Implementation commit: `08ef504a2f0e99289cd5d5ccdb6c324eccff3580`. It has not been
integrated into main or released. The upstream reviewed-through remains separate.

### Native Metal draw-pass performance (October 5, 2026)

Decision: adopt conservative reuse on `codex/metal-performance-pass`. Consecutive
blend-disabled draws share a pass only with identical attachments and no query.
Every original draw state is rebound; all non-draw operations, attachment
changes, queries, blended draws, packet end and failures close the pass. Full
atomic preflight, shader code and synchronous completion remain intact. Broader
reuse changed 384 captured color bytes and was rejected; blended draws retain
their original per-draw store boundaries.

Validation: the production ordered replay preserves all 378 color/depth/stencil/
query checkpoints and the coalesced 126-draw replay preserves all six final
outputs with Metal API validation. Proofs are
`build/metal-poc/performance-pass-ordered-frame-attempt2/comparison.json`
(SHA256 `4419afa815ed140d480dd192bede3a82d9e535272430ff7009fb5ee71db96c00`)
and `build/metal-poc/performance-pass-coalesced-frame-attempt2/result.json`
(SHA256 `4fbdb0c7661768bc9907df72ce894fed0f36c52736043d73ce8b0631eeafb313`).
The focused GPU fixture has 13,608 identical checkpoint bytes and reduces
32 passes to 25. The final union of targeted CPU suites passes 80 tests;
the production FXAA regression also passes all 103 readbacks with no failure.

The warmed headless A/B/B/A replay has 5.386 ms median host cost before and
4.006 ms after (25.6% lower), with exact final bytes in every run. This is one
captured 640x480 frame; baseline drift, gameplay packet building, presentation
and native-resolution performance remain separate. All ten subsequent
fullscreen comparisons passed in
`build/macos-metal/performance-pass-attempt1/matrix-attempt5/matrix.json`
(SHA256 `5ee5bb8bb61f94e81c4eba557da49575c7710551a91fc0527f616c86680b2395`).
At native 3600x2338, the stationary campaign opening averages 35.59 versus
38.98 FPS with VSync off and 34.48 versus 39.03 with it on. Solo Chill Out
averages 147.32 versus 153.71 uncapped/off and about 118.7 in both on runs.
The campaign reproduces long stalls; solo Chill Out does not reproduce the
multiplayer report. Both native hosts use the same new guest, so this measures
host pass reuse. ANGLE uses the much smaller original logical picture, and
stationary/audio-disabled runs exclude combat, traversal and input latency.
Earlier locked, launcher-identity and lost-focus attempts remain invalid. See
[measurement scope and reproducible commands](metal-performance.md).

The benchmark now freezes selected binaries inside a private app with a unique
bundle identifier, the selected executable name, no URL handlers and isolated
relaunch settings. This prevents activation from opening an extra primary Halo
copy. Host/guest bytes remain unchanged; whole-app signing is not claimed.
Launcher correction: `de52b60a7c5de19223de1ed5c2d4a74afe088b88`, with 16 focused
CPU tests. Later optional shader metrics preserve older log readers.

Implementation commit: `69deba4f697707d3ac36b6721e1629760d4fb6c0`. Integration remains
local and unreleased; ANGLE remains the default, and original assets, HUD and
30 Hz gameplay remain unchanged. This does not certify retail parity or sustained
60/120 FPS in the reported multiplayer/campaign scenes.

### Native Metal shader compilation reuse (October 5, 2026)

Decision: adopt on `codex/metal-performance-pass`. Reuse successfully compiled
functions only for identical source bytes, shader stage and math/invariance
contracts, within one Metal device/context. Packet-private candidates publish
after complete validation; ordinary rejection cannot publish them. Cache
allocation failure may change cache warmth, but not live resources, queries or
sequence state. Each cache is bounded by 256 entries and 8 MiB of source keys;
this is not a bound on driver code memory. Shared-stage cleanup retains other
live programs' warm pipelines. Shader text, draw order, resource validation and
synchronous completion remain unchanged.

Validation: the focused CPU/GPU proof passes with API validation and exact
controlled render bytes. The rebuilt real ILP32 ordered replay preserves all
378 attachment/query checkpoints, and the coalesced replay preserves all six
final outputs. Proofs:
`build/metal-poc/function-cache-ordered-frame-attempt1/comparison.json`
(SHA256 `9ff3b0db2d4e2b55eadda8e3119f912e2db1e458b9254ab51ee60ade6b76b42b`)
and `build/metal-poc/function-cache-coalesced-frame-attempt3/result.json`
(SHA256 `7a9c8bc41f6bef0c1162926557de06364245cc5beaf64cf4ddc18c5931e8bc15`).
A four-run campaign A/B/B/A avoids 316/400 and 356/440 reported compilation
requests. Run FPS is 30.52, 38.17, 42.69 and 43.92; substantial baseline drift
prevents a precise causal FPS claim. Long hitches and the 60 FPS goal remain.
See [contracts, proofs and timing scope](metal-function-compilation-cache.md).

Implementation commit: `fca76d55c8e3b7e576abc9d677a674d25ec9a845`. Local and
unreleased; ANGLE remains the default and original assets/gameplay are preserved.

### Coherent catch-up interpolation (October 5, 2026)

Decision: correct a shared ANGLE/Metal Smooth Motion timing mismatch. Object
snapshots are captured every simulation tick, while camera samples are captured
on rendered frames. After a frame advances several ticks, their endpoint pairs
span different durations. The current-tick fallback now applies to camera,
object nodes, first-person pose and shader time together, persists across
zero-tick frames, and resumes normal blending on the next tick. First/reset/
re-enabled frames seed current raw nodes without advancing gameplay. Internal
unsigned tick comparisons handle wrap. No camera cadence, assets, settings or
30 Hz simulation changes are introduced; Smooth Motion off keeps raw rendering.

Validation: 11 focused CPU tests compile the production interpolation unit and
object accessor with 32-bit-normalized counters and ASan/UBSan. A negative
control reproduces the camera/object separation. Tests cover tracking across
1/2/1/3-tick gaps, zero-tick frames, resets/toggles, cuts, teleports, direct
facing, network corrections and wrap. The final targeted CPU union passes 94
tests at the initial motion implementation, increasing to 95 after the
benchmark's explicit interpolation setting. Runtime confirmation of the
reported Pelican jump remains separate.
During fallback, a new camera cut may wait for the next advancing tick; see
[presentation tradeoff and test scope](render-interpolation-catch-up.md).

Implementation commit: `19743f0a33363c3db4d82e1f43cffde28f98bf62`. Local and
unreleased; this fixes the optional interpolation path rather than establishing
retail cinematic parity. Upstream reviewed-through is unchanged.

### Performance pass merged-main build (October 5, 2026)

Local source `7ad3151071a23565ae38d41b9de1ddda6519558e` merges main into
`codex/metal-performance-pass`; it does not merge these changes into main or
publish a release. The dual Mac build, all 95 targeted renderer/motion CPU tests
and 36 main compatibility tests pass. Installed signature, BuildInfo source and
ANGLE/native guest hashes match. The initial personal settings checksum changed
during installation; that comparison is retained as failed rather than claimed
unchanged. The isolated content tests leave the current personal settings intact.

All four installed original B30 content checks pass: each renderer with Smooth
Motion off/on, original map hashes, advancing native ticks/draws, API validation
and clean host/guest exits. Matrix:
`build/macos-metal/performance-pass-attempt1/final-motion-content-smoke-attempt1/motion-content-smoke.json`
(SHA256 `b1791f4ba8c8e2a42609b9c518e8873f8a26ae6f16bc738c3ba23238b6fb5edb`).
These are bounded loading checks with no foreground, FPS, visual-motion or
retail-parity gate. A preceding motion timing attempt lost foreground and remains
failed, with its timings discarded. Full-resolution campaign 60 FPS, reported
multiplayer Chill Out drops and visual resolution of the Pelican jump remain
unverified. ANGLE remains the default; the original assets and 30 Hz schedule
remain intact.

### System Link teammate split-screen prototype (October 6, 2026)

At the user's explicit request, a host-selected **Team Split Screen** option
appears in the authored gametype Rules menus when Team Play is enabled. It
defaults Off. The native presentation adds one camera-only, living, on-foot
remote teammate view for machines with one real local player. Input ownership,
30 Hz simulation, hit authority and network scheduling remain unchanged; it
uses already received unit state, including the existing 5 Hz scheduling tier.
The prototype adds no camera packets or network capability and carries the
host's setting in unused upper bits of the existing complete game variant.

This is an intentional presentation departure, not an Xbox fidelity correction.
The teammate pane omits weapon hands, HUD, zoom, camera effects, atmospheric fog
and weather. Audio remains the real player's audio, and distant effects remain
limited by the existing local visibility coverage. Off retains the ordinary
HUD count and rendering paths. Matching prototype builds are needed for every
participant to see teammate panes; older builds ignore the option.

Compiled fixtures validate target restrictions, stable player/controller
ownership, staged menu accept/cancel, rule-byte preservation and renderer
isolation, including GLES/Metal/retail defines with ASan/UBSan. A local ANGLE
four-process 2v2 enabled session and Off control passed, with all eight clean
exits and all role screenshots inspected. The final HUD build also passed an
enabled Native Metal four-process 2v2 session. This does not establish separate
machine LAN/WAN performance, smooth 5 Hz presentation or retail parity.
Local and unreleased. See [prototype behavior and validation](teammate-split-screen.md).
No upstream baseline or reviewed-through revision changes.

### Original target

The executable target is Xbox build **2342**, `cachebeta.exe`, SHA-256
`4cc87b45f721270392a96f1674ed2b5cd4a7bb4355faeab4531d1cf1884d9520`.
The original data baseline is USA NTSC cache v5 build **2276**,
`01.10.12.2276`. These are different identifiers.

Matching an Xbox executable and reproducing its feel on native ARM/x86 require
different evidence. Physical controllers, reference-Xbox comparisons,
campaign/save coverage, multiplayer timing and cross-platform play need runtime
validation. Compilation, cache hashes and short smoke runs alone do not certify
retail fidelity. Use repeatable timing measurements and isolated saves; keep
generated evidence outside the source tree.
