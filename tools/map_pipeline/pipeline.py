"""Directory batches with independently publishable v5 maps and builder reports."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .formats import FormatError, discover_maps, inspect_cache
from .profiles import ROOT, TARGET_BUILD, ID, load_profile, reviewed_pb3_profile, select_map
from .diagnostics import diagnostic, parse_tool_output, render_report, shareable_report
from .metadata import build_metadata, validate_metadata
from ..map_catalog import RESERVED, publish_directory


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def map_id(header: dict, profile: dict) -> str:
    spec = select_map(profile, header)
    if spec:
        return spec["id"]
    name = re.sub(r"[^a-z0-9_-]+", "_", header["name"].casefold()).strip("_-") or "map"
    if name in RESERVED:
        name = "community_" + name
    if len(name) > 31:
        name = name[:22] + "_" + header["sha256"][:8]
    return name


def check_target(header: dict, profile: dict) -> None:
    target = profile["target"]
    if header["version"] != 5 or header["build"] != TARGET_BUILD or header["type"] != 1:
        raise ValueError("Expected an Xbox NTSC 2276 v5 multiplayer cache")
    if (header["declared_bytes"] > target["max_cache_bytes"] or header["tag_bytes"] > target["max_tag_bytes"]
            or header["file_bytes"] > target["max_cache_bytes"]):
        raise ValueError("Output exceeds the selected target cache/tag limits")
    # IDs are normalized once by the compiler, never by editing compiled headers.
    if not ID.fullmatch(header["name"]) or header["name"] in RESERVED:
        raise ValueError("Output needs a safe, distinct community identity; rebuild through a reviewed profile")


def editorial_for(identifier: str, profile: dict, header: dict, metadata_dir: Path | None) -> tuple[dict | None, Path | None]:
    spec = select_map(profile, header)
    editorial = copy.deepcopy((spec or {}).get("metadata", profile.get("metadata")))
    if editorial is None and spec and spec.get("display_name"):
        editorial = {"schema_version": 1, "display_name": spec["display_name"],
                     "field_provenance": {"display_name": {"origin": "reviewed_profile"}}}
    base = None
    if metadata_dir:
        path = metadata_dir / (identifier + ".json")
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.stat().st_size > 64 * 1024:
                raise ValueError("Editorial metadata must be a regular JSON file smaller than 64 KiB")
            editorial = json.loads(path.read_text(encoding="utf-8"))
            base = metadata_dir
    if editorial is not None:
        editorial = validate_metadata(editorial)
    return editorial, base


def copy_preview(editorial: dict | None, base: Path | None, staged: Path, identifier: str) -> dict | None:
    if not editorial or not editorial.get("preview"):
        return None
    if base is None:
        raise ValueError("A preview needs --metadata-dir so its relative source path is unambiguous")
    preview = editorial["preview"]
    source = base / preview["file"]
    current = base
    for part in Path(preview["file"]).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Preview source paths must not contain symlinks")
    source = source.resolve(strict=True)
    if not source.is_relative_to(base.resolve()) or not source.is_file() or source.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Preview must be a regular file inside the metadata directory, at most 10 MiB")
    if source.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        raise ValueError("Preview must use a supported image filename")
    with source.open("rb") as stream:
        magic = stream.read(16)
    matches = {".png": magic.startswith(b"\x89PNG\r\n\x1a\n"),
               ".jpg": magic.startswith(b"\xff\xd8\xff"), ".jpeg": magic.startswith(b"\xff\xd8\xff"),
               ".bmp": magic.startswith(b"BM"),
               ".webp": magic.startswith(b"RIFF") and magic[8:12] == b"WEBP"}
    if not matches[source.suffix.casefold()]:
        raise ValueError("Preview image signature does not match its filename")
    if sha256(source) != preview["sha256"]:
        raise ValueError("Preview differs from its declared SHA-256")
    relative = "previews/" + identifier + source.suffix.casefold()
    destination = staged / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256(destination) != preview["sha256"]:
        raise ValueError("Preview changed during packaging")
    return {**preview, "file": relative}


def failure(record: dict, code: str, stage: str, message: str, *, status="failed", **context) -> None:
    record["status"] = status
    record["diagnostics"].append(diagnostic(code, stage, message, **context))


def convert_directory(input_dir: Path, output: Path, *, profile_selection="authored-xbox-v5",
                      recursive=False, invader_bin: Path | None = None, invader_manifest: Path | None = None,
                      stock_maps: Path | None = None, source_tags: Path | None = None,
                      resources: Path | None = None, metadata_dir: Path | None = None,
                      asset_manifest: Path | None = None,
                      inspect_only=False, backend=None) -> dict:
    if Path(input_dir).is_symlink():
        raise ValueError("Input must be a real directory, not a symlink")
    input_dir = Path(input_dir).resolve(strict=True)
    output = Path(os.path.abspath(output))
    if not input_dir.is_dir():
        raise ValueError("Input must be a map directory")
    if os.path.lexists(output):
        raise FileExistsError("Output already exists; choose a fresh directory")
    if output.resolve().is_relative_to(input_dir):
        raise ValueError("Output must be outside the source directory")
    profile = reviewed_pb3_profile() if str(profile_selection) == "jukkis-pb3" else load_profile(profile_selection)
    if asset_manifest:
        profile["asset_manifest"] = str(Path(asset_manifest).absolute())
    discovery_errors = {}
    paths = discover_maps(input_dir, recursive, on_error=lambda path, error: discovery_errors.setdefault(path, error))
    paths = sorted(set(paths) | set(discovery_errors), key=lambda p: (p.relative_to(input_dir).as_posix().casefold(),
                                                                    p.relative_to(input_dir).as_posix()))
    if not paths:
        raise ValueError("No .map inputs were found")
    if metadata_dir:
        metadata_dir = Path(metadata_dir).resolve(strict=True)
    if source_tags is None:
        for candidate in (input_dir / "tags", input_dir.parent / "tags"):
            if candidate.is_dir() and not candidate.is_symlink():
                source_tags = candidate
                break
    if source_tags:
        profile["source_tags"] = str(Path(source_tags).resolve(strict=True))
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="." + output.name + "-", suffix=".partial", dir=output.parent))
    reports = []
    private_workspace = None
    try:
        prepared = []
        for index, source in enumerate(paths):
            fallback = "input-" + str(index + 1).zfill(4)
            record = {"schema_version": 1, "id": fallback, "source_file": source.relative_to(input_dir).as_posix(),
                      "profile": {k: profile[k] for k in ("id", "version", "sha256")}, "status": "pending",
                      "diagnostics": [], "repairs": [], "omissions": [], "gameplay_validation": "pending", "outputs": {}}
            try:
                if source in discovery_errors:
                    raise discovery_errors[source]
                header = inspect_cache(source)
                record["source"] = header
                if header["format"] == "resource":
                    record["status"] = "resource"
                else:
                    record["id"] = map_id(header, profile)
            except FormatError as error:
                failure(record, error.code, "identify", error.message, field=error.field,
                        value=error.value, suggested_fix=error.suggested_fix, status="unsupported")
            except (ValueError, OSError) as error:
                failure(record, "invalid_source", "identify", str(error))
            prepared.append((source, record))
        # Resolve all names before work: neither input wins a same-ID collision.
        identifiers = {}
        for _, record in prepared:
            if record["status"] == "pending":
                identifiers.setdefault(record["id"], []).append(record)
        for identifier, group in identifiers.items():
            if len(group) > 1:
                for record in group:
                    failure(record, "duplicate_map_identity", "profile", "Multiple source maps resolve to " + identifier,
                            suggested_fix="Assign distinct reviewed output IDs; filenames alone do not identify revisions.")
        for source, record in prepared:
            header = record.get("source")
            if record["status"] == "pending":
                stage = "profile"
                try:
                    if header["version"] not in profile["supported_formats"]:
                        failure(record, "profile_format_mismatch", "profile", "Selected profile does not accept this format",
                                status="needs_profile", value=header["version"], suggested_fix="Choose a profile for this cache format.")
                    elif header["type"] != 1:
                        failure(record, "scenario_type_needs_profile", "profile", "This target currently packages multiplayer maps",
                                status="needs_profile", value=header["type"], suggested_fix="Use a separately reviewed campaign/UI target profile.")
                    elif inspect_only:
                        record["status"] = "inventoried"
                    else:
                        stage = "metadata"
                        editorial, preview_base = editorial_for(record["id"], profile, header, metadata_dir)
                        stage = "verify"
                        if (header["version"] == 5 and profile["script_policy"] != "omit"
                                and profile["weapon_policy"] == "preserve"
                                and profile["presentation_policy"] == "preserve"
                                and profile["weapon_placement_policy"] == "engine-native"
                                and all(value == "preserve" for value in profile["asset_policy"].values())):
                            selected = select_map(profile, header)
                            if (profile["dependency_policy"] != "authored-first" or profile["script_policy"] != "preserve"
                                    or profile["overlays"] or (selected and "source_sha256" not in selected)):
                                failure(record, "v5_recipe_requires_rebuild", "profile", "Existing v5 input is copied without changing its tags",
                                        status="needs_profile", suggested_fix="Use an authored-preserving profile or rebuild the source tags explicitly.")
                                result = None
                            else:
                                check_target(header, profile)
                                if source.stem != header["name"]:
                                    raise ValueError("Existing v5 filename must match its compiled name; rebuild to change identity")
                                result = {"output": source, "header": header, "steps": [{"operation": "preserve_existing_v5"}], "toolchain": None}
                        else:
                            if invader_bin is None or invader_manifest is None:
                                failure(record, "toolchain_required", "extract", "Conversion needs reviewed native Invader helpers",
                                        status="needs_profile", suggested_fix="Supply --invader-bin and --invader-manifest from an authoring toolchain.")
                                result = None
                            else:
                                if backend is None:
                                    from .backend import convert_cache
                                    backend = convert_cache
                                if private_workspace is None:
                                    (ROOT / "build").mkdir(exist_ok=True)
                                    private_workspace = Path(tempfile.mkdtemp(prefix="map-pipeline-", dir=ROOT / "build"))
                                selected_profile = copy.deepcopy(profile)
                                selected_profile["output_id"] = record["id"]
                                selected_profile["selected_map"] = select_map(profile, header)
                                result = backend(source, header, private_workspace / record["id"], selected_profile,
                                                 Path(invader_bin), Path(invader_manifest), stock_maps,
                                                 resources or source.parent)
                        if result is not None:
                            converted = inspect_cache(Path(result["output"]))
                            check_target(converted, profile)
                            if converted["name"] != record["id"]:
                                raise ValueError("Compiler output identity differs from the selected map identity")
                            if sha256(source) != header["sha256"]:
                                raise ValueError("Source cache changed during conversion")
                            relative = "maps/" + record["id"] + ".map"
                            destination = staged / relative
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(result["output"], destination)
                            if inspect_cache(destination) != converted:
                                raise ValueError("Compiled cache changed during packaging")
                            stage = "metadata"
                            preview = copy_preview(editorial, preview_base, staged, record["id"])
                            metadata = build_metadata(record["id"], header, converted, profile, editorial=editorial, preview=preview)
                            meta_relative = "metadata/" + record["id"] + ".json"
                            write_json(staged / meta_relative, metadata)
                            record.update(status="converted", conversion={k: result.get(k) for k in ("steps", "toolchain", "provenance")},
                                          repairs=result.get("repairs", []), omissions=result.get("omissions", []))
                            for command in (result.get("toolchain") or {}).get("commands", []):
                                messages = parse_tool_output(command.get("stdout", "") + "\n" + command.get("stderr", ""),
                                                             command.get("stage", "compile"))
                                record["diagnostics"].extend(item for item in messages if item["severity"] == "warning")
                            for step in result.get("steps", []):
                                if step.get("operation") == "weapon_placement_audit":
                                    record["diagnostics"].extend(step.get("diagnostics", []))
                                if step.get("operation") != "canonical_weapons":
                                    continue
                                for name, completion in step.get("authored_original_completions", {}).items():
                                    remaining = completion["remaining_missing_fields"]
                                    record["diagnostics"].append(diagnostic(
                                        "original_completion_incomplete" if remaining else "original_completion_retained",
                                        "canonical_weapons", completion["diagnostic"], tag=name, tag_type="weapon",
                                        value={"original_weapon": completion["stock_weapon"], "remaining_missing_fields": remaining},
                                        severity="warning" if remaining else "info",
                                        suggested_fix="Supply the remaining first-person/HUD references when completing this original weapon."
                                        if remaining else "Review the recorded completion provenance; gameplay validation remains pending."))
                                for name, exception in step.get("authored_community_exceptions", {}).items():
                                    lineage = exception["reviewed_lineage"]
                                    record["diagnostics"].append(diagnostic(
                                        "approved_community_weapon_retained", "canonical_weapons",
                                        "Approved community weapon retained by explicit user decision; no original Halo 1 ancestry is claimed.",
                                        tag=name, tag_type="weapon", severity="info",
                                        value={"outcome": lineage["outcome"], "approval": lineage["approval"],
                                               "gameplay_validation": "pending"},
                                        suggested_fix="Review the recorded approval and authored asset provenance; gameplay validation remains pending."))
                            record["outputs"] = {"map": {"file": relative, "sha256": converted["sha256"]},
                                                 "metadata": {"file": meta_relative, "sha256": sha256(staged / meta_relative)},
                                                 "preview": preview}
                            if preview is None:
                                record["diagnostics"].append(diagnostic("preview_missing", "metadata",
                                    "No authored or generated preview was supplied", severity="warning",
                                    suggested_fix="Supply a checksum-bound author image or a captured overview in --metadata-dir."))
                            if not metadata.get("creator_username") or not metadata.get("map_version"):
                                record["diagnostics"].append(diagnostic("authorship_metadata_missing", "metadata",
                                    "Creator username or author map version is unknown", severity="warning",
                                    suggested_fix="Ask the map creator to supply these fields; cache/build versions are different."))
                except Exception as error:
                    code = getattr(error, "code", "invalid_metadata" if stage == "metadata" else "conversion_failed")
                    stage = getattr(error, "stage", stage)
                    status = "needs_profile" if code in {"needs_profile", "unsupported_script", "unsupported_codec", "missing_resource", "missing_resources"} else "failed"
                    details = getattr(error, "details", {})
                    context = {key: details[key] for key in ("tag", "tag_type", "field", "value", "dependency_chain") if key in details}
                    failure(record, code, stage, str(error), status=status,
                            suggested_fix="Review the diagnostic report and provide a compatible source or an explicit reviewed profile.",
                            **context)
                    if details:
                        record["failure_context"] = details
                        # Deliberate changes remain reviewable when a later asset
                        # fails to compile; they are not successful map outputs.
                        for key in ("repairs", "omissions"):
                            if isinstance(details.get(key), list):
                                record[key] = details[key]
                        if isinstance(details.get("steps"), list):
                            record["conversion"] = {"steps": details["steps"]}
                        record["diagnostics"].extend(parse_tool_output(str(details.get("output", details.get("stderr", ""))), stage))
                    # A rejected result never leaves a playable file in the package.
                    for folder in ("maps", "metadata", "previews"):
                        for path in (staged / folder).glob(record["id"] + ".*") if (staged / folder).exists() else []:
                            path.unlink()
                    record["outputs"] = {}
            reports.append(record)
            report_key = record["id"] + "-" + str(len(reports)).zfill(4)
            record["report_files"] = {"json": "reports/" + report_key + ".json", "markdown": "reports/" + report_key + ".md"}
            portable = shareable_report(record)
            write_json(staged / "reports" / (report_key + ".json"), portable)
            (staged / "reports" / (report_key + ".md")).write_text(render_report(portable), encoding="utf-8")
        statuses = sorted({r["status"] for r in reports})
        summary = {"schema_version": 1, "profile": {k: profile[k] for k in ("id", "version", "sha256")},
                   "counts": {status: sum(r["status"] == status for r in reports) for status in statuses},
                   "maps": [shareable_report(r) for r in reports], "gameplay_validation": "pending"}
        write_json(staged / "batch.json", summary)
        publish_directory(staged, output)
        return summary
    finally:
        if staged.exists():
            shutil.rmtree(staged)
