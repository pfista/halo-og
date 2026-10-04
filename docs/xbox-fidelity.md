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
| `c9ee319ab5f2964a32372fffdc7756111e39727d` | Adopt v11 wire record, original defaults, advertisement metadata and received action-only input. Exclude PC menus, added modes, bindings/save format and associated dependencies. Integrated as `694cc79d`; network fixtures cover wire layout and admission before precache. |
| `2b0103a0ef2f46f3713d7e045436c5283668f9a6`, `383355381c3f92ae8ce6c9c79cbe84924856aa2f` | Exclude expanded score menus. |
| `e8e0c2215ab6871bbe6f855f67b3459d94817b35` | Defer compiler include-path changes required only by the excluded PC menus. |
| `62b630a2610e7c0df88ffa43d6f03914cb35345e` | Exclude new weapon/loadout policy. |
| `23b542601f2ca505c7a0143703e92fbda6075e18` | Exclude altered infinite-grenade and unarmed-loadout rules; retain existing Xbox behavior and mixed-build admission gates. |

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
hosts original-rule defaults and rejects active PC options it does not implement
before applying settings or loading maps. Use matching builds and maps.

PB capability flag `0x04` is separate from the in-progress flag `0x02`.
Options-off games advertise stock v11; enabled PB games advertise `0x800B` and
require supporting peers. v10/PB-v10 builds must update. Mixed upstream/fork
games with five or more players must leave Infinite Grenades off.
See [networking](../port/linux/NETCODE.md), [PB Options](performance-options.md)
and [playtesting](playtesting.md) for implementation and player guidance.

## Optional competitive features

PB Options permits host-selected match timers, timer announcements, spawn
markers and silent movement/weapon-ready sounds. All modifications default off;
sounds default Normal. Timer audio/display preferences are local. These limited
options do not authorize other Performance Build mechanics, weapon changes or
a different tick rate. Original PC v7 caches remain unsupported.

## Defaults and comparison profile

New configurations set `display.high_res_hud`, `display.interpolation` and
`display.direct_camera` to `false`. Existing choices are preserved. Simulation
stays at 30 Hz; high-refresh rendering can be appropriate, with interpolation
and input response assessed separately.

Use [xbox-ntsc.toml](../port/macos/profiles/xbox-ntsc.toml) with the existing
`HALO_SCREEN_WIDTH=640` override for an isolated 4:3 comparison. This 30 FPS
reference is separate from normal-play performance choices. Native maps can use
128 MiB disk caches; the original 22 MiB tag arena and Xbox build limits remain.

## Reconstruction target and validation

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
