#!/usr/bin/env python3
"""Preserve a failed immutable-config ANGLE attempt and prepare a fresh plan.

This is test-only. It never rebuilds, changes game sources, launches the game,
or promotes the old failed execution to a passing capture.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import tomllib


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def flatten(value, prefix=""):
    result = {}
    for name, child in value.items():
        key = prefix + name
        if isinstance(child, dict):
            result.update(flatten(child, key + "."))
        else:
            result[key] = child
    return result


def initial_config(source, folder, index):
    tree = ast.parse(source)
    nodes = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "config" for t in n.targets)
             and isinstance(n.value, ast.JoinedStr)]
    if len(nodes) != 1:
        raise ValueError("Retained preparer has no unique config template")
    # Only the retained trusted source's string template is evaluated. Its
    # expressions are path/port expressions; no game/config content is code.
    return eval(compile(ast.Expression(nodes[0]), "retained-config-template", "eval"),
                {"__builtins__": {}}, {"folder": folder, "index": index})


def setting_defaults(source):
    values = {}
    quoted = r'"(?:\\.|[^"\\])*"'
    pattern = r'\{\s*"([^"\n]+)"\s*,\s*_config_\w+\s*,\s*((?:' + quoted + r'\s*)+)'
    for match in re.finditer(pattern, source):
        strings = re.findall(quoted, match.group(2))
        text = "".join(json.loads(s) for s in strings)
        values[match.group(1)] = tomllib.loads("value=" + text)["value"]
    return values


def verify(bindings, allowed_changed=None):
    mismatches = {}
    for path, expected in bindings.items():
        actual = sha(path)
        if actual != expected:
            mismatches[path] = {"expected_sha256": expected, "actual_sha256": actual}
    if set(mismatches) != set(allowed_changed or ()):
        raise ValueError("Unexpected frozen source/artifact changes: " + ", ".join(mismatches))
    return mismatches


def prepare(args):
    previous = args.previous.resolve()
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Output exists; preserve attempts")
    record = json.loads((previous / "prepared.json").read_bytes())
    old_plan = json.loads((previous / "execution-plan.json").read_bytes())
    selected = next(p for p in record["runtime_plans"] if p["name"] == args.case)
    folder = Path(selected["cwd"])
    old_execution = json.loads((folder / "execution.json").read_bytes())
    config_path = folder / "saves/config.toml"
    if old_execution["complete"] or old_execution.get("exit_code") != 0 or old_execution.get("error") != "Frozen diagnostic input changed: " + str(config_path):
        raise ValueError("This helper accepts only the observed immutable-config failure")
    verify(record["original_bindings"])
    verify(record["retained_object_bindings"])
    verify(old_plan["additional_bindings"])
    mutations = verify(record["artifact_bindings"], [str(config_path)])
    original_text = initial_config((previous / "preparation-helper.py").read_text(), folder,
                                   record["runtime_plans"].index(selected))
    if hashlib.sha256(original_text.encode()).hexdigest() != record["artifact_bindings"][str(config_path)]:
        raise ValueError("Reconstructed initial bytes disagree with frozen hash")
    requested = flatten(tomllib.loads(original_text))
    effective_text = config_path.read_text()
    effective = flatten(tomllib.loads(effective_text))
    if any(k not in effective or effective[k] != v or type(effective[k]) != type(v) for k, v in requested.items()):
        raise ValueError("An explicitly requested setting changed")
    primary = Path(record["fresh_host"]["builder"]).parents[1]
    source_path = primary / "port/linux/src/port_config.c"
    if str(source_path) not in record["original_bindings"]:
        raise ValueError("Config implementation lacks a frozen source binding")
    defaults = setting_defaults(source_path.read_text())
    added = sorted(set(effective) - set(requested))
    if not added or any(k not in defaults or defaults[k] != effective[k] or type(defaults[k]) != type(effective[k]) for k in added):
        raise ValueError("Added settings differ from source defaults")
    logged = sorted(re.findall(r"settings: added ([\w.]+) \(new in this version\) at its default", (folder / "halo.log").read_text()))
    if logged != added:
        raise ValueError("Actual source-default append logs disagree with parsed config")
    out.mkdir(parents=True)
    audit_dir = out / "prior-failure-audit"
    audit_dir.mkdir()
    (audit_dir / "initial-config-reconstructed.toml").write_text(original_text)
    shutil.copy2(config_path, audit_dir / "effective-config-observed.toml")
    audit = {"kind": "roof_original_angle_failed_config_audit", "complete": True,
        "prior_execution_complete": False, "prior_execution_promoted": False,
        "observed_game_exit": 0, "strict_plan_failure_preserved": True,
        "previous_prepared": {"file": str(previous / "prepared.json"), "sha256": sha(previous / "prepared.json")},
        "previous_plan": {"file": str(previous / "execution-plan.json"), "sha256": sha(previous / "execution-plan.json")},
        "previous_execution": {"file": str(folder / "execution.json"), "sha256": sha(folder / "execution.json")},
        "verified_source_count": len(record["original_bindings"]),
        "verified_retained_object_count": len(record["retained_object_bindings"]),
        "verified_unchanged_artifact_count": len(record["artifact_bindings"]) - 1,
        "mutation": mutations[str(config_path)], "requested_setting_count": len(requested),
        "all_requested_values_and_types_retained": True, "added_source_default_count": len(added),
        "added_setting_names": added, "actual_append_log_matches": True,
        "source": {"file": str(source_path), "sha256": sha(source_path),
                   "implementation": "config_load calls config_add_missing, which inserts only absent settings at source defaults and writes the completed file"},
        "limits": ["An independently audited game execution does not promote the failed immutable-config plan",
                   "Library linkage/source bindings are not an intercepted dynamic loader trace",
                   "No renderer, Xbox hardware, camera-pixel parity or clipping-fix conclusion"]}
    write(audit_dir / "audit.json", audit)
    new_folder = out / "runs" / args.case
    (new_folder / "data").mkdir(parents=True)
    (new_folder / "saves").mkdir()
    (new_folder / "screenshots").mkdir()
    (new_folder / "data/maps").symlink_to((folder / "data/maps").resolve(), target_is_directory=True)
    for name in ("init.txt", "camera.txt"):
        shutil.copy2(folder / "data" / name, new_folder / "data" / name)
    # Retain the observed complete defaults and all explicit original controls.
    # Only paths/port belonging to this new isolated run are changed.
    new_text = effective_text.replace(str(folder / "screenshots"), str(new_folder / "screenshots"))
    new_text, replacements = re.subn(r"(?m)^telnet_console_port\s*=\s*\d+\s*$",
                                     "telnet_console_port=" + str(args.port), new_text)
    if replacements != 1:
        raise ValueError("Expected one console port setting")
    new_flat = flatten(tomllib.loads(new_text))
    expected = dict(effective)
    expected["debug.screenshot_directory"] = str(new_folder / "screenshots")
    expected["debug.telnet_console_port"] = args.port
    if new_flat != expected:
        raise ValueError("Fresh complete config has an unexpected semantic change")
    (new_folder / "saves/config.toml").write_text(new_text)
    new_selected = dict(selected)
    new_selected.update({"cwd": str(new_folder), "console_port": args.port,
        "environment_overrides": {**selected["environment_overrides"],
            "HALO_DATA_ROOT": str(new_folder / "data"), "HALO_SAVE_ROOT": str(new_folder / "saves")}})
    # The frozen old compiled sources/binaries are retained exactly. The only
    # old mismatched artifact is bound at its observed hash, explicitly above.
    original = dict(record["original_bindings"])
    original[str(Path(__file__).resolve())] = sha(__file__)
    for p in (previous / "prepared.json", previous / "execution-plan.json", folder / "execution.json", config_path):
        original[str(p)] = sha(p)
    artifacts = dict(record["artifact_bindings"])
    artifacts.pop(str(config_path))
    for p in out.rglob("*"):
        if p.is_file():
            artifacts[str(p)] = sha(p)
    fresh = {**record, "scope": record["scope"] + "; fresh isolated complete-config runtime, previous strict failure preserved",
        "original_bindings": original, "artifact_bindings": artifacts, "runtime_plans": [new_selected],
        "reused_compiled_build": {"prepared": str(previous / "prepared.json"), "sha256": sha(previous / "prepared.json"),
                                 "old_execution_gate_passed": False, "no_rebuild_or_gpu_execution": True},
        "config_audit": {"file": str(audit_dir / "audit.json"), "sha256": sha(audit_dir / "audit.json")}}
    write(out / "prepared.json", fresh)
    write(out / "execution-plan.json", {**old_plan, "prepared": str(out / "prepared.json"),
        "prepared_sha256": sha(out / "prepared.json"), "cases": [args.case], "gpu_executed": False,
        "previous_failed_plan": {"file": str(previous / "execution-plan.json"), "sha256": sha(previous / "execution-plan.json")}})
    verify(original); verify(record["retained_object_bindings"]); verify(artifacts)
    print(json.dumps({"plan": str(out / "execution-plan.json"), "sha256": sha(out / "execution-plan.json"),
        "audit": str(audit_dir / "audit.json"), "audit_sha256": sha(audit_dir / "audit.json"),
        "source_default_appends": len(added), "requested_settings_unchanged": len(requested), "gpu_executed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", default="center-z6.5-surface5427")
    parser.add_argument("--port", type=int, default=23880)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Invalid isolated console port")
    prepare(args)
