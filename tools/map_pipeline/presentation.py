"""Explicit Xbox shell presentation for imported multiplayer caches.

The overlay uses only the verified stock UI dependency tree. Authored gameplay
tags and all unselected multiplayer strings remain independent and unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import zlib

from .backend import ConversionError, _tree, legacy

digest = legacy.digest


PAUSE_PREFIX = "ui/shell/multiplayer_game/pause_game/"
COLLECTION = "ui/shell/multiplayer.ui_widget_collection"
IMPLICIT_COLLECTION = "ui/ui_tags_loaded_multiplayer_scenario_type.tag_collection"
TEXT_TAG = "ui/multiplayer_game_text.unicode_string_list"
SEEDS = (
    *(PAUSE_PREFIX + f"{players}p_pause_game.ui_widget_definition" for players in (1, 2, 4)),
    COLLECTION,
    "ui/small_ui.font", "ui/large_ui.font",
    "ui/shell/bitmaps/menu_bkds.bitmap",
    *(f"ui/shell/bitmaps/pausebox2_{piece}.bitmap" for piece in ("left", "center", "right")),
    "ui/shell/bitmaps/semi_transparent_grey.bitmap",
    "ui/shell/main_menu/button_key_sm.ui_widget_definition",
    PAUSE_PREFIX + "quit_netgame_button.ui_widget_definition",
)
ALLOWED_CLASSES = frozenset({"ui_widget_definition", "ui_widget_collection", "tag_collection",
                             "font", "bitmap", "unicode_string_list", "string_list",
                             "sound", "sound_looping"})
# Native NTSC maps contain only 36 entries. These native fallback values come
# from source/text/text_group.c at the same indices; tokens are Xbox UI tokens.
FALLBACK_TEXT = {72: "\t%b-button =quit    %a-button =pick game",
                 73: "\t%b-button =quit", 100: "Hold BACK for score"}
REASON = "Canonical Xbox engine UI for the selected native-xbox presentation policy"


def _fail(message: str, code: str = "needs_profile", **details):
    raise ConversionError(code, "presentation", message, details)


def _name(value: str) -> str:
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {".", ".."} for part in path.parts)
            or any(char in value for char in "\t\r\n\0:")
            or path.suffix.removeprefix(".") not in ALLOWED_CLASSES):
        _fail("Canonical shell dependency is outside the allowed UI tag classes", tag=value)
    return value


def _path(root: Path, name: str) -> Path:
    name = _name(name)
    at = root
    if at.is_symlink() or not at.is_dir():
        _fail("Expected a regular UI tag directory")
    for part in PurePosixPath(name).parts:
        at /= part
        if at.is_symlink():
            _fail("Linked UI inputs are not supported", tag=name)
    if not at.is_file() or at.stat().st_nlink != 1:
        _fail("A canonical Xbox UI dependency is missing or linked", tag=name)
    return at


def _winner(roots: list[Path], name: str) -> Path | None:
    for root in roots:
        path = root / name
        if path.exists() or path.is_symlink():
            return _path(root, name)
    return None


def _dependencies(tool, root: Path, name: str) -> set[str]:
    return {_name(line.strip()) for line in
            tool.run("dependency", "-r", "-t", root, name).splitlines() if line.strip()}


def _unicode(data: bytes) -> tuple[bytes, bytes, list[bytes], list[bytes]]:
    """Parse bounded, sequential HEK ustr data without discarding any metadata.

    HEK fields are big endian, while string payloads are UTF-16LE. Serialized
    tags contain the 12-byte reflexive, all 20-byte data descriptors, then each
    payload in descriptor order (Invader UnicodeStringList definition).
    """
    if (len(data) < 76 or data[36:40] != b"ustr" or data[60:64] != b"blam"
            or struct.unpack_from(">I", data, 44)[0] != 64
            or struct.unpack_from(">H", data, 56)[0] != 1):
        _fail("Invalid HEK multiplayer Unicode header")
    count = struct.unpack_from(">I", data, 64)[0]
    if count > 800 or len(data) < 76 + count * 20:
        _fail("Multiplayer Unicode entry count exceeds its bounded data")
    headers, values = [], []
    cursor = 76 + count * 20
    for index in range(count):
        descriptor = data[76 + index * 20:96 + index * 20]
        size = struct.unpack_from(">I", descriptor)[0]
        if size < 2 or size > 32768 or size % 2 or size > len(data) - cursor:
            _fail("Multiplayer Unicode entry has invalid bounds", index=index)
        value = data[cursor:cursor + size]
        cursor += size
        try:
            decoded = value.decode("utf-16-le")
        except UnicodeDecodeError as error:
            _fail("Multiplayer Unicode entry has invalid UTF-16", index=index)
            raise AssertionError from error
        if not decoded.endswith("\0") or "\0" in decoded[:-1]:
            _fail("Multiplayer Unicode entry has invalid null termination", index=index)
        headers.append(descriptor)
        values.append(value)
    if cursor != len(data):
        _fail("Multiplayer Unicode tag has unparsed trailing data")
    return data[:64], data[64:76], headers, values


def _replace_unicode(data: bytes, replacements: dict[int, bytes]) -> bytes:
    header, reflexive, descriptors, values = _unicode(data)
    result_descriptors = list(descriptors)
    result_values = list(values)
    for index, value in replacements.items():
        if type(index) is not int or not 0 <= index < len(values):
            _fail("Selected multiplayer Unicode entry is absent", index=index)
        result_descriptors[index] = struct.pack(">I", len(value)) + descriptors[index][4:]
        result_values[index] = value
    body = reflexive + b"".join(result_descriptors) + b"".join(result_values)
    result = bytearray(header + body)
    # Invader HEK tags store the complement of the ordinary IEEE CRC32.
    struct.pack_into(">I", result, 40, zlib.crc32(body) ^ 0xFFFFFFFF)
    parsed_header, parsed_reflexive, parsed_descriptors, parsed_values = _unicode(bytes(result))
    if (parsed_header[:40] != header[:40] or parsed_header[44:] != header[44:]
            or parsed_reflexive != reflexive or parsed_descriptors != result_descriptors
            or parsed_values != result_values):
        _fail("Multiplayer Unicode output failed preservation verification", "invalid_output")
    return bytes(result)


def canonical_shell_overlay(tool, stock: Path, roots: list[Path], workspace: Path,
                            steps: list, repairs: list, protected: dict) -> Path:
    """Create a fresh, first-root-wins UI overlay; never mutate supplied trees."""
    stock, workspace = Path(stock), Path(workspace)
    roots = [Path(root) for root in roots]
    folder, overlay = workspace / "native-shell", workspace / "native-shell/tags"
    if folder.exists() or folder.is_symlink():
        _fail("Native shell output must be fresh", "invalid_output")
    if workspace.is_symlink() or not workspace.is_dir():
        _fail("Native shell workspace must be a regular directory", "invalid_output")
    snapshots = {root: _tree(root) for root in dict.fromkeys([stock, *roots])}
    for root, inventory in snapshots.items():
        for name, expected in inventory.items():
            path = root / name
            if path in protected and protected[path] != expected:
                _fail("Protected input changed before shell conversion", "input_changed", tag=name)
            protected[path] = expected

    def verify_inputs():
        for root, inventory in snapshots.items():
            try:
                unchanged = _tree(root) == inventory
            except (OSError, ValueError):
                unchanged = False
            if not unchanged:
                _fail("Input tags changed during shell conversion", "input_changed")
        for path, expected in protected.items():
            try:
                unchanged = digest(path) == expected
            except OSError:
                unchanged = False
            if not unchanged:
                _fail("Protected input changed during shell conversion", "input_changed")

    tool.stage = "presentation"
    selected = set(SEEDS)
    for name in SEEDS:
        _path(stock, name)
        selected.update(_dependencies(tool, stock, name))
    for name in selected:
        _path(stock, name)
    verify_inputs()
    overlay.mkdir(parents=True)
    actions = []
    for name in sorted(selected):
        source, before = _path(stock, name), _winner(roots, name)
        target = overlay / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        expected = snapshots[stock][name]
        if digest(target) != expected:
            _fail("Canonical Xbox UI copy differs from its source", "invalid_output", tag=name)
        actions.append({"kind": "canonical_engine_ui", "operation": "native_shell_overlay",
                        "tag": name, "source": "stock_xbox", "source_sha256": expected,
                        "sha256_before": digest(before) if before else None,
                        "sha256_after": expected, "reason": REASON,
                        "payload_copy_exact": True})

    # Xbox Invader builds compile Soul implicitly, rather than the PC/MCC
    # ui_tags_loaded_* collection. Preserve every canonical reference and append
    # only the native lookup seeds not already present in this compiled root.
    count = int(tool.run("edit", "-t", overlay, "-C", "tags", COLLECTION))
    if not 0 <= count <= 200:
        _fail("Canonical widget collection exceeds its reference limit", "invalid_output")
    original_references = [_name(tool.run("edit", "-t", overlay, "-G", f"tags[{index}].reference", COLLECTION).strip())
                           for index in range(count)]
    additions = [name for name in SEEDS if name != COLLECTION and name not in original_references]
    if len(additions) + count > 200:
        _fail("Native UI residency exceeds the widget collection reference limit")
    if additions:
        args = ["-t", overlay, "-I", "tags", len(additions), "end"]
        for index, name in enumerate(additions, count):
            args += ["-S", f"tags[{index}].reference", name]
        tool.run("edit", *args, COLLECTION)
    expected_references = original_references + additions
    actual_count = int(tool.run("edit", "-t", overlay, "-C", "tags", COLLECTION))
    if actual_count != len(expected_references):
        _fail("Compiled Xbox UI collection has an unexpected entry count", "invalid_output")
    for index, name in enumerate(expected_references):
        actual = _name(tool.run("edit", "-t", overlay, "-G", f"tags[{index}].reference", COLLECTION).strip())
        if actual != name:
            _fail("Compiled Xbox UI collection changed a canonical reference", "invalid_output")
    compiled_resident = _dependencies(tool, overlay, COLLECTION)
    if (not (set(SEEDS) - {COLLECTION}).issubset(compiled_resident)
            or not compiled_resident.issubset(selected)):
        _fail("Compiled Xbox UI residency differs from its stock-only closure", "invalid_output")
    action = next(item for item in actions if item["tag"] == COLLECTION)
    action.update(sha256_after=digest(overlay / COLLECTION), payload_copy_exact=not additions,
                  inserted_references=additions, existing_references_preserved=True,
                  compiled_residency_root=True,
                  reason=REASON + "; append missing UI lookup dependencies to the Xbox implicit Soul root")

    # These engine lookups have no authored widget edges. Make them resident via
    # a minimal PC/MCC audit collection too. This collection is deliberately not
    # referenced by Soul, avoiding a cycle and any change to Xbox compiler pins.
    collection_target = overlay / IMPLICIT_COLLECTION
    collection_target.parent.mkdir(parents=True, exist_ok=True)
    template = stock / IMPLICIT_COLLECTION
    existing = _winner(roots, IMPLICIT_COLLECTION)
    args = ["-t", overlay, "-n"]
    template_hash = None
    if template.exists() or template.is_symlink():
        template = _path(stock, IMPLICIT_COLLECTION)
        shutil.copyfile(template, collection_target)
        template_hash = digest(template)
        args += ["-E", "tags[*]"]
    else:
        args += ["-N"]
    args += ["-I", "tags", len(SEEDS), "0"]
    for index, name in enumerate(SEEDS):
        args += ["-S", f"tags[{index}].reference", name]
    tool.run("edit", *args, IMPLICIT_COLLECTION)
    if int(tool.run("edit", "-t", overlay, "-C", "tags", IMPLICIT_COLLECTION)) != len(SEEDS):
        _fail("Native shell residency collection has an unexpected entry count", "invalid_output")
    for index, name in enumerate(SEEDS):
        value = tool.run("edit", "-t", overlay, "-G", f"tags[{index}].reference", IMPLICIT_COLLECTION)
        if _name(value.strip()) != name:
            _fail("Native shell residency collection contains an unexpected reference", "invalid_output")
    resident = _dependencies(tool, overlay, IMPLICIT_COLLECTION)
    if not set(SEEDS).issubset(resident) or not resident.issubset(selected | {IMPLICIT_COLLECTION}):
        _fail("Native shell residency dependencies differ from the stock UI closure", "invalid_output")
    actions.append({"kind": "canonical_engine_ui", "operation": "native_shell_residency",
                    "tag": IMPLICIT_COLLECTION, "source": "stock_xbox" if template_hash else "generated_ui_collection",
                    "source_sha256": template_hash, "sha256_before": digest(existing) if existing else None,
                    "sha256_after": digest(collection_target), "references": list(SEEDS),
                    "reason": "Make canonical UI lookup assets resident without importing gameplay references",
                    "payload_copy_exact": False})

    # Select only the three strings consumed with Xbox button semantics. Keep
    # missing entries absent so the native fallback continues to supply them.
    authored = _winner(roots, TEXT_TAG)
    stock_text = stock / TEXT_TAG
    canonical_values = _unicode(_path(stock, TEXT_TAG).read_bytes())[3] if stock_text.exists() else []
    if authored:
        source_bytes = authored.read_bytes()
        source_values = _unicode(source_bytes)[3]
        replacements, string_actions = {}, []
        for index, fallback in FALLBACK_TEXT.items():
            if index >= len(source_values):
                continue
            canonical = canonical_values[index] if index < len(canonical_values) else (fallback + "\0").encode("utf-16-le")
            if source_values[index] == canonical:
                continue
            replacements[index] = canonical
            string_actions.append({"index": index, "before": source_values[index].decode("utf-16-le")[:-1],
                                   "after": canonical.decode("utf-16-le")[:-1],
                                   "origin": "stock_xbox" if index < len(canonical_values) else "native_ntsc_fallback",
                                   "reason": "Match the native Xbox score/postgame text consumer"})
        if replacements:
            target = overlay / TEXT_TAG
            if target.exists():
                _fail("Stock shell closure unexpectedly selects the authored game text", "invalid_output")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_replace_unicode(source_bytes, replacements))
            if int(tool.run("edit", "-t", overlay, "-C", "strings", TEXT_TAG)) != len(source_values):
                _fail("Native parser changed the multiplayer Unicode entry count", "invalid_output")
            actions.append({"kind": "native_multiplayer_text", "operation": "native_shell_text",
                            "tag": TEXT_TAG, "source": "authored", "source_sha256": digest(authored),
                            "sha256_before": digest(authored), "sha256_after": digest(target),
                            "actions": string_actions, "entries_replaced": len(replacements),
                            "entries_preserved": len(source_values) - len(replacements),
                            "unselected_entries_exact": True, "unselected_metadata_exact": True,
                            "native_reparse_verified": True, "reason": "Native Xbox button and score prompts"})
    verify_inputs()
    output_files = _tree(overlay)
    if any(_name(name) != name for name in output_files):
        _fail("Native shell output includes an unsafe dependency", "invalid_output")
    record = {"schema_version": 1, "operation": "canonical_native_shell", "status": "converted",
              "policy": "native-xbox", "stock_tags_sha256": {name: snapshots[stock][name] for name in sorted(selected)},
              "output_sha256": output_files, "actions": actions, "source_unchanged": True,
              "engine_rules_changed": False, "presentation_validation": "pending"}
    manifest = folder / "conversion.json"
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    repairs.extend(actions)
    steps.append({"operation": "canonical_native_shell", "policy": "native-xbox", "ui_tags": len(selected),
                  "text_entries_replaced": sum(action.get("entries_replaced", 0) for action in actions),
                  "source_unchanged": True, "manifest": str(manifest), "manifest_sha256": digest(manifest),
                  "presentation_validation": "pending"})
    return overlay
