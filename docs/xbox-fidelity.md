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

**Reviewed through:** `23b542601f2ca505c7a0143703e92fbda6075e18`.
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
v10/PB-v10 builds must update. For mixed cybersecurity tests, leave PB Options
Stock and Input Delay Off. Games with five or more players should leave
Infinite Grenades off because the native Xbox rule still differs even though
the best-effort gate admits that setting.
See [networking](../port/linux/NETCODE.md), [PB Options](performance-options.md)
and [playtesting](playtesting.md) for implementation and player guidance.

## Optional competitive features

PB Options permits host-selected match timers, timer announcements, spawn
markers, silent movement/weapon-ready sounds and fixed 33ms input delay.
All modifications default off; sounds default Normal. Timer audio/display
preferences are local. These limited
options do not authorize other Performance Build mechanics, weapon changes or
a different tick rate. Original PC v7 caches remain unsupported.

## Defaults and comparison profile

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

Status: installed locally, experimental branch and draft PR #4 pending review;
not merged or released.

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
