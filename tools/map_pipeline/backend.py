"""Pinned offline authoring backend; conversion never changes its input files.

Format conversion preserves recovered HSC by default. Explicit script omission
requires a stated profile reason and records the actual source identities.
Unsupported required content produces a diagnostic instead of silent removal.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct
import subprocess

try:
    from .. import community_maps as legacy
    from .. import community_map_conversion as conversion
except ImportError:
    import community_maps as legacy
    import community_map_conversion as conversion


TOOL_TIMEOUT_SECONDS = 300
OUTPUT_EXCERPT_CHARS = 16000
STARTING_PROFILE_PATCH_SHA256 = "f63f474725424241aa6c647d0062ef9b89f48c31536b5ebecbb45f90fae47d36"
AUTHORING_TOOLS = ("extract", "dependency", "convert", "refactor", "edit", "bludgeon", "build")


class ConversionError(RuntimeError):
    def __init__(self, code: str, stage: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        # Helper records also belong to the command log. Keep contextual
        # failure additions out of that record to avoid recursive reports.
        self.details = dict(details or {})


class ApprovedInvader(legacy.Invader):
    """Verify the pinned helpers and keep failures bounded and inspectable."""

    def __init__(self, binary: Path, manifest: Path, logs: Path):
        self.binary = binary.resolve(strict=True)
        self.logs, self.sequence = logs, 0
        self.provenance: dict[str, str] = {}
        self.tool_paths: dict[str, Path] = {}
        pinned = json.loads(manifest.read_text())
        if pinned["invader_commit"] != json.loads(legacy.POLICY.read_text())["invader_commit"]:
            raise ValueError("Invader source revision differs from the reviewed import toolchain")
        for name in AUTHORING_TOOLS:
            candidates = [self.binary / ("invader-" + name + suffix) for suffix in ("", ".exe")]
            present = [path for path in candidates if path.is_file()]
            if len(present) != 1:
                raise ValueError("Expected one approved Invader helper (plain or .exe): " + name)
            actual = legacy.digest(present[0])
            if actual != pinned["binaries"][name]["sha256"]:
                raise ValueError("Invader binary differs from its source manifest: " + name)
            self.tool_paths[name], self.provenance[name] = present[0], actual
        self.commit = pinned["invader_commit"]
        self.source_patches = pinned.get("source_patches", [])
        self.stage = "toolchain"
        self.commands: list[dict] = []

    def run(self, tool, *args):
        if legacy.digest(self.tool_paths[tool]) != self.provenance[tool]:
            raise ConversionError("toolchain_invalid", "toolchain",
                                  "Invader helper changed after manifest verification", {"tool": tool})
        self.sequence += 1
        command = [str(self.tool_paths[tool]), *map(str, args)]
        log = self.logs / f"{self.sequence:04d}-{tool}.log"
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=TOOL_TIMEOUT_SECONDS)
            stdout, stderr, code, timed_out = result.stdout, result.stderr, result.returncode, False
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
            stdout, stderr, code, timed_out = decoded(error.stdout), decoded(error.stderr), None, True
        log.write_text(stdout + stderr)
        record = {"stage": self.stage, "tool": tool, "command": command,
                  "exit_code": code, "timed_out": timed_out, "log": str(log),
                  "stdout": stdout[-OUTPUT_EXCERPT_CHARS:], "stderr": stderr[-OUTPUT_EXCERPT_CHARS:],
                  "output": (stdout + "\n" + stderr)[-OUTPUT_EXCERPT_CHARS:]}
        self.commands.append(record)
        if timed_out:
            raise ConversionError("tool_timeout", self.stage,
                                  f"invader-{tool} exceeded {TOOL_TIMEOUT_SECONDS} seconds", record)
        if code:
            status = "needs_profile" if self.stage in {"compile", "models", "shaders", "scripts"} else "tool_failed"
            raise ConversionError(status, self.stage,
                                  f"invader-{tool} rejected this input; inspect its recorded diagnostic", record)
        return stdout.strip()


def _tree(path: Path) -> dict:
    """Hash a regular tree without following source symlinks or hard links."""
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Expected a regular tag directory: {path}")
    for item in path.rglob("*"):
        if item.is_symlink() or (item.is_file() and item.stat().st_nlink != 1):
            raise ValueError(f"Linked tag inputs are not supported: {item}")
    return conversion.tree(path)


def _scenario_spec(profile: dict, header: dict) -> dict | None:
    def matches_source(spec):
        if spec.get("source_sha256"):
            return spec["source_sha256"] == header["sha256"]
        return header["name"].casefold() in {
            spec.get("source_name", "").casefold(), Path(spec.get("scenario", "")).name.casefold(),
            spec.get("id", "").removeprefix("h1pb_").casefold()}
    matches = [spec for spec in profile.get("maps", []) if matches_source(spec)]
    if len(matches) > 1:
        raise ConversionError("needs_profile", "profile", "More than one profile entry matches this map")
    spec = profile.get("selected_map", matches[0] if matches else None)
    if spec and not matches_source(spec):
        raise ConversionError("needs_profile", "profile", "Selected profile entry identifies a different source map")
    if spec and matches and spec != matches[0]:
        raise ConversionError("needs_profile", "profile", "Selected profile entry differs from the matching reviewed entry")
    if profile.get("maps") and spec is None:
        raise ConversionError("needs_profile", "profile", "No reviewed profile entry matches this map")
    if spec and spec.get("source_sha256") and spec["source_sha256"] != header["sha256"]:
        raise ConversionError("needs_profile", "profile", "Source cache differs from its reviewed profile hash")
    return spec


def _scenario(tags: Path, header: dict, spec: dict | None, output_id: str | None = None) -> tuple[str, str]:
    if spec and spec.get("scenario"):
        scenario = spec["scenario"].replace("\\", "/")
    else:
        scenarios = sorted(tags.rglob("*.scenario"))
        named = [path for path in scenarios if path.stem == header["name"]]
        selected = named if named else scenarios
        if len(selected) != 1:
            raise ConversionError("needs_profile", "scenario", "The source scenario is ambiguous or missing",
                                  {"candidates": [str(path.relative_to(tags)) for path in scenarios]})
        scenario = selected[0].relative_to(tags).with_suffix("").as_posix()
    if (not legacy.SCENARIO.fullmatch(scenario) or Path(scenario).is_absolute()
            or ".." in Path(scenario).parts):
        raise ConversionError("needs_profile", "scenario", "Profile scenario path is unsafe")
    try:
        original = legacy.safe_tag(tags, scenario + ".scenario")
    except (OSError, ValueError) as error:
        raise ConversionError("needs_profile", "scenario", str(error)) from error
    if spec and spec.get("scenario_sha256") and legacy.digest(original) != spec["scenario_sha256"]:
        raise ConversionError("needs_profile", "profile", "Scenario tag differs from its reviewed profile hash")
    output_id = output_id or (spec or {}).get("id", header["name"])
    if not legacy.NAME.fullmatch(output_id):
        raise ConversionError("needs_profile", "scenario", "Output identity is not a safe cache name")
    compiled = str(Path(scenario).with_name(output_id))
    if compiled != scenario:
        destination = tags / (compiled + ".scenario")
        if destination.exists():
            raise ConversionError("needs_profile", "scenario", "Output scenario alias collides with authored content")
        shutil.copyfile(original, destination)
    return scenario, compiled


def _target_header(output: Path, target: dict, expected_name: str) -> dict:
    header = legacy.cache_header(output)
    limits = {"max_cache_bytes": legacy.MAX_CACHE_BYTES, "max_tag_bytes": legacy.TAG_ARENA_BYTES}
    if (header["version"] != 5 or header["build"] != legacy.NTSC_BUILD or header["type"] != 1
            or header["name"] != expected_name):
        raise ConversionError("invalid_output", "verify", "Output is not the selected Xbox NTSC v5 multiplayer cache", header)
    for field, header_field in (("max_cache_bytes", "declared_bytes"), ("max_tag_bytes", "tag_bytes")):
        maximum = min(target.get(field, limits[field]), limits[field])
        if not 0 < header[header_field] <= maximum:
            raise ConversionError("needs_profile", "verify", "Output exceeds the native cache capacity",
                                  {"header": header, "limit": field, "maximum": maximum,
                                   "actual": header[header_field], "excess_bytes": max(0, header[header_field] - maximum)})
    if header["declared_bytes"] < 2048 or header["tag_bytes"] > header["declared_bytes"] - 2048:
        raise ConversionError("invalid_output", "verify", "Output cache header has inconsistent bounds", header)
    with output.open("rb") as stream:
        prefix = stream.read(24)
    offset = struct.unpack_from("<I", prefix, 16)[0]
    if offset < 2048 or offset > header["declared_bytes"] - header["tag_bytes"]:
        raise ConversionError("invalid_output", "verify", "Output tag arena extends outside the declared cache", header)
    return header


def _reviewed_pb3_spec(spec: dict) -> None:
    canonical = json.loads(legacy.POLICY.read_text())["maps"]
    matches = [item for item in canonical if item["scenario"] == spec.get("scenario")]
    fields = ("id", "scenario", "scenario_sha256", "optional_scripts", "cleanup_prefixes")
    if len(matches) != 1 or any(spec.get(field, []) != matches[0].get(field, []) for field in fields):
        raise ConversionError("needs_profile", "profile", "Script removal must match the checked-in PB3 recipe exactly")


def _extract_stock(tool: ApprovedInvader, stock_maps: Path, destination: Path, include_campaign_weapons=False) -> dict:
    destination.mkdir()
    sources = {}
    names = ["bloodgulch", "a10", "ui"]
    if include_campaign_weapons and (stock_maps / "c40.map").exists():
        # Two Betrayals supplies the original Sword/Fuel Rod/Hunter/Sentinel
        # definitions. Existing multiplayer tags retain extraction priority.
        names.append("c40")
    for name in names:
        source = stock_maps / f"{name}.map"
        h = legacy.cache_header(source)
        if h["version"] != 5 or h["build"] != legacy.NTSC_BUILD:
            raise ConversionError("needs_profile", "stock", "Stock fallback requires Xbox NTSC 2276", h)
        tool.run("extract", "-t", destination, source)
        if legacy.digest(source) != h["sha256"]:
            raise ConversionError("input_changed", "stock", "Stock input changed during extraction")
        sources[name] = {"path": str(source), **h}
    return {"inputs": sources, "compatibility_patches": []}


def _checked_overlays(paths: list, known_roots: list[Path]) -> list[Path]:
    roots = []
    # Legacy ordering is first root wins. Inspect later inputs too because a
    # reviewed overlay can derive from another supplied, hashed overlay.
    overlays = [Path(path).resolve(strict=True) for path in paths]
    for overlay in overlays:
        if not (overlay / "conversion.json").is_file():
            raise ConversionError("needs_profile", "overlays", "An overlay needs its reviewed conversion manifest")
        record = json.loads((overlay / "conversion.json").read_text())
        if not record.get("operation") and not record.get("conversion"):
            raise ConversionError("needs_profile", "overlays", "Overlay manifest does not identify a reviewed conversion")
    try:
        roots = conversion.overlay_roots(overlays)
        known = [_tree(root) for root in [*known_roots, *roots]]
        for overlay in overlays:
            record = json.loads((overlay / "conversion.json").read_text())
            inputs = record.get("input_sha256", record.get("profile", {}).get("tags", {}))
            if not inputs:
                raise ValueError("Overlay manifest has no reviewed source identities")
            input_sets = inputs.values() if all(isinstance(v, dict) for v in inputs.values()) else [inputs]
            for hashes in input_sets:
                for name, value in hashes.items():
                    expected = value.get("sha256") if isinstance(value, dict) else value
                    if not any(inventory.get(name) == expected for inventory in known):
                        raise ValueError(f"Overlay source is absent or changed for this map: {name}")
    except (OSError, ValueError, KeyError) as error:
        raise ConversionError("needs_profile", "overlays", str(error)) from error
    return roots


def _changed_inputs(protected: dict[Path, str], originals: Path, original_tree: dict | None) -> list[str]:
    changed = []
    for path, expected in protected.items():
        try:
            if legacy.digest(path) != expected:
                changed.append(str(path))
        except OSError:
            changed.append(str(path))
    if original_tree is not None:
        try:
            if _tree(originals) != original_tree:
                changed.append(str(originals))
        except (OSError, ValueError):
            changed.append(str(originals))
    return changed


def _script_policy(tool: ApprovedInvader, policy: str, counts: dict) -> None:
    if not (counts["scripts"] or counts["globals"] or counts["source_files"]):
        return
    if policy == "none":
        raise ConversionError("needs_profile", "scripts", "Script removal requires an exact reviewed behavior recipe", counts)
    patches = tool.source_patches
    if not isinstance(patches, list) or not any(isinstance(item, dict) and
            item.get("sha256") == STARTING_PROFILE_PATCH_SHA256 for item in patches):
        raise ConversionError("needs_profile", "scripts",
                              "Preserving HSC requires the reviewed starting-profile compiler fix; "
                              "build the patched authoring toolset and supply its verified source manifest",
                              {"counts": counts, "required_source_patch_sha256": STARTING_PROFILE_PATCH_SHA256})


def _omit_scripts(tool: ApprovedInvader, tags: Path, scenario: str, profile: dict,
                  header: dict, original_scenario_hash: str, counts: dict,
                  steps: list, omissions: list) -> None:
    tag = scenario + ".scenario"
    path = legacy.safe_tag(tags, tag)
    child_count = tool.count(tags, tag, "child_scenarios")
    if child_count:
        raise ConversionError("needs_profile", "scripts", "Script omission requires a scenario without child scenarios; child merges could reintroduce HSC",
                              {"tag": tag, "child_scenarios": child_count})
    before = legacy.digest(path)
    reference_count = tool.count(tags, tag, "references")
    omission = {"kind": "script_omission", "policy": "omit", "tag": tag,
                "reason": profile["script_omission_reason"].strip(), "source_sha256": header["sha256"],
                "original_scenario_sha256": original_scenario_hash, "sha256_before": before,
                "counts_before": counts, "fields": ["scripts", "globals", "source_files", "references"],
                "child_scenarios": child_count,
                "script_references_before": reference_count,
                "status": "requested"}
    omissions.append(omission)
    steps.append({"operation": "omit_scripts", **omission})
    # Scenario.references holds script tag operands, regenerated by the HSC
    # compiler. Clear it now so asset dependency selection excludes stale HSC.
    tool.run("edit", "-t", tags, "-n", "-E", "scripts[*]", "-E", "globals[*]", "-E", "source_files[*]", "-E", "references[*]", tag)
    after = {field: tool.count(tags, tag, field) for field in counts}
    omission.update(sha256_after=legacy.digest(path), counts_after=after,
                    script_references_after=tool.count(tags, tag, "references"),
                    status="omitted" if not any(after.values()) else "verification_failed")
    steps[-1].update(omission)
    if any(after.values()) or omission["script_references_after"]:
        raise ConversionError("needs_profile", "scripts", "Script omission did not clear all selected fields", omission)


def convert_cache(source: Path, header: dict, workspace: Path, profile: dict,
                  invader_bin: Path, invader_manifest: Path, stock_maps: Path | None,
                  resources: Path | None = None) -> dict:
    """Convert one multiplayer map with a selected, declarative profile.

    The caller owns scanning/output publication. This function writes only a
    fresh workspace; all failed work and helper diagnostics remain there.
    """
    source = source.resolve(strict=True)
    workspace = workspace.resolve()
    stage = "profile"
    tool = None
    protected: dict[Path, str] = {source: legacy.digest(source)}
    original_tree = None
    asset_toolchain = None
    originals = workspace / "source-tags"
    steps: list[dict] = []
    repairs: list[dict] = []
    omissions: list[dict] = []
    try:
        if header.get("sha256") != protected[source]:
            raise ConversionError("input_changed", "profile", "Source cache changed since inventory")
        if header["version"] not in {5, 6, 7, 609, 13} or header["version"] not in profile.get("supported_formats", []):
            raise ConversionError("unsupported_format", "profile", "Profile does not support this cache version")
        target = profile.get("target", {})
        if target.get("engine") != "xbox-ntsc" or target.get("build") != legacy.NTSC_BUILD:
            raise ConversionError("unsupported_target", "profile", "Only Xbox NTSC 2276 output is supported")
        spec = _scenario_spec(profile, header)
        policy = profile.get("dependency_policy", "authored-first")
        scripts = profile.get("script_policy", "preserve")
        if policy not in {"authored-first", "stock-first"} or scripts not in {"preserve", "reviewed", "none", "omit"}:
            raise ConversionError("needs_profile", "profile", "Unknown dependency or script policy")
        reviewed = policy == "stock-first" and scripts == "reviewed"
        presentation_policy = profile.get("presentation_policy", "preserve")
        if presentation_policy not in {"preserve", "native-xbox"}:
            raise ConversionError("needs_profile", "profile", "Unknown presentation policy")
        native_digits = presentation_policy == "native-xbox"
        native_presentation = native_digits and header["version"] == 13
        weapon_policy = profile.get("weapon_policy", "preserve")
        if weapon_policy not in {"preserve", "bungie-originals"}:
            raise ConversionError("needs_profile", "profile", "Unknown weapon policy")
        canonical_weapons = weapon_policy == "bungie-originals"
        placement_policy = profile.get("weapon_placement_policy", "engine-native")
        if placement_policy not in {"engine-native", "authored-default"} or (placement_policy == "authored-default"
                and (not canonical_weapons or not native_digits or policy != "authored-first")):
            raise ConversionError("needs_profile", "weapon_placements", "Authored default placements require original Bungie weapons, native Xbox presentation and authored-first dependencies")
        if canonical_weapons and (reviewed or not stock_maps):
            raise ConversionError("needs_profile", "weapons", "Original Bungie weapon policy requires canonical Xbox stock maps and authored-first dependencies")
        if native_digits and (reviewed or not stock_maps):
            raise ConversionError("needs_profile", "presentation", "Native Xbox presentation requires canonical Xbox stock maps and authored-first dependencies")
        asset_policy = profile.get("asset_policy", {"audio": "preserve", "bitmaps": "preserve"})
        if reviewed and any(value != "preserve" for value in asset_policy.values()):
            raise ConversionError("needs_profile", "profile", "The PB3 collection recipe does not apply generic asset stages")
        if policy == "stock-first" and not reviewed:
            raise ConversionError("needs_profile", "profile", "Stock-first resolution requires the reviewed PB3 recipe")
        if scripts == "reviewed" and not reviewed:
            raise ConversionError("needs_profile", "scripts", "This profile has no supported reviewed script recipe")
        if scripts == "omit" and (not isinstance(profile.get("script_omission_reason"), str)
                or not profile["script_omission_reason"].strip()):
            raise ConversionError("needs_profile", "scripts", "Script omission requires an explicit profile reason")
        if reviewed and (not spec or not spec.get("scenario_sha256") or not profile.get("source_tags") or not stock_maps):
            raise ConversionError("needs_profile", "profile", "The reviewed PB3 recipe requires exact source tags, scenario hash and stock maps")
        if reviewed:
            _reviewed_pb3_spec(spec)
            if profile.get("output_id", spec["id"]) != spec["id"]:
                raise ConversionError("needs_profile", "profile", "The PB3 recipe requires its reviewed output identity")
        if workspace.exists() and any(workspace.iterdir()):
            raise ConversionError("workspace_exists", "prepare", "Conversion workspace must be empty")
        workspace.mkdir(parents=True, exist_ok=True)
        logs = workspace / "logs"
        logs.mkdir()
        stage = "toolchain"
        tool = ApprovedInvader(invader_bin, invader_manifest, logs)
        protected[invader_manifest] = legacy.digest(invader_manifest)
        protected.update({tool.tool_paths[name]: value for name, value in tool.provenance.items()})
        tool.stage = stage = "extract"
        if reviewed:
            input_tags = Path(profile["source_tags"]).resolve(strict=True)
            input_hashes = _tree(input_tags)
            protected.update({input_tags / name: value for name, value in input_hashes.items()})
            shutil.copytree(input_tags, originals)
            steps.append({"operation": "copy_reviewed_source_tags", "source": str(input_tags),
                          "tag_count": len(input_hashes), "sha256": input_hashes})
        else:
            originals.mkdir()
            resource_dir = (resources or source.parent).resolve(strict=True)
            if not resource_dir.is_dir():
                raise ConversionError("missing_resources", stage, "Expected a source resource directory")
            resource_hashes = {}
            for name in ("bitmaps.map", "sounds.map", "loc.map"):
                resource = resource_dir / name
                if resource.exists():
                    if resource.is_symlink() or not resource.is_file():
                        raise ConversionError("invalid_resources", stage, "Resource input must be a regular file")
                    protected[resource] = legacy.digest(resource)
                    resource_hashes[name] = protected[resource]
            tool.run("extract", "-t", originals, "-m", resource_dir, source)
            steps.append({"operation": "extract", "resources": {"directory": str(resource_dir), "sha256": resource_hashes}})
        original_tree = _tree(originals)
        if not original_tree:
            raise ConversionError("invalid_input", "extract", "Extraction produced no tags")
        tags = workspace / "tags"
        shutil.copytree(originals, tags)
        stock = workspace / "stock-tags"
        stock_record = {"inputs": {}, "compatibility_patches": []}
        if stock_maps:
            tool.stage = stage = "stock"
            stock_names = ["bloodgulch", "a10", "ui"]
            if canonical_weapons and (stock_maps / "c40.map").exists():
                stock_names.append("c40")
            for name in stock_names:
                p = stock_maps / f"{name}.map"
                protected[p] = legacy.digest(p)
            stock_record = legacy.prepare_stock(tool, stock_maps, stock) if reviewed else _extract_stock(tool, stock_maps, stock, include_campaign_weapons=canonical_weapons)
        else:
            stock.mkdir()
        steps.append({"operation": "stock_fallback", "policy": policy, **stock_record})
        repairs.extend({"kind": "stock_compatibility", **item} for item in stock_record["compatibility_patches"])
        if reviewed:
            if profile.get("overlays"):
                raise ConversionError("needs_profile", "overlays", "The existing PB3 recipe does not apply extra overlays")
            tool.stage = stage = "compile"
            package = workspace / "reviewed-package"
            package.mkdir()
            shutil.copytree(originals, package / "tags")
            output_dir = workspace / "reviewed-builds"
            output_dir.mkdir()
            spec = {**spec, "display_name": spec.get("display_name", spec.get("id", header["name"]))}
            result = legacy.build_map(tool, spec, package, stock, output_dir)
            output = Path(result["output"])
            result_header = _target_header(output, target, spec["id"])
            steps.append({"operation": "reviewed_pb3_recipe", "result": result})
            if result.get("models_converted"):
                repairs.append({"kind": "model_layout", "count": result["models_converted"],
                                "source": "gbxmodel", "target": "model"})
            repairs.extend({"kind": "extended_shader_layout", **item}
                           for item in result.get("chicago_shader_conversions", []))
            omissions.extend({"kind": "reviewed_optional_script", "name": name}
                             for name in result.get("removed_optional_scripts", []))
            provenance = {"source_tags": original_tree, "stock": stock_record,
                          "dependency_policy": policy, "recipe_manifest": str(output.parent.parent / "manifest.json"),
                          "removed_optional_scripts": result.get("removed_optional_scripts", [])}
        else:
            scenario, compiled = _scenario(tags, header, spec, profile.get("output_id"))
            tool.stage = stage = "scripts"
            script_counts = {field: tool.count(tags, compiled + ".scenario", field) for field in ("scripts", "globals", "source_files")}
            if scripts == "omit":
                original_scenario_hash = legacy.digest(legacy.safe_tag(originals, scenario + ".scenario"))
                _omit_scripts(tool, tags, compiled, profile, header, original_scenario_hash, script_counts, steps, omissions)
            else:
                _script_policy(tool, scripts, script_counts)
                steps.append({"operation": "scripts", "policy": scripts, "source": "tags", "counts": script_counts,
                              "removed": [], "note": "Recovered HSC is compiled for Xbox; incompatible APIs are reported"})
            tool.stage = stage = "models"
            models = [name for name in _tree(tags) if name.endswith(".gbxmodel")]
            if any((tags / name).with_suffix(".model").exists() for name in models):
                raise ConversionError("needs_profile", stage, "Model conversion collides with an authored Xbox model")
            if models:
                tool.run("convert", "-t", tags, "-g", "gbxmodel", "model", "-b", "*.gbxmodel")
                tool.run("refactor", "-t", tags, "-M", "no-move", "-g", "gbxmodel", "model")
            steps.append({"operation": "models", "models_converted": len(models)})
            if models:
                repairs.append({"kind": "model_layout", "count": len(models), "tags": models,
                                "source": "gbxmodel", "target": "model"})
            tool.stage = stage = "shaders"
            shaders = legacy.convert_extended_shaders(tool, tags)
            steps.append({"operation": "extended_shaders", "conversions": shaders})
            repairs.extend({"kind": "extended_shader_layout", **item} for item in shaders)
            stage = "overlays"
            overlays = _checked_overlays(profile.get("overlays", []), [originals, tags, stock])
            if scripts == "omit" and any((root / (name + ".scenario")).is_file()
                    for root in overlays for name in {scenario, compiled}):
                raise ConversionError("needs_profile", "overlays", "Script omission does not allow overlays to replace the source or compiled scenario")
            for root in overlays:
                overlay_record = json.loads((root.parent / "conversion.json").read_text())
                change = {"kind": "reviewed_overlay", "conversion": overlay_record.get("conversion", overlay_record.get("operation")),
                          "manifest": str(root.parent / "conversion.json"),
                          "manifest_sha256": legacy.digest(root.parent / "conversion.json"),
                          "changes": overlay_record.get("actions", overlay_record.get("changes", []))}
                repairs.append(change)
                steps.append({"operation": "reviewed_overlay", **change})
            roots = [*overlays, tags, stock]
            native_hud_tags = set()
            if native_presentation:
                from .presentation import canonical_shell_overlay
                tool.stage = stage = "presentation_shell"
                shell = canonical_shell_overlay(tool, stock, roots, workspace, steps, repairs, protected)
                roots.insert(0, shell)
            scenario_root = next(root for root in roots if (root / (compiled + ".scenario")).is_file())
            if scenario_root != tags:
                tool.stage = stage = "scripts"
                effective_counts = {field: tool.count(scenario_root, compiled + ".scenario", field)
                                    for field in ("scripts", "globals", "source_files")}
                _script_policy(tool, scripts, effective_counts)
                steps.append({"operation": "effective_overlay_scripts", "policy": scripts, "source": "tags",
                              "counts": effective_counts, "removed": [], "tree": str(scenario_root)})
            if canonical_weapons or native_digits or any(value != "preserve" for value in asset_policy.values()):
                from .assets import AssetTools, convert_assets, bitmap_usage_proof
                tool.stage = stage = "asset_dependencies"
                asset_tools = None
                if native_presentation or any(value != "preserve" for value in asset_policy.values()):
                    if not profile.get("asset_manifest"):
                        raise ConversionError("needs_profile", stage, "Selected asset conversion needs --asset-manifest from build_map_asset_tools.py")
                    asset_tools = AssetTools(Path(profile["asset_manifest"]), logs, tool.commands)
                    asset_toolchain = asset_tools.provenance()
                    protected[asset_tools.manifest] = asset_tools.manifest_hash
                decisions = {"audio": asset_policy["audio"], "bitmaps": asset_policy["bitmaps"],
                             "mips": asset_policy.get("dimensions", "preserve"),
                             "packing": asset_policy.get("packing", "preserve"),
                             "extensions": asset_policy.get("extensions", "preserve")}
                for kind, decision in decisions.items():
                    if decision != "preserve":
                        protected[asset_tools.binary(kind)] = asset_toolchain["binaries"][kind]["sha256"]
                if native_presentation:
                    protected[asset_tools.binary("hud")] = asset_toolchain["binaries"]["hud"]["sha256"]
                    protected[asset_tools.binary("mips")] = asset_toolchain["binaries"]["mips"]["sha256"]
                dependency_roots = [compiled + ".scenario"]
                # Invader compiles globals implicitly even when the scenario
                # has no explicit reference to the engine's common assets.
                if any((root / "globals/globals.globals").is_file() for root in roots):
                    dependency_roots.append("globals/globals.globals")
                if native_presentation:
                    dependency_roots.append("ui/ui_tags_loaded_multiplayer_scenario_type.tag_collection")
                def current_dependencies():
                    result = set(dependency_roots)
                    root_args = sum((["-t", root] for root in roots), [])
                    for origin in dependency_roots:
                        result.update(line.strip().replace("\\", "/") for line in
                                      tool.run("dependency", "-r", *root_args, origin).splitlines() if line.strip())
                    return result
                required = current_dependencies()
                if canonical_weapons:
                    from .stock_weapons import canonical_weapon_overlay
                    from .hud import HUD_TYPES
                    tool.stage = stage = "canonical_weapons"
                    overlay = canonical_weapon_overlay(tool, stock, roots, required, compiled + ".scenario",
                                                        workspace, steps, repairs, protected)
                    if overlay:
                        roots.insert(0, overlay)
                        overlay_tags = _tree(overlay)
                        for name in steps[-1]["native_hud_tags"]:
                            if name not in overlay_tags or Path(name).suffix not in HUD_TYPES:
                                raise ConversionError("invalid_output", stage, "Canonical HUD marker does not identify an output HUD tag", {"tag": name})
                            native_hud_tags.add(name)
                        required = current_dependencies()
                if native_presentation and not canonical_weapons and profile.get("stock_weapon_hud_policy", "preserve") == "reuse-native":
                    from .stock_hud import stock_weapon_hud_overlay
                    from .hud import HUD_TYPES
                    tool.stage = stage = "presentation_stock_hud"
                    overlay = stock_weapon_hud_overlay(tool, stock, roots, required, workspace, steps, repairs, protected)
                    if overlay:
                        roots.insert(0, overlay)
                        native_hud_tags.update(name for name in _tree(overlay) if Path(name).suffix in HUD_TYPES)
                        required = current_dependencies()
                if native_digits:
                    from .hud_digits import canonical_hud_digits_overlay
                    tool.stage = stage = "presentation_hud_digits"
                    overlay = canonical_hud_digits_overlay(tool, stock, roots, workspace, steps, repairs, protected)
                    roots.insert(0, overlay)
                    overlay_tags = _tree(overlay)
                    for name in steps[-1]["native_hud_tags"]:
                        if name not in overlay_tags or Path(name).suffix != ".hud_number":
                            raise ConversionError("invalid_output", stage, "Canonical digits marker does not identify an output HUDNumber tag", {"tag": name})
                        native_hud_tags.add(name)
                    required = current_dependencies()
                steps.append({"operation": "asset_dependencies", "roots": dependency_roots,
                              "required_tags": len(required)})
                for kind in ("extensions", "audio", "bitmaps", "mips", "packing"):
                    if decisions[kind] != "preserve":
                        tool.stage = stage = "asset_" + kind
                        shader_only = None
                        if kind == "mips":
                            shader_only = bitmap_usage_proof(asset_tools, roots, required, workspace, steps)
                            protected[shader_only] = legacy.digest(shader_only)
                            protected[shader_only.parent / "usage.json"] = legacy.digest(shader_only.parent / "usage.json")
                        overlay = convert_assets(asset_tools, kind, roots, required, workspace, steps, repairs,
                                                 shader_only=shader_only)
                        if overlay:
                            roots.insert(0, overlay)
                            if kind == "extensions":
                                for repair in repairs:
                                    if repair.get("operation") == "asset_extensions":
                                        omissions.append({**repair, "reason": repair["measurements"]["reason"],
                                                          "policy": decisions[kind]})
                                before_required = required
                                tool.stage = stage = "asset_dependencies"
                                required = current_dependencies()
                                steps.append({"operation": "recompute_target_dependencies", "required_before": len(before_required),
                                              "required_after": len(required), "omitted_dependencies": sorted(before_required - required),
                                              "reason": "No longer reachable after omitting unsupported MCC fields"})
                if native_presentation:
                    from .hud_anchors import normalize_weapon_hud_anchors
                    from .hud import normalize_mcc_hud
                    tool.stage = stage = "presentation_hud_anchors"
                    overlay = normalize_weapon_hud_anchors(tool, roots, required, workspace, steps, repairs, protected,
                                                         native_tags=native_hud_tags)
                    if overlay:
                        roots.insert(0, overlay)
                        required = current_dependencies()
                    tool.stage = stage = "presentation_hud"
                    overlay = normalize_mcc_hud(asset_tools, tool, roots, stock, required,
                                                workspace, steps, repairs, protected, native_tags=native_hud_tags)
                    if overlay:
                        roots.insert(0, overlay)
            from .weapon_placements import audit_weapon_placements, verify_compiled_placements, SOUL
            tool.stage = stage = "weapon_placements"
            placement_overlay, placement_audit = audit_weapon_placements(
                tool, originals, scenario + ".scenario", roots, compiled + ".scenario",
                workspace, steps, repairs, protected, placement_policy, source_fallback=stock)
            if placement_overlay:
                roots.insert(0, placement_overlay)
            snapshots = {str(root): _tree(root) for root in roots}
            tool.stage = stage = "compile"
            maps, data = workspace / "maps", workspace / "data"
            maps.mkdir(); data.mkdir()
            args = ["-g", "xbox-ntsc"]
            for root in roots:
                args += ["-t", root]
            # The engine accepts a bigger file than Invader's retail-console
            # authoring default. -E permits authoring; our native bounds still
            # apply below. Never disable compilation/reference checks.
            args += ["-m", maps, "-d", data, "-S", "tags", "-E", compiled]
            tool.run("build", *args)
            output = maps / f"{Path(compiled).name}.map"
            stage = "verify"
            try:
                result_header = _target_header(output, target, Path(compiled).name)
            except ConversionError as error:
                if error.details.get("limit") and (workspace / "bitmap-usage/usage.json").is_file():
                    usage = json.loads((workspace / "bitmap-usage/usage.json").read_text(encoding="utf-8"))
                    bitmaps = {entry["tag"]: {"tag": entry["tag"], "pixel_bytes": entry["metadata"].get("pixel_bytes", 0),
                                             "consumers": sorted({consumer["class"] for consumer in entry["consumers"]})}
                               for entry in usage["classifications"]}
                    for repair in repairs:
                        if repair.get("tag") in bitmaps:
                            after = repair.get("measurements", {}).get("sizes", {}).get("pixel_after")
                            if type(after) is int:
                                bitmaps[repair["tag"]]["pixel_bytes"] = after
                    error.details["largest_bitmap_inputs"] = sorted(bitmaps.values(), key=lambda entry: (-entry["pixel_bytes"], entry["tag"]))[:20]
                    error.details["bitmap_sizes_scope"] = "winning input tag payloads after conversion; compiler deduplication not included"
                raise
            tool.stage = stage = "weapon_placements_verify"
            verify_compiled_placements(tool, output, workspace, placement_audit, steps)
            for root, snapshot in snapshots.items():
                if _tree(Path(root)) != snapshot:
                    raise ConversionError("input_changed", stage, "Compiler or overlay changed an input tag tree", {"tree": root})
            tool.stage = stage = "dependencies"
            dependencies = []
            origins = [compiled + ".scenario"]
            if any((root / "globals/globals.globals").is_file() for root in roots):
                origins.append("globals/globals.globals")
            if native_presentation:
                origins.append("ui/ui_tags_loaded_multiplayer_scenario_type.tag_collection")
            if placement_audit["capability"]:
                origins.append(SOUL)
            for origin in origins:
                dependencies.extend([origin, *tool.run("dependency", "-r", *sum((["-t", root] for root in roots), []), origin).splitlines()])
            resolved = {}
            for name in dict.fromkeys(item.strip().replace("\\", "/") for item in dependencies if item.strip()):
                for root in roots:
                    candidate = root / name
                    if candidate.is_file():
                        checked = legacy.safe_tag(root, name)
                        resolved[name] = {"tree": str(root), "sha256": legacy.digest(checked),
                                          "origin": "stock-fallback" if root == stock else ("authored-or-converted" if root == tags else "reviewed-overlay")}
                        break
                else:
                    raise ConversionError("missing_dependency", stage, "A reachable tag dependency is unresolved", {"tag": name})
            steps.append({"operation": "compile", "script_source": "tags", "scenario": compiled,
                          "status": "compiled; runtime validation pending"})
            provenance = {"source_tags": original_tree, "stock": stock_record, "dependency_policy": policy,
                          "priority": [str(root) for root in roots], "reachable_tags": resolved,
                          "unused_extracted_tags": sorted(set(original_tree) - set(resolved))}
            if provenance["unused_extracted_tags"]:
                omissions.append({"kind": "unreachable_extracted_tags", "tags": provenance["unused_extracted_tags"],
                                  "reason": "Not reachable from the compiled scenario; required dependencies are retained"})
        changed = _changed_inputs(protected, originals, original_tree)
        if changed:
            raise ConversionError("input_changed", "verify", "An immutable input changed during conversion", {"paths": changed})
        return {"output": output, "header": result_header, "steps": steps, "repairs": repairs, "omissions": omissions,
                "toolchain": {"invader_commit": tool.commit, "binaries": tool.provenance,
                              "source_patches": tool.source_patches,
                              "asset_tools": asset_toolchain,
                              "manifest": str(invader_manifest), "manifest_sha256": legacy.digest(invader_manifest),
                              "commands": tool.commands}, "provenance": provenance}
    except ConversionError as error:
        if asset_toolchain:
            error.details.setdefault("asset_tools", asset_toolchain)
        error.details.setdefault("steps", steps)
        error.details.setdefault("repairs", repairs)
        error.details.setdefault("omissions", omissions)
        changed = _changed_inputs(protected, originals, original_tree)
        if changed and error.code != "input_changed":
            raise ConversionError("input_changed", "verify", "An immutable input changed during conversion",
                                  {"paths": changed, "original_error": {"code": error.code, "stage": error.stage,
                                                                       "message": error.message, "details": error.details},
                                   "workspace": str(workspace), "commands": tool.commands if tool else [],
                                   "steps": steps, "repairs": repairs, "omissions": omissions}) from error
        if tool is not None:
            error.details.setdefault("commands", tool.commands)
            error.details.setdefault("output", "\n".join(command.get("output", command.get("stderr", ""))
                                                           for command in tool.commands)[-OUTPUT_EXCERPT_CHARS:])
        error.details.setdefault("workspace", str(workspace))
        raise
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        code = "toolchain_invalid" if stage == "toolchain" else "needs_profile"
        details = {"workspace": str(workspace), "steps": steps, "repairs": repairs, "omissions": omissions}
        if tool is not None:
            details["commands"] = tool.commands
            details["output"] = "\n".join(command.get("output", command.get("stderr", ""))
                                           for command in tool.commands)[-OUTPUT_EXCERPT_CHARS:]
        changed = _changed_inputs(protected, originals, original_tree)
        if changed:
            code, stage = "input_changed", "verify"
            details.update(paths=changed, original_error=str(error))
        raise ConversionError(code, stage, str(error), details) from error
