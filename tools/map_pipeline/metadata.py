"""Authored menu metadata, separate from the compiled gameplay cache identity.

User metadata is a strict schema-1 JSON object. Unknown facts remain null;
neither spawn counts nor source filenames establish creators or player ranges.
Descriptions and modes are editorial metadata, not gameplay qualification.
"""
import json
import re
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
FIELDS = (
    "display_name", "creator_username", "contributors", "map_version",
    "description", "recommended_players", "modes", "source_url", "preview",
    "field_provenance",
)
MODES = frozenset(("slayer", "team_slayer", "ctf", "oddball", "team_oddball",
                   "king", "team_king", "race", "team_race"))
PREVIEW_ORIGINS = frozenset(("author", "generated_capture", "generated_artwork"))
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAP_ID = re.compile(r"[A-Za-z0-9_ -]{1,31}\Z")


def _text(value, label, limit, *, nullable=False, multiline=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be a nonempty string of at most {limit} characters")
    for character in value:
        if ord(character) < 32 and not (multiline and character in "\n\t") or ord(character) == 127:
            raise ValueError(f"{label} contains control characters")
    return value.strip()


def _sha(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _strings(value, label, *, limit=128):
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(f"{label} must be a list of at most 64 strings")
    result = [_text(item, label, limit) for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"{label} contains duplicates")
    return result


def validate_preview(value):
    """Validate relative preview identity without opening or altering any file."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"file", "sha256", "origin"}:
        raise ValueError("preview must contain only file, sha256 and origin")
    path = _text(value["file"], "preview.file", 512)
    parts = path.split("/")
    if (path.startswith(("/", "~")) or "\\" in path or ":" in path
            or any(part in ("", ".", "..") for part in parts)):
        raise ValueError("preview.file must be a safe relative path")
    if not isinstance(value["origin"], str) or value["origin"] not in PREVIEW_ORIGINS:
        raise ValueError("preview.origin must identify author, generated_capture or generated_artwork")
    return {"file": path, "sha256": _sha(value["sha256"], "preview.sha256"),
            "origin": value["origin"]}


def validate_metadata(value):
    """Return canonical schema-1 authored metadata; reject misspelled fields."""
    if not isinstance(value, dict) or set(value) - {"schema_version", *FIELDS}:
        raise ValueError("Metadata must be an object containing only documented fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Metadata schema_version must be 1")
    result = {"schema_version": SCHEMA_VERSION}
    result["display_name"] = _text(value.get("display_name"), "display_name", 128)
    for field, limit in (("creator_username", 128), ("map_version", 64), ("description", 2048)):
        result[field] = _text(value.get(field), field, limit, nullable=True,
                              multiline=field == "description")
    result["contributors"] = _strings(value.get("contributors", []), "contributors")
    players = value.get("recommended_players")
    if players is not None:
        if (not isinstance(players, dict) or set(players) != {"min", "max"}
                or any(type(players[key]) is not int for key in ("min", "max"))
                or not 1 <= players["min"] <= players["max"] <= 16):
            raise ValueError("recommended_players must contain integers 1 <= min <= max <= 16")
        players = {"min": players["min"], "max": players["max"]}
    result["recommended_players"] = players
    modes = _strings(value.get("modes", []), "modes", limit=32)
    if set(modes) - MODES:
        raise ValueError("modes must use classic preset IDs: " + ", ".join(sorted(MODES)))
    result["modes"] = modes
    source_url = _text(value.get("source_url"), "source_url", 2048, nullable=True)
    if source_url is not None:
        try:
            parsed = urlsplit(source_url)
            valid = (parsed.scheme in ("http", "https") and bool(parsed.hostname)
                     and parsed.username is None and parsed.password is None
                     and not any(character.isspace() for character in source_url))
            parsed.port  # Validate malformed ports without contacting the URL.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("source_url must be an HTTP(S) URL without credentials")
    result["source_url"] = source_url
    result["preview"] = validate_preview(value.get("preview"))
    provenance = value.get("field_provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - (set(FIELDS) - {"field_provenance"}):
        raise ValueError("field_provenance must name documented metadata fields")
    try:
        encoded = json.dumps(provenance, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("field_provenance must contain finite JSON data") from error
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("field_provenance exceeds 64 KiB")
    result["field_provenance"] = json.loads(encoded)
    return result


def build_metadata(map_id, source, converted, profile, editorial=None, preview=None):
    """Bind menu metadata to source, converter profile and final cache separately.

    Headers use the existing inspector's version/build/sha256 fields. The
    converter profile uses id/version/sha256. Only cache.sha256 identifies
    gameplay bytes; preview and editorial revisions never change that identity.
    """
    if not isinstance(map_id, str) or not MAP_ID.fullmatch(map_id):
        raise ValueError("Invalid map ID")
    if not all(isinstance(item, dict) for item in (source, converted, profile)):
        raise ValueError("Source, converted cache and profile must be objects")
    source_version = source.get("version", source.get("cache_version"))
    cache_version = converted.get("version", converted.get("cache_version"))
    if type(source_version) is not int or source_version < 1 or cache_version != 5 or type(cache_version) is not int:
        raise ValueError("Metadata must bind a recognized source version and Xbox v5 output")
    profile_id = _text(profile.get("id"), "profile.id", 128)
    profile_version = profile.get("version")
    if type(profile_version) is int:
        if profile_version < 1:
            raise ValueError("profile.version must be positive")
    else:
        profile_version = _text(profile_version, "profile.version", 64)
    if editorial is None:
        editorial = {"schema_version": 1, "display_name": map_id,
                     "field_provenance": {"display_name": {"origin": "generated_filename"}}}
    fields = validate_metadata(editorial)
    if preview is not None:
        fields["preview"] = validate_preview(preview)
        fields["field_provenance"].setdefault("preview", {"origin": fields["preview"]["origin"]})
    result = {
        **fields, "id": map_id,
        "source": {"sha256": _sha(source.get("sha256"), "source.sha256"),
                   "cache_version": source_version},
        "cache": {"version": cache_version,
                  "build": _text(converted.get("build"), "cache.build", 32),
                  "sha256": _sha(converted.get("sha256"), "cache.sha256")},
        "conversion": {"profile_id": profile_id, "profile_version": profile_version,
                       "profile_sha256": _sha(profile.get("sha256"), "profile.sha256")},
        "gameplay_validation": "pending",
    }
    # Editorial provenance can name a private source directory. Generated
    # sidecars share the same portability boundary as conversion reports.
    from .diagnostics import shareable_report
    return shareable_report(result)
