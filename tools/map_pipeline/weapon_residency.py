"""Keep admitted assets resident without adding roles to the retail registry."""
from __future__ import annotations

from pathlib import Path
import shutil

from .backend import ConversionError, _tree, legacy
from .stock_weapons import _dependencies, _name, _winner

COLLECTION = "__native_policy/admitted_weapon_assets_v1.tag_collection"
SOUL = "ui/shell/multiplayer.ui_widget_collection"
MAX_REFERENCES = 200


def _fail(message, code="needs_profile", **details):
    raise ConversionError(code, "weapon_residency", message, details)


def _references(tool, root, tag):
    count = tool.count(root, tag, "tags")
    if type(count) is not int or not 0 <= count <= MAX_REFERENCES:
        _fail("Weapon residency collection exceeds its native 200-reference bound", tag=tag)
    return [_name(tool.get(root, tag, f"tags[{index}].reference").strip()) for index in range(count)]


def attach_weapon_residency(tool, roots, weapons, overlay, protected):
    """Attach one checked dependency root to Soul; mutate only the owned overlay.

    The caller supplies already admitted weapon roots. This function supplies
    residency, not ancestry approval or a new runtime weapon-set policy.
    """
    overlay = Path(overlay)
    roots = [Path(root) for root in roots]
    if not isinstance(weapons, (list, tuple)) or len(weapons) > MAX_REFERENCES:
        _fail("Admitted weapon residency exceeds its native 200-reference bound")
    if not weapons:
        return None
    weapons = list(dict.fromkeys(_name(name, {"weapon"}) for name in weapons))
    if overlay.is_symlink() or not overlay.is_dir():
        _fail("Weapon residency requires an owned regular output overlay", "invalid_output")
    collection = overlay / COLLECTION
    if collection.exists() or collection.is_symlink():
        _fail("Weapon residency output collides with an existing collection", "invalid_output", tag=COLLECTION)
    snapshots = {root: _tree(root) for root in dict.fromkeys(roots) if root != overlay}
    owned_before = _tree(overlay)
    for root, inventory in snapshots.items():
        for name, checksum in inventory.items():
            path = root / name
            if path in protected and protected[path] != checksum:
                _fail("Protected input changed before weapon residency", "input_changed", tag=name)
            protected[path] = checksum

    def unchanged():
        if any(_tree(root) != inventory for root, inventory in snapshots.items()):
            _fail("Weapon residency changed an immutable input tree", "input_changed")
        after = _tree(overlay)
        if any(after.get(name) != checksum for name, checksum in owned_before.items()
               if name not in {SOUL, COLLECTION}):
            _fail("Weapon residency changed an unrelated owned output", "input_changed")

    stage = getattr(tool, "stage", "canonical_weapons")
    tool.stage = "weapon_residency"
    try:
        previous = _winner(roots, COLLECTION, {"tag_collection"})
        if previous and _references(tool, previous[0], COLLECTION) != weapons:
            _fail("Existing reserved weapon collection has stale or unapproved asset scope; review before reimport", tag=COLLECTION)
        soul = _winner(roots, SOUL, {"ui_widget_collection"})
        if not soul:
            _fail("Weapon residency requires Xbox's implicit multiplayer Soul root", tag=SOUL)
        original_refs = _references(tool, soul[0], SOUL)
        if original_refs.count(COLLECTION) > 1:
            _fail("Xbox Soul has duplicate reserved weapon collection references", tag=SOUL)
        if COLLECTION in original_refs and previous is None:
            _fail("Xbox Soul references a missing reserved weapon collection", tag=COLLECTION)
        append = COLLECTION not in original_refs
        if append and len(original_refs) == MAX_REFERENCES:
            _fail("Xbox Soul cannot safely attach another residency reference", tag=SOUL)
        old_soul_closure = _dependencies(tool, roots, SOUL)
        weapon_closure = set()
        for name in weapons:
            if _winner(roots, name, {"weapon"}) is None:
                _fail("An admitted weapon residency root is missing", tag=name)
            weapon_closure.update(_dependencies(tool, roots, name))
        if {SOUL, COLLECTION} & weapon_closure:
            _fail("Admitted weapon dependencies would cycle through their residency root")
        inputs = {name: legacy.digest(_winner(roots, name)[1])
                  for name in sorted(weapon_closure | {SOUL})}
        previous_hash = legacy.digest(previous[1]) if previous else None
        # Approved invader-edit creates a valid native tag/header/checksum;
        # no new binary layout is hand-authored or safeguard disabled.
        collection.parent.mkdir(parents=True, exist_ok=True)
        args = ["-t", overlay, "-N", "-I", "tags", len(weapons), "0"]
        for index, name in enumerate(weapons):
            args += ["-S", f"tags[{index}].reference", name]
        tool.run("edit", *args, COLLECTION)
        if _references(tool, overlay, COLLECTION) != weapons:
            _fail("Admitted weapon collection failed exact native readback", "invalid_output", tag=COLLECTION)
        target = overlay / SOUL
        target.parent.mkdir(parents=True, exist_ok=True)
        if target != soul[1]:
            shutil.copyfile(soul[1], target)
            if legacy.digest(target) != inputs[SOUL]:
                _fail("Xbox Soul copy changed its native source payload", "invalid_output", tag=SOUL)
        if append:
            tool.run("edit", "-t", overlay, "-I", "tags", 1, "end", "-S",
                     f"tags[{len(original_refs)}].reference", COLLECTION, SOUL)
        expected_refs = [*original_refs, *([COLLECTION] if append else [])]
        if _references(tool, overlay, SOUL) != expected_refs:
            _fail("Weapon residency changed an existing Xbox Soul reference", "invalid_output", tag=SOUL)
        effective = [overlay, *(root for root in roots if root != overlay)]
        resident = _dependencies(tool, effective, COLLECTION)
        if resident != weapon_closure | {COLLECTION}:
            _fail("Admitted weapon residency has an unexpected dependency closure", "invalid_output", tag=COLLECTION)
        soul_resident = _dependencies(tool, effective, SOUL)
        if soul_resident != old_soul_closure | weapon_closure | {COLLECTION}:
            _fail("Xbox Soul dependency closure changed outside admitted weapon residency", "invalid_output", tag=SOUL)
        unchanged()
        output = {name: legacy.digest(overlay / name) for name in (COLLECTION, SOUL)}
        protected.update({overlay / name: checksum for name, checksum in output.items()})
        return {"kind": "admitted_weapon_residency", "operation": "admitted_weapon_residency",
                "tag": COLLECTION, "weapon_references": weapons, "dependency_tags": sorted(resident),
                "input_sha256": inputs, "output_sha256": output,
                "sha256_before": previous_hash, "sha256_after": output[COLLECTION],
                "soul_references_before": original_refs, "soul_references_after": expected_refs,
                "inserted_soul_references": [COLLECTION] if append else [],
                "native_reparse_verified": True, "dependency_residency_verified": True,
                "existing_references_preserved": True, "source_unchanged": True,
                "reason": "Keep admitted assets resident through Xbox Soul without expanding retail Globals weapon roles",
                "gameplay_validation": "pending"}
    finally:
        tool.stage = stage
        unchanged()
