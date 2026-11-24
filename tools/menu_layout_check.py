#!/usr/bin/env python3
"""Walk the real menus and fail on any text that does not fit its box.

Starts one isolated Mac game with debug.ui_layout_check on, drives controller 1
through the script console ("press <button>"), waits for each screen by its
tag name ("ui"), and saves a picture of every screen it visits. The game logs
each text that is wider or taller than its box; any such line fails the run.

Needs a local Mac build (tools/macos_build.py --build-only) and game data in
the primary checkout. Personal saves and settings are not used.
"""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from primary_checkout import PRIMARY  # noqa: E402

BUILD = ROOT / "build/macos"
LAYOUT_MARKER = "ui layout: "

# Each tour is a list of steps: ("press", button), ("focus", place in the
# list, from 0), ("expect", part of the top screen's tag name), ("shot",
# picture name) or ("wait", seconds). "focus" reads the game's own focus and
# presses up or down until it is there, so a tour does not count presses.
MAIN_MENU = [("expect", "main_menu\\main_menu"), ("focus", 0), ("shot", "main-menu")]
MULTIPLAYER = MAIN_MENU + [
    ("focus", 1), ("press", "a"), ("expect", "multiplayer_type_select_screen"), ("shot", "multiplayer"),
]
GAME_SETTINGS = MAIN_MENU + [
    ("focus", 2), ("press", "a"), ("expect", "native_settings\\settings"), ("shot", "settings"),
    ("focus", 1), ("press", "a"), ("expect", "native_settings\\screen_0_0"), ("shot", "game-settings"),
]


def game_settings_page(place, screen, name):
    return [("focus", place), ("press", "a"), ("expect", "native_settings\\" + screen), ("shot", name),
            ("press", "b"), ("expect", "native_settings\\screen_0_0")]


def pause_tour(players):
    """Pause for this many local players: its menu, Performance Options and every Game Settings page."""
    layout = {1: 1, 2: 2, 4: 3}[players]
    root, settings = f"performance\\pause_{players}p", f"native_settings\\screen_{layout}_"
    steps = [("wait", 22), ("press", "start"), ("expect", root), ("shot", "pause"),
             ("focus", 1), ("press", "a"), ("expect", f"performance\\pause_options_{players}p"), ("shot", "pause-performance"),
             ("press", "b"), ("expect", root),
             ("focus", 2), ("press", "a"), ("expect", settings + "0"), ("shot", "pause-settings")]
    for place, (page, name) in enumerate(((1, "audio"), (2, "video"), (4, "controller"), (5, "multiplayer"))):
        steps += [("focus", place), ("press", "a"), ("expect", settings + str(page)), ("shot", "pause-" + name)]
        if name == "audio":
            # Audio's sub-page, the one a page gets instead of more rows.
            steps += [("focus", 4), ("press", "a"), ("expect", settings + "3"), ("shot", "pause-audio-timer"),
                      ("press", "b"), ("expect", settings + str(page))]
        steps += [("press", "b"), ("expect", settings + "0")]
    return steps


TOURS = {
    # The game type list's legend and the locked game type's dialog.
    "gametypes": MULTIPLAYER + [
        ("focus", 3), ("press", "a"), ("expect", "gametype_select_screen"), ("shot", "edit-gametypes"),
        ("press", "a"), ("expect", "error_modal"), ("shot", "locked-game-type"),
    ],
    # Settings, and every Game Settings page as the main menu shows it.
    "settings": GAME_SETTINGS + game_settings_page(0, "screen_0_1", "game-settings-audio")
    + game_settings_page(1, "screen_0_2", "game-settings-video")
    + game_settings_page(2, "screen_0_4", "game-settings-controller")
    + game_settings_page(3, "screen_0_5", "game-settings-multiplayer"),
    # Pause in a hosted Slayer game, one player.
    "pause": pause_tour(1),
    # The same pages as two and four players' split screen lays them out. One
    # controller cannot open a second player's Pause, so debug.pause_layout
    # shows player one's in a half or a quarter of the screen.
    "pause-2p": pause_tour(2),
    "pause-4p": pause_tour(4),
}


# Tours that start in a hosted Slayer game on this map instead of at the main menu.
IN_GAME = {"pause": "hangemhigh", "pause-2p": "hangemhigh", "pause-4p": "hangemhigh"}
# debug.pause_layout for a tour.
PAUSE_LAYOUT = {"pause-2p": 2, "pause-4p": 4}


class Console:
    """The game's script console: one line in, the reply's lines out."""

    def __init__(self, port):
        self.port = port
        self.pending = 0

    def command(self, text, until=None, timeout=5.0):
        """Send one line; return what the game prints, waiting for `until` when given."""
        deadline = time.monotonic() + 15
        while True:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=2) as connection:
                    connection.settimeout(0.1)
                    connection.sendall(text.encode("ascii") + b"\r\n")
                    reply = b""
                    end = time.monotonic() + (timeout if until else 0.3)
                    while time.monotonic() < end:
                        try:
                            chunk = connection.recv(4096)
                        except socket.timeout:
                            chunk = None
                        if chunk == b"":
                            break
                        if chunk:
                            reply += chunk
                        if until and until.encode("ascii") in reply and reply.endswith(b"\n"):
                            break
                    return reply.decode("ascii", "replace")
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("The game's script console did not answer")
                time.sleep(0.5)

    def state(self):
        """The top screen's tag name, the focused item's place in its list and its tag name."""
        for line in self.command("ui", until=" | presses ").splitlines():
            if "ui: " in line and " | focus " in line:
                screen, rest = line.split("ui: ", 1)[1].split(" | focus ", 1)
                focus, _, presses = rest.partition(" | presses ")
                index, _, name = focus.strip().partition(" ")
                self.pending = int(presses.strip() or 0)
                return screen.strip(), int(index), name.strip()
        return "", -1, ""

    def press(self, button):
        """Press a button and wait until the game has read the press and its release."""
        if "press up|down" in self.command("press " + button):
            raise RuntimeError("The game does not know the button " + button)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.state()
            if not self.pending:
                break
            time.sleep(0.1)
        time.sleep(0.15)  # the menu acts on the press in its next update

    def screen(self):
        return self.state()[0]


def prepare(folder, port, asset_quality, render_height, host=None, pause_layout=0):
    saves, data, frames = folder / "saves", folder / "data", folder / "frames"
    for directory in (saves, data / "maps", frames, folder / "screens"):
        directory.mkdir(parents=True)
    (data / "init.txt").write_text("")
    for cache in (PRIMARY / "assets/maps").iterdir():
        if cache.suffix == ".map":
            (data / "maps" / cache.name).symlink_to(cache.resolve())
    (saves / "config.toml").write_text(f'''[network]
online = false
allow_upnp = false
join_from_clipboard = false
[discord]
application_id = ""
[update]
auto = false
[display]
fullscreen = false
window_scale = 2
vsync = true
interpolation = true
high_res_hud = {"true" if asset_quality == "upres" else "false"}
render_height = {render_height}
defaults_revision = 1
[audio]
enabled = false
[debug]
telnet_console = true
telnet_console_port = {port}
ui_layout_check = true
pause_layout = {pause_layout}
screenshot_every = 15
screenshot_directory = "{frames}"
''' + (f'network_test = "host:{host}:slayer"\nnetwork_test_start = 4.0\n' if host else ""))
    return dict(os.environ, HALO_DATA_ROOT=str(data), HALO_SAVE_ROOT=str(saves), HALO_WINDOWED="1",
                HALO_VOLUME="0", HALO_NO_AUDIO="1")


def save_picture(folder, name):
    frames = sorted((folder / "frames").glob("*.bmp"))
    if not frames:
        return
    target = folder / "screens" / (name + ".png")
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "png", str(frames[-1]), "--out", str(target)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        shutil.copyfile(frames[-1], target.with_suffix(".bmp"))
    for frame in frames[:-1]:
        frame.unlink()


def run_tour(console, folder, steps):
    for kind, value in steps:
        if kind == "press":
            console.press(value)
        elif kind == "wait":
            time.sleep(float(value))
        elif kind == "focus":
            for _ in range(24):
                index = console.state()[1]
                if index == int(value):
                    break
                console.press("down" if index < int(value) else "up")
            else:
                raise RuntimeError(f"Could not move the focus to item {value}; it is at {console.state()[1:]}")
        elif kind == "expect":
            deadline = time.monotonic() + 20
            seen = ""
            while time.monotonic() < deadline:
                seen = console.screen()
                if value in seen:
                    break
                time.sleep(0.4)
            else:
                raise RuntimeError(f"Expected a screen named like '{value}', but the top screen is '{seen}'")
            time.sleep(0.6)  # the screen's opening transition
        elif kind == "shot":
            time.sleep(0.5)
            save_picture(folder, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="A new folder for pictures and the log")
    parser.add_argument("--tour", choices=sorted(TOURS) + ["all"], default="all")
    parser.add_argument("--asset-quality", choices=("upres", "original"), default="upres")
    parser.add_argument("--render-height", type=int, default=1080,
                        help="Lines to draw: 480 is the Xbox's, 0 is native. The check itself uses the "
                        "game's 480-line units, so this only sets how sharp the pictures are")
    parser.add_argument("--screen-width", default=None, help="Logical width, such as 640 for 4:3; default follows the window")
    parser.add_argument("--port", type=int, default=2390)
    parser.add_argument("--host", metavar="MAP", help="With --steps: host a Slayer game on this map first, to reach Pause")
    parser.add_argument("--pause-layout", type=int, choices=(0, 2, 4), default=0,
                        help="With --steps: show Pause as two or four players' split screen does")
    parser.add_argument("--steps", help="Instead of a tour: comma-separated press:<button>, expect:<name>, "
                        "shot:<name>, wait:<seconds>; prints the top screen after each press")
    args = parser.parse_args()
    executable, guest = BUILD / "halo", BUILD / "halo_guest.elf"
    if not executable.exists() or not guest.exists():
        sys.exit("Build the Mac game first: python3 tools/macos_build.py --build-only")
    if not (PRIMARY / "assets/maps/ui.map").exists():
        sys.exit("Game data is required in the primary checkout's assets/maps")
    output = args.output.resolve()
    if output.exists():
        sys.exit("Use a new output folder so earlier pictures are kept")
    tours = sorted(TOURS) if args.tour == "all" else [args.tour]
    if args.steps:
        tours = ["steps"]
    failures = []
    for index, tour in enumerate(tours):
        folder = output / tour
        environment = prepare(folder, args.port + index, args.asset_quality, args.render_height,
                              args.host if args.steps else IN_GAME.get(tour),
                              args.pause_layout if args.steps else PAUSE_LAYOUT.get(tour, 0))
        if args.screen_width:
            environment["HALO_SCREEN_WIDTH"] = args.screen_width
        console = Console(args.port + index)
        with open(folder / "game.log", "w") as log:
            game = subprocess.Popen([str(executable), str(guest)], env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, cwd=str(folder))
            try:
                if args.steps:
                    for step in args.steps.split(","):
                        kind, _, value = step.partition(":")
                        run_tour(console, folder, [(kind, value)])
                        if kind in ("press", "focus"):
                            print(f"  after {kind} {value}: {' | '.join(map(str, console.state()))}")
                else:
                    run_tour(console, folder, TOURS[tour])
            except RuntimeError as error:
                failures.append(f"{tour}: {error}")
            finally:
                game.terminate()
                try:
                    game.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    game.kill()
        lines = [line.split(LAYOUT_MARKER, 1)[1] for line in (folder / "game.log").read_text(errors="replace").splitlines()
                 if LAYOUT_MARKER in line]
        shutil.rmtree(folder / "frames", ignore_errors=True)
        print(f"{tour}: {len(list((folder / 'screens').iterdir()))} screens, {len(lines)} texts that do not fit")
        for line in lines:
            print("  " + line)
        failures += [f"{tour}: {line}" for line in lines]
    print(f"Pictures: {output}")
    if failures:
        print(f"FAILED: {len(failures)} problems")
        for failure in failures:
            print("  " + failure)
        sys.exit(1)
    print("Every text on the visited screens fits its box")


if __name__ == "__main__":
    main()
