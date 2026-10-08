# Experimental camo and overshield synchronization

`network.experimental_powerup_sync` defaults to **false**. This opt-in experiment
addresses off-host camo/overshield copies falling while the host keeps them
suspended, and resting objects missing periodic network refreshes. The saved
preference belongs to the host installation, independent of Pro/Precision Spread
and saved gametypes. Joining clients automatically follow the host's session
choice, including Off, even if their own saved preference differs.

## Enable or disable

Open **Game Settings → Multiplayer → Powerup Sync (Experimental)** and choose
On or Off, then **Accept**. Cancel discards the draft. The choice is captured
when hosting starts and stays fixed throughout that hosted session, including
its lobby and subsequent matches. If changed while already hosting, the value
shows **current > next**; leave the session and host again to apply the new
preference. This avoids changing the experimental replication behavior halfway
through a match or while another machine is loading.

Joined clients see **On/Off (Host)** and cannot edit that row. The received value
is temporary: it never changes the client's saved preference, and leaving the
session restores the local preference for future hosting. Clients do not need
to enable the experiment themselves.

The equivalent config entry is in the host's existing `[network]` section:

```toml
[network]
experimental_powerup_sync = true
```

Edit the existing section rather than adding a duplicate `[network]` header.
On Mac, the usual file is
`~/Library/Application Support/Halo OG/config.toml`; on Linux/Windows it is next
to the executable, and on Android it is in the selected game-data folder.
Configuration-file edits require restarting the game. Menu edits save the same
key without requiring a restart, but an existing hosted session still requires
rehosting to adopt the new choice.

To restore the previous replication paths, choose Off and rehost. For a file
edit, set the value to `false` (or remove the key), then restart and host again.
There are no map, tag or save-format changes to undo. Original object packets
retain their layout; a separate reliable control carries the host's choice.
Compatible clients acknowledge that choice before loading readiness can admit
them to initial object replication. An On session requires this support and
rejects older builds. Off sessions retain compatibility with older peers; new
clients joining an older host use Off for the experiment.

The implementation is marked `EXPERIMENTAL_POWERUP_SYNC` in
`port/linux/game/network_objects.c`, with a dedicated regression fixture in
`tools/test_experimental_powerup_sync.py`. Its separate commit can be reverted
to remove the original repair, configuration registration, tests and
documentation. To remove the complete feature after this menu extension, revert
the menu/session-control commit first, then `b5cd49e1`.

## Scope and evidence

The receiver repair is limited to world equipment whose tag identifies active
camouflage or overshield. It applies the host's resting state at creation and on
updates that would otherwise be skipped because the position is already close.
Rest-state transitions and resting refreshes also receive the host's linear and
angular velocity. A positional correction clears stale client surface/object
contacts only when the corrected powerup moves beyond the existing tolerance.
Carried/attached equipment and other object types retain their existing receive
behavior. The host's resting-object sweep visits slots in order using its
existing limit of four refresh states per tick; this scheduling repair includes
other resting objects eligible for that sweep.

Host spawning, gravity, collision, pickup decisions, powerup duration, respawn
timing and the 30 Hz simulation are unchanged. The host-selected Off path retains
the previous receive behavior and refresh traversal. This is an experimental native
replication correction; it has not been established as original Xbox behavior.

Source tracing identified missing rest-state application on creation, a
same-position early return that skips rest-state transitions, and a refresh
cursor that can repeatedly omit resting slots. These explain plausible failure
paths, but the reported missing first spawn still needs a multiplayer capture
to distinguish a falling/hidden copy from failed object creation.

Run the focused source fixtures with
`python3 -m unittest tools.test_experimental_powerup_sync tools.test_powerup_host_setting`.
They cover enabled and disabled creation/state paths, input rejection, deleted
objects, stale support contacts, resting-refresh coverage within the existing
budget, session ownership and the reliable policy protocol. Settings fixtures
in `tools.test_device_settings` and `tools.test_game_settings` also cover saving,
Cancel, host-controlled clients and the current/next display.

## Multiplayer validation still required

Compare disabled and enabled runs with a host and off-host client on Pat Race
and Worthy, including the first spawn, suspended waiting period, drop, pickup,
second respawn and joining after the match starts. Give the client the opposite
saved preference in both On and Off runs: its menu should display the host's
value, remain read-only and restore its own preference after leaving. Confirm
that host edits take effect only after rehosting, that On rejects an older
client and that Off still admits it. Shoot or disturb a suspended
powerup and verify that both machines follow the host's falling/landing state.
Also check stock floor camo/overshield, other equipment and weapons, resting
bodies/vehicles, and a powerup that landed on a moving object before resync.
Record both viewpoints and the setting on each machine. Production-function CPU
fixtures and compilation do not establish multiplayer behavior or Xbox parity.
