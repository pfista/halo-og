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

**Getting started: [Mac](docs/setup-macos.md) · [Windows](docs/setup-windows.md) ·
[Linux](docs/setup-linux.md) · [Android](docs/setup-android.md)**

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
- **A persistent community-map library.** Mac managed maps, saves, and settings
  survive app updates. Mac, Windows, and Linux download the complete community
  collection in the background by default and reuse verified maps offline.
- **Competitive options chosen by the host.** PB Options adds timers, spawn
  markers, announcements, and sound options without enabling them by default.
  Stock remains the original-rule preset.
- **Selective upstream integration.** Review correctness, performance, platform,
  and networking improvements individually, preserving the Xbox baseline and
  keeping optional modifications explicit.
- **A shared multiplayer ecosystem.** Aim to find and join cybersecurity games
  through compatible network and discovery protocols while retaining Halo OG's
  original presentation and local experience. Shared match rules remain the
  host's responsibility; mixed-client support needs explicit testing.

The decompilation foundation and protocol-11 networking are shared with our
upstream projects; they are not exclusive Halo OG features. Our distinction is
the original-game baseline, native Mac experience, and community-map workflow.
Full retail fidelity and physical cross-platform multiplayer still need further
validation. See the [fidelity policy](docs/xbox-fidelity.md) for decisions and
evidence, and the [upstream credits](#build-and-contribute) for the work we build on.

## Download

Use the **[test-v0.3.0-net11-setup1 testing release](https://github.com/pfista/halo-og/releases/tag/test-v0.3.0-net11-setup1)**.
This build adds automatic disc-image setup and Halo OG update notices on Mac,
Windows, and Linux, with short setup guides for every platform. It also includes
the prior spawn, teleporter, and projectile-trail fixes. Choose your platform:

| Platform | Testing package | Requirements |
| --- | --- | --- |
| Mac | [Halo-OG-macos-arm64.dmg](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-setup1/Halo-OG-macos-arm64.dmg) | Apple Silicon, macOS 26+ |
| Windows | [halo-windows-release.zip](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-setup1/halo-windows-release.zip) | x86/x86-64 PC, OpenGL 4.5 |
| Linux | [halo-linux-release.zip](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-setup1/halo-linux-release.zip) | x86, OpenGL 4.5, [32-bit runtime libraries](port/linux/README.md#requirements) |
| Android | [halo-android-release.zip](https://github.com/pfista/halo-og/releases/download/test-v0.3.0-net11-setup1/halo-android-release.zip) | ARM64, Android 9+, OpenGL ES 3; controller or keyboard |

All packages in the release come from the **same source commit**. Use the same
tag when playing together. The release includes `SHA256SUMS`, `provenance.json`,
and Mac installation notes. These are experimental builds.
The Mac test build is ad-hoc signed and unnotarized, with update notices and manual
installation; signed automatic installation is not configured. Use [playtesting](docs/playtesting.md) for installation, dependencies,
CI artifact downloads and updating.

## Getting started

Choose your platform's short guide for installation, importing your disc,
keyboard controls, settings, and hosting or joining a game:

- [Mac setup](docs/setup-macos.md)
- [Windows setup](docs/setup-windows.md)
- [Linux setup](docs/setup-linux.md)
- [Android setup](docs/setup-android.md)

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

For the simplest Windows/Linux setup, extract the package, put one original
Xbox `.iso` / `.xiso` beside the executable, then open the game. New setup builds
import it automatically when no original data is already available; older
downloads may ask you to choose it. Community maps download in the background.
Mac also supports an adjacent image in new setup builds, with its usual disc
chooser available. Keyboard remapping currently uses the commented `[bindings]`
section in `config.toml`; the platform guides show its location and examples.
Audio and Video settings are available through in-game **Game Settings**.

## Community maps and competitive options

The community collection contains **40 Xbox v5 NTSC maps**, about **863 MiB**.
Mac, Windows, and Linux download the whole collection automatically in the
background after compatible game data is selected. Existing saved opt-outs
remain off: use Mac Settings or `community_maps.auto_download` in Windows/Linux
`config.toml` to change this. Android installs community maps manually.
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

Interoperability with cybersecurity clients is a goal. We can share connection
and discovery protocols while keeping original Xbox graphics and our own menus.
The host's rules still govern a shared game: changing the HUD or rendering is
different from changing movement, weapons, damage, or match timing independently.
Some upstream game options need further compatibility work, and Internet play
needs mixed-client testing. Its PC-style server browser UI is not part of this fork;
future discovery UI will use original Xbox-style Multiplayer/System Link menus
after a user check-in.
See the [interoperability review](docs/network-interoperability.md).

## Community maps and original assets

Complete playable community `.map` files stay separate from the client on
Cloudflare R2 so map updates can ship independently and builds stay small.
Downloads verify size, SHA-256, and Xbox cache identity before installation.
These maps include their normal embedded Halo dependencies; they do not require
local tag extraction or map reconstruction. That experimental work is set aside.

Players still supply their own original Xbox disc image or extracted game data.
The hosted collection excludes disc images and separate stock, campaign, and UI
map files. Mac community downloads live in the managed map library, separately
from the application, and survive updates. Windows and Linux put them in the
active game-data root's `maps` folder; keep that folder when updating a build.

Physical cross-platform play, Internet/NAT, long sessions, full campaign coverage
and reference-Xbox fidelity still require acceptance testing. See
[playtesting](docs/playtesting.md) and the [fidelity policy](docs/xbox-fidelity.md).

## Build and contribute

[Build from source](docs/building.md) · [Apple setup](docs/apple-build.md) ·
[Community-map conversion](docs/community-maps.md) ·
[Report a playtest problem](docs/playtesting.md#report-a-problem)

The experimental [iPhone port](port/ios/README.md) is a developer build with no
installation package in this testing release. Halo OG builds on
[bnunu/halo-1](https://github.com/bnunu/halo-1),
[punpckhdq/halo](https://github.com/punpckhdq/halo), and the platform work in
[cybersecurity/halo-ce-universal](https://github.com/cybersecurity/halo-ce-universal).
We review upstream changes individually and keep optional modifications explicit.
