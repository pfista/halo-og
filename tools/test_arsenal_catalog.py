"""Offline hidden-arsenal delivery schema, source isolation and publication tests.

Synthetic cache headers exercise delivery boundaries; they do not establish
weapon/playability equivalence. Production native preflight remains separate.
"""
import ast
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

from tools import arsenal_catalog as catalog
from tools import publish_arsenal_catalog as publisher
from tools import publish_map_catalog as shared
from tools.test_map_catalog import synthetic_map
from tools.test_publish_map_catalog import FakeHTTPS


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode("ascii")


class ArsenalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="halo-arsenal-delivery-")
        self.addCleanup(self.temporary.cleanup)
        # macOS /var aliases /private/var. Tests use the real root, keeping the
        # production output policy's no-symlink boundary intact.
        self.root = Path(self.temporary.name).resolve()
        self.arsenal = self.root / "reviewed/maps/arsenal/v1"
        self.arsenal.mkdir(parents=True)
        self.physical = catalog.physical_name("prisoner")
        self.cache = self.arsenal / (self.physical + ".map")
        self.cache_data = synthetic_map(self.cache)
        self.manifest = {"schema_version": 1, "generation": 1, "logical_map": "prisoner",
                         "physical_map": self.physical, "cache_sha256": hashlib.sha256(self.cache_data).hexdigest(),
                         "base_sha256": "a" * 64, "weapon_list_sha256": catalog.WEAPON_LIST_SHA256,
                         "cache_file_bytes": len(self.cache_data), "cache_declared_bytes": len(self.cache_data)}
        self.manifest_path = self.cache.with_suffix(".json")
        self.manifest_path.write_bytes(encoded(self.manifest))
        header = (catalog.ROOT / "port/linux/include/halo_expanded_cache_weapons.h").read_text()
        weapons = [ast.literal_eval(value) for value in re.findall(r'^\s*(".*"),$', header, re.M)]
        reviewed = {**self.manifest, "eligible_weapons": weapons, "all_count": 31, "uncut_count": 9,
                    "authoring_manifest": "/private/authoring/source/manifest.json",
                    "compiled_player_proof": {"all_other_compiled_player_bytes_equal": True,
                                              "compiled_multiplayer_globals_reference_verified": True,
                                              "proof_directory": "/private/authoring/player-proof"}}
        self.authoring = {"schema_version": 1, "generation": 1, "weapon_list_sha256": catalog.WEAPON_LIST_SHA256,
                          "maps": {"prisoner": reviewed}, "failures": {}}
        self.authoring_path = self.root / "reviewed/catalog.json"
        self.authoring_path.write_bytes(encoded(self.authoring))
        self.output = self.root / "build/delivery"
        self.root_patch = patch.object(catalog, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def prepare(self):
        return catalog.prepare_catalog(self.authoring_path, self.arsenal, self.output)

    def test_clean_exact_catalog_objects_and_unchanged_sources(self):
        original = {path: path.read_bytes() for path in (self.cache, self.manifest_path, self.authoring_path)}
        prepared = self.prepare()
        parsed = catalog.validate_catalog(prepared.catalog)
        self.assertEqual(set(parsed), catalog.CATALOG_FIELDS)
        self.assertEqual(set(parsed["arsenals"][0]), catalog.ENTRY_FIELDS)
        self.assertEqual(len(prepared.objects), 2)
        self.assertEqual(prepared.upload_bytes, len(prepared.catalog) + len(self.cache_data) + len(encoded(self.manifest)))
        self.assertNotIn(b"/private/authoring", prepared.catalog)
        self.assertNotIn(b"authoring_manifest", prepared.catalog)
        self.assertEqual(catalog.validate_prepared(self.output).catalog, prepared.catalog)
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)

    def test_identity_is_logical_map_and_original_base_digest(self):
        entry = catalog.entry_from_manifest(encoded(self.manifest))
        other_manifest = {**self.manifest, "base_sha256": "b" * 64}
        other = catalog.entry_from_manifest(encoded(other_manifest))
        self.assertEqual(len(catalog.validate_catalog(catalog.catalog_bytes([entry, other]))["arsenals"]), 2)
        with self.assertRaisesRegex(shared.PublishError, "Duplicate"):
            catalog.catalog_bytes([entry, copy.deepcopy(entry)])

    def test_public_names_match_downloader_safety_and_generation_one_identities(self):
        self.assertEqual(catalog.physical_name("prisoner"), "_fiesta_prisoner")
        self.assertEqual(catalog.physical_name("safe map-2"), "_fiesta_safe map-2")
        logical = "a" * 24
        self.assertEqual(catalog.physical_name(logical),
                         "_fiestah_" + hashlib.sha256(logical.encode("ascii")).hexdigest()[:16])
        for logical in ("", "A", "_hidden", " space", "trailing ", "a" * 32, "../map", "ui", "a10",
                        "con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9", "nonasciié"):
            with self.subTest(logical=logical), self.assertRaises(shared.PublishError):
                catalog.physical_name(logical)

    def test_generation_pin_exact_fields_integer_and_transfer_bounds(self):
        good = json.loads(catalog.catalog_bytes([catalog.entry_from_manifest(encoded(self.manifest))]))
        cases = []
        for key, value in (("schema_version", True), ("generation", 2), ("profile", "stock-xbox-ntsc"),
                           ("weapon_list_sha256", "0" * 64), ("private_path", "/private/source"), ("arsenals", [])):
            changed = copy.deepcopy(good);changed[key] = value;cases.append(changed)
        for key, value in (("manifest_bytes", True), ("manifest_bytes", 4097), ("cache_file_bytes", 536870913),
                           ("cache_declared_bytes", 536870913), ("base_sha256", "A" * 64),
                           ("physical_map", "_fiesta_other"), ("logical_map", "../prisoner"),
                           ("cache_object_key", "arsenals/v1/../prisoner.map"), ("private_path", "/private/source")):
            changed = copy.deepcopy(good);changed["arsenals"][0][key] = value;cases.append(changed)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(shared.PublishError):
                catalog.validate_catalog(encoded(value))
        entry = good["arsenals"][0]
        with patch.object(catalog, "MAX_BATCH_BYTES", len(encoded(good)) + entry["cache_file_bytes"]):
            with self.assertRaisesRegex(shared.PublishError, "2 GiB"):
                catalog.validate_catalog(encoded(good))
        with self.assertRaises(shared.PublishError):
            catalog.validate_catalog(b'{"schema_version":1,"schema_version":1}')
        with self.assertRaises(shared.PublishError):
            catalog.validate_catalog(encoded(good) + b" " * catalog.MAX_CATALOG_BYTES)
        with self.assertRaises(shared.PublishError):
            catalog.validate_catalog(encoded(good).replace(b"prisoner", b"pris\\u006fner"))

    def test_512_mib_cache_admission_keeps_independent_manifest_and_batch_limits(self):
        boundary = {**self.manifest, "cache_file_bytes": 512 * 1024 * 1024,
                    "cache_declared_bytes": 512 * 1024 * 1024}
        self.assertEqual(catalog.validate_manifest(encoded(boundary)), boundary)
        entry = catalog.entry_from_manifest(encoded(boundary))
        self.assertEqual(catalog.validate_catalog(catalog.catalog_bytes([entry]))["arsenals"][0]["cache_file_bytes"], 536870912)
        for field in ("cache_file_bytes", "cache_declared_bytes"):
            with self.subTest(field=field), self.assertRaises(shared.PublishError):
                catalog.validate_manifest(encoded({**boundary, field: 512 * 1024 * 1024 + 1}))
        self.assertEqual(catalog.MAX_MANIFEST_BYTES, 4096)
        self.assertEqual(catalog.MAX_BATCH_BYTES, 2 * 1024 * 1024 * 1024)
        # Numbers in small JSON exercise transfer admission, without allocating maps.
        entries = []
        for index in range(5):
            logical = "synthetic" + str(index)
            value = {**boundary, "logical_map": logical, "physical_map": catalog.physical_name(logical),
                     "base_sha256": format(index, "064x")}
            entries.append(catalog.entry_from_manifest(encoded(value)))
        with self.assertRaisesRegex(shared.PublishError, "2 GiB"):
            catalog.catalog_bytes(entries)

    def test_flat_manifest_must_match_catalog_exactly(self):
        prepared = self.prepare()
        entry = prepared.arsenals[0]
        path = self.output / entry["manifest_object_key"]
        path.write_bytes(encoded({**self.manifest, "base_sha256": "b" * 64}))
        with self.assertRaisesRegex(shared.PublishError, "flat manifest"):
            catalog.validate_prepared(self.output)

    def test_extra_files_and_symlinks_are_refused(self):
        prepared = self.prepare()
        extra = self.output / "private-authoring.json"
        extra.write_text("private")
        with self.assertRaises(shared.PublishError):
            catalog.validate_prepared(self.output)
        extra.unlink()
        target = self.output / prepared.arsenals[0]["manifest_object_key"]
        target.unlink();target.symlink_to(self.manifest_path)
        with self.assertRaises(shared.PublishError):
            catalog.validate_prepared(self.output)

    def test_output_traversal_symlink_and_existing_target_are_preserved(self):
        for output in (self.root / "build/../reviewed", self.root / "elsewhere/delivery"):
            with self.subTest(output=output), self.assertRaises(shared.PublishError):
                catalog.prepare_catalog(self.authoring_path, self.arsenal, output)
        (self.root / "build").mkdir()
        (self.root / "build/alias").symlink_to(self.root / "reviewed", target_is_directory=True)
        with self.assertRaises(shared.PublishError):
            catalog.prepare_catalog(self.authoring_path, self.arsenal, self.root / "build/alias/delivery")
        self.output.mkdir()
        marker = self.output / "keep";marker.write_text("existing")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(marker.read_text(), "existing")

    def test_changed_or_unqualified_source_is_refused(self):
        changed = copy.deepcopy(self.authoring)
        changed["maps"]["prisoner"]["compiled_player_proof"]["all_other_compiled_player_bytes_equal"] = False
        self.authoring_path.write_bytes(encoded(changed))
        with self.assertRaises(shared.PublishError):
            self.prepare()
        self.authoring_path.write_bytes(encoded(self.authoring))
        original_copy = catalog.shutil.copyfile
        def corrupt(source, destination, **kwargs):
            result = original_copy(source, destination, **kwargs)
            if Path(destination).suffix == ".map":
                with Path(destination).open("ab") as stream:
                    stream.write(b"changed")
            return result
        with patch.object(catalog.shutil, "copyfile", side_effect=corrupt):
            with self.assertRaises(shared.PublishError):
                self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob(".delivery-*.partial")), [])
        self.assertEqual(self.cache.read_bytes(), self.cache_data)

    def test_hidden_publisher_verifies_both_objects_before_catalog_and_leaves_visible_unchanged(self):
        prepared = self.prepare()
        config = publisher.load_config()
        http = FakeHTTPS(config)
        visible_key = shared.load_config()["catalog_key"]
        http.objects[visible_key] = b"existing visible catalog"
        r2 = shared.R2(config, "b" * 32, "c" * 64, http)
        publisher.publish(prepared, config, r2, http, progress=lambda line: None)
        writes = [request for request in http.requests if request[0] == "PUT"]
        self.assertEqual(len(writes), 3)
        self.assertTrue(writes[-1][1].endswith("/" + catalog.CATALOG_KEY))
        self.assertEqual(writes[1][2]["content-type"], "application/json")
        for entry in prepared.objects:
            public_read = next(index for index, request in enumerate(http.requests)
                               if request[1] == config["public_base_url"] + entry["object_key"])
            self.assertLess(public_read, http.requests.index(writes[-1]))
        self.assertEqual(http.objects[visible_key], b"existing visible catalog")
        http.requests.clear()
        publisher.publish(prepared, config, r2, http, progress=lambda line: None)
        self.assertEqual([request for request in http.requests if request[0] == "PUT"], [])

    def test_public_manifest_mismatch_never_advances_catalog(self):
        prepared = self.prepare()
        config = publisher.load_config()
        http = FakeHTTPS(config)
        for entry in prepared.objects:
            http.objects[entry["object_key"]] = (self.output / entry["object_key"]).read_bytes()
        http.objects[catalog.CATALOG_KEY] = b"previous hidden catalog"
        http.public_bad[prepared.arsenals[0]["manifest_object_key"]] = shared.Response(200, {}, b"different")
        with self.assertRaises(shared.PublishError):
            publisher.publish(prepared, config, shared.R2(config, "b" * 32, "c" * 64, http), http, progress=lambda line: None)
        self.assertEqual(http.objects[catalog.CATALOG_KEY], b"previous hidden catalog")
        self.assertEqual([request for request in http.requests if request[0] == "PUT"], [])

    def test_allowed_space_names_use_encoded_immutable_http_paths(self):
        physical = catalog.physical_name("safe map")
        cache = self.arsenal / (physical + ".map")
        data = synthetic_map(cache)
        manifest = {**self.manifest, "logical_map": "safe map", "physical_map": physical,
                    "cache_sha256": hashlib.sha256(data).hexdigest()}
        raw = encoded(manifest)
        entry = catalog.entry_from_manifest(raw)
        self.output.mkdir(parents=True)
        for key, content in ((entry["cache_object_key"], data), (entry["manifest_object_key"], raw)):
            path = self.output / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.output / "catalog.json").write_bytes(catalog.catalog_bytes([entry]))
        prepared = catalog.validate_prepared(self.output)
        config = publisher.load_config()
        http = FakeHTTPS(config)
        publisher.publish(prepared, config, shared.R2(config, "b" * 32, "c" * 64, http), http,
                          progress=lambda line: None)
        for item in prepared.objects:
            key = quote(item["object_key"], safe="/-_.~")
            self.assertTrue(any(url == config["public_base_url"] + key for _, url, _, _ in http.requests))
            self.assertTrue(any(method == "PUT" and url.endswith("/" + key)
                                for method, url, _, _ in http.requests))
        self.assertFalse(any(" " in url for _, url, _, _ in http.requests))

    def test_default_cli_never_reads_credentials_or_connects(self):
        self.prepare()
        with patch.object(sys, "argv", ["publish_arsenal_catalog.py", "--prepared", str(self.output)]), \
             patch.object(shared, "load_token", side_effect=AssertionError("Credentials must not be read")), \
             patch.object(shared, "HTTPS", side_effect=AssertionError("Network must not be used")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            publisher.main()
        self.assertIn("Offline validation only", output.getvalue())
        with self.assertRaises(shared.PublishError):
            shared.validate_prepared(self.output, shared.load_config())


if __name__ == "__main__":
    unittest.main()
