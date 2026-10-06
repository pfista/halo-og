#!/usr/bin/env python3
"""Compile read-only Mac release checks and the shared parser with authored HTTPS fixtures."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "build/macos/tests/release-updates"
    output.mkdir(parents=True, exist_ok=True)
    parser = output / "release-discovery.o"
    executable = output / "release-updates"
    subprocess.run([
        "clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-O2", "-std=c99",
        "-Wall", "-Wextra", "-Werror", "-Iport/linux/src", "-c",
        "port/linux/src/release_discovery.c", "-o", parser,
    ], cwd=ROOT, check=True)
    subprocess.run([
        "clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-fobjc-arc", "-fblocks",
        "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations",
        "-Iport/macos/native", "-Iport/linux/src", "port/macos/tests/release_updates.m",
        "port/macos/native/HaloReleaseUpdates.m", parser, "-framework", "Foundation", "-o", executable,
    ], cwd=ROOT, check=True)
    subprocess.run([executable], check=True, timeout=30)


if __name__ == "__main__":
    main()
