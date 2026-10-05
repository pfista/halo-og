# Getting started on Android

You need an **ARM64 Android device running Android 9 or later with OpenGL ES 3**,
a **game controller or keyboard**, your own original Xbox Halo: Combat Evolved
`.iso` / `.xiso`, and several GB of free space. **Gameplay has no touch controls.**
Use USA NTSC game data for the community collection; PC, Custom Edition,
Anniversary, and MCC files will not work.

## Install and start

1. Download and extract the Android ZIP from [Halo OG downloads](../README.md#download).
2. Copy **app-release.apk** onto the device and open it. Allow installation
   from that file source if Android asks, then install Halo OG.
3. Copy your Xbox disc image onto the device. Open Halo OG, use the import
   button to open the system file picker, and select that image.
4. Wait for extraction, connect a game controller or keyboard, then create or
   select a profile. Try a stock map before joining others.

The app keeps game data in
`/sdcard/Android/data/com.halo.decomp/files/`. Your disc image is not modified.
**Android does not yet automatically download community maps.** To add one,
copy the approved `.map` file into that folder's **maps** directory and restart.
Modern Android may restrict access to this folder; use a computer and the
[Android data instructions](../port/android/README.md#game-data) if needed.
[Approved map download links](playtesting.md#community-maps) list the collection.

## Controls and settings

Controller buttons follow Xbox positions with the standard controller preset:

| Action | Xbox button |
| --- | --- |
| Move / aim | Left / right stick |
| Fire / grenade | Right / left trigger |
| Jump / select | A |
| Melee / back | B |
| Use / reload | X |
| Change weapon | Y |
| Crouch / zoom | Left / right stick click |
| Pause | Start |
| Hold scoreboard | Back/Select |

Open **Settings → Game Settings** for Audio and Video, or **Game Settings** in
Pause; choose **Accept** to save. **Settings → Profile Settings** opens original
controller preferences. Gameplay stays at the original **30 Hz**; competitive
options are optional and default off.

A Bluetooth/USB keyboard uses the [Linux keyboard defaults](setup-linux.md#controls-and-settings).
There is currently no in-game keyboard remapping page. Keyboard bindings live
in **config.toml** in the app's data folder, with the same `[bindings]` format.
Editing it may require a computer; [Android settings](../port/android/README.md#settings)
explains how. For the easiest first session, use a controller.

## Host or join a game

Use the **same release and map** as your friends. Start with stock Blood Gulch,
Slayer, and **Performance Options → Stock**, with Input Delay and Hardcore Off.

1. The host opens **Multiplayer → System Link**, selects a profile, and chooses
   **Create Game** (Y). Pick the map and mode.
2. On the same Wi-Fi/LAN, other players open **Multiplayer → System Link**,
   select their profiles, choose the host, and join.
3. For Internet play, the host shares the invite copied to the clipboard.
   Joining players open the complete `halo://join/…` link, or copy it and
   return to Halo, then select the host in **System Link** and join.
4. The host starts the match when everyone is in the lobby. **Keep Halo in
   the foreground** throughout: Android can stop it when you switch apps.

## If something goes wrong

- **No touch response in gameplay:** connect a controller or keyboard.
- **Cannot find the host:** check matching releases and maps; avoid isolated
  guest Wi-Fi. Get a new invite if the host restarted. Internet/router
  compatibility still needs playtesting.
- **Updating:** install the new APK over the current one if its signing key
  matches. If Android reports a signature conflict, back up maps and saves
  before uninstalling; **uninstalling can remove all app data**.

Logs are **debug.txt** in the app's data folder; profiles/saves are under **save**.
See [reporting a problem](playtesting.md#report-a-problem) and
[Android troubleshooting](../port/android/README.md#find-problems). Do not
include game files or private invite codes in public reports.
