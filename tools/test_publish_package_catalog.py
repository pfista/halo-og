"""Offline package cutover/retirement gates; every remote request is mocked."""
import copy
import contextlib
import hashlib
import json
import os
import io
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from tools import community_packages as packages
from tools import package_catalog
from tools import mapog
from tools import publish_map_catalog as transport
from tools import publish_package_catalog as publisher
from tools import test_community_packages as fixtures
from tools.test_publish_map_catalog import FakeHTTPS


class PackageHTTPS(FakeHTTPS):
    def __init__(self, config):
        super().__init__(config)
        self.listing_responses = []

    def request(self, method, url, *, headers=None, body=None, limit=16384):
        parsed = urlsplit(url)
        private = parsed.hostname.endswith(".r2.cloudflarestorage.com")
        normalized = {k.lower(): v for k, v in (headers or {}).items()}
        if private and (parsed.query or method == "DELETE"):
            self.requests.append((method, url, normalized, body))
            if not normalized.get("authorization", "").startswith("AWS4-HMAC-SHA256 "):
                raise AssertionError("unsigned private operation")
            if parsed.query:
                if self.listing_responses: return self.listing_responses.pop(0)
                encoded = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>' +
                           ''.join('<Contents><Key>' + escape(key) + '</Key></Contents>' for key in sorted(self.objects)) + '</ListBucketResult>').encode()
                return transport.Response(200, {}, encoded)
            key = parsed.path.split("/", 2)[2]
            self.objects.pop(key, None)
            return transport.Response(204, {}, b"")
        return super().request(method, url, headers=headers, body=body, limit=limit)


class PackagePublisherTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CommunityPackageTests("test_whole_unchanged_assets_only_and_exact_materialization")
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        pins = json.loads(publisher.PRODUCER_PINS.read_text())["compatible_package_producers"][0]["tool_sha256"]
        f.toolchain.write_text(json.dumps({"invader_commit": packages.INVADER_COMMIT,
            "binaries": {key: {"sha256": value} for key, value in pins.items()}}))
        self.manifest = f.prepare()
        self.directory = f.root / "public-packages"
        self.catalog, self.audit = package_catalog.prepare_package_catalog([f.package], [f.expected], f.original, self.directory, ["downrush"])
        self.audit_path = f.root / "private-audit.json"; self.audit_path.write_text(json.dumps(self.audit))
        self.config = transport.load_config()
        self.prepared = self.validate()
        self.entry = self.prepared.maps[0]; self.key = self.entry["object_key"]
        self.package_bytes = (self.directory / self.key).read_bytes()
        self.raw_package_bytes = f.package.read_bytes()
        self.map_bytes = f.expected.read_bytes()
        self.http = PackageHTTPS(self.config)
        self.r2 = publisher.PackageR2(self.config, "b" * 32, "c" * 64, self.http)
        self.backup = f.root / "private-backup"
        self.old_keys = []
        for tail in (b"original version", b"another reviewed version"):
            raw = bytearray(self.map_bytes); raw[-len(tail):] = tail; data = bytes(raw)
            digest = hashlib.sha256(data).hexdigest(); key = f"maps/sha256/{digest}/downrush.map"
            self.old_keys.append(key); self.http.objects[key] = data
        self.old_catalog = b'{"schema_version":1,"profile":"stock-xbox-ntsc","maps":[]}\n'
        self.http.objects[self.config["catalog_key"]] = self.old_catalog

    def validate(self):
        return publisher.validate_prepared(self.directory, self.audit_path, self.fixture.original, self.config)

    def backup_all(self):
        return publisher.backup_complete_maps(self.config, self.r2, self.backup, progress=lambda _: None)

    def publish(self):
        transport.publish(self.prepared, self.config, self.r2, self.http, package_delivery=True, progress=lambda _: None)

    def retire(self, inventory):
        return publisher.retire_complete_maps(self.prepared, self.config, self.r2, self.http, self.backup, inventory, progress=lambda _: None)

    def deletes(self):
        return [r for r in self.http.requests if r[0] == "DELETE"]

    def rewrite_package(self, manifest, payload=None):
        _, length = packages.HEADER.unpack_from(self.raw_package_bytes)
        payload = self.raw_package_bytes[16 + length:] if payload is None else payload
        encoded = json.dumps(manifest).encode()
        data = packages.HEADER.pack(packages.MAGIC, len(encoded)) + encoded + payload
        raw = self.fixture.root / "forged-raw.hogpkg"; raw.write_bytes(data)
        compressed = self.fixture.root / "forged.mapog"; compressed.unlink(missing_ok=True)
        mapog.compress_package(raw, compressed); data = compressed.read_bytes()
        digest = hashlib.sha256(data).hexdigest(); key = f"packages/sha256/{digest}/downrush.mapog"
        shutil.rmtree(self.directory)
        path = self.directory / key; path.parent.mkdir(parents=True); path.write_bytes(data)
        catalog = copy.deepcopy(self.catalog); catalog["maps"][0].update(object_key=key, package_sha256=digest, package_bytes=len(data))
        catalog_bytes = json.dumps(catalog).encode(); (self.directory / "catalog.json").write_bytes(catalog_bytes)
        audit = copy.deepcopy(self.audit); audit["catalog_sha256"] = hashlib.sha256(catalog_bytes).hexdigest()
        self.audit_path.write_text(json.dumps(audit))

    def test_private_audit_requires_exact_catalog_map_set_and_strict_scope(self):
        for field, value in (("scope", "chunk-delta"), ("modified_originals_retained", False), ("catalog_sha256", "0" * 64),
                             ("maps", []), ("maps", self.audit["maps"] * 2)):
            changed = copy.deepcopy(self.audit); changed[field] = value; self.audit_path.write_text(json.dumps(changed))
            with self.assertRaises(transport.PublishError): self.validate()
        for field, value in (("unchanged_original_literals", False), ("unchanged_original_literals", 1), ("exact_rebuilt_map_sha256", "0" * 64)):
            changed = copy.deepcopy(self.audit); changed["maps"][0][field] = value; self.audit_path.write_text(json.dumps(changed))
            with self.assertRaises(transport.PublishError): self.validate()
        self.assertEqual(self.deletes(), [])

    def test_unknown_producer_and_complete_unchanged_original_literal_refused(self):
        changed = copy.deepcopy(self.manifest); changed["tool_sha256"]["build"] = "0" * 64
        self.rewrite_package(changed)
        with self.assertRaisesRegex(transport.PublishError, "producer"): self.validate()
        changed = copy.deepcopy(self.manifest)
        original = self.fixture.original_bytes[self.fixture.unchanged]
        changed["files"].append({"tree": "tags", "path": "custom/copied-original.bitmap", "kind": "literal", "classification": "unknown-or-community",
            "size": len(original), "sha256": hashlib.sha256(original).hexdigest(), "offset": changed["payload_bytes"]})
        changed["payload_bytes"] += len(original)
        _, length = packages.HEADER.unpack_from(self.raw_package_bytes)
        self.rewrite_package(changed, self.raw_package_bytes[16 + length:] + original)
        with self.assertRaisesRegex(transport.PublishError, "unchanged original"): self.validate()

    def test_producer_allowlist_is_independent_of_native_consumer_binary_pins(self):
        pins = json.loads(publisher.PRODUCER_PINS.read_text())
        # Native consumer binaries may be rebuilt for another platform/minimum
        # OS while the approved source producer of all forty packages stays.
        pins["binaries"] = {"extract": "1" * 64, "build": "2" * 64}
        path = self.fixture.root / "reviewed-producer-pins.json"; path.write_text(json.dumps(pins))
        with patch.object(publisher, "PRODUCER_PINS", path):
            self.assertEqual(self.validate().maps[0]["package_sha256"], self.entry["package_sha256"])
            for changes in ({"compatible_package_producers": []},
                            {"compatible_package_producers": [{"invader_commit": packages.INVADER_COMMIT,
                                                               "tool_sha256": {"extract": "1" * 64, "build": "2" * 64}}]},
                            {"invader_commit": "0" * 40}):
                changed = copy.deepcopy(pins); changed.update(changes); path.write_text(json.dumps(changed))
                with self.assertRaises(transport.PublishError): self.validate()

    def test_package_upload_authenticates_package_bytes_not_logical_map(self):
        self.assertNotEqual(self.entry["package_sha256"], self.entry["sha256"])
        self.publish()
        puts = [r for r in self.http.requests if r[0] == "PUT"]
        self.assertEqual(puts[0][3], self.package_bytes)
        self.assertEqual(puts[0][2]["x-amz-content-sha256"], self.entry["package_sha256"])
        self.assertEqual(puts[0][2]["if-none-match"], "*")
        public = next(i for i, r in enumerate(self.http.requests) if r[1] == self.config["public_base_url"] + self.key)
        self.assertLess(public, self.http.requests.index(puts[-1]))
        self.assertEqual(self.http.objects[self.config["catalog_key"]], self.prepared.catalog)
        self.assertEqual(self.deletes(), [])

    def test_explicit_objects_only_cli_does_not_touch_live_catalog_or_retire_maps(self):
        arguments = ["publish_package_catalog.py", "--prepared", str(self.directory), "--audit", str(self.audit_path),
                     "--original-stock-tags", str(self.fixture.original), "--publish", "--objects-only"]
        output = io.StringIO()
        with patch.object(publisher.sys, "argv", arguments), patch.object(transport, "HTTPS", return_value=self.http), \
                patch.object(transport, "load_token", return_value="synthetic-memory-only"), \
                patch.object(transport, "derive_s3_credentials", return_value=("b" * 32, "c" * 64)), \
                contextlib.redirect_stdout(output):
            publisher.main()
        self.assertEqual(self.http.objects[self.config["catalog_key"]], self.old_catalog)
        self.assertEqual(self.http.objects[self.key], self.package_bytes)
        self.assertEqual(self.deletes(), [])
        self.assertFalse(self.backup.exists())
        self.assertFalse(any(self.config["catalog_key"] in request[1] for request in self.http.requests))
        self.assertIn("catalog was not read or advanced", output.getvalue())

    def test_objects_only_requires_publish_and_rejects_retirement_before_credentials(self):
        base = ["publish_package_catalog.py", "--prepared", str(self.directory), "--audit", str(self.audit_path),
                "--original-stock-tags", str(self.fixture.original), "--objects-only"]
        for extra in ([], ["--publish", "--retire-complete-maps"], ["--publish", "--retirement-backup", str(self.backup)]):
            with self.subTest(extra=extra), patch.object(publisher.sys, "argv", base + extra), \
                    patch.object(transport, "load_token") as credentials, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error: publisher.main()
                self.assertEqual(error.exception.code, 2)
                credentials.assert_not_called()
        self.assertEqual(self.http.requests, [])

    def test_every_object_is_backed_up_before_any_delete_and_retirement_is_exact(self):
        inventory = self.backup_all()
        self.assertEqual(len(inventory), 2); self.assertEqual(self.deletes(), [])
        self.assertEqual((self.backup / "previous-catalog.json").read_bytes(), self.old_catalog)
        for item in inventory: self.assertEqual((self.backup / item["object_key"]).read_bytes(), self.http.objects[item["object_key"]])
        if os.name != "nt":
            self.assertEqual(self.backup.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.backup / "inventory.json").stat().st_mode & 0o777, 0o600)
        self.publish(); result = self.retire(inventory)
        self.assertEqual(result["removed_complete_map_objects"], 2)
        self.assertEqual(result["public_urls_still_served"], [])
        self.assertEqual(len(self.deletes()), 2)
        self.assertIn(self.key, self.http.objects)
        for key in self.old_keys: self.assertNotIn(key, self.http.objects)
        self.assertTrue((self.backup / "retirement-result.json").exists())

    def test_last_backup_changed_refuses_before_first_delete(self):
        inventory = self.backup_all(); self.publish()
        target = self.backup / inventory[-1]["object_key"]; data = bytearray(target.read_bytes()); data[-1] ^= 1; target.write_bytes(data)
        with self.assertRaisesRegex(transport.PublishError, "backup changed"): self.retire(inventory)
        self.assertEqual(self.deletes(), [])
        for key in self.old_keys: self.assertIn(key, self.http.objects)

    def test_changed_current_catalog_public_catalog_and_current_object_preserved(self):
        inventory = self.backup_all(); self.publish()
        catalog_key = self.config["catalog_key"]
        self.http.objects[catalog_key] = b"racing catalog"
        with self.assertRaises(transport.PublishError): self.retire(inventory)
        self.http.objects[catalog_key] = self.prepared.catalog
        self.http.public_bad[catalog_key] = transport.Response(200, {}, b"cached old catalog")
        with self.assertRaises(transport.PublishError): self.retire(inventory)
        self.http.public_bad.clear()
        key = inventory[0]["object_key"]; self.http.objects[key] = b"changed remote object"
        with self.assertRaises(transport.PublishError): self.retire(inventory)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.http.objects[key], b"changed remote object")

    def test_unreviewed_map_disc_and_stock_objects_prevent_backup_or_deletion(self):
        for key in ("maps/sha256/" + "0" * 64 + "/bloodgulch.map", "original/game.iso", "original/game.xiso", "elsewhere/downrush.map"):
            self.http.objects[key] = b"unreviewed"
            with self.assertRaisesRegex(transport.PublishError, "unreviewed"): self.backup_all()
            self.assertFalse(self.backup.exists()); self.assertEqual(self.deletes(), [])
            del self.http.objects[key]

    def test_inventory_injection_duplicates_and_changed_record_never_delete(self):
        inventory = self.backup_all(); self.publish()
        forged = []
        for key in ("../outside", "original/game.iso", "maps/sha256/" + "0" * 64 + "/bloodgulch.map"):
            item = dict(inventory[0], object_key=key); forged.append([item])
        forged += [inventory * 2, [dict(inventory[0], file_bytes=True)], [dict(inventory[0], sha256="0" * 64)]]
        for value in forged:
            (self.backup / "inventory.json").write_text(json.dumps(value))
            with self.assertRaises(transport.PublishError): self.retire(value)
            self.assertEqual(self.deletes(), [])
        (self.backup / "inventory.json").write_text("[]")
        with self.assertRaisesRegex(transport.PublishError, "inventory changed"): self.retire(inventory)
        self.assertEqual(self.deletes(), [])

    def test_backup_symlink_ancestor_refused_without_external_writes(self):
        if os.name == "nt": self.skipTest("Windows runner symlink privileges vary; reparse checks are explicit")
        inventory = self.backup_all(); self.publish()
        original = self.backup / "maps"; external = self.fixture.root / "external-backup"
        original.rename(external); original.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(transport.PublishError, "real directory"): self.retire(inventory)
        self.assertEqual(self.deletes(), [])
        self.assertTrue((external / "sha256").is_dir())

    def test_cached_old_public_url_records_blocker_after_private_retirement(self):
        inventory = self.backup_all(); self.publish()
        key = inventory[0]["object_key"]
        self.http.public_bad[key] = transport.Response(200, {}, self.http.objects[key])
        with self.assertRaisesRegex(transport.PublishError, "cache purge"): self.retire(inventory)
        record = json.loads((self.backup / "retirement-result.json").read_text())
        self.assertEqual(record["remaining_complete_map_objects"], 0)
        self.assertEqual(record["public_urls_still_served"], [key])
        self.assertEqual(len(self.deletes()), 2)

    def test_signed_listing_pagination_duplicate_keys_and_entities_refused(self):
        self.http.listing_responses = [transport.Response(200, {}, b'<ListBucketResult><IsTruncated>true</IsTruncated><Contents><Key>one</Key></Contents><NextContinuationToken>a+b/== &amp;</NextContinuationToken></ListBucketResult>'),
            transport.Response(200, {}, b'<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>two</Key></Contents></ListBucketResult>')]
        self.assertEqual(self.r2.list_keys(), ["one", "two"])
        self.assertIn("continuation-token=a%2Bb%2F%3D%3D%20%26", self.http.requests[-1][1])
        for response in (b'<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>x</Key></Contents><Contents><Key>x</Key></Contents></ListBucketResult>',
                         b'<!DOCTYPE x [<!ENTITY value "secret">]><ListBucketResult/>', b'<ListBucketResult><IsTruncated>true</IsTruncated></ListBucketResult>'):
            self.http.listing_responses = [transport.Response(200, {}, response)]
            with self.assertRaises(transport.PublishError): self.r2.list_keys()
        url = f"https://{self.config['account_id']}.r2.cloudflarestorage.com/{self.config['bucket']}?list-type=2"
        with self.assertRaises(transport.PublishError): transport.sign_s3("GET", url, None, {}, "b" * 32, "c" * 64)
        with self.assertRaises(transport.PublishError): transport.sign_s3("GET", url, None, {}, "b" * 32, "c" * 64, query_parameters={"list-type": "1"})


if __name__ == "__main__": unittest.main()
