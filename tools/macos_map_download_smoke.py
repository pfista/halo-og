#!/usr/bin/env python3
"""Opt-in live acceptance check for the production Mac map downloader.

Runs the checked-in HTTPS endpoint, preserves a fresh isolated library and JSON
evidence, and verifies network-disabled reuse. Never reads/writes user settings
or uploads content. This verifies download/storage only, not gameplay or rights.

Example:
    python3 tools/macos_map_download_smoke.py --data-root /path/to/NTSC/data \
        --tools-app /path/to/reviewed-helper-build.app
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "port/macos/tests/map_download_smoke.m", ROOT / "port/macos/native/HaloMapDownloads.m",
           ROOT / "port/macos/native/HaloMapPackages.m"]
CODEC_SOURCES = [ROOT / "port/linux/src/community_mapog.c", ROOT / "port/third_party/miniz/tinfl_only.c"]
CONFIG = ROOT / "port/macos/map-downloads.json"


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2, sort_keys=True)
        file.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", required=True, type=Path,
        help="Read-only original Xbox NTSC 2276 data root with exact bloodgulch/a10/ui caches required by the packages")
    parser.add_argument("--tools-app", required=True, type=Path,
        help="Reviewed helper-enabled app; its fixed native helpers/ContentTools.json are copied to the isolated probe bundle")
    parser.add_argument("--map", default="downrush", dest="map_id", help="Canonical lowercase approved community-map ID (default downrush)")
    parser.add_argument("--output", type=Path, help="New directory to preserve; existing paths are refused")
    parser.add_argument("--timeout", type=int, default=600, help="Live READY deadline in seconds, 1..600 (offline deadline up to 15 seconds)")
    parser.add_argument("--config", type=Path, default=CONFIG, help="Downloader configuration; default is checked-in public R2 settings")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("This native acceptance probe requires an Apple Silicon Mac.")
    if not re.fullmatch(r"[a-z0-9_ -]{1,31}", args.map_id):
        parser.error("--map must be a safe canonical lowercase map ID.")
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds.")
    config = args.config.expanduser().resolve()
    if not config.is_file():
        parser.error("Downloader configuration does not exist.")
    data_root = args.data_root.expanduser().resolve()
    tools_app = args.tools_app.expanduser().resolve()
    if not data_root.is_dir():
        parser.error("--data-root must be an existing directory.")
    inputs = {"ContentTools.json": tools_app / "Contents/Resources/ContentTools.json"}
    for name in ("extract", "build"):
        inputs["helper/" + name] = tools_app / "Contents/Helpers" / ("invader-" + name)
    if any(path.is_symlink() or not path.is_file() for path in inputs.values()):
        parser.error("--tools-app must contain regular fixed helpers and ContentTools.json.")
    stock_folders = [path for path in data_root.iterdir() if path.name.lower() == "maps"]
    if len(stock_folders) != 1 or stock_folders[0].is_symlink() or not stock_folders[0].is_dir():
        parser.error("--data-root must contain one real maps directory.")
    for name in ("bloodgulch", "a10", "ui"):
        matches = [path for path in stock_folders[0].iterdir() if path.name.lower() == name + ".map"]
        if len(matches) != 1 or matches[0].is_symlink() or not matches[0].is_file():
            parser.error("--data-root must contain unambiguous regular bloodgulch/a10/ui caches.")
        inputs["stock/" + name] = matches[0]
    before = {name: {"path": str(path), "sha256": sha256(path), "file_bytes": path.stat().st_size}
              for name, path in inputs.items()}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = (args.output.expanduser() if args.output else ROOT / "build/macos/tests/map-download-smoke" / stamp).absolute()
    if os.path.lexists(output):
        parser.error(f"Refusing existing output path: {output}")
    if any(output.resolve().is_relative_to(path) for path in (data_root, tools_app)):
        parser.error("Output must be outside the original data and helper app.")
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    support = output / "support"
    support.mkdir()
    contents = output / "Probe.app/Contents"
    for component in ("MacOS", "Helpers", "Resources"):
        (contents / component).mkdir(parents=True)
    (contents / "Info.plist").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>CFBundleExecutable</key><string>native-probe</string>
<key>CFBundleIdentifier</key><string>org.halo-og.tests.live-package-download</string>
<key>CFBundlePackageType</key><string>APPL</string></dict></plist>''')
    for name in ("extract", "build"):
        shutil.copy2(inputs["helper/" + name], contents / "Helpers" / ("invader-" + name))
    shutil.copy2(inputs["ContentTools.json"], contents / "Resources/ContentTools.json")
    probe = contents / "MacOS/native-probe"
    native_report = output / "native-report.json"
    objects = [output / (path.stem + ".o") for path in CODEC_SOURCES]
    codec_commands = [["clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-O2",
        "-I", str(ROOT / "port/linux/src"), "-I", str(ROOT / "port/third_party/miniz"),
        "-c", str(source), "-o", str(target)] for source, target in zip(CODEC_SOURCES, objects)]
    compile_command = [
        "clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-fobjc-arc", "-fblocks",
        "-O2", "-Wall", "-Wextra", "-Wno-deprecated-declarations", "-I", str(ROOT / "port/macos/native"),
        "-I", str(ROOT / "port/linux/src"), *(str(path) for path in SOURCES + objects),
        "-framework", "Foundation", "-o", str(probe),
    ]
    probe_command = [str(probe), str(config), str(data_root), str(support), args.map_id, str(native_report), str(args.timeout)]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    provenance = {
        "schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(), "git_revision": revision,
        "platform": platform.platform(), "map_id": args.map_id, "output_directory": str(output),
        "data_root": str(data_root), "data_source": "user-provided read-only original data",
        "tools_app": str(tools_app), "inputs_before": before,
        "config_path": str(config), "config_sha256": sha256(config),
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES + CODEC_SOURCES + [Path(__file__).resolve()]},
        "codec_compile_commands": codec_commands, "compile_command": compile_command, "probe_command": probe_command,
        "scope": "Real native HTTPS package delivery, exact-base local assembly, full output/header verification, guest READY and isolated disk-only reuse; no gameplay validation or uploads",
        "user_preferences_modified": False,
    }
    write_json(output / "provenance.json", provenance)
    print(f"Preserving smoke results in {output}", flush=True)
    status = {"schema_version": 1, "success": False, "provenance": "provenance.json", "native_report": "native-report.json"}
    try:
        with (output / "compile.log").open("x", encoding="utf-8") as log:
            for command in codec_commands:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(compile_command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        with (output / "download.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(probe_command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                timeout=args.timeout + 35, check=False)
        status["probe_exit_code"] = result.returncode
        if native_report.is_file():
            native = json.loads(native_report.read_text(encoding="utf-8"))
            status["success"] = result.returncode == 0 and native.get("success") is True
            status["result"] = native
        else:
            status["error"] = "The native probe exited without a report; inspect download.log."
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        status["error"] = str(error)
    after = {name: {"path": str(path), "sha256": sha256(path), "file_bytes": path.stat().st_size}
             for name, path in inputs.items()}
    status["inputs_unchanged"] = before == after
    status["inputs_after"] = after
    status["success"] = status["success"] and status["inputs_unchanged"]
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output / "status.json", status)
    print(f"{'PASS' if status['success'] else 'FAIL'}: {output / 'status.json'}", flush=True)
    if not status["success"]:
        print(status.get("error") or status.get("result", {}).get("error", "Inspect preserved logs."), file=sys.stderr)
    return 0 if status["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
