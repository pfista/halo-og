"""Portable, evidence-based tool diagnostics and builder reports.

Parsing supplies only context present in the log. It does not infer dependency
chains, recommend deleting authored content, or claim gameplay validation.
"""
import json
import math
from pathlib import PurePosixPath
import re


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SEVERITIES = frozenset(("error", "warning", "info"))
TAG_EXTENSIONS = (
    "scenario_structure_bsp", "shader_transparent_chicago_extended", "shader_transparent_chicago",
    "shader_transparent_generic", "shader_transparent_glass", "shader_transparent_meter",
    "shader_transparent_water", "shader_transparent_plasma", "shader_environment", "shader_model",
    "weapon_hud_interface", "unit_hud_interface", "grenade_hud_interface", "hud_globals",
    "unicode_string_list", "hud_message_text", "model_animations", "damage_effect", "lens_flare",
    "item_collection", "device_machine", "device_control", "device_light_fixture", "particle_system",
    "sound_looping", "sound_environment", "actor_variant", "scenario", "gbxmodel", "model",
    "bitmap", "sound", "weapon", "biped", "vehicle", "projectile", "equipment", "scenery",
    "effect", "particle", "contrail", "decal", "actor", "globals", "font", "ui_widget_definition",
)
TAG_RE = re.compile(r"(?P<tag>(?:[A-Za-z0-9_ .-]+[\\/])*[A-Za-z0-9_ .-]+\."
                    r"(?:" + "|".join(TAG_EXTENSIONS) + r"))(?=$|[\s'\"),:])", re.I)
ABS_START = r"(?:[A-Za-z]:[\\/]|\\\\|~[A-Za-z0-9_.-]*/|/(?!/))"
ABS_TOKEN = re.compile(r"(?<![A-Za-z0-9:/])" + ABS_START + r"[^\s\"'<>;,)]*")
QUOTED_ABS = re.compile(r"(?P<quote>[\"'])(?P<path>" + ABS_START + r"[^\"'\n]+)(?P=quote)")
FILE_URL = re.compile(r"file://[^\s\"'<>;,)]*", re.I)
ASSET_KEYS = frozenset(("asset_bytes", "raw_bytes", "payload", "binary_data", "base64",
                        "blob", "pixels", "sample_data", "script_source", "source_text"))


def _portable_path(value):
    normalized = value.replace("\\", "/")
    # Tag identities remain useful after removing their private extraction root.
    for root in ("/source-tags/", "/stock-tags/", "/tags/"):
        if root in normalized:
            return normalized.rsplit(root, 1)[1]
    name = normalized.rstrip("/").rsplit("/", 1)[-1]
    return "<local-path>" + ("/" + name if name else "")


def portable_text(value):
    """Remove terminal controls and absolute local paths, preserving tag context."""
    value = ANSI.sub("", str(value))
    value = "".join(character for character in value if ord(character) >= 32 or character in "\n\t")
    # A standalone path may include spaces. Quoted paths are handled before
    # token paths; URLs never match the absolute-path starting boundary.
    if re.match(r"^" + ABS_START, value):
        return _portable_path(value)
    value = FILE_URL.sub(lambda m: _portable_path(m[0][7:]), value)
    value = QUOTED_ABS.sub(lambda m: m["quote"] + _portable_path(m["path"]) + m["quote"], value)
    return ABS_TOKEN.sub(lambda m: _portable_path(m[0]), value)


def diagnostic(code, stage, message, tag=None, tag_type=None, field=None, value=None,
               dependency_chain=None, suggested_fix=None, severity="error"):
    if severity not in SEVERITIES:
        raise ValueError("Diagnostic severity must be error, warning or info")
    if not all(isinstance(item, str) and item for item in (code, stage, message)):
        raise ValueError("Diagnostics require nonempty code, stage and message")
    result = {"code": code, "stage": stage, "severity": severity, "message": portable_text(message)}
    for key, item in (("tag", tag), ("tag_type", tag_type), ("field", field),
                      ("value", value), ("dependency_chain", dependency_chain), ("suggested_fix", suggested_fix)):
        if item is not None:
            result[key] = _sanitize(item)
    return result


def _tag_in(line, known_tags):
    normalized = line.replace("\\", "/")
    found = [tag for tag in known_tags if tag.replace("\\", "/") in normalized]
    if len(found) == 1:
        return portable_text(found[0]).replace("\\", "/")
    # RIAT reports the group and extensionless path separately.
    missing = re.search(r"(?:can(?:not|'t)|could not) find ([a-z_]+) tag [\"']([^\"']+)[\"']", line, re.I)
    if missing and missing[1].lower() in TAG_EXTENSIONS:
        return portable_text(missing[2] + "." + missing[1].lower()).replace("\\", "/")
    # Prefer the explicit context forms emitted by Invader over arbitrary
    # phrases preceding a filename, which may contain legitimate spaces.
    context = re.search(r"(?:\.\.\.in|[Ff]ailed to (?:compile tag|find|open))\s+(.+?)\s*$", line)
    if context:
        candidate = context[1].strip(" '\"").replace("\\", "/")
        if any(candidate.lower().endswith("." + extension) for extension in TAG_EXTENSIONS):
            return portable_text(candidate)
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", line)
    candidates = [portable_text(candidate).replace("\\", "/") for candidate in quoted
                  if any(candidate.lower().endswith("." + extension) for extension in TAG_EXTENSIONS)]
    return candidates[0] if len(set(candidates)) == 1 else None


def _classify(message):
    lower = message.lower()
    if (re.search(r"(?:failed to find|can(?:not|'t) find|missing|not found)", lower)
            and ("tag" in lower or TAG_RE.search(message))):
        return "missing_tag", "Supply the matching dependency from the reviewed source/resource set."
    if "function" in lower and any(word in lower for word in ("unknown", "unrecognized", "unsupported", "undefined", "not found", "not available", "does not exist")):
        return "unsupported_hs_function", "Review the script against Xbox HSC APIs; retain required behavior or record a scoped omission."
    if any(codec in lower for codec in ("ogg vorbis", "ima adpcm", "16-bit pcm", "16 bit pcm", "codec", "sound format")):
        return "sound_codec", "Review the source sound format and apply a pinned Xbox-compatible codec conversion where needed."
    if re.search(r"\b(?:field|[A-Za-z0-9_]+::[A-Za-z0-9_]+)\b", message) and any(word in lower for word in ("invalid", "must", "bounds", "exceeds")):
        return "invalid_tag_field", "Inspect the named field and expected bounds; add only a reviewed profile correction."
    if "target engine" in lower or "tags are unimplemented" in lower:
        return "unsupported_tag_layout", "Review a supported layout conversion or report this required dependency as unsupported."
    return "tool_error", "Inspect the recorded tool diagnostic and dependency context before changing the profile."


def parse_tool_output(output, stage, known_tags=()):
    """Parse Invader/RIAT errors, including wrapped messages and ...in context."""
    if not isinstance(output, str):
        raise ValueError("Tool output must be text")
    known_tags = tuple(str(tag) for tag in known_tags)
    entries = []
    active = None
    for original in ANSI.sub("", output).splitlines():
        line = original.strip()
        if not line:
            active = None
            continue
        if line.startswith("...in "):
            if active is not None:
                tag = _tag_in(line, known_tags)
                if tag:
                    active["tag"] = tag
                    active["tag_type"] = PurePosixPath(tag).suffix[1:]
            active = None
            continue
        warning = bool(re.search(r"\bwarning(?:\s*\(minor\))?\s*:", line, re.I))
        error = bool(re.search(r"\b(?:fatal\s+)?error\s*:", line, re.I))
        failure = bool(re.match(r"(?:Failed|Cannot|Unable)\b", line, re.I))
        if not (warning or error or failure):
            # Invader wraps diagnostic paragraphs at terminal width. Keep the
            # text, but do not attach an unrelated successful progress line.
            if active is not None and not re.match(r"(?:Successfully|Compiled|Extracted|Built|Building|Extracting|Loading)\b", line):
                active["message"] += " " + portable_text(line)
            else:
                active = None
            continue
        tag = _tag_in(line, known_tags)
        code, fix = _classify(line)
        if warning and code == "tool_error":
            code = "tool_warning"
        active = diagnostic(code, stage, line, tag=tag,
                            tag_type=PurePosixPath(tag).suffix[1:] if tag else None,
                            suggested_fix=fix, severity="warning" if warning else "error")
        explicit = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*::[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)\b", line)
        if explicit:
            active["field"] = explicit[1]
        else:
            explicit = re.search(r"\bfield\s+['\"]([^'\"]+)['\"]", line, re.I)
            if explicit:
                active["field"] = portable_text(explicit[1])
        value_match = re.search(r"\b(?:value|got)\s*[:=]\s*([^,;]+)", line, re.I)
        if value_match:
            active["value"] = portable_text(value_match[1].strip())
        entries.append(active)
    for entry in entries:
        # Reclassify only from the completed paragraph, because wrapped codec
        # or function names may not occur on its first line.
        code, fix = _classify(entry["message"])
        entry["code"] = "tool_warning" if code == "tool_error" and entry["severity"] == "warning" else code
        entry["suggested_fix"] = fix
    return entries


def _sanitize(value, depth=0):
    if depth > 32:
        return "<omitted-deep-value>"
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key = str(key)
            if key.lower() in ASSET_KEYS and not (
                    (key.lower() == "script_source" and item in ("tags", "data", "recovered", "preserved"))
                    or (key.lower() == "pixels" and type(item) is int and item >= 0)):
                continue
            clean_key = portable_text(key)
            if clean_key in result:
                suffix = 2
                while f"{clean_key} ({suffix})" in result:
                    suffix += 1
                clean_key = f"{clean_key} ({suffix})"
            result[clean_key] = _sanitize(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in value if not isinstance(item, (bytes, bytearray, memoryview))]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<omitted-asset-bytes>"
    if isinstance(value, str):
        return portable_text(value)
    if type(value) is float and not math.isfinite(value):
        return "<omitted-nonfinite-value>"
    if value is None or type(value) in (bool, int, float):
        return value
    return portable_text(value)


def shareable_report(record):
    """Copy a report without absolute local paths or raw embedded asset data."""
    if not isinstance(record, dict):
        raise ValueError("A shareable report must be an object")
    return _sanitize(record)


def _inline(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("`", "'").replace("\n", " ").replace("\r", " ")


def render_report(record):
    """Render a portable builder-facing Markdown report without raw tool logs."""
    record = shareable_report(record)
    lines = ["# Map conversion report", "", f"Map: `{_inline(record.get('id', 'unknown'))}`",
             f"Status: **{_inline(record.get('status', 'unknown'))}**", "",
             "Gameplay validation: **" + _inline(record.get("gameplay_validation", "pending")) + "**.",
             "Compilation and static checks do not establish gameplay acceptance."]
    for label, value in (("Source", record.get("source")), ("Profile", record.get("profile"))):
        if isinstance(value, dict):
            identity = {key: item for key, item in value.items()
                        if key in ("id", "version", "format", "build", "sha256")}
            lines += ["", f"{label}: `{_inline(identity)}`"]
    entries = record.get("diagnostics", [])
    groups = (("Blockers", [item for item in entries if isinstance(item, dict) and item.get("severity", "error") == "error"]),
              ("Warnings", [item for item in entries if isinstance(item, dict) and item.get("severity") == "warning"]),
              ("Notes", [item for item in entries if isinstance(item, dict) and item.get("severity") == "info"]),
              ("Repairs", record.get("repairs", [])), ("Omissions", record.get("omissions", [])))
    for label, items in groups:
        if label == "Notes" and not items:
            continue
        lines += ["", "## " + label, ""]
        if not items:
            lines.append("None recorded.")
            continue
        for item in items:
            if not isinstance(item, dict):
                lines.append("- " + _inline(item))
                continue
            message = item.get("message", item.get("reason", item.get("operation", "Recorded change")))
            context = [f"{key}: {_inline(item[key])}" for key in ("code", "stage", "tag", "tag_type", "field", "value", "dependency_chain", "status", "counts_before", "counts_after") if key in item]
            lines.append("- " + _inline(message) + (" (" + "; ".join(context) + ")" if context else ""))
            if item.get("suggested_fix"):
                lines.append("  Suggested next step: " + _inline(item["suggested_fix"]))
    return "\n".join(lines) + "\n"
