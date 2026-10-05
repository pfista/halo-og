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
| `0182da817285b67eee8264663ca79f7c32d66b5e` | Exclude replacement fonts and OpenCE titles; retain original presentation. |
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

## Optional competitive features

The October 5 meeting-feedback implementation adds an explicit Hardcore
precision rule, default Off, independent of Stock/Practice aid presets. It
changes only pistol/unscoped-sniper initial spread and retains maximum spread,
buildup, recovery and firing RNG calls. Enabled matches require peer support
and a host acknowledgement; active match rules are locked. Local map filters
do not restrict joining, and Join In Progress defaults On to retain the prior
host behavior. These are requested options, not reference-Xbox corrections.

The requested pistol hollow-metal effect and dirt-only overshield material
changes are intentional content refinements of retail quirks. Loaded native
tags are changed selectively; source caches and custom authored effects remain
intact. See [the meeting implementation record](meeting-fixes-2026-10-05.md)
for exact boundaries, evidence and remaining work.

Performance Options permits host-selected match timers, timer announcements,
spawn markers, silent movement/weapon-ready sounds, fixed 33ms input delay
and Hardcore precision spread.
All modifications default off; sounds default Normal. Timer audio/display
preferences are local. These limited
options do not authorize other Performance Build mechanics, weapon changes or
a different tick rate. Original PC v7 caches remain unsupported.

## Defaults and comparison profile

Controller settings offer **Menu Repeat: Original / Faster** as an intentional
local UI preference. Original retains the reconstructed 250 ms cadence; Faster
opts into 100 ms held navigation for arrows, D-pad directions and sticks in
menus and the on-screen keyboard. It defaults Original and applies only after
Accept, with no simulation, gameplay-button or network-rule change. This does
not alter the original event-queue or stick-edge behavior. See
[menu repeat](menu-repeat.md) for the option and validation boundaries.

New configurations set `display.high_res_hud`, `display.interpolation` and
`display.direct_camera` to `false`. Existing choices are preserved. Simulation
stays at 30 Hz; high-refresh rendering can be appropriate, with interpolation
and input response assessed separately.

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

Integration decision: user-approved for main through [PR #4](https://github.com/pfista/halo-og/pull/4).
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
