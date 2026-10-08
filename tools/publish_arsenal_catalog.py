#!/usr/bin/env python3
"""Publish the explicit hidden-Fiesta delivery profile; defaults to offline validation.

Uses the existing R2 signer, immutable create/readback/public verification and
catalog-last ETag transaction. Never publishes to the visible community catalog.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__:
    from . import publish_map_catalog as shared
    from .arsenal_catalog import CATALOG_KEY, physical_name, validate_prepared
else:
    import publish_map_catalog as shared
    from arsenal_catalog import CATALOG_KEY, physical_name, validate_prepared

DEFAULT_CONFIG = Path(__file__).with_name("arsenal-publisher.json")


def load_config(path=DEFAULT_CONFIG):
    config = shared.parse_json(shared.read_regular(path, 16384))
    fields = {"schema_version", "account_id", "bucket", "public_base_url", "catalog_key", "allowed_logical_maps"}
    if (not isinstance(config, dict) or set(config) != fields or type(config["schema_version"]) is not int
            or config["schema_version"] != 1 or config["catalog_key"] != CATALOG_KEY):
        raise shared.PublishError("Arsenal publisher config must use the pinned hidden testing endpoint")
    # Hosting uses the already-reviewed map origin/account/bucket. The new
    # profile extends delivery scope, without changing visible-map publication.
    hosting = shared.load_config()
    if any(config[key] != hosting[key] for key in ("account_id", "bucket", "public_base_url")):
        raise shared.PublishError("Arsenal hosting must match the reviewed community-map origin/account/bucket")
    allowed = config["allowed_logical_maps"]
    if not isinstance(allowed, list) or not 1 <= len(allowed) <= 115:
        raise shared.PublishError("Arsenal logical-map allowlist is invalid")
    for name in allowed:
        physical_name(name)
    if len(set(allowed)) != len(allowed):
        raise shared.PublishError("Arsenal logical-map allowlist is duplicate")
    return config


def publish(prepared, config, r2, http, *, progress=print, objects_only=False,
            expected_catalog_sha256=None):
    # Exact object keys/hashes and flat-manifest correspondence were checked by
    # this profile's validator. The shared engine rechecks bytes before upload.
    objects = shared.Prepared(prepared.directory, prepared.catalog, prepared.objects)
    shared.publish(objects, config, r2, http, progress=progress,
                   objects_only=objects_only, expected_catalog_sha256=expected_catalog_sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True, help="Directory produced by arsenal_catalog.py")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--credential-file", type=Path, help="Existing 1Password-mounted literal token assignment file")
    parser.add_argument("--publish", action="store_true", help="Publish verified immutable objects then arsenals-v1.json")
    parser.add_argument("--objects-only", action="store_true", help="With --publish, stage immutable objects without advancing the hidden catalog")
    parser.add_argument("--expect-catalog-sha256", help="Require the current R2 catalog to match the preparation snapshot before uploading")
    args = parser.parse_args()
    if args.objects_only and not args.publish:
        parser.error("--objects-only requires --publish")
    try:
        config = load_config(args.config)
        prepared = validate_prepared(args.prepared, config["allowed_logical_maps"])
        print(f"Validated {len(prepared.arsenals)} hidden arsenals; {prepared.upload_bytes} bytes including catalog")
        if not args.publish:
            print("Offline validation only; no credentials read or network requests made.")
            return
        token = shared.load_token(args.credential_file)
        http = shared.HTTPS()
        access, secret = shared.derive_s3_credentials(token, config, http)
        del token
        publish(prepared, config, shared.R2(config, access, secret, http), http,
                objects_only=args.objects_only, expected_catalog_sha256=args.expect_catalog_sha256)
    except (shared.PublishError, OSError, ValueError, UnicodeError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, shared.PublishError) else "Local arsenal publication inputs could not be validated"
        parser.exit(1, "Arsenal publication failed: " + message + "\n")


if __name__ == "__main__":
    main()
