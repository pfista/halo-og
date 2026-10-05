# Joining hosts with additional game settings

The protocol-11 diagnostic helper recognizes these host-authoritative options:

- Nonnegative match time limits and vehicle respawn times.
- Friendly fire on, off, shields only, or explosives only.
- Nonnegative friendly-fire respawn penalties.
- Automatic team balancing, encoded as a valid boolean.

The fields remain in the received settings record; they do not change Halo OG's
hosting defaults or introduce the upstream PC menus. Current best-effort client
admission is broader than this helper, as described below.

The distributed host decides when the match ends and replicates its postgame
state. `game_engine_update` already prevents clients from independently ending
the match, and `game_engine_read_network_state` applies the host's end state.
This makes a host's time limit compatible without adding a second local clock
that could end a client's game early. The upstream countdown display is not
included by this change.

`network_objects_handle_changes` already applies the host's reliable object
deletions and creations, including respawned vehicles. `network_damage_deals`
reports client hits and lets the host decide damage; received damage and health
state determine the client's result. Players only spawn when the host supplies
their new unit. The local respawn countdown can finish before a host's extra
penalty expires, but it cannot cause an early spawn.

Automatic team balancing also needs a narrow client correction: when attaching
a newly spawned unit, take its valid host-assigned team before setting unit
ownership. This is the `network_player_attach_unit` change from upstream's
mixed `c9ee319ab5f2964a32372fffdc7756111e39727d`, independently checked against
`23b542601f2ca505c7a0143703e92fbda6075e18`. Only the client attachment correction
is adopted; the host-side rebalance algorithm and PC menus are not imported.

For immediate live testing, the user explicitly requested disabling the client
settings compatibility gate. All received protocol-11 gametype options now pass
admission, including radar, per-team vehicles, custom loadouts, PC weapon sets,
and large-game infinite grenades. The compatibility helper remains available
for review but no longer controls admission. This does not implement missing
local simulation or presentation behavior; initial vehicle placement and weapon
rules may still differ. The helper's negative-timer, enum and boolean checks are
diagnostic only; the admission path deliberately does not call it. Protocol/
version, PB capability, packet reassembly, machine/player counts, difficulty,
map-name and map compatibility checks remain enforced before settings can
change state or start precaching. Hosting defaults remain original. This is
best-effort test admission, not supported mixed-host gameplay for every option.

Use Performance Options Stock, Input Delay Off and Hardcore Off when testing current cybersecurity
hosts. Any enabled PB option advertises `0x800B`; 33ms delay also requires
confirmed delay support on every peer, so older PB builds cannot join an
enabled-delay match. See [Performance Options](performance-options.md#host-authority-and-v11-compatibility).

Upstream was refreshed and remains at
`23b542601f2ca505c7a0143703e92fbda6075e18` (protocol 11). These rejections came
from the fork's deliberate settings gate after importing the wire record.

Validation: the production settings/reassembly and postgame-state functions pass
the protocol test harness under AddressSanitizer and UndefinedBehaviorSanitizer.
Tests cover timer boundaries, all four friendly-fire modes, combined and
fragmented differing host settings, malformed negative timers/enums/booleans in
the diagnostic helper, unchanged hosting defaults, structural rejection before
precache or state changes, and applying the end state
only after valid host game state. The production player-attachment function is
tested for both valid team switches, invalid host teams and free-for-all games.
Actual upstream-host timed matches, respawns and team changes still need live
playtesting.
