# System Link teammate split-screen prototype

In **Multiplayer → Edit Gametypes**, edit the variant's **Game Options** and
open **Step 2: Set Game Rules**. Set **Team Play** to **Yes**, then **Team Split
Screen** to **On** and save the variant. CTF always has teams, so its Rules
menu includes the option directly. The System Link host selects that variant.
The default is Off.

Each prototype-enabled machine with one local player reserves its own view above
one remote teammate pane throughout the active match. Targets must remain on the
player's current team. When death, departure, team change or a vehicle leaves no
eligible on-foot teammate, the lower pane stays black and shows **TEAMMATE
UNAVAILABLE**. Respawning restores the view without resizing the local viewport
or changing its HUD layout. A larger team shows one eligible teammate, keeping
that target while it remains valid. Machines with multiple local controllers
retain their existing player ownership and local split-screen layout.



This is a camera-only proof of concept. The teammate pane has a name label,
fixed unzoomed field of view, no weapon hands, no HUD, no camera shake or damage
flashes, and no atmospheric fog or weather. Existing local particle visibility
can omit effects far from the local player. Audio and input remain attached to
the real local player. Vehicle-following cameras are outside this prototype.

The camera is reconstructed from the teammate's unit and aim already received
by the game. The host's existing visibility/distance scheduling is unchanged,
including remote updates as low as 5 Hz. The pane can look delayed or choppy,
and it does not exactly reproduce the teammate's own locally predicted screen.
No video, camera packets, new network capability, protocol version, update-rate
change, gameplay timing or hit-authority change is introduced.

The host option is saved and sent inside the existing complete 104-byte game
variant. A complete `0x53535000` marker occupies the currently unused upper
24 bits of `universal_variant.flags`; the low byte's Xbox rule flags and the
separate Performance extension remain intact. Unknown upper-bit extensions are
preserved and cannot be overwritten by this option. Existing transport already
copies these bytes. Older builds ignore the presentation option and show their
usual view; use matching prototype builds to see teammate panes on every
machine. This prototype does not enforce feature support across participants.

The renderer uses a separate display-target identity and never assigns the
teammate a local player/controller index. Teammate rendering skips local HUD,
first-person animation, sound, screen-effect, widget and debug callbacks.
The player's body is excluded only from its own first-person pane.

## Interactive local session

Double-click `tools/macos_teammate_view_runner.command`, or run:

```sh
python3 tools/macos_teammate_view_runner.py
```

The runner opens four windowed 640×480 instances from the installed
`/Applications/Halo OG.app`, automatically hosts a private Blood Gulch Team
Slayer game with Team Split Screen On, and assigns two Red and two Blue players.
Native Metal is the default; use `--renderer angle` for ANGLE. Click a game
window to control that player. All players use normal controls; players whose
windows are inactive remain idle with keyboard/mouse input. Only the Red host
plays audio. The setup script does not shoot, kill, teleport, gather players,
pick up equipment or inject bot/controller input. Its large test score target
avoids ordinary short match endings.

Four separate save/data directories and four different **already configured**
IPv4 addresses keep the fixed game ports apart. The runner never adds network
interfaces or changes personal saves, settings or already running apps. It
disables public discovery, clipboard joining, UPnP, background downloads and
update checks. Private encrypted invites connect only this session's clients.
An existing game using the host's port 5150 or a chosen client's port 5151
causes a clear preflight error; the runner leaves that game running.

The default session directory is a fresh timestamped directory under
`build/macos/`. The terminal prints each role, PID and log path plus a session
stop command. Leave the terminal open and press **Ctrl-C** to stop only these
four instances. The session runs until stopped; `--seconds 90` provides a
bounded run. To stop it from another terminal, use the printed command:

```sh
python3 tools/macos_teammate_view_runner.py --stop /path/to/session/session.json
```

Use `--dry-run` to inspect all configurations and port availability without
creating files or opening windows. `--output /path/to/fresh-directory` chooses
the session location; existing directories are rejected. `--hide-clients`
shows only the Red host, and `--addresses HOST,RED_CLIENT,BLUE_1,BLUE_2` selects
four existing addresses explicitly. `--data-root /path/to/GameData` chooses a
read-only folder containing `maps/ui.map` and the chosen multiplayer cache;
`--map chillout` selects another installed stock map.

## Validation

Run the compiled selection/ownership and renderer-isolation fixtures:

```sh
python3 -m unittest tools.test_teammate_view tools.test_teammate_view_render tools.test_teammate_view_menu tools.test_macos_teammate_view_smoke
```

Run four real one-player processes in a 2v2 match, with isolated saves and
existing configured IPv4 addresses, including an Off control:

```sh
python3 tools/macos_teammate_view_smoke.py --output /tmp/halo-team-view-smoke
```

The script never adds network interfaces. Its logs check two players on each
team, four separate owning machines, one actual local player per process,
host-option propagation and rendered pane counts. Captured frames need visual
inspection. One-Mac tests do not establish physical LAN/WAN latency or sustained
performance. Death/respawn, team changes and invalid targets are also exercised
by the compiled selection fixture.

The 2026-10-06 local ANGLE proof completed enabled and disabled 2v2 sessions
with four isolated processes in each session. All eight processes exited
successfully, with no assertions or crashes. Logs confirmed stable machine,
controller and player ownership, one real local player per process, the host's
option on every participant, and only a same-team remote target when enabled.
Screenshots from all eight roles were visually inspected. Evidence is in
`build/macos/teammate-view-proof-2/validation.json` and the enabled/disabled
role directories. The disabled session retained ordinary full-screen views.

The final HUD-adjusted build also completed an enabled four-process 2v2 Native
Metal session. All four processes selected Native Metal, exited successfully,
and passed the same ownership, team, host-option and view-target checks. Evidence
is in `build/macos/teammate-view-metal-final-proof/validation.json`.

The actual native Slayer Rules menu was also checked with isolated saves:
Team Play No hides the row; Yes reveals it; the Off/On selection and help are
readable; Accept and Save Changes retain On when the custom variant is reopened.
Screenshots are in `build/macos/teammate-view-menu-proof/`. The compiled menu
fixture covers all five supported game modes and Cancel behavior.

This validates rendering and existing variant transport, rather than smooth
5 Hz presentation or performance on separate computers. There is a second
world-render pass, so graphics and visibility work increase even though each
pane occupies half the display. The prototype adds no per-frame network payload
or extra gameplay update packets.

The local dual-renderer app is installed at `/Applications/Halo OG.app`, with
the previous app backed up. Installed guest hashes match the tested final build,
the signature verifies, and the 71 checked personal configuration/save files
retain their pre-install hashes. The installation check is recorded in
`build/macos/teammate-view-install-final-validation.json`.
