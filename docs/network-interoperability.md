# Multiplayer interoperability

This document records Halo OG main's historical protocol-11 review. On
`pfister/open-ce`, the complete upstream protocol-20 gameplay and network code
is integrated. See [the branch policy and validation boundary](open-ce-compatibility.md)
for current behavior; the historical limitations below do not describe this
branch's implemented host-option support.

Halo OG aims to find and join cybersecurity games while retaining original Xbox
graphics, presentation and its own menus. Reference their connection and
discovery protocols independently of their PC-style UI. **Check in with the
user before implementing discovery UI**, then place it in original Xbox-style
Multiplayer/System Link menus, as agreed. OS-native settings windows are not
the intended game-discovery interface.
No server-browser UI or public-listing backend is imported by this review.

The original source audit compared Halo OG `2c8a111b8292b9ef474e02c1fc8a95414baf51e6`
with cybersecurity `193cbf59c7e483386538fa34e28fb2503ab79a4b`; links to those
revisions below preserve that review evidence. The current boundary also
includes the October 4 directory/input-delay commits and
best-effort host-settings commit `6de3e8d221208e85c9340a8b58c70ddcddcbe044`. The host-settings review refreshed upstream
through `23b542601f2ca505c7a0143703e92fbda6075e18`, independently selecting the
client team-attachment correction. See [the settings review](host-time-limit-compatibility.md)
and [the integration ledger](xbox-fidelity.md#upstream-integration).
These source findings do not establish physical mixed-client play.

## Current connection boundary

| Layer | Source findings | Remaining validation |
| --- | --- | --- |
| LAN/session wire format | Both use native protocol 11, search/message version 2, distributed flag `0x01`, and the same session and 28-byte PC-options layouts. Movement, inputs, object, inventory, damage and ping records match. | Both host directions, joins, reconnects, postgame and new games. |
| Private Internet invites | Invite shape, signaling topics, key derivation and version-2 UDP/KCP tunnel framing match. Upstream's MQTT 5 transport retains MQTT 3.1.1 fallback; broker connections negotiate separately. | Real broker/NAT combinations and both host directions. |
| Public discovery | Halo OG's own HTTPS directory is integrated into the Xbox-style System Link list. Upstream signed MQTT listings use the existing private-invite format, but remain a separate, unintegrated adapter. | Physical desktop/NAT tests of Halo OG discovery; a focused upstream adapter review if requested. |
| Maps | Local cache/header validation checks supported Xbox cache versions and build identifiers. It does not compare a peer's exact map bytes. | Players must use the same converted map revision. Our catalog checksum only verifies our downloaded file. |
| Optional rules | Halo OG hosting defaults remain original. The current client deliberately admits all differing v11 gametype options for best-effort testing, without implementing every local rule. | Actual upstream-host timed matches, respawns, team changes, radar, vehicle placement and weapon behavior. |

There is no active source-SHA or exact client-build admission check in the
current native configurations. Matching protocol numbers and wire layouts do
not establish compatible gameplay for every host setting. Removing the
gametype-options gate does not remove protocol/version or PB capability checks,
packet reassembly, machine/player counts, difficulty, map-name or local map
compatibility checks; these still precede precaching and received-state changes.
See [upstream admission](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/source/networking/network_client_manager.c#L2963),
[Halo OG's historical option gate](https://github.com/pfista/halo-og/blob/2c8a111b8292b9ef474e02c1fc8a95414baf51e6/source/networking/network_client_manager.c#L1278)
and [accepted defaults](https://github.com/pfista/halo-og/blob/2c8a111b8292b9ef474e02c1fc8a95414baf51e6/source/game/game_variant_options.h#L27).

## Original presentation and shared rules

Halo OG can retain original fonts, HUD artwork, graphics and sounds while using
shared network records. Local interpolation and direct-camera preferences can
also differ, though they change apparent input latency and need separate feel
testing. Shared movement, weapons, damage and match rules must remain consistent
with the host's authoritative state.

Some host options may work through replicated state without exposing those
options in our hosting menus. For example, upstream's `no_map_weapons` occupies
our existing padding byte and its item-spawn reader is host-only. Timers,
vehicle spawning and team allocation also have host-authoritative paths. The
current best-effort test build admits the whole PC-options record at the user's
request, but admission does not establish compatible behavior for every field.
The diagnostic helper still classifies unsupported and invalid settings
without blocking a join. See the
[option layout](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/source/game/game_engine.h#L215)
and [host-only item spawning](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/source/game/game_engine.c#L8245).

Other settings still need client adapters. Friends-only radar requires filtering
contacts by viewer team; accepting that setting without its reader would reveal
enemy contacts. Unarmed actions and pickup/weapon-ready differences interact
with local prediction and first-person presentation. Infinite grenades with
five or more players differs from the Xbox suppression rule we retain. These
settings now pass best-effort admission even though the local behavior can
differ, so use original settings for the baseline mixed-client playtest.
See [upstream radar filtering](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/source/game/game_engine.c#L4707)
and [grenade behavior](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/source/game/game_engine.c#L3192).

Keep Halo OG **Performance Options: Stock** for mixed protocol-11 tests. PB-enabled
sessions advertise `0x800B` and require supporting peers; current cybersecurity
clients reject that extended version. Do not disguise those games as ordinary
protocol-11 sessions. Input Delay: 33ms also needs confirmed delay support on
every connected peer; older PB builds cannot join an enabled-delay match.
Keep Input Delay and Hardcore Off for stock cybersecurity tests. See [Performance Options](performance-options.md) and the
[fidelity policy](xbox-fidelity.md#protocol-compatibility).

## Public discovery reference

The reviewed upstream implementation publishes signed retained MQTT listings
at `hceu/3/lobby/s/<key-hash>` and queries at `hceu/3/lobby/q`. Listings yield
ordinary `halo://join/<host-hash+token>` invites. Reusing this requires the lobby
state machine, MQTT retained/QoS/will handling, Ed25519/Monocypher support and
our native build/bridge integration. Their Halo PC-style screen is not a
dependency. See the
[listing protocol](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/port/linux/src/p2p_lobby.c#L4)
and [signaling](https://github.com/cybersecurity/halo-ce-universal/blob/193cbf59c7e483386538fa34e28fb2503ab79a4b/port/linux/src/p2p_signal.c#L4).

Listings advertise base protocol 11 and basic session fields, without map
hashes or the full PC/PB capability set. Future adaptation must filter
unsupported sessions and avoid listing PB-active Halo OG games as stock 11.
Halo OG's separate HTTPS directory and current hosting settings are documented
in [public System Link discovery](system-link-directory.md). Adapting upstream
discovery still requires the separate product check-in before implementing its
menu flow.

## Mixed-client playtest plan

Before claiming supported crossplay, test the exact cybersecurity release in
both host directions with Mac, Windows and Linux Halo OG clients:

- Stock maps plus identical Downrush and Derelict revisions.
- Two, four and five-plus players; original defaults, best-effort differing PC
  settings, PB-off acceptance and PB-on rejection. Keep Infinite Grenades off
  for the baseline five-plus-player test, then record the known differing rule
  separately if testing it.
- Late joins, reconnects, reused player slots, postgame and starting another game.
- Death/respawn, weapon pickups and ammo, damage, objectives, timed games,
  team changes, teleporters and local/remote sniper trails.
- Private invites across common brokers and NAT setups.
- Separate 30/120 FPS presentation comparisons with input-age and host-authority
  traces under comparable network conditions.

The 30 Hz simulation and current distributed prediction do not alone reproduce
the Xbox System Link timing model. Keep physical fidelity evidence separate
from wire compatibility and compilation. See [netcode](../port/linux/NETCODE.md)
and [playtesting](playtesting.md).
