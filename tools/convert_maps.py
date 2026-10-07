#!/usr/bin/env python3
"""Inventory or convert a source map directory into checksum-bound Xbox v5 packages."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.map_pipeline.pipeline import convert_directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("maps", type=Path, help="Source directory; matching resource maps can live alongside caches")
    parser.add_argument("--output", required=True, type=Path, help="Fresh output directory outside the source tree")
    parser.add_argument("--profile", default="authored-xbox-v5", help="Built-in profile ID or reviewed JSON profile")
    parser.add_argument("--inspect", action="store_true", help="Only identify formats and write builder inventory reports")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--invader-bin", type=Path)
    parser.add_argument("--invader-manifest", type=Path)
    parser.add_argument("--asset-manifest", type=Path, help="Source-bound sound/bitmap helper build manifest")
    parser.add_argument("--stock-maps", type=Path, help="Original Xbox NTSC 2276 fallback input")
    parser.add_argument("--source-tags", type=Path, help="Authored tag package for reviewed collection recipes")
    parser.add_argument("--resources", type=Path, help="Matching resource directory; defaults to each source cache's directory")
    parser.add_argument("--metadata-dir", type=Path, help="Reviewed <output-id>.json metadata and relative preview files")
    args = parser.parse_args(argv)
    try:
        result = convert_directory(args.maps, args.output, profile_selection=args.profile, recursive=args.recursive,
                                   invader_bin=args.invader_bin, invader_manifest=args.invader_manifest,
                                   stock_maps=args.stock_maps, source_tags=args.source_tags, resources=args.resources,
                                   metadata_dir=args.metadata_dir, asset_manifest=args.asset_manifest, inspect_only=args.inspect)
    except (OSError, ValueError) as error:
        parser.exit(2, "Map batch could not start: " + str(error) + "\n")
    print("Map batch: " + ", ".join(f"{count} {status}" for status, count in result["counts"].items()))
    print("Reports: " + str(args.output.resolve() / "reports"))
    return 1 if any(result["counts"].get(status, 0) for status in ("failed", "unsupported", "needs_profile")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
