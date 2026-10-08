#!/usr/bin/env python3
"""Draft unverified asset reviews from immutable extracted Halo tag files.

This inventories contents; it never infers Bungie ancestry or approves a weapon.
Use the source-tags directory retained by convert_maps.py after a failed import.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.map_pipeline.backend import ApprovedInvader, ConversionError, _tree
from tools.map_pipeline.stock_hud import IDENTITY_FIELDS
from tools.map_pipeline.stock_weapons import _dependencies, _identity
from tools.map_pipeline.weapon_lineage import MAX_CATALOG_BYTES, tag_path, validate_catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_tags", type=Path)
    parser.add_argument("--invader-bin", type=Path, required=True)
    parser.add_argument("--invader-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New catalog draft JSON; existing files are preserved")
    parser.add_argument("--weapon", action="append", default=[], help="Class-qualified weapon path; repeat to select assets")
    args = parser.parse_args(argv)
    source = args.source_tags
    if source.is_symlink() or not source.is_dir():
        parser.error("source_tags must be a regular extracted-tag directory")
    source = source.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink():
        parser.error("output already exists; select a new draft path")
    if source == output.parent or source in output.parents:
        parser.error("review output must stay outside immutable source tags")
    before = _tree(source)
    weapons = sorted(set(args.weapon or [name for name in before if name.endswith(".weapon")]))
    for weapon in weapons:
        tag_path(weapon, ".weapon")
        if weapon not in before:
            parser.error("selected weapon is absent from source tags: " + weapon)
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=output.stem + "-review-", dir=output.parent))
    (workspace / "logs").mkdir()
    tool = ApprovedInvader(args.invader_bin, args.invader_manifest, workspace / "logs")
    tool.stage = "weapon_lineage_review"
    entries, errors = [], []
    for index, weapon in enumerate(weapons, 1):
        try:
            closure = _dependencies(tool, [source], weapon)
            entries.append({
                "asset_id": f"review-weapon-{index:04d}",
                "variant_id": "source-" + before[weapon][:16],
                "weapon": weapon, "weapon_sha256": before[weapon],
                "identity": dict(zip(IDENTITY_FIELDS, _identity(tool, source, weapon))),
                "closure_sha256": {name: before[name] for name in sorted(closure)},
                "outcome": "unverified", "ancestor": None, "evidence": [],
                "reason": "Pending original Halo 1 ancestry and completion review; inventory hashes establish content identity only.",
            })
        except ConversionError as error:
            errors.append({"weapon": weapon, "code": error.code, "stage": error.stage,
                           "message": str(error), "details": error.details})
    if _tree(source) != before:
        raise ValueError("Source tags changed during review; no draft was published")
    catalog = validate_catalog({"schema_version": 1, "id": "weapon-lineage-review",
                                "version": "0.1.0", "entries": entries})
    payload = json.dumps(catalog, indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > MAX_CATALOG_BYTES:
        raise ValueError("Draft exceeds catalog bounds; select a smaller weapon group")
    with output.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    report = workspace / "review.json"
    report.write_text(json.dumps({"schema_version": 1, "source_tags": str(source), "draft": str(output),
                                  "weapons_selected": len(weapons), "unverified_variants": len(entries),
                                  "errors": errors, "source_unchanged": True,
                                  "commands": tool.commands, "tools": tool.provenance}, indent=2) + "\n")
    print(json.dumps({"draft": str(output), "review": str(report), "unverified_variants": len(entries),
                      "errors": len(errors), "source_unchanged": True}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
