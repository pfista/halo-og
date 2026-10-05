# Native game settings and Mac window controls

Open **Settings → Game Settings** from the main menu, or **Game Settings**
from Pause in multiplayer, campaign or cooperative play. **Profile Settings**
continues to open the original player-profile editor. Keyboard and mouse
preferences remain in `config.toml`.

The main Settings chooser uses the original Multiplayer menu's left-hand list
and right-hand picture/description panel. Profile Settings shows the original
Spartan artwork; Game Settings shows the controller artwork. Moving between
the rows updates the preview, with the original fonts, blue highlights and
button legend retained.

Game Settings uses the same two-column chooser for Audio, Video and Multiplayer, with the
original controller-calibration and TV/Xbox illustrations. Its Audio and Video
pages clone the original Advanced Controls editor: blue option rows, separate
labels and values, the original arrow graphics, contextual help, and the native
Accept/Cancel legend. There are no replacement fonts or new artwork.

Campaign and multiplayer maps do not contain the main-menu editor artwork.
Their in-game settings use the resident pause artwork: original 202×27 buttons,
original bitmap fonts and text baseline, and the blue frame with its native
Select/Back legend. Taller option pages extend the middle of the frame while
preserving its corners and footer divider. Split-screen pages fit within their
local viewport; focused help appears beneath the frame in full-screen layouts.

Audio, Video and Multiplayer preferences belong to the local installation. They are not
part of a player profile, map or network gametype. Performance Options remain saved
gametype options with host authority. Timer cue groups, volume, position and
size are local preferences; the host still controls whether the timer and
timer audio are enabled.

## Multiplayer

| Menu control | Config key | Default | Meaning |
| --- | --- | --- | --- |
| OG Maps | `maps.show_og` | On | Show the original Xbox maps when hosting |
| Community Maps | `maps.show_community` | On | Show installed community maps, including alternate/refined imports |
| Join In Progress | `network.join_in_progress` | On | Permit new players to join a running hosted match |

Map visibility affects the host's map-selection list. Hidden maps remain
available for joining and approved downloads. At least one set must remain
On; if no visible community map is installed, the list falls back to OG maps.
Separate alternate/refined categories require reviewed catalog metadata.

Join In Progress is a local host preference. Off closes admission and reports
a running match as closed in discovery/invites; pregame lobby joining remains
available. Queue consumption rechecks it too, preventing extra split-screen
seats or queued additions after closing the match. Applying it does not remove
existing players.

## Audio

| Menu control | Config key | Meaning |
| --- | --- | --- |
| Master volume | `audio.volume` | All output, including timer announcements |
| Music volume | `audio.music_volume` | The engine's music sound class |
| Effects volume | `audio.effects_volume` | Effects and ambience, including the multiplayer announcer |
| Dialogue volume | `audio.dialogue_volume` | Unit dialogue and the three scripted dialogue classes |
| Timer Audio → Volume | `audio.timer_volume` | Optional PB timer recordings |
| Timer Audio → Countdown | `audio.timer_countdown` | Spoken warnings and ten-to-one countdown; default On |
| Timer Audio → Beeps | `audio.timer_beeps` | Common timer beeps; default On |
| Timer Audio → Minute Announcements | `audio.timer_minutes` | Elapsed minute calls; default On |
| Timer Audio → Item Cues | `audio.timer_items` | Deterministic map rocket/powerup wave reminders; default Off |
| Menu music | `audio.menu_music` | Main-menu title music on/off |

Timer Audio is a child page of Audio. Its Accept retains changes in the parent
draft; its Cancel restores the values present when entering that child page.
Accept on Audio writes the complete audio draft. Cancel on Audio discards all
pending child changes. The footer explains that the host must enable Timer Sounds.

The recordings are separate content. On Mac, they download automatically in
the background by default. **Halo OG → Settings** shows progress and lets you
disable downloads. Restart after their first installation. A complete pack in
the selected game-data folder takes priority over the managed recordings in
the saves folder. Downloading the pack does not enable Timer Sounds. See
[timer recording installation and publishing](timer-audio.md).

Volumes range from 0 to 100 percent. Left/right or clicking either arrow changes
the selection; compact pause controls also respond to either side of their row.
An untouched value from the config, such as 15 percent,
is preserved exactly. The first volume edit moves to the next or previous
10-percent step. Master zero mutes the output; the startup-only `audio.enabled`
device switch remains a file setting.

In the main-menu editors, press **A** or **Start**, or click **Accept** in the
button legend, to save the page and apply it to the running game. In the compact
pause editors, select the **Accept** row. **B**, Back or Escape discards the draft.
Existing music fades, sound-class script gains and
dialogue ducking still apply; user volumes multiply those gains. Master and
timer changes reach the mixer under its lock, including a timer clip already
playing. Changing Menu Music during a match affects the next main-menu visit.

## Video

Video contains **Fullscreen**, **VSync**, **Smooth Motion**, **Timer Position**
and **Timer Size**. Smooth Motion enables render interpolation while simulation remains
30 Hz. Switching interpolation resets its old snapshots before rendering with
the new setting.

Timer Position is Top Center, Bottom Center or Bottom Right
(`display.timer_position`, default 0). Timer Size is 50–100%
(`display.timer_scale`, default 1); editing moves in 5% steps and untouched
fractional values remain exact. Both apply to each local viewport using the
stock HUD font, colors and shadow. They only appear when the host enables Match Timer.

Fullscreen shares the existing native Mac preference in `macos-settings.json`;
Linux and Windows save it as `display.fullscreen` in `config.toml`.
VSync and Smooth Motion use `display.vsync` and `display.interpolation` in
`config.toml`. Settings apply on Accept without restarting. Rendering resolution,
aspect selection, Direct Camera and high-resolution HUD behavior are unchanged.

## Mac input and window behavior

- Escape opens Pause during gameplay and releases the cursor. Within menus it
  goes back; inside the developer console it closes the console.
- F and Backspace retain Halo's B button behavior. Escape is consumed by the
  native behavior even when an older config includes it in the B binding.
- F12 remains the mouse release/recapture shortcut. Menus keep the cursor free.
- Resume captures after Pause closes. Clicking released gameplay also captures,
  and that first click is consumed so it cannot fire a weapon.
- Changing focus, opening native panels and choosing Show Game leave the cursor
  free. Releasing clears held and queued gameplay input.
- The game window retains the native resizable frame, with the title and
  traffic-light buttons hidden. Its top strip can be dragged while the cursor
  is free. Control-Command-F and the View menu still change fullscreen;
  Command-Q quits normally.

Multiplayer networking continues while the local cursor is released.
Campaign and co-op settings inherit the original pause menu's pause flag, so
opening Audio, Video or nested Timer Audio keeps game time and game audio paused.
Closing the menu releases that pause. Multiplayer settings retain the original
unpaused behavior.

## Persistence and verification

The shared settings boundary validates changed rows, preserves unrelated TOML
text, and replaces the config atomically. A failed save keeps the menu open.
On Mac, fullscreen and TOML preferences use separate stores. On Linux and
Windows, fullscreen joins the same config transaction as other preferences.
If storage or the display backend also refuses restoration after an error,
the menu reloads current values and reports that restoration was incomplete.

The current renderer retains the startup aspect when resizing; dynamic aspect
changes are a separate improvement. Physical-controller split-screen, subjective
audio and cross-platform gameplay need separate runtime checks. See
[building and validation](building.md#validation-and-contribution) for test entry points.
