# OpenCE compatibility branch

`pfister/open-ce` starts from complete OpenCE upstream
`76addf661f02e2fd090d7b00f9dd12c29e562a9b` and reapplies Halo OG main
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
- Use OpenCE's actual protocol-20 codecs, co-op messages, host settings,
  admission, transport and shared gameplay readers. Never make clients lie
  about their protocol version to admit a mismatched peer.
- Received host rules take precedence over conflicting local game behavior.
  A client must honor custom loadouts, radar restrictions and other shared
  settings even when our own hosting menus do not expose them.
- OG-specific input delay, Hardcore, Fiesta and expanded arsenals retain their
  own capability checks. Stock OpenCE clients must reject incompatible modes.
  Extended sessions use advertisement `0x8014` and the separate `HPCE` control
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
- Focused gameplay/menu/input/audio/save/invite/transport/asset tests pass.
  Apple, Linux and Windows CI include explicit OpenCE contract fixtures;
  native-only probes skip on unsupported platforms. Linux/Windows/mobile full
  builds and an actual mixed-client game were not executed locally.

Future upstream refreshes can rebase this new patch series from the recorded
upstream base onto the new upstream head. Fold subsequent `main` changes in as
a reviewed delta from the recorded main snapshot; do not merge main's old
ancestry back into the compatibility branch. Resolve shared gameplay/protocol
conflicts with the branch policy above and repeat tests plus mixed-peer play.
