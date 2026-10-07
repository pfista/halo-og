"""Select the original Xbox global HUD number provider without sharing its atlas.

Native interface.c consumes interface_bitmaps[0].hud_digits_definition. Other
interface records, authored weapon registries and shared bitmap names remain
unchanged. This is an explicit presentation policy, independent of cache format.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from .backend import ConversionError, _tree, legacy

GLOBALS = "globals/globals.globals"
FIELD = "interface_bitmaps[0].hud_digits_definition"
NAMESPACE = "__native_hud/stock"
DISPLAY_CLASSES = frozenset({"hud_number", "bitmap"})


def _fail(message, code="needs_profile", **details):
    raise ConversionError(code, "presentation_hud_digits", message, details)


def _name(value, classes=DISPLAY_CLASSES):
    if not isinstance(value, str):
        _fail("HUD digits reference is not a tag path")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(char in value for char in "\t\r\n\0:")
            or path.suffix.removeprefix(".") not in classes):
        _fail("HUD digits dependency has an unsafe path or unsupported class", tag=value)
    return value


def _path(root, name, classes=DISPLAY_CLASSES):
    name = _name(name, classes)
    at = Path(root)
    if at.is_symlink() or not at.is_dir():
        _fail("Expected a regular HUD digits input directory")
    for part in PurePosixPath(name).parts:
        at /= part
        if at.is_symlink():
            _fail("Linked HUD digits inputs are unsupported", tag=name)
    if not at.is_file() or at.stat().st_nlink != 1:
        _fail("Required HUD digits tag is missing or linked", tag=name)
    return at


def _winner(roots, name, classes=DISPLAY_CLASSES):
    for root in roots:
        if (root / name).exists() or (root / name).is_symlink():
            return root, _path(root, name, classes)
    return None


def _reference(value, tag_class):
    if not isinstance(value, str):
        _fail("HUD digits reference is not text")
    value = value.replace("\\", "/").strip()
    return "" if value in {"", "." + tag_class} else _name(value, {tag_class})


def _closure(tool, root, name):
    names = {name}
    for line in tool.run("dependency", "-r", "-t", root, name).splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith(" [BROKEN]"):
            _fail("Canonical Xbox HUD digits dependency is unavailable", tag=name,
                  missing_tag=line[:-9].replace("\\", "/"))
        names.add(_name(line))
    for dependency in names:
        _path(root, dependency)
    return names


def _without_reference(dump, field, active_interface=False):
    """Compare every parsed value except one explicitly selected dependency.

Invader's -L output uses four-character tree prefixes per nesting level. Keep
all other lines verbatim; even inactive interface records remain in the proof.
"""
    kept, removed, in_active = [], 0, False
    for line in dump.splitlines():
        match = re.match(r"([ │├└─]*)([A-Za-z_][A-Za-z_0-9]*)(.*)$", line)
        if not match:
            _fail("Cannot verify the parsed HUD digits field inventory", "invalid_output")
        prefix, name, rest = match.groups()
        if len(prefix) % 4:
            _fail("Cannot verify HUD digits parser nesting", "invalid_output")
        depth = len(prefix) // 4
        if active_interface and depth <= 1:
            in_active = depth == 1 and name == "interface_bitmaps" and rest.startswith("[0]")
        selected = name == field and ((in_active and depth == 2) if active_interface else depth == 0)
        if selected:
            if not rest.lstrip().startswith("("):
                _fail("Selected HUD digits field is not a parsed dependency", "invalid_output")
            removed += 1
        else:
            kept.append(line.rstrip())
    if removed != 1:
        _fail("Expected exactly one active HUD digits dependency in the parsed inventory",
              "invalid_output", field=FIELD if active_interface else field, occurrences=removed)
    return kept


def _active(tool, root):
    count = tool.count(root, GLOBALS, "interface_bitmaps")
    if not isinstance(count, int) or isinstance(count, bool) or not 0 < count <= 65535:
        _fail("Globals needs an addressable active interface record 0 for HUD digits",
              tag=GLOBALS, field="interface_bitmaps", count=count,
              suggested_fix="Supply Globals with a valid interface_bitmaps[0] record")
    return count, _reference(tool.get(root, GLOBALS, FIELD), "hud_number")


def canonical_hud_digits_overlay(tool, stock, roots, workspace, steps, repairs, protected):
    """Copy a verified stock number definition/atlas and edit only active Globals."""
    stock, workspace = Path(stock), Path(workspace)
    roots = [Path(root) for root in roots]
    folder, overlay = workspace / "native-hud-digits", workspace / "native-hud-digits/tags"
    if folder.exists() or folder.is_symlink():
        _fail("HUD digits output must be fresh", "invalid_output")
    if workspace.is_symlink() or not workspace.is_dir():
        _fail("HUD digits workspace must be a regular directory", "invalid_output")
    inventories = {}
    for root in dict.fromkeys([stock, *roots]):
        try:
            inventory = _tree(root)
        except (OSError, ValueError) as error:
            _fail(str(error), "invalid_input")
        inventories[root] = inventory
        for name, expected in inventory.items():
            path = root / name
            if path in protected and protected[path] != expected:
                _fail("A protected HUD digits input changed", "input_changed", tag=name)
            protected[path] = expected

    def unchanged():
        for root, expected in inventories.items():
            try:
                same = _tree(root) == expected
            except (OSError, ValueError):
                same = False
            if not same:
                _fail("HUD digits selection changed an input tree", "input_changed")

    tool.stage = "presentation_hud_digits"
    _path(stock, GLOBALS, {"globals"})
    winning = _winner(roots, GLOBALS, {"globals"})
    if winning is None:
        _fail("The effective authored Globals tag is missing", tag=GLOBALS)
    source_root, source_globals = winning
    stock_count, stock_hud = _active(tool, stock)
    source_count, source_hud = _active(tool, source_root)
    if not stock_hud:
        _fail("Canonical Xbox Globals has no active HUD number provider", tag=GLOBALS, field=FIELD)
    _path(stock, stock_hud)
    bitmap = _reference(tool.get(stock, stock_hud, "digits_bitmap"), "bitmap")
    if not bitmap:
        _fail("Canonical Xbox HUDNumber has no digits bitmap", tag=stock_hud, field="digits_bitmap")
    names = _closure(tool, stock, stock_hud)
    if names != {stock_hud, bitmap} or _closure(tool, stock, bitmap) != {bitmap}:
        _fail("Canonical HUD digits must contain the verified HUDNumber and bitmap pair only",
              tag=stock_hud, dependencies=sorted(names))
    hashes = {name: inventories[stock][name] for name in sorted(names)}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    aliases = {name: f"{NAMESPACE}/{fingerprint}/{name}" for name in names}
    globals_before = tool.run("edit", "-t", source_root, "-L", GLOBALS)
    donor_before = tool.run("edit", "-t", stock, "-L", stock_hud)
    unchanged()
    overlay.mkdir(parents=True)
    for name in sorted(names):
        target = overlay / aliases[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_path(stock, name), target)
        if legacy.digest(target) != hashes[name]:
            _fail("Copied Xbox HUD digits payload differs from its donor", "invalid_output", tag=name)
    tool.run("edit", "-t", overlay, "-S", "digits_bitmap", aliases[bitmap], aliases[stock_hud])
    if _reference(tool.get(overlay, aliases[stock_hud], "digits_bitmap"), "bitmap") != aliases[bitmap]:
        _fail("Private HUDNumber bitmap reference was not written", "invalid_output", tag=aliases[stock_hud])
    donor_after = tool.run("edit", "-t", overlay, "-L", aliases[stock_hud])
    if _without_reference(donor_before, "digits_bitmap") != _without_reference(donor_after, "digits_bitmap"):
        _fail("Private HUDNumber changed a native metric or another authored field", "invalid_output", tag=aliases[stock_hud])
    if legacy.digest(overlay / aliases[bitmap]) != hashes[bitmap]:
        _fail("The canonical HUD digits bitmap was modified", "invalid_output", tag=aliases[bitmap])
    if _closure(tool, overlay, aliases[stock_hud]) != set(aliases.values()):
        _fail("Private HUD digits provider has an unisolated dependency", "invalid_output")
    for name, alias in aliases.items():
        existing = _winner(roots, alias)
        if existing and (source_hud != aliases[stock_hud] or legacy.digest(existing[1]) != legacy.digest(overlay / alias)):
            _fail("Private HUD digits namespace collides with an authored tag", tag=alias,
                  suggested_fix="Remove or rename the conflicting authored private-namespace tag")
    target_globals = overlay / GLOBALS
    target_globals.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_globals, target_globals)
    tool.run("edit", "-t", overlay, "-S", FIELD, aliases[stock_hud], GLOBALS)
    after_count, after_hud = _active(tool, overlay)
    if after_count != source_count or after_hud != aliases[stock_hud]:
        _fail("Active Globals HUD digits selection was not preserved", "invalid_output", tag=GLOBALS, field=FIELD)
    globals_after = tool.run("edit", "-t", overlay, "-L", GLOBALS)
    if _without_reference(globals_before, "hud_digits_definition", True) != _without_reference(globals_after, "hud_digits_definition", True):
        _fail("HUD digits selection changed another Globals field or inactive interface record", "invalid_output", tag=GLOBALS)
    unchanged()
    output = _tree(overlay)
    expected_output = {GLOBALS, *aliases.values()}
    if set(output) != expected_output:
        _fail("HUD digits overlay contains unexpected files", "invalid_output")
    actions = [{"operation": "canonical_hud_digits_dependency", "tag": aliases[name], "stock_tag": name,
                "source_sha256": hashes[name], "sha256_after": output[aliases[name]],
                "reason": "Use the original Xbox HUD number definition and exact atlas in a private namespace",
                "bitmap_bytes_exact": name == bitmap, "native_metrics_preserved": True}
               for name in sorted(names)]
    actions.append({"operation": "canonical_hud_digits_reference", "tag": GLOBALS, "field": FIELD,
                    "source_sha256": inventories[source_root][GLOBALS], "sha256_before": inventories[source_root][GLOBALS],
                    "sha256_after": output[GLOBALS], "reference_before": source_hud or None,
                    "reference_after": aliases[stock_hud], "inactive_interfaces_preserved": True,
                    "other_globals_fields_preserved": True, "weapon_registry_preserved": True,
                    "reason": "The native number renderer consumes the active Globals HUD digits provider"})
    record = {"schema_version": 1, "operation": "canonical_hud_digits", "status": "converted",
              "source_snapshots": [{"root": str(root), "sha256": inventory} for root, inventory in inventories.items()],
              "stock_globals_sha256": inventories[stock][GLOBALS], "stock_interface_count": stock_count,
              "authored_interface_count": source_count, "active_interface_index": 0,
              "stock_hud_number": stock_hud, "stock_digits_bitmap": bitmap,
              "actions": actions, "output_sha256": output, "native_hud_tags": [aliases[stock_hud]],
              "source_unchanged": True, "presentation_validation": "pending"}
    manifest = folder / "conversion.json"
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    protected[manifest] = legacy.digest(manifest)
    protected.update({overlay / name: value for name, value in output.items()})
    repairs.extend(actions)
    steps.append({"operation": "canonical_hud_digits", "status": "converted", "active_interface_index": 0,
                  "authored_interface_count": source_count, "native_hud_tags": [aliases[stock_hud]],
                  "private_display_tags": len(names), "weapon_registry_preserved": True,
                  "manifest": str(manifest), "manifest_sha256": legacy.digest(manifest),
                  "presentation_validation": "pending"})
    return overlay
