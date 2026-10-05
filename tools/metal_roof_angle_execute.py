#!/usr/bin/env python3
"""Test-only original ANGLE roof capture using an explicitly frozen preparation."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def verify(bindings):
    for path, expected in bindings.items():
        if sha(path) != expected:
            raise ValueError("Frozen diagnostic input changed: " + path)


def prepare(prepared):
    out = prepared.resolve()
    record = read(out / "prepared.json")
    if (out / "execution-plan.json").exists():
        raise ValueError("Execution plan already exists")
    verify(record["original_bindings"]); verify(record["retained_object_bindings"]); verify(record["artifact_bindings"])
    primary = Path(record["fresh_host"]["builder"]).parents[1]
    benchmark = primary / "tools/macos_benchmark.py"
    dependencies = {str(Path(__file__).resolve()): sha(__file__), str(benchmark): sha(benchmark),
                    str(primary / "assets/maps/ui.map"): sha(primary / "assets/maps/ui.map")}
    for path in (Path("/opt/homebrew/opt/sdl3/lib/libSDL3.0.dylib"),
                 primary / "build/macos/sparkle/Sparkle.framework/Sparkle"):
        dependencies[str(path)] = sha(path)
    write(out / "execution-plan.json", {"kind": "roof_original_angle_execution_plan", "complete": True, "gpu_executed": False,
        "prepared": str(out / "prepared.json"), "prepared_sha256": sha(out / "prepared.json"), "additional_bindings": dependencies,
        "console_helper": str(benchmark), "cases": [p["name"] for p in record["runtime_plans"]],
        "limits": ["Not executed", "Current-cached original ANGLE reference, distinct from historical frame420",
                   "Exact camera and projection evidence is the per-draw raw snapshot, not requested camera text",
                   "No production fix, image/depth parity, original hardware or full-game fidelity claim"]})
    print(json.dumps({"plan": str(out / "execution-plan.json"), "sha256": sha(out / "execution-plan.json"), "gpu_executed": False}))


def blob_refs(value):
    if isinstance(value, dict):
        if "file" in value and "bytes" in value:
            yield value
        for child in value.values():
            yield from blob_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from blob_refs(child)


def capture(plan_path, case):
    plan = read(plan_path)
    if sha(plan["prepared"]) != plan["prepared_sha256"]:
        raise ValueError("Prepared reference changed")
    record = read(plan["prepared"])
    verify(plan["additional_bindings"]); verify(record["original_bindings"])
    verify(record["retained_object_bindings"]); verify(record["artifact_bindings"])
    selected = next(p for p in record["runtime_plans"] if p["name"] == case)
    folder = Path(selected["cwd"])
    if (folder / "execution.json").exists() or (folder / "halo.log").exists():
        raise ValueError("Execution already attempted; preserve it")
    spec = importlib.util.spec_from_file_location("original_roof_console", plan["console_helper"])
    benchmark = importlib.util.module_from_spec(spec); spec.loader.exec_module(benchmark)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HALO_")}
    env.update(selected["environment_overrides"])
    env["MTL_DEBUG_LAYER"] = "1"
    execution = {"kind": "roof_original_angle_execution", "complete": False, "plan_sha256": sha(plan_path),
        "case": selected, "environment_overrides": {**selected["environment_overrides"], "MTL_DEBUG_LAYER": "1"},
        "gpu_executed": True, "production_edits": False}
    write(folder / "execution.json", execution)
    process = None
    try:
        start = time.monotonic()
        with (folder / "halo.log").open("w") as log:
            process = subprocess.Popen(selected["command"], cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 10
            connection = None
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    connection = socket.create_connection(("127.0.0.1", selected["console_port"]), timeout=.5)
                    break
                except OSError:
                    time.sleep(.1)
            if connection is None:
                raise ValueError("Original diagnostic console unavailable")
            with connection, (folder / "console.log").open("w") as transcript:
                console = benchmark.Console(connection, transcript)
                console.player_ready(timeout=15)
                execution["player_ready_acknowledged_seconds"] = time.monotonic() - start
                for command in selected["console_commands_after_player_ready"]:
                    console.command(command)
                execution["camera_load_acknowledged_seconds"] = time.monotonic() - start
                write(folder / "execution.json", execution)
                process.wait(timeout=45)
        execution["exit_code"] = process.returncode
        execution["wall_seconds"] = time.monotonic() - start
        if process.returncode != 0:
            raise ValueError("Original reference host/guest exited with failure")
        frame_dir = folder / "saves/metal-frames" / ("frame" + str(selected["trace_frame"]))
        status = read(frame_dir / "status.json")
        if not status["complete"] or status["frame"] != selected["trace_frame"]:
            raise ValueError("Selected original frame incomplete")
        log = (folder / "halo.log").read_text()
        if benchmark.FAULT.search(log):
            raise ValueError("Original diagnostic reports an API/guest failure")
        begin = re.search(r"METAL_FRAME_CAPTURE begin " + str(selected["trace_frame"]), log)
        if not begin:
            raise ValueError("Actual capture frame was not reported")
        draws = sorted(frame_dir.glob("draw-*.json"))
        if len(draws) != status["draw_count"]:
            raise ValueError("Captured original draw count mismatch")
        cameras = []
        captured_payloads = {}
        for filename in draws:
            draw = read(filename)
            if not draw["complete"] or draw["frame"] != selected["trace_frame"]:
                raise ValueError("Original draw incomplete/frame mismatch")
            for ref in blob_refs(draw):
                path = frame_dir / ref["file"]
                if not path.resolve().is_relative_to(frame_dir.resolve()) or path.stat().st_size != ref["bytes"]:
                    raise ValueError("Invalid original captured blob extent/path")
                captured_payloads[str(path)] = sha(path)
            state = draw["render_camera_diagnostic"]
            if state["long_bytes"] != 4 or state["float_bytes"] != 4:
                raise ValueError("Actual camera capture is not original ILP32 float32")
            raw = (frame_dir / state["camera_blob"]["file"]).read_bytes()
            frustum = (frame_dir / state["frustum_blob"]["file"]).read_bytes()
            if len(raw) != state["camera_size"] or len(frustum) != state["frustum_size"]:
                raise ValueError("Raw camera/frustum extent disagrees with compiled layout")
            offsets = state["camera_offsets"]
            values = {name: list(struct.unpack_from("<3f", raw, offsets[name])) for name in ("position", "forward", "up")}
            values.update({name: struct.unpack_from("<f", raw, offsets[name])[0]
                           for name in ("vertical_field_of_view", "z_near", "z_far")})
            if not all(math.isfinite(v) for name in ("position", "forward", "up") for v in values[name]):
                raise ValueError("Nonfinite actual rendered camera")
            values.update({"draw": filename.name, "use": draw["use"], "viewport": draw["viewport"],
                "camera_sha256": sha(frame_dir / state["camera_blob"]["file"]),
                "frustum_sha256": sha(frame_dir / state["frustum_blob"]["file"]), "actual_compiled_layout": state,
                "raw_constants_sha256": sha(frame_dir / draw["vertex_constants"]["file"]),
                "raw_viewport_sha256": sha(frame_dir / draw["viewport_bits"]["file"])})
            cameras.append(values)
        bmp = folder / "screenshots" / ("frame%05d.bmp" % selected["trace_frame"])
        if not bmp.is_file():
            raise ValueError("No screenshot for the exact captured frame")
        png = folder / "selected-frame.png"
        subprocess.run(["/usr/bin/sips", "-s", "format", "png", str(bmp), "--out", str(png)], check=True, capture_output=True)
        write(folder / "rendered-camera-records.json", {"kind": "actual_original_per_draw_camera_records", "records": cameras})
        verify(plan["additional_bindings"]); verify(record["original_bindings"]); verify(record["retained_object_bindings"]); verify(record["artifact_bindings"])
        result = {"kind": "roof_original_angle_camera_capture", "complete": True, "scope": record["scope"],
            "plan_sha256": sha(plan_path), "prepared_sha256": plan["prepared_sha256"], "actual_process_exit": process.returncode,
            "status": status, "camera_records": str(folder / "rendered-camera-records.json"),
            "captured_payload_bindings": captured_payloads,
            "output_bindings": {str(p): sha(p) for p in folder.rglob("*") if p.is_file() and p.name != "execution.json"},
            "historical_frame420_rebound": False, "native_or_original_hardware_parity": False, "clipping_fix_proven": False,
            "limits": ["Current-cached original ANGLE reference, not historical420", "Captured draw camera is authoritative; requested pose is not a guaranteed exact match",
                       "Synthetic roof camera; exact unseen user camera remains unknown", "Image review and camera/geometry/depth pairing remain separate work"]}
        write(folder / "result.json", result)
        execution["complete"] = True; execution["result_sha256"] = sha(folder / "result.json")
    except Exception as error:
        execution["error"] = str(error)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        if process is not None:
            execution["exit_code"] = process.returncode
        raise
    finally:
        write(folder / "execution.json", execution)
    print(json.dumps({"result": str(folder / "result.json"), "sha256": sha(folder / "result.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    p = actions.add_parser("prepare"); p.add_argument("--prepared", type=Path, required=True)
    p = actions.add_parser("execute"); p.add_argument("--plan", type=Path, required=True); p.add_argument("--case", required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.prepared)
    else:
        capture(args.plan, args.case)
