#!/usr/bin/env python3
"""Run native Timer Audio fixtures without game data or external network."""
from pathlib import Path
import argparse
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly download the public pack through production NSURLSession into a fresh, preserved build folder")
    args = parser.parse_args()
    output = ROOT / "build/macos/tests/timer-audio"
    output.mkdir(parents=True, exist_ok=True)
    executable = output / "timer-audio"
    subprocess.run([
        "clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-fobjc-arc", "-fblocks",
        "-O2", "-Wall", "-Wextra", "-Wno-deprecated-declarations", "-Iport/macos/native",
        "port/macos/tests/timer_audio.m", "port/macos/native/HaloTimerAudio.m",
        "-framework", "Foundation", "-o", executable,
    ], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=output) as fixtures:
        subprocess.run([executable, fixtures], check=True, timeout=30)
    if args.live:
        support = output / "live-native-save" / str(uuid.uuid4())
        support.mkdir(parents=True, exist_ok=False)
        subprocess.run([executable, support, "--live"], check=True, timeout=190)


if __name__ == "__main__":
    main()
