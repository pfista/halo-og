"""Asset-free acceptance for the package-only public delivery boundary."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import community_packages as packages
from tools import package_catalog as catalog
from tools import test_community_packages as fixtures


class PackageCatalogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CommunityPackageTests(methodName="test_whole_unchanged_assets_only_and_exact_materialization")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare()
        self.root = self.fixture.root
        self.output = self.root / "delivery"

    def prepare(self):
        return catalog.prepare_package_catalog([self.fixture.package], [self.fixture.expected],
            self.fixture.original, self.output, ["downrush"])

    def test_only_packages_public_and_whole_original_audit(self):
        record, audit = self.prepare()
        entry = record["maps"][0]
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(entry["object_key"], f"packages/sha256/{entry['package_sha256']}/downrush.mapog")
        self.assertNotEqual(entry["package_sha256"], packages.digest(self.fixture.package))
        self.assertEqual(entry["sha256"], packages.digest(self.fixture.expected))
        self.assertEqual(audit["catalog_sha256"], packages.digest(self.output / "catalog.json"))
        self.assertTrue(audit["modified_originals_retained"])
        self.assertEqual(audit["maps"][0]["unchanged_original_literals"], 0)
        self.assertEqual(set(p.suffix for p in self.output.rglob("*") if p.is_file()), {".json", ".mapog"})
        catalog.validate_public_tree(self.output, {"downrush"})
        with self.assertRaises(FileExistsError): self.prepare()

    def test_extra_complete_map_empty_folder_link_or_unknown_id_rejected(self):
        self.prepare()
        for relative in ("original.map", "logs"):
            path = self.output / relative
            path.mkdir() if relative == "logs" else path.write_bytes(b"forbidden")
            with self.assertRaises(ValueError): catalog.validate_public_tree(self.output)
            path.rmdir() if path.is_dir() else path.unlink()
        with self.assertRaises(ValueError): catalog.validate_public_tree(self.output, {"atlas"})
        link = self.output / "link"
        try:
            link.symlink_to(self.fixture.original, target_is_directory=True)
        except OSError:
            return  # Native Windows runners can lack symlink privilege.
        with self.assertRaises(ValueError): catalog.validate_public_tree(self.output)

    def test_full_map_schema_duplicate_json_bad_key_or_corrupt_package_rejected(self):
        record, _ = self.prepare()
        path = self.output / "catalog.json"
        original = path.read_bytes()
        for change in ("schema", "map-key", "unknown-field", "bool-length"):
            bad = copy.deepcopy(record)
            if change == "schema": bad["schema_version"] = 1
            elif change == "map-key": bad["maps"][0]["object_key"] = "maps/sha256/" + "a" * 64 + "/downrush.map"
            elif change == "unknown-field": bad["maps"][0]["url"] = "https://untrusted.test/"
            else: bad["maps"][0]["package_bytes"] = True
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError): catalog.validate_public_tree(self.output)
        path.write_bytes(original.replace(b'"schema_version": 2', b'"schema_version": 2, "schema_version": 2'))
        with self.assertRaises(ValueError): catalog.validate_public_tree(self.output)
        path.write_bytes(original)
        package = self.output / record["maps"][0]["object_key"]
        with package.open("ab") as stream: stream.write(b"!")
        with self.assertRaises(ValueError): catalog.validate_public_tree(self.output)

    def test_literal_under_another_path_cannot_smuggle_unchanged_original(self):
        manifest = packages.read_package(self.fixture.package)
        literal = next(item for item in manifest["files"] if item["kind"] == "literal")
        # Introduce the same complete bytes into the pristine stock inventory at
        # another path. Classification labels do not grant permission to serve it.
        payload = self.fixture.payload()
        source = self.fixture.original / "renamed-original.weapon"
        source.write_bytes(payload[literal["offset"]:literal["offset"] + literal["size"]])
        with self.assertRaisesRegex(ValueError, "unchanged whole original"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_final_rebuild_identity_is_required_and_inputs_preserved(self):
        before = self.fixture.source_snapshot()
        with self.fixture.expected.open("ab") as stream: stream.write(b"!")
        with self.assertRaisesRegex(ValueError, "exact independently rebuilt"):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.fixture.source_snapshot())

    def test_changed_source_between_audit_and_compression_never_published(self):
        original = self.fixture.package.read_bytes()
        compress = catalog.mapog.compress_package
        def changed_source(source, destination):
            # A retained literal changed after the omission check. Even if a
            # later validator could parse it, its audit no longer applies.
            data = bytearray(original)
            data[-1] ^= 1
            source.write_bytes(data)
            return compress(source, destination)
        with patch.object(catalog.mapog, "compress_package", side_effect=changed_source):
            with self.assertRaisesRegex(ValueError, "source changed"):
                self.prepare()
        self.assertFalse(self.output.exists())
        self.assertFalse(any(path.name.startswith(".package-delivery-") for path in self.root.iterdir()))


if __name__ == "__main__": unittest.main()
