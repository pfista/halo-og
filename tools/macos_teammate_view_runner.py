#!/usr/bin/env python3
"""Open an interactive, private 2v2 teammate-view session on one Mac.

All four machines have separate temporary saves and existing IPv4 addresses.
The setup harness chooses the lobby, teams and host option; gameplay controls
remain manual. Ctrl-C closes only the processes launched by this runner.
"""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import time

try:
    from .macos_multiplayer_smoke import ROOT, read_log
    from .macos_teammate_view_smoke import (
        ROLES, configured_addresses, default_addresses, parse_invite, parse_tick,
        teammate_target_valid,
    )
except ImportError:
    from macos_multiplayer_smoke import ROOT, read_log
    from macos_teammate_view_smoke import (
        ROLES, configured_addresses, default_addresses, parse_invite, parse_tick,
        teammate_target_valid,
    )

DEFAULT_EXECUTABLE = Path("/Applications/Halo OG.app/Contents/MacOS/halo")


def resolve_addresses(value, configured):
    """Use only four distinct addresses that already exist on this Mac."""
    try:
        addresses = ([str(ipaddress.IPv4Address(part.strip())) for part in value.split(",")]
                     if value else default_addresses(configured))
    except ipaddress.AddressValueError as error:
        raise ValueError(f"Invalid IPv4 address: {error}") from error
    if len(addresses) != 4 or len(set(addresses)) != 4 or any(address not in configured for address in addresses):
        raise ValueError("Four distinct, already configured IPv4 addresses are required. "
                         "Use --addresses HOST,RED_CLIENT,BLUE_1,BLUE_2; this runner never changes interfaces.")
    return addresses


def check_ports(addresses):
    """Check the actual fixed game ports without connecting or changing interfaces."""
    checks = [(socket.SOCK_STREAM, "0.0.0.0", 5150, "host"),
              (socket.SOCK_DGRAM, addresses[0], 5150, "host")]
    checks += [(kind, address, 5151, role) for (role, _), address in zip(ROLES, addresses)
               for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM)]
    errors = []
    for kind, address, port, role in checks:
        try:
            with socket.socket(socket.AF_INET, kind) as probe:
                if kind == socket.SOCK_STREAM:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((address, port))
        except OSError as error:
            transport = "TCP" if kind == socket.SOCK_STREAM else "UDP"
            errors.append(f"{role}: {transport} {address}:{port} is unavailable ({error}).")
    return errors


def validate_app(executable, renderer):
    if renderer not in ("metal", "angle"):
        raise ValueError("Select renderer metal or angle.")
    executable = Path(executable).expanduser().resolve()
    if executable.parent.name != "MacOS" or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Use the native executable inside a built Halo OG app's Contents/MacOS directory.")
    resources = executable.parent.parent / "Resources"
    if not (resources / "halo_guest.elf").is_file():
        raise ValueError(f"The app is missing {resources / 'halo_guest.elf'}")
    if renderer == "metal":
        metal = executable.parent / "halo-metal"
        if not metal.is_file() or not os.access(metal, os.X_OK) or not (resources / "halo_guest-metal.elf").is_file():
            raise ValueError("Native Metal needs both Contents/MacOS/halo-metal and "
                             "Contents/Resources/halo_guest-metal.elf; select --renderer angle for an ANGLE-only app.")
    return executable


def make_config(role, team, address, map_name, renderer, hide_clients=False, start_delay=35.0):
    host = role == "red_host"
    return f'''[network]
address = {json.dumps(address)}
broadcast = {json.dumps(address)}
online = true
directory_url = ""
public_games = false
allow_upnp = false
join_from_clipboard = false

[discord]
application_id = ""

[display]
renderer = {json.dumps(renderer)}
fullscreen = false
window_scale = 1
interpolation = false
direct_camera = false
high_res_hud = false

[audio]
enabled = {str(host).lower()}
volume = 1.0

[update]
auto = false

[community_maps]
auto_download = false

[timer_audio]
auto_download = false

[debug]
hidden_window = {str(hide_clients and not host).lower()}
network_test = {json.dumps('host:' + map_name + ':team_slayer' if host else 'join')}
network_test_start = {float(start_delay)}
network_test_team = {team}
network_test_team_view = {str(host).lower()}
network_test_score = 1000000
network_test_shoot = 0.0
network_test_kill = 0.0
network_test_vehicle = 0.0
network_test_pickup = 0.0
network_test_pickup_weapon = ""
test_input = ""
exit_after = 0.0
'''


def prepare_instance(folder, role, team, address, map_name, renderer, hide_clients=False,
                     start_delay=35.0, data_root=ROOT / "assets"):
    folder = Path(folder)
    maps = Path(data_root).expanduser().resolve() / "maps"
    if not maps.is_dir() or not (maps / "ui.map").is_file() or not (maps / (map_name + ".map")).is_file():
        raise ValueError(f"Game data needs maps/ui.map and maps/{map_name}.map: {maps.parent}")
    folder.mkdir(parents=True, exist_ok=False)
    saves, data = folder / "saves", folder / "data"
    saves.mkdir()
    (data / "maps").mkdir(parents=True)
    (data / "init.txt").write_text("")
    for source in maps.iterdir():
        if source.is_file():
            (data / "maps" / source.name).symlink_to(source.resolve())
    (saves / "config.toml").write_text(make_config(role, team, address, map_name, renderer, hide_clients, start_delay))
    (saves / "macos-settings.json").write_text(json.dumps({
        "community_downloads": False, "timer_audio_downloads": False, "release_checks": False,
    }, indent=2) + "\n")
    # Runtime overrides outrank config.toml. Never inherit a parent's bot,
    # network-test actions, personal save root, hidden window or dynamic loader.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("HALO_", "DYLD_")) and key != "POC_DIAG_EVENT_FILE"}
    environment.update(HALO_DATA_ROOT=str(data.resolve()), HALO_SAVE_ROOT=str(saves.resolve()),
                       HALO_WINDOWED="1", HALO_SCREEN_WIDTH="640", HALO_WINDOW_SCALE="1")
    if role != "red_host":
        environment["HALO_NO_AUDIO"] = "1"
    return environment


def make_plan(output, addresses, executable, renderer, map_name, hide_clients=False,
              start_delay=35.0, data_root=ROOT / "assets"):
    output = Path(output).expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output already exists; choose a fresh directory: {output}")
    output = output.resolve()
    executable = validate_app(executable, renderer)
    if len(addresses) != 4 or len(set(addresses)) != 4:
        raise ValueError("Four distinct IPv4 addresses are required.")
    if not re.fullmatch(r"[A-Za-z0-9_ -]{1,31}", map_name):
        raise ValueError("Use a map cache name of 1–31 letters, numbers, spaces, underscores or hyphens.")
    maps = Path(data_root).expanduser().resolve() / "maps"
    if not maps.is_dir() or any(not (maps / name).is_file() for name in ("ui.map", map_name + ".map")):
        raise ValueError(f"Game data needs maps/ui.map and maps/{map_name}.map: {maps.parent}")
    return {"output": str(output), "executable": str(executable), "renderer": renderer, "map": map_name,
            "data_source": str(maps.parent), "start_delay": start_delay, "hide_clients": hide_clients,
            "addresses": addresses, "instances": [
                {"role": role, "team": team, "address": address, "folder": str(output / role),
                 "config": make_config(role, team, address, map_name, renderer, hide_clients, start_delay),
                 "command": [str(executable)], "pid": None}
                for (role, team), address in zip(ROLES, addresses)]}


def prepare_session(output, addresses, executable, renderer, map_name, hide_clients=False,
                    start_delay=35.0, data_root=ROOT / "assets"):
    plan = make_plan(output, addresses, executable, renderer, map_name, hide_clients, start_delay, data_root)
    Path(plan["output"]).mkdir(parents=True, mode=0o700, exist_ok=False)
    for instance in plan["instances"]:
        instance["environment"] = prepare_instance(Path(instance["folder"]), instance["role"], instance["team"],
                                                   instance["address"], map_name, renderer, hide_clients,
                                                   start_delay, data_root)
    return plan


def process_start_time(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def manifest_path(plan):
    return Path(plan["output"]) / "session.json"


def write_manifest(plan):
    # Do not write inherited shell variables (which can contain credentials).
    serializable = dict(plan)
    serializable["instances"] = [{key: value for key, value in instance.items() if key != "environment"}
                                 for instance in plan["instances"]]
    path = manifest_path(plan)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(serializable, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def stop_processes(processes):
    """Only Popen objects created by this runner can reach this cleanup path."""
    for process in processes.values():
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
    for process in processes.values():
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def stop_session(path):
    path = Path(path).expanduser().resolve()
    plan = json.loads(path.read_text())
    if plan.get("state") == "stopped":
        print("This session is already stopped.")
        return
    runner = plan.get("runner", {})
    if runner.get("start_time") and process_start_time(runner["pid"]) == runner["start_time"]:
        os.kill(runner["pid"], signal.SIGTERM)
        print(f"Requested cleanup from session runner PID {runner['pid']}.")
        return
    # An abruptly closed Terminal can leave child apps. Verify each recorded
    # process birth time before signalling it, so a reused PID is preserved.
    for instance in plan.get("instances", []):
        pid, birth = instance.get("pid"), instance.get("start_time")
        if pid and birth and process_start_time(pid) == birth:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Stopped {instance['role']} PID {pid}.")
            except ProcessLookupError:
                pass
        elif pid:
            print(f"Preserved PID {pid}: no matching live session process.")


def run_session(plan, seconds=0):
    processes, streams = {}, []
    plan.update(state="starting", runner={"pid": os.getpid(), "start_time": process_start_time(os.getpid())})
    started, invite, ready = time.monotonic(), None, False
    write_manifest(plan)
    print(f"Session: {plan['output']}\nStop: {shlex.join([sys.executable, str(Path(__file__).resolve()), '--stop', str(manifest_path(plan))])}", flush=True)
    try:
        for index, instance in enumerate(plan["instances"]):
            folder = Path(instance["folder"])
            command = list(instance["command"])
            if index:
                if not invite:
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline and processes["red_host"].poll() is None:
                        invite = parse_invite(read_log(Path(plan["instances"][0]["folder"])))
                        if invite:
                            break
                        time.sleep(0.2)
                    if not invite:
                        raise RuntimeError("Host produced no private invite. Inspect red_host/game.log and saves/halo.log.")
                command.append(invite)
            stream = (folder / "game.log").open("w")
            streams.append(stream)
            process = subprocess.Popen(command, cwd=ROOT, env=instance["environment"],
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            processes[instance["role"]] = process
            instance.update(pid=process.pid, start_time=process_start_time(process.pid),
                            log=str(folder / "game.log"), native_log=str(folder / "saves/halo.log"))
            write_manifest(plan)
            print(f"{instance['role']} — {'Red' if instance['team'] == 0 else 'Blue'}; "
                  f"PID {process.pid}; {instance['address']}; log {instance['native_log']}", flush=True)
        plan["state"] = "running"
        write_manifest(plan)
        print("Four one-player instances launched. Click the Red host window to play; "
              "switch windows to control another player. Others remain idle. Ctrl-C stops this session.", flush=True)
        while True:
            ended = [(role, process.poll()) for role, process in processes.items() if process.poll() is not None]
            if ended:
                role, code = ended[0]
                print(f"{role} exited ({code}); stopping this session's remaining instances.", flush=True)
                return 0 if code == 0 else 1
            if seconds and time.monotonic() - started >= seconds:
                print(f"Reached the requested {seconds:g}-second session limit.", flush=True)
                return 0
            if not ready:
                records = []
                for instance in plan["instances"]:
                    ticks = [record for line in read_log(Path(instance["folder"])).splitlines()
                             if (record := parse_tick(line))]
                    records.append(ticks[-1] if ticks else None)
                ready = all(record and record["enabled"] and record["local_count"] == 1
                            and sorted(player["team"] for player in record["players"].values()) == [0, 0, 1, 1]
                            and record["windows"] == 2 and teammate_target_valid(record) for record in records)
                if ready:
                    plan["observed_2v2_teammate_views"] = True
                    write_manifest(plan)
                    print("All four instances report one local player, 2v2 teams and a same-team teammate pane.", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping this session's instances.", flush=True)
        return 0
    finally:
        stop_processes(processes)
        plan["state"] = "stopped"
        for instance in plan["instances"]:
            process = processes.get(instance["role"])
            instance["exit_code"] = process.returncode if process else None
        write_manifest(plan)
        for stream in streams:
            stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Fresh session directory (default: timestamped build/macos directory)")
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE, help="Native executable inside the installed or candidate app")
    parser.add_argument("--data-root", type=Path, default=ROOT / "assets", help="Read-only map source; never uses its saves")
    parser.add_argument("--map", default="bloodgulch")
    parser.add_argument("--addresses", help="Four existing IPv4 addresses: host, red teammate, blue player, blue teammate")
    parser.add_argument("--renderer", choices=("metal", "angle"), default="metal")
    parser.add_argument("--hide-clients", action="store_true", help="Show only the human Red host window")
    parser.add_argument("--seconds", type=float, default=0, help="Optional session limit; 0 runs until Ctrl-C")
    parser.add_argument("--start-delay", type=float, default=35, help="Lobby setup delay before automatic start")
    parser.add_argument("--dry-run", action="store_true", help="Inspect configuration and port availability without writing files or launching apps")
    parser.add_argument("--stop", type=Path, metavar="SESSION_JSON", help="Stop only the recorded session's processes")
    args = parser.parse_args(argv)
    if args.stop:
        stop_session(args.stop)
        return 0
    if not math.isfinite(args.seconds) or not math.isfinite(args.start_delay) or args.seconds < 0 or args.start_delay < 10:
        parser.error("Use --seconds 0 or a positive limit, and --start-delay of at least 10 seconds.")
    output = args.output or ROOT / "build/macos" / ("teammate-view-local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    try:
        addresses = resolve_addresses(args.addresses, configured_addresses())
        plan = make_plan(output, addresses, args.executable, args.renderer, args.map,
                         args.hide_clients, args.start_delay, args.data_root)
        errors = check_ports(addresses)
        if args.dry_run:
            plan["port_errors"] = errors
            print(json.dumps(plan, indent=2))
            return 0
        if errors:
            raise ValueError("Existing game ports are busy; no apps were launched or stopped.\n" + "\n".join(errors) +
                             "\nClose an existing local Halo session yourself, or choose other available configured addresses.")
        plan = prepare_session(output, addresses, args.executable, args.renderer, args.map,
                               args.hide_clients, args.start_delay, args.data_root)
        previous_handler = signal.getsignal(signal.SIGTERM)
        def request_stop(signum, frame):
            raise KeyboardInterrupt()

        signal.signal(signal.SIGTERM, request_stop)
        try:
            return run_session(plan, args.seconds)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Team View runner: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
