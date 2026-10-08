# Experimental camo and overshield synchronization

`network.experimental_powerup_sync` defaults to **false**. This opt-in experiment
addresses off-host camo/overshield copies falling while the host keeps them
suspended, and resting objects missing periodic network refreshes. It is a local
installation preference, independent of Pro/Precision Spread and saved gametypes.

## Enable or disable

Quit Halo OG on the host and each participating test client. In the existing
`[network]` section of each installation's `config.toml`, set:

```toml
[network]
experimental_powerup_sync = true
```

Edit the existing section rather than adding a duplicate `[network]` header.
On Mac, the usual file is
`~/Library/Application Support/Halo OG/config.toml`; on Linux/Windows it is next
to the executable, and on Android it is in the selected game-data folder.
Restart the game and begin a new match. Configuration is cached for the process;
editing the file during a match does not change the running experiment.

To restore the previous code paths, set the value to `false` (or remove that
key), restart each installation and start a new match. There are no map, tag,
save-format or network packet changes to undo. The host needs the option for the
refresh sweep repair; clients need it for the powerup receive repair. Existing
peers use the same protocol, but a disabled peer retains its previous behavior.

The implementation is marked `EXPERIMENTAL_POWERUP_SYNC` in
`port/linux/game/network_objects.c`, with a dedicated regression fixture in
`tools/test_experimental_powerup_sync.py`. Its separate commit can be reverted
to remove the experiment, configuration registration, tests and documentation.

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
timing and the 30 Hz simulation are unchanged. The default-off path retains the
previous receive behavior and refresh traversal. This is an experimental native
replication correction; it has not been established as original Xbox behavior.

Source tracing identified missing rest-state application on creation, a
same-position early return that skips rest-state transitions, and a refresh
cursor that can repeatedly omit resting slots. These explain plausible failure
paths, but the reported missing first spawn still needs a multiplayer capture
to distinguish a falling/hidden copy from failed object creation.

Run the focused source fixtures with
`python3 -m unittest tools.test_experimental_powerup_sync`. They cover enabled
and disabled creation/state paths, input rejection, deleted objects, stale
support contacts and resting-refresh coverage within the existing budget.

## Multiplayer validation still required

Compare disabled and enabled runs with a host and off-host client on Pat Race
and Worthy, including the first spawn, suspended waiting period, drop, pickup,
second respawn and joining after the match starts. Shoot or disturb a suspended
powerup and verify that both machines follow the host's falling/landing state.
Also check stock floor camo/overshield, other equipment and weapons, resting
bodies/vehicles, and a powerup that landed on a moving object before resync.
Record both viewpoints and the setting on each machine. Production-function CPU
fixtures and compilation do not establish multiplayer behavior or Xbox parity.
