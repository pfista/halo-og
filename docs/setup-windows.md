# Getting started on Windows

You need an **x86/x86-64 Windows PC with OpenGL 4.5**, your own original Xbox
Halo: Combat Evolved disc image (`.iso` or `.xiso`), an Internet connection,
and several GB of free space. Use **USA NTSC** game data for community maps.
PC, Custom Edition, Anniversary, and MCC files will not work.

## Install and start

1. Download the Windows ZIP from [Halo OG downloads](../README.md#download).
   Windows uses the ZIP, not the Mac DMG.
2. Right-click the ZIP and choose **Extract All…** into a folder you can write
   to, such as **Documents\Halo OG**. This is a portable build, not an installer.
3. Put **one** original Xbox `.iso` / `.xiso` in the extracted folder beside
   **halo.exe**. Keep **SDL3.dll** and the other supplied files there too.
4. Open **halo.exe** and wait for game-data import. The image stays unchanged;
   extracted files go into **maps** in the same folder. Older releases may ask
   you to select the image manually. If more than one supported image is present,
   choose the one you want when prompted.
5. Create or select a profile and try a stock map.

Already have extracted Xbox maps? Put the complete **maps** folder beside
**halo.exe**. It must include original `ui.map`. Existing game data takes priority
over disc import; existing maps are not overwritten.

All 40 community maps download automatically in the background after compatible
original data is available, about **863 MiB** total. Play stock maps while you
wait, then **restart the game** to refresh the map list. Downloaded maps stay in
the same **maps** folder and work offline. If downloads were previously disabled,
quit the game and set `auto_download = true` in the existing `[community_maps]`
section of **config.toml**, then reopen it.

## Controls and settings

Use the mouse or arrow keys for menus; **Enter/Space** selects and **Backspace**
goes back. A gamepad also works. These defaults assume the standard controller preset:

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

Open **Settings → Game Settings** for Audio and Video, or **Game Settings** from
Pause. **Smooth Motion** allows smoother rendering while gameplay stays at the
original **30 Hz**; use **Accept** to save. **Settings → Profile Settings** opens
controller preferences. Keyboard remapping currently uses a file:

1. Close Halo OG. Back up **config.toml** beside **halo.exe**, then open it in Notepad.
2. Find the existing `[bindings]` section and change lines, for example:

   ```toml
   zoom = "MouseMiddle"
   select = "CapsLock, F1"
   ```

3. Save without changing the filename to `.txt`, then reopen the game. Commas
   allow alternative keys; `""` disables an action. Use the comments for other
   actions and do not add a second `[bindings]` section. For mouse speed, change
   `mouse_sensitivity` in the existing `[input]` section: `0.5` is slower than
   the default `1.0`.

These bindings act as Xbox buttons, so changing the controller preset can change
their actions. [All key names and controls](../port/linux/README.md#controls).

## Host or join a game

Use the **same release and map** as your friends. Start with stock Blood Gulch,
Slayer, and **PB Options → Stock**; optional competitive changes default off.

1. The host opens **Multiplayer → System Link**, selects a profile, and chooses
   **Create Game** (Y on a controller, or Tab). Select the map and mode.
2. On the same LAN, others open **Multiplayer → System Link**, select their
   profiles, choose the host's game, and join. Allow firewall access for Halo
   when Windows asks on your trusted local network.
3. For Internet play, the host pastes the invite copied to its clipboard into a
   message. Joining players **copy the complete `halo://join/…` link and switch
   back to Halo**, then select the host in **System Link** and join.
4. Once everyone is in the lobby, the host starts the match and keeps the game open.

## Update Halo OG

New setup builds check for updates in the background and show **Halo OG update
available** in the main menu. Choose **Open download** for the Windows ZIP, or
**Later** to keep playing. **Stop checking** turns off future checks; to re-enable
them, close the game and set `auto = true` in the existing `[update]` section
of **config.toml**.

After downloading, close Halo and extract the new build into a separate folder.
Copy your **maps** folder and **config.toml** into it. Profiles/saves stay in
**%APPDATA%\Halo OG**. Keep the old folder until the new build works.
Install the downloaded build manually using these steps.

The published `test-v0.3.0-net11-gameplay1` build predates these notices; check
[Halo OG downloads](../README.md#download) manually when using that build.

## If something goes wrong

- **Missing SDL3.dll:** extract the entire ZIP; run the extracted **halo.exe**.
- **No maps:** select your Xbox image when prompted. Keep custom-only folders
  separate until original data has been imported; custom maps alone cannot start the game.
- **Graphics error:** check OpenGL 4.5 support and your GPU driver.
- **Cannot see the host:** check releases, firewall access, and Wi-Fi; guest
  networks often isolate players. Restarting the host requires a new invite.
- **Where are my files?** Keep the extracted **maps** folder and **config.toml**
  when updating. Profiles/saves live in **%APPDATA%\Halo OG** by default.

For reporting, **debug.txt** is in the folder containing **maps**. See
[playtesting](playtesting.md#report-a-problem) for download logs and connection
help. Do not share disc images or private invite codes in public reports.
