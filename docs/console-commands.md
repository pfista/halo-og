# Halo OG console reference

This guide describes the Halo OG console source in `pfista-halo-macos`, reviewed
October 8, 2026 at revision **a1367ec5**. It includes
all 418 registered HaloScript functions, all **442 distinct built-in variable
names** (443 registry slots because `decals` appears twice), the native PB commands,
and `ban`. Map-authored scripts and globals add names that depend on the loaded map.

The quick reference explains useful everyday commands. The complete catalogs
below retain the engine's signatures and help text. Registration does not prove
that every old Xbox developer feature works on every native renderer or platform;
known no-ops and variables with no backing storage are marked. This is a source
reference, not a claim that every command has been exercised in a running game.
An installed build from another revision may have a smaller command set.

## Contents

- [Opening and using the console](#opening-and-using-the-console)
- [Syntax and parameter types](#syntax-and-parameter-types)
- [Everyday commands](#everyday-commands)
- [Native PB controls](#native-pb-controls)
- [Map, campaign and practice examples](#map-campaign-and-practice-examples)
- [Objects, players and cameras](#objects-players-and-cameras)
- [Multiplayer authority and bans](#multiplayer-authority-and-bans)
- [Persistence and configuration](#persistence-and-configuration)
- [Complete function catalog](#complete-function-catalog)
- [Complete variable catalog](#complete-variable-catalog)
- [Sources and verification](#sources-and-verification)

## Opening and using the console

| Action | macOS default |
| --- | --- |
| Open or close console | **F2**; use **Fn–F2** if the keyboard uses F2 for a system function |
| Close console | **Escape**, or Enter with an empty input line |
| Execute | **Enter** or keypad Enter |
| Complete names and show matches | **Tab** |
| Recall recent commands | **Up / Down**; eight commands are kept in memory |
| Release or recapture mouse | **F12** |

On other native desktop ports, the default console key is the backtick/grave key.
On Mac that key defaults to holding the scoreboard. `bindings.console` in
`config.toml` can change the console binding; choose a keyboard key distinct from
the scoreboard binding. Some laptops require Fn with function keys.

Type `pb` for native PB status and help. For a scripting function, use:

```text
help "game_speed"
help "object_create"
```

`help` describes one **function**. It does not describe console variables, `pb`,
`performance_options`, or `ban`, and an unknown name produces no help text.
`script_doc` writes or overwrites **`hs_doc.txt` in the game data root** with all
built-in function signatures and descriptions. It omits variables and native
commands. Tab completion also includes names from the loaded map.

## Syntax and parameter types

There are three kinds of input:

| Kind | Example | What happens |
| --- | --- | --- |
| Native control | `pb timer on` | Runs the PB command parser. Use lowercase and no parentheses. |
| HaloScript function | `show_hud false` | Calls a function. `(show_hud false)` is equivalent. |
| Console variable assignment | `display_framerate true` | Sets a registered variable. `(set display_framerate true)` is equivalent. |

A bare variable name evaluates the variable, but the console does not
automatically print every returned value. Use **`inspect`** when you need visible
output (offline or as host):

```text
inspect display_framerate
inspect (game_time)
inspect (list_count (players))
inspect (game_difficulty_get_real)
```

Do not write `(display_framerate true)` or `(cheat_deathless_player true)`:
those are variables, so the parenthesized form must use **`set`**. Nested
function calls need parentheses. Functions and built-in variable names are
case-insensitive; native `pb` syntax is case-sensitive. Map script names are
case-sensitive. Use the documented spelling for map content.

Enter **one command per line**. In the current parser, **any semicolon anywhere
causes the whole line to be ignored**, including a semicolon inside quoted text.
Do not append comments or join commands with semicolons. Parenthesized `begin`
can sequence expressions for offline/host scripting.

| Parameter type | How to read it |
| --- | --- |
| `boolean` | `true` or `false` (also `on` or `off`) |
| `real` | Decimal number, e.g. `0.5` |
| `short` / `long` | Integer; short is 16-bit and long is 32-bit in this engine |
| `string` | Text; quote it when it contains spaces |
| `expression` | A value or nested call, e.g. `(game_time)` |
| `game_difficulty` | `easy`, `normal`, `heroic`, `legendary` |
| `team` | `default`, `player`, `human`, `covenant`, `flood`, `sentinel`, `unused6`–`unused9`; these are scripting allegiances, not multiplayer team colors |
| `ai_default_state` | `none`, `sleep`, `alert`, `move_repeat`, `move_loop`, `move_loop_back_and_forth`, `move_loop_random`, `move_random`, `guard`, `guard_at_position`, `search`, `flee` |
| `actor_type` | `elite`, `jackal`, `grunt`, `hunter`, `engineer`, `assassin`, `player`, `marine`, `crew`, `combat_form`, `infection_form`, `carrier_form`, `monitor`, `sentinel`, `none`, `mounted_weapon` |
| `hud_corner` | `top_left`, `top_right`, `bottom_left`, `bottom_right`, `center` |
| `object`, `unit`, `vehicle`, etc. | An existing object, authored object name, or an expression returning that type |
| `object_list` | A list expression such as `(players)` |
| `object_name`, `starting_profile`, `trigger_volume`, `cutscene_flag`, camera point, AI, etc. | A name authored into the loaded map; Tab helps find names |
| `sound`, `effect`, `object_definition`, other tag types | Loaded map tag references; arbitrary files on disk are not automatically available |
| `void` return | The command performs an action; it has no value to inspect |

Angle brackets in the catalog are placeholders; do not type them. Repeated
`<real>` or `<short>` parameters have an order defined by the description or
implementation. `[]` means optional and `...` means a repeated sequence.
Timing values explicitly described as **ticks** use the 30 Hz simulation:
30 ticks = one second at normal game speed. Some APIs use seconds, frames,
normalized fractions or raw vitality instead; follow the individual command.

## Everyday commands

| Input | What it does | Joining player? |
| --- | --- | --- |
| `display_framerate true` | Shows FPS at bottom right, averaged over roughly half a second. Use `false` to hide. | Yes |
| `help "game_speed"` | Prints function syntax and help. | Yes |
| `script_doc` | Writes the full function reference to `hs_doc.txt`. | Yes |
| `cls` | Clears console text. | Yes |
| `print "Hello"` | Prints a line. Avoid literal percent signs: this legacy function treats text as a printf format. | Yes |
| `version` | Prints engine build version information. | No |
| `show_hud false` / `show_hud true` | Hides / restores the local HUD. | Yes |
| `show_hud_help_text false` / `true` | Hides / restores HUD help text. | Yes |
| `hud_show_crosshair false` / `true` | Hides / restores the crosshair. | Yes |
| `hud_show_health false` / `true` | Hides / restores health panel. | Yes |
| `hud_show_shield false` / `true` | Hides / restores shield panel. | Yes |
| `hud_show_motion_sensor false` / `true` | Hides / restores motion sensor panel. | Yes |
| `sound_enable false` / `sound_enable true` | Disables / enables the local sound manager. | Yes |
| `pb status` | Shows the host's PB settings and timer/audio diagnostics. | Yes |

There is currently **no console command or variable that displays ping**.
`display_framerate` is FPS, and `debug.network_latency` is a file setting that
simulates network delay for testing.

`sound_set_gain` edits a loaded sound tag's gain and the original help discourages
using it. It is not a general volume slider. Use the game's Audio settings for
master, music, effects, dialogue and timer volumes.

## Native PB controls

These controls operate independently of HaloScript. Type exactly the following
raw lowercase forms; `(pb ...)` is not supported.

| Command | Meaning |
| --- | --- |
| `pb` or `pb help` | Status and usage |
| `pb status` | Status only |
| `pb timer on` / `off` / `toggle` | Show or hide elapsed match timer |
| `pb markers on` / `off` / `toggle` | Show or hide supported map item spawn markers |
| `pb audio on` / `off` / `toggle` | Enable or disable timer audio |
| `pb movement normal` / `self` / `silent` / `toggle` | Normal, Just Me, or suppressed movement sounds; toggle cycles through those modes |
| `pb weapons normal` / `self` / `silent` / `toggle` | Normal, Just Me, or suppressed weapon-ready sounds; toggle cycles through those modes |
| `pb default` or `pb stock` | Disable timer, markers and timer audio; use normal movement/weapon-ready sounds; preserve preselected match rules |
| `pb practice` | Enable timer, markers and timer audio; use normal movement/weapon-ready sounds; preserve preselected match rules |
| `pb pro` | Enable timer and timer audio, disable markers, and use Just Me movement/weapon-ready sounds; preserve preselected match rules |
| `pb timer`, `pb markers`, `pb audio`, `pb movement`, `pb weapons` | Inspect status without changing it |
| `performance_options` | Inspect status |
| `performance_options N` | Replace the entire option bitmask with a valid decimal sum of the option bits below |

Inspection works for joining players. Changes require an existing **multiplayer
host** and compatible joined peers, so they may be refused in a solo campaign.
Timer audio needs the complete timer recordings installed and the game restarted
after installation. **Team Slayer Pro** is locked; choose another gametype to
change its options. A refusal leaves the settings unchanged.

The numeric interface is an advanced alternative. Add the values for options
you want enabled; omitted bits are cleared:

| Bit value | Option |
| --- | --- |
| 1 | Match timer |
| 2 | Spawn markers |
| 4 | Timer audio |
| 8 | Silent movement |
| 16 | Silent weapon-ready sounds |
| 32 | One simulation tick of input delay, nominally 33 ms |
| 64 | Precision Spread |
| 128 | Fiesta starting equipment |
| 256 | Stronger Camo |
| 4096 | Just Me movement sounds |
| 8192 | Just Me weapon-ready sounds |

The allowed bitmask is **12799**. Choose one sound mode per role: combining
Silent movement (8) with Just Me movement (4096), or Silent weapon-ready sounds
(16) with Just Me weapon-ready sounds (8192), is rejected. Bits absent from the
table are also rejected.

For example, `performance_options 3` selects timer + markers, and
`performance_options 7` selects timer + markers + audio. These **replace** the
whole set, including match-rule bits. Prefer named `pb` controls to preserve the
current match rules. Numeric autocomplete currently suggests only 0–63; type
larger valid combinations directly.

Input Delay, Precision Spread, Fiesta and Stronger Camo are selected before the
match; changing those bits after starting is refused. `pb default`, `pb stock`,
`pb practice` and `pb pro` preserve them. Select Pro match rules in the gametype
editor before playing; `pb pro` changes only the aids and sound modes. There are
no named `pb delay`,
`pb hardcore`, `pb fiesta` or `pb camo` commands. Use the gametype editor for saved
rules. PB console changes update the active session and broadcast to peers;
they do not directly save a gametype profile or `config.toml`.

## Map, campaign and practice examples

These are for local play or the host. The joining-client console refuses them.

| Example | Meaning |
| --- | --- |
| `map_name "levels\a10\a10"` | Load the first campaign level from available game data |
| `map_reset` | Restart the current map from its beginning |
| `game_difficulty_set legendary` | Choose difficulty for the next loaded map |
| `inspect (game_difficulty_get_real)` | Print actual current difficulty; `game_difficulty_get` reports Normal when the actual setting is Easy |
| `game_speed 0.5` | Half simulation speed |
| `game_speed 1` | Restore normal simulation speed |
| `inspect (game_time)` | Print elapsed simulation ticks |
| `game_save` | Request a safe campaign save; gives up after eight seconds if unsafe |
| `game_revert` | Revert to the last campaign save, if available |
| `cheat_deathless_player true` | Prevent normal player death from damage; `false` disables |
| `cheat_infinite_ammo true` | Keep reserve ammunition and player grenade counts from being consumed; `false` disables |
| `cheat_bottomless_clip true` | Keep loaded magazine from draining; `false` disables |
| `cheat_super_jump true` | Increase player jump; `false` disables |
| `cheat_all_weapons` | Drop loaded weapons near the first spawned player unit |
| `cheat_all_powerups` | Drop entries from the map's cheat-powerup list; list may be empty |
| `cheat_all_vehicles` | Spawn entries from the map's multiplayer vehicle list near the first spawned player; campaign maps may lack that list |
| `cheat_active_camouflage` | Apply camo to the first spawned player unit |
| `cheat_active_camouflage_local_player 0` | Apply camo to local split-screen slot zero; indices are 0–3 |

Most booleans can be undone by replacing `true` with `false`. Spawned items,
vehicles, destroyed objects and save/revert operations are actions rather than
toggle settings; a subsequent `false` is not an undo. Deathless does not promise
protection against arbitrary map scripts removing or replacing an object.

`game_speed 0` freezes simulation; use `game_speed 1` to restore it. Arbitrary
negative or huge speeds are not documented as supported values.

`multiplayer_map_name "levels\test\bloodgulch\bloodgulch"` selects/pre-caches a
multiplayer map. It does **not** itself create a lobby or switch a host's live
match. Use the normal multiplayer menu for that. Campaign save commands and
debug `core_*` snapshots are separate features; `core_*` uses binary developer
state files and is not a normal player save workflow.

## Objects, players and cameras

Most entries in the full catalog serve map scripts. Names must exist in the
loaded scenario. A vehicle tag path is not a scenario object name.

```text
inspect (list_count (players))
object_create authored_object_name
object_create_anew authored_object_name
object_destroy authored_object_name
(unit_exit_vehicle (unit (list_get (players) 0)))
```

Replace `authored_object_name` with a real map object name. `object_create_anew`
destroys any existing instance before creating it. `(players)` is a list of
spawned player **unit objects**, not display names. Element zero is not guaranteed
to be your local player. `unit` casts an object to the unit type.

`unit_enter_vehicle <unit> <vehicle> "<seat_label>"` needs an existing vehicle
and its exact authored seat label; occupancy and seat compatibility apply.
`unit_set_current_vitality <unit> <body> <shield>` uses raw vitality values:
`1 1` does not universally mean full health and shield. Use an appropriate
authored starting profile with `player_add_equipment` when resetting loadout.

Camera commands have different purposes:

| Command | Purpose |
| --- | --- |
| `camera_control true` / `false` | Enable authored scripted camera / restore gameplay camera; this is not a free-camera toggle |
| `camera_set <camera_point> <ticks>` | Move to a map-authored camera point over a specified number of simulation ticks |
| `debug_camera_save` | Save camera position, direction and FOV to data-root `camera.txt` |
| `debug_camera_load` | Restore that camera file and put local player zero into flying-camera mode |
| `cheat_teleport_to_camera` | Teleport the first local spawned player, or its parent vehicle, to the camera; destination must be within the map BSP |

The registered `camera_set` API calls its duration ticks, but the current
implementation truncates the conversion to whole seconds: 15 ticks becomes an
immediate move, and 45 ticks becomes one second. Use multiples of 30 when a
whole-second camera transition is intended. See
[camera timing](../source/camera/camera_scripting.c#L282).

AI commands require authored encounters, squads, command lists and conversations.
An ordinary multiplayer map may contain none. Tag-literal commands resolve
through the map's script-reference table; a tag may be loaded yet unavailable
as a console literal. Use existing scenario names or typed map globals.

## Multiplayer authority and bans

A joining player's console has a strict expression allowlist in both lobby and
match. It is not sufficient for a command to sound read-only. Even `version`,
`game_time`, `inspect`, and unlisted variable reads are refused. Every unquoted
name in the expression must be allowed; quoted text in `help` and `print` is
accepted. Native PB status/help run before this script guard.

The allowed script names are:

```text
set cls help print
script_doc display_framerate framerate_throttle framerate_lock
rasterizer_fps_accumulate console_dump_to_file terminal_render screenshot_size
screenshot_count show_hud show_hud_help_text show_hud_timer
hud_show_crosshair hud_show_health hud_show_motion_sensor hud_show_shield
sound_enable sound_set_gain controls_swapped controls_enable_crouch
controls_enable_doubled_spin controls_swap_doubled_spin_state player0_look_yaw_rate player1_look_yaw_rate
player2_look_yaw_rate player3_look_yaw_rate player0_look_pitch_rate player1_look_pitch_rate
player2_look_pitch_rate player3_look_pitch_rate true false
on off
```

Cheats, simulation speed and drawing settings that reveal extra world geometry
are enforced back to permitted values while joining another host's game.

Host moderation:

```text
ban "Player Name"
```

Use a full name or a unique name prefix; matching is case-insensitive and Tab
completes remote player names. A ban removes **every player on that remote
machine**, records its address/hardware identity in `bans.txt`, and blocks future
joins from matching identities. It persists across sessions. There is no
`unban` console command; remove the relevant entry from the data-root `bans.txt`.
`ban` is a special host command, so `help "ban"` does not describe it.

## Persistence and configuration

On Mac, `config.toml` normally lives at
`~/Library/Application Support/Halo OG/config.toml`; **Advanced Settings** opens
it. The **game data root** is the selected folder containing `maps/`. Managed
imports typically use
`~/Library/Application Support/Halo OG/Game Data/<import-id>/`; **Use This
Folder** can select an external folder elsewhere. This root can differ from
the saves/settings folder. The startup line `Halo ARM64 starting: data ...;
saves ...` in `~/Library/Application Support/Halo OG/halo.log` identifies both.

Console variable changes generally affect the running process; they do not
automatically update `config.toml`. Some functions deliberately write files,
save games, change game state or reset maps. Their descriptions identify those
actions. Do not assume every command is a harmless preference.

For repeatable startup HaloScript commands, put one line per command in the
game data root's **`init.txt`**. For example:

```text
display_framerate true
```

Startup dispatch goes directly to HaloScript. **`pb` and `performance_options`
do not work in `init.txt`**. Host/client restrictions still apply to expressions.
Use saved gametypes for persistent PB/match rules and the normal Audio/Video
settings or registered config keys for application preferences.

| Setting or variable | Where it belongs |
| --- | --- |
| `game.console_log = "important"`, `"all"`, or `"none"` | `[game]` section of `config.toml`; controls unsolicited console messages. Typed command responses still show. |
| `bindings.console = "F2"` | `[bindings]` in `config.toml`; edit with the game closed and restart. |
| `console_dump_to_file true` | Actual console variable; additionally writes `console_printf`/warning output to the error log. |
| `debug.telnet_console = true` and `debug.telnet_console_port = 2323` | `[debug]` in `config.toml`; optional local script-console listener, bound to 127.0.0.1. |
| `debug.network_latency` / `debug.network_loss` | Config-only test settings that add delay/drop datagrams, not console diagnostics or ping display. |

In an actual TOML section use the key without its section prefix, e.g.:

```toml
[game]
console_log = "important"

[bindings]
console = "F2"
```

On Mac, the primary launcher/runtime log is **`halo.log`** in the saves/settings
folder. Engine errors and explicit console-dump output also go to **`debug.txt`**
in the selected game data root. `console_dump_to_file` controls additional
explicit console-print output; it is distinct from the display filter
`game.console_log`. The optional telnet listener accepts HaloScript with the
same client restrictions and also passes native `pb` / `performance_options`
commands through the same authority checks as the on-screen console.

## Complete function catalog

Every registered built-in function appears once below, grouped by purpose and
sorted by command name. Signatures and original help come from
`source/hs/hs.c`; unhelpful or missing descriptions are clarified where the
evaluator establishes their purpose. Old help text can be terse, informal or imprecise; the practical
sections above clarify commonly used commands. **Guest** means the function name
is on the joining-client allowlist, subject to its arguments also passing that
allowlist. **Host/local** means the joining-client console rejects it. It does not
guarantee that the function works in every map or that a local host mutation is
safe to perform during a live match.

Known inert functions: `debug_tags`, `radiosity_start`, `radiosity_save`, and
`radiosity_debug_point` are explicit no-ops. Features tied to the old editor,
Xbox graphics/debug infrastructure or map content need separate validation in
the native port. The `crash` command deliberately crashes the application.

### Language, expressions and timing

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(!= <expression> <expression>)` | `boolean` | returns true if two expressions are not equal [source](../source/hs/hs.c#L5647) | Host/local |
| `(* <number(s)>)` | `real` | returns the product of all specified expressions. [source](../source/hs/hs.c#L5587) | Host/local |
| `(+ <number(s)>)` | `real` | returns the sum of all specified expressions. [source](../source/hs/hs.c#L5563) | Host/local |
| `(- <number> <number>)` | `real` | returns the difference of two expressions. [source](../source/hs/hs.c#L5575) | Host/local |
| `(/ <number> <number>)` | `real` | returns the quotient of two expressions. [source](../source/hs/hs.c#L5599) | Host/local |
| `(< <number> <number>)` | `boolean` | returns true if the first number is smaller than the second. [source](../source/hs/hs.c#L5671) | Host/local |
| `(<= <number> <number>)` | `boolean` | returns true if the first number is smaller than or equal to the second. [source](../source/hs/hs.c#L5695) | Host/local |
| `(= <expression> <expression>)` | `boolean` | returns true if two expressions are equal [source](../source/hs/hs.c#L5635) | Host/local |
| `(> <number> <number>)` | `boolean` | returns true if the first number is larger than the second. [source](../source/hs/hs.c#L5659) | Host/local |
| `(>= <number> <number>)` | `boolean` | returns true if the first number is larger than or equal to the second. [source](../source/hs/hs.c#L5683) | Host/local |
| `(and <boolean(s)>)` | `boolean` | returns true if all specified expressions are true. [source](../source/hs/hs.c#L5539) | Host/local |
| `(begin <expression(s)>)` | `expression` | returns the last expression in a sequence after evaluating the sequence in order. [source](../source/hs/hs.c#L5479) | Host/local |
| `(begin_random <expression(s)>)` | `expression` | evaluates the sequence of expressions in random order and returns the last value evaluated. [source](../source/hs/hs.c#L5491) | Host/local |
| `(cond (<boolean1> <result1>) [(<boolean2> <result2>) [...]])` | `expression` | returns the value associated with the first true condition. [source](../source/hs/hs.c#L5515) | Host/local |
| `(if <boolean> <then> [<else>])` | `expression` | returns one of two values based on the value of a condition. [source](../source/hs/hs.c#L5503) | Host/local |
| `(inspect <expression>)` | `void` | prints the value of an expression to the screen for debugging purposes. Host/local only; use for numeric/boolean values. Avoid percent signs in inspected strings. [source](../source/hs/hs.c#L5743) | Host/local |
| `(max <number(s)>)` | `real` | returns the maximum of all specified expressions. [source](../source/hs/hs.c#L5623) | Host/local |
| `(min <number(s)>)` | `real` | returns the minimum of all specified expressions. [source](../source/hs/hs.c#L5611) | Host/local |
| `(not <boolean>)` | `boolean` | returns the opposite of the expression. [source](../source/hs/hs.c#L5803) | Host/local |
| `(or <boolean(s)>)` | `boolean` | returns true if any specified expressions are true. [source](../source/hs/hs.c#L5551) | Host/local |
| `(random_range <short> <short>)` | `short` | returns a random value in the range [lower bound, upper bound) [source](../source/hs/hs.c#L6287) | Host/local |
| `(real_random_range <real> <real>)` | `real` | returns a random value in the range [lower bound, upper bound) [source](../source/hs/hs.c#L6303) | Host/local |
| `(set <variable name> <expression>)` | `expression` | set the value of a global variable. [source](../source/hs/hs.c#L5527) | Guest |
| `(sleep <short> [<script>])` | `void` | pauses execution of this script (or, optionally, another script) for the specified number of ticks. [source](../source/hs/hs.c#L5707) | Host/local |
| `(sleep_until <boolean> [<short>])` | `void` | pauses execution of this script until the specified condition is true, checking once per second unless a different number of ticks is specified. [source](../source/hs/hs.c#L5719) | Host/local |
| `(wake <script name>)` | `void` | wakes a sleeping script in the next update. [source](../source/hs/hs.c#L5731) | Host/local |

### Units and vehicles

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(magic_melee_attack)` | `void` | causes player's unit to start a melee attack [source](../source/hs/hs.c#L7220) | Host/local |
| `(magic_seat_name <string>)` | `void` | all units controlled by the player will assume the given seat name (valid values are 'asleep', 'alert', 'stand', 'crouch' and 'flee') [source](../source/hs/hs.c#L7189) | Host/local |
| `(unit <object>)` | `unit` | converts an object to a unit. [source](../source/hs/hs.c#L5755) | Host/local |
| `(unit_aim_without_turning <unit> <boolean>)` | `void` | allows a unit to aim in place without turning [source](../source/hs/hs.c#L6966) | Host/local |
| `(unit_can_blink <unit> <boolean>)` | `void` | allows a unit to blink or not (units never blink when they are dead) [source](../source/hs/hs.c#L6797) | Host/local |
| `(unit_close <unit>)` | `void` | closes the hatches on a given unit [source](../source/hs/hs.c#L6828) | Host/local |
| `(unit_custom_animation_at_frame <unit> <animation_graph> <string> <boolean> <short>)` | `boolean` | starts a custom animation playing on a unit at a specific frame index(interpolates into animation if next to last parameter is TRUE) [source](../source/hs/hs.c#L6935) | Host/local |
| `(unit_doesnt_drop_items <object_list>)` | `void` | prevents any of the given units from dropping weapons or grenades when they die [source](../source/hs/hs.c#L7354) | Host/local |
| `(unit_enter_vehicle <unit> <vehicle> <string>)` | `void` | puts the specified unit in the specified vehicle (in the named seat) [source](../source/hs/hs.c#L7014) | Host/local |
| `(unit_exit_vehicle <unit>)` | `void` | makes a unit exit its vehicle [source](../source/hs/hs.c#L7078) | Host/local |
| `(unit_get_current_flashlight_state <unit>)` | `boolean` | gets the unit's current flashlight state [source](../source/hs/hs.c#L7445) | Host/local |
| `(unit_get_custom_animation_time <unit>)` | `short` | returns the number of ticks remaining in a unit's custom animation (or zero, if the animation is over). [source](../source/hs/hs.c#L6873) | Host/local |
| `(unit_get_health <unit>)` | `real` | returns the health [0,1] of the unit, returns -1 if the unit does not exists [source](../source/hs/hs.c#L7277) | Host/local |
| `(unit_get_shield <unit>)` | `real` | returns the shield [0,1] of the unit, returns -1 if the unit does not exists [source](../source/hs/hs.c#L7292) | Host/local |
| `(unit_get_total_grenade_count <unit>)` | `short` | returns the total number of grenades for the given unit, 0 if it does not exist [source](../source/hs/hs.c#L7307) | Host/local |
| `(unit_has_weapon <unit> <object_definition>)` | `boolean` | returns TRUE if the &lt;unit&gt; has &lt;object&gt; as a weapon, FALSE otherwise [source](../source/hs/hs.c#L7322) | Host/local |
| `(unit_has_weapon_readied <unit> <object_definition>)` | `boolean` | returns TRUE if the &lt;unit&gt; has &lt;object&gt; as the primary weapon, FALSE otherwise [source](../source/hs/hs.c#L7338) | Host/local |
| `(unit_impervious <object_list> <boolean>)` | `void` | prevents any of the given units from being knocked around or playing ping animations [source](../source/hs/hs.c#L7369) | Host/local |
| `(unit_is_playing_custom_animation <unit>)` | `boolean` | returns TRUE if the given unit is still playing a custom animation [source](../source/hs/hs.c#L6951) | Host/local |
| `(unit_kill <unit>)` | `void` | kills a given unit, no saving throw [source](../source/hs/hs.c#L6843) | Host/local |
| `(unit_kill_silent <unit>)` | `void` | kills a given unit silently (doesn't make them play their normal death animation or sound) [source](../source/hs/hs.c#L6858) | Host/local |
| `(unit_open <unit>)` | `void` | opens the hatches on the given unit [source](../source/hs/hs.c#L6813) | Host/local |
| `(unit_set_current_vitality <unit> <real> <real>)` | `void` | sets a unit's current body and shield vitality [source](../source/hs/hs.c#L7125) | Host/local |
| `(unit_set_desired_flashlight_state <unit> <boolean>)` | `void` | sets the unit's desired flashlight state [source](../source/hs/hs.c#L7429) | Host/local |
| `(unit_set_emotion <unit> <short>)` | `void` | sets a unit's facial expression (-1 is none, other values depend on unit) [source](../source/hs/hs.c#L6982) | Host/local |
| `(unit_set_emotion_animation <unit> <string>)` | `void` | sets the emotion animation to be used for the given unit [source](../source/hs/hs.c#L7062) | Host/local |
| `(unit_set_enterable_by_player <unit> <boolean>)` | `void` | can be used to prevent the player from entering a vehicle [source](../source/hs/hs.c#L6998) | Host/local |
| `(unit_set_maximum_vitality <unit> <real> <real>)` | `void` | sets a unit's maximum body and shield vitality [source](../source/hs/hs.c#L7093) | Host/local |
| `(unit_set_seat <unit> <string>)` | `void` | this unit will assume the named seat [source](../source/hs/hs.c#L7204) | Host/local |
| `(unit_solo_player_integrated_night_vision_is_active)` | `boolean` | returns whether the night-vision mode could be activated via the flashlight button [source](../source/hs/hs.c#L7401) | Host/local |
| `(unit_stop_custom_animation <unit>)` | `void` | stops the custom animation running on the given unit. [source](../source/hs/hs.c#L6888) | Host/local |
| `(unit_suspended <unit> <boolean>)` | `void` | stops gravity from working on the given unit [source](../source/hs/hs.c#L7385) | Host/local |
| `(units_set_current_vitality <object_list> <real> <real>)` | `void` | sets a group of units' current body and shield vitality [source](../source/hs/hs.c#L7141) | Host/local |
| `(units_set_desired_flashlight_state <object_list> <boolean>)` | `void` | sets the units' desired flashlight state [source](../source/hs/hs.c#L7413) | Host/local |
| `(units_set_maximum_vitality <object_list> <real> <real>)` | `void` | sets a group of units' maximum body and shield vitality [source](../source/hs/hs.c#L7109) | Host/local |
| `(vehicle_driver <unit>)` | `unit` | returns the driver of a vehicle [source](../source/hs/hs.c#L7247) | Host/local |
| `(vehicle_gunner <unit>)` | `unit` | returns the gunner of a vehicle [source](../source/hs/hs.c#L7262) | Host/local |
| `(vehicle_hover <vehicle> <boolean>)` | `void` | stops the vehicle from running real physics and runs fake hovering physics instead. [source](../source/hs/hs.c#L10660) | Host/local |
| `(vehicle_load_magic <unit> <string> <object_list>)` | `short` | makes a list of units (named or by encounter) magically get into a vehicle, in the substring-specified seats (e.g. CD-passenger... empty string matches all seats) [source](../source/hs/hs.c#L7157) | Host/local |
| `(vehicle_riders <unit>)` | `object_list` | returns a list of all riders in a vehicle [source](../source/hs/hs.c#L7232) | Host/local |
| `(vehicle_test_seat <vehicle> <string> <unit>)` | `boolean` | tests whether the named seat has a specified unit in it [source](../source/hs/hs.c#L7046) | Host/local |
| `(vehicle_test_seat_list <vehicle> <string> <object_list>)` | `boolean` | tests whether the named seat has an object in the object list [source](../source/hs/hs.c#L7030) | Host/local |
| `(vehicle_unload <unit> <string>)` | `short` | makes units get out of a vehicle from the substring-specified seats (e.g. CD-passenger... empty string matches all seats) [source](../source/hs/hs.c#L7173) | Host/local |

### AI, encounters and conversations

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(ai_actors <ai>)` | `object_list` | converts an ai reference to an object list. [source](../source/hs/hs.c#L9118) | Host/local |
| `(ai_allegiance <team> <team>)` | `void` | creates an allegiance between two teams. [source](../source/hs/hs.c#L8280) | Host/local |
| `(ai_allegiance_broken <team> <team>)` | `boolean` | returns whether two teams have an allegiance that is currently broken by traitorous behavior [source](../source/hs/hs.c#L9193) | Host/local |
| `(ai_allegiance_remove <team> <team>)` | `void` | destroys an allegiance between two teams. [source](../source/hs/hs.c#L8296) | Host/local |
| `(ai_allow_charge <ai> <boolean>)` | `void` | either enables or disables charging behavior for a group of actors [source](../source/hs/hs.c#L8966) | Host/local |
| `(ai_allow_dormant <ai> <boolean>)` | `void` | either enables or disables automatic dormancy for a group of actors [source](../source/hs/hs.c#L8982) | Host/local |
| `(ai_attach <unit> <ai>)` | `void` | attaches the specified unit to the specified encounter. [source](../source/hs/hs.c#L7823) | Host/local |
| `(ai_attach_free <unit> <actor_variant>)` | `void` | attaches a unit to a newly created free actor of the specified type [source](../source/hs/hs.c#L7855) | Host/local |
| `(ai_attack <ai>)` | `void` | makes the specified platoon(s) go into the attacking state. [source](../source/hs/hs.c#L8156) | Host/local |
| `(ai_automatic_migration_target <ai> <boolean>)` | `void` | enables or disables a squad as being an automatic migration target [source](../source/hs/hs.c#L8794) | Host/local |
| `(ai_berserk <ai> <boolean>)` | `void` | forces a group of actors to start or stop berserking [source](../source/hs/hs.c#L8934) | Host/local |
| `(ai_braindead <ai> <boolean>)` | `void` | makes a group of actors braindead, or restores them to life (in their initial state) [source](../source/hs/hs.c#L8359) | Host/local |
| `(ai_braindead_by_unit <object_list> <boolean>)` | `void` | makes a list of objects braindead, or restores them to life. if you pass in a vehicle index, it makes all actors in that vehicle braindead (including any built-in guns) [source](../source/hs/hs.c#L8375) | Host/local |
| `(ai_command_list <ai> <ai_command_list>)` | `void` | tells a group of actors to begin executing the specified command list [source](../source/hs/hs.c#L8514) | Host/local |
| `(ai_command_list_advance <ai>)` | `void` | tells a group of actors that are running a command list that they may advance further along the list (if they are waiting for a stimulus) [source](../source/hs/hs.c#L8546) | Host/local |
| `(ai_command_list_advance_by_unit <unit>)` | `void` | just like ai_command_list_advance but operates upon a unit instead [source](../source/hs/hs.c#L8561) | Host/local |
| `(ai_command_list_by_unit <unit> <ai_command_list>)` | `void` | tells a named unit to begin executing the specified command list [source](../source/hs/hs.c#L8530) | Host/local |
| `(ai_command_list_status <object_list>)` | `short` | gets the status of a number of units running command lists: 0 = none, 1 = finished command list, 2 = waiting for stimulus, 3 = running command list [source](../source/hs/hs.c#L9013) | Host/local |
| `(ai_conversation <conversation>)` | `boolean` | tries to add an entry to the list of conversations waiting to play. returns FALSE if the required units could not be found to play the conversation, or if the player is too far away and the 'delay' flag is not set. [source](../source/hs/hs.c#L9148) | Host/local |
| `(ai_conversation_advance <conversation>)` | `void` | tells a conversation that it may advance [source](../source/hs/hs.c#L8903) | Host/local |
| `(ai_conversation_line <conversation>)` | `short` | returns which line the conversation is currently playing, or 999 if the conversation is not currently playing [source](../source/hs/hs.c#L9163) | Host/local |
| `(ai_conversation_status <conversation>)` | `short` | returns the status of a conversation (0=none, 1=trying to begin, 2=waiting for guys to get in position, 3=playing, 4=waiting to advance, 5=could not begin, 6=finished successfully, 7=aborted midway [source](../source/hs/hs.c#L9178) | Host/local |
| `(ai_conversation_stop <conversation>)` | `void` | stops a conversation from playing or trying to play [source](../source/hs/hs.c#L8888) | Host/local |
| `(ai_debug_communication_focus <string(s)>)` | `void` | focuses (or stops focusing) a set of unit vocalization types. [source](../source/hs/hs.c#L5791) | Host/local |
| `(ai_debug_communication_ignore <string(s)>)` | `void` | ignores (or stops ignoring) a set of AI communication types when printing out communications. [source](../source/hs/hs.c#L5779) | Host/local |
| `(ai_debug_communication_suppress <string(s)>)` | `void` | suppresses (or stops suppressing) a set of AI communication types. [source](../source/hs/hs.c#L5767) | Host/local |
| `(ai_debug_sound_point_set)` | `void` | drops the AI debugging sound point at the camera location [source](../source/hs/hs.c#L9979) | Host/local |
| `(ai_debug_speak <string>)` | `void` | makes the currently selected AI speak a vocalization (e.g. ai_speak "pain minor") [source](../source/hs/hs.c#L10022) | Host/local |
| `(ai_debug_speak_list <string>)` | `void` | makes the currently selected AI speak a list of vocalizations (e.g. ai_speak_list "involuntary") [source](../source/hs/hs.c#L10037) | Host/local |
| `(ai_debug_teleport_to <ai>)` | `void` | teleports all players to the specified encounter [source](../source/hs/hs.c#L10007) | Host/local |
| `(ai_debug_vocalize <string> <string>)` | `void` | makes the selected AI vocalize [source](../source/hs/hs.c#L9991) | Host/local |
| `(ai_defend <ai>)` | `void` | makes the specified platoon(s) go into the defending state. [source](../source/hs/hs.c#L8171) | Host/local |
| `(ai_deselect)` | `void` | clears the selected encounter. [source](../source/hs/hs.c#L7988) | Host/local |
| `(ai_detach <unit>)` | `void` | detaches the specified unit from all AI. [source](../source/hs/hs.c#L7871) | Host/local |
| `(ai_dialogue_triggers <boolean>)` | `void` | turns impromptu dialogue on or off. [source](../source/hs/hs.c#L7763) | Host/local |
| `(ai_disregard <object_list> <boolean>)` | `void` | if TRUE, forces all actors to completely disregard the specified units, otherwise lets them acknowledge the units again [source](../source/hs/hs.c#L8391) | Host/local |
| `(ai_erase <ai>)` | `void` | erases the specified encounter and/or squad. [source](../source/hs/hs.c#L7946) | Host/local |
| `(ai_erase_all)` | `void` | erases all AI. [source](../source/hs/hs.c#L7961) | Host/local |
| `(ai_exit_vehicle <ai>)` | `void` | tells a group of actors to get out of any vehicles that they are in [source](../source/hs/hs.c#L8344) | Host/local |
| `(ai_follow_distance <ai> <real>)` | `void` | sets the distance threshold which will cause squads to migrate when following someone [source](../source/hs/hs.c#L8872) | Host/local |
| `(ai_follow_target_ai <ai> <ai>)` | `void` | sets the follow target for an encounter to be a group of AI (encounter, squad or platoon) [source](../source/hs/hs.c#L8856) | Host/local |
| `(ai_follow_target_disable <ai>)` | `void` | turns off following for an encounter [source](../source/hs/hs.c#L8810) | Host/local |
| `(ai_follow_target_players <ai>)` | `void` | sets the follow target for an encounter to be the closest player [source](../source/hs/hs.c#L8825) | Host/local |
| `(ai_follow_target_unit <ai> <unit>)` | `void` | sets the follow target for an encounter to be a specific unit [source](../source/hs/hs.c#L8840) | Host/local |
| `(ai_force_active <ai> <boolean>)` | `void` | forces an encounter to remain active (i.e. not freeze in place) even if there are no players nearby [source](../source/hs/hs.c#L8576) | Host/local |
| `(ai_force_active_by_unit <unit> <boolean>)` | `void` | forces a named actor that is NOT in an encounter to remain active (i.e. not freeze in place) even if there are no players nearby [source](../source/hs/hs.c#L8592) | Host/local |
| `(ai_free <ai>)` | `void` | removes a group of actors from their encounter and sets them free [source](../source/hs/hs.c#L7793) | Host/local |
| `(ai_free_units <object_list>)` | `void` | removes a set of units from their encounter (if any) and sets them free [source](../source/hs/hs.c#L7808) | Host/local |
| `(ai_go_to_vehicle <ai> <unit> <string>)` | `void` | tells a group of actors to get into a vehicle, in the substring-specified seats (e.g. passenger for pelican)... does not interrupt any actors who are already going to vehicles [source](../source/hs/hs.c#L8312) | Host/local |
| `(ai_go_to_vehicle_override <ai> <unit> <string>)` | `void` | tells a group of actors to get into a vehicle, in the substring-specified seats (e.g. passenger for pelican)... NB: any actors who are already going to vehicles will stop and go to this one instead! [source](../source/hs/hs.c#L8328) | Host/local |
| `(ai_going_to_vehicle <unit>)` | `short` | return the number of actors that are still trying to get into the specified vehicle [source](../source/hs/hs.c#L9028) | Host/local |
| `(ai_grenades <boolean>)` | `void` | turns grenade inventory on or off. [source](../source/hs/hs.c#L7778) | Host/local |
| `(ai_is_attacking <ai>)` | `boolean` | returns whether a platoon is in the attacking mode (or if an encounter is specified, returns whether any platoon in that encounter is attacking) [source](../source/hs/hs.c#L8998) | Host/local |
| `(ai_kill <ai>)` | `void` | instantly kills the specified encounter and/or squad. [source](../source/hs/hs.c#L7916) | Host/local |
| `(ai_kill_silent <ai>)` | `void` | instantly and silently (no animation or sound played) kills the specified encounter and/or squad. [source](../source/hs/hs.c#L7931) | Host/local |
| `(ai_lines)` | `void` | cycles through AI line-spray modes [source](../source/hs/hs.c#L9967) | Host/local |
| `(ai_link_activation <ai> <ai>)` | `void` | links the first encounter so that it will be made active whenever it detects that the second encounter is active [source](../source/hs/hs.c#L8918) | Host/local |
| `(ai_living_count <ai>)` | `short` | return the number of living actors in the specified encounter and/or squad. [source](../source/hs/hs.c#L9043) | Host/local |
| `(ai_living_fraction <ai>)` | `real` | return the fraction [0-1] of living actors in the specified encounter and/or squad. [source](../source/hs/hs.c#L9058) | Host/local |
| `(ai_look_at_object <unit> <object>)` | `void` | tells an actor to look at an object until further notice [source](../source/hs/hs.c#L8763) | Host/local |
| `(ai_magically_see_encounter <ai> <ai>)` | `void` | makes one encounter magically aware of another. [source](../source/hs/hs.c#L8063) | Host/local |
| `(ai_magically_see_players <ai>)` | `void` | makes an encounter magically aware of nearby players. [source](../source/hs/hs.c#L8079) | Host/local |
| `(ai_magically_see_unit <ai> <unit>)` | `void` | makes an encounter magically aware of the specified unit. [source](../source/hs/hs.c#L8094) | Host/local |
| `(ai_maneuver <ai>)` | `void` | makes all squads in the specified platoon(s) maneuver to their designated maneuver squads. [source](../source/hs/hs.c#L8201) | Host/local |
| `(ai_maneuver_enable <ai> <boolean>)` | `void` | enables or disables the maneuver/retreat rule for an encounter or platoon. the rule will still trigger, but none of the actors will be given the order to change squads. [source](../source/hs/hs.c#L8216) | Host/local |
| `(ai_migrate <ai> <ai>)` | `void` | makes all or part of an encounter move to another encounter. [source](../source/hs/hs.c#L8232) | Host/local |
| `(ai_migrate_and_speak <ai> <ai> <string>)` | `void` | makes all or part of an encounter move to another encounter, and say their 'advance' or 'retreat' speech lines. [source](../source/hs/hs.c#L8248) | Host/local |
| `(ai_migrate_by_unit <object_list> <ai>)` | `void` | makes a named vehicle or group of units move to another encounter. [source](../source/hs/hs.c#L8264) | Host/local |
| `(ai_nonswarm_count <ai>)` | `short` | return the number of non-swarm actors in the specified encounter and/or squad. [source](../source/hs/hs.c#L9103) | Host/local |
| `(ai_place <ai>)` | `void` | places the specified encounter on the map. [source](../source/hs/hs.c#L7901) | Host/local |
| `(ai_playfight <ai> <boolean>)` | `void` | sets an encounter to be playfighting or not [source](../source/hs/hs.c#L8640) | Host/local |
| `(ai_prefer_target <object_list> <boolean>)` | `void` | if TRUE, *ALL* enemies will prefer to attack the specified units. if FALSE, removes the preference. [source](../source/hs/hs.c#L8407) | Host/local |
| `(ai_reconnect)` | `void` | reconnects all AI information to the current structure bsp (use this after you create encounters or command lists in sapien, or place new firing points or command list points) [source](../source/hs/hs.c#L8656) | Host/local |
| `(ai_renew <ai>)` | `void` | refreshes the health and grenade count of a group of actors, so they are as good as new [source](../source/hs/hs.c#L8453) | Host/local |
| `(ai_retreat <ai>)` | `void` | makes all squads in the specified platoon(s) maneuver to their designated maneuver squads. [source](../source/hs/hs.c#L8186) | Host/local |
| `(ai_select <ai>)` | `void` | selects the specified encounter. [source](../source/hs/hs.c#L7973) | Host/local |
| `(ai_set_blind <ai> <boolean>)` | `void` | enables or disables sight for actors in the specified encounter. [source](../source/hs/hs.c#L8047) | Host/local |
| `(ai_set_current_state <ai> <ai_default_state>)` | `void` | sets the current state of a group of actors. WARNING: may have unpredictable results on actors that are in combat [source](../source/hs/hs.c#L8624) | Host/local |
| `(ai_set_deaf <ai> <boolean>)` | `void` | enables or disables hearing for actors in the specified encounter. [source](../source/hs/hs.c#L8031) | Host/local |
| `(ai_set_respawn <ai> <boolean>)` | `void` | enables or disables respawning in the specified encounter. [source](../source/hs/hs.c#L8015) | Host/local |
| `(ai_set_return_state <ai> <ai_default_state>)` | `void` | sets the state that a group of actors will return to when they have nothing to do [source](../source/hs/hs.c#L8608) | Host/local |
| `(ai_set_team <ai> <team>)` | `void` | makes an encounter change to a new team [source](../source/hs/hs.c#L8950) | Host/local |
| `(ai_spawn_actor <ai>)` | `void` | spawns a single actor in the specified encounter and/or squad. [source](../source/hs/hs.c#L8000) | Host/local |
| `(ai_status <ai>)` | `short` | returns the most severe combat status of a group of actors (0=inactive, 1=noncombat, 2=guarding, 3=search/suspicious, 4=definite enemy(heard or magic awareness), 5=visible enemy, 6=engaging in combat. [source](../source/hs/hs.c#L9133) | Host/local |
| `(ai_stop_looking <unit>)` | `void` | tells an actor to stop looking at whatever it's looking at [source](../source/hs/hs.c#L8779) | Host/local |
| `(ai_strength <ai>)` | `real` | return the current strength (average body vitality from 0-1) of the specified encounter and/or squad. [source](../source/hs/hs.c#L9073) | Host/local |
| `(ai_swarm_count <ai>)` | `short` | return the number of swarm actors in the specified encounter and/or squad. [source](../source/hs/hs.c#L9088) | Host/local |
| `(ai_teleport_to_starting_location <ai>)` | `void` | teleports a group of actors to the starting locations of their current squad(s) [source](../source/hs/hs.c#L8423) | Host/local |
| `(ai_teleport_to_starting_location_if_unsupported <ai>)` | `void` | teleports a group of actors to the starting locations of their current squad(s), only if they are not supported by solid ground (i.e. if they are falling after switching BSPs) [source](../source/hs/hs.c#L8438) | Host/local |
| `(ai_timer_expire <ai>)` | `void` | makes a squad's delay timer expire and releases them to enter combat. [source](../source/hs/hs.c#L8141) | Host/local |
| `(ai_timer_start <ai>)` | `void` | makes a squad's delay timer start counting. [source](../source/hs/hs.c#L8126) | Host/local |
| `(ai_try_to_fight <ai> <ai>)` | `void` | causes a group of actors to preferentially target another group of actors [source](../source/hs/hs.c#L8483) | Host/local |
| `(ai_try_to_fight_nothing <ai>)` | `void` | removes the preferential target setting from a group of actors [source](../source/hs/hs.c#L8468) | Host/local |
| `(ai_try_to_fight_player <ai>)` | `void` | causes a group of actors to preferentially target the player [source](../source/hs/hs.c#L8499) | Host/local |
| `(ai_vehicle_encounter <unit> <ai>)` | `void` | sets a vehicle to 'belong' to a particular encounter/squad. any actors who get into the vehicle will be placed in this squad. NB: vehicles potentially drivable by multiple teams need their own encounter! [source](../source/hs/hs.c#L8668) | Host/local |
| `(ai_vehicle_enterable_actor_type <unit> <actor_type>)` | `void` | sets a vehicle as being impulsively enterable for actors of a certain type (grunt, elite, marine etc) [source](../source/hs/hs.c#L8716) | Host/local |
| `(ai_vehicle_enterable_actors <unit> <ai>)` | `void` | sets a vehicle as being impulsively enterable for a certain encounter/squad of actors [source](../source/hs/hs.c#L8732) | Host/local |
| `(ai_vehicle_enterable_disable <unit>)` | `void` | disables actors from impulsively getting into a vehicle (this is the default state for newly placed vehicles) [source](../source/hs/hs.c#L8748) | Host/local |
| `(ai_vehicle_enterable_distance <unit> <real>)` | `void` | sets a vehicle as being impulsively enterable for actors within a certain distance [source](../source/hs/hs.c#L8684) | Host/local |
| `(ai_vehicle_enterable_team <unit> <team>)` | `void` | sets a vehicle as being impulsively enterable for actors on a certain team [source](../source/hs/hs.c#L8700) | Host/local |

### Console, scripting and other tools

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(activate_team_nav_point_flag <navpoint> <team> <cutscene_flag> <real>)` | `void` | activates a nav point type &lt;string&gt; attached to a team anchored to a flag with a vertical offset &lt;real&gt;. If the player is not local to the machine, this will fail [source](../source/hs/hs.c#L10765) | Host/local |
| `(activate_team_nav_point_object <navpoint> <team> <object> <real>)` | `void` | activates a nav point type &lt;string&gt; attached to a team anchored to an object with a vertical offset &lt;real&gt;. If the player is not local to the machine, this will fail [source](../source/hs/hs.c#L10781) | Host/local |
| `(ai <boolean>)` | `void` | turns all AI on or off. [source](../source/hs/hs.c#L7748) | Host/local |
| `(cls)` | `void` | clears console text from the screen [source](../source/hs/hs.c#L10861) | Guest |
| `(crash <string>)` | `void` | **Deliberately crashes the application.** crashes (for debugging). [source](../source/hs/hs.c#L9703) | Host/local |
| `(deactivate_team_nav_point_flag <team> <cutscene_flag>)` | `void` | deactivates a nav point type attached to a team anchored to a flag [source](../source/hs/hs.c#L10829) | Host/local |
| `(deactivate_team_nav_point_object <team> <object>)` | `void` | deactivates a nav point type attached to a team anchored to an object [source](../source/hs/hs.c#L10845) | Host/local |
| `(delete_save_game_files)` | `void` | delete all custom profile files [source](../source/hs/hs.c#L11444) | Host/local |
| `(enumerate_memory_units)` | `void` | enumerate memory units [source](../source/hs/hs.c#L11432) | Host/local |
| `(error_overflow_suppression <boolean>)` | `void` | enables or disables the suppression of error spamming [source](../source/hs/hs.c#L10873) | Host/local |
| `(help <string>)` | `void` | prints a description of the named function. [source](../source/hs/hs.c#L6272) | Guest |
| `(numeric_countdown_timer_get <short>)` | `short` | &lt;digit_index&gt; [source](../source/hs/hs.c#L6335) | Host/local |
| `(numeric_countdown_timer_restart)` | `void` | Restarts the numeric countdown timer. [source](../source/hs/hs.c#L6362) | Host/local |
| `(numeric_countdown_timer_set <long> <boolean>)` | `void` | &lt;milliseconds&gt;, &lt;auto_start&gt; [source](../source/hs/hs.c#L6319) | Host/local |
| `(numeric_countdown_timer_stop)` | `void` | Stops the numeric countdown timer. [source](../source/hs/hs.c#L6350) | Host/local |
| `(pause_hud_timer <boolean>)` | `void` | pauses or unpauses the hud timer [source](../source/hs/hs.c#L11189) | Host/local |
| `(playback)` | `void` | starts game in film playback mode [source](../source/hs/hs.c#L9757) | Host/local |
| `(print <string>)` | `void` | prints a string to the console. Avoid percent signs in printed text. [source](../source/hs/hs.c#L5818) | Guest |
| `(script_doc)` | `void` | saves a file called hs_doc.txt with parameters for all script commands. [source](../source/hs/hs.c#L6260) | Guest |
| `(script_recompile)` | `void` | recompiles scripts. [source](../source/hs/hs.c#L6248) | Host/local |
| `(script_screen_effect_set_value <short> <real>)` | `void` | sets a screen effect script value [source](../source/hs/hs.c#L11310) | Host/local |
| `(time_code_reset)` | `void` | resets the time code timer [source](../source/hs/hs.c#L11246) | Host/local |
| `(time_code_show <boolean>)` | `void` | shows the time code timer [source](../source/hs/hs.c#L11216) | Host/local |
| `(time_code_start <boolean>)` | `void` | starts/stops the time code timer [source](../source/hs/hs.c#L11231) | Host/local |
| `(version)` | `void` | prints the build version. [source](../source/hs/hs.c#L9745) | Host/local |

### Objects, lists, effects and volumes

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(breakable_surfaces_enable <boolean>)` | `void` | enables or disables breakability of all breakable surfaces on level [source](../source/hs/hs.c#L6374) | Host/local |
| `(breakable_surfaces_reset)` | `void` | restores all breakable surfaces [source](../source/hs/hs.c#L7649) | Host/local |
| `(custom_animation <unit> <animation_graph> <string> <boolean>)` | `boolean` | starts a custom animation playing on a unit (interpolates into animation if last parameter is TRUE) [source](../source/hs/hs.c#L6888) | Host/local |
| `(custom_animation_list <object_list> <animation_graph> <string> <boolean>)` | `boolean` | starts a custom animation playing on a unit list (interpolates into animation if last parameter is TRUE) [source](../source/hs/hs.c#L6919) | Host/local |
| `(damage_new <damage> <cutscene_flag>)` | `void` | causes the specified damage at the specified flag. [source](../source/hs/hs.c#L6138) | Host/local |
| `(damage_object <damage> <object>)` | `void` | causes the specified damage at the specified object. [source](../source/hs/hs.c#L6154) | Host/local |
| `(effect_new <effect> <cutscene_flag>)` | `void` | starts the specified effect at the specified flag. [source](../source/hs/hs.c#L6106) | Host/local |
| `(effect_new_on_object_marker <effect> <object> <string>)` | `void` | starts the specified effect on the specified object at the specified marker. [source](../source/hs/hs.c#L6122) | Host/local |
| `(garbage_collect_now)` | `void` | causes all garbage objects except those visible to a player to be collected immediately [source](../source/hs/hs.c#L6575) | Host/local |
| `(list_count <object_list>)` | `short` | returns the number of objects in a list [source](../source/hs/hs.c#L6091) | Host/local |
| `(list_get <object_list> <short>)` | `object` | returns an item in an object list. [source](../source/hs/hs.c#L6075) | Host/local |
| `(object_beautify <object> <boolean>)` | `void` | makes an object pretty for the remainder of the levels' cutscenes. [source](../source/hs/hs.c#L6617) | Host/local |
| `(object_can_take_damage <object_list>)` | `void` | allows an object to take damage again [source](../source/hs/hs.c#L6602) | Host/local |
| `(object_cannot_take_damage <object_list>)` | `void` | prevents an object from taking damage [source](../source/hs/hs.c#L6587) | Host/local |
| `(object_create <object_name>)` | `void` | creates an object from the scenario. [source](../source/hs/hs.c#L5909) | Host/local |
| `(object_create_anew <object_name>)` | `void` | creates an object, destroying it first if it already exists. [source](../source/hs/hs.c#L5939) | Host/local |
| `(object_create_anew_containing <string>)` | `void` | creates anew all objects from the scenario whose names contain the given substring. [source](../source/hs/hs.c#L5969) | Host/local |
| `(object_create_containing <string>)` | `void` | creates all objects from the scenario whose names contain the given substring. [source](../source/hs/hs.c#L5954) | Host/local |
| `(object_destroy <object>)` | `void` | destroys an object. [source](../source/hs/hs.c#L5924) | Host/local |
| `(object_destroy_all)` | `void` | destroys all non player objects. [source](../source/hs/hs.c#L5999) | Host/local |
| `(object_destroy_containing <string>)` | `void` | destroys all objects from the scenario whose names contain the given substring. [source](../source/hs/hs.c#L5984) | Host/local |
| `(object_pvs_activate <object>)` | `void` | just another (old) name for object_pvs_set_object. [source](../source/hs/hs.c#L6705) | Host/local |
| `(object_pvs_clear)` | `void` | removes the special place that activates everything it sees. [source](../source/hs/hs.c#L6693) | Host/local |
| `(object_pvs_set_camera <cutscene_camera_point>)` | `void` | sets the specified cutscene camera point as the special place that activates everything it sees. [source](../source/hs/hs.c#L6678) | Host/local |
| `(object_pvs_set_object <object>)` | `void` | sets the specified object as the special place that activates everything it sees. [source](../source/hs/hs.c#L6663) | Host/local |
| `(object_set_collideable <object> <boolean>)` | `void` | FALSE prevents any object from colliding with the given object [source](../source/hs/hs.c#L6511) | Host/local |
| `(object_set_facing <object> <cutscene_flag>)` | `void` | turns the specified object in the direction of the specified flag. [source](../source/hs/hs.c#L6027) | Host/local |
| `(object_set_melee_attack_inhibited <object> <boolean>)` | `void` | FALSE prevents object from using melee attack [source](../source/hs/hs.c#L6483) | Host/local |
| `(object_set_permutation <object> <string> <string>)` | `void` | sets the desired region (use "" for all regions) to the permutation with the given name, e.g. (object_set_permutation flood "right arm" ~damaged) [source](../source/hs/hs.c#L6059) | Host/local |
| `(object_set_ranged_attack_inhibited <object> <boolean>)` | `void` | FALSE prevents object from using ranged attack [source](../source/hs/hs.c#L6467) | Host/local |
| `(object_set_scale <object> <real> <short>)` | `void` | sets the scale for a given object and interpolates over the given number of frames to achieve that scale [source](../source/hs/hs.c#L6527) | Host/local |
| `(object_set_shield <object> <real>)` | `void` | sets the shield vitality of the specified object (between 0 and 1). [source](../source/hs/hs.c#L6043) | Host/local |
| `(object_teleport <object> <cutscene_flag>)` | `void` | moves the specified object to the specified flag. [source](../source/hs/hs.c#L6011) | Host/local |
| `(object_type_predict <object_definition>)` | `void` | loads textures necessary to draw an object that's about to come on-screen. [source](../source/hs/hs.c#L6648) | Host/local |
| `(objects_attach <object> <string> <object> <string>)` | `void` | attaches the second object to the first; both strings can be empty [source](../source/hs/hs.c#L6543) | Host/local |
| `(objects_can_see_flag <object_list> <cutscene_flag> <real>)` | `boolean` | returns true if any of the specified units are looking within the specified number of degrees of the flag. [source](../source/hs/hs.c#L6186) | Host/local |
| `(objects_can_see_object <object_list> <object> <real>)` | `boolean` | returns true if any of the specified units are looking within the specified number of degrees of the object. [source](../source/hs/hs.c#L6170) | Host/local |
| `(objects_delete_by_definition <object_definition>)` | `void` | deletes all objects of type &lt;definition&gt; [source](../source/hs/hs.c#L6202) | Host/local |
| `(objects_detach <object> <object>)` | `void` | detaches from the given parent object the given child object [source](../source/hs/hs.c#L6559) | Host/local |
| `(objects_dump_memory)` | `void` | debugs object memory usage [source](../source/hs/hs.c#L6499) | Host/local |
| `(objects_predict <object_list>)` | `void` | loads textures necessary to draw a objects that are about to come on-screen. [source](../source/hs/hs.c#L6633) | Host/local |
| `(players)` | `object_list` | returns a list of the players [source](../source/hs/hs.c#L5833) | Host/local |
| `(scenery_animation_start <scenery> <animation_graph> <string>)` | `void` | starts a custom animation playing on a piece of scenery [source](../source/hs/hs.c#L6750) | Host/local |
| `(scenery_animation_start_at_frame <scenery> <animation_graph> <string> <short>)` | `void` | starts a custom animation playing on a piece of scenery at a specific frame [source](../source/hs/hs.c#L6766) | Host/local |
| `(scenery_get_animation_time <scenery>)` | `short` | returns the number of ticks remaining in a custom animation (or zero, if the animation is over). [source](../source/hs/hs.c#L6735) | Host/local |
| `(structure_bsp_index)` | `short` | returns the current structure bsp index [source](../source/hs/hs.c#L9733) | Host/local |
| `(volume_teleport_players_not_inside <trigger_volume> <cutscene_flag>)` | `void` | moves all players outside a specified trigger volume to a specified flag. [source](../source/hs/hs.c#L5845) | Host/local |
| `(volume_test_object <trigger_volume> <object>)` | `boolean` | returns true if the specified object is within the specified volume. [source](../source/hs/hs.c#L5861) | Host/local |
| `(volume_test_objects <trigger_volume> <object_list>)` | `boolean` | returns true if any of the specified objects are within the specified volume. [source](../source/hs/hs.c#L5877) | Host/local |
| `(volume_test_objects_all <trigger_volume> <object_list>)` | `boolean` | returns true if any of the specified objects are within the specified volume. [source](../source/hs/hs.c#L5893) | Host/local |

### Sound and music

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(debug_sounds_distances <string> <real> <real>)` | `void` | changes the minimum and maximum distances for all sound classes matching the substring. [source](../source/hs/hs.c#L10597) | Host/local |
| `(debug_sounds_enable <string> <boolean>)` | `void` | enables or disabled all sound classes matching the substring. [source](../source/hs/hs.c#L10581) | Host/local |
| `(debug_sounds_wet <string> <real>)` | `void` | changes the reverb level for all sound classes matching the substring. [source](../source/hs/hs.c#L10613) | Host/local |
| `(sound_cache_flush)` | `void` | Flushes the sound cache; legacy developer helper. [source](../source/hs/hs.c#L9781) | Host/local |
| `(sound_class_set_gain <string> <real> <short>)` | `void` | changes the gain on the specified sound class(es) to the specified game over the specified number of ticks. [source](../source/hs/hs.c#L10629) | Host/local |
| `(sound_enable <boolean>)` | `void` | enables or disables all sound. [source](../source/hs/hs.c#L10645) | Guest |
| `(sound_get_gain <string>)` | `real` | Returns a loaded sound tag's gain. Original help discourages use. [source](../source/hs/hs.c#L6233) | Host/local |
| `(sound_impulse_start <sound> <object> <real>)` | `void` | plays an impulse sound from the specified source object (or "none"), with the specified scale. [source](../source/hs/hs.c#L10457) | Host/local |
| `(sound_impulse_stop <sound>)` | `void` | stops the specified impulse sound. [source](../source/hs/hs.c#L10488) | Host/local |
| `(sound_impulse_time <sound>)` | `long` | returns the time remaining for the specified impulse sound. [source](../source/hs/hs.c#L10473) | Host/local |
| `(sound_looping_predict <looping_sound>)` | `void` | Runs the legacy looping-sound prediction/preload helper; original registry help has no useful description. [source](../source/hs/hs.c#L10503) | Host/local |
| `(sound_looping_set_alternate <looping_sound> <boolean>)` | `void` | enables or disables the alternate loop/alternate end for a looping sound. [source](../source/hs/hs.c#L10565) | Host/local |
| `(sound_looping_set_scale <looping_sound> <real>)` | `void` | changes the scale of the sound (which should affect the volume) within the range 0 to 1. [source](../source/hs/hs.c#L10549) | Host/local |
| `(sound_looping_start <looping_sound> <object> <real>)` | `void` | plays a looping sound from the specified source object (or "none"), with the specified scale. [source](../source/hs/hs.c#L10518) | Host/local |
| `(sound_looping_stop <looping_sound>)` | `void` | stops the specified looping sound. [source](../source/hs/hs.c#L10534) | Host/local |
| `(sound_set_gain <string> <real>)` | `void` | Changes the gain of a loaded sound tag named by the string. Not master volume; original help discourages use. [source](../source/hs/hs.c#L6217) | Guest |

### Cameras, cinematics and recordings

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(attract_mode_start)` | `void` | Starts attract mode; registry provides no help text. [source](../source/hs/hs.c#L10193) | Host/local |
| `(camera_control <boolean>)` | `void` | toggles script control of the camera. [source](../source/hs/hs.c#L9209) | Host/local |
| `(camera_set <cutscene_camera_point> <short>)` | `void` | moves the camera to the specified camera point over the specified number of ticks. [source](../source/hs/hs.c#L9224) | Host/local |
| `(camera_set_animation <animation_graph> <string>)` | `void` | begins a prerecorded camera animation. [source](../source/hs/hs.c#L9256) | Host/local |
| `(camera_set_dead <unit>)` | `void` | makes the scripted camera zoom out around a unit as if it were dead. [source](../source/hs/hs.c#L9287) | Host/local |
| `(camera_set_first_person <unit>)` | `void` | makes the scripted camera follow a unit. [source](../source/hs/hs.c#L9272) | Host/local |
| `(camera_set_relative <cutscene_camera_point> <short> <object>)` | `void` | moves the camera to the specified camera point over the specified number of ticks (position is relative to the specified object). [source](../source/hs/hs.c#L9240) | Host/local |
| `(camera_time)` | `short` | returns the number of ticks remaining in the current camera interpolation. [source](../source/hs/hs.c#L9302) | Host/local |
| `(cinematic_screen_effect_set_convolution <short> <short> <real> <real> <real>)` | `void` | sets the convolution effect [source](../source/hs/hs.c#L11341) | Host/local |
| `(cinematic_screen_effect_set_filter <real> <real> <real> <real> <boolean> <real>)` | `void` | sets the filter effect [source](../source/hs/hs.c#L11357) | Host/local |
| `(cinematic_screen_effect_set_filter_desaturation_tint <real> <real> <real>)` | `void` | sets the desaturation filter tint color [source](../source/hs/hs.c#L11373) | Host/local |
| `(cinematic_screen_effect_set_video <short> <real>)` | `void` | Sets video effect: first short = overbright (0 none, 1 2x, 2 4x); second real = noise intensity [0,1]. The original help lists these in the opposite order. [source](../source/hs/hs.c#L11389) | Host/local |
| `(cinematic_screen_effect_start <boolean>)` | `void` | starts screen effect; pass TRUE to clear [source](../source/hs/hs.c#L11326) | Host/local |
| `(cinematic_screen_effect_stop)` | `void` | returns control of the screen effects to the rest of the game [source](../source/hs/hs.c#L11405) | Host/local |
| `(cinematic_set_near_clip_distance <real>)` | `void` | Sets cinematic near-clip distance; registry provides no help text. [source](../source/hs/hs.c#L11417) | Host/local |
| `(cinematic_set_title <cutscene_title>)` | `void` | activates the chapter title [source](../source/hs/hs.c#L10147) | Host/local |
| `(cinematic_set_title_delayed <cutscene_title> <real>)` | `void` | activates the chapter title, delayed by &lt;real&gt; seconds [source](../source/hs/hs.c#L10162) | Host/local |
| `(cinematic_show_letterbox <boolean>)` | `void` | sets or removes the letterbox bars [source](../source/hs/hs.c#L10132) | Host/local |
| `(cinematic_skip_start_internal)` | `void` | Internal cinematic-skip helper; registry provides no help text. [source](../source/hs/hs.c#L10108) | Host/local |
| `(cinematic_skip_stop_internal)` | `void` | Internal cinematic-skip helper; registry provides no help text. [source](../source/hs/hs.c#L10120) | Host/local |
| `(cinematic_start)` | `void` | initializes game to start a cinematic (interruptive) cutscene [source](../source/hs/hs.c#L10084) | Host/local |
| `(cinematic_stop)` | `void` | initializes the game to end a cinematic (interruptive) cutscene [source](../source/hs/hs.c#L10096) | Host/local |
| `(cinematic_suppress_bsp_object_creation <boolean>)` | `void` | suppresses or enables the automatic creation of objects during cutscenes due to a bsp switch [source](../source/hs/hs.c#L10178) | Host/local |
| `(debug_camera_load)` | `void` | loads the saved camera position and facing. [source](../source/hs/hs.c#L9326) | Host/local |
| `(debug_camera_save)` | `void` | saves the camera position and facing. [source](../source/hs/hs.c#L9314) | Host/local |
| `(fade_in <real> <real> <real> <short>)` | `void` | does a screen fade in from a particular color [source](../source/hs/hs.c#L10052) | Host/local |
| `(fade_out <real> <real> <real> <short>)` | `void` | does a screen fade out to a particular color [source](../source/hs/hs.c#L10068) | Host/local |
| `(recording_kill <unit>)` | `void` | kill the specified unit's cutscene recording. [source](../source/hs/hs.c#L6437) | Host/local |
| `(recording_play <unit> <cutscene_recording>)` | `boolean` | make the specified unit run the specified cutscene recording. [source](../source/hs/hs.c#L6389) | Host/local |
| `(recording_play_and_delete <unit> <cutscene_recording>)` | `boolean` | make the specified unit run the specified cutscene recording, deletes the unit when the animation finishes. [source](../source/hs/hs.c#L6405) | Host/local |
| `(recording_play_and_hover <vehicle> <cutscene_recording>)` | `boolean` | make the specified vehicle run the specified cutscene recording, hovers the vehicle when the animation finishes. [source](../source/hs/hs.c#L6421) | Host/local |
| `(recording_time <unit>)` | `short` | return the time remaining in the specified unit's cutscene recording. [source](../source/hs/hs.c#L6452) | Host/local |

### Rendering, performance and developer diagnostics

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(debug_memory)` | `void` | dumps memory leaks. [source](../source/hs/hs.c#L9793) | Host/local |
| `(debug_memory_by_file)` | `void` | dumps memory leaks by source file. [source](../source/hs/hs.c#L9805) | Host/local |
| `(debug_memory_for_file <string>)` | `void` | dumps memory leaks from the specified source file. [source](../source/hs/hs.c#L9817) | Host/local |
| `(debug_pvs <boolean>)` | `void` | displays the current pvs. [source](../source/hs/hs.c#L9916) | Host/local |
| `(debug_tags)` | `void` | **No-op in current source.** Registered description: writes all memory being used by tag files into tag_dump.txt [source](../source/hs/hs.c#L9832) | Host/local |
| `(profile_activate <string>)` | `void` | activates profile sections based on a substring. [source](../source/hs/hs.c#L9871) | Host/local |
| `(profile_deactivate <string>)` | `void` | deactivates profile sections based on a substring. [source](../source/hs/hs.c#L9886) | Host/local |
| `(profile_dump <string>)` | `void` | dumps profile based on a substring. [source](../source/hs/hs.c#L9856) | Host/local |
| `(profile_graph_toggle <string>)` | `void` | enables or disables profile graph display of a particular value. [source](../source/hs/hs.c#L9901) | Host/local |
| `(profile_reset)` | `void` | resets profiling data. [source](../source/hs/hs.c#L9844) | Host/local |
| `(profile_unlock_solo_levels)` | `void` | unlocks all the solo player levels for player 1's profile [source](../source/hs/hs.c#L11468) | Host/local |
| `(radiosity_debug_point)` | `void` | **No-op in current source.** Registered description: tests sun occlusion at a point. [source](../source/hs/hs.c#L9955) | Host/local |
| `(radiosity_save)` | `void` | **No-op in current source.** Registered description: saves radiosity solution. [source](../source/hs/hs.c#L9943) | Host/local |
| `(radiosity_start)` | `void` | **No-op in current source.** Registered description: starts radiosity computation. [source](../source/hs/hs.c#L9931) | Host/local |
| `(rasterizer_decals_flush)` | `void` | flush all decals [source](../source/hs/hs.c#L11258) | Host/local |
| `(rasterizer_fps_accumulate)` | `void` | average fps [source](../source/hs/hs.c#L11270) | Guest |
| `(rasterizer_lights_reset_for_new_map)` | `void` | Renderer light-reset helper; registry provides no help text. [source](../source/hs/hs.c#L11298) | Host/local |
| `(rasterizer_model_ambient_reflection_tint <real> <real> <real> <real>)` | `void` | Legacy renderer ambient-reflection tint helper; registry provides no parameter meanings. [source](../source/hs/hs.c#L11282) | Host/local |
| `(render_effects <boolean>)` | `void` | Controls effect rendering (registry provides no help text). [source](../source/hs/hs.c#L6782) | Host/local |
| `(render_lights <boolean>)` | `boolean` | enables/disables dynamic lights [source](../source/hs/hs.c#L6720) | Host/local |
| `(structure_lens_flares_place)` | `void` | places lens flares in the structure bsp [source](../source/hs/hs.c#L10888) | Host/local |
| `(texture_cache_flush)` | `void` | Flushes the texture cache; legacy developer helper, original help discourages use. [source](../source/hs/hs.c#L9769) | Host/local |

### Devices and switches

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(device_get_position <device>)` | `real` | gets the current position of the given device (used for devices without explicit device groups) [source](../source/hs/hs.c#L7523) | Host/local |
| `(device_get_power <device>)` | `real` | gets the current power of a named device [source](../source/hs/hs.c#L7492) | Host/local |
| `(device_group_change_only_once_more_set <device_group> <boolean>)` | `void` | TRUE allows a device to change states only once [source](../source/hs/hs.c#L7633) | Host/local |
| `(device_group_get <device_group>)` | `real` | returns the desired value of the specified device group. [source](../source/hs/hs.c#L7554) | Host/local |
| `(device_group_set <device_group> <real>)` | `boolean` | changes the desired value of the specified device group. [source](../source/hs/hs.c#L7569) | Host/local |
| `(device_group_set_immediate <device_group> <real>)` | `void` | instantaneously changes the value of the specified device group. [source](../source/hs/hs.c#L7585) | Host/local |
| `(device_one_sided_set <device> <boolean>)` | `void` | TRUE makes the given device one-sided (only able to be opened from one direction), FALSE makes it two-sided [source](../source/hs/hs.c#L7601) | Host/local |
| `(device_operates_automatically_set <device> <boolean>)` | `void` | TRUE makes the given device open automatically when any biped is nearby, FALSE makes it not [source](../source/hs/hs.c#L7617) | Host/local |
| `(device_set_never_appears_locked <device> <boolean>)` | `void` | changes a machine's never_appears_locked flag, but only if paul is a bastard [source](../source/hs/hs.c#L7460) | Host/local |
| `(device_set_position <device> <real>)` | `boolean` | set the desired position of the given device (used for devices without explicit device groups) [source](../source/hs/hs.c#L7507) | Host/local |
| `(device_set_position_immediate <device> <real>)` | `void` | instantaneously changes the position of the given device (used for devices without explicit device groups [source](../source/hs/hs.c#L7538) | Host/local |
| `(device_set_power <device> <real>)` | `void` | immediately sets the power of a named device to the given value [source](../source/hs/hs.c#L7476) | Host/local |

### Cheats and practice

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(cheat_active_camouflage)` | `void` | gives the player active camouflage [source](../source/hs/hs.c#L7709) | Host/local |
| `(cheat_active_camouflage_local_player <short>)` | `void` | gives the player active camouflage [source](../source/hs/hs.c#L7721) | Host/local |
| `(cheat_all_powerups)` | `void` | drops all powerups near player [source](../source/hs/hs.c#L7661) | Host/local |
| `(cheat_all_vehicles)` | `void` | drops all vehicles on player [source](../source/hs/hs.c#L7685) | Host/local |
| `(cheat_all_weapons)` | `void` | drops all weapons near player [source](../source/hs/hs.c#L7673) | Host/local |
| `(cheat_teleport_to_camera)` | `void` | teleports player to camera location [source](../source/hs/hs.c#L7697) | Host/local |
| `(cheats_load)` | `void` | reloads the cheats.txt file [source](../source/hs/hs.c#L7736) | Host/local |

### Maps, game state, saves and multiplayer

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(core_load)` | `void` | loads debug game state from core\core.bin [source](../source/hs/hs.c#L10349) | Host/local |
| `(core_load_at_startup)` | `void` | loads debug game state from core\core.bin as soon as the map is initialized [source](../source/hs/hs.c#L10361) | Host/local |
| `(core_load_name <string>)` | `void` | loads debug game state from core\&lt;path&gt; [source](../source/hs/hs.c#L10373) | Host/local |
| `(core_load_name_at_startup <string>)` | `void` | loads debug game state from core\&lt;path&gt; as soon as the map is initialized [source](../source/hs/hs.c#L10388) | Host/local |
| `(core_save)` | `void` | saves debug game state to core\core.bin [source](../source/hs/hs.c#L10403) | Host/local |
| `(core_save_name <string>)` | `void` | saves debug game state to core\&lt;path&gt; [source](../source/hs/hs.c#L10415) | Host/local |
| `(display_scenario_help <short>)` | `void` | display in-game help dialog [source](../source/hs/hs.c#L11534) | Host/local |
| `(fast_setup_network_server)` | `void` | for zach's multiplayer testing [source](../source/hs/hs.c#L11456) | Host/local |
| `(game_all_quiet)` | `boolean` | returns FALSE if there are bad guys around, projectiles in the air, etc. [source](../source/hs/hs.c#L10241) | Host/local |
| `(game_difficulty_get)` | `game_difficulty` | returns the current difficulty setting, but lies to you and will never return easy, instead returning normal [source](../source/hs/hs.c#L9380) | Host/local |
| `(game_difficulty_get_real)` | `game_difficulty` | returns the actual current difficulty setting without lying [source](../source/hs/hs.c#L9392) | Host/local |
| `(game_difficulty_set <game_difficulty>)` | `void` | changes the difficulty setting for the next map to be loaded. [source](../source/hs/hs.c#L9688) | Host/local |
| `(game_is_cooperative)` | `boolean` | returns TRUE if the game is cooperative [source](../source/hs/hs.c#L10265) | Host/local |
| `(game_lost)` | `void` | causes the player to revert to his previous saved game [source](../source/hs/hs.c#L10217) | Host/local |
| `(game_revert)` | `void` | Reverts to the last saved game, if any. [source](../source/hs/hs.c#L10337) | Host/local |
| `(game_reverted)` | `boolean` | Internal game-revert state query; original help discourages use. [source](../source/hs/hs.c#L10445) | Host/local |
| `(game_safe_to_save)` | `boolean` | returns FALSE if it would be a bad idea to save the player's game right now [source](../source/hs/hs.c#L10229) | Host/local |
| `(game_safe_to_speak)` | `boolean` | returns FALSE if it would be a bad idea to save the player's game right now [source](../source/hs/hs.c#L10253) | Host/local |
| `(game_save)` | `void` | checks to see if it is safe to save game, then saves (gives up after 8 seconds) [source](../source/hs/hs.c#L10277) | Host/local |
| `(game_save_cancel)` | `void` | cancels any pending game_save, timeout or not [source](../source/hs/hs.c#L10289) | Host/local |
| `(game_save_no_timeout)` | `void` | checks to see if it is safe to save game, then saves (this version never gives up) [source](../source/hs/hs.c#L10301) | Host/local |
| `(game_save_totally_unsafe)` | `void` | disregards player's current situation [source](../source/hs/hs.c#L10313) | Host/local |
| `(game_saving)` | `boolean` | checks to see if the game is trying to save the map. [source](../source/hs/hs.c#L10325) | Host/local |
| `(game_skip_ticks <short>)` | `void` | skips &lt;short&gt; amount of game ticks. ONLY USE IN CUTSCENES!!! [source](../source/hs/hs.c#L10430) | Host/local |
| `(game_speed <real>)` | `void` | changes the game speed. [source](../source/hs/hs.c#L9338) | Host/local |
| `(game_time)` | `long` | gets ticks elapsed since the start of the game. [source](../source/hs/hs.c#L9368) | Host/local |
| `(game_variant <string>)` | `void` | set the game engine [source](../source/hs/hs.c#L9353) | Host/local |
| `(game_won)` | `void` | causes the player to successfully finish the current level and move to the next [source](../source/hs/hs.c#L10205) | Host/local |
| `(map_name <string>)` | `void` | changes the name of the solo player map. [source](../source/hs/hs.c#L9658) | Host/local |
| `(map_reset)` | `void` | starts the map from the beginning. [source](../source/hs/hs.c#L9646) | Host/local |
| `(multiplayer_map_name <string>)` | `void` | changes the name of the multiplayer map Selects/pre-caches; does not itself switch a running host match. [source](../source/hs/hs.c#L9673) | Host/local |
| `(network_game_start_now)` | `void` | Requests immediate network game start through the client manager; session/host authority still applies. [source](../source/hs/hs.c#L11549) | Host/local |
| `(switch_bsp <short>)` | `void` | takes off your condom and changes to a different structure bsp [source](../source/hs/hs.c#L9718) | Host/local |
| `(ui_widget_show_path <boolean>)` | `void` | Enables/disables the UI widget path diagnostic. [source](../source/hs/hs.c#L11519) | Host/local |
| `(xbox_set_machine_name <string>)` | `void` | Sets the machine name through the Xbox-era naming helper; native-platform effect depends on implementation. [source](../source/hs/hs.c#L11561) | Host/local |

### Players, input, HUD and navigation

| Signature | Returns | Purpose / original help | Access |
| --- | --- | --- | --- |
| `(activate_nav_point_flag <navpoint> <unit> <cutscene_flag> <real>)` | `void` | activates a nav point type &lt;string&gt; attached to (local) player &lt;unit&gt; anchored to a flag with a vertical offset &lt;real&gt;. If the player is not local to the machine, this will fail [source](../source/hs/hs.c#L10733) | Host/local |
| `(activate_nav_point_object <navpoint> <unit> <object> <real>)` | `void` | activates a nav point type &lt;string&gt; attached to (local) player &lt;unit&gt; anchored to an object with a vertical offset &lt;real&gt;. If the player is not local to the machine, this will fail [source](../source/hs/hs.c#L10749) | Host/local |
| `(deactivate_nav_point_flag <unit> <cutscene_flag>)` | `void` | deactivates a nav point type attached to a player &lt;unit&gt; anchored to a flag [source](../source/hs/hs.c#L10797) | Host/local |
| `(deactivate_nav_point_object <unit> <object>)` | `void` | deactivates a nav point type attached to a player &lt;unit&gt; anchored to an object [source](../source/hs/hs.c#L10813) | Host/local |
| `(debug_teleport_player <short> <short>)` | `void` | Developer player teleport helper; registry provides no parameter meanings. [source](../source/hs/hs.c#L9630) | Host/local |
| `(enable_hud_help_flash <boolean>)` | `void` | starts/stops the help text flashing [source](../source/hs/hs.c#L10706) | Host/local |
| `(hud_blink_health <boolean>)` | `void` | starts/stops manual blinking of the health panel [source](../source/hs/hs.c#L10994) | Host/local |
| `(hud_blink_motion_sensor <boolean>)` | `void` | starts/stops manual blinking of the motion sensor panel [source](../source/hs/hs.c#L11054) | Host/local |
| `(hud_blink_shield <boolean>)` | `void` | starts/stops manual blinking of the shield panel [source](../source/hs/hs.c#L11024) | Host/local |
| `(hud_clear_messages)` | `void` | clears all non-state messages on the hud [source](../source/hs/hs.c#L11084) | Host/local |
| `(hud_get_timer_ticks)` | `short` | returns the ticks left on the hud timer [source](../source/hs/hs.c#L11204) | Host/local |
| `(hud_help_flash_restart)` | `void` | resets the timer for the help text flashing [source](../source/hs/hs.c#L10721) | Host/local |
| `(hud_set_help_text <hud_message>)` | `void` | displays &lt;message&gt; as the help text [source](../source/hs/hs.c#L11096) | Host/local |
| `(hud_set_objective_text <hud_message>)` | `void` | sets &lt;message&gt; as the current objective [source](../source/hs/hs.c#L11111) | Host/local |
| `(hud_set_timer_position <short> <short> <hud_corner>)` | `void` | sets the timer upper left position to (x, y)=&gt;(&lt;short&gt;, &lt;short&gt;) [source](../source/hs/hs.c#L11158) | Host/local |
| `(hud_set_timer_time <short> <short>)` | `void` | sets the time for the timer to &lt;short&gt; minutes and &lt;short&gt; seconds, and starts and displays timer [source](../source/hs/hs.c#L11126) | Host/local |
| `(hud_set_timer_warning_time <short> <short>)` | `void` | sets the warning time for the timer to &lt;short&gt; minutes and &lt;short&gt; seconds [source](../source/hs/hs.c#L11142) | Host/local |
| `(hud_show_crosshair <boolean>)` | `void` | hides/shows the weapon crosshair [source](../source/hs/hs.c#L11069) | Guest |
| `(hud_show_health <boolean>)` | `void` | hides/shows the health panel [source](../source/hs/hs.c#L10979) | Guest |
| `(hud_show_motion_sensor <boolean>)` | `void` | hides/shows the motion sensor panel [source](../source/hs/hs.c#L11039) | Guest |
| `(hud_show_shield <boolean>)` | `void` | hides/shows the shield panel [source](../source/hs/hs.c#L11009) | Guest |
| `(player0_joystick_set_is_normal)` | `boolean` | returns TRUE if player0 is using the normal joystick set [source](../source/hs/hs.c#L11507) | Host/local |
| `(player0_look_invert_pitch <boolean>)` | `void` | invert player0's look [source](../source/hs/hs.c#L11480) | Host/local |
| `(player0_look_pitch_is_inverted)` | `boolean` | returns TRUE if player0's look pitch is inverted [source](../source/hs/hs.c#L11495) | Host/local |
| `(player_action_test_accept)` | `boolean` | returns true if any player has hit accept since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9518) | Host/local |
| `(player_action_test_action)` | `boolean` | returns true if any player has hit the action key since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9506) | Host/local |
| `(player_action_test_back)` | `boolean` | returns true if any player has hit the back key since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9530) | Host/local |
| `(player_action_test_grenade_trigger)` | `boolean` | returns true if any player has used grenade trigger since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9482) | Host/local |
| `(player_action_test_jump)` | `boolean` | returns true if any player has jumped since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9458) | Host/local |
| `(player_action_test_look_relative_all_directions)` | `boolean` | returns true if any player has looked up, down, left, and right since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9590) | Host/local |
| `(player_action_test_look_relative_down)` | `boolean` | returns true if any player has looked down since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9554) | Host/local |
| `(player_action_test_look_relative_left)` | `boolean` | returns true if any player has looked left since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9566) | Host/local |
| `(player_action_test_look_relative_right)` | `boolean` | returns true if any player has looked right since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9578) | Host/local |
| `(player_action_test_look_relative_up)` | `boolean` | returns true if any player has looked up since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9542) | Host/local |
| `(player_action_test_move_relative_all_directions)` | `boolean` | returns true if any player has moved forward, backward, left, and right since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9602) | Host/local |
| `(player_action_test_primary_trigger)` | `boolean` | returns true if any player has used primary trigger since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9470) | Host/local |
| `(player_action_test_reset)` | `void` | resets the player action test state so that all tests will return false. [source](../source/hs/hs.c#L9446) | Host/local |
| `(player_action_test_zoom)` | `boolean` | returns true if any player has hit the zoom button since the last call to (player_action_test_reset). [source](../source/hs/hs.c#L9494) | Host/local |
| `(player_add_equipment <unit> <starting_profile> <boolean>)` | `void` | adds/resets the player's health, shield, and inventory (weapons and grenades) to the named profile. resets if third parameter is true, adds if false. [source](../source/hs/hs.c#L9614) | Host/local |
| `(player_camera_control <boolean>)` | `boolean` | enables/disables camera control globally [source](../source/hs/hs.c#L9431) | Host/local |
| `(player_effect_set_max_rotation <real> <real> <real>)` | `void` | &lt;yaw&gt; &lt;pitch&gt; &lt;roll&gt; [source](../source/hs/hs.c#L10916) | Host/local |
| `(player_effect_set_max_rumble <real> <real>)` | `void` | &lt;left&gt; &lt;right&gt; [source](../source/hs/hs.c#L10932) | Host/local |
| `(player_effect_set_max_translation <real> <real> <real>)` | `void` | &lt;x&gt; &lt;y&gt; &lt;z&gt; [source](../source/hs/hs.c#L10900) | Host/local |
| `(player_effect_start <real> <real>)` | `void` | &lt;max_intensity&gt; &lt;attack time&gt; [source](../source/hs/hs.c#L10948) | Host/local |
| `(player_effect_stop <real>)` | `void` | &lt;decay&gt; [source](../source/hs/hs.c#L10964) | Host/local |
| `(player_enable_input <boolean>)` | `void` | toggle player input. the player can still free-look, but nothing else. [source](../source/hs/hs.c#L9416) | Host/local |
| `(players_unzoom_all)` | `void` | resets zoom levels on all players [source](../source/hs/hs.c#L9404) | Host/local |
| `(show_hud <boolean>)` | `boolean` | shows or hides the hud [source](../source/hs/hs.c#L10676) | Guest |
| `(show_hud_help_text <boolean>)` | `boolean` | shows or hides the hud help text [source](../source/hs/hs.c#L10691) | Guest |
| `(show_hud_timer <boolean>)` | `void` | displays the hud timer [source](../source/hs/hs.c#L11174) | Guest |

## Complete variable catalog

These are variables, not callable functions. For a boolean use `name true` or
`name false`; for a number use `name 0.5` or an appropriate integer. The general
explicit form is `(set name value)`. Host/local users can print values with
`inspect name`. The joining-client allowlist also applies to reads and writes.

Unlike functions, these registrations have **no built-in descriptions**. The
purpose labels below are plain-language interpretations of each name/backing
field unless the quick reference explains verified behavior. They do not define
valid numeric ranges, defaults or guarantee a visible effect. Do not guess values
for renderer internals, AI tuning, counters, or padding/experimental variables.
The linked source shows the exact type and storage binding.

Five compatibility names have no backing storage: the four `radiosity_*`
variables and `run_game_scripts`. They read type defaults and writes have no
engine effect. `decals` appears in two legacy registry slots and is listed once.

### Renderer, graphics and legacy lightmapping

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `f0` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.f[0]`. [source](../source/hs/hs_globals_external.c#L1260) | Host/local |
| `f1` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.f[1]`. [source](../source/hs/hs_globals_external.c#L1262) | Host/local |
| `f2` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.f[2]`. [source](../source/hs/hs_globals_external.c#L1264) | Host/local |
| `f3` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.f[3]`. [source](../source/hs/hs_globals_external.c#L1266) | Host/local |
| `f4` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.f[4]`. [source](../source/hs/hs_globals_external.c#L1268) | Host/local |
| `f5` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.f[5]`. [source](../source/hs/hs_globals_external.c#L1270) | Host/local |
| `force_all_player_views_to_default_player` | `boolean` | Legacy control/diagnostic for force all player views to default player. [source](../source/hs/hs_globals_external.c#L1240) | Host/local |
| `pad3` | `short` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.pad3`. [source](../source/hs/hs_globals_external.c#L1256) | Host/local |
| `pad3_scale` | `real` | Legacy renderer scratch/padding variable; no supported setting contract. Binding: `&rasterizer_debug_options.pad3_scale`. [source](../source/hs/hs_globals_external.c#L1258) | Host/local |
| `radiosity_lines` | `boolean` | **Inert compatibility name:** no backing engine storage; reads type default and ignores writes. [source](../source/hs/hs_globals_external.c#L1286) | Host/local |
| `radiosity_normals` | `boolean` | **Inert compatibility name:** no backing engine storage; reads type default and ignores writes. [source](../source/hs/hs_globals_external.c#L1288) | Host/local |
| `radiosity_quality` | `short` | **Inert compatibility name:** no backing engine storage; reads type default and ignores writes. [source](../source/hs/hs_globals_external.c#L1282) | Host/local |
| `radiosity_step_count` | `short` | **Inert compatibility name:** no backing engine storage; reads type default and ignores writes. [source](../source/hs/hs_globals_external.c#L1284) | Host/local |
| `rasterizer_DXTC_noise` | `boolean` | Legacy renderer control/diagnostic: DXTC noise. [source](../source/hs/hs_globals_external.c#L1226) | Host/local |
| `rasterizer_active_camouflage` | `boolean` | Legacy renderer control/diagnostic: active camouflage. [source](../source/hs/hs_globals_external.c#L1210) | Host/local |
| `rasterizer_active_camouflage_multipass` | `boolean` | Legacy renderer control/diagnostic: active camouflage multipass. [source](../source/hs/hs_globals_external.c#L1212) | Host/local |
| `rasterizer_bump_mapping` | `boolean` | Legacy renderer control/diagnostic: bump mapping. [source](../source/hs/hs_globals_external.c#L1188) | Host/local |
| `rasterizer_debug_geometry` | `boolean` | Legacy renderer control/diagnostic: debug geometry. [source](../source/hs/hs_globals_external.c#L1180) | Host/local |
| `rasterizer_debug_geometry_multipass` | `boolean` | Legacy renderer control/diagnostic: debug geometry multipass. [source](../source/hs/hs_globals_external.c#L1182) | Host/local |
| `rasterizer_debug_meter_shader` | `boolean` | Legacy renderer control/diagnostic: debug meter shader. [source](../source/hs/hs_globals_external.c#L1128) | Host/local |
| `rasterizer_debug_model_lod` | `short` | Legacy renderer control/diagnostic: debug model lod. [source](../source/hs/hs_globals_external.c#L1124) | Host/local |
| `rasterizer_debug_model_vertices` | `boolean` | Legacy renderer control/diagnostic: debug model vertices. [source](../source/hs/hs_globals_external.c#L1122) | Host/local |
| `rasterizer_debug_transparents` | `boolean` | Legacy renderer control/diagnostic: debug transparents. [source](../source/hs/hs_globals_external.c#L1126) | Host/local |
| `rasterizer_detail_objects` | `boolean` | Legacy renderer control/diagnostic: detail objects. [source](../source/hs/hs_globals_external.c#L1178) | Host/local |
| `rasterizer_detail_objects_offset_multiplier` | `real` | Legacy renderer control/diagnostic: detail objects offset multiplier. [source](../source/hs/hs_globals_external.c#L1234) | Host/local |
| `rasterizer_draw_first_person_weapon_first` | `boolean` | Legacy renderer control/diagnostic: draw first person weapon first. [source](../source/hs/hs_globals_external.c#L1134) | Host/local |
| `rasterizer_dynamic_lit_geometry` | `boolean` | Legacy renderer control/diagnostic: dynamic lit geometry. [source](../source/hs/hs_globals_external.c#L1172) | Host/local |
| `rasterizer_dynamic_screen_geometry` | `boolean` | Legacy renderer control/diagnostic: dynamic screen geometry. [source](../source/hs/hs_globals_external.c#L1174) | Host/local |
| `rasterizer_dynamic_unlit_geometry` | `boolean` | Legacy renderer control/diagnostic: dynamic unlit geometry. [source](../source/hs/hs_globals_external.c#L1170) | Host/local |
| `rasterizer_environment` | `boolean` | Legacy renderer control/diagnostic: environment. [source](../source/hs/hs_globals_external.c#L1138) | Host/local |
| `rasterizer_environment_alpha_testing` | `boolean` | Legacy renderer control/diagnostic: environment alpha testing. [source](../source/hs/hs_globals_external.c#L1200) | Host/local |
| `rasterizer_environment_decals` | `boolean` | Legacy renderer control/diagnostic: environment decals. [source](../source/hs/hs_globals_external.c#L1148) | Host/local |
| `rasterizer_environment_diffuse_lights` | `boolean` | Legacy renderer control/diagnostic: environment diffuse lights. [source](../source/hs/hs_globals_external.c#L1144) | Host/local |
| `rasterizer_environment_diffuse_textures` | `boolean` | Legacy renderer control/diagnostic: environment diffuse textures. [source](../source/hs/hs_globals_external.c#L1146) | Host/local |
| `rasterizer_environment_fog` | `boolean` | Legacy renderer control/diagnostic: environment fog. [source](../source/hs/hs_globals_external.c#L1162) | Host/local |
| `rasterizer_environment_fog_screen` | `boolean` | Legacy renderer control/diagnostic: environment fog screen. [source](../source/hs/hs_globals_external.c#L1164) | Host/local |
| `rasterizer_environment_lightmaps` | `boolean` | Legacy renderer control/diagnostic: environment lightmaps. [source](../source/hs/hs_globals_external.c#L1140) | Host/local |
| `rasterizer_environment_reflection_lightmap_mask` | `boolean` | Legacy renderer control/diagnostic: environment reflection lightmap mask. [source](../source/hs/hs_globals_external.c#L1154) | Host/local |
| `rasterizer_environment_reflection_mirrors` | `boolean` | Legacy renderer control/diagnostic: environment reflection mirrors. [source](../source/hs/hs_globals_external.c#L1156) | Host/local |
| `rasterizer_environment_reflections` | `boolean` | Legacy renderer control/diagnostic: environment reflections. [source](../source/hs/hs_globals_external.c#L1158) | Host/local |
| `rasterizer_environment_shadows` | `boolean` | Legacy renderer control/diagnostic: environment shadows. [source](../source/hs/hs_globals_external.c#L1142) | Host/local |
| `rasterizer_environment_specular_lightmaps` | `boolean` | Legacy renderer control/diagnostic: environment specular lightmaps. [source](../source/hs/hs_globals_external.c#L1152) | Host/local |
| `rasterizer_environment_specular_lights` | `boolean` | Legacy renderer control/diagnostic: environment specular lights. [source](../source/hs/hs_globals_external.c#L1150) | Host/local |
| `rasterizer_environment_specular_mask` | `boolean` | Legacy renderer control/diagnostic: environment specular mask. [source](../source/hs/hs_globals_external.c#L1202) | Host/local |
| `rasterizer_environment_transparents` | `boolean` | Legacy renderer control/diagnostic: environment transparents. [source](../source/hs/hs_globals_external.c#L1160) | Host/local |
| `rasterizer_far_clip_distance` | `real` | Legacy renderer control/diagnostic: far clip distance. [source](../source/hs/hs_globals_external.c#L1088) | Host/local |
| `rasterizer_filthy_decal_fog_hack` | `boolean` | Legacy renderer control/diagnostic: filthy decal fog hack. [source](../source/hs/hs_globals_external.c#L1248) | Host/local |
| `rasterizer_first_person_weapon_far_clip_distance` | `real` | Legacy renderer control/diagnostic: first person weapon far clip distance. [source](../source/hs/hs_globals_external.c#L1092) | Host/local |
| `rasterizer_first_person_weapon_near_clip_distance` | `real` | Legacy renderer control/diagnostic: first person weapon near clip distance. [source](../source/hs/hs_globals_external.c#L1090) | Host/local |
| `rasterizer_floating_point_zbuffer` | `boolean` | Legacy renderer control/diagnostic: floating point zbuffer. [source](../source/hs/hs_globals_external.c#L1098) | Host/local |
| `rasterizer_fog_atmosphere` | `boolean` | Legacy renderer control/diagnostic: fog atmosphere. [source](../source/hs/hs_globals_external.c#L1184) | Host/local |
| `rasterizer_fog_plane` | `boolean` | Legacy renderer control/diagnostic: fog plane. [source](../source/hs/hs_globals_external.c#L1186) | Host/local |
| `rasterizer_frame_bounds_bottom` | `short` | Legacy renderer control/diagnostic: frame bounds bottom. [source](../source/hs/hs_globals_external.c#L1112) | Host/local |
| `rasterizer_frame_bounds_left` | `short` | Legacy renderer control/diagnostic: frame bounds left. [source](../source/hs/hs_globals_external.c#L1106) | Host/local |
| `rasterizer_frame_bounds_right` | `short` | Legacy renderer control/diagnostic: frame bounds right. [source](../source/hs/hs_globals_external.c#L1108) | Host/local |
| `rasterizer_frame_bounds_top` | `short` | Legacy renderer control/diagnostic: frame bounds top. [source](../source/hs/hs_globals_external.c#L1110) | Host/local |
| `rasterizer_framerate_stabilization` | `boolean` | Legacy renderer control/diagnostic: framerate stabilization. [source](../source/hs/hs_globals_external.c#L1102) | Host/local |
| `rasterizer_framerate_throttle` | `boolean` | Legacy renderer control/diagnostic: framerate throttle. [source](../source/hs/hs_globals_external.c#L1100) | Host/local |
| `rasterizer_hud_motion_sensor` | `boolean` | Legacy renderer control/diagnostic: hud motion sensor. [source](../source/hs/hs_globals_external.c#L1176) | Host/local |
| `rasterizer_lens_flares` | `boolean` | Legacy renderer control/diagnostic: lens flares. [source](../source/hs/hs_globals_external.c#L1168) | Host/local |
| `rasterizer_lens_flares_occlusion` | `boolean` | Legacy renderer control/diagnostic: lens flares occlusion. [source](../source/hs/hs_globals_external.c#L1216) | Host/local |
| `rasterizer_lens_flares_occlusion_debug` | `boolean` | Legacy renderer control/diagnostic: lens flares occlusion debug. [source](../source/hs/hs_globals_external.c#L1218) | Host/local |
| `rasterizer_lightmap_ambient` | `real` | Legacy renderer control/diagnostic: lightmap ambient. [source](../source/hs/hs_globals_external.c#L1190) | Host/local |
| `rasterizer_lightmap_mode` | `short` | Legacy renderer control/diagnostic: lightmap mode. [source](../source/hs/hs_globals_external.c#L1192) | Host/local |
| `rasterizer_lightmaps_filtering` | `boolean` | Legacy renderer control/diagnostic: lightmaps filtering. [source](../source/hs/hs_globals_external.c#L1196) | Host/local |
| `rasterizer_lightmaps_incident_radiosity` | `boolean` | Legacy renderer control/diagnostic: lightmaps incident radiosity. [source](../source/hs/hs_globals_external.c#L1194) | Host/local |
| `rasterizer_mode` | `short` | Legacy renderer control/diagnostic: mode. [source](../source/hs/hs_globals_external.c#L1116) | Host/local |
| `rasterizer_model_lighting_ambient` | `real` | Legacy renderer control/diagnostic: model lighting ambient. [source](../source/hs/hs_globals_external.c#L1198) | Host/local |
| `rasterizer_model_transparents` | `boolean` | Legacy renderer control/diagnostic: model transparents. [source](../source/hs/hs_globals_external.c#L1132) | Host/local |
| `rasterizer_models` | `boolean` | Legacy renderer control/diagnostic: models. [source](../source/hs/hs_globals_external.c#L1130) | Host/local |
| `rasterizer_near_clip_distance` | `real` | Legacy renderer control/diagnostic: near clip distance. [source](../source/hs/hs_globals_external.c#L1086) | Host/local |
| `rasterizer_plasma_energy` | `boolean` | Legacy renderer control/diagnostic: plasma energy. [source](../source/hs/hs_globals_external.c#L1214) | Host/local |
| `rasterizer_profile_log` | `boolean` | Legacy renderer control/diagnostic: profile log. [source](../source/hs/hs_globals_external.c#L1232) | Host/local |
| `rasterizer_profile_objectlock_time` | `real` | Legacy renderer control/diagnostic: profile objectlock time. [source](../source/hs/hs_globals_external.c#L1254) | Host/local |
| `rasterizer_profile_print_locks` | `boolean` | Legacy renderer control/diagnostic: profile print locks. [source](../source/hs/hs_globals_external.c#L1252) | Host/local |
| `rasterizer_pushbuffer_kickoff_size` | `short` | Legacy renderer control/diagnostic: pushbuffer kickoff size. [source](../source/hs/hs_globals_external.c#L1096) | Host/local |
| `rasterizer_pushbuffer_size` | `short` | Legacy renderer control/diagnostic: pushbuffer size. [source](../source/hs/hs_globals_external.c#L1094) | Host/local |
| `rasterizer_ray_of_buddha` | `boolean` | Legacy renderer control/diagnostic: ray of buddha. [source](../source/hs/hs_globals_external.c#L1220) | Host/local |
| `rasterizer_refresh_rate` | `short` | Legacy renderer control/diagnostic: refresh rate. [source](../source/hs/hs_globals_external.c#L1104) | Host/local |
| `rasterizer_safe_frame_bounds` | `boolean` | Legacy renderer control/diagnostic: safe frame bounds. [source](../source/hs/hs_globals_external.c#L1242) | Host/local |
| `rasterizer_screen_effects` | `boolean` | Legacy renderer control/diagnostic: screen effects. [source](../source/hs/hs_globals_external.c#L1224) | Host/local |
| `rasterizer_screen_flashes` | `boolean` | Legacy renderer control/diagnostic: screen flashes. [source](../source/hs/hs_globals_external.c#L1222) | Host/local |
| `rasterizer_secondary_render_target_debug` | `boolean` | Legacy renderer control/diagnostic: secondary render target debug. [source](../source/hs/hs_globals_external.c#L1230) | Host/local |
| `rasterizer_shadows_convolution` | `boolean` | Legacy renderer control/diagnostic: shadows convolution. [source](../source/hs/hs_globals_external.c#L1204) | Host/local |
| `rasterizer_shadows_debug` | `boolean` | Legacy renderer control/diagnostic: shadows debug. [source](../source/hs/hs_globals_external.c#L1206) | Host/local |
| `rasterizer_smart` | `boolean` | Legacy renderer control/diagnostic: smart. [source](../source/hs/hs_globals_external.c#L1120) | Host/local |
| `rasterizer_soft_filter` | `boolean` | Legacy renderer control/diagnostic: soft filter. [source](../source/hs/hs_globals_external.c#L1228) | Host/local |
| `rasterizer_splitscreen_VB_optimization` | `boolean` | Legacy renderer control/diagnostic: splitscreen VB optimization. [source](../source/hs/hs_globals_external.c#L1250) | Host/local |
| `rasterizer_stats` | `short` | Legacy renderer control/diagnostic: stats. [source](../source/hs/hs_globals_external.c#L1114) | Host/local |
| `rasterizer_stencil_mask` | `boolean` | Legacy renderer control/diagnostic: stencil mask. [source](../source/hs/hs_globals_external.c#L1136) | Host/local |
| `rasterizer_transparent_pixel_counter` | `boolean` | Legacy renderer control/diagnostic: transparent pixel counter. [source](../source/hs/hs_globals_external.c#L1272) | Host/local |
| `rasterizer_water` | `boolean` | Legacy renderer control/diagnostic: water. [source](../source/hs/hs_globals_external.c#L1166) | Host/local |
| `rasterizer_water_mipmapping` | `boolean` | Legacy renderer control/diagnostic: water mipmapping. [source](../source/hs/hs_globals_external.c#L1208) | Host/local |
| `rasterizer_wireframe` | `boolean` | Legacy renderer control/diagnostic: wireframe. [source](../source/hs/hs_globals_external.c#L1118) | Host/local |
| `rasterizer_zbias` | `long` | Legacy renderer control/diagnostic: zbias. [source](../source/hs/hs_globals_external.c#L1236) | Host/local |
| `rasterizer_zoffset` | `real` | Legacy renderer control/diagnostic: zoffset. [source](../source/hs/hs_globals_external.c#L1238) | Host/local |
| `rasterizer_zsprites` | `boolean` | Legacy renderer control/diagnostic: zsprites. [source](../source/hs/hs_globals_external.c#L1246) | Host/local |
| `texture_cache_graph` | `boolean` | Legacy control/diagnostic for texture cache graph. [source](../source/hs/hs_globals_external.c#L1926) | Host/local |
| `texture_cache_list` | `boolean` | Legacy control/diagnostic for texture cache list. [source](../source/hs/hs_globals_external.c#L1928) | Host/local |

### Console, profiling and other developer controls

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `allow_out_of_sync` | `boolean` | Legacy out-of-sync allowance; internal diagnostic control. [source](../source/hs/hs_globals_external.c#L1940) | Host/local |
| `console_dump_to_file` | `boolean` | Additionally append console_printf/warning output to the error log. [source](../source/hs/hs_globals_external.c#L1084) | Guest |
| `debug_bink` | `boolean` | Developer diagnostic/control: bink. [source](../source/hs/hs_globals_external.c#L1278) | Host/local |
| `debug_bsp` | `boolean` | Developer diagnostic/control: bsp. [source](../source/hs/hs_globals_external.c#L1570) | Host/local |
| `debug_camera` | `boolean` | Developer diagnostic/control: camera. [source](../source/hs/hs_globals_external.c#L1564) | Host/local |
| `debug_collision_skip_objects` | `boolean` | Developer diagnostic/control: collision skip objects. [source](../source/hs/hs_globals_external.c#L1596) | Host/local |
| `debug_collision_skip_vectors` | `boolean` | Developer diagnostic/control: collision skip vectors. [source](../source/hs/hs_globals_external.c#L1598) | Host/local |
| `debug_damage` | `boolean` | Developer diagnostic/control: damage. [source](../source/hs/hs_globals_external.c#L1466) | Host/local |
| `debug_damage_taken` | `boolean` | Developer diagnostic/control: damage taken. [source](../source/hs/hs_globals_external.c#L1318) | Host/local |
| `debug_detail_objects` | `boolean` | Developer diagnostic/control: detail objects. [source](../source/hs/hs_globals_external.c#L1292) | Host/local |
| `debug_fog_planes` | `boolean` | Developer diagnostic/control: fog planes. [source](../source/hs/hs_globals_external.c#L1576) | Host/local |
| `debug_framerate` | `boolean` | Developer diagnostic/control: framerate. [source](../source/hs/hs_globals_external.c#L1072) | Host/local |
| `debug_frustum` | `boolean` | Developer diagnostic/control: frustum. [source](../source/hs/hs_globals_external.c#L1276) | Host/local |
| `debug_game_save` | `boolean` | Developer diagnostic/control: game save. [source](../source/hs/hs_globals_external.c#L1080) | Host/local |
| `debug_inactive_objects` | `boolean` | Developer diagnostic/control: inactive objects. [source](../source/hs/hs_globals_external.c#L1414) | Host/local |
| `debug_input` | `boolean` | Developer diagnostic/control: input. [source](../source/hs/hs_globals_external.c#L1572) | Host/local |
| `debug_input_target` | `short` | Developer diagnostic/control: input target. [source](../source/hs/hs_globals_external.c#L1304) | Host/local |
| `debug_leaf_index` | `long` | Developer diagnostic/control: leaf index. [source](../source/hs/hs_globals_external.c#L1306) | Host/local |
| `debug_leaf_portal_index` | `long` | Developer diagnostic/control: leaf portal index. [source](../source/hs/hs_globals_external.c#L1308) | Host/local |
| `debug_leaf_portals` | `boolean` | Developer diagnostic/control: leaf portals. [source](../source/hs/hs_globals_external.c#L1310) | Host/local |
| `debug_lights` | `boolean` | Developer diagnostic/control: lights. [source](../source/hs/hs_globals_external.c#L1586) | Host/local |
| `debug_looping_sound` | `boolean` | Developer diagnostic/control: looping sound. [source](../source/hs/hs_globals_external.c#L1348) | Host/local |
| `debug_material_effects` | `boolean` | Developer diagnostic/control: material effects. [source](../source/hs/hs_globals_external.c#L1600) | Host/local |
| `debug_motion_sensor_draw_all_units` | `boolean` | Developer diagnostic/control: motion sensor draw all units. [source](../source/hs/hs_globals_external.c#L1476) | Host/local |
| `debug_no_drawing` | `boolean` | Developer diagnostic/control: no drawing. [source](../source/hs/hs_globals_external.c#L1302) | Host/local |
| `debug_no_frustum_clip` | `boolean` | Developer diagnostic/control: no frustum clip. [source](../source/hs/hs_globals_external.c#L1274) | Host/local |
| `debug_obstacle_path` | `boolean` | Developer diagnostic/control: obstacle path. [source](../source/hs/hs_globals_external.c#L1548) | Host/local |
| `debug_obstacle_path_goal_point_x` | `real` | Developer diagnostic/control: obstacle path goal point x. [source](../source/hs/hs_globals_external.c#L1558) | Host/local |
| `debug_obstacle_path_goal_point_y` | `real` | Developer diagnostic/control: obstacle path goal point y. [source](../source/hs/hs_globals_external.c#L1560) | Host/local |
| `debug_obstacle_path_goal_surface_index` | `long` | Developer diagnostic/control: obstacle path goal surface index. [source](../source/hs/hs_globals_external.c#L1562) | Host/local |
| `debug_obstacle_path_on_failure` | `boolean` | Developer diagnostic/control: obstacle path on failure. [source](../source/hs/hs_globals_external.c#L1550) | Host/local |
| `debug_obstacle_path_start_point_x` | `real` | Developer diagnostic/control: obstacle path start point x. [source](../source/hs/hs_globals_external.c#L1552) | Host/local |
| `debug_obstacle_path_start_point_y` | `real` | Developer diagnostic/control: obstacle path start point y. [source](../source/hs/hs_globals_external.c#L1554) | Host/local |
| `debug_obstacle_path_start_surface_index` | `long` | Developer diagnostic/control: obstacle path start surface index. [source](../source/hs/hs_globals_external.c#L1556) | Host/local |
| `debug_permanent_decals` | `boolean` | Developer diagnostic/control: permanent decals. [source](../source/hs/hs_globals_external.c#L1574) | Host/local |
| `debug_physics_disable_penetration_freeze` | `boolean` | Developer diagnostic/control: physics disable penetration freeze. [source](../source/hs/hs_globals_external.c#L1474) | Host/local |
| `debug_point_physics` | `boolean` | Developer diagnostic/control: point physics. [source](../source/hs/hs_globals_external.c#L1472) | Host/local |
| `debug_render_freeze` | `boolean` | Developer diagnostic/control: render freeze. [source](../source/hs/hs_globals_external.c#L1300) | Host/local |
| `debug_scripting` | `boolean` | Developer diagnostic/control: scripting. [source](../source/hs/hs_globals_external.c#L1468) | Host/local |
| `debug_sprites` | `boolean` | Developer diagnostic/control: sprites. [source](../source/hs/hs_globals_external.c#L1412) | Host/local |
| `debug_texture_cache` | `boolean` | Developer diagnostic/control: texture cache. [source](../source/hs/hs_globals_external.c#L1294) | Host/local |
| `debug_trigger_volumes` | `boolean` | Developer diagnostic/control: trigger volumes. [source](../source/hs/hs_globals_external.c#L1470) | Host/local |
| `display_framerate` | `boolean` | Show the FPS counter, averaged over about half a second. [source](../source/hs/hs_globals_external.c#L1074) | Guest |
| `display_precache_progress` | `boolean` | Legacy control/diagnostic for display precache progress. [source](../source/hs/hs_globals_external.c#L1078) | Host/local |
| `display_vblank_deltas` | `boolean` | Legacy control/diagnostic for display vblank deltas. [source](../source/hs/hs_globals_external.c#L1076) | Host/local |
| `find_all_fucked_up_shit` | `boolean` | Legacy internal diagnostic switch; no supported player-facing contract. [source](../source/hs/hs_globals_external.c#L1938) | Host/local |
| `framerate_lock` | `boolean` | Legacy fixed-frame-update control; not an ordinary display FPS setting. [source](../source/hs/hs_globals_external.c#L1070) | Guest |
| `framerate_throttle` | `boolean` | Legacy frame-throttle control; use native Video/config settings for presentation preferences. [source](../source/hs/hs_globals_external.c#L1068) | Guest |
| `freeze_flying_camera` | `short` | Legacy control/diagnostic for freeze flying camera. [source](../source/hs/hs_globals_external.c#L1244) | Host/local |
| `global_connection_dont_timeout` | `boolean` | Legacy connection-timeout override; internal diagnostic control. [source](../source/hs/hs_globals_external.c#L1942) | Host/local |
| `profile_display` | `boolean` | Profiling display/control: display. [source](../source/hs/hs_globals_external.c#L1382) | Host/local |
| `profile_dump_frames` | `boolean` | Profiling display/control: dump frames. [source](../source/hs/hs_globals_external.c#L1386) | Host/local |
| `profile_dump_lost_frames` | `boolean` | Profiling display/control: dump lost frames. [source](../source/hs/hs_globals_external.c#L1388) | Host/local |
| `profile_graph` | `boolean` | Profiling display/control: graph. [source](../source/hs/hs_globals_external.c#L1380) | Host/local |
| `profile_timebase_ticks` | `boolean` | Profiling display/control: timebase ticks. [source](../source/hs/hs_globals_external.c#L1384) | Host/local |
| `recover_saved_games_hack` | `boolean` | Legacy control/diagnostic for recover saved games hack. [source](../source/hs/hs_globals_external.c#L1280) | Host/local |
| `run_game_scripts` | `boolean` | **Inert compatibility name:** no backing engine storage; reads type default and ignores writes. [source](../source/hs/hs_globals_external.c#L1944) | Host/local |
| `screenshot_count` | `short` | Legacy control/diagnostic for screenshot count. [source](../source/hs/hs_globals_external.c#L1064) | Guest |
| `screenshot_size` | `short` | Legacy control/diagnostic for screenshot size. [source](../source/hs/hs_globals_external.c#L1062) | Guest |
| `temporary_hud` | `boolean` | Legacy control/diagnostic for temporary hud. [source](../source/hs/hs_globals_external.c#L1296) | Host/local |
| `terminal_render` | `boolean` | Enable terminal/console text rendering. [source](../source/hs/hs_globals_external.c#L1082) | Guest |
| `weather` | `boolean` | Legacy control/diagnostic for weather. [source](../source/hs/hs_globals_external.c#L1602) | Host/local |

### Player, input, units and cheats

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `cheat_bottomless_clip` | `boolean` | Prevent loaded magazines from draining. [source](../source/hs/hs_globals_external.c#L1326) | Host/local |
| `cheat_bump_possession` | `boolean` | Legacy gameplay cheat: bump possession; exact behavior is implementation-specific. [source](../source/hs/hs_globals_external.c#L1328) | Host/local |
| `cheat_controller` | `boolean` | Legacy gameplay cheat: controller; exact behavior is implementation-specific. [source](../source/hs/hs_globals_external.c#L1338) | Host/local |
| `cheat_deathless_player` | `boolean` | Prevent normal player death from damage. [source](../source/hs/hs_globals_external.c#L1320) | Host/local |
| `cheat_infinite_ammo` | `boolean` | Prevent reserve-ammo and player-grenade consumption. [source](../source/hs/hs_globals_external.c#L1324) | Host/local |
| `cheat_jetpack` | `boolean` | Legacy gameplay cheat: jetpack; exact behavior is implementation-specific. [source](../source/hs/hs_globals_external.c#L1322) | Host/local |
| `cheat_medusa` | `boolean` | Legacy gameplay cheat: medusa; exact behavior is implementation-specific. [source](../source/hs/hs_globals_external.c#L1334) | Host/local |
| `cheat_omnipotent` | `boolean` | Legacy gameplay cheat: omnipotent; exact behavior is implementation-specific. [source](../source/hs/hs_globals_external.c#L1336) | Host/local |
| `cheat_reflexive_damage_effects` | `boolean` | Legacy gameplay cheat: reflexive damage effects; exact behavior is implementation-specific. [source](../source/hs/hs_globals_external.c#L1332) | Host/local |
| `cheat_super_jump` | `boolean` | Increase player jump. [source](../source/hs/hs_globals_external.c#L1330) | Host/local |
| `controls_enable_crouch` | `boolean` | Enable player crouching. [source](../source/hs/hs_globals_external.c#L1896) | Guest |
| `controls_enable_doubled_spin` | `boolean` | Legacy control/diagnostic for controls enable doubled spin. [source](../source/hs/hs_globals_external.c#L1900) | Guest |
| `controls_swap_doubled_spin_state` | `boolean` | Legacy control/diagnostic for controls swap doubled spin state. [source](../source/hs/hs_globals_external.c#L1902) | Guest |
| `controls_swapped` | `boolean` | Legacy control/diagnostic for controls swapped. [source](../source/hs/hs_globals_external.c#L1898) | Guest |
| `debug_biped_limp_body_disable` | `boolean` | Developer diagnostic/control: biped limp body disable. [source](../source/hs/hs_globals_external.c#L1594) | Host/local |
| `debug_biped_physics` | `boolean` | Developer diagnostic/control: biped physics. [source](../source/hs/hs_globals_external.c#L1588) | Host/local |
| `debug_biped_skip_collision` | `boolean` | Developer diagnostic/control: biped skip collision. [source](../source/hs/hs_globals_external.c#L1592) | Host/local |
| `debug_biped_skip_update` | `boolean` | Developer diagnostic/control: biped skip update. [source](../source/hs/hs_globals_external.c#L1590) | Host/local |
| `debug_player` | `boolean` | Developer diagnostic/control: player. [source](../source/hs/hs_globals_external.c#L1566) | Host/local |
| `debug_player_color` | `short` | Developer diagnostic/control: player color. [source](../source/hs/hs_globals_external.c#L1936) | Host/local |
| `debug_player_teleport` | `boolean` | Developer diagnostic/control: player teleport. [source](../source/hs/hs_globals_external.c#L1924) | Host/local |
| `debug_unit_all_animations` | `boolean` | Developer diagnostic/control: unit all animations. [source](../source/hs/hs_globals_external.c#L1312) | Host/local |
| `debug_unit_animations` | `boolean` | Developer diagnostic/control: unit animations. [source](../source/hs/hs_globals_external.c#L1314) | Host/local |
| `debug_unit_illumination` | `boolean` | Developer diagnostic/control: unit illumination. [source](../source/hs/hs_globals_external.c#L1316) | Host/local |
| `player0_look_pitch_rate` | `real` | Local split-screen player 0 look vertical (pitch) rate. [source](../source/hs/hs_globals_external.c#L1912) | Guest |
| `player0_look_yaw_rate` | `real` | Local split-screen player 0 look horizontal (yaw) rate. [source](../source/hs/hs_globals_external.c#L1904) | Guest |
| `player1_look_pitch_rate` | `real` | Local split-screen player 1 look vertical (pitch) rate. [source](../source/hs/hs_globals_external.c#L1914) | Guest |
| `player1_look_yaw_rate` | `real` | Local split-screen player 1 look horizontal (yaw) rate. [source](../source/hs/hs_globals_external.c#L1906) | Guest |
| `player2_look_pitch_rate` | `real` | Local split-screen player 2 look vertical (pitch) rate. [source](../source/hs/hs_globals_external.c#L1916) | Guest |
| `player2_look_yaw_rate` | `real` | Local split-screen player 2 look horizontal (yaw) rate. [source](../source/hs/hs_globals_external.c#L1908) | Guest |
| `player3_look_pitch_rate` | `real` | Local split-screen player 3 look vertical (pitch) rate. [source](../source/hs/hs_globals_external.c#L1918) | Guest |
| `player3_look_yaw_rate` | `real` | Local split-screen player 3 look horizontal (yaw) rate. [source](../source/hs/hs_globals_external.c#L1910) | Guest |
| `player_autoaim` | `boolean` | Player autoaim control; distinct from magnetism. [source](../source/hs/hs_globals_external.c#L1920) | Host/local |
| `player_magnetism` | `boolean` | Player magnetism control; distinct from autoaim. [source](../source/hs/hs_globals_external.c#L1922) | Host/local |
| `player_spawn_count` | `short` | Developer player-spawn count control. [source](../source/hs/hs_globals_external.c#L1066) | Host/local |
| `rider_ejection` | `boolean` | Legacy control/diagnostic for rider ejection. [source](../source/hs/hs_globals_external.c#L1366) | Host/local |
| `stun_enable` | `boolean` | Legacy control/diagnostic for stun enable. [source](../source/hs/hs_globals_external.c#L1368) | Host/local |

### Objects, models, animation and camera

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `debug_object_garbage_collection` | `boolean` | Developer diagnostic/control: object garbage collection. [source](../source/hs/hs_globals_external.c#L1298) | Host/local |
| `debug_object_lights` | `boolean` | Developer diagnostic/control: object lights. [source](../source/hs/hs_globals_external.c#L1584) | Host/local |
| `debug_objects` | `boolean` | Developer diagnostic/control: objects. [source](../source/hs/hs_globals_external.c#L1424) | Host/local |
| `debug_objects_biped_autoaim_pills` | `boolean` | Developer diagnostic/control: objects biped autoaim pills. [source](../source/hs/hs_globals_external.c#L1448) | Host/local |
| `debug_objects_biped_physics_pills` | `boolean` | Developer diagnostic/control: objects biped physics pills. [source](../source/hs/hs_globals_external.c#L1446) | Host/local |
| `debug_objects_bounding_spheres` | `boolean` | Developer diagnostic/control: objects bounding spheres. [source](../source/hs/hs_globals_external.c#L1430) | Host/local |
| `debug_objects_collision_models` | `boolean` | Developer diagnostic/control: objects collision models. [source](../source/hs/hs_globals_external.c#L1432) | Host/local |
| `debug_objects_devices` | `boolean` | Developer diagnostic/control: objects devices. [source](../source/hs/hs_globals_external.c#L1452) | Host/local |
| `debug_objects_names` | `boolean` | Developer diagnostic/control: objects names. [source](../source/hs/hs_globals_external.c#L1436) | Host/local |
| `debug_objects_pathfinding_spheres` | `boolean` | Developer diagnostic/control: objects pathfinding spheres. [source](../source/hs/hs_globals_external.c#L1438) | Host/local |
| `debug_objects_physics` | `boolean` | Developer diagnostic/control: objects physics. [source](../source/hs/hs_globals_external.c#L1434) | Host/local |
| `debug_objects_position_velocity` | `boolean` | Developer diagnostic/control: objects position velocity. [source](../source/hs/hs_globals_external.c#L1426) | Host/local |
| `debug_objects_root_node` | `boolean` | Developer diagnostic/control: objects root node. [source](../source/hs/hs_globals_external.c#L1428) | Host/local |
| `debug_objects_unit_mouth_apeture` | `boolean` | Developer diagnostic/control: objects unit mouth apeture. [source](../source/hs/hs_globals_external.c#L1444) | Host/local |
| `debug_objects_unit_seats` | `boolean` | Developer diagnostic/control: objects unit seats. [source](../source/hs/hs_globals_external.c#L1442) | Host/local |
| `debug_objects_unit_vectors` | `boolean` | Developer diagnostic/control: objects unit vectors. [source](../source/hs/hs_globals_external.c#L1440) | Host/local |
| `debug_objects_vehicle_powered_mass_points` | `boolean` | Developer diagnostic/control: objects vehicle powered mass points. [source](../source/hs/hs_globals_external.c#L1450) | Host/local |
| `debug_recording` | `boolean` | Developer diagnostic/control: recording. [source](../source/hs/hs_globals_external.c#L1932) | Host/local |
| `debug_recording_newlines` | `short` | Developer diagnostic/control: recording newlines. [source](../source/hs/hs_globals_external.c#L1934) | Host/local |
| `director_camera_switch_fast` | `boolean` | Legacy control/diagnostic for director camera switch fast. [source](../source/hs/hs_globals_external.c#L1930) | Host/local |
| `model_animation_bullshit0` | `long` | Legacy control/diagnostic for model animation bullshit0. [source](../source/hs/hs_globals_external.c#L1402) | Host/local |
| `model_animation_bullshit1` | `long` | Legacy control/diagnostic for model animation bullshit1. [source](../source/hs/hs_globals_external.c#L1404) | Host/local |
| `model_animation_bullshit2` | `long` | Legacy control/diagnostic for model animation bullshit2. [source](../source/hs/hs_globals_external.c#L1406) | Host/local |
| `model_animation_bullshit3` | `long` | Legacy control/diagnostic for model animation bullshit3. [source](../source/hs/hs_globals_external.c#L1408) | Host/local |
| `model_animation_compression` | `boolean` | Legacy control/diagnostic for model animation compression. [source](../source/hs/hs_globals_external.c#L1390) | Host/local |
| `model_animation_data_compressed_size` | `long` | Legacy control/diagnostic for model animation data compressed size. [source](../source/hs/hs_globals_external.c#L1392) | Host/local |
| `model_animation_data_compression_savings_in_bytes` | `long` | Legacy control/diagnostic for model animation data compression savings in bytes. [source](../source/hs/hs_globals_external.c#L1396) | Host/local |
| `model_animation_data_compression_savings_in_bytes_at_import` | `long` | Legacy control/diagnostic for model animation data compression savings in bytes at import. [source](../source/hs/hs_globals_external.c#L1398) | Host/local |
| `model_animation_data_compression_savings_in_percent` | `real` | Legacy control/diagnostic for model animation data compression savings in percent. [source](../source/hs/hs_globals_external.c#L1400) | Host/local |
| `model_animation_data_uncompressed_size` | `long` | Legacy control/diagnostic for model animation data uncompressed size. [source](../source/hs/hs_globals_external.c#L1394) | Host/local |
| `object_light_ambient_base` | `real` | Legacy control/diagnostic for object light ambient base. [source](../source/hs/hs_globals_external.c#L1358) | Host/local |
| `object_light_ambient_scale` | `real` | Legacy control/diagnostic for object light ambient scale. [source](../source/hs/hs_globals_external.c#L1360) | Host/local |
| `object_light_interpolate` | `boolean` | Legacy control/diagnostic for object light interpolate. [source](../source/hs/hs_globals_external.c#L1364) | Host/local |
| `object_light_secondary_scale` | `real` | Legacy control/diagnostic for object light secondary scale. [source](../source/hs/hs_globals_external.c#L1362) | Host/local |

### World rendering, effects and visibility

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `breakable_surfaces` | `boolean` | Legacy control/diagnostic for breakable surfaces. [source](../source/hs/hs_globals_external.c#L1494) | Host/local |
| `debug_decals` | `boolean` | Developer diagnostic/control: decals. [source](../source/hs/hs_globals_external.c#L1582) | Host/local |
| `debug_effects_nonviolent` | `boolean` | Developer diagnostic/control: effects nonviolent. [source](../source/hs/hs_globals_external.c#L1342) | Host/local |
| `debug_portals` | `boolean` | Developer diagnostic/control: portals. [source](../source/hs/hs_globals_external.c#L1410) | Host/local |
| `debug_structure` | `boolean` | Developer diagnostic/control: structure. [source](../source/hs/hs_globals_external.c#L1568) | Host/local |
| `decals` | `boolean` | Decal rendering control (two registry slots share this name). [source](../source/hs/hs_globals_external.c#L1148) | Host/local |
| `effects_corpse_nonviolent` | `boolean` | Legacy control/diagnostic for effects corpse nonviolent. [source](../source/hs/hs_globals_external.c#L1340) | Host/local |
| `render_contrails` | `boolean` | World diagnostic rendering/control: contrails. [source](../source/hs/hs_globals_external.c#L1416) | Host/local |
| `render_model_index_counts` | `boolean` | World diagnostic rendering/control: model index counts. [source](../source/hs/hs_globals_external.c#L1458) | Host/local |
| `render_model_markers` | `boolean` | World diagnostic rendering/control: model markers. [source](../source/hs/hs_globals_external.c#L1460) | Host/local |
| `render_model_no_geometry` | `boolean` | World diagnostic rendering/control: model no geometry. [source](../source/hs/hs_globals_external.c#L1462) | Host/local |
| `render_model_nodes` | `boolean` | World diagnostic rendering/control: model nodes. [source](../source/hs/hs_globals_external.c#L1454) | Host/local |
| `render_model_vertex_counts` | `boolean` | World diagnostic rendering/control: model vertex counts. [source](../source/hs/hs_globals_external.c#L1456) | Host/local |
| `render_particles` | `boolean` | World diagnostic rendering/control: particles. [source](../source/hs/hs_globals_external.c#L1418) | Host/local |
| `render_psystems` | `boolean` | World diagnostic rendering/control: psystems. [source](../source/hs/hs_globals_external.c#L1420) | Host/local |
| `render_shadows` | `boolean` | World diagnostic rendering/control: shadows. [source](../source/hs/hs_globals_external.c#L1464) | Host/local |
| `render_wsystems` | `boolean` | World diagnostic rendering/control: wsystems. [source](../source/hs/hs_globals_external.c#L1422) | Host/local |
| `structures_use_pvs_for_vs` | `boolean` | Legacy control/diagnostic for structures use pvs for vs. [source](../source/hs/hs_globals_external.c#L1290) | Host/local |

### Sound diagnostics and tuning

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `debug_sound` | `boolean` | Developer diagnostic/control: sound. [source](../source/hs/hs_globals_external.c#L1346) | Host/local |
| `debug_sound_cache` | `boolean` | Developer diagnostic/control: sound cache. [source](../source/hs/hs_globals_external.c#L1344) | Host/local |
| `debug_sound_channels` | `boolean` | Developer diagnostic/control: sound channels. [source](../source/hs/hs_globals_external.c#L1350) | Host/local |
| `debug_sound_environment` | `boolean` | Developer diagnostic/control: sound environment. [source](../source/hs/hs_globals_external.c#L1356) | Host/local |
| `loud_dialog_hack` | `boolean` | Legacy control/diagnostic for loud dialog hack. [source](../source/hs/hs_globals_external.c#L1352) | Host/local |
| `sound_gain_under_dialog` | `real` | Legacy control/diagnostic for sound gain under dialog. [source](../source/hs/hs_globals_external.c#L1354) | Host/local |

### Collision diagnostics

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `collision_debug` | `boolean` | Collision diagnostic/control: debug. [source](../source/hs/hs_globals_external.c#L1478) | Host/local |
| `collision_debug_features` | `boolean` | Collision diagnostic/control: debug features. [source](../source/hs/hs_globals_external.c#L1482) | Host/local |
| `collision_debug_flag_back_facing_surfaces` | `boolean` | Collision diagnostic/control: debug flag back facing surfaces. [source](../source/hs/hs_globals_external.c#L1488) | Host/local |
| `collision_debug_flag_front_facing_surfaces` | `boolean` | Collision diagnostic/control: debug flag front facing surfaces. [source](../source/hs/hs_globals_external.c#L1486) | Host/local |
| `collision_debug_flag_ignore_breakable_surfaces` | `boolean` | Collision diagnostic/control: debug flag ignore breakable surfaces. [source](../source/hs/hs_globals_external.c#L1494) | Host/local |
| `collision_debug_flag_ignore_invisible_surfaces` | `boolean` | Collision diagnostic/control: debug flag ignore invisible surfaces. [source](../source/hs/hs_globals_external.c#L1492) | Host/local |
| `collision_debug_flag_ignore_two_sided_surfaces` | `boolean` | Collision diagnostic/control: debug flag ignore two sided surfaces. [source](../source/hs/hs_globals_external.c#L1490) | Host/local |
| `collision_debug_flag_media` | `boolean` | Collision diagnostic/control: debug flag media. [source](../source/hs/hs_globals_external.c#L1498) | Host/local |
| `collision_debug_flag_objects` | `boolean` | Collision diagnostic/control: debug flag objects. [source](../source/hs/hs_globals_external.c#L1500) | Host/local |
| `collision_debug_flag_objects_bipeds` | `boolean` | Collision diagnostic/control: debug flag objects bipeds. [source](../source/hs/hs_globals_external.c#L1502) | Host/local |
| `collision_debug_flag_objects_controls` | `boolean` | Collision diagnostic/control: debug flag objects controls. [source](../source/hs/hs_globals_external.c#L1516) | Host/local |
| `collision_debug_flag_objects_equipment` | `boolean` | Collision diagnostic/control: debug flag objects equipment. [source](../source/hs/hs_globals_external.c#L1508) | Host/local |
| `collision_debug_flag_objects_light_fixtures` | `boolean` | Collision diagnostic/control: debug flag objects light fixtures. [source](../source/hs/hs_globals_external.c#L1518) | Host/local |
| `collision_debug_flag_objects_machines` | `boolean` | Collision diagnostic/control: debug flag objects machines. [source](../source/hs/hs_globals_external.c#L1514) | Host/local |
| `collision_debug_flag_objects_placeholders` | `boolean` | Collision diagnostic/control: debug flag objects placeholders. [source](../source/hs/hs_globals_external.c#L1520) | Host/local |
| `collision_debug_flag_objects_projectiles` | `boolean` | Collision diagnostic/control: debug flag objects projectiles. [source](../source/hs/hs_globals_external.c#L1510) | Host/local |
| `collision_debug_flag_objects_scenery` | `boolean` | Collision diagnostic/control: debug flag objects scenery. [source](../source/hs/hs_globals_external.c#L1512) | Host/local |
| `collision_debug_flag_objects_vehicles` | `boolean` | Collision diagnostic/control: debug flag objects vehicles. [source](../source/hs/hs_globals_external.c#L1504) | Host/local |
| `collision_debug_flag_objects_weapons` | `boolean` | Collision diagnostic/control: debug flag objects weapons. [source](../source/hs/hs_globals_external.c#L1506) | Host/local |
| `collision_debug_flag_skip_passthrough_bipeds` | `boolean` | Collision diagnostic/control: debug flag skip passthrough bipeds. [source](../source/hs/hs_globals_external.c#L1524) | Host/local |
| `collision_debug_flag_structure` | `boolean` | Collision diagnostic/control: debug flag structure. [source](../source/hs/hs_globals_external.c#L1496) | Host/local |
| `collision_debug_flag_try_to_keep_location_valid` | `boolean` | Collision diagnostic/control: debug flag try to keep location valid. [source](../source/hs/hs_globals_external.c#L1522) | Host/local |
| `collision_debug_flag_use_vehicle_physics` | `boolean` | Collision diagnostic/control: debug flag use vehicle physics. [source](../source/hs/hs_globals_external.c#L1526) | Host/local |
| `collision_debug_height` | `real` | Collision diagnostic/control: debug height. [source](../source/hs/hs_globals_external.c#L1544) | Host/local |
| `collision_debug_length` | `real` | Collision diagnostic/control: debug length. [source](../source/hs/hs_globals_external.c#L1540) | Host/local |
| `collision_debug_phantom_bsp` | `boolean` | Collision diagnostic/control: debug phantom bsp. [source](../source/hs/hs_globals_external.c#L1546) | Host/local |
| `collision_debug_point_x` | `real` | Collision diagnostic/control: debug point x. [source](../source/hs/hs_globals_external.c#L1528) | Host/local |
| `collision_debug_point_y` | `real` | Collision diagnostic/control: debug point y. [source](../source/hs/hs_globals_external.c#L1530) | Host/local |
| `collision_debug_point_z` | `real` | Collision diagnostic/control: debug point z. [source](../source/hs/hs_globals_external.c#L1532) | Host/local |
| `collision_debug_repeat` | `boolean` | Collision diagnostic/control: debug repeat. [source](../source/hs/hs_globals_external.c#L1484) | Host/local |
| `collision_debug_spray` | `boolean` | Collision diagnostic/control: debug spray. [source](../source/hs/hs_globals_external.c#L1480) | Host/local |
| `collision_debug_vector_i` | `real` | Collision diagnostic/control: debug vector i. [source](../source/hs/hs_globals_external.c#L1534) | Host/local |
| `collision_debug_vector_j` | `real` | Collision diagnostic/control: debug vector j. [source](../source/hs/hs_globals_external.c#L1536) | Host/local |
| `collision_debug_vector_k` | `real` | Collision diagnostic/control: debug vector k. [source](../source/hs/hs_globals_external.c#L1538) | Host/local |
| `collision_debug_width` | `real` | Collision diagnostic/control: debug width. [source](../source/hs/hs_globals_external.c#L1542) | Host/local |
| `collision_log_detailed` | `boolean` | Collision diagnostic/control: log detailed. [source](../source/hs/hs_globals_external.c#L1372) | Host/local |
| `collision_log_extended` | `boolean` | Collision diagnostic/control: log extended. [source](../source/hs/hs_globals_external.c#L1374) | Host/local |
| `collision_log_render` | `boolean` | Collision diagnostic/control: log render. [source](../source/hs/hs_globals_external.c#L1370) | Host/local |
| `collision_log_time` | `boolean` | Collision diagnostic/control: log time. [source](../source/hs/hs_globals_external.c#L1378) | Host/local |
| `collision_log_totals_only` | `boolean` | Collision diagnostic/control: log totals only. [source](../source/hs/hs_globals_external.c#L1376) | Host/local |

### AI tuning and diagnostics

| Variable | Type | Purpose label | Access |
| --- | --- | --- | --- |
| `ai_debug_ballistic_lineoffire_freeze` | `boolean` | AI diagnostic display/control: debug ballistic lineoffire freeze. [source](../source/hs/hs_globals_external.c#L1860) | Host/local |
| `ai_debug_blind` | `boolean` | AI diagnostic display/control: debug blind. [source](../source/hs/hs_globals_external.c#L1870) | Host/local |
| `ai_debug_communication_focus_enable` | `boolean` | AI diagnostic display/control: debug communication focus enable. [source](../source/hs/hs_globals_external.c#L1868) | Host/local |
| `ai_debug_communication_random_disabled` | `boolean` | AI diagnostic display/control: debug communication random disabled. [source](../source/hs/hs_globals_external.c#L1862) | Host/local |
| `ai_debug_communication_timeout_disabled` | `boolean` | AI diagnostic display/control: debug communication timeout disabled. [source](../source/hs/hs_globals_external.c#L1864) | Host/local |
| `ai_debug_communication_unit_repeat_disabled` | `boolean` | AI diagnostic display/control: debug communication unit repeat disabled. [source](../source/hs/hs_globals_external.c#L1866) | Host/local |
| `ai_debug_deaf` | `boolean` | AI diagnostic display/control: debug deaf. [source](../source/hs/hs_globals_external.c#L1872) | Host/local |
| `ai_debug_disable_wounded_sounds` | `boolean` | AI diagnostic display/control: debug disable wounded sounds. [source](../source/hs/hs_globals_external.c#L1882) | Host/local |
| `ai_debug_evaluate_all_positions` | `boolean` | AI diagnostic display/control: debug evaluate all positions. [source](../source/hs/hs_globals_external.c#L1840) | Host/local |
| `ai_debug_fast_los` | `boolean` | AI diagnostic display/control: debug fast los. [source](../source/hs/hs_globals_external.c#L1836) | Host/local |
| `ai_debug_flee_always` | `boolean` | AI diagnostic display/control: debug flee always. [source](../source/hs/hs_globals_external.c#L1878) | Host/local |
| `ai_debug_force_all_active` | `boolean` | AI diagnostic display/control: debug force all active. [source](../source/hs/hs_globals_external.c#L1880) | Host/local |
| `ai_debug_force_crouch` | `boolean` | AI diagnostic display/control: debug force crouch. [source](../source/hs/hs_globals_external.c#L1886) | Host/local |
| `ai_debug_force_vocalizations` | `boolean` | AI diagnostic display/control: debug force vocalizations. [source](../source/hs/hs_globals_external.c#L1884) | Host/local |
| `ai_debug_ignore_player` | `boolean` | AI diagnostic display/control: debug ignore player. [source](../source/hs/hs_globals_external.c#L1876) | Host/local |
| `ai_debug_invisible_player` | `boolean` | AI diagnostic display/control: debug invisible player. [source](../source/hs/hs_globals_external.c#L1874) | Host/local |
| `ai_debug_oversteer_disable` | `boolean` | AI diagnostic display/control: debug oversteer disable. [source](../source/hs/hs_globals_external.c#L1838) | Host/local |
| `ai_debug_path` | `boolean` | AI diagnostic display/control: debug path. [source](../source/hs/hs_globals_external.c#L1842) | Host/local |
| `ai_debug_path_accept_radius` | `real` | AI diagnostic display/control: debug path accept radius. [source](../source/hs/hs_globals_external.c#L1858) | Host/local |
| `ai_debug_path_attractor` | `boolean` | AI diagnostic display/control: debug path attractor. [source](../source/hs/hs_globals_external.c#L1852) | Host/local |
| `ai_debug_path_attractor_radius` | `real` | AI diagnostic display/control: debug path attractor radius. [source](../source/hs/hs_globals_external.c#L1854) | Host/local |
| `ai_debug_path_attractor_weight` | `real` | AI diagnostic display/control: debug path attractor weight. [source](../source/hs/hs_globals_external.c#L1856) | Host/local |
| `ai_debug_path_disable_obstacle_avoidance` | `boolean` | AI diagnostic display/control: debug path disable obstacle avoidance. [source](../source/hs/hs_globals_external.c#L1890) | Host/local |
| `ai_debug_path_disable_smoothing` | `boolean` | AI diagnostic display/control: debug path disable smoothing. [source](../source/hs/hs_globals_external.c#L1888) | Host/local |
| `ai_debug_path_end_freeze` | `boolean` | AI diagnostic display/control: debug path end freeze. [source](../source/hs/hs_globals_external.c#L1846) | Host/local |
| `ai_debug_path_flood` | `boolean` | AI diagnostic display/control: debug path flood. [source](../source/hs/hs_globals_external.c#L1848) | Host/local |
| `ai_debug_path_maximum_radius` | `real` | AI diagnostic display/control: debug path maximum radius. [source](../source/hs/hs_globals_external.c#L1850) | Host/local |
| `ai_debug_path_start_freeze` | `boolean` | AI diagnostic display/control: debug path start freeze. [source](../source/hs/hs_globals_external.c#L1844) | Host/local |
| `ai_fix_actor_variants` | `boolean` | AI tuning/control: fix actor variants. [source](../source/hs/hs_globals_external.c#L1894) | Host/local |
| `ai_fix_defending_guard_firing_positions` | `boolean` | AI tuning/control: fix defending guard firing positions. [source](../source/hs/hs_globals_external.c#L1892) | Host/local |
| `ai_print_acknowledgement` | `boolean` | AI tuning/control: print acknowledgement. [source](../source/hs/hs_globals_external.c#L1828) | Host/local |
| `ai_print_allegiance` | `boolean` | AI tuning/control: print allegiance. [source](../source/hs/hs_globals_external.c#L1804) | Host/local |
| `ai_print_automatic_migration` | `boolean` | AI tuning/control: print automatic migration. [source](../source/hs/hs_globals_external.c#L1810) | Host/local |
| `ai_print_bsp_transition` | `boolean` | AI tuning/control: print bsp transition. [source](../source/hs/hs_globals_external.c#L1832) | Host/local |
| `ai_print_command_lists` | `boolean` | AI tuning/control: print command lists. [source](../source/hs/hs_globals_external.c#L1816) | Host/local |
| `ai_print_communication` | `boolean` | AI tuning/control: print communication. [source](../source/hs/hs_globals_external.c#L1792) | Host/local |
| `ai_print_communication_player` | `boolean` | AI tuning/control: print communication player. [source](../source/hs/hs_globals_external.c#L1794) | Host/local |
| `ai_print_conversations` | `boolean` | AI tuning/control: print conversations. [source](../source/hs/hs_globals_external.c#L1824) | Host/local |
| `ai_print_damage_modifiers` | `boolean` | AI tuning/control: print damage modifiers. [source](../source/hs/hs_globals_external.c#L1818) | Host/local |
| `ai_print_evaluation_statistics` | `boolean` | AI tuning/control: print evaluation statistics. [source](../source/hs/hs_globals_external.c#L1790) | Host/local |
| `ai_print_killing_sprees` | `boolean` | AI tuning/control: print killing sprees. [source](../source/hs/hs_globals_external.c#L1826) | Host/local |
| `ai_print_lost_speech` | `boolean` | AI tuning/control: print lost speech. [source](../source/hs/hs_globals_external.c#L1806) | Host/local |
| `ai_print_major_upgrade` | `boolean` | AI tuning/control: print major upgrade. [source](../source/hs/hs_globals_external.c#L1786) | Host/local |
| `ai_print_migration` | `boolean` | AI tuning/control: print migration. [source](../source/hs/hs_globals_external.c#L1808) | Host/local |
| `ai_print_oversteer` | `boolean` | AI tuning/control: print oversteer. [source](../source/hs/hs_globals_external.c#L1822) | Host/local |
| `ai_print_placement` | `boolean` | AI tuning/control: print placement. [source](../source/hs/hs_globals_external.c#L1798) | Host/local |
| `ai_print_pursuit_checks` | `boolean` | AI tuning/control: print pursuit checks. [source](../source/hs/hs_globals_external.c#L1780) | Host/local |
| `ai_print_respawn` | `boolean` | AI tuning/control: print respawn. [source](../source/hs/hs_globals_external.c#L1788) | Host/local |
| `ai_print_rule_values` | `boolean` | AI tuning/control: print rule values. [source](../source/hs/hs_globals_external.c#L1784) | Host/local |
| `ai_print_rules` | `boolean` | AI tuning/control: print rules. [source](../source/hs/hs_globals_external.c#L1782) | Host/local |
| `ai_print_scripting` | `boolean` | AI tuning/control: print scripting. [source](../source/hs/hs_globals_external.c#L1812) | Host/local |
| `ai_print_secondary_looking` | `boolean` | AI tuning/control: print secondary looking. [source](../source/hs/hs_globals_external.c#L1820) | Host/local |
| `ai_print_speech` | `boolean` | AI tuning/control: print speech. [source](../source/hs/hs_globals_external.c#L1800) | Host/local |
| `ai_print_speech_timers` | `boolean` | AI tuning/control: print speech timers. [source](../source/hs/hs_globals_external.c#L1802) | Host/local |
| `ai_print_surprise` | `boolean` | AI tuning/control: print surprise. [source](../source/hs/hs_globals_external.c#L1814) | Host/local |
| `ai_print_uncovering` | `boolean` | AI tuning/control: print uncovering. [source](../source/hs/hs_globals_external.c#L1834) | Host/local |
| `ai_print_unfinished_paths` | `boolean` | AI tuning/control: print unfinished paths. [source](../source/hs/hs_globals_external.c#L1830) | Host/local |
| `ai_print_vocalizations` | `boolean` | AI tuning/control: print vocalizations. [source](../source/hs/hs_globals_external.c#L1796) | Host/local |
| `ai_profile_disable` | `boolean` | AI tuning/control: profile disable. [source](../source/hs/hs_globals_external.c#L1604) | Host/local |
| `ai_profile_random` | `boolean` | AI tuning/control: profile random. [source](../source/hs/hs_globals_external.c#L1606) | Host/local |
| `ai_render` | `boolean` | AI diagnostic display/control: render. [source](../source/hs/hs_globals_external.c#L1624) | Host/local |
| `ai_render_activation` | `boolean` | AI diagnostic display/control: render activation. [source](../source/hs/hs_globals_external.c#L1726) | Host/local |
| `ai_render_active_cover_seeking` | `boolean` | AI diagnostic display/control: render active cover seeking. [source](../source/hs/hs_globals_external.c#L1682) | Host/local |
| `ai_render_aiming_validity` | `boolean` | AI diagnostic display/control: render aiming validity. [source](../source/hs/hs_globals_external.c#L1694) | Host/local |
| `ai_render_aiming_vectors` | `boolean` | AI diagnostic display/control: render aiming vectors. [source](../source/hs/hs_globals_external.c#L1670) | Host/local |
| `ai_render_all_actors` | `boolean` | AI diagnostic display/control: render all actors. [source](../source/hs/hs_globals_external.c#L1626) | Host/local |
| `ai_render_audibility` | `boolean` | AI diagnostic display/control: render audibility. [source](../source/hs/hs_globals_external.c#L1668) | Host/local |
| `ai_render_ballistic_lineoffire` | `boolean` | AI diagnostic display/control: render ballistic lineoffire. [source](../source/hs/hs_globals_external.c#L1636) | Host/local |
| `ai_render_burst_geometry` | `boolean` | AI diagnostic display/control: render burst geometry. [source](../source/hs/hs_globals_external.c#L1708) | Host/local |
| `ai_render_charge_decisions` | `boolean` | AI diagnostic display/control: render charge decisions. [source](../source/hs/hs_globals_external.c#L1722) | Host/local |
| `ai_render_control` | `boolean` | AI diagnostic display/control: render control. [source](../source/hs/hs_globals_external.c#L1724) | Host/local |
| `ai_render_current_state` | `boolean` | AI diagnostic display/control: render current state. [source](../source/hs/hs_globals_external.c#L1642) | Host/local |
| `ai_render_danger_zones` | `boolean` | AI diagnostic display/control: render danger zones. [source](../source/hs/hs_globals_external.c#L1720) | Host/local |
| `ai_render_detailed_state` | `boolean` | AI diagnostic display/control: render detailed state. [source](../source/hs/hs_globals_external.c#L1644) | Host/local |
| `ai_render_dialogue_variants` | `boolean` | AI diagnostic display/control: render dialogue variants. [source](../source/hs/hs_globals_external.c#L1716) | Host/local |
| `ai_render_emotions` | `boolean` | AI diagnostic display/control: render emotions. [source](../source/hs/hs_globals_external.c#L1666) | Host/local |
| `ai_render_encounter_activeregion` | `boolean` | AI diagnostic display/control: render encounter activeregion. [source](../source/hs/hs_globals_external.c#L1638) | Host/local |
| `ai_render_evaluations` | `boolean` | AI diagnostic display/control: render evaluations. [source](../source/hs/hs_globals_external.c#L1684) | Host/local |
| `ai_render_firing_positions` | `boolean` | AI diagnostic display/control: render firing positions. [source](../source/hs/hs_globals_external.c#L1704) | Host/local |
| `ai_render_grenade_decisions` | `boolean` | AI diagnostic display/control: render grenade decisions. [source](../source/hs/hs_globals_external.c#L1718) | Host/local |
| `ai_render_gun_positions` | `boolean` | AI diagnostic display/control: render gun positions. [source](../source/hs/hs_globals_external.c#L1706) | Host/local |
| `ai_render_idle_look` | `boolean` | AI diagnostic display/control: render idle look. [source](../source/hs/hs_globals_external.c#L1658) | Host/local |
| `ai_render_inactive_actors` | `boolean` | AI diagnostic display/control: render inactive actors. [source](../source/hs/hs_globals_external.c#L1628) | Host/local |
| `ai_render_lineoffire` | `boolean` | AI diagnostic display/control: render lineoffire. [source](../source/hs/hs_globals_external.c#L1632) | Host/local |
| `ai_render_lineoffire_crouching` | `boolean` | AI diagnostic display/control: render lineoffire crouching. [source](../source/hs/hs_globals_external.c#L1630) | Host/local |
| `ai_render_lineofsight` | `boolean` | AI diagnostic display/control: render lineofsight. [source](../source/hs/hs_globals_external.c#L1634) | Host/local |
| `ai_render_melee_check` | `boolean` | AI diagnostic display/control: render melee check. [source](../source/hs/hs_globals_external.c#L1714) | Host/local |
| `ai_render_paths` | `boolean` | AI diagnostic display/control: render paths. [source](../source/hs/hs_globals_external.c#L1728) | Host/local |
| `ai_render_paths_avoidance_obstacles` | `boolean` | AI diagnostic display/control: render paths avoidance obstacles. [source](../source/hs/hs_globals_external.c#L1746) | Host/local |
| `ai_render_paths_avoidance_search` | `boolean` | AI diagnostic display/control: render paths avoidance search. [source](../source/hs/hs_globals_external.c#L1748) | Host/local |
| `ai_render_paths_avoidance_segment` | `short` | AI diagnostic display/control: render paths avoidance segment. [source](../source/hs/hs_globals_external.c#L1744) | Host/local |
| `ai_render_paths_avoided` | `boolean` | AI diagnostic display/control: render paths avoided. [source](../source/hs/hs_globals_external.c#L1742) | Host/local |
| `ai_render_paths_current` | `boolean` | AI diagnostic display/control: render paths current. [source](../source/hs/hs_globals_external.c#L1736) | Host/local |
| `ai_render_paths_destination` | `boolean` | AI diagnostic display/control: render paths destination. [source](../source/hs/hs_globals_external.c#L1732) | Host/local |
| `ai_render_paths_failed` | `boolean` | AI diagnostic display/control: render paths failed. [source](../source/hs/hs_globals_external.c#L1738) | Host/local |
| `ai_render_paths_nodes` | `boolean` | AI diagnostic display/control: render paths nodes. [source](../source/hs/hs_globals_external.c#L1750) | Host/local |
| `ai_render_paths_nodes_all` | `boolean` | AI diagnostic display/control: render paths nodes all. [source](../source/hs/hs_globals_external.c#L1752) | Host/local |
| `ai_render_paths_nodes_closest` | `boolean` | AI diagnostic display/control: render paths nodes closest. [source](../source/hs/hs_globals_external.c#L1758) | Host/local |
| `ai_render_paths_nodes_costs` | `boolean` | AI diagnostic display/control: render paths nodes costs. [source](../source/hs/hs_globals_external.c#L1756) | Host/local |
| `ai_render_paths_nodes_polygons` | `boolean` | AI diagnostic display/control: render paths nodes polygons. [source](../source/hs/hs_globals_external.c#L1754) | Host/local |
| `ai_render_paths_raw` | `boolean` | AI diagnostic display/control: render paths raw. [source](../source/hs/hs_globals_external.c#L1734) | Host/local |
| `ai_render_paths_selected_only` | `boolean` | AI diagnostic display/control: render paths selected only. [source](../source/hs/hs_globals_external.c#L1730) | Host/local |
| `ai_render_paths_smoothed` | `boolean` | AI diagnostic display/control: render paths smoothed. [source](../source/hs/hs_globals_external.c#L1740) | Host/local |
| `ai_render_player_aiming_blocked` | `boolean` | AI diagnostic display/control: render player aiming blocked. [source](../source/hs/hs_globals_external.c#L1760) | Host/local |
| `ai_render_player_ratings` | `boolean` | AI diagnostic display/control: render player ratings. [source](../source/hs/hs_globals_external.c#L1700) | Host/local |
| `ai_render_postcombat` | `boolean` | AI diagnostic display/control: render postcombat. [source](../source/hs/hs_globals_external.c#L1778) | Host/local |
| `ai_render_projectile_aiming` | `boolean` | AI diagnostic display/control: render projectile aiming. [source](../source/hs/hs_globals_external.c#L1692) | Host/local |
| `ai_render_props` | `boolean` | AI diagnostic display/control: render props. [source](../source/hs/hs_globals_external.c#L1646) | Host/local |
| `ai_render_props_no_friends` | `boolean` | AI diagnostic display/control: render props no friends. [source](../source/hs/hs_globals_external.c#L1650) | Host/local |
| `ai_render_props_target_weight` | `boolean` | AI diagnostic display/control: render props target weight. [source](../source/hs/hs_globals_external.c#L1656) | Host/local |
| `ai_render_props_unopposable` | `boolean` | AI diagnostic display/control: render props unopposable. [source](../source/hs/hs_globals_external.c#L1654) | Host/local |
| `ai_render_props_unreachable` | `boolean` | AI diagnostic display/control: render props unreachable. [source](../source/hs/hs_globals_external.c#L1652) | Host/local |
| `ai_render_props_web` | `boolean` | AI diagnostic display/control: render props web. [source](../source/hs/hs_globals_external.c#L1648) | Host/local |
| `ai_render_pursuit` | `boolean` | AI diagnostic display/control: render pursuit. [source](../source/hs/hs_globals_external.c#L1686) | Host/local |
| `ai_render_recent_damage` | `boolean` | AI diagnostic display/control: render recent damage. [source](../source/hs/hs_globals_external.c#L1662) | Host/local |
| `ai_render_secondary_looking` | `boolean` | AI diagnostic display/control: render secondary looking. [source](../source/hs/hs_globals_external.c#L1672) | Host/local |
| `ai_render_shooting` | `boolean` | AI diagnostic display/control: render shooting. [source](../source/hs/hs_globals_external.c#L1688) | Host/local |
| `ai_render_spatial_effects` | `boolean` | AI diagnostic display/control: render spatial effects. [source](../source/hs/hs_globals_external.c#L1702) | Host/local |
| `ai_render_speech` | `boolean` | AI diagnostic display/control: render speech. [source](../source/hs/hs_globals_external.c#L1696) | Host/local |
| `ai_render_states` | `boolean` | AI diagnostic display/control: render states. [source](../source/hs/hs_globals_external.c#L1678) | Host/local |
| `ai_render_support_surfaces` | `boolean` | AI diagnostic display/control: render support surfaces. [source](../source/hs/hs_globals_external.c#L1660) | Host/local |
| `ai_render_targets` | `boolean` | AI diagnostic display/control: render targets. [source](../source/hs/hs_globals_external.c#L1674) | Host/local |
| `ai_render_targets_last_visible` | `boolean` | AI diagnostic display/control: render targets last visible. [source](../source/hs/hs_globals_external.c#L1676) | Host/local |
| `ai_render_teams` | `boolean` | AI diagnostic display/control: render teams. [source](../source/hs/hs_globals_external.c#L1698) | Host/local |
| `ai_render_threats` | `boolean` | AI diagnostic display/control: render threats. [source](../source/hs/hs_globals_external.c#L1664) | Host/local |
| `ai_render_trigger` | `boolean` | AI diagnostic display/control: render trigger. [source](../source/hs/hs_globals_external.c#L1690) | Host/local |
| `ai_render_vector_avoidance` | `boolean` | AI diagnostic display/control: render vector avoidance. [source](../source/hs/hs_globals_external.c#L1762) | Host/local |
| `ai_render_vector_avoidance_avoid_t` | `boolean` | AI diagnostic display/control: render vector avoidance avoid t. [source](../source/hs/hs_globals_external.c#L1768) | Host/local |
| `ai_render_vector_avoidance_clear_time` | `boolean` | AI diagnostic display/control: render vector avoidance clear time. [source](../source/hs/hs_globals_external.c#L1770) | Host/local |
| `ai_render_vector_avoidance_intermediate` | `boolean` | AI diagnostic display/control: render vector avoidance intermediate. [source](../source/hs/hs_globals_external.c#L1776) | Host/local |
| `ai_render_vector_avoidance_objects` | `boolean` | AI diagnostic display/control: render vector avoidance objects. [source](../source/hs/hs_globals_external.c#L1774) | Host/local |
| `ai_render_vector_avoidance_rays` | `boolean` | AI diagnostic display/control: render vector avoidance rays. [source](../source/hs/hs_globals_external.c#L1764) | Host/local |
| `ai_render_vector_avoidance_sense_t` | `boolean` | AI diagnostic display/control: render vector avoidance sense t. [source](../source/hs/hs_globals_external.c#L1766) | Host/local |
| `ai_render_vector_avoidance_weights` | `boolean` | AI diagnostic display/control: render vector avoidance weights. [source](../source/hs/hs_globals_external.c#L1772) | Host/local |
| `ai_render_vehicle_avoidance` | `boolean` | AI diagnostic display/control: render vehicle avoidance. [source](../source/hs/hs_globals_external.c#L1710) | Host/local |
| `ai_render_vehicles_enterable` | `boolean` | AI diagnostic display/control: render vehicles enterable. [source](../source/hs/hs_globals_external.c#L1712) | Host/local |
| `ai_render_vision_cones` | `boolean` | AI diagnostic display/control: render vision cones. [source](../source/hs/hs_globals_external.c#L1640) | Host/local |
| `ai_render_vitality` | `boolean` | AI diagnostic display/control: render vitality. [source](../source/hs/hs_globals_external.c#L1680) | Host/local |
| `ai_show` | `boolean` | AI tuning/control: show. [source](../source/hs/hs_globals_external.c#L1608) | Host/local |
| `ai_show_actors` | `boolean` | AI tuning/control: show actors. [source](../source/hs/hs_globals_external.c#L1612) | Host/local |
| `ai_show_line_of_sight` | `boolean` | AI tuning/control: show line of sight. [source](../source/hs/hs_globals_external.c#L1618) | Host/local |
| `ai_show_paths` | `boolean` | AI tuning/control: show paths. [source](../source/hs/hs_globals_external.c#L1616) | Host/local |
| `ai_show_prop_types` | `boolean` | AI tuning/control: show prop types. [source](../source/hs/hs_globals_external.c#L1620) | Host/local |
| `ai_show_sound_distance` | `boolean` | AI tuning/control: show sound distance. [source](../source/hs/hs_globals_external.c#L1622) | Host/local |
| `ai_show_stats` | `boolean` | AI tuning/control: show stats. [source](../source/hs/hs_globals_external.c#L1610) | Host/local |
| `ai_show_swarms` | `boolean` | AI tuning/control: show swarms. [source](../source/hs/hs_globals_external.c#L1614) | Host/local |

## Sources and verification

- [Default bindings](../port/linux/src/input_bindings.def), [console input/history/completion/startup](../source/main/console.c).
- [Native PB parser](../source/main/performance_console.inc), [option bit values](../source/game/performance_variant.h), [host/peer gates](../source/networking/network_server_manager.c).
- [Function registry, help, export, syntax and guest allowlist](../source/hs/hs.c), [external variable registry](../source/hs/hs_globals_external.c), [types](../source/hs/hs.h).
- [Value evaluation, inspection and variable storage](../source/hs/hs_runtime.c), [cheat implementations](../source/game/cheats.c), [path translation](../port/linux/src/xbox_files.c).
- [Optional local telnet console](../source/networking/telnet_console.c), [scripting team values](../source/game/game_allegiance.c), [AI states](../source/ai/ai_scenario_definitions.c), [actor types](../source/ai/actor_types.c), [HUD corners](../source/interface/hud_definitions.c).
- [Native port README](../port/linux/README.md), [native settings](native-settings.md), [Apple multiplayer](apple-multiplayer.md).

The catalog was extracted from registry initializers and checked against their
declared counts: 418 unique functions and 443 variable slots / 442 unique names.
Function parameter counts match the declared types. Known no-op evaluators and
NULL-backed globals were checked in source. The practical examples were reviewed
against implementations; no gameplay commands were executed and no application
settings were changed while preparing this guide.
