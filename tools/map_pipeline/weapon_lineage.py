"""Reviewed asset variants, bound to immutable extracted tag contents.

The catalog supplies review evidence, not an origin inference from a filename.
A community exception records user approval separately from Halo 1 ancestry.
A matching unsupported/unverified entry is still a blocked policy outcome.
"""
from __future__ import annotations

import copy
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

MAX_CATALOG_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 512
MAX_CLOSURE_TAGS = 8192
OUTCOMES = frozenset({"canonical-stock", "original-completion", "approved-community", "omit", "unsupported", "unverified"})
ORIGINAL_ADMITTED = frozenset({"canonical-stock", "original-completion"})
ADMITTED = ORIGINAL_ADMITTED | {"approved-community"}
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
THREAD_REFERENCE = re.compile(r"thread://[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
ENTRY_KEYS = {"asset_id", "variant_id", "weapon", "weapon_sha256", "identity",
              "closure_sha256", "outcome", "ancestor", "evidence", "reason"}


def _text(value, name, maximum=2048, empty=False):
    if (not isinstance(value, str) or len(value) > maximum
            or (not empty and not value.strip())
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(name + " must be bounded text without control characters")
    return value


def _id(value, name):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(name + " must be a safe lowercase asset identifier")
    return value


def _hash(value, name):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(name + " must be an exact lowercase SHA-256")
    return value


def tag_path(value, suffix=None):
    _text(value, "Tag path", 1024)
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or "\\" in value or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or not re.fullmatch(r"\.[a-z][a-z_0-9]*", path.suffix)
            or path.name == path.suffix or (suffix and path.suffix != suffix)):
        raise ValueError("Catalog tag paths must be portable, relative class-qualified names")
    return value


def _identity(value):
    if not isinstance(value, dict) or set(value) != {"model", "weapon_type", "label"}:
        raise ValueError("Identity requires exactly model, weapon_type and label")
    model = value["model"]
    if not isinstance(model, str):
        raise ValueError("Raw identity model must be text")
    if model not in {"", ".model", ".gbxmodel"}:
        tag_path(model)
        if PurePosixPath(model).suffix not in {".model", ".gbxmodel"}:
            raise ValueError("Raw identity model must be a model or gbxmodel reference")
    _text(value["weapon_type"], "Weapon type", 64)
    _text(value["label"], "Weapon label", 31, empty=True)
    return value


def _closure(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_CLOSURE_TAGS:
        raise ValueError("Closure must contain a bounded complete tag/hash mapping")
    for name, checksum in value.items():
        tag_path(name)
        _hash(checksum, "Dependency hash")
    return value


def _approval(value):
    """An explicit policy decision; this is not historical source evidence."""
    if (not isinstance(value, dict) or set(value) != {"kind", "date", "reference", "statement"}
            or value["kind"] != "user-decision"):
        raise ValueError("Approval requires exactly user-decision kind, date, reference and statement")
    when = value["date"]
    if not isinstance(when, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", when):
        raise ValueError("Approval date must be a real YYYY-MM-DD calendar date")
    try:
        date.fromisoformat(when)
    except ValueError as error:
        raise ValueError("Approval date must be a real YYYY-MM-DD calendar date") from error
    if not isinstance(value["reference"], str) or not THREAD_REFERENCE.fullmatch(value["reference"]):
        raise ValueError("Approval reference must be an exact thread:// lowercase UUID")
    statement = _text(value["statement"], "Approval statement", 4096)
    if any(128 <= ord(c) <= 159 for c in statement):
        raise ValueError("Approval statement must not contain control characters")
    return value


def validate_catalog(value):
    """Validate a source JSON object without changing the caller's value."""
    if not isinstance(value, dict) or set(value) != {"schema_version", "id", "version", "entries"}:
        raise ValueError("Weapon lineage catalog requires exactly schema_version, id, version and entries")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Weapon lineage catalog requires schema_version 1")
    _id(value["id"], "Catalog id")
    _text(value["version"], "Catalog version", 64)
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["version"]):
        raise ValueError("Catalog version must be an explicit major.minor.patch")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError("Catalog entries must be a bounded list")
    seen, signatures = set(), set()
    for entry in entries:
        if (not isinstance(entry, dict) or not ENTRY_KEYS <= set(entry)
                or set(entry) - ENTRY_KEYS - {"approval"}):
            raise ValueError("Catalog variant has missing or unsupported fields")
        _id(entry["asset_id"], "Asset id")
        _id(entry["variant_id"], "Variant id")
        pair = entry["asset_id"], entry["variant_id"]
        if pair in seen:
            raise ValueError("Catalog has duplicate asset/variant ids")
        seen.add(pair)
        weapon = tag_path(entry["weapon"], ".weapon")
        _hash(entry["weapon_sha256"], "Weapon hash")
        _identity(entry["identity"])
        closure = _closure(entry["closure_sha256"])
        if closure.get(weapon) != entry["weapon_sha256"]:
            raise ValueError("Complete closure must include the weapon and its matching root hash")
        if not isinstance(entry["outcome"], str) or entry["outcome"] not in OUTCOMES:
            raise ValueError("Catalog outcome is unsupported")
        ancestor = entry["ancestor"]
        if ancestor is not None:
            if (not isinstance(ancestor, dict) or set(ancestor) != {"kind", "asset_id", "stock_weapon"}
                    or not isinstance(ancestor["kind"], str)
                    or ancestor["kind"] not in {"retail-xbox", "recovered-halo1"}):
                raise ValueError("Ancestor requires reviewed retail-xbox or recovered-halo1 identity")
            _id(ancestor["asset_id"], "Ancestor asset id")
            if ancestor["stock_weapon"] is not None:
                tag_path(ancestor["stock_weapon"], ".weapon")
            if ancestor["kind"] == "retail-xbox" and ancestor["stock_weapon"] is None:
                raise ValueError("Retail ancestor requires an exact stock weapon reference")
        evidence = entry["evidence"]
        if not isinstance(evidence, list) or len(evidence) > 32:
            raise ValueError("Evidence must be a bounded source-reference list")
        for reference in evidence:
            if not isinstance(reference, dict) or set(reference) != {"title", "url"}:
                raise ValueError("Evidence requires exactly title and url")
            _text(reference["title"], "Evidence title", 512)
            url = _text(reference["url"], "Evidence URL", 2048)
            try:
                parsed = urlsplit(url)
                valid = (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                         and parsed.username is None and parsed.password is None
                         and not any(c.isspace() for c in url))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("Evidence URL must be HTTP(S) without credentials")
        _text(entry["reason"], "Review reason", 4096)
        if "approval" in entry:
            _approval(entry["approval"])
            if entry["outcome"] not in {"original-completion", "approved-community", "omit"}:
                raise ValueError("User approval applies only to original completions, community exceptions or asset omissions")
        if entry["outcome"] in ORIGINAL_ADMITTED and (ancestor is None or not evidence):
            raise ValueError("Admitted variants require original Halo 1 ancestor and source evidence")
        if entry["outcome"] in {"approved-community", "omit"} and (ancestor is not None or "approval" not in entry):
            raise ValueError(entry["outcome"] + " outcome requires user approval and no claimed Halo 1 ancestor")
        if entry["outcome"] == "canonical-stock" and ancestor["stock_weapon"] is None:
            raise ValueError("Canonical-stock outcome requires an exact stock weapon")
        signature = json.dumps({key: entry[key] for key in ("weapon", "identity", "closure_sha256")},
                               sort_keys=True, separators=(",", ":"))
        if signature in signatures:
            raise ValueError("Catalog has duplicate or conflicting exact asset variants")
        signatures.add(signature)
    return copy.deepcopy(value)


def load_catalog(path, expected_sha256=None):
    """Read one regular, hash-bound catalog; returned path is operational only."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Catalog must not be a symlink")
    if not path.is_file() or path.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError("Catalog must be a regular JSON file within 8 MiB")
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        data = stream.read(MAX_CATALOG_BYTES + 1)
    if len(data) > MAX_CATALOG_BYTES:
        raise ValueError("Catalog exceeds 8 MiB")
    checksum = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and checksum != _hash(expected_sha256, "Selected catalog hash"):
        raise ValueError("Weapon lineage catalog differs from its selected SHA-256")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Catalog JSON contains a duplicate key: " + key)
            value[key] = item
        return value
    catalog = validate_catalog(json.loads(data, object_pairs_hook=unique_object))
    catalog.update(sha256=checksum, path=str(path))
    return catalog


def catalog_metadata(catalog):
    return {key: catalog[key] for key in ("id", "version", "sha256")}


def variants_for_weapon(catalog, weapon):
    tag_path(weapon, ".weapon")
    return [entry for entry in catalog["entries"] if entry["weapon"] == weapon]


def match_variant(catalog, weapon, identity, closure_sha256):
    """Return (exact variant, []) or (None, precise per-variant mismatches).

    A match proves catalog binding only. Callers must enforce the entry outcome.
    The supplied closure must come from the immutable source dependency graph.
    """
    tag_path(weapon, ".weapon")
    _identity(identity)
    _closure(closure_sha256)
    mismatches = []
    for entry in variants_for_weapon(catalog, weapon):
        expected = entry["closure_sha256"]
        missing, extra = sorted(set(expected) - set(closure_sha256)), sorted(set(closure_sha256) - set(expected))
        changed = {name: {"expected": expected[name], "actual": closure_sha256[name]}
                   for name in sorted(set(expected) & set(closure_sha256))
                   if expected[name] != closure_sha256[name]}
        identity_changes = {key: {"expected": entry["identity"][key], "actual": identity[key]}
                            for key in entry["identity"] if entry["identity"][key] != identity[key]}
        if not missing and not extra and not changed and not identity_changes:
            return copy.deepcopy(entry), []
        mismatches.append({"asset_id": entry["asset_id"], "variant_id": entry["variant_id"],
                           "weapon": weapon, "missing_tags": missing, "extra_tags": extra,
                           "changed_dependencies": changed, "identity_changes": identity_changes,
                           "reason": "Source variant does not match the reviewed identity and complete dependency hashes"})
    if not mismatches:
        mismatches.append({"weapon": weapon, "reason": "No reviewed catalog variant for this weapon"})
    return None, mismatches
