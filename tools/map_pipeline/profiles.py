"""Versioned conversion decisions, separate from source-format detection."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = ROOT / "tools" / "map_conversion" / "profiles"
FORMATS = {5, 6, 7, 609, 13}
TARGET_BUILD = "01.10.12.2276"
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,30}\Z")


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_profile(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Conversion profile must be an object")
    profile = copy.deepcopy(value)
    allowed = {"schema_version", "id", "version", "description", "supported_formats", "target",
               "dependency_policy", "script_policy", "script_omission_reason", "asset_policy", "presentation_policy", "stock_weapon_hud_policy", "weapon_policy", "weapon_placement_policy", "maps", "overlays", "metadata"}
    if set(profile) - allowed:
        raise ValueError("Unknown profile fields: " + ", ".join(sorted(set(profile) - allowed)))
    if (type(profile.get("schema_version")) is not int or profile["schema_version"] != 1 or not isinstance(profile.get("id"), str)
            or not ID.fullmatch(profile["id"]) or not isinstance(profile.get("version"), str)
            or not profile["version"].strip() or len(profile["version"]) > 64):
        raise ValueError("Profile needs schema_version 1, a safe id and an explicit version")
    if any(ord(c) < 32 or ord(c) == 127 for c in profile["version"]):
        raise ValueError("Profile version contains control characters")
    formats = profile.get("supported_formats")
    if (not isinstance(formats, list) or not formats or any(type(v) is not int or v not in FORMATS for v in formats)
            or len(formats) != len(set(formats))):
        raise ValueError("supported_formats must select distinct known cache versions")
    target = profile.get("target")
    if (not isinstance(target, dict) or set(target) != {"engine", "build", "max_cache_bytes", "max_tag_bytes"}
            or target["engine"] != "xbox-ntsc" or target["build"] != TARGET_BUILD
            or type(target["max_cache_bytes"]) is not int or not 2048 <= target["max_cache_bytes"] <= 512 * 1024 * 1024
            or type(target["max_tag_bytes"]) is not int or not 1 <= target["max_tag_bytes"] <= 22 * 1024 * 1024):
        raise ValueError("Target must use Xbox NTSC 2276 within Halo OG cache/tag bounds")
    if profile.get("dependency_policy") not in {"authored-first", "stock-first"}:
        raise ValueError("Select authored-first or stock-first dependencies explicitly")
    if profile.get("script_policy") not in {"preserve", "reviewed", "none", "omit"}:
        raise ValueError("Select preserve, reviewed, none or omit script policy explicitly")
    if profile["script_policy"] == "omit":
        reason = profile.get("script_omission_reason")
        if (not isinstance(reason, str) or not reason.strip() or len(reason) > 2048
                or any(ord(c) < 32 or ord(c) == 127 for c in reason)):
            raise ValueError("Script omission requires an explicit reason without control characters")
    elif "script_omission_reason" in profile:
        raise ValueError("Script omission reasons require the omit script policy")
    profile.setdefault("presentation_policy", "preserve")
    if not isinstance(profile["presentation_policy"], str) or profile["presentation_policy"] not in {"preserve", "native-xbox"}:
        raise ValueError("Presentation policy must select preserve or native-xbox")
    profile.setdefault("stock_weapon_hud_policy", "preserve")
    if (not isinstance(profile["stock_weapon_hud_policy"], str)
            or profile["stock_weapon_hud_policy"] not in {"preserve", "reuse-native"}
            or (profile["stock_weapon_hud_policy"] == "reuse-native" and profile["presentation_policy"] != "native-xbox")):
        raise ValueError("Stock weapon HUD reuse requires the native-xbox presentation policy")
    profile.setdefault("weapon_policy", "preserve")
    if not isinstance(profile["weapon_policy"], str) or profile["weapon_policy"] not in {"preserve", "bungie-originals"}:
        raise ValueError("Weapon policy must select preserve or bungie-originals")
    profile.setdefault("weapon_placement_policy", "engine-native")
    if (not isinstance(profile["weapon_placement_policy"], str)
            or profile["weapon_placement_policy"] not in {"engine-native", "authored-default"}):
        raise ValueError("Weapon placement policy must select engine-native or authored-default")
    if (profile["weapon_placement_policy"] == "authored-default"
            and (profile["weapon_policy"] != "bungie-originals"
                 or profile["presentation_policy"] != "native-xbox"
                 or profile["dependency_policy"] != "authored-first")):
        raise ValueError("Authored weapon placements require original Bungie weapons, native Xbox presentation and authored-first dependencies")
    profile.setdefault("asset_policy", {"audio": "preserve", "bitmaps": "preserve"})
    assets = profile["asset_policy"]
    if isinstance(assets, dict):
        assets.setdefault("dimensions", "preserve")
        assets.setdefault("packing", "preserve")
        assets.setdefault("extensions", "preserve")
    if (not isinstance(assets, dict) or set(assets) != {"audio", "bitmaps", "dimensions", "packing", "extensions"}
            or assets["audio"] not in {"preserve", "xbox-adpcm"}
            or assets["bitmaps"] not in {"preserve", "bc7-to-dxt5"}
            or assets["dimensions"] not in {"preserve", "existing-mip"}
            or assets["packing"] not in {"preserve", "lossless"}
            or assets["extensions"] not in {"preserve", "omit-mcc"}):
        raise ValueError("Asset policy must select audio codecs, bitmap codecs, dimensions, packing and target extensions")
    profile.setdefault("maps", [])
    if not isinstance(profile["maps"], list):
        raise ValueError("maps must be a list of reviewed source selections")
    for spec in profile["maps"]:
        if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not ID.fullmatch(spec["id"]):
            raise ValueError("Each reviewed map needs a safe output id")
        if set(spec) - {"id", "display_name", "scenario", "source_name", "source_sha256", "scenario_sha256",
                       "optional_scripts", "cleanup_prefixes", "metadata"}:
            raise ValueError("Map recipe contains unsupported decisions")
        if "source_name" in spec and (not isinstance(spec["source_name"], str) or not spec["source_name"]
                or len(spec["source_name"]) > 31 or any(ord(c) < 32 or ord(c) >= 127 for c in spec["source_name"])):
            raise ValueError("Reviewed source_name must match a printable ASCII cache name")
        if "display_name" in spec and (not isinstance(spec["display_name"], str) or not spec["display_name"].strip()):
            raise ValueError("Reviewed display_name must be nonempty text")
        for field in ("optional_scripts", "cleanup_prefixes"):
            if field in spec and (not isinstance(spec[field], list) or any(not isinstance(s, str) or not s for s in spec[field])):
                raise ValueError("Reviewed script decisions must be lists of names")
        if any(field in spec for field in ("optional_scripts", "cleanup_prefixes")) and profile["script_policy"] != "reviewed":
            raise ValueError("Script cleanup fields require a reviewed script policy")
        if not isinstance(spec.get("scenario"), str) or any(c in spec["scenario"] for c in "\\\0\r\n"):
            raise ValueError("Each reviewed map needs a portable scenario path")
        scenario = Path(spec["scenario"])
        if (scenario.is_absolute() or any(part in ("", ".", "..") for part in spec["scenario"].split("/"))
                or ":" in spec["scenario"] or scenario.suffix == ".scenario"):
            raise ValueError("Scenario path must stay inside the source tag tree")
        for field in ("source_sha256", "scenario_sha256"):
            if field in spec and (not isinstance(spec[field], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", spec[field])):
                raise ValueError("Reviewed source expectations must use exact SHA-256 values")
        if not any(field in spec for field in ("source_sha256", "scenario_sha256")):
            raise ValueError("Reviewed map decisions must identify an exact source or scenario hash")
    profile.setdefault("overlays", [])
    if not isinstance(profile["overlays"], list) or any(not isinstance(p, str) or not p for p in profile["overlays"]):
        raise ValueError("overlays must be an explicit list of reviewed overlay directories")
    profile["sha256"] = fingerprint(profile)
    return profile


def load_profile(selection: str | Path = "authored-xbox-v5") -> dict:
    path = Path(selection)
    if not path.is_file():
        if not ID.fullmatch(str(selection)):
            raise ValueError("Profile does not exist: " + str(selection))
        path = PROFILE_ROOT / (str(selection) + ".json")
    if path.is_symlink():
        raise ValueError("Profile files must not be symlinks")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Profile exceeds 1 MiB")
    value = json.loads(path.read_text(encoding="utf-8"))
    profile = validate_profile(value)
    # Operational paths are resolved from the profile file, outside its portable fingerprint.
    profile["overlays"] = [str((path.parent / p).resolve(strict=True)) for p in profile["overlays"]]
    return profile


def reviewed_pb3_profile() -> dict:
    policy = json.loads((ROOT / "port" / "maps" / "jukkis-beta3.json").read_text())
    value = json.loads((PROFILE_ROOT / "jukkis-pb3.json").read_text())
    value["maps"] = policy["maps"]
    return validate_profile(value)


def select_map(profile: dict, header: dict) -> dict | None:
    """Resolve reviewed recipe candidates; backend verifies scenario-content hashes."""
    selections = []
    for spec in profile["maps"]:
        if "source_sha256" in spec:
            if spec["source_sha256"] == header["sha256"]:
                selections.append(spec)
        elif header["name"].casefold() in {spec.get("source_name", "").casefold(), spec["id"].removeprefix("h1pb_").casefold(),
                                           Path(spec["scenario"]).name.casefold()}:
            selections.append(spec)
    if len(selections) > 1:
        raise ValueError("More than one reviewed recipe matches this source")
    return selections[0] if selections else None
