"""Canonical original-Xbox weapon assets for the bungie-originals policy.

Authored scenario references remain intact. Identified weapons resolve to their
original gameplay, model, projectile, sound and HUD dependency trees under one
private namespace. The sole globals change is the original weapon registry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from .backend import ConversionError, _tree, legacy
from .stock_hud import IDENTITY_FIELDS, _reference

GLOBALS = "globals/globals.globals"
NAMESPACE = "__native_weapons/og"
NATIVE_MODEL = re.compile(r"\A__native_weapons/og/[0-9a-f]{16}/(.+\.model)\Z")
COMPLETION_FIELDS = {"first_person_model": "model", "first_person_animations": "model_animations",
                     "hud_interface": "weapon_hud_interface"}
# These original gametype objects intentionally lack a player-gun interface.
OBJECTIVE_WEAPONS = frozenset({"weapons/ball/ball.weapon", "weapons/flag/flag.weapon"})
HUD_CLASSES = frozenset({"weapon_hud_interface", "unit_hud_interface",
                         "grenade_hud_interface", "hud_globals", "hud_number"})
# Original HEK cache classes; complete stock dependency closure is allowed, but
# scenarios, BSPs and globals are map/engine roots rather than weapon assets.
ASSET_CLASSES = frozenset("""actor actor_variant antenna biped bitmap camera_track
color_table contrail damage_effect decal device_control device_light_fixture
device_machine dialogue effect equipment flag fog font garbage glow grenade_hud_interface
hud_globals hud_message_text hud_number input_device_defaults item_collection lens_flare
light light_volume lightning material_effects meter model gbxmodel model_animations
model_collision_geometry multiplayer_scenario_description particle particle_system
physics placeholder point_physics projectile scenery shader_environment shader_model
shader_transparent_chicago shader_transparent_chicago_extended shader_transparent_generic
shader_transparent_glass shader_transparent_meter shader_transparent_plasma
shader_transparent_water sky sound sound_environment sound_looping sound_scenery
spheroid string_list tag_collection ui_widget_collection ui_widget_definition
unicode_string_list unit_hud_interface vehicle virtual_keyboard weapon
weapon_hud_interface wind""".split())


def _fail(message, code="needs_profile", **details):
    raise ConversionError(code, "canonical_weapons", message, details)


def _name(value, classes=ASSET_CLASSES):
    if not isinstance(value, str):
        _fail("Canonical asset reference is not a tag path")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(char in value for char in "\t\r\n\0:")
            or path.suffix.removeprefix(".") not in classes):
        _fail("Canonical weapon dependency has an unsafe path or non-asset class", tag=value)
    return value


def _path(root, name, classes=ASSET_CLASSES):
    name = _name(name, classes)
    at = Path(root)
    if at.is_symlink() or not at.is_dir():
        _fail("Canonical weapon inputs must be regular tag directories")
    for part in PurePosixPath(name).parts:
        at /= part
        if at.is_symlink():
            _fail("Linked canonical weapon inputs are unsupported", tag=name)
    if not at.is_file() or at.stat().st_nlink != 1:
        _fail("Canonical weapon dependency is missing or linked", tag=name)
    return at


def _winner(roots, name, classes=ASSET_CLASSES):
    for root in roots:
        if (root / name).exists() or (root / name).is_symlink():
            return root, _path(root, name, classes)
    return None


def _dependencies(tool, roots, name, classes=ASSET_CLASSES):
    result = {name}
    args = sum((["-t", root] for root in roots), [])
    for line in tool.run("dependency", "-r", *args, name).splitlines():
        if not line.strip():
            continue
        if line.endswith(" [BROKEN]"):
            _fail("Canonicalization requires an unavailable dependency", tag=name,
                  missing_tag=line[:-9].replace("\\", "/"))
        result.add(_name(line, classes))
    for dependency in result:
        if not _winner(roots, dependency, classes):
            _fail("Canonicalization requires an unavailable dependency", tag=name, missing_tag=dependency)
    return result


def _identity(tool, root, name):
    values = []
    for field in IDENTITY_FIELDS:
        value = tool.get(root, name, field)
        value = _reference(value, "model") if field == "model" else value.strip()
        values.append(value)
    return tuple(values)


def _original_identity(identity):
    # Older converted maps may use a previous original-library fingerprint.
    # Recognize only our exact namespace shape; unique stock identity is still
    # required, and every selected asset is replaced from the current library.
    match = NATIVE_MODEL.fullmatch(identity[0])
    if match:
        return (_name(match.group(1), {"model"}), *identity[1:]), True
    return identity, False


def _original_classification(tool, stock, name):
    """Classify original assets by their actual missing player-use fields.

    This covers original cut/NPC guns, including Gravity Rifle. The original
    Flamethrower has all three fields and remains a complete canonical gun.
    Vehicle guns and gametype objects intentionally use other presentation.
    """
    if name.startswith("vehicles/") or name in OBJECTIVE_WEAPONS:
        return {"classification": "original_non_player_weapon", "missing_fields": {}, "stock_fields": {}}
    fields = {field: _reference(tool.get(stock, name, field), tag_class)
              for field, tag_class in COMPLETION_FIELDS.items()}
    missing = {field: "Original tag has a null " + tag_class + " reference"
               for field, tag_class in COMPLETION_FIELDS.items() if not fields[field]}
    return {"classification": "unfinished_original_player_interface" if missing else "complete_original_weapon",
            "missing_fields": missing, "stock_fields": fields}


def _registry(tool, root, canonical=False):
    count = tool.count(root, GLOBALS, "weapon_list")
    if not 0 < count <= 64:
        _fail("Weapon registry must contain a bounded original list", count=count)
    result = [_name(tool.get(root, GLOBALS, f"weapon_list[{index}].weapon"), {"weapon", "equipment"})
              for index in range(count)]
    if canonical and len(result) != len(set(result)):
        _fail("Canonical weapon registry contains duplicate entries")
    return result


def _without_registry(listing):
    """Preserve the complete native parser dump outside the sole edited array."""
    kept, skipping, found = [], False, False
    for line in listing.splitlines():
        if line.startswith("weapon_list["):
            if found:
                _fail("Globals parser lists the weapon registry more than once", "invalid_output")
            found, skipping = True, True
            continue
        if skipping and line and line[0].isascii() and line[0].isalpha():
            skipping = False
        if not skipping:
            kept.append(line)
    if not found:
        _fail("Globals parser did not expose its weapon registry", "invalid_output")
    return "\n".join(kept)


def canonical_weapon_overlay(tool, stock, roots, required, scenario, workspace,
                             steps, repairs, protected, *, lineage_catalog=None,
                             lineage_source=None, lineage_derived=None):
    stock, workspace = Path(stock), Path(workspace)
    roots = [Path(root) for root in roots]
    folder, overlay = workspace / "canonical-weapons", workspace / "canonical-weapons/tags"
    if folder.exists() or folder.is_symlink() or workspace.is_symlink() or not workspace.is_dir():
        _fail("Canonical weapon output requires a fresh regular workspace", "invalid_output")
    input_roots = [stock, *roots]
    if lineage_catalog is not None:
        if lineage_source is None:
            _fail("A weapon lineage catalog requires immutable extracted source tags")
        lineage_source = Path(lineage_source)
        input_roots.append(lineage_source)
    inventories = {root: _tree(root) for root in dict.fromkeys(input_roots)}
    for root, inventory in inventories.items():
        for name, expected in inventory.items():
            path = root / name
            if path in protected and protected[path] != expected:
                _fail("Protected input changed before weapon canonicalization", "input_changed", tag=name)
            protected[path] = expected

    def unchanged():
        for root, inventory in inventories.items():
            if _tree(root) != inventory:
                _fail("Weapon canonicalization changed an input tree", "input_changed")

    fingerprint = hashlib.sha256(json.dumps(inventories[stock], sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
    private_prefix = f"{NAMESPACE}/{fingerprint[:16]}/"
    tool.stage = "canonical_weapons"
    _path(stock, GLOBALS, {"globals"})
    winning_globals = _winner(roots, GLOBALS, {"globals"})
    if winning_globals is None:
        _fail("Authored globals are required to preserve non-weapon engine settings", tag=GLOBALS)
    globals_root, globals_path = winning_globals
    source_registry = _registry(tool, globals_root)
    stock_registry = _registry(tool, stock, canonical=True)
    scenario = scenario.replace("\\", "/")
    if not scenario.endswith(".scenario"):
        scenario += ".scenario"
    _name(scenario, {"scenario"})
    scenario_classes = ASSET_CLASSES | {"globals", "scenario", "scenario_structure_bsp"}
    scenario_dependencies = _dependencies(tool, roots, scenario, scenario_classes)
    scenario_weapons = sorted(name for name in scenario_dependencies if name.endswith(".weapon"))
    stock_weapons = sorted(name for name in inventories[stock] if name.endswith(".weapon"))
    if len(stock_weapons) > 256 or len(scenario_weapons) > 256:
        _fail("Weapon identity index exceeds its bounded original-asset scope")
    stock_identities = {name: _identity(tool, stock, name) for name in stock_weapons}
    by_identity = {}
    for name, identity in stock_identities.items():
        by_identity.setdefault(identity, []).append(name)
    catalog = {}
    def classification(name):
        if name not in catalog:
            catalog[name] = _original_classification(tool, stock, name)
        return catalog[name]
    reviewed_matches, reviewed_errors = {}, {}

    def reviewed(name):
        """Bind ancestry review to originals, before format conversion changes tags."""
        if lineage_catalog is None:
            return None
        if name in reviewed_matches:
            return reviewed_matches[name]
        if name in reviewed_errors:
            return None
        from .weapon_lineage import match_variant, variants_for_weapon
        variants = variants_for_weapon(lineage_catalog, name)
        if not variants:
            return None
        if name not in inventories[lineage_source]:
            reviewed_errors[name] = {"weapon": name, "reason": "Reviewed weapon is absent from immutable source tags",
                                     "lineage_status": "missing_source"}
            return None
        raw_identity = dict(zip(IDENTITY_FIELDS, _identity(tool, lineage_source, name)))
        raw_closure = _dependencies(tool, [lineage_source], name)
        raw_hashes = {tag: inventories[lineage_source][tag] for tag in sorted(raw_closure)}
        entry, mismatches = match_variant(lineage_catalog, name, raw_identity, raw_hashes)
        if entry is None:
            reviewed_errors[name] = {"weapon": name, "identity": raw_identity,
                                     "reason": "Weapon differs from every reviewed original-asset variant",
                                     "lineage_status": "variant_mismatch", "lineage_mismatches": mismatches}
            return None
        proof = {"asset_id": entry["asset_id"], "variant_id": entry["variant_id"],
                 "outcome": entry["outcome"], "ancestor": entry["ancestor"],
                 "evidence": entry["evidence"], "reason": entry["reason"],
                 "source_sha256": raw_hashes[name], "original_source_closure_sha256": raw_hashes}
        if "approval" in entry:
            proof["approval"] = entry["approval"]
        if entry["outcome"] in {"unsupported", "unverified", "omit"}:
            reviewed_errors[name] = {"weapon": name, "identity": raw_identity,
                                     "reason": "Explicitly excluded weapon still has a reachable reference after the omission stage" if entry["outcome"] == "omit" else entry["reason"],
                                     "lineage_status": entry["outcome"],
                                     "reviewed_lineage": proof}
            return None
        canonical = entry["ancestor"]["stock_weapon"] if entry["ancestor"] else None
        if canonical is not None and canonical not in stock_identities:
            reviewed_errors[name] = {"weapon": name, "reason": "Reviewed original ancestor is unavailable in the stock library",
                                     "lineage_status": "missing_ancestor", "stock_weapon": canonical,
                                     "reviewed_lineage": proof}
            return None
        # The backend snapshots tags after pinned model/shader conversion,
        # before optional authored overlays. Bind every winning dependency to
        # that snapshot, so a source receipt cannot admit a changed projectile,
        # damage effect, model or weapon through a higher-priority overlay.
        def converted_tag(tag):
            if lineage_derived is None:
                return tag
            if tag.endswith(".gbxmodel"):
                return tag.removesuffix(".gbxmodel") + ".model"
            if tag.endswith(".shader_transparent_chicago_extended"):
                return tag.removesuffix(".shader_transparent_chicago_extended") + ".shader_transparent_chicago"
            return tag
        expected = {converted_tag(tag): (lineage_derived.get(converted_tag(tag))
                                        if lineage_derived is not None else checksum)
                    for tag, checksum in raw_hashes.items()}
        closure = _dependencies(tool, roots, name)
        winning_hashes = {tag: legacy.digest(_winner(roots, tag)[1]) for tag in sorted(closure)}
        missing, extra = sorted(set(expected) - closure), sorted(closure - set(expected))
        changed = {tag: {"expected": expected[tag], "actual": winning_hashes[tag]}
                   for tag in sorted(set(expected) & closure) if expected[tag] != winning_hashes[tag]}
        if missing or extra or changed:
            reviewed_errors[name] = {"weapon": name, "reason": "Winning weapon closure changed beyond verified format conversion",
                                     "lineage_status": "unreviewed_overlay", "reviewed_lineage": proof,
                                     "missing_tags": missing, "extra_tags": extra, "changed_dependencies": changed}
            return None
        proof["working_source_closure_sha256"] = winning_hashes
        proof["verified_format_conversion"] = lineage_derived is not None
        reviewed_matches[name] = proof
        return proof

    def reviewed_ancestor(name, identity, proof):
        # Reviewed completions cannot turn an already identifiable, complete
        # retail gun into an authored variant, even with contradictory ancestry
        # metadata. Keep the user's stock-asset preference unconditional.
        candidates = by_identity.get(identity, [])
        known = name if stock_identities.get(name) == identity else candidates[0] if len(candidates) == 1 else None
        if known and classification(known)["classification"] == "complete_original_weapon":
            proof["applied_outcome"] = "canonical-stock"
            proof["canonical_stock_preference"] = known
            return known
        proof["applied_outcome"] = proof["outcome"]
        return proof["ancestor"]["stock_weapon"] if proof["ancestor"] else None

    candidate_weapons = set(scenario_weapons)
    inherited_resident_weapons = []
    if lineage_source is not None:
        from .weapon_residency import COLLECTION
        if (lineage_source / COLLECTION).is_file():
            count = tool.count(lineage_source, COLLECTION, "tags")
            if type(count) is not int or not 0 <= count <= 200:
                _fail("Inherited weapon residency exceeds its bounded asset scope", tag=COLLECTION)
            for index in range(count):
                name = _name(tool.get(lineage_source, COLLECTION, f"tags[{index}].reference").strip(), {"weapon"})
                if _winner(roots, name) is None:
                    _fail("Inherited resident weapon is unavailable", tag=COLLECTION,
                          field=f"tags[{index}].reference", weapon=name)
                inherited_resident_weapons.append(name)
            if len(set(inherited_resident_weapons)) != len(inherited_resident_weapons):
                _fail("Inherited weapon residency has duplicate references", tag=COLLECTION)
            # The native shell can replace the source Soul root. Still review
            # inherited library assets individually instead of silently losing
            # those that were previously reachable only through residency.
            candidate_weapons.update(inherited_resident_weapons)
    registry_originals, discarded_registry_weapons = {}, []
    # Keep a completed original prototype supplied through the source registry
    # even when this particular scenario has no placed instance of that gun.
    for name in source_registry:
        if not name.endswith(".weapon"):
            continue
        source = _winner(roots, name)
        if not source:
            continue
        identity, _ = _original_identity(_identity(tool, source[0], name))
        candidates = by_identity.get(identity, [])
        proof = reviewed(name)
        canonical = (reviewed_ancestor(name, identity, proof) if proof else
                     name if stock_identities.get(name) == identity else candidates[0] if len(candidates) == 1 else None)
        if (canonical or proof) and name not in reviewed_errors:
            registry_originals[name] = canonical
            if (proof and proof["outcome"] in {"original-completion", "approved-community"}) or (canonical and classification(canonical)["missing_fields"]) or canonical not in stock_registry:
                candidate_weapons.add(name)
        else:
            discarded_registry_weapons.append({"weapon": name, "identity": dict(zip(IDENTITY_FIELDS, identity)),
                                                "stock_candidates": candidates,
                                                **reviewed_errors.get(name, {"reason": "No identifiable original Halo 1 registry ancestor"})})
    assignments, identity_proofs, blockers, completions = {}, {}, [], {}
    pending = sorted(candidate_weapons)
    processed = set()
    while pending:
        name = pending.pop(0)
        if name in processed:
            continue
        processed.add(name)
        if len(processed) > 256:
            _fail("Weapon completion closure exceeds the bounded original-asset scope")
        source = _winner(roots, name)
        identity, previous_native = _original_identity(_identity(tool, source[0], name))
        candidates = by_identity.get(identity, [])
        proof = reviewed(name)
        if name in reviewed_errors:
            blockers.append({"stock_candidates": candidates, **reviewed_errors[name]})
            continue
        if proof:
            canonical = reviewed_ancestor(name, identity, proof)
            match = "reviewed_community_exception" if proof["outcome"] == "approved-community" else "reviewed_original_lineage"
        elif previous_native and len(candidates) != 1:
            blockers.append({"weapon": name, "identity": dict(zip(IDENTITY_FIELDS, identity)),
                             "stock_candidates": candidates,
                             "reason": "Previous original-weapon model alias lacks a unique current stock identity"})
            continue
        elif stock_identities.get(name) == identity:
            canonical, match = name, "same_path_and_identity"
        else:
            if len(candidates) != 1:
                blockers.append({"weapon": name, "identity": dict(zip(IDENTITY_FIELDS, identity)),
                                 "stock_candidates": candidates,
                                 "reason": "No unique verified original Xbox weapon identity"})
                continue
            canonical, match = candidates[0], "unique_stock_model_type_label"
        identity_proofs[name] = {"stock_weapon": canonical, "source": dict(zip(IDENTITY_FIELDS, identity)),
                                "stock": dict(zip(IDENTITY_FIELDS, stock_identities[canonical])) if canonical else None, "match": match,
                                "previous_native_model_namespace": previous_native}
        if proof:
            identity_proofs[name]["reviewed_lineage"] = proof
        original = classification(canonical) if canonical else {
            "classification": "approved_community_weapon" if proof and proof["outcome"] == "approved-community" else "reviewed_recovered_halo1_weapon",
            "missing_fields": {}, "stock_fields": {}}
        if proof and proof["outcome"] == "original-completion" and canonical and original["classification"] == "original_non_player_weapon":
            fields = {field: _reference(tool.get(stock, canonical, field), tag_class)
                      for field, tag_class in COMPLETION_FIELDS.items()}
            original = {"classification": "reviewed_original_non_player_completion",
                        "stock_fields": fields,
                        "missing_fields": {field: "Original tag lacks a player-use reference" for field, value in fields.items() if not value}}
        completed_fields = {}
        # A recovered prerelease ancestor or explicitly approved community
        # weapon can be absent from every shipped cache. Record supplied
        # interface assets without inventing missing historical fields.
        supplied_fields = COMPLETION_FIELDS if proof and canonical is None else original["missing_fields"]
        for field in supplied_fields:
            tag_class = COMPLETION_FIELDS[field]
            reference = _reference(tool.get(source[0], name, field), tag_class)
            if reference:
                reference = _name(reference, {tag_class})
                dependency = _winner(roots, reference)
                if not dependency:
                    _fail("An original-weapon completion references a missing asset", weapon=name, field=field, tag=reference)
                completed_fields[field] = {"reference": reference, "sha256": legacy.digest(dependency[1])}
        retain_reviewed = bool(proof and proof["outcome"] in {"original-completion", "approved-community"}
                               and (canonical is None or original["missing_fields"]))
        # An admission record never overrides the preference for a complete
        # shipped gun. Its customized source payload is replaced from stock.
        if (completed_fields and (proof is None or proof["outcome"] in {"original-completion", "approved-community"})) or retain_reviewed:
            closure = _dependencies(tool, roots, name)
            closure_hashes = {dependency: legacy.digest(_winner(roots, dependency)[1]) for dependency in sorted(closure)}
            for dependency in closure:
                if not dependency.endswith(".weapon"):
                    continue
                dependency_root = _winner(roots, dependency)
                dependency_identity, native = _original_identity(_identity(tool, dependency_root[0], dependency))
                ancestors = by_identity.get(dependency_identity, [])
                same_path = stock_identities.get(dependency) == dependency_identity
                dependency_review = reviewed(dependency)
                if dependency in reviewed_errors or not (dependency_review or (same_path and not native) or len(ancestors) == 1):
                    _fail("A retained authored weapon depends on a weapon without admitted lineage or an explicit exception",
                          weapon=name, unrelated_weapon=dependency, identity=dict(zip(IDENTITY_FIELDS, dependency_identity)),
                          lineage_diagnostic=reviewed_errors.get(dependency))
                # Registry-only completions can reference other weapons that
                # are not in the scenario graph. Apply every nested weapon's
                # reviewed outcome through the same canonicalization path.
                if dependency not in candidate_weapons:
                    candidate_weapons.add(dependency)
                    pending.append(dependency)
                    pending.sort()
            remaining = sorted(set(original["missing_fields"]) - set(completed_fields))
            completions[name] = {"stock_weapon": canonical, "identity": identity_proofs[name],
                                 "classification": original["classification"], "stock_missing_fields": original["missing_fields"],
                                 "stock_fields": original["stock_fields"], "authored_completed_fields": completed_fields,
                                 "remaining_missing_fields": remaining, "source_sha256": legacy.digest(source[1]),
                                 "closure_sha256": closure_hashes,
                                 "closure_fingerprint": hashlib.sha256(json.dumps(closure_hashes, sort_keys=True).encode()).hexdigest(),
                                 "gameplay_validation": "pending", "presentation_validation": "pending",
                                 "diagnostic": "Original completion retained; remaining player-interface gaps require review" if remaining else "Original completion retained; behavior validation is pending"}
            if proof:
                completions[name].update({"reviewed_lineage": proof,
                                          "original_source_closure_sha256": proof["original_source_closure_sha256"],
                                          "historical_missing_fields_verified": canonical is not None})
                if proof["applied_outcome"] == "approved-community":
                    completions[name]["diagnostic"] = "Approved community weapon retained by explicit user decision; gameplay validation is pending"
        else:
            if proof:
                proof["applied_outcome"] = "canonical-stock"
                proof["canonical_stock_preference"] = canonical
            assignments[name] = canonical
    if blockers:
        _fail("Scenario contains weapons without an admitted asset decision or unique original Xbox identity",
              unknown_weapons=blockers, policy="bungie-originals",
              reviewed_lineage_matches=reviewed_matches,
              lineage_catalog={key: lineage_catalog[key] for key in ("id", "version", "sha256")} if lineage_catalog else None)
    community_exceptions = {name: completion for name, completion in completions.items()
                            if completion["classification"] == "approved_community_weapon"}
    original_completions = {name: completion for name, completion in completions.items()
                            if name not in community_exceptions}
    completed_by_original = {}
    for name, completion in completions.items():
        if name in stock_registry and completion["stock_weapon"] != name:
            _fail("An original completion occupies a different original registry weapon path",
                  weapon=name, original_registry_ancestor=name, completion_ancestor=completion["stock_weapon"])
        if completion["stock_weapon"] is not None:
            completed_by_original.setdefault(completion["stock_weapon"], []).append(name)
    completion_registry_aliases = {}
    for name in stock_registry:
        if name in completed_by_original:
            candidates = completed_by_original[name]
            if name in candidates:
                selected_completion = name
            elif len(candidates) == 1:
                selected_completion = candidates[0]
            else:
                _fail("Original registry root has several different authored completions", stock_weapon=name, completions=candidates)
            completion_registry_aliases[name] = selected_completion
            continue
        if name in assignments and assignments[name] != name:
            _fail("A scenario weapon alias collides with an original registry root", weapon=name,
                  stock_weapon=assignments[name])
        assignments[name] = name
    # Keep extra resident weapon roots in authored order. They do not add new
    # roles to the original enum-indexed Globals registry.
    additional_registry = list(dict.fromkeys(name for name in source_registry
                                            if name in registry_originals and registry_originals[name] not in stock_registry))
    additional_registry += [name for name in inherited_resident_weapons
                            if name not in stock_registry and name not in additional_registry
                            and (name in completions or (name in assignments and assignments[name] not in stock_registry))]
    # Recovered ancestors may be reachable only through scenario equipment.
    # Retain every admitted completion and original NPC alias as a dependency
    # root even when the authored registry omits it.
    additional_registry += [name for name in sorted(candidate_weapons)
                            if name not in stock_registry and name not in additional_registry
                            and (name in completions or (name in assignments and assignments[name] not in stock_registry))]
    # The native matg list supplies the fixed Xbox weapon-set roles; it is not
    # an inventory of every loaded weapon. Unlisted weapons remain playable
    # through their authored references (game_engine_remap_weapon's NONE path).
    # Keep its exact prefix and root additions through a resident collection.
    target_registry = stock_registry
    resident_weapon_roots = additional_registry
    resident_community_weapon_roots = [name for name in resident_weapon_roots if name in community_exceptions]
    resident_original_weapon_roots = [name for name in resident_weapon_roots if name not in community_exceptions]
    if len(target_registry) > 20 or len(resident_weapon_roots) > 200:
        _fail("Reviewed weapon residency exceeds native tag collection bounds",
              registry_count=len(target_registry), resident_count=len(resident_weapon_roots))
    # A completed ancestor may also have another uncompleted source alias.
    # Keep that alias canonical; only the explicitly completed implementation
    # and its original registry alias are retained from authored inputs.
    canonical_roots = set(assignments.values())
    full_closure = set()
    for name in sorted(canonical_roots):
        full_closure.update(_dependencies(tool, [stock], name))
    aliases = {name: private_prefix + name for name in full_closure}
    # A repeat import may already contain this source-fingerprinted namespace.
    # Its original assets are selected again under the same explicit policy.
    previous_private = {alias: _winner(roots, alias) for alias in aliases.values()}
    globals_other_fields = _without_registry(tool.run("edit", "-t", globals_root, "-L", GLOBALS))
    unchanged()
    overlay.mkdir(parents=True)
    staging = folder / "staging/tags"
    staging.mkdir(parents=True)
    for name in sorted(full_closure):
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_path(stock, name), target)
        if legacy.digest(target) != inventories[stock][name]:
            _fail("Canonical weapon copy differs from the original Xbox source", "invalid_output", tag=name)
    args = ["-t", staging, "-M", "move"]
    for name in sorted(full_closure):
        args += ["-T", name, aliases[name]]
    tool.run("refactor", *args)
    private_names = set(aliases.values())
    if set(_tree(staging)) != private_names:
        _fail("Original-weapon refactor produced an unexpected inventory", "invalid_output")
    for name in sorted(canonical_roots):
        refs = _dependencies(tool, [staging], aliases[name])
        if not refs.issubset(private_names):
            _fail("Original weapon still references an unisolated dependency", "invalid_output", tag=name)
    actions = []
    for name, alias in sorted(aliases.items()):
        target = overlay / alias
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_path(staging, alias), target)
        actions.append({"kind": "canonical_weapon_asset", "tag": alias, "stock_tag": name,
                        "source_sha256": inventories[stock][name], "sha256_after": legacy.digest(target),
                        "sha256_before": legacy.digest(previous_private[alias][1]) if previous_private[alias] else None,
                        "tag_class": Path(name).suffix[1:], "references_private": True,
                        "operation": "private_original_asset_copy"})
    for source_name, canonical in sorted(assignments.items()):
        target = overlay / source_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(overlay / aliases[canonical], target)
        before = _winner(roots, source_name)
        refs = _dependencies(tool, [overlay], source_name) - {source_name}
        if not refs.issubset(private_names):
            _fail("Original weapon alias has an unisolated dependency", "invalid_output", tag=source_name)
        actions.append({"kind": "canonical_weapon_root", "tag": source_name, "stock_tag": canonical,
                        "source_sha256": inventories[stock][canonical],
                        "sha256_before": legacy.digest(before[1]) if before else None,
                        "sha256_after": legacy.digest(target), "private_root_alias": aliases[canonical],
                        "identity": identity_proofs.get(source_name), "operation": "original_weapon_reuse",
                        "reason": "Use complete original Xbox weapon assets under bungie-originals"})
    for original_name, source_name in sorted(completion_registry_aliases.items()):
        # Preserve the complete authored implementation and references. Only an
        # alias is needed when the original registry name differs; the authored
        # dependency tree continues to resolve through its unchanged input root.
        if original_name != source_name:
            target = overlay / original_name
            target.parent.mkdir(parents=True, exist_ok=True)
            source = _winner(roots, source_name)
            shutil.copyfile(source[1], target)
            actions.append({"kind": "original_completion_registry_alias", "tag": original_name,
                            "source_tag": source_name, "sha256_after": legacy.digest(target),
                            "source_sha256": legacy.digest(source[1]), "operation": "retain_original_completion"})
    for name, completion in sorted(completions.items()):
        community = name in community_exceptions
        actions.append({"kind": "approved_community_weapon" if community else "original_weapon_completion", "tag": name,
                        "operation": "retain_approved_community_weapon" if community else "retain_original_completion",
                        **completion, "stock_sha256": inventories[stock].get(completion["stock_weapon"]),
                        "canonical_og_payload": False,
                        "reason": "Explicit user-approved community exception; no original Halo 1 ancestry claimed" if community else "Authored implementation completes verified original Halo 1 weapon gaps"})
    target_globals = overlay / GLOBALS
    target_globals.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(globals_path, target_globals)
    args = ["-t", overlay, "-E", "weapon_list[*]", "-I", "weapon_list", len(target_registry), "0"]
    for index, name in enumerate(target_registry):
        args += ["-S", f"weapon_list[{index}].weapon", name]
    tool.run("edit", *args, GLOBALS)
    if _registry(tool, overlay) != target_registry:
        _fail("Original weapon registry failed native reparse verification", "invalid_output")
    if _without_registry(tool.run("edit", "-t", overlay, "-L", GLOBALS)) != globals_other_fields:
        _fail("Replacing the weapon registry changed other authored globals fields", "invalid_output")
    removed = sorted(set(source_registry) - set(target_registry))
    actions.append({"kind": "canonical_weapon_registry", "tag": GLOBALS,
                    "source_sha256": legacy.digest(globals_path), "stock_sha256": inventories[stock][GLOBALS],
                    "sha256_before": legacy.digest(globals_path), "sha256_after": legacy.digest(target_globals),
                    "source_registry": source_registry, "stock_registry": stock_registry,
                    "target_registry": target_registry, "additional_original_registry": [],
                    "additional_community_registry": [],
                    "removed_registry_references": removed, "other_globals_fields_verified": True,
                    "operation": "original_weapon_registry", "reason": "Restore the original Xbox registry and ordering"})
    if resident_weapon_roots:
        from .weapon_residency import attach_weapon_residency
        residency = attach_weapon_residency(tool, [overlay, *roots], resident_weapon_roots,
                                            overlay, protected)
        if residency is not None:
            actions.append(residency)
    unchanged()
    output = _tree(overlay)
    # HUDs copied into this overlay are current canonical native stock payloads.
    # Authored completion HUDs stay in input roots and receive MCC conversion;
    # a completion referencing a canonical copied HUD uses its native winner.
    completion_hud_tags = {name for completion in completions.values() for name in completion["closure_sha256"]
                           if Path(name).suffix[1:] in HUD_CLASSES}
    native_hud_tags = sorted(name for name in output if Path(name).suffix[1:] in HUD_CLASSES)
    record = {"schema_version": 1, "operation": "canonical_weapons", "policy": "bungie-originals", "status": "converted",
              "source_unchanged": True, "stock_tree_sha256": fingerprint,
              "identity_criteria": ["model", "weapon_type", "label"], "identity_proofs": identity_proofs,
              "lineage_catalog": {key: lineage_catalog[key] for key in ("id", "version", "sha256")} if lineage_catalog else None,
              "reviewed_lineage_matches": reviewed_matches,
              "canonical_roots": sorted(canonical_roots), "source_weapon_aliases": assignments,
              "original_asset_catalog": catalog, "authored_original_completions": original_completions,
              "authored_community_exceptions": community_exceptions,
              "resident_weapon_roots": resident_weapon_roots,
              "resident_original_weapon_roots": resident_original_weapon_roots,
              "resident_community_weapon_roots": resident_community_weapon_roots,
              "inherited_resident_weapons": inherited_resident_weapons,
              "completion_registry_aliases": completion_registry_aliases,
              "authored_completion_hud_tags": sorted(completion_hud_tags),
              "source_registry": source_registry, "stock_registry": stock_registry,
              "target_registry": target_registry, "additional_original_registry": [],
              "additional_community_registry": [],
              "discarded_registry_weapons": discarded_registry_weapons,
              "removed_registry_references": removed, "other_globals_fields_verified": True,
              "actions": actions, "output_sha256": output, "native_hud_tags": native_hud_tags,
              "gameplay_validation": "pending", "presentation_validation": "pending"}
    manifest = folder / "conversion.json"
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    protected[manifest] = legacy.digest(manifest)
    for name, expected in output.items():
        protected[overlay / name] = expected
    repairs.extend(actions)
    steps.append({"operation": "canonical_weapons", "policy": "bungie-originals", "stock_tree_sha256": fingerprint,
                  "scenario_weapons": len(scenario_weapons), "weapon_roots_reused": len(assignments),
                  "canonical_assets": len(full_closure), "native_hud_tags": native_hud_tags,
                  "original_asset_catalog": catalog, "authored_original_completions": original_completions,
                  "authored_community_exceptions": community_exceptions,
                  "resident_weapon_roots": resident_weapon_roots,
                  "resident_original_weapon_roots": resident_original_weapon_roots,
                  "resident_community_weapon_roots": resident_community_weapon_roots,
                  "inherited_resident_weapons": inherited_resident_weapons,
                  "lineage_catalog": record["lineage_catalog"], "reviewed_lineage_matches": reviewed_matches,
                  "completion_registry_aliases": completion_registry_aliases,
                  "authored_completion_hud_tags": sorted(completion_hud_tags),
                  "additional_original_registry": [],
                  "additional_community_registry": [],
                  "discarded_registry_weapons": discarded_registry_weapons,
                  "removed_registry_references": removed, "other_globals_fields_verified": True,
                  "manifest": str(manifest), "manifest_sha256": legacy.digest(manifest),
                  "source_unchanged": True, "gameplay_validation": "pending", "presentation_validation": "pending"})
    return overlay
