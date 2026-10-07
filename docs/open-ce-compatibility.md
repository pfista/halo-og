# OpenCE compatibility branch

`pfista/open-ce` starts from complete OpenCE upstream
`4e8ed2f196e0edd1f2830a4de9841686aabbf466` (checked October 7, 2026) and reapplies Halo OG main
`20787ea03e7d99e261cd525a009f9aa11b8d5f41` as a fresh patch series. The original
main history remains available unchanged. The net overlay includes changes
previously made inside merge resolutions, which replaying only individual
non-merge commits would miss.

The shared integration baseline is `c55e4e2b9d90550b0e761eb78dfe9d7c74880cb9`.
Future updates must preserve the complete new upstream baseline, audit the
overlay for shared-rule and packet conflicts, and repeat interoperability checks.
Do not treat a conflict-free application as proof of compatibility.

## Behavior policy

- Keep Halo OG's original Xbox menus, HUD, fonts, local input choices, native
  Metal/ANGLE support, map tools and original hosting defaults.
- Use OpenCE's actual protocol-22 codecs, co-op messages, host settings,
  admission, transport and shared gameplay readers. Never make clients lie
  about their protocol version to admit a mismatched peer.
- Received host rules take precedence over conflicting local game behavior.
  A client must honor custom loadouts, radar restrictions and other shared
  settings even when our own hosting menus do not expose them.
- OG-specific input delay, Hardcore, Fiesta and expanded arsenals retain their
  own capability checks. Stock OpenCE clients must reject incompatible modes.
  Extended sessions use advertisement `0x8016` and the separate `HPCE` control
  magic, so older protocol-11 OG clients cannot falsely acknowledge support.
- OpenCE's canonical weapon sets 11, 12 and 13 are Covenant, Classic and Heavy.
  OG's restored Uncut and All sets use 14 and 15 on this branch. Do not infer
  whether an old saved ID 11 meant OG Uncut or OpenCE Covenant.

## Separate installations

The Mac app is **Halo OG OpenCE.app**, bundle `local.halo.og.opence`, with saves
under `~/Library/Application Support/Halo OG OpenCE`. It does not automatically
import Halo OG or Halo CE Universal profiles. It keeps the existing game artwork.
Android uses application ID `com.halo.decomp.opence`; the default iOS bundle ID
is `local.halo.og.opence.ios`. Platform app containers therefore remain separate.
Windows saves use `%APPDATA%\\Halo OG OpenCE`; Linux uses
`$XDG_DATA_HOME/halo-og-opence` or `~/.local/share/halo-og-opence`. Explicit save
paths remain supported, but automatic profile imports are disabled.

OS handlers use `halo-og-opence://`. Shared invitation text uses the standard
`halo://join/<code>` format understood by OpenCE. The compatibility parser also
accepts pasted `halo-og://` and `halo-og-opence://` links. Keep its local handoff
endpoint separate from the normal Halo OG instance.

These experimental builds do not use main's automatic release feed. Build
artifacts remain manual updates. Publishing tags, releases or services requires
the user's separate explicit authorization.

## Custom Edition maps

The upstream loader reads genuine CE version-609 caches and their `bitmaps.map`,
`sounds.map` and `loc.map` resources from `custom_maps` or the configured CE
installation. It converts supported tag, model, geometry, texture and sound
data in memory while loading; the files on disk are unchanged. This is separate
from Halo OG's offline tools that rebuild Xbox version-5 community caches.
See [the upstream CE loader guide](custom_edition_caches.md) for limits.

CE level names keep their `custom_maps\\` namespace throughout discovery,
network settings and cache loading. Halo OG full arsenal caches apply to Xbox
maps; CE maps retain their own weapon tags and use standard weapon sets.
Ordinary Xbox community maps continue to use Halo OG's managed map storage.

The desktop Mac guest now has the upstream 512 MiB game-memory budget and
256 MiB texture cache. Its image moved to `0xA0000000`, with ABI `0x10002`,
and the CE tag region at `0x40440000` is reserved without overwriting another
mapping. Android and iOS retain their 128 MiB guest window and image placement.
Both ANGLE and Metal apply CE texture channel mappings.

## Original System Link discovery

The original System Link list combines LAN advertisements, Halo OG's HTTPS
directory and OpenCE's signed public MQTT listings. Upstream's listing provider
validates protocol, signature, key hash, sequence and expiry. The menu adapter
also checks bounded names/maps/player counts and deduplicates by authenticated
host identity. Hidden lists stop both Internet discovery providers.
OpenCE permits empty server-name and game-type labels. Display those as
`OpenCE Game` and the signed engine's game type rather than hiding the game.

Selecting a compatible remote row starts the existing invite connection, then
waits for the authenticated host's address and actual game advertisement.
Directory/display metadata never supplies authoritative gameplay settings or
bypasses protocol, capability or map admission.

Normal Halo OG protocol-11 directory entries remain visible as closed
`OG v11: ...` rows. Join those with the normal Halo OG app. Password-protected
OpenCE entries appear as closed `Password: ...` rows; a host-provided standard
invite can join them. Password entry inside the Xbox list is not implemented.

## Validation boundary

Compile the Mac guest and host against the actual upstream game code, run
production packet/admission fixtures and retained feature tests, and verify
default Xbox menu/HUD routing. Before declaring supported crossplay, test the
exact upstream revision with both host directions, identical stock/community
maps, differing host rules, five-plus players, deaths/respawns and pickups,
late joins/reconnects/new games, and private/public/password invitations.

A successful build or wire fixture does not establish physical mixed-client
play, complete campaign/co-op coverage or retail Xbox fidelity. Record actual
verification and any unresolved boundary here before distributing this branch.

## October 6 verification

These checks describe the previous protocol-20 baseline at `76addf66`.

- Both full Apple Silicon game images and native hosts compile: ANGLE and
  native Metal. Local SDL was built for macOS 26; the linker warns about the
  port's older macOS 14 deployment target. This run validates the current Mac,
  not execution on older macOS releases.
- Native ABI probes pass: address rebasing, allocator/write watch/threading,
  UDP/peer validation, Discord IO, invite delivery and SDL audio handoff.
- Protocol fixtures freeze 108 upstream declarations/codecs plus 136 unit/input
  wire vectors, including truncated-record boundaries. Optional OG control
  packets are ignored safely by compiled stock receiver fragments.
- ANGLE and Metal each completed a 45-second encrypted two-instance Blood
  Gulch Slayer run on one Mac. Both peers simulated players and exchanged
  updates, with clean exits and no assertion/fault. Metal captures show the
  original Xbox pregame lobby and in-game HUD. These used two compatibility
  builds, not an unmodified stock OpenCE peer.
- The separate dual-renderer `build/macos/Halo OG OpenCE.app` was packaged with
  an ad hoc signature and passed deep/strict signature verification. Its bundle
  ID, private URL handler, source/guest hashes and packaged broker list were
  checked. A further 45-second encrypted two-instance run through the packaged
  native menus also passed. No personal profile was imported and the app was
  not installed or published.
- Focused gameplay/menu/input/audio/save/invite/transport/asset tests pass.
  Apple, Linux and Windows CI include explicit OpenCE contract fixtures;
  native-only probes skip on unsupported platforms. Linux/Windows/mobile full
  builds and an actual mixed-client game were not executed locally.
- The 14 OpenCE/discovery/UI fixtures pass, plus the production signed-listing
  checker (zero failures). They cover provider withdrawal, invalid records,
  identity/token deduplication, full list capacity, legacy/locked rows,
  authenticated-address join and timeout. Public listings were verified through
  production fixtures; a live stock-host listing and mixed-peer join remain
  part of the interoperability playtest.

## October 7 refresh verification

- Rebasing the overlay from `76addf66` onto complete upstream `4e8ed2f1`
  retains upstream protocol 22 and the committed main snapshot `20787ea0`.
  Later uncommitted work in the main checkout is separate from this snapshot.
- Both full Mac renderer/guest pairs build with the new memory ABI. Each
  completed a 45-second encrypted two-instance Blood Gulch Slayer run, including
  deaths/respawns, with clean exits, exchanged updates and no assertion/fault.
  Both peers were compatibility builds; an unmodified OpenCE peer was not used.
- A read-only run loaded the original Xbox System Link screen and displayed
  nine live public games, captured in the original UI, without joining or
  advertising a game. The optional-label fix has a production adapter regression.
  All eight protocol-20 listings examined during diagnosis had empty game-type
  labels, explaining why the previous adapter hid them.
- Production listing parsing, Ed25519 signatures, topic/key binding and
  600-second freshness checks verified eleven protocol-22 games on each of
  the four packaged brokers. The OG HTTPS directory returned HTTP 200 with
  an empty list at that moment. Game counts are time-sensitive observations.
- CE cache/resource/malformed-data fixtures passed 126 tests, with four tests
  skipped for optional real game data. Native Metal CE channel tests matched
  all three channel orders with zero float error on the current Mac.
- ABI/link and native Darwin allocation, protection, write-watch and mapping
  probes pass, including collision rejection for the separate CE tag region.
  Production wire/admission/transport-origin fixtures and retained map,
  menu, Fiesta, interpolation, save and packaging checks pass.

Real CE map gameplay, mixed-client play against unmodified OpenCE, complete
co-op coverage, other operating systems and older macOS execution remain
outside this local verification. The macOS 26 SDL/macOS 14 linker warning
described above remains applicable.

Future upstream refreshes can rebase this new patch series from the recorded
upstream base onto the new upstream head. Fold subsequent `main` changes in as
a reviewed delta from the recorded main snapshot; do not merge main's old
ancestry back into the compatibility branch. Resolve shared gameplay/protocol
conflicts with the branch policy above and repeat tests plus mixed-peer play.
