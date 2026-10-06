#!/usr/bin/env python3
"""Measure a selected Mac host/guest pair with isolated, stock game content.

Example (use a fresh output directory for each run)::

  python3 tools/macos_renderer_benchmark.py --assets /path/to/assets \
    --host /path/to/halo-metal --guest /path/to/halo_metal_guest.elf \
    --renderer metal --level chillout --output build/benchmark-attempt1 \
    --seconds 40 --render-height 0 --fps-limit 0 --vsync off

This is a bounded camera workload, not a multiplayer or campaign fidelity gate.
Native timings include diagnostic logging, completed presentation and cap waits.
ANGLE renders its original logical picture and upscales it; its fullscreen
drawable size is not an equal native-resolution rendering workload. Do not use
this tool's results to claim retail parity, all-scene performance, or 120 FPS.
"""

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import statistics
import subprocess
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
LEVELS = {"chillout": r"levels\test\chillout\chillout", "b30": r"levels\b30\b30"}
FRAME_TIMING = re.compile(r"Native timing: frame (\d+), monotonic (\d+) ns, tick (-?\d+), initialized ([01])")
DISPLAY = re.compile(
    r"Native display: ([0-9.]+) FPS, ([0-9.]+) simulation Hz, "
    r"(\d+)x(\d+) storage, (\d+)x(\d+) logical, cap (-?\d+), interpolation ([01]), ticks (-?\d+)-(-?\d+)")
HOST_METRICS = re.compile(
    r"Native Metal host metrics: (\d+) frames, (\d+) submits, (\d+) draws, (\d+) bytes; "
    r"packet-copy (\d+) us, prepare (\d+) us, encode (\d+) us, drawable-wait (\d+) us, commit (\d+) us, "
    r"completion-wait (\d+) us, gpu (\d+) us/(\d+) samples; packet-buffers (\d+), sampler-hits (\d+), "
    r"sampler-misses (\d+), sampler-allocations (\d+), sampler-cache (\d+), upload-buffers (\d+), visibility-buffers (\d+)"
    r"(?:[,;] render-passes (\d+))?")
HOST_KEYS = ("frames", "submissions", "draws", "bytes", "packet_copy_us", "prepare_us", "encode_us",
             "drawable_wait_us", "commit_us", "completion_wait_us", "gpu_us", "gpu_samples", "packet_buffers",
             "sampler_hits", "sampler_misses", "sampler_allocations", "sampler_cache", "upload_buffers",
             "visibility_buffers", "render_passes")
SUBMISSIONS = re.compile(r"Native submissions frames (\d+)-(\d+): (\d+) batches, (\d+) commands, "
                         r"(\d+) bytes, (\d+) host-submit us, largest (\d+) bytes")
FAULT = re.compile(r"Validation Error|failed assertion|ASSERTION FAILED|Assertion failed|EXCEPTION halt in|"
                   r"guest abort|SIGSEGV|signal (?:10|11)|GL error|command buffer was aborted|"
                   r"Native Metal: .* failed|Native unsupported", re.I)
SCRIPT_ERROR = re.compile(r"overflowed client buffer|not a valid|not found|syntax error|unable to parse|failed to compile", re.I)


def descriptor(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"file": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def timing_summary(times):
    if not times or any(not math.isfinite(value) or value <= 0 for value in times):
        raise ValueError("No valid warmed frame intervals")
    return {"interval_count": len(times), "elapsed_seconds": sum(times) / 1000,
            "render_fps": 1000 * len(times) / sum(times),
            "p50_ms": percentile(times, .5), "p95_ms": percentile(times, .95),
            "p99_ms": percentile(times, .99), "max_ms": max(times),
            "over_16_67_ms": sum(value > 1000 / 60 for value in times),
            "over_8_33_ms": sum(value > 1000 / 120 for value in times),
            "percentile_method": "linear sorted rank (n-1)*p", "logging_cost_included": True}


def native_summary(rows, cutoff=150):
    intervals, ticks, discarded = [], 0, 0
    for previous, current in zip(rows, rows[1:]):
        if not (previous["initialized"] and current["initialized"] and
                previous["tick"] >= cutoff and current["tick"] >= cutoff):
            continue
        if (current["frame"] != previous["frame"] + 1 or current["ns"] <= previous["ns"] or
                current["tick"] < previous["tick"]):
            discarded += 1
            continue
        intervals.append((current["ns"] - previous["ns"]) / 1e6)
        ticks += current["tick"] - previous["tick"]
    result = timing_summary(intervals)
    result.update(tick_cutoff=cutoff, observed_simulation_hz=ticks / result["elapsed_seconds"],
                  simulation_ticks=ticks, discarded_nonconsecutive_intervals=discarded,
                  scope="Consecutive completed-present intervals after original simulation tick 150; includes cap waits.")
    return result


def angle_summary(path, warmup_seconds):
    with Path(path).open() as stream:
        rows = list(csv.DictReader(stream))
    elapsed, active = 0., []
    for row in rows:
        interval = float(row["frame_ms"])
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Invalid ANGLE frame timing")
        elapsed += interval / 1000
        if elapsed >= warmup_seconds and int(row["draws"]) > 0:
            active.append(row)
    result = timing_summary([float(row["frame_ms"]) for row in active])
    result.update(warmup_seconds=warmup_seconds, observed_simulation_hz=None,
                  scope="ANGLE swap intervals after acknowledged player readiness plus five wall-clock seconds; simulation telemetry unavailable.",
                  mean_draws=statistics.mean(int(row["draws"]) for row in active),
                  mean_upload_bytes=statistics.mean(int(row["upload_bytes"]) for row in active),
                  mean_driver_draw_ms=statistics.mean(float(row["draw_ms"]) for row in active),
                  mean_swap_ms=statistics.mean(float(row["swap_ms"]) for row in active),
                  max_footprint_mb=max(float(row["footprint_mb"]) for row in rows))
    return result


def parse_log(text):
    timings, displays, metrics, submissions, errors = [], [], [], [], []
    last_timing = None
    for line in text.splitlines():
        match = FRAME_TIMING.search(line)
        if match:
            frame, ns, tick, initialized = map(int, match.groups())
            last_timing = {"frame": frame, "ns": ns, "tick": tick, "initialized": bool(initialized)}
            timings.append(last_timing)
        elif "Native timing:" in line:
            errors.append("Malformed native timing: " + line)
        match = DISPLAY.search(line)
        if match:
            fps, hz = map(float, match.group(1, 2))
            width, height, logical_width, logical_height, cap, interpolation, first_tick, last_tick = map(int, match.groups()[2:])
            displays.append(dict(render_fps=fps, simulation_hz=hz, storage_width=width, storage_height=height,
                                 logical_width=logical_width, logical_height=logical_height, frame_limit=cap,
                                 interpolation=bool(interpolation), first_tick=first_tick, last_tick=last_tick))
        elif "Native display:" in line:
            errors.append("Malformed native display: " + line)
        match = HOST_METRICS.search(line)
        if match:
            metrics.append(dict(zip(HOST_KEYS, (int(value) if value is not None else None for value in match.groups())),
                                preceding_timing=last_timing))
        elif "Native Metal host metrics:" in line:
            errors.append("Malformed native host metrics: " + line)
        match = SUBMISSIONS.search(line)
        if match:
            keys = ("first_frame", "last_frame", "batches", "commands", "bytes", "host_submit_us", "largest_batch_bytes")
            submissions.append(dict(zip(keys, map(int, match.groups()))))
    angle_sizes = [dict(logical_width=int(a), logical_height=int(b), presentation_width=int(c), presentation_height=int(d))
                   for a, b, c, d in re.findall(r"screen: (\d+)x(\d+) drawn at (\d+)x(\d+)", text)]
    return {"frame_timing": timings, "display_telemetry": displays, "host_metrics": metrics,
            "submission_blocks": submissions, "parse_errors": errors, "angle_sizes": angle_sizes,
            "drawable_sizes": [list(map(int, pair)) for pair in re.findall(r"Metal drawable (\d+)x(\d+)", text)],
            "guest_exit_records": list(map(int, re.findall(r"Game exited \((-?\d+)\)", text))),
            "faults": [line for line in text.splitlines() if FAULT.search(line)],
            "renderer_records": re.findall(r"Renderer active: ([^;\r\n]+)", text)}


def aggregate_host_metrics(rows, timings):
    # Host reporting precedes the guest's current completed-present log. Use a
    # full prior 60-frame window, conservatively excluding an extra boundary
    # frame, so even a 15 FPS run cannot put startup work in warmed totals.
    by_frame = {row["frame"]: row for row in timings}
    eligible = []
    for row in rows:
        previous = row["preceding_timing"]
        if not previous:
            continue
        window = [by_frame.get(frame) for frame in range(previous["frame"] - 60, previous["frame"] + 1)]
        if all(item and item["initialized"] and item["tick"] >= 150 for item in window):
            eligible.append(row)
    if not eligible:
        return None
    totals = {key: sum(row[key] for row in eligible) for key in HOST_KEYS
              if key != "sampler_cache" and all(row[key] is not None for row in eligible)}
    totals["blocks"] = len(eligible)
    for key in ("submissions", "draws", "bytes", "packet_copy_us", "prepare_us", "encode_us", "drawable_wait_us",
                "completion_wait_us", "gpu_us", "upload_buffers", "visibility_buffers", "render_passes"):
        if key in totals:
            totals[key + "_per_frame"] = totals[key] / totals["frames"]
    totals["scope"] = "Host 60-frame blocks with a complete preceding 60-frame window beyond original tick 150; CPU/GPU phases may overlap."
    return totals


def controlled_config(renderer, seconds, port, render_height, cap, vsync, aa, scripted_input):
    bindings = re.findall(r"^BINDING\((\w+),", (ROOT / "port/linux/src/input_bindings.def").read_text(), re.M)
    return f'''[network]
online = false
allow_upnp = false
join_from_clipboard = false
[discord]
application_id = ""
[update]
auto = false
[audio]
enabled = false
[display]
renderer = "{renderer}"
fullscreen = true
screen_width = 0
window_scale = 2
render_height = {render_height}
frame_limit = {cap}
vsync = {str(vsync).lower()}
interpolation = true
high_res_hud = false
direct_camera = false
anti_aliasing = "{aa}"
[input]
mouse_sensitivity = 1e-20
[bindings]
''' + "".join(f'{binding} = ""\n' for binding in bindings) + f'''[game]
console_log = "all"
[debug]
telnet_console = true
telnet_console_port = {port}
test_input = "{scripted_input}"
hidden_window = false
null_renderer = false
gpu_stats = true
gl_debug = false
exit_after = {float(seconds)}
screenshot_every = 0
screenshot_directory = ""
'''


def sanitized_environment(output, renderer, source=None):
    source = os.environ if source is None else source
    removed = sorted(key for key in source if key.startswith(("HALO_", "MTL_", "METAL_", "Malloc", "DYLD_"))
                     or key == "METAL_DEVICE_WRAPPER_TYPE")
    environment = {key: value for key, value in source.items() if key not in removed}
    overrides = {"HALO_DATA_ROOT": str(output / "data"), "HALO_SAVE_ROOT": str(output / "saves"),
                 "HALO_WINDOWED": "0", "HALO_GPU_STATS": "1"}
    if renderer == "angle":
        overrides["HALO_PERF_LOG"] = str(output / "frames.csv")
    environment.update(overrides)
    return environment, overrides, removed


def freeze_pair(output, host, guest):
    host, guest = Path(host).resolve(), Path(guest).resolve()
    if not host.is_file() or not guest.is_file() or not os.access(host, os.X_OK):
        raise ValueError("An existing executable host and its matching guest are required")
    frozen = output / "frozen"
    frozen.mkdir()
    # Packaged hosts depend on ../Frameworks and use ../Resources metadata.
    # Copy their existing complete app bytes, preserving signatures and rpaths.
    if host.parent.name == "MacOS" and host.parent.parent.name == "Contents":
        app = host.parent.parent.parent
        if app.suffix == ".app":
            destination = frozen / app.name
            shutil.copytree(app, destination, symlinks=True)
            frozen_host = destination / host.relative_to(app)
            dependencies = [descriptor(path) for path in (destination / "Contents/Frameworks").rglob("*")
                            if path.is_file() and not path.is_symlink()]
        else:
            raise ValueError("Packaged MacOS host must belong to an .app")
    else:
        frozen_host = frozen / host.name
        shutil.copy2(host, frozen_host)
        dependencies = []
    frozen_guest = frozen / ("guest-" + guest.name)
    shutil.copy2(guest, frozen_guest)
    result = {"source_host": descriptor(host), "source_guest": descriptor(guest),
              "host": descriptor(frozen_host), "guest": descriptor(frozen_guest), "bundled_dependencies": dependencies}
    for name in ("host", "guest"):
        if result["source_" + name]["sha256"] != result[name]["sha256"]:
            raise RuntimeError("Selected " + name + " changed while freezing")
    result["dependency_scope"] = ("Copied app Frameworks, resources and signatures" if dependencies else
                                  "Raw host retains its existing system/absolute library paths; external libraries were not frozen")
    return result


class Console:
    def __init__(self, connection, transcript):
        self.connection, self.transcript = connection, transcript
        connection.settimeout(.2)

    def send(self, expression):
        encoded = expression.encode("ascii")
        if len(encoded) >= 128 or "\n" in expression or "\r" in expression:
            raise ValueError("Console expression exceeds the game's 127-byte limit")
        self.transcript.write("\nSEND: " + expression + "\n")
        self.transcript.flush()
        self.connection.sendall(encoded + b"\r\n")

    def wait(self, marker, timeout):
        received, deadline = "", time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = self.connection.recv(65536)
            except socket.timeout:
                continue
            if not data:
                raise RuntimeError("Game console disconnected")
            chunk = data.decode("latin1")
            self.transcript.write(chunk)
            self.transcript.flush()
            received += chunk
            if SCRIPT_ERROR.search(received):
                raise RuntimeError("Game rejected the console workload")
            if marker in [line.strip() for line in received.replace("\r", "").split("\n")[:-1]]:
                return
        raise TimeoutError("Console acknowledgment missing: " + marker)

    def player_ready(self, timeout=35):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            marker = "ready_" + uuid.uuid4().hex[:12]
            self.send('(if (> (list_count (players)) 0) (print "' + marker + '"))')
            try:
                self.wait(marker, min(2, max(.1, deadline - time.monotonic())))
                return
            except TimeoutError:
                pass
        raise TimeoutError("Map did not produce a player")


def foreground_observation(pid, activate=False):
    # NSRunningApplication avoids Apple Events/System Events automation access.
    script = "ObjC.import('AppKit'); var app=$.NSRunningApplication.runningApplicationWithProcessIdentifier(" + str(pid) + ");"
    script += "var activation=" + ("app.activateWithOptions(3)" if activate else "null") + ";"
    script += "var front=$.NSWorkspace.sharedWorkspace.frontmostApplication;"
    script += ("JSON.stringify({target_active:app.active,activation_returned:activation,"
               "frontmost_pid:front.processIdentifier,frontmost_name:ObjC.unwrap(front.localizedName)});")
    result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                            text=True, capture_output=True, timeout=5)
    try:
        observed = json.loads(result.stdout.strip())
    except ValueError:
        observed = {}
    return {"active": result.returncode == 0 and observed.get("frontmost_pid") == pid,
            "target_active": observed.get("target_active"),
            "frontmost_pid": observed.get("frontmost_pid"), "frontmost_name": observed.get("frontmost_name"),
            "activation_returned": observed.get("activation_returned"),
            "command_returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def foreground(pid, activate=False):
    first = foreground_observation(pid, activate)
    attempts = [first]
    # Cocoa activation requests return before the foreground transition. Wait
    # for that transition briefly; later samples still fail if focus is lost.
    deadline = time.monotonic() + 2
    while activate and not attempts[-1]["active"] and time.monotonic() < deadline:
        time.sleep(.1)
        attempts.append(foreground_observation(pid))
    return dict(attempts[-1], activation_returned=first["activation_returned"], attempts=attempts)


def foreground_error(observation, startup=False):
    if observation.get("frontmost_name") == "loginwindow":
        return "Mac is locked or at the login screen; unlock the active user session before fullscreen benchmarking"
    return ("Benchmark game could not become the foreground application" if startup else
            "Benchmark game lost foreground; timings are not valid")


def record_foreground_check(process, started, samples):
    observed = foreground(process.pid)
    # The application can exit naturally while osascript is observing it. An
    # application that has already quit is no longer a lost-focus game sample.
    if process.poll() is not None:
        return False
    samples.append(dict(seconds=time.monotonic() - started, **observed))
    if not observed["active"]:
        raise RuntimeError(foreground_error(observed))
    return True


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    assets = args.assets.resolve()
    record = {"schema_version": 1, "kind": "scoped_macos_renderer_benchmark", "passed": False,
              "renderer": args.renderer, "level": args.level, "duration_seconds": args.seconds,
              "workload": "Original stock map, isolated offline single player, " + args.test_input + " scripted controller",
              "requested_simulation_hz": 30, "retail_fidelity_gate": False, "equal_renderer_workload_gate": False,
              "performance_improvement_gate": False, "foreground_samples": []}
    process, connection, started = None, None, None
    try:
        for level in ("ui", args.level):
            if not (assets / "maps" / (level + ".map")).is_file():
                raise ValueError("Missing original stock map: " + level)
        (output / "data").mkdir()
        (output / "saves").mkdir()
        for name in ("maps", "sounds"):
            if (assets / name).is_dir():
                (output / "data" / name).symlink_to(assets / name, target_is_directory=True)
        record["assets"] = {"root": str(assets), "maps": [descriptor(assets / "maps" / (level + ".map"))
                                                               for level in ("ui", args.level)]}
        init = ("game_variant slayer\n" if args.level == "chillout" else "game_difficulty_set normal\n")
        init += "map_name " + LEVELS[args.level] + "\n"
        (output / "data/init.txt").write_text(init)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        config = controlled_config(args.renderer, args.seconds, port, args.render_height, args.fps_limit,
                                   args.vsync == "on", args.anti_aliasing, args.test_input)
        (output / "initial-config.toml").write_text(config)
        (output / "saves/config.toml").write_text(config)
        record["pair"] = freeze_pair(output, args.host, args.guest)
        environment, overrides, removed = sanitized_environment(output, args.renderer)
        command = [record["pair"]["host"]["file"], record["pair"]["guest"]["file"]]
        plan = {"command": command, "cwd": str(output), "environment_override_key_names": sorted(overrides),
                "environment_overrides": overrides, "removed_environment_key_names": removed,
                "initial_config": descriptor(output / "initial-config.toml"), "init": descriptor(output / "data/init.txt"),
                "settings": tomllib.loads(config), "binary_pair": record["pair"]}
        (output / "launch-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
        record["launch_plan"] = descriptor(output / "launch-plan.json")
        started = time.monotonic()
        with (output / "launch.log").open("w") as log, (output / "console.log").open("w") as transcript:
            process = subprocess.Popen(command, cwd=output, env=environment, stdout=log, stderr=subprocess.STDOUT)
            deadline = started + min(40, args.seconds - 8)
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    connection = socket.create_connection(("127.0.0.1", port), .5)
                    break
                except OSError:
                    time.sleep(.1)
            if connection is None:
                raise RuntimeError("Game console did not start")
            console = Console(connection, transcript)
            console.player_ready(timeout=max(1, deadline - time.monotonic()))
            record["player_ready_seconds"] = time.monotonic() - started
            activation = foreground(process.pid, activate=True)
            record["foreground_samples"].append(dict(seconds=time.monotonic() - started, **activation))
            if not activation["active"]:
                raise RuntimeError(foreground_error(activation, startup=True))
            next_check = time.monotonic() + 3
            while process.poll() is None and time.monotonic() < started + args.seconds + 15:
                if time.monotonic() >= next_check:
                    if not record_foreground_check(process, started, record["foreground_samples"]):
                        break
                    next_check = time.monotonic() + 3
                time.sleep(.1)
            process.wait(timeout=3)
        record["actual_host_returncode"] = process.returncode
        record["elapsed_seconds"] = time.monotonic() - started
        text = (output / "launch.log").read_text(errors="replace")
        if (output / "data/debug.txt").is_file():
            text += "\n" + (output / "data/debug.txt").read_text(errors="replace")
        parsed = parse_log(text)
        record.update(parsed)
        record["saved_config"] = descriptor(output / "saves/config.toml")
        actual = tomllib.loads((output / "saves/config.toml").read_text())
        record["actual_display_settings"] = actual.get("display", {})
        for key, value in plan["settings"]["display"].items():
            if actual.get("display", {}).get(key) != value:
                raise ValueError("Game changed requested display setting: " + key)
        expected_renderer = "Native Metal" if args.renderer == "metal" else "ANGLE"
        if parsed["renderer_records"] != [expected_renderer]:
            raise RuntimeError("Observed renderer does not match selected host/guest pair")
        if process.returncode != 0 or parsed["guest_exit_records"] != [0] or parsed["faults"] or parsed["parse_errors"]:
            raise RuntimeError("Game failed, lacked a clean guest exit, or reported rendering/runtime faults")
        if record["elapsed_seconds"] < args.seconds - 3:
            raise RuntimeError("Game exited before the requested duration")
        if args.renderer == "metal":
            record["timing_summary"] = native_summary(parsed["frame_timing"])
            record["host_metrics_summary"] = aggregate_host_metrics(parsed["host_metrics"], parsed["frame_timing"])
            if not parsed["display_telemetry"] or not parsed["host_metrics"]:
                raise RuntimeError("Native display or host telemetry missing")
        else:
            record["timing_summary"] = angle_summary(output / "frames.csv", record["player_ready_seconds"] + 5)
            if not parsed["angle_sizes"]:
                raise RuntimeError("ANGLE logical/presentation resolution missing")
        if record["timing_summary"]["elapsed_seconds"] < 5:
            raise RuntimeError("Insufficient warmed gameplay intervals")
        record["passed"] = True
    except (OSError, RuntimeError, TimeoutError, ValueError, subprocess.SubprocessError) as error:
        record["error"] = str(error)
    finally:
        if connection:
            connection.close()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process:
            record["actual_host_returncode"] = process.returncode
        if started is not None:
            record["elapsed_seconds"] = time.monotonic() - started
        if (output / "launch.log").is_file():
            record["launch_log"] = descriptor(output / "launch.log")
        (output / "benchmark.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--assets", type=Path, required=True, help="Existing original Xbox assets root (never changed)")
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--guest", type=Path, required=True)
    parser.add_argument("--renderer", choices=("angle", "metal"), required=True)
    parser.add_argument("--level", choices=LEVELS, default="chillout")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--render-height", type=int, choices=(0, 480, 720, 1080, 1440, 2160), default=0)
    parser.add_argument("--fps-limit", type=int, choices=(0, 30, 60, 120), default=0)
    parser.add_argument("--vsync", choices=("on", "off"), default="off")
    parser.add_argument("--anti-aliasing", choices=("off", "fxaa"), default="fxaa")
    parser.add_argument("--test-input", choices=("look:0", "bot:0"), default="look:0")
    args = parser.parse_args()
    if not 20 <= args.seconds <= 580:
        parser.error("Use 20..580 seconds for a bounded, warmed run")
    if args.output.exists():
        parser.error("Use a fresh output directory to preserve previous evidence")
    result = run(args)
    print(json.dumps({key: result.get(key) for key in ("passed", "error", "renderer", "level", "elapsed_seconds",
                                                      "actual_host_returncode", "timing_summary", "host_metrics_summary")}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
