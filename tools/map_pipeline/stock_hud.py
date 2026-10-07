"""Reuse verified Xbox weapon presentation without importing gameplay tags.

Identity uses the complete weapon path, converted model reference, weapon type
and label. Every copied display dependency receives a private name so a native
weapon HUD cannot replace an authored unit HUD's shared MCC bitmap atlas.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil

from .backend import ConversionError, _tree, legacy

ALLOWED = frozenset({"weapon_hud_interface", "bitmap", "font", "hud_number",
                     "unicode_string_list", "string_list"})
HUD_CLASSES = frozenset({"weapon_hud_interface", "hud_number"})
IDENTITY_FIELDS = ("model", "weapon_type", "label")
HUD_FIELD = "hud_interface"
NAMESPACE = "__native_hud/stock"


def _fail(message, code="needs_profile", **details):
    raise ConversionError(code, "presentation_stock_hud", message, details)


def _name(value, classes=ALLOWED):
    if not isinstance(value, str):
        _fail("A weapon presentation reference is not a tag path")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(char in value for char in "\t\r\n\0:")
            or path.suffix.removeprefix(".") not in classes):
        _fail("Weapon HUD dependency is outside the allowed display classes", tag=value)
    return value


def _path(root, name, classes=ALLOWED):
    name = _name(name, classes)
    at = Path(root)
    if at.is_symlink() or not at.is_dir():
        _fail("Expected a regular weapon presentation directory")
    for part in PurePosixPath(name).parts:
        at /= part
        if at.is_symlink():
            _fail("Linked weapon presentation inputs are unsupported", tag=name)
    if not at.is_file() or at.stat().st_nlink != 1:
        _fail("A canonical weapon presentation dependency is missing or linked", tag=name)
    return at


def _winner(roots, name, classes=ALLOWED):
    for root in roots:
        if (root / name).exists() or (root / name).is_symlink():
            return root, _path(root, name, classes)
    return None


def _reference(value, tag_class):
    """Invader renders a null dependency as its bare class extension."""
    value = value.replace("\\", "/").strip()
    return "" if value == "." + tag_class else value


def _closure(tool, root, name):
    result = {name}
    for line in tool.run("dependency", "-r", "-t", root, name).splitlines():
        if not line.strip():
            continue
        if line.endswith(" [BROKEN]"):
            _fail("Canonical Xbox weapon HUD has an unavailable display dependency",
                  tag=name, missing_tag=line[:-9].replace("\\", "/"))
        result.add(_name(line))
    for dependency in result:
        _path(root, dependency)
    return result


def stock_weapon_hud_overlay(tool, stock, roots, required, workspace, steps,
                             repairs, protected):
    """Produce a stock display overlay for reachable, identified stock weapons."""
    stock, workspace = Path(stock), Path(workspace)
    roots = [Path(root) for root in roots]
    folder, overlay = workspace / "stock-weapon-hud", workspace / "stock-weapon-hud/tags"
    if folder.exists() or folder.is_symlink():
        _fail("Stock weapon HUD output must be fresh", "invalid_output")
    if workspace.is_symlink() or not workspace.is_dir():
        _fail("Stock weapon HUD workspace must be a regular directory", "invalid_output")
    inventories = {root: _tree(root) for root in dict.fromkeys([stock, *roots])}
    for root, inventory in inventories.items():
        for name, expected in inventory.items():
            path = root / name
            if path in protected and protected[path] != expected:
                _fail("A protected weapon presentation input changed", "input_changed", tag=name)
            protected[path] = expected

    def unchanged():
        for root, inventory in inventories.items():
            if _tree(root) != inventory:
                _fail("Weapon HUD reuse changed an input tree", "input_changed")

    tool.stage = "presentation_stock_hud"
    selected, skipped, source_users = {}, [], {}
    for name in sorted(set(required)):
        if not name.endswith(".weapon"):
            continue
        name = _name(name, {"weapon"})
        winning = _winner(roots, name, {"weapon"})
        if winning is None:
            _fail("A reachable authored weapon tag is missing", tag=name)
        root, weapon = winning
        source_hud = _reference(tool.get(root, name, HUD_FIELD), "weapon_hud_interface")
        if source_hud:
            source_hud = _name(source_hud, {"weapon_hud_interface"})
            if source_hud not in required:
                _fail("Authored weapon HUD is absent from the reachable dependency closure",
                      tag=name, hud_tag=source_hud)
            source_users.setdefault(source_hud, []).append(name)
        stock_weapon = stock / name
        if not stock_weapon.exists() and not stock_weapon.is_symlink():
            skipped.append({"weapon": name, "reason": "No same-path original Xbox weapon identity", "authored_hud_preserved": True})
            continue
        _path(stock, name, {"weapon"})
        identity = {}
        for field in IDENTITY_FIELDS:
            source_value = tool.get(root, name, field)
            stock_value = tool.get(stock, name, field)
            identity[field] = {"source": _reference(source_value, "model") if field == "model" else source_value.strip(),
                               "stock": _reference(stock_value, "model") if field == "model" else stock_value.strip()}
        matches = all(value["source"] == value["stock"] for value in identity.values())
        # A missing model/label is not enough evidence for a stock weapon match.
        matches = matches and bool(identity["model"]["source"]) and bool(identity["label"]["source"])
        stock_hud = _reference(tool.get(stock, name, HUD_FIELD), "weapon_hud_interface")
        if not matches or not source_hud or not stock_hud:
            skipped.append({"weapon": name, "identity": identity, "reason": "Weapon identity differs or HUD reference is absent", "authored_hud_preserved": True})
            continue
        stock_hud = _name(stock_hud, {"weapon_hud_interface"})
        _path(stock, stock_hud)
        _winner(roots, source_hud) or _fail("Authored weapon HUD is missing", tag=name, hud_tag=source_hud)
        if source_hud in selected and selected[source_hud]["stock_hud"] != stock_hud:
            _fail("One authored HUD is shared by weapons identifying different canonical Xbox HUDs",
                  hud_tag=source_hud, weapons=selected[source_hud]["weapons"] + [name],
                  stock_hud_tags=[selected[source_hud]["stock_hud"], stock_hud])
        entry = selected.setdefault(source_hud, {"stock_hud": stock_hud, "weapons": [], "identity": {}})
        entry["weapons"].append(name)
        entry["identity"][name] = identity
    # An unmatched custom weapon sharing this HUD retains its authored display.
    for source_hud in list(selected):
        extra = sorted(set(source_users[source_hud]) - set(selected[source_hud]["weapons"]))
        if extra:
            skipped.append({"hud_tag": source_hud, "reason": "Shared HUD also belongs to an unmatched authored weapon",
                            "unmatched_weapons": extra, "authored_hud_preserved": True})
            del selected[source_hud]
    closures, aliases = {}, {}
    for source_hud, entry in selected.items():
        stock_hud = entry["stock_hud"]
        if stock_hud not in closures:
            closures[stock_hud] = _closure(tool, stock, stock_hud)
            key = hashlib.sha256(stock_hud.encode("utf-8")).hexdigest()[:16]
            aliases[stock_hud] = {name: f"{NAMESPACE}/{key}/{name}" for name in closures[stock_hud]}
        for target in aliases[stock_hud].values():
            if _winner(roots, target):
                _fail("Private stock HUD namespace collides with an authored tag", tag=target)
    unchanged()
    if not selected:
        steps.append({"operation": "stock_weapon_hud_reuse", "selection": "Exact weapon path, model reference, weapon type and label",
                      "weapons_reused": 0, "authored_preserved": skipped, "gameplay_tags_replaced": 0})
        return None
    overlay.mkdir(parents=True)
    actions = []
    for stock_hud, names in sorted(closures.items()):
        key = hashlib.sha256(stock_hud.encode("utf-8")).hexdigest()[:16]
        staging = folder / "staging" / key / "tags"
        staging.mkdir(parents=True)
        for name in sorted(names):
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_path(stock, name), target)
            if legacy.digest(target) != inventories[stock][name]:
                _fail("Copied Xbox weapon presentation changed before refactoring", "invalid_output", tag=name)
        args = ["-t", staging, "-M", "move"]
        for name in sorted(names):
            args += ["-T", name, aliases[stock_hud][name]]
        tool.run("refactor", *args)
        expected = set(aliases[stock_hud].values())
        if set(_tree(staging)) != expected:
            _fail("Private stock HUD refactor produced an unexpected file inventory", "invalid_output", hud_tag=stock_hud)
        for name, alias in sorted(aliases[stock_hud].items()):
            path = _path(staging, alias)
            refs = _closure(tool, staging, alias)
            if not refs.issubset(expected):
                _fail("Private stock HUD still references an unisolated dependency", "invalid_output", tag=alias,
                      references=sorted(refs - expected))
            target = overlay / alias
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            actions.append({"kind": "canonical_weapon_display_dependency", "tag": alias, "stock_tag": name,
                            "source_sha256": inventories[stock][name], "sha256_after": legacy.digest(target),
                            "operation": "private_stock_display_copy", "references_private": True})
    for source_hud, entry in sorted(selected.items()):
        stock_hud = entry["stock_hud"]
        canonical = overlay / aliases[stock_hud][stock_hud]
        target = overlay / source_hud
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canonical, target)
        winner = _winner(roots, source_hud)
        refs = _closure(tool, overlay, source_hud) - {source_hud}
        if not refs.issubset(set(aliases[stock_hud].values())):
            _fail("Reused weapon HUD has an unisolated display reference", "invalid_output", tag=source_hud)
        actions.append({"kind": "canonical_weapon_hud", "tag": source_hud, "stock_tag": stock_hud,
                        "weapons": entry["weapons"], "identity": entry["identity"],
                        "identity_criteria": ["exact_weapon_tag_path", *IDENTITY_FIELDS],
                        "source_sha256": inventories[stock][stock_hud],
                        "sha256_before": legacy.digest(winner[1]), "sha256_after": legacy.digest(target),
                        "private_root_alias": aliases[stock_hud][stock_hud],
                        "operation": "stock_weapon_hud_reuse", "gameplay_tags_replaced": 0,
                        "reason": "Reuse the original Xbox HUD for a matching stock weapon"})
    unchanged()
    output = _tree(overlay)
    native_hud_tags = sorted(name for name in output if Path(name).suffix.removeprefix(".") in HUD_CLASSES)
    record = {"schema_version": 1, "operation": "stock_weapon_hud_reuse", "status": "converted",
              "identity_criteria": ["exact_weapon_tag_path", *IDENTITY_FIELDS], "actions": actions,
              "authored_preserved": skipped, "output_sha256": output, "native_hud_tags": native_hud_tags,
              "source_unchanged": True, "gameplay_tags_replaced": 0, "presentation_validation": "pending"}
    manifest = folder / "conversion.json"
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    protected[manifest] = legacy.digest(manifest)
    for name, expected in output.items():
        protected[overlay / name] = expected
    repairs.extend(actions)
    steps.append({"operation": "stock_weapon_hud_reuse", "identity_criteria": record["identity_criteria"],
                  "weapons_reused": sum(len(entry["weapons"]) for entry in selected.values()),
                  "hud_roots_reused": len(selected), "private_display_tags": len(output) - len(selected),
                  "native_hud_tags": native_hud_tags, "authored_preserved": skipped,
                  "gameplay_tags_replaced": 0, "manifest": str(manifest),
                  "manifest_sha256": legacy.digest(manifest), "presentation_validation": "pending"})
    return overlay
