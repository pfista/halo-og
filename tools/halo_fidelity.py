#!/usr/bin/env python3
"""Build isolated historical/current engines and compare a live 30 Hz spin test.

No app is packaged or installed. No personal saves, configuration, maps, or source
files are modified. The injected probe enters at the packed-action boundary.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import fcntl
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "tools/fidelity"
REFERENCE = "f538f7f6692f7ce42c95c94a3aff48ddb0e77fb8"
SOURCE_DIRS = {"port", "source", "tools", "pgo", "config", "libs"}
MEASUREMENT_FIELDS = ("press_to_shot_ms", "action_age_ms", "shot_minus_drawn_camera_deg",
                      "shot_minus_press_camera_deg", "shot_minus_press_action_deg",
                      "press_to_shot_ticks", "action_age_ticks", "shot_camera_residual_deg")
sys.path.insert(0, str(ROOT))
from tools.fidelity.local_broker import LocalBroker


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def source_allowed(name):
    p = Path(name)
    return bool(p.parts) and not p.is_absolute() and ".." not in p.parts and (
        p.parts[0] in SOURCE_DIRS or name == "configure.py") and not any(
        x.startswith(".env") or x in ("__pycache__", ".git") for x in p.parts)


def snapshot(destination, revision):
    destination.mkdir(parents=True)
    if revision == "working":
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        for name in sorted(set(names)):
            if not source_allowed(name):
                continue
            source = ROOT / name
            if not source.is_file():
                continue
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        commit = git("rev-parse", "HEAD")
    else:
        commit = git("rev-parse", "--verify", revision + "^{commit}")
        with tempfile.TemporaryFile() as archive:
            subprocess.run(["git", "archive", commit], cwd=ROOT, stdout=archive, check=True)
            archive.seek(0)
            with tarfile.open(fileobj=archive) as package:
                for member in package.getmembers():
                    if not source_allowed(member.name) or not member.isfile():
                        continue
                    path = destination / member.name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(package.extractfile(member).read())
                    path.chmod(member.mode)
    files = {str(p.relative_to(destination)): digest(p) for p in sorted(destination.rglob("*")) if p.is_file()}
    return {"revision": revision, "commit": commit, "files": files,
            "source_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def replace_once(path, before, after):
    text = path.read_text()
    if text.count(before) != 1:
        raise ValueError(f"Instrumentation anchor drift in {path.name}: {before[:90]!r}")
    path.write_text(text.replace(before, after))


def instrument(tree, legacy):
    source = tree / "source"
    (source / "game/fidelity_probe.h").write_bytes((PROBES / "probe.h").read_bytes())
    files = [source / path for path in ("game/player_control.c", "game/players.c", "items/weapons.c", "game/game_engine.c")]
    files.append(tree / "port/linux/game/render_interpolation.c")
    for path in files:
        path.write_text('#include "game/fidelity_probe.h"\n' + path.read_text())
    control = source / "game/player_control.c"
    replace_once(control, "\t\tupdate_client_queue(&action);", """\t\tfidelity_input(&action, local_player_index);
        player->desired_angles = action.desired_facing;
        player->control_flags = action.control_flags;
        player->primary_trigger = action.primary_trigger;
        player->throttle = action.throttle;
\t\tupdate_client_queue(&action);""")
    mode = "(!network_game_distributed())" if legacy else "0"
    control.write_text(control.read_text() + '\n#include "networking/network_game_globals.h"\n' +
                       f"#define FIDELITY_LEGACY {mode}\n" + (PROBES / "probe.c").read_text())
    replace_once(source / "game/players.c", "\t\t\taction = &actions[action_index];",
                 "\t\t\taction = &actions[action_index];\n\t\t\tif (player->local_player_index == 0) fidelity_consumed(action, iterator.datum_index);")
    weapon = source / "items/weapons.c"
    ray = "\t\t\tunit_adjust_projectile_ray(owner_object_index, &origin, &forward, &velocity, adjust_origin, use_aiming_vector);"
    def record(stage, vector="forward", target="NONE", origin="origin"):
        return (f"\n                fidelity_ray('{stage}', weapon->definition_index, owner_object_index, {target}, "
                f"{origin}.x, {origin}.y, {origin}.z, {vector}.i, {vector}.j, {vector}.k);")
    replace_once(weapon, ray, ray + record("b"))
    aimed = "\t\t\t\ttarget_object_index= player_aim_projectile(player_index, &origin, &forward);"
    replace_once(weapon, aimed, aimed + record("s", target="target_object_index"))
    created = "\t\t\t\tprojectile_object_index= object_new(&data);"
    replace_once(weapon, created, created + record("f", "data.forward", "projectile_object_index", "data.position"))
    engine = source / "game/game_engine.c"
    replace_once(engine, "void game_engine_postspawn_player_update(\n",
                 "static void fidelity_original_postspawn(\n")
    engine.write_text(engine.read_text() + """
void game_engine_postspawn_player_update(long player_index)
{
    fidelity_original_postspawn(player_index);
    fidelity_loadout(player_index);
}
""")
    camera = files[-1]
    replace_once(camera, "struct observer_result const *render_interpolation_camera(\n",
                 "static struct observer_result const *fidelity_original_camera(\n")
    camera.write_text(camera.read_text() + """
struct observer_result const *render_interpolation_camera(
    short local_player_index, struct observer_result const *observer)
    {
        struct observer_result const *result = fidelity_original_camera(local_player_index, observer);
        fidelity_camera(local_player_index, result);
        return result;
    }
""")
    # Keep diagnostic sockets separate from the user's normal game and other
    # native smoke tests. Both endpoints still run the original transport code.
    protocol = source / "networking/network_game_protocol.h"
    replace_once(protocol, "NETWORK_GAME_SERVER_PORT = 0x141E", "NETWORK_GAME_SERVER_PORT = 56150")
    replace_once(protocol, "NETWORK_GAME_CLIENT_PORT = 0x141F", "NETWORK_GAME_CLIENT_PORT = 56151")
    files.append(protocol)
    p2p = tree / "port/linux/src/p2p.c"
    replace_once(p2p, "const char *p2p_take_clipboard_text(void)\n{",
                 'const char *p2p_take_clipboard_text(void)\n{\n    if (config_string("debug.network_test")[0]) return NULL;')
    files.append(p2p)
    if legacy:
        # Mac socket emulation can return WOULD_BLOCK while the asynchronous
        # connection is pending. Preserve the old in-match queues and packets;
        # only keep the pre-match connect wait alive until its existing timeout.
        endpoint = source / "bungie_net/network/transport_endpoint_winsock.c"
        replace_once(endpoint, "while (error == WSAEINPROGRESS);",
                     "while (error == WSAEINPROGRESS || error == WSAEWOULDBLOCK);")
        files.append(endpoint)
    return {str(path.relative_to(tree)): digest(path) for path in files}


def build_one(out, revision, legacy, jobs):
    tree = out / "source"
    manifest = snapshot(tree, revision)
    manifest.update(schema=1, legacy_lockstep=legacy, scope="native historical reconstruction; not retail Xbox hardware",
                    diagnostic_transport_ports=[56150, 56151],
                    diagnostic_fixture="stock pistol, fixed Blood Gulch positions, full-turn firing warmup, starting ammo reset before capture",
                    portability_patches=["pre-match connect wait also accepts WOULD_BLOCK"] if legacy else [],
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    probe_files={p.name: digest(p) for p in sorted(PROBES.glob("probe.*"))})
    manifest["instrumented_files"] = instrument(tree, legacy)
    # Dependencies are already installed by the normal Mac setup. ANGLE is copied
    # because build_host refreshes a companion symlink inside its framework.
    for name in ("build/macos/toolchain", "build/macos/angle/dist"):
        source = ROOT / name
        if not source.is_dir():
            raise RuntimeError(f"Missing {source}; run the repository's normal Mac setup first")
        shutil.copytree(source, tree / name, symlinks=True)
    for name in ("build/android/third_party/musl-1.2.5", "build/android/third_party/SDL3", "build/macos/sparkle"):
        source = ROOT / name
        if source.is_dir():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source.resolve(), target_is_directory=True)
    llvm = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm@22/bin"))
    manifest["compiler"] = subprocess.check_output([llvm / "clang", "--version"], text=True).strip()
    save(out / "manifest.json", manifest)
    commands = [
        [sys.executable, "-c", "from tools.macos_build import build_plugin; build_plugin()"],
        [sys.executable, "configure.py", "--macos", "--android-guest-llvm-bin", "build/macos/toolchain/bin",
         "--android-guest-gl-include", "build/macos/toolchain/gl", "--pgo", "off"],
        [shutil.which("ninja") or str(ROOT / "build/macos/toolchain/venv/bin/ninja"), "-j", str(jobs), "macos_guest"],
        [sys.executable, "-c", "from tools.macos_build import build_host; build_host()"],
    ]
    with (out / "build.log").open("w") as log:
        for command in commands:
            print(f"{out.name}: {command[1]}", flush=True)
            log.write(json.dumps(command) + "\n"); log.flush()
            subprocess.run(command, cwd=tree, env=dict(os.environ, HALO_MACOS_LLVM_BIN=str(llvm)),
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    manifest["binaries"] = {name: digest(tree / "build/macos" / name) for name in ("halo", "halo_guest.elf")}
    save(out / "manifest.json", manifest)


def run_one(build, output, shots, rate, phase, tap, interpolation, role="host", transport="auto"):
    lock_path = ROOT / "build/fidelity/.run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another fidelity capture is running; fixed diagnostic ports require sequential runs") from None
        return _run_one(build, output, shots, rate, phase, tap, interpolation, role, transport)


def run_configuration(*, address, other_address, transport, broker_port, legacy,
                      endpoint, role, shots, rate, phase, tap, interpolation, duration):
    """Keep every diagnostic run private even as normal game defaults change."""
    config = f'''[network]
address = "{address}"
broadcast = "{other_address if transport == 'lan' else address}"
online = {str(transport == 'local-relay').lower()}
allow_upnp = false
join_from_clipboard = false
directory_url = ""
public_games = false
signalling_brokers = "{'127.0.0.1:' + str(broker_port) if transport == 'local-relay' else ''}"
stun_servers = ""
'''
    if legacy:
        config += 'netcode = "lockstep"\n'
    scenario = f"fidelity:{shots}:{rate}:{phase}:{tap}" if endpoint == role else "fidelity_idle"
    return config + f'''[discord]
application_id = ""
[update]
auto = false
[community_maps]
auto_download = false
[display]
interpolation = {str(interpolation).lower()}
direct_camera = false
high_res_hud = false
vsync = true
[debug]
hidden_window = true
network_test = "{'host:bloodgulch:slayer' if endpoint == 'host' else 'join'}"
network_test_start = 20.0
network_test_shoot = 0.0
network_test_kill = 0.0
test_input = "{scenario}"
exit_after = {duration}.0
'''


def _run_one(build, output, shots, rate, phase, tap, interpolation, role, transport):
    manifest = json.loads((build / "manifest.json").read_text())
    if not manifest.get("binaries"):
        raise ValueError("Build did not finish; no binary hashes")
    tree = build / "source"
    for name, expected in manifest["binaries"].items():
        if digest(tree / "build/macos" / name) != expected:
            raise ValueError(f"Binary changed after build: {name}")
    output.mkdir(parents=True, exist_ok=False)
    maps = {}
    # Xbox v5 caches contain their own assets; PC's shared bitmaps/sounds caches
    # are not prerequisites and must not be substituted for Xbox game data.
    for name in ("bloodgulch.map", "ui.map"):
        path = ROOT / "assets/maps" / name
        if not path.exists():
            raise ValueError(f"Missing independently supplied stock map: {path}")
    # The historical lobby enumerates other multiplayer maps while selecting
    # its initial playlist, before network_test applies the requested map.
    for path in sorted((ROOT / "assets/maps").glob("*.map")):
        name = path.name
        maps[name] = digest(path)
    duration = 55 + 2 + ((shots - 1) // 12) * 14 + (shots - 1) % 12 + 5
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(("192.0.2.1", 9))  # Choose an interface without sending a packet.
        host_address = route.getsockname()[0]
    if host_address.startswith("127."):
        raise ValueError("The two-instance fixture needs an active LAN IPv4 interface")
    listing = subprocess.run(["/sbin/ifconfig"], text=True, capture_output=True, check=False)
    addresses = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)\b", listing.stdout)
    client_address = next((a for a in addresses if a != host_address and not ipaddress.ip_address(a).is_loopback), None)
    if transport == "auto":
        reachable = False
        if client_address:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as left, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as right:
                try:
                    left.bind((host_address, 0)); right.bind((client_address, 0))
                    left.settimeout(0.5); right.settimeout(0.5)
                    for sender, receiver in ((left, right), (right, left)):
                        sender.sendto(b"halo-fidelity-local-probe", receiver.getsockname())
                        if receiver.recvfrom(64)[0] != b"halo-fidelity-local-probe":
                            raise ValueError("Unexpected local probe response")
                    reachable = True
                except (OSError, ValueError):
                    pass
        transport = "lan" if reachable else "local-relay"
    if transport == "lan" and not client_address:
        raise ValueError("LAN needs a second configured non-loopback IPv4 address; use --transport local-relay")
    if transport == "local-relay":
        client_address = "127.0.0.1"
    broker = LocalBroker() if transport == "local-relay" else None
    processes, streams, metadata = {}, [], {}
    try:
        folders = {name: output if name == role else output / "peer" for name in ("host", "client")}
        environments = {}
        for endpoint, folder in folders.items():
            folder.mkdir(parents=True, exist_ok=True)
            saves, data = folder / "saves", folder / "data"
            saves.mkdir(); (data / "maps").mkdir(parents=True)
            for name in maps:
                (data / "maps" / name).symlink_to((ROOT / "assets/maps" / name).resolve())
            address = host_address if endpoint == "host" else client_address
            other_address = client_address if endpoint == "host" else host_address
            config = run_configuration(address=address, other_address=other_address, transport=transport,
                broker_port=broker.port if broker else None, legacy=manifest["legacy_lockstep"],
                endpoint=endpoint, role=role, shots=shots, rate=rate, phase=phase, tap=tap,
                interpolation=interpolation, duration=duration)
            (saves / "config.toml").write_text(config)
            (folder / "requested-config.toml").write_text(config)
            # Inherited HALO_* overrides can silently defeat TOML. Keep toolchain
            # overrides out of runtime and use established isolation keys only.
            env = {k: v for k, v in os.environ.items() if not k.startswith("HALO_")}
            env.update(HALO_DATA_ROOT=str(data), HALO_SAVE_ROOT=str(saves), HALO_WINDOWED="1",
                       HALO_SCREEN_WIDTH="640", HALO_WINDOW_SCALE="1", HALO_VOLUME="0", HALO_NO_AUDIO="1")
            environments[endpoint] = env
        saves = output / "saves"
        metadata = {"build": str(build), "build_manifest_sha256": digest(build / "manifest.json"),
                    "map_sha256": maps, "requested_config_sha256": digest(saves / "config.toml"),
                    "scenario": {"shots": shots, "rate_dps": rate, "phase_ms": phase, "tap_ms": tap,
                                 "interpolation": interpolation, "role": role, "transport": transport},
                    "scope": f"two real native instances on one Mac, {transport}, packed-action injection, stock tags"}
        save(output / "run.json", metadata)
        command = [str(tree / "build/macos/halo"), str(tree / "build/macos/halo_guest.elf")]
        started = time.monotonic()
        for endpoint in ("host", "client"):
            endpoint_command = list(command)
            if endpoint == "client" and transport == "local-relay":
                deadline = time.monotonic() + 30
                invite = None
                while time.monotonic() < deadline and processes["host"].poll() is None:
                    host_log = (folders["host"] / "game.log").read_text(errors="replace")
                    # The pinned historical invite has 44 hex digits; current
                    # native invites have 64. Accept exactly the known formats.
                    match = re.search(r"halo://join/(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{44})(?![0-9a-fA-F])", host_log)
                    if match:
                        invite = match[0]
                        break
                    time.sleep(0.2)
                if not invite:
                    raise RuntimeError("Host did not produce an invite; inspect its game.log")
                endpoint_command.append(invite)
            stream = (folders[endpoint] / "game.log").open("w")
            streams.append(stream)
            processes[endpoint] = subprocess.Popen(endpoint_command, cwd=tree, env=environments[endpoint],
                                                    stdout=stream, stderr=subprocess.STDOUT)
        while any(p.poll() is None for p in processes.values()) and time.monotonic() - started < duration + 40:
            time.sleep(0.2)
        metadata["exit_code"] = processes[role].poll()
        metadata["peer_exit_code"] = processes["client" if role == "host" else "host"].poll()
        metadata["timed_out"] = any(p.poll() is None for p in processes.values())
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        for stream in streams:
            stream.close()
        if broker:
            broker.close()
            metadata["local_signalling"] = broker.stats
            save(output / "local-signalling.json", broker.stats)
        if "build" in metadata:
            # Preserve evidence even on setup exceptions or Ctrl-C. The config
            # manager adds defaults, so retain requested and effective versions.
            metadata.setdefault("exit_code", processes[role].poll() if role in processes else None)
            peer = "client" if role == "host" else "host"
            metadata.setdefault("peer_exit_code", processes[peer].poll() if peer in processes else None)
            metadata["config_sha256"] = digest(saves / "config.toml")
            save(output / "run.json", metadata)
    result = analyze(output)
    save(output / "analysis.json", result)
    return result


def signed_degrees(a, b):
    return (math.degrees(a - b) + 180) % 360 - 180


def stats(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"count": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
            "p05": ordered[round((len(ordered) - 1) * 0.05)],
            "p95": ordered[round((len(ordered) - 1) * 0.95)],
            "min": min(values), "max": max(values), "stdev": statistics.pstdev(values)}


def analyze(folder):
    run = json.loads((folder / "run.json").read_text())
    logs = "\n".join(p.read_text(errors="replace") for p in
                     (folder / "game.log", folder / "saves/halo.log") if p.exists())
    diagnostic_logs = logs + "\n" + "\n".join(p.read_text(errors="replace") for p in
        (folder / "data/debug.txt", folder / "peer/game.log", folder / "peer/data/debug.txt") if p.exists())
    records = [json.loads(line.split("FTRACE ", 1)[1]) for line in logs.splitlines() if "FTRACE {" in line]
    groups = {kind: [r for r in records if r["event"] == kind] for kind in ("meta", "end", "a", "c", "p", "b", "s", "f", "v")}
    meta = groups["meta"][0] if len(groups["meta"]) == 1 else {}
    cameras = {r["sample"]: r for r in groups["v"]}
    displayed_actions = {r["sample"]: r for r in groups["a"]}
    shots = []
    used_presses = set()
    # Retain long real stalls instead of dropping their latency outliers. Keep
    # the search shorter than a full turn so a later revolution cannot match.
    match_window_ms = min(2000, 0.8 * 360000 / max(abs(run["scenario"]["rate_dps"]), 1))
    for shot in groups["s"]:
        preceding = [p for p in groups["p"] if 0 <= shot["ms"] - p["ms"] <= match_window_ms]
        press = preceding[-1] if preceding else None
        camera = cameras.get(shot["sample"])
        displayed_action = displayed_actions.get(shot["sample"])
        press_camera = cameras.get(press["sample"]) if press else None
        consumed = [c for c in groups["c"] if c["tick"] == shot["tick"]]
        consumption = consumed[-1] if consumed else None
        # The legacy wire format quantizes angles. Match within its precision,
        # in a bounded time window, and retain the error instead of assuming IDs
        # survived transmission or treating a later wrap around as the source.
        matching = [a for a in groups["a"] if 0 <= shot["ms"] - a["ms"] <= match_window_ms and
                    consumption and abs(signed_degrees(a["x"], consumption["x"])) < 0.02]
        aim_sample = min(matching, key=lambda a: abs(signed_degrees(a["x"], consumption["x"]))) if matching else None
        aim = math.atan2(shot["j"], shot["i"])
        if press:
            used_presses.add(press["object"])
        shots.append({"tick": shot["tick"], "ms": shot["ms"], "press": press["object"] if press else None,
                      "press_to_shot_ms": shot["ms"] - press["ms"] if press else None,
                      "press_to_shot_ticks": shot["tick"] - press["tick"] if press else None,
                      "action_age_ms": shot["ms"] - aim_sample["ms"] if aim_sample else None,
                      "action_age_ticks": shot["tick"] - aim_sample["tick"] if aim_sample else None,
                      "aim_sample": aim_sample["sample"] if aim_sample else None,
                      "aim_match_error_deg": signed_degrees(aim_sample["x"], consumption["x"]) if aim_sample else None,
                      "shot_minus_drawn_camera_deg": signed_degrees(aim, math.atan2(camera["j"], camera["i"])) if camera else None,
                      "shot_minus_press_camera_deg": signed_degrees(aim, math.atan2(press_camera["j"], press_camera["i"])) if press_camera else None,
                      "shot_minus_press_action_deg": signed_degrees(aim, press["x"]) if press else None,
                      # Remove the measured rotation between the consumed and
                      # displayed samples, not an assumed one-tick/33 ms lag.
                      # The independently measured queue age remains a gate.
                      "sampled_input_advance_deg": signed_degrees(displayed_action["x"], consumption["x"])
                           if displayed_action and consumption else None,
                      "shot_camera_residual_deg": signed_degrees(
                           aim - math.atan2(camera["j"], camera["i"]), consumption["x"] - displayed_action["x"])
                           if camera and displayed_action and consumption else None,
                      "autoaim_target": shot["target"]})
    frame_gaps = [b["ms"] - a["ms"] for a, b in zip(groups["v"], groups["v"][1:])]
    ticks = sorted({r["tick"] for r in groups["c"]})
    elapsed = (groups["c"][-1]["ms"] - groups["c"][0]["ms"]) / 1000 if len(groups["c"]) > 1 else 0
    tick_hz = (ticks[-1] - ticks[0]) / elapsed if elapsed and ticks else None
    expected = run["scenario"]["shots"]
    weapons = re.findall(r"FIDELITY_WEAPON\s+\S+\s+([^\n]+)", logs)
    checks = {
        "clean_exit": run.get("exit_code") == run.get("peer_exit_code") == 0 and not run.get("timed_out", False),
        "no_fault": not re.search(r"ASSERTION FAILED|EXCEPTION halt|guest abort|SIGSEGV|signal 11|signal 10|FIDELITY_FIXTURE_ERROR", diagnostic_logs, re.I),
        "complete_trace": len(groups["meta"]) == len(groups["end"]) == 1 and groups["end"][0]["records"] == len(records) - 2,
        "no_trace_overflow": meta.get("overflow") == 0,
        "scenario_applied": meta.get("requested_shots") == expected and all(
            key in meta and abs(meta[key] - run["scenario"][key]) < 0.001
            for key in ("rate_dps", "phase_ms", "tap_ms")),
        "all_presses_observed": len(groups["p"]) == expected and {p["object"] for p in groups["p"]} == set(range(expected)),
        "one_projectile_per_press": len(shots) == len(groups["b"]) == len(groups["f"]) == len(used_presses) == expected,
        "projectiles_created": bool(groups["f"]) and all(r["target"] != -1 for r in groups["f"]),
        "stock_pistol": len(weapons) == expected and all(w.strip() == r"weapons\pistol\pistol" for w in weapons),
        "no_autoaim_target": bool(shots) and all(s["autoaim_target"] == -1 for s in shots),
        "matched_camera_and_action": bool(shots) and all(s["action_age_ms"] is not None and
             s["shot_minus_drawn_camera_deg"] is not None and s["shot_minus_press_camera_deg"] is not None and
             s["shot_camera_residual_deg"] is not None for s in shots),
        "30_hz_simulation": tick_hz is not None and abs(tick_hz - 30) < 0.5,
    }
    build = json.loads((Path(run["build"]) / "manifest.json").read_text())
    checks["requested_netcode_active"] = meta.get("legacy_lockstep") == int(build["legacy_lockstep"])
    checks["requested_network_role"] = meta.get("role") == (2 if run["scenario"]["role"] == "host" else 1)
    peer_logs = "\n".join(p.read_text(errors="replace") for p in
                         (folder / "peer/game.log", folder / "peer/saves/halo.log") if p.exists())
    ready = [re.findall(r"FIDELITY_READY tick=(\d+) player=(-?\d+) loaded=(\d+) total=(\d+)", log)
             for log in (logs, peer_logs)]
    first_shot_tick = min((s["tick"] for s in groups["s"]), default=-1)
    checks["fixture_ready_on_both_endpoints"] = all(len({r[1] for r in endpoint}) == 2 and
        all(int(r[0]) < first_shot_tick and (int(r[2]), int(r[3])) == (12, 48) for r in endpoint)
        for endpoint in ready)
    checks["two_players_simulated"] = all(any(len(set(re.findall(r"player (\d+):", line))) >= 2
        for line in log.splitlines() if "network test: tick" in line) for log in (logs, peer_logs))
    peer_ticks = [int(t) for t in re.findall(r"network test: tick (\d+)", peer_logs)]
    checks["peer_survived_capture"] = bool(peer_ticks) and bool(ticks) and max(peer_ticks) >= ticks[-1] - 30
    if run["scenario"]["transport"] == "local-relay":
        checks["local_network_connected"] = all("Internet play: connected to" in log for log in (logs, peer_logs))
        checks["local_signalling_only"] = run.get("local_signalling", {}).get("deliveries", 0) > 0
    else:
        checks["local_network_connected"] = all(re.search(r"network test: tick[^\n]*received [1-9]\d*", log)
                                                  is not None for log in (logs, peer_logs))
    checks["build_manifest_unchanged"] = digest(Path(run["build"]) / "manifest.json") == run["build_manifest_sha256"]
    checks["config_unchanged"] = digest(folder / "saves/config.toml") == run["config_sha256"]
    if (folder / "requested-config.toml").exists():
        requested = tomllib.loads((folder / "requested-config.toml").read_text())
        effective = tomllib.loads((folder / "saves/config.toml").read_text())
        checks["requested_settings_applied"] = all(effective.get(section, {}).get(key) == value
            for section, entries in requested.items() for key, value in entries.items())
    checks["finite_trace"] = all(math.isfinite(value) for row in records for value in row.values()
                                 if isinstance(value, (int, float)))
    checks["input_time_ordered"] = all(b["ms"] >= a["ms"] and b["sample"] > a["sample"]
                                     for a, b in zip(groups["a"], groups["a"][1:]))
    # Keep every shot, including unmatched events, in an ordinary export.
    if shots:
        with (folder / "shots.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(shots[0]))
            writer.writeheader(); writer.writerows(shots)
    return {"schema": 1, "valid": all(checks.values()), "checks": checks, "metadata": meta,
            "event_counts": {k: len(v) for k, v in groups.items()}, "simulation_hz": tick_hz,
            "frame_gap_ms": stats(frame_gaps), "metrics": {k: stats([s[k] for s in shots if s[k] is not None]) for k in MEASUREMENT_FIELDS},
            "action_match_window_ms": match_window_ms,
            "shots": shots, "limits": ["Packed actions bypass controller response and calibration.",
                "Two native instances on one Mac are not physical Xbox or wired System Link measurements.",
                "Camera capture is the view submitted for drawing, not display scanout."]}


def compare(reference, candidate, angle_tolerance=0.25, time_tolerance=5.0):
    # Re-read raw evidence and integrity checks. An old successful analysis file
    # must not mask a subsequently truncated log or changed build/configuration.
    a, b = (analyze(path) for path in (reference, candidate))
    for path, report in ((reference, a), (candidate, b)):
        save(path / "analysis.json", report)
    ra, rb = (json.loads((path / "run.json").read_text()) for path in (reference, candidate))
    return compare_reports(a, b, ra, rb, angle_tolerance, time_tolerance)


def compare_reports(a, b, ra, rb, angle_tolerance=0.25, time_tolerance=5.0):
    compatible = ra["scenario"] == rb["scenario"] and ra["map_sha256"] == rb["map_sha256"]
    deltas = {}
    for key in MEASUREMENT_FIELDS:
        av, bv = a["metrics"].get(key), b["metrics"].get(key)
        tolerance = 0 if key.endswith("ticks") else angle_tolerance if key.endswith("deg") else time_tolerance
        delta = bv["median"] - av["median"] if av and bv else None
        quantile_deltas = {q: bv[q] - av[q] for q in ("min", "p05", "median", "p95", "max")} if av and bv else {}
        deltas[key] = {"reference": av, "candidate": bv, "median_delta": delta,
                       "quantile_deltas": quantile_deltas, "tolerance": tolerance,
                       "gates_result": key != "shot_minus_drawn_camera_deg",
                       "within_tolerance": bool(quantile_deltas) and av.get("count") == bv.get("count") == ra["scenario"]["shots"] and
                           all(math.isfinite(d) and abs(d) <= tolerance for d in quantile_deltas.values())}
    passed = a["valid"] and b["valid"] and compatible and all(d["within_tolerance"] for d in deltas.values() if d["gates_result"])
    return {"schema": 1, "passed": passed, "reference_valid": a["valid"], "candidate_valid": b["valid"],
            "same_scenario_and_assets": compatible, "metrics": deltas,
            "camera_gate": "camera residual after measured input advance; raw shot-camera angle retained separately because frame cadence varies",
            "scope": "historical native lockstep versus native candidate on one Mac; provisional engineering tolerances",
            "retail_xbox_parity": "not established"}


def suite(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for rate in args.rates:
        for phase in args.phases:
            name = f"rate-{rate:g}-phase-{phase:g}"
            case = output / name
            for label, build in (("reference", args.reference_build), ("candidate", args.candidate_build)):
                print(f"Running {name} / {label}", flush=True)
                run_one(build.resolve(), case / label, args.shots, rate, phase, args.tap_ms, args.interpolation, args.role, args.transport)
            result = compare(case / "reference", case / "candidate", args.angle_tolerance, args.time_tolerance_ms)
            save(case / "comparison.json", result)
            cases.append({"case": name, "comparison": result})
            save(output / "suite.json", {"complete": False, "cases": cases})
    result = {"complete": True, "passed": all(c["comparison"]["passed"] for c in cases), "cases": cases}
    save(output / "suite.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Snapshot and compile a diagnostic engine, without packaging an app")
    build.add_argument("--revision", default="working", help=f"working or a Git revision; historical reference: {REFERENCE}")
    build.add_argument("--legacy", action="store_true", help="Enable the historical lockstep configuration")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--jobs", type=int, default=6)
    run = sub.add_parser("run", help="Run the actual engine with isolated saves and collect a spin trace")
    run.add_argument("--build", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--shots", type=int, default=48)
    run.add_argument("--rate", type=float, default=100)
    run.add_argument("--phase-ms", type=float, default=0)
    run.add_argument("--tap-ms", type=float, default=70)
    run.add_argument("--interpolation", action="store_true")
    run.add_argument("--role", choices=("host", "client"), default="host")
    run.add_argument("--transport", choices=("auto", "lan", "local-relay"), default="auto")
    analysis = sub.add_parser("analyze")
    analysis.add_argument("folder", type=Path)
    comparison = sub.add_parser("compare")
    comparison.add_argument("reference", type=Path)
    comparison.add_argument("candidate", type=Path)
    comparison.add_argument("--output", type=Path, required=True)
    comparison.add_argument("--angle-tolerance", type=float, default=0.25)
    comparison.add_argument("--time-tolerance-ms", type=float, default=5.0)
    matrix = sub.add_parser("suite", help="Run both builds sequentially across phase and turn-direction cases")
    matrix.add_argument("--reference-build", type=Path, required=True)
    matrix.add_argument("--candidate-build", type=Path, required=True)
    matrix.add_argument("--output", type=Path, required=True)
    matrix.add_argument("--shots", type=int, default=48)
    matrix.add_argument("--rates", nargs="+", type=float, default=[100, -100])
    matrix.add_argument("--phases", nargs="+", type=float, default=[0, 8.333, 16.667, 25])
    matrix.add_argument("--tap-ms", type=float, default=70)
    matrix.add_argument("--interpolation", action="store_true")
    matrix.add_argument("--role", choices=("host", "client"), default="host")
    matrix.add_argument("--transport", choices=("auto", "lan", "local-relay"), default="auto")
    matrix.add_argument("--angle-tolerance", type=float, default=0.25)
    matrix.add_argument("--time-tolerance-ms", type=float, default=5.0)
    args = parser.parse_args()
    if args.command == "build":
        if args.jobs < 1 or args.output.exists():
            parser.error("Use a new output directory and positive job count")
        build_one(args.output.resolve(), args.revision, args.legacy, args.jobs)
        return 0
    if args.command == "run":
        if not 1 <= args.shots <= 48 or not all(math.isfinite(x) for x in (args.rate, args.phase_ms, args.tap_ms)):
            parser.error("Use 1-48 shots and finite scenario values")
        if not 1 <= abs(args.rate) <= 150 or not 0 <= args.phase_ms < 1000 / 30 or not 1 <= args.tap_ms <= 100:
            parser.error("Use 1-150 degrees/s, phase within a 30 Hz tick, and a 1-100 ms tap")
        result = run_one(args.build.resolve(), args.output.resolve(), args.shots, args.rate,
                         args.phase_ms, args.tap_ms, args.interpolation, args.role, args.transport)
    elif args.command == "analyze":
        result = analyze(args.folder.resolve()); save(args.folder / "analysis.json", result)
    elif args.command == "suite":
        if not 1 <= args.shots <= 48 or not 1 <= args.tap_ms <= 100 or not all(
            math.isfinite(x) and 1 <= abs(x) <= 150 for x in args.rates) or not all(
            math.isfinite(x) and 0 <= x < 1000 / 30 for x in args.phases):
            parser.error("Invalid scenario: check shots, rates, phases and tap duration")
        if not all(math.isfinite(x) and x >= 0 for x in (args.angle_tolerance, args.time_tolerance_ms)):
            parser.error("Tolerances must be finite and nonnegative")
        result = suite(args)
    else:
        if not all(math.isfinite(x) and x >= 0 for x in (args.angle_tolerance, args.time_tolerance_ms)):
            parser.error("Tolerances must be finite and nonnegative")
        result = compare(args.reference.resolve(), args.candidate.resolve(), args.angle_tolerance, args.time_tolerance_ms)
        save(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "shots"}, indent=2, allow_nan=False))
    return 0 if result.get("passed", result.get("valid", False)) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Fidelity test failed: {exc}", file=sys.stderr)
        sys.exit(2)
