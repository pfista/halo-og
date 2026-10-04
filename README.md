# Halo OG

Original Xbox **Halo: Combat Evolved**, brought to modern devices through its
decompilation and native ports.

Our goal is a **faithful cross-platform reconstruction of Halo 1**, aiming for
the **closest possible feel to original Xbox LAN gameplay on any platform**.
That includes movement, weapons, sounds, presentation, input response, match
timing, and the original 30 Hz simulation. Community maps and **optional**
competitive/practice features give serious players more ways to play while
keeping OG rules as the default. This is the target we test against; complete
retail parity and matching Xbox LAN feel across platforms remain validation work.

**[Get running and join the playtest →](docs/playtesting.md)**

![Original Halo main menu running on Apple Silicon](docs/images/main-menu.png)

## Why Halo OG?

Halo OG is for players who want original Xbox Halo 1 gameplay and LAN feel on
modern devices, with community maps and optional tools for competitive and
practice play. The project's priorities are:

- **Original Xbox LAN feel across platforms.** Preserve the movement, weapon
  behavior, input response, and multiplayer timing OG players know. Assess
  networking and rendering changes against that goal, rather than assuming a
  newer implementation feels the same.
- **Xbox gameplay and presentation as the baseline.** Keep the original menus,
  bitmap fonts, HUD, scoreboard, sounds, and game rules. Preserve the 30 Hz
  simulation while allowing high-refresh rendering and optional display settings.
- **Native Mac support and straightforward installation.** An Apple Silicon app,
  Mac settings, first-launch data import, and a drag-to-Applications DMG accompany
  the Windows, Linux, and Android ports.
- **A persistent community-map library.** Managed maps, saves, and settings
  survive app updates. Mac players can opt into verified background map downloads
  and reuse downloaded maps offline.
- **Competitive options chosen by the host.** PB Options adds timers, spawn
  markers, announcements, and sound options without enabling them by default.
  Stock remains the original-rule preset.
- **Selective upstream integration.** Review correctness, performance, platform,
  and networking improvements individually, preserving the Xbox baseline and
  keeping optional modifications explicit.

The decompilation foundation and protocol-11 networking are shared with our
upstream projects; they are not exclusive Halo OG features. Our distinction is
the original-game baseline, native Mac experience, and community-map workflow.
Full retail fidelity and physical cross-platform multiplayer still need further
validation. See the [fidelity policy](docs/xbox-fidelity.md) for decisions and
evidence, and the [upstream credits](#build-and-contribute) for the work we build on.

## Download

Use the **[test-v0.3.0-net11-dmg2 testing release](https://github.com/pfista/halo-og/releases/tag/test-v0.3.0-net11-dmg2)**.
Choose your platform:

| Platform | Testing package | Requirements |
| --- | --- | --- |
| Mac | [Halo-OG-macos-arm64.dmg](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-dmg2/Halo-OG-macos-arm64.dmg) | Apple Silicon, macOS 26+ |
| Windows | [halo-windows-release.zip](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-dmg2/halo-windows-release.zip) | x86/x86-64 PC, OpenGL 4.5 |
| Linux | [halo-linux-release.zip](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-dmg2/halo-linux-release.zip) | x86, OpenGL 4.5, [32-bit runtime libraries](port/linux/README.md#requirements) |
| Android | [halo-android-release.zip](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-dmg2/halo-android-release.zip) | ARM64, Android 9+, OpenGL ES 3; controller or keyboard |

All packages in the release come from the **same source commit**. Use the same
tag when playing together. The release includes `SHA256SUMS`, `provenance.json`,
and Mac installation notes. These are experimental builds.
The Mac test build is ad-hoc signed and unnotarized, with automatic updates
disabled. Use [playtesting](docs/playtesting.md) for installation, dependencies,
CI artifact downloads and updating.

## Get running

1. Download and install the package for your platform.
2. Supply your own original Xbox Halo disc image (`.iso` / `.xiso`) or complete
   extracted `maps` folder. **USA NTSC data is recommended** and required by the
   current community-map collection. Game data is not bundled; PC, Custom
   Edition, Anniversary, and MCC data are not substitutes.
3. Create/select a profile, try a stock map, then
   [join the multiplayer playtest](docs/playtesting.md#play-together).

Mac first launch imports a disc or offers to manage a copy of your maps.
Data, saves, and settings live in `~/Library/Application Support/Halo OG/`.
Prior `Halo CE Universal` data is copied where needed, preserving the old folder
and existing files. External map folders can remain selected.
[Data management details](docs/macos-menu-and-releases.md#independently-supplied-data).

## Community maps and competitive options

The community collection contains **40 Xbox v5 NTSC maps**. Mac Settings offers
opt-in background downloads; current Windows/Linux source enables
`community_maps.auto_download` by default. The published Windows/Linux testing
packages require manual installation. Android also installs maps manually.
Verified maps remain available offline, and existing files are preserved.
Use [community-map setup](docs/playtesting.md#community-maps) for your selected
release and [map guidance](docs/community-maps.md) for storage and controls.

**PB Options** offers a match timer, spawn markers, timer announcements, and
optional silent movement/weapon-ready sounds. All modifications default **off**;
the host chooses the match's options. Use **Stock** for original-rule play.
Timer announcements need a separate audio pack, not bundled with these builds.
[PB Options](docs/performance-options.md) explains settings and compatibility.

The current network protocol is **11**; protocol-10 builds need updating.
Enabled PB Options require compatible peers. For the first cross-platform
tests, use matching Halo OG packages with PB Options off.

## Rendering, performance, and gameplay

Our reference is the feel of **original Xbox LAN play**. We assess rendering,
input response, simulation timing, and networking separately: higher FPS or a
newer protocol number alone does not establish more faithful gameplay. The
following describes the current implementation; full Xbox and cross-platform
comparisons remain acceptance work.

### Rendering and FPS

With Smooth Motion off, gameplay draws one frame per simulation tick, targeting
the original 30 FPS presentation. Optional **Smooth Motion** interpolates frames
between ticks so rendering can follow a higher display refresh rate. It keeps
the simulation at 30 Hz and presents world motion roughly one tick behind the
simulation (about 33 ms). **VSync** defaults on; turning it off removes display
synchronization, with actual FPS depending on hardware and workload. There is
no numeric FPS selector or guaranteed 120/240 FPS target. Smooth Motion and the
high-resolution HUD default off; existing saved choices are preserved.

### Performance

Native platform and renderer improvements should reduce frame time and memory
use while preserving gameplay. We compare the same maps, settings, and player
counts; changing game speed, collision, weapon timing, or movement to gain FPS
does not meet that goal. Mac rendering uses ANGLE's Metal backend, while the
Windows/Linux ports use OpenGL. Each platform still needs its own performance
and gameplay checks; a successful build is not evidence of equivalent feel.

### Simulation ticks and game modes

Gameplay runs at **30 Hz**, approximately **33.3 ms per tick**, independent of
rendering FPS. Campaign and the original Slayer, Capture the Flag, Oddball, King,
and Race modes remain available. Optional PB tools do not increase the tick rate
or replace stock mode rules. PB's elapsed match timer follows host simulation
time, uses the latest received host time on clients, and does not end matches or
change their duration. Mode availability is broader than our completed
multiplayer test coverage.

### Input response and lag

Controller input, simulation ticks, presentation delay, and network round-trip
time are different parts of the experience. We want to measure movement, aiming,
and shot response against Xbox LAN behavior, including host and client timing,
rather than equating smooth visuals with lower gameplay latency. The optional
direct-camera path is off by default and currently applies to Windows/Linux;
Mac and Android bypass it. There is no universal zero-lag mode or player-facing
one-tick input-delay toggle. Physical-controller, reference-Xbox, jitter, and
packet-loss comparisons remain work to complete.

### Networking

The current shared upstream **protocol 11** uses host authority, local client
prediction, and corrections at a 30 Hz simulation rate. The host decides damage,
deaths, spawns, pickups, and scores. This modern native networking replaces the
original Xbox lockstep implementation; matching its LAN feel is a goal we must
verify, not a claim that the networking code is identical. Protocol 11 adds wire
compatibility and received-input handling; it is not a new Halo OG prediction
algorithm. Use matching Halo OG builds for playtests. See the
[networking implementation](port/linux/NETCODE.md),
[protocol review](docs/xbox-fidelity.md#protocol-compatibility), and
[fidelity policy](docs/xbox-fidelity.md) for details and current evidence.

## Community maps and original assets

Maps stay separate from the client on Cloudflare R2 so content and application
updates can ship independently. Package reconstruction combines community
content with original dependencies extracted locally from the player's own XISO.
It removes whole unchanged original assets; modified and differently serialized
assets remain in scope. This does not establish that every retained byte is
community-authored.

The published testing build predates package reconstruction. Use the
[reconstruction guide](docs/community-map-packages.md) for current implementation,
platform support and exact original-data requirements. Keep release behavior
separate from work on `main`.

Physical cross-platform play, Internet/NAT, long sessions, full campaign coverage
and reference-Xbox fidelity still require acceptance testing. See
[playtesting](docs/playtesting.md) and the [fidelity policy](docs/xbox-fidelity.md).

## Build and contribute

[Build from source](docs/building.md) · [Apple setup](docs/apple-build.md) ·
[Community-map conversion](docs/community-maps.md) ·
[Map reconstruction](docs/community-map-packages.md) ·
[Report a playtest problem](docs/playtesting.md#report-a-problem)

The experimental [iPhone port](port/ios/README.md) is a developer build with no
installation package in this testing release. Halo OG builds on
[bnunu/halo-1](https://github.com/bnunu/halo-1),
[punpckhdq/halo](https://github.com/punpckhdq/halo), and the platform work in
[cybersecurity/halo-ce-universal](https://github.com/cybersecurity/halo-ce-universal).
We review upstream changes individually and keep optional modifications explicit.
