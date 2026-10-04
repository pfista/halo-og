#!/usr/bin/env python3
"""Publish audited packages, then retire backed-up complete community maps.

The default only validates local files. Remote changes require --publish;
--retire-complete-maps additionally removes only reviewed maps/sha256 objects
after package catalog verification and a complete fresh private local backup.
Credentials use the established 1Password-mounted file, never package metadata.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote
import xml.etree.ElementTree as XML

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import community_packages as packages
from tools import package_catalog
from tools import publish_map_catalog as transport
from tools.map_catalog import MAX_CATALOG_BYTES, validate_map

PublishError = transport.PublishError
PRODUCER_PINS = Path(__file__).resolve().parents[1] / "tools/community-toolchain/pins.json"


def _reviewed_producer():
    pins = transport.parse_json(transport.read_regular(PRODUCER_PINS, MAX_CATALOG_BYTES))
    if (not isinstance(pins, dict) or pins.get("invader_commit") != packages.INVADER_COMMIT
            or not isinstance(pins.get("compatible_package_producers"), list)
            or not 1 <= len(pins["compatible_package_producers"]) <= 32):
        raise PublishError("Reviewed package-producer pins are unavailable")
    result = []
    for producer in pins["compatible_package_producers"]:
        if (not isinstance(producer, dict) or set(producer) != {"invader_commit", "tool_sha256"}
                or producer["invader_commit"] != packages.INVADER_COMMIT
                or not isinstance(producer["tool_sha256"], dict) or set(producer["tool_sha256"]) != {"extract", "build"}
                or any(not isinstance(value, str) or not packages.SHA.fullmatch(value) for value in producer["tool_sha256"].values())):
            raise PublishError("Reviewed package-producer identity is invalid")
        result.append(producer["tool_sha256"])
    return result


def validate_prepared(directory, audit_path, original_stock_tags, config):
    try:
        data, catalog = package_catalog.validate_public_tree(directory, set(config["allowed_map_ids"]))
        audit = transport.parse_json(transport.read_regular(audit_path, MAX_CATALOG_BYTES))
        if (not isinstance(audit, dict) or audit.get("scope") != "whole-byte-identical-original-tags-only"
                or audit.get("modified_originals_retained") is not True
                or audit.get("catalog_sha256") != hashlib.sha256(data).hexdigest()
                or not isinstance(audit.get("maps"), list) or len(audit["maps"]) != len(catalog["maps"])):
            raise PublishError("A matching private whole-asset audit receipt is required")
        receipts = {item["id"]: item for item in audit["maps"]}
        if len(receipts) != len(audit["maps"]):
            raise PublishError("Private audit contains duplicate map identities")
        producer = _reviewed_producer()
        originals = packages._tree(original_stock_tags)
        original_hashes = {(entry["size"], entry["sha256"]) for entry in originals.values()}
        for entry in catalog["maps"]:
            receipt = receipts.get(entry["id"], {})
            if (type(receipt.get("unchanged_original_literals")) is not int
                    or receipt["unchanged_original_literals"] != 0 or receipt.get("exact_rebuilt_map_sha256") != entry["sha256"]):
                raise PublishError("Private audit does not attest every exact rebuilt map")
            manifest = packages.read_package(Path(directory) / entry["object_key"])
            if manifest["tool_sha256"] not in producer:
                raise PublishError("Package producer differs from the reviewed source-tool hash pins")
            packages._verify_originals(manifest, originals)
            if any(item["kind"] == "literal" and (item["size"], item["sha256"]) in original_hashes for item in manifest["files"]):
                raise PublishError("A complete unchanged original asset remains in package payload")
        return transport.Prepared(Path(directory), data, tuple(catalog["maps"]))
    except PublishError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise PublishError("Prepared package tree or private audit could not be validated") from None


class PackageR2(transport.R2):
    def list_keys(self, prefix=""):
        token, seen_tokens, keys = None, set(), []
        for page in range(100):
            query = {"list-type": "2", "max-keys": "1000", "prefix": prefix}
            if token: query["continuation-token"] = token
            canonical = "&".join(quote(key, safe="-_.~") + "=" + quote(value, safe="-_.~") for key, value in sorted(query.items()))
            url = f"https://{self.config['account_id']}.r2.cloudflarestorage.com/{self.config['bucket']}?{canonical}"
            headers = transport.sign_s3("GET", url, None, {"Accept-Encoding": "identity"},
                self.access_key, self.secret_key, query_parameters=query)
            response = self.http.request("GET", url, headers=headers, limit=MAX_CATALOG_BYTES)
            if response.status != 200 or b"<!DOCTYPE" in response.body.upper() or b"<!ENTITY" in response.body.upper():
                raise PublishError("R2 object inventory could not be read safely")
            try:
                root = XML.fromstring(response.body)
                if root.tag.rsplit("}", 1)[-1] != "ListBucketResult": raise ValueError()
                def texts(name):
                    return [node.text for node in root.iter() if node.tag.rsplit("}", 1)[-1] == name]
                page_keys = texts("Key")
                if len(page_keys) > 1000 or any(not isinstance(key, str) or len(key.encode()) > 1024 or not key.startswith(prefix) for key in page_keys):
                    raise ValueError()
                keys.extend(page_keys)
                if len(keys) > 10000 or len(set(keys)) != len(keys): raise ValueError()
                truncated = texts("IsTruncated")
                if truncated == ["false"]: return keys
                tokens = texts("NextContinuationToken")
                if truncated != ["true"] or len(tokens) != 1 or not tokens[0] or tokens[0] in seen_tokens: raise ValueError()
                token = tokens[0]; seen_tokens.add(token)
            except (XML.ParseError, ValueError):
                raise PublishError("R2 returned an invalid or excessive object inventory") from None
        raise PublishError("R2 object inventory exceeds the page limit")


def _private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data); file.flush(); os.fsync(file.fileno())


def _real_directory_chain(path):
    """Do not follow a local backup link/junction into unrelated user data."""
    path = Path(os.path.abspath(path))
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not parent.is_dir() or parent.is_symlink() or packages._reparse(info):
            raise PublishError("Retirement backup must have real directory ancestors")
    return path


def _retirement_inventory(inventory, config):
    if not isinstance(inventory, list) or len(inventory) > 10000:
        raise PublishError("Invalid retirement inventory")
    seen = set()
    for item in inventory:
        if not isinstance(item, dict) or set(item) != {"object_key", "sha256", "file_bytes"}:
            raise PublishError("Invalid retirement inventory entry")
        key, digest, size = item["object_key"], item["sha256"], item["file_bytes"]
        match = re.fullmatch(r"maps/sha256/([0-9a-f]{64})/([a-z0-9][a-z0-9_-]{0,30})\.map", key) if isinstance(key, str) else None
        if (not match or match[2] not in config["allowed_map_ids"] or digest != match[1] or key in seen
                or type(size) is not int or not 2048 <= size <= packages.MAX_CACHE_BYTES):
            raise PublishError("Retirement is limited to unique reviewed immutable complete-map objects")
        seen.add(key)
    return inventory


def _backup_bytes(backup, item):
    path = Path(backup) / item["object_key"]
    _real_directory_chain(path.parent)
    data = transport.read_regular(path, item["file_bytes"])
    if len(data) != item["file_bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise PublishError("Private retirement backup changed; remaining objects were preserved")
    header = validate_map(path)
    if header["name"].casefold() != path.stem:
        raise PublishError("Private retirement backup map identity differs")
    return data


def backup_complete_maps(config, r2, backup, *, progress=print):
    backup = Path(os.path.abspath(backup))
    if os.path.lexists(backup): raise PublishError("Retirement backup must be a new private directory")
    # Existing ancestors are checked before creating this new owned subtree.
    ancestor = backup.parent
    while not os.path.lexists(ancestor): ancestor = ancestor.parent
    _real_directory_chain(ancestor)
    keys = r2.list_keys()
    selected = []
    for key in keys:
        if not key.lower().endswith((".map", ".iso", ".xiso")): continue
        match = re.fullmatch(r"maps/sha256/([0-9a-f]{64})/([a-z0-9][a-z0-9_-]{0,30})\.map", key)
        if not match or match[2] not in config["allowed_map_ids"]:
            raise PublishError("An unreviewed complete-map or disc-image object remains; automatic retirement is limited to the reviewed collection")
        selected.append((key, match[1], match[2]))
    backup.mkdir(parents=True, mode=0o700)
    old = r2.request("GET", config["catalog_key"], limit=MAX_CATALOG_BYTES)
    if old.status not in (200, 404): raise PublishError("Current catalog could not be backed up")
    if old.status == 200: _private_write(backup / "previous-catalog.json", old.body)
    inventory = []
    for key, digest, identity in sorted(selected):
        response = r2.request("GET", key, limit=packages.MAX_CACHE_BYTES)
        if response.status != 200 or hashlib.sha256(response.body).hexdigest() != digest:
            raise PublishError("A complete-map object differs from its immutable identity; nothing has been removed")
        destination = backup / key
        _private_write(destination, response.body)
        header = validate_map(destination)
        if header["name"].casefold() != identity:
            raise PublishError("A retirement object is not its declared community map; nothing has been removed")
        inventory.append({"object_key": key, "sha256": digest, "file_bytes": len(response.body)})
        progress("Backed up complete map " + identity)
    _private_write(backup / "inventory.json", (json.dumps(inventory, indent=2) + "\n").encode())
    return inventory


def retire_complete_maps(prepared, config, r2, http, backup, inventory, *, progress=print):
    transport.require_exact(r2.request("GET", config["catalog_key"], limit=MAX_CATALOG_BYTES), prepared.catalog, "Package catalog before retirement", catalog_pending=False)
    transport.require_exact(http.request("GET", config["public_base_url"] + config["catalog_key"], headers={"Cache-Control": "no-cache"}, limit=MAX_CATALOG_BYTES), prepared.catalog, "Public package catalog before retirement", catalog_pending=False)
    backup = _real_directory_chain(backup)
    _retirement_inventory(inventory, config)
    saved = transport.parse_json(transport.read_regular(backup / "inventory.json", MAX_CATALOG_BYTES))
    if saved != inventory:
        raise PublishError("Private retirement inventory changed; complete maps were preserved")
    # Validate every backup before the first destructive operation. Recheck
    # each immediately before DELETE too; an interruption can leave a truthful
    # partial-retirement result, never a missing or unauthenticated local copy.
    for item in inventory: _backup_bytes(backup, item)
    for item in inventory:
        key = item["object_key"]
        data = _backup_bytes(backup, item)
        current = r2.request("GET", key, limit=item["file_bytes"])
        if current.status == 200:
            transport.require_exact(current, data, "Complete map before retirement", catalog_pending=False)
            # R2 does not document conditional DeleteObject. These reviewed
            # content-addressed objects are create-only; this GET is a current
            # hash gate, not an atomic conditional-delete guarantee.
            deleted = r2.request("DELETE", key)
            if deleted.status not in (200, 204): raise PublishError("Complete-map retirement failed; inspect the saved inventory")
        elif current.status != 404: raise PublishError("Complete-map retirement readback failed")
        if r2.request("GET", key, limit=item["file_bytes"]).status != 404:
            raise PublishError("R2 still serves a retired complete map")
        progress("Removed complete-map object " + key.rsplit("/", 1)[-1])
    remaining = r2.list_keys()
    if any(key.lower().endswith((".map", ".iso", ".xiso")) for key in remaining):
        raise PublishError("Complete-map or disc-image objects still remain in the bucket")
    cached = []
    for item in inventory:
        response = http.request("GET", config["public_base_url"] + item["object_key"],
            headers={"Cache-Control": "no-cache", "Accept-Encoding": "identity"}, limit=item["file_bytes"])
        if response.status != 404: cached.append(item["object_key"])
    result = {"removed_complete_map_objects": len(inventory), "remaining_complete_map_objects": 0,
        "public_urls_still_served": cached, "public_catalog_sha256": hashlib.sha256(prepared.catalog).hexdigest()}
    _private_write(Path(backup) / "retirement-result.json", (json.dumps(result, indent=2) + "\n").encode())
    if cached: raise PublishError("R2 complete maps were removed but old public URLs still respond; a Cloudflare cache purge is required before claiming retirement complete")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--original-stock-tags", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=transport.DEFAULT_CONFIG)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--objects-only", action="store_true",
                        help="With --publish, upload/verify immutable packages without reading or advancing the live catalog")
    parser.add_argument("--retire-complete-maps", action="store_true")
    parser.add_argument("--retirement-backup", type=Path)
    args = parser.parse_args()
    if args.objects_only and (not args.publish or args.retire_complete_maps or args.retirement_backup):
        parser.error("--objects-only requires --publish and cannot be combined with retirement or a retirement backup")
    if args.retire_complete_maps and (not args.publish or not args.retirement_backup):
        parser.error("Retirement requires --publish and a fresh --retirement-backup")
    try:
        config = transport.load_config(args.config)
        prepared = validate_prepared(args.prepared, args.audit, args.original_stock_tags, config)
        print(f"Validated {len(prepared.maps)} package-only objects; custom content and modified originals retained.")
        if not args.publish:
            print("Local validation only; no credentials read or network requests made."); return
        http = transport.HTTPS()
        token = transport.load_token(args.credential_file)
        access, secret = transport.derive_s3_credentials(token, config, http)
        del token
        r2 = PackageR2(config, access, secret, http)
        inventory = backup_complete_maps(config, r2, args.retirement_backup) if args.retire_complete_maps else None
        transport.publish(prepared, config, r2, http, package_delivery=True, advance_catalog=not args.objects_only)
        if args.objects_only:
            print("Immutable package objects verified publicly; live catalog was not read or advanced, and no complete maps were retired.")
            return
        if inventory is not None:
            result = retire_complete_maps(prepared, config, r2, http, args.retirement_backup, inventory)
            print(f"Retired {result['removed_complete_map_objects']} complete maps; old public URLs return404.")
    except (PublishError, OSError, ValueError):
        error = sys.exc_info()[1]
        parser.exit(1, "Package publication failed: " + (str(error) if isinstance(error, PublishError) else "Local input could not be read or validated") + "\n")


if __name__ == "__main__": main()
