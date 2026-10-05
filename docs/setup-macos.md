# Getting started on Mac

You need an **Apple Silicon Mac running macOS 26 or later**, your own original
Xbox Halo: Combat Evolved disc image (`.iso` or `.xiso`), an Internet connection,
and several GB of free space. Use **USA NTSC** game data for community maps.
PC, Custom Edition, Anniversary, and MCC files will not work.

## Install and start

1. Download the Mac DMG from [Halo OG downloads](../README.md#download).
2. Open the DMG and drag **Halo OG.app** onto **Applications**. Eject the DMG.
3. Open **Halo OG** from Applications. The current testing app is not notarized;
   if macOS blocks it, attempt to open it, then use **System Settings → Privacy
   & Security → Open Anyway** for Halo OG.
4. Choose your Xbox disc image when asked and wait for import to finish. The app
   extracts the game files and leaves your disc image unchanged. Alternatively,
   place one supported `.iso` / `.xiso` beside **Halo OG.app** before opening it
   in builds with automatic disc discovery. More than one image opens a chooser.
5. Create or select a player profile. Try a stock map before joining friends.

Already have extracted Xbox maps? Choose **Choose Maps Folder**. **Copy and
Manage** keeps a separate copy in Halo OG's data folder; **Use This Folder**
keeps your external folder selected. Your original files stay in place.

All 40 community maps download in the background once compatible original data
is available, about **863 MiB** total. You can play stock maps while they download.
Check progress in **Halo OG → Settings…**, or use **Check Maps / Retry**.
Reopen map selection after downloads finish; restart if the new maps are absent.
If you previously turned downloads off, enable **Download approved community
maps in the background** there.

## Controls and settings

Use the mouse or arrow keys to navigate menus; **Enter/Space** selects and
**Escape** goes back. A gamepad also works. These keyboard defaults assume the
standard in-game controller preset:

| Action | Default |
| --- | --- |
| Move / aim | WASD / mouse |
| Fire / throw grenade | Left / right mouse button |
| Jump | Space |
| Use / reload | E or R |
| Melee | F |
| Change weapon | Q, Tab, or mouse wheel |
| Crouch / zoom | Shift / Control or middle mouse button |
| Change grenade / flashlight | X / L |
| Hold scoreboard | Backtick or F1 |
| Pause / release mouse | Escape |
| Release or recapture mouse | F12 (Fn-F12 on some keyboards) |

Open **Settings → Game Settings** in the main menu for Audio and Video, or
**Game Settings** in Pause during a match. **Smooth Motion** makes rendering
smoother on a high-refresh display; gameplay still runs at the original **30 Hz**.
Use **Accept** to save changes. **Settings → Profile Settings** opens the original
player-profile editor for controller preferences. Keyboard remapping currently
uses a file:

1. Quit Halo OG. In Finder, choose **Go → Go to Folder…** and paste
   `~/Library/Application Support/Halo OG/`.
2. Make a backup of `config.toml`, then open it as plain text. In TextEdit use
   **Format → Make Plain Text** if needed; preserve the `.toml` filename and
   use straight quotes like the examples below.
3. Find the existing `[bindings]` section and change the desired lines, for example:

   ```toml
   zoom = "MouseMiddle"
   select = "CapsLock, F1"
   ```

4. Save and reopen Halo OG. Commas allow alternative keys; `""` disables an
   action. The comments in the file describe each action. Do not add a second
   `[bindings]` section. To adjust mouse speed, change `mouse_sensitivity` in
   the existing `[input]` section: `0.5` is slower than the default `1.0`.

These bindings act as Xbox buttons; a different controller preset can change
what they do. [More controls and key names](../port/macos/README.md#launch).

## Host or join a game

Everyone should use the **same release** and map. Start with stock Blood Gulch,
Slayer, and **Performance Options → Stock**, with Input Delay and Hardcore Off.

1. The host opens **Multiplayer → System Link**, selects a profile, and uses
   **Create Game** (Y on a controller, or Tab on the keyboard). Choose map and mode.
2. On the same Wi-Fi/LAN, other players open **Multiplayer → System Link**,
   select their profiles, choose the host's game, and join.
3. New desktop discovery builds show public Internet games from **games.oghalo.com**
   in this same list. Select a game and wait for **Connecting…** to open its lobby.
   See [public discovery/private hosting](system-link-directory.md). For older
   builds or private games, the host pastes the invite copied to the clipboard into a
   message to friends. Joining players open the `halo-og://join/…` link, or copy
   it and return to Halo OG. Then select the host in **System Link** and join.
4. Once everyone is in the lobby, the host starts the match. Keep the host app running.

## Update Halo OG

In builds with update notices, use **Check for Updates…** to see availability
in Settings. **Automatically check for updates** checks for a new version;
it does not install anything. **Download Update…** opens the Mac download on
GitHub. Download it, quit Halo OG, and drag the new app into Applications to
replace the previous one. Maps, profiles, and settings stay in Application Support.

The published `test-v0.3.0-net11-gameplay1` build predates these notices; check
[Halo OG downloads](../README.md#download) manually when using that build.

## If something goes wrong

- **No maps:** use the helmet menu / Settings to choose your disc image again.
  The folder must contain original Xbox `ui.map`, not just custom maps.
- **Cannot find a friend's game:** allow Halo OG local-network access; avoid
  guest Wi-Fi. Check matching releases and send a fresh invite after restarting
  the host. Internet connections may be blocked by some routers.
- **Mouse is trapped:** press Escape or F12; click gameplay or Resume to recapture.
- **Where are my files?** Maps, profiles, settings, and `halo.log` stay in
  **Application Support/Halo OG**. Deleting the DMG does not delete them.

See [playtesting and reporting a problem](playtesting.md#report-a-problem) for
logs and connection details. Do not post your disc image or private invite.
