# Halo OG on Apple Silicon

The native ARM64 port uses ANGLE's Metal renderer and the Xbox-derived engine.
Original game data is supplied separately.

## Download

Use [playtesting](../../docs/playtesting.md#mac) for current packages, installation
and first launch. [Release tooling](../../docs/macos-menu-and-releases.md) covers
DMG packaging, CI artifacts and publication.

## Launch

Open `build/macos/Halo OG.app` in Finder. There is no automatic timeout.
The app includes SDL3, ANGLE, Sparkle, and the compiled game image. It remembers
your chosen local data location. Development builds can fall back to this
checkout's `assets/` directory. The helmet menu icon opens Settings, changes
fullscreen, and selects your own disc image or maps folder. See
[Mac menu and releases](../../docs/macos-menu-and-releases.md) for first launch,
data import and the intentionally unconfigured release hosting.

The app defaults to borderless fullscreen at the desktop's aspect ratio, with
Retina output. The 3D field of view widens; the image is not stretched. Rendering
still uses 480 vertical lines internally, scaled to the display. On the tested
display this is 740x480 into a 3420x2214 drawable. Set `HALO_WINDOWED=1` for a
resizable window or `HALO_SCREEN_WIDTH=640` to restore the original 4:3 view.
`HALO_WINDOW_SCALE` controls the initial size in windowed mode.

New configurations use the maps' original HUD bitmaps, 30 FPS presentation and
the tick-based camera. Existing `config.toml` values remain in effect. The
upstream high-resolution HUD artwork, interpolation and direct camera remain
available as explicit settings. For a separate 4:3 comparison configuration,
use [xbox-ntsc.toml](profiles/xbox-ntsc.toml) and the existing
`HALO_SCREEN_WIDTH=640` override. See the [fidelity policy](../../docs/xbox-fidelity.md).
Text glyphs keep the fonts in the game data and have clear borders to
prevent neighboring characters from bleeding into their edges, and widescreen
menu dimming and flat backgrounds cover the whole display.

Saves, cache files, `config.toml`, and `halo.log` are under:

```text
~/Library/Application Support/Halo OG/
```

On first launch, prior settings, saves and managed game data are copied from
`~/Library/Application Support/Halo CE Universal/`. The original files remain
in place, and existing files under Halo OG are preserved. The bundle identifier
remains stable.

Keyboard/mouse controls:

| Control | Action |
| --- | --- |
| W A S D / mouse | Move / aim |
| Left / right mouse button | Fire / grenade |
| Space or Enter | Jump / accept |
| E or R | Action / reload (X) |
| F or Backspace | Melee / back (B) |
| Escape | Pause and release mouse / back in menus |
| Q, Tab or mouse wheel | Change weapon (Y) |
| L | Flashlight |
| X | Change grenade type |
| Shift (either side) | Crouch |
| Control (either side) or middle mouse button | Zoom |
| 1 | Pause (Start) |
| Backtick (`) or F1 | Hold for scoreboard (Back/Select) |
| F2 | Open / close developer console |
| F12 (Fn-F12 on some keyboards) | Release or recapture mouse |

Menus support mouse navigation. The cursor stays free after switching apps or
closing a native panel; choose Resume or click gameplay to capture it. That
first capture click does not fire. Windowed play keeps a resizable native frame
with its title/buttons hidden; drag the top strip while the cursor is released.
See [native settings](../../docs/native-settings.md) for live Audio/Video options
in the main and pause menus.

All keyboard/controller actions and mouse buttons can be changed in the
`[bindings]` section of `~/Library/Application Support/Halo OG/config.toml`.
The first launch adds any missing bindings with their defaults, preserving
existing settings, bindings and comments. Quit Halo, edit the file, and restart
to apply changes. These bindings emit Xbox controller buttons, so an in-game
controller preset can also change what an action does.

For example, these are the Mac defaults for the main keyboard actions:

```toml
[bindings]
x = "E, R"
y = "Q, Tab, Wheel"
zoom = "Ctrl, MouseMiddle"
start = "1"
select = "Grave, F1"
a = "Space, Return, KeypadEnter"
b = "F, Escape, Backspace, MouseX1, ACBack"
crouch = "Shift"
console = "F2"
release_mouse = "F12"
```

Names are case-insensitive. Separate alternative keys/buttons with commas;
for example, `select = "CapsLock, F1"`. `Grave`, `Backtick`, or the literal
backtick names the physical backtick key. `Ctrl`, `Shift`, `Alt`/`Option`, and
`Cmd` match either side; `LeftCtrl` and `RightCtrl` select just one. Letters,
digits, F1-F24, arrows, `Space`, `Return`, `Escape`, `Tab`, `Backspace`,
`CapsLock`, navigation keys and keypad keys are supported. Mouse names are
`MouseLeft`, `MouseRight`, `MouseMiddle`, `MouseX1`, `MouseX2`, and `Wheel`.
Use `""` to unbind an action, and use names such as `Comma` for punctuation.
The `console` and `release_mouse` bindings accept keyboard keys only and take
priority over controller actions. Invalid bindings are logged and use the
default for that action. The remaining movement, D-pad, trigger, flashlight
and grenade bindings are listed with comments in the generated config.

`HALO_DATA_ROOT`, `HALO_SAVE_ROOT`, `HALO_WINDOW_SCALE`, `HALO_VOLUME`, and the
other [shared native settings](../linux/README.md#settings) remain available.
For a command-line run from the repository root:

```sh
build/macos/halo build/macos/halo_guest.elf
```

That development command uses `build/macos/saves/` by default; the app uses the
Mac Application Support location above.

For Mac invite links and Mac-versus-iPhone LAN setup, follow
[Apple multiplayer setup](../../docs/apple-multiplayer.md). Builds must use the
same networking revision and map set. Hosting copies an invite to the clipboard;
opening it, or copying it and switching to Halo, connects the peers so the host
appears in the System Link browser.

With the Discord desktop client running, Halo connects to its local RPC socket
and accepts Discord game invitations. Hosting a System Link game publishes
"Hosting a game" with an invite in Discord. Enable activity sharing in Discord
to make it visible. The installed app handles both `halo://` links and the
upstream Discord application's launch scheme, so an invite can start Halo
when it is closed. Ordinary campaign/client gameplay does not publish activity.
This branch uses multiplayer protocol 11 and 64-digit invite codes; all players
need matching builds. Command-W is ignored while playing, and Command-Q or
the window's close button quits.

## Build

Complete [Apple dependencies and setup](../../docs/apple-build.md), keeping its
LLVM exports in the shell used for the build. From the repository root:

```sh
python3 tools/macos_build.py
open "build/macos/Halo OG.app"
```

`--install` installs a verified app in Applications and preserves the previous
copy. Quit an older running copy before launching its replacement.
`--no-data-path` omits the development data path; first launch then asks for data.
`--data-root /path/to/game` selects another local data root.

After configuration, `ninja macos_guest` rebuilds game code;
`macos_build.py --host-only` rebuilds/packages the host. Compiler adapters and
wrappers are tracked build dependencies. `HALO_MACOS_SDL_PREFIX` and
`HALO_MACOS_ANGLE_DIR` can select dependency locations. Local builds are ad-hoc
signed; packaging verifies the signature. See [release tooling](../../docs/macos-menu-and-releases.md)
for distributable bundles and [validation](../../docs/apple-build.md#validation).

## Memory and host architecture

Extra RAM does not solve the original address problem: the game stores pointers
and `long` in 32 bits, while ordinary ARM Mac executables cannot use its original
low addresses. The LLVM pass preserves those layouts and rebases memory access
and indirect calls into a 4 GB **virtual** arena at `0x10000000000`. This address
is not a physical RAM requirement. Memory is committed only as needed.

The pass uses LLVM address space 272 for 64-bit dereferences, explicitly lowers
varargs and memory intrinsics, preserves opaque GL offsets/handles, and translates
host pointer arguments. The Mac image has a distinct ABI version, so it cannot
be accidentally loaded by the Android host. This is an ABI adapter for the
locally compiled game, not an isolation boundary for arbitrary binaries.

The native host translates Linux/musl file, time, synchronization, memory, and
error interfaces to Darwin. Xbox 4 KB allocations share native 16 KB pages;
protection combines their requirements so freeing one allocation cannot remove
access to its neighbors. Texture write tracking therefore has 16 KB granularity.
Fresh heap mappings are explicitly recreated: Darwin's `MADV_DONTNEED` alone
does not guarantee the zero-filled pages expected by musl.

The Mac renderer streams current geometry by default. The optional cache in
`renderer_config.h` compares current vertex and index pages with a CPU shadow
before reusing the contiguous geometry mirror. This detects reused map memory
and writes missed by page tracking, including changes within one frame. Shadows
are allocated lazily and bounded by the original 128 MB contiguous arena;
frequently rewritten geometry, allocation failures and unsupported ranges use
the existing streaming path. The cache reduced uploads but did not improve
median frame time, so it remains disabled. iOS continues streaming until its
cache is validated on a device. The cache prototype passed Prisoner → Chill Out
→ a10 → b30 → Prisoner; captured Chill Out geometry matched the streamed
reference after a map change.

SDL video stays on the real main thread. Audio mixing runs on a guest-stack
worker, with the results returned to SDL's callback thread before submission.
This avoids a cross-thread stream-lock deadlock. Mouse capture is enabled on
macOS even though the renderer shares the Android GLES compilation path.

## Validation and remaining work

Use the [Apple checks](../../docs/apple-build.md#validation) for ABI/runtime,
input, native UI and renderer regressions. Physical controllers, split screen,
reference-Xbox comparisons, full campaign/save coverage, long sessions and
cross-platform networking need explicit gameplay validation. Bink startup videos
are skipped by the native port.

## Performance checks

Compare the same maps, settings and player counts using isolated outputs:

```sh
python3 tools/macos_benchmark.py --output build/macos/performance/retest --effects --fullscreen
```

`--host` and `--guest` select comparison builds; `--levels` and `--cycle-seconds`
select workloads. `--checkpoints` verifies safe save/revert (use a30, since the
initial a10 scene can refuse saves). `--screenshot-every N` captures frames.
The benchmark records CSV, console/game logs and `validation.json`; rejected
commands, early exits and rendering failures fail the run.

`HALO_PERF_LOG=/absolute/path/frames.csv` profiles an ordinary launch. Draw timing
includes driver/VSync waits and is not a GPU timestamp measurement. Maximum FPS,
memory growth and visual fidelity require comparable sustained workloads.
