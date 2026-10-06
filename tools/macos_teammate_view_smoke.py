#!/usr/bin/env python3
"""Run a real four-machine 2v2 Team View prototype and its disabled control.

Each process owns one player, uses an isolated save/data directory, and binds a
different already configured IPv4 address. This checks one Mac, not internet
latency or multiple physical machines. Rendered frames remain visual evidence.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time

try:
    from .macos_multiplayer_smoke import BUILD, ROOT, prepare, read_log
except ImportError:
    from macos_multiplayer_smoke import BUILD, ROOT, prepare, read_log

TEAM_VIEW_MARKER = 0x53535000
PLAYER = re.compile(r"player (\d+):.*? t(-?\d+) m(-?\d+) lp(-?\d+) c(-?\d+)")
PRESENTATION = re.compile(r"variant_flags 0x([0-9a-fA-F]+) team_view (\d+) windows (\d+) local_count (\d+) view_target (-?\d+)")
INVITE = re.compile(r"halo-og://join/[0-9a-fA-F]{64}(?![0-9a-fA-F])")
FAULT = re.compile(r"ASSERTION FAILED|EXCEPTION halt in|guest abort|SIGSEGV|signal 11|signal 10", re.I)
ROLES = (("red_host", 0), ("red_client", 0), ("blue_client_1", 1), ("blue_client_2", 1))


def configured_addresses():
    return list(dict.fromkeys(re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)\b",
                                        subprocess.check_output(["ifconfig"], text=True))))


def default_addresses(configured):
    host = next((address for address in configured if not ipaddress.IPv4Address(address).is_loopback), None)
    clients = [address for address in configured if address != host and ipaddress.IPv4Address(address).is_loopback]
    clients += [address for address in configured if address != host and address not in clients]
    return ([host] + clients[:3]) if host and len(clients) >= 3 else []


def parse_tick(line):
    players = {int(match[1]): {"team": int(match[2]), "machine": int(match[3]),
                              "local_index": int(match[4]), "controller": int(match[5])}
               for match in PLAYER.finditer(line)}
    presentation = PRESENTATION.search(line)
    if len(players) != 4 or not presentation:
        return None
    return {"players": players, "flags": int(presentation[1], 16),
            "enabled": int(presentation[2]), "windows": int(presentation[3]),
            "local_count": int(presentation[4]), "view_target": int(presentation[5])}


def parse_invite(log):
    match = INVITE.search(log)
    return match[0] if match else None


def teammate_target_valid(record):
    target = record["players"].get(record["view_target"])
    local = next((player for player in record["players"].values() if player["local_index"] == 0), None)
    return bool(target and local and target["local_index"] == -1 and target["team"] == local["team"]
                and target["machine"] != local["machine"])


def validate_logs(logs, diagnostics, codes, enabled, folders, renderer=None):
    records = {role: [record for line in re.findall(r"network test: tick[^\n]+", logs.get(role, ""))
                      if (record := parse_tick(line))] for role, _ in ROLES}
    checks = {
        "all_four_roles_present": all(role in collection for role, _ in ROLES
                                      for collection in (logs, diagnostics, codes, folders)),
        "clean_exit": all(code == 0 for code in codes.values()),
        "no_assertion_or_fault": all(not FAULT.search(log) for log in diagnostics.values()),
        "four_players_on_every_machine": all(len(lines) >= 5 for lines in records.values()),
        "encrypted_clients_connected": all("Internet play: connected to" in logs.get(role, "")
                                            for role, _ in ROLES if role != "red_host"),
        "all_frames_captured": all(role in folders and any((folders[role] / "frames").glob("*"))
                                   for role, _ in ROLES),
    }
    if renderer:
        expected = "Native Metal" if renderer == "metal" else "ANGLE"
        checks["all_four_used_requested_renderer"] = all(
            re.findall(r"Renderer active: ([^;\r\n]+)", logs.get(role, "")) == [expected]
            for role, _ in ROLES)
    for role, team in ROLES:
        lines = records[role]
        checks[role + "_two_red_two_blue"] = bool(lines) and all(
            sorted(player["team"] for player in record["players"].values()) == [0, 0, 1, 1]
            for record in lines)
        checks[role + "_separate_machine_ownership"] = bool(lines) and all(
            len({player["machine"] for player in record["players"].values()}) == 4
            and all(player["controller"] == 0 for player in record["players"].values())
            for record in lines)
        checks[role + "_stable_player_ownership"] = bool(lines) and all(
            {index: (player["machine"], player["local_index"], player["controller"])
             for index, player in record["players"].items()} ==
            {index: (player["machine"], player["local_index"], player["controller"])
             for index, player in lines[0]["players"].items()}
            for record in lines)
        checks[role + "_one_local_player"] = bool(lines) and all(
            sorted(player["local_index"] for player in record["players"].values()) == [-1, -1, -1, 0]
            and record["local_count"] == 1
            and next(player for player in record["players"].values() if player["local_index"] == 0)["team"] == team
            for record in lines)
        checks[role + "_received_host_option"] = bool(lines) and all(
            record["enabled"] == int(enabled)
            and (record["flags"] & 0xFFFFFF00) == (TEAM_VIEW_MARKER if enabled else 0)
            for record in lines)
        # Dead/disconnected teammates may have a placeholder or no view. Require
        # repeated two-view frames during a complete roster's normal play.
        checks[role + "_expected_window_count"] = bool(lines) and (
            sum(record["windows"] == 2 for record in lines) >= 5 if enabled
            else all(record["windows"] == 1 for record in lines))
        checks[role + "_same_team_remote_view"] = bool(lines) and all(
            teammate_target_valid(record) if record["windows"] == 2
            else record["view_target"] == -1
            for record in lines)
    return records, checks


def run_case(args, addresses, enabled, out):
    out.mkdir(parents=True)
    processes, streams, folders = {}, [], {}
    try:
        invite = None
        for index, (role, team) in enumerate(ROLES):
            folder = out / role
            folders[role] = folder
            environment = prepare(folder, "host" if index == 0 else "client", "invite", args.seconds,
                                  addresses[0], addresses[index], "team_slayer", 0, args.map,
                                  reference_profile=True, screenshot_every=args.screenshot_every)
            config_path = folder / "saves/config.toml"
            config = config_path.read_text().replace("[network]\n", '[network]\ndirectory_url = ""\npublic_games = false\n')
            config = config.replace("network_test_start = 20.0", "network_test_start = 35.0")
            config = config.replace("[debug]\n", f"[debug]\nnetwork_test_team = {team}\n"
                                    f"network_test_team_view = {str(enabled and index == 0).lower()}\n")
            if args.renderer:
                config = config.replace("[display]\n", f'[display]\nrenderer = "{args.renderer}"\n')
            config_path.write_text(config)
            command = [str(args.executable.resolve())]
            if not args.native_menu:
                command.append(str(args.guest.resolve()))
            if index:
                if not invite:
                    deadline = time.monotonic() + 40
                    while time.monotonic() < deadline and processes["red_host"].poll() is None:
                        invite = parse_invite(read_log(folders["red_host"]))
                        if invite:
                            break
                        time.sleep(0.2)
                    if not invite:
                        raise RuntimeError("Host produced no invite; inspect red_host/game.log")
                command.append(invite)
            stream = (folder / "game.log").open("w")
            streams.append(stream)
            processes[role] = subprocess.Popen(command, cwd=ROOT, env=environment,
                                               stdout=stream, stderr=subprocess.STDOUT)
            print(f"Started {role}, team {team}, Team View {'On' if enabled else 'Off'}", flush=True)
        deadline = time.monotonic() + args.seconds + 60
        while any(process.poll() is None for process in processes.values()) and time.monotonic() < deadline:
            time.sleep(0.2)
        codes = {role: process.poll() for role, process in processes.items()}
        logs = {role: read_log(folder) for role, folder in folders.items()}
        diagnostics = {role: log + ((folders[role] / "data/debug.txt").read_text(errors="replace")
                                   if (folders[role] / "data/debug.txt").exists() else "")
                       for role, log in logs.items()}
        records, checks = validate_logs(logs, diagnostics, codes, enabled, folders, args.renderer)
        result = {"scope": "four real one-player instances on one Mac, 2v2",
                  "team_view": enabled, "map": args.map, "addresses": addresses,
                  "requested_renderer": args.renderer,
                  "observed_renderers": {role: re.findall(r"Renderer active: ([^;\r\n]+)", log)
                                         for role, log in logs.items()},
                  "exit_codes": codes, "complete_roster_ticks": {role: len(lines) for role, lines in records.items()},
                  "checks": checks, "passed": all(checks.values())}
        (out / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
        return result
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in streams:
            stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("both", "enabled", "disabled"), default="both")
    parser.add_argument("--seconds", type=int, default=95)
    parser.add_argument("--map", default="bloodgulch")
    parser.add_argument("--screenshot-every", type=int, default=60)
    parser.add_argument("--addresses", help="Four distinct already configured IPv4 addresses, host first")
    parser.add_argument("--executable", type=Path, default=BUILD / "halo")
    parser.add_argument("--guest", type=Path, default=BUILD / "halo_guest.elf")
    parser.add_argument("--native-menu", action="store_true")
    parser.add_argument("--renderer", choices=("angle", "metal"), help="Select and verify the renderer in every isolated config")
    args = parser.parse_args()
    if args.seconds < 60 or args.screenshot_every <= 0 or not re.fullmatch(r"[A-Za-z0-9_ -]{1,31}", args.map):
        parser.error("Use at least 60 seconds, a positive frame interval, and a safe map cache name")
    if args.native_menu and args.executable.parent.name != "MacOS":
        parser.error("--native-menu requires the executable inside an app bundle")
    configured = configured_addresses()
    try:
        addresses = [str(ipaddress.IPv4Address(address.strip())) for address in args.addresses.split(",")] if args.addresses else default_addresses(configured)
    except ipaddress.AddressValueError as error:
        parser.error(str(error))
    if len(addresses) != 4 or len(set(addresses)) != 4 or any(address not in configured for address in addresses):
        parser.error("Four distinct configured IPv4 addresses are required; this tool never changes network interfaces")
    out = args.output.resolve()
    if out.exists():
        parser.error("Use a new output directory to preserve earlier evidence")
    out.mkdir(parents=True)
    cases = [True, False] if args.case == "both" else [args.case == "enabled"]
    results = [run_case(args, addresses, enabled, out / ("enabled" if enabled else "disabled")) for enabled in cases]
    result = {"scope": "four real one-player instances on one Mac, 2v2",
              "cases": results, "passed": all(case["passed"] for case in results)}
    (out / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
