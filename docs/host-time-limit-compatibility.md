# Joining hosts with additional game settings

This describes how the client treats protocol-11 host options that Halo OG's
own hosting menus do not set. It was written for mixed-host testing with
upstream builds, which is [no longer a goal](xbox-fidelity.md#protocol-compatibility).

The protocol-11 diagnostic helper recognizes these host-authoritative options:

- Nonnegative match time limits and vehicle respawn times.
- Friendly fire on, off, shields only, or explosives only.
- Nonnegative friendly-fire respawn penalties.
- Automatic team balancing, encoded as a valid boolean.

The fields remain in the received settings record; they do not change Halo OG's
hosting defaults or introduce the upstream PC menus. A record with any other
active option is refused, as described below.

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

The client refuses a settings record whose options it does not implement:
radar players, per-team vehicle sets, custom loadouts, unknown weapon sets, and
negative timers or out-of-range friendly-fire and team-balancing values. It
explains the unsupported option and leaves its current settings untouched. The
check runs before the record can select a cache, precache a map or change
state, alongside the protocol/version, PB capability, packet reassembly,
machine/player count, difficulty, map-name and map compatibility checks.
Hosting defaults remain original.

From October 4 to November 19, 2026 this check was switched off at the user's
request for live testing against upstream hosts, and every protocol-11 option
passed admission. It is enforced again now that Halo OG has its own network
version.

Any enabled PB option advertises the practice version (`0xCE26`); 33ms delay
also requires confirmed delay support on every peer, so older PB builds cannot
join an enabled-delay match. See [Performance Options](performance-options.md#host-authority-and-v11-compatibility).

Validation: the production settings/reassembly and postgame-state functions pass
the protocol test harness under AddressSanitizer and UndefinedBehaviorSanitizer.
Tests cover timer boundaries, all four friendly-fire modes, combined and
fragmented host settings, refusal of unimplemented options and of malformed
negative timers/enums/booleans, unchanged hosting defaults, rejection before
precache or state changes, and applying the end state
only after valid host game state. The production player-attachment function is
tested for both valid team switches, invalid host teams and free-for-all games.
Actual upstream-host timed matches, respawns and team changes still need live
playtesting.
