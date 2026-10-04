# Getting started on Linux

The current package is a **32-bit x86 Linux build requiring OpenGL 4.5**.
You need your own original Xbox Halo: Combat Evolved `.iso` / `.xiso`, an
Internet connection, and several GB of free space. Use **USA NTSC** data for
community maps; PC, Custom Edition, Anniversary, and MCC files will not work.

## Install and start

1. Download the Linux ZIP from [Halo OG downloads](../README.md#download) and
   extract it into a writable folder, such as **~/Games/Halo OG**. It is a
   portable package, not an installer.
2. Install your distribution's **32-bit** glibc, SDL3, OpenGL/Mesa, and
   PipeWire or PulseAudio client libraries. Even a 64-bit OS needs their 32-bit
   versions. [Runtime requirements and package names](../port/linux/README.md#requirements).
3. Put **one** original Xbox `.iso` / `.xiso` beside **halo** in that folder.
4. Open a terminal in the extracted folder and run:

   ```sh
   chmod +x halo
   ./halo
   ```

5. Wait for import, then create or select a profile and try a stock map. Your
   disc image stays unchanged; extracted files go into **maps** beside **halo**.
   Older releases may ask you to select the image manually. Multiple supported
   images open a chooser.

A complete extracted Xbox **maps** folder can go beside **halo** instead. It
must include original `ui.map`. Existing original game data takes priority
over importing an image and is not overwritten.

All 40 community maps download in the background after compatible original
data is ready, about **863 MiB** total. You can play stock maps meanwhile.
Watch the terminal for progress/errors and **restart after downloads finish**
to refresh the map list. Downloads remain in the active **maps** folder for
offline play. If you previously disabled them, close Halo and set
`auto_download = true` in the existing `[community_maps]` section of **config.toml**.

## Controls and settings

Use the mouse or arrow keys to navigate menus; **Enter/Space** selects and
**Backspace** goes back. A gamepad also works. These defaults assume the standard controller preset:

| Action | Default |
| --- | --- |
| Move / aim | WASD / mouse |
| Fire / throw grenade | Left / right mouse button |
| Jump | Space |
| Use / reload | E or R |
| Melee | F |
| Change weapon | Tab or mouse wheel |
| Crouch / zoom | Left Control or C / Z or middle mouse button |
| Change grenade / flashlight | X / Q |
| Hold scoreboard | F1 |
| Pause | Escape |
| Release or recapture mouse | F12 |
| Fullscreen / window | F11 |

**Settings → Game Settings** in the main menu, or **Game Settings** in Pause,
provides Audio and Video controls. **Smooth Motion** allows smoother rendering
while the original gameplay simulation stays at **30 Hz**; choose **Accept**
to save. **Settings → Profile Settings** opens controller preferences.
Keyboard remapping currently uses a file:

1. Close Halo and back up **config.toml** beside **halo**.
2. Open it in a text editor. Find the existing `[bindings]` section and edit
   the relevant lines, for example:

   ```toml
   zoom = "MouseMiddle"
   select = "CapsLock, F1"
   ```

3. Save and restart. Commas allow alternative keys; `""` disables an action.
   Read the comments for other actions and do not add another `[bindings]`
   section. For mouse speed, change `mouse_sensitivity` in the existing `[input]`
   section: `0.5` is slower than the default `1.0`.

These bindings act as Xbox buttons; a different controller preset can change
their actions. [Full key names and controls](../port/linux/README.md#controls).

## Host or join a game

Everyone needs the **same release and map**. Start with stock Blood Gulch,
Slayer, and **PB Options → Stock**; optional competitive changes default off.

1. The host opens **Multiplayer → System Link**, selects a profile, and chooses
   **Create Game** (Y on a controller, or Tab). Select the map and mode.
2. On the same LAN, other players open **Multiplayer → System Link**, select
   their profiles, choose the host's game, and join.
3. For Internet play, the host pastes the invite copied to the clipboard into a
   message. Joining players **copy the complete `halo://join/…` link and return
   to Halo**, then select the host in **System Link** and join.
4. The host starts the match when everyone is in the lobby and keeps Halo running.

## Update Halo OG

New setup builds check in the background and show **Halo OG update available**
in the main menu. **Open download** opens the Linux ZIP in your browser;
**Later** keeps playing. **Stop checking** disables future checks. To re-enable
them, close Halo and set `auto = true` in the existing `[update]` section of
**config.toml**.

After downloading, close Halo, extract the new build into a separate folder,
and copy **maps** and **config.toml** from the previous folder. Keep backups
until it works. Profiles/saves stay in **~/.local/share/halo-og** by default
(or **$XDG_DATA_HOME/halo-og** if configured). Install the downloaded build
manually using these steps.

The `gameplay1` and `setup1` Windows/Linux builds do not have these notices; check
[Halo OG downloads](../README.md#download) manually when using that build.

## If something goes wrong

- **“No such file” although halo exists, or a missing library:** check the
  required 32-bit runtime libraries. A 64-bit SDL3 package alone is insufficient.
- **No maps:** select your Xbox image when prompted; custom-only maps do not
  replace original `ui.map`. See [data-folder selection](../port/linux/README.md#start-the-game)
  if you already have data elsewhere.
- **Cannot find the host:** allow Halo traffic through your firewall, use the
  same LAN, and avoid guest Wi-Fi. Send a new invite after restarting the host.
  Some Internet routers prevent peer connections.
- **Where are my files?** Keep **maps** and **config.toml** when updating.
  Profiles/saves stay in **~/.local/share/halo-og** by default.

**debug.txt** is in the folder containing **maps**. See
[playtesting and reporting](playtesting.md#report-a-problem) for logs and
connection details. Do not post disc images or private invites.
