#!/usr/bin/env python3
"""Verify cold/warm iOS URL delivery in a disposable Simulator, without game data.

Uses SDL's real UIKit delegate, the production host event bridge and invite
writer, and the app's Info.plist template. This does not join a network game
or install anything on a physical device. Requires the existing iOS SDL build.
Open the named isolated simulator in Simulator or Device Hub, then tap Open
when iOS asks to open each invite.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from test_mobile_invites import java_method

ROOT = Path(__file__).resolve().parents[1]
SDL = ROOT / "build/android/third_party/SDL3"
LIBRARY = ROOT / "build/ios/simulator/sdl/Release-iphonesimulator/libSDL3.a"
BUNDLE_ID = "local.halo-og.invite-probe"


def run(*args, **kwargs):
    result = subprocess.run([str(arg) for arg in args], text=True,
                            capture_output=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def build_probe(output):
    if not LIBRARY.is_file():
        raise RuntimeError("Build the iOS simulator host first; its existing SDL3 library is required")
    app = output / "HaloInviteProbe.app"
    app.mkdir()
    source = (ROOT / "port/macos/host/host_sdl.c").read_text()
    event_bridge = "\n".join(java_method(source, declaration) for declaration in
                             ("int host_sdl_init(", "int host_sdl_poll_event("))
    fixture = r'''
#include "host.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list args; va_start(args, format); vfprintf(stderr, format, args); va_end(args);
    fputc('\n', stderr);
}
/*PRODUCTION_EVENT_BRIDGE*/
int main(int argc, char **argv) {
    (void)argc; (void)argv;
    @autoreleasepool {
        NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        NSString *saves = [documents stringByAppendingPathComponent:@"InviteProbe"];
        [NSFileManager.defaultManager createDirectoryAtPath:saves withIntermediateDirectories:YES attributes:nil error:NULL];
        setenv("HALO_SAVE_ROOT", saves.fileSystemRepresentation, 1);
        NSString *ready = [saves stringByAppendingPathComponent:@"pid.txt"];
        [[NSString stringWithFormat:@"%d", getpid()] writeToFile:ready atomically:YES encoding:NSUTF8StringEncoding error:NULL];
        if (!host_sdl_init(SDL_INIT_VIDEO)) { fprintf(stderr, "SDL init failed: %s\n", SDL_GetError()); return 1; }
        SDL_Window *window = SDL_CreateWindow("Halo OG invite probe", 640, 480, 0);
        if (!window) { fprintf(stderr, "SDL window failed: %s\n", SDL_GetError()); return 2; }
        for (;;) {
            SDL_Event event;
            while (host_sdl_poll_event(&event)) {}
            SDL_Delay(16);
        }
    }
}
'''.replace("/*PRODUCTION_EVENT_BRIDGE*/", event_bridge)
    test = output / "invite_probe.m"
    test.write_text(fixture)
    sdk = run("xcrun", "--sdk", "iphonesimulator", "--show-sdk-path")
    frameworks = ("CoreMedia", "CoreVideo", "CoreAudio", "AudioToolbox", "AVFoundation",
                  "CoreBluetooth", "CoreGraphics", "CoreMotion", "Foundation", "GameController",
                  "Metal", "OpenGLES", "QuartzCore", "UIKit", "CoreHaptics")
    flags = [flag for framework in frameworks for flag in ("-framework", framework)]
    run("xcrun", "--sdk", "iphonesimulator", "clang", "-target", "arm64-apple-ios26.0-simulator",
        "-isysroot", sdk, "-fobjc-arc", "-O2", "-DHALO_IOS=1", "-DHALO_MACOS=1",
        "-I" + str(SDL / "include"), "-I" + str(ROOT / "port/macos/host"),
        "-I" + str(ROOT / "port/android/include"), test,
        ROOT / "port/macos/host/host_invite.c", LIBRARY, "-lobjc", "-lm", *flags,
        "-o", app / "Halo")
    info = (ROOT / "port/ios/Info.plist.in").read_text().replace("@HALO_BUNDLE_IDENTIFIER@", BUNDLE_ID)
    info = info.replace("@HALO_OG_VERSION@", "0.0.1")
    (app / "Info.plist").write_text(info)
    run("codesign", "--force", "--sign", "-", app)
    run("codesign", "--verify", "--deep", "--strict", app)
    return app


def wait_for(path, expected=None, timeout=30):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if path.is_file():
            value = path.read_text()
            if expected is None or value == expected:
                return value
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", help="Installed available iOS simulator runtime identifier")
    parser.add_argument("--open-timeout", type=int, default=300,
                        help="Seconds allowed to accept iOS's Open in Halo OG prompt")
    args = parser.parse_args()
    os.environ.setdefault("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")
    with tempfile.TemporaryDirectory(prefix="halo-ios-invite-") as temporary:
        app = build_probe(Path(temporary))
        runtimes = json.loads(run("xcrun", "simctl", "list", "runtimes", "--json"))["runtimes"]
        available = [entry for entry in runtimes if entry["isAvailable"] and entry["name"].startswith("iOS ")]
        runtime = args.runtime or sorted(available, key=lambda entry: tuple(map(int, entry["version"].split("."))))[-1]["identifier"]
        device = run("xcrun", "simctl", "create", "Halo OG URI probe",
                     "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro", runtime)
        try:
            run("xcrun", "simctl", "boot", device)
            run("xcrun", "simctl", "bootstatus", device, "-b")
            run("xcrun", "simctl", "install", device, app)
            container = Path(run("xcrun", "simctl", "get_app_container", device, BUNDLE_ID, "data"))
            saves = container / "Documents/InviteProbe"
            first = "halo-og://join/" + "0123456789abcdef" * 4
            second = "halo-og://join/" + "fedcba9876543210" * 4
            assert len(first) == 79 and len(second) == 79
            print(f"Cold URI open in disposable simulator Halo OG URI probe ({device}); display it in Simulator or Device Hub and tap Open", flush=True)
            run("xcrun", "simctl", "openurl", device, first)
            pid = wait_for(saves / "pid.txt", timeout=args.open_timeout)
            assert wait_for(saves / "join_link.txt", first) == first
            (saves / "join_link.txt").unlink()
            print("Warm URI open; tap Open again if iOS asks", flush=True)
            run("xcrun", "simctl", "openurl", device, second)
            assert wait_for(saves / "join_link.txt", second, timeout=args.open_timeout) == second
            assert (saves / "pid.txt").read_text() == pid
            old = subprocess.run(["xcrun", "simctl", "openurl", device,
                                  "halo://join/" + "a" * 64], capture_output=True, text=True)
            assert old.returncode != 0, "The probe unexpectedly claimed the legacy halo scheme"
            print(f"iOS {runtime}: cold and warm halo-og URI delivery passed; exact 79-byte links; same PID {pid}; halo scheme unclaimed")
        except Exception:
            screenshot = ROOT / "build/ios/invite-smoke-failure.png"
            subprocess.run(["xcrun", "simctl", "io", device, "screenshot", str(screenshot)],
                           capture_output=True, timeout=30)
            print(f"Simulator failure screenshot: {screenshot}")
            logs = subprocess.run(["xcrun", "simctl", "spawn", device, "log", "show", "--last", "2m",
                                   "--style", "compact", "--predicate", 'process == "Halo" OR eventMessage CONTAINS "local.halo-og"'],
                                  capture_output=True, text=True, timeout=30)
            print(logs.stdout[-12000:] + logs.stderr[-2000:])
            raise
        finally:
            subprocess.run(["xcrun", "simctl", "shutdown", device], capture_output=True)
            subprocess.run(["xcrun", "simctl", "delete", device], check=True, capture_output=True)


if __name__ == "__main__":
    main()
