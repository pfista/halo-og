"""Asset-free batch gates; real Invader acceptance is separate ignored evidence."""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from tools import community_package_batch as batch
from tools import community_packages as packages
from tools import test_community_packages as fixtures
from tools.test_map_catalog import synthetic_map


class CommunityPackageBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CommunityPackageTests("test_whole_unchanged_assets_only_and_exact_materialization")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.root = f.root
        self.collection = self.root / "collection"
        self.collection.mkdir()
        shutil.copytree(f.patched, self.collection / "stock-tags")
        self.tools = self.root / "tools"
        self.tools.mkdir()
        suffix = ".exe" if packages._consumer_platform() == "windows" else ""
        for name in ("extract", "build"):
            (self.tools / ("invader-" + name + suffix)).write_bytes(("fake-" + name).encode())
        stock = packages._stock_inputs(f.maps)
        self.build = {"profile": "stock-xbox-ntsc", "invader_commit": packages.INVADER_COMMIT,
                      "tool_sha256": packages._tools(f.toolchain),
                      "stock": {"inputs": {item["name"]: {**item, "file_bytes": item["size"]} for item in stock}},
                      "maps": []}
        self.catalog = self.root / "catalog.json"
        self.catalog_record = {"schema_version": 1, "profile": "stock-xbox-ntsc", "maps": []}
        self.add_map("downrush")
        self.destination = self.root / "batch-output"

    def add_map(self, ident):
        folder = self.collection / ident
        folder.mkdir()
        shutil.copytree(self.fixture.tags, folder / "tags")
        shutil.copytree(self.fixture.data, folder / "data")
        scenario = f"levels/test/{ident}/{ident}"
        tag = folder / "tags" / (scenario + ".scenario")
        tag.parent.mkdir(parents=True, exist_ok=True)
        tag.write_bytes(b"authored-scenario-" + ident.encode())
        (folder / "maps").mkdir()
        synthetic_map(folder / "maps" / (ident + ".map"))
        cache = packages._cache(folder / "maps" / (ident + ".map"))
        record = {"id": ident, "profile": "stock-xbox-ntsc", "compiled_scenario": scenario,
                  "sha256": cache["sha256"], "file_bytes": cache["size"]}
        (folder / "manifest.json").write_text(json.dumps(record))
        self.build["maps"].append({"id": ident})
        (self.collection / "build.json").write_text(json.dumps(self.build))
        self.catalog_record["maps"].append({"id": ident, "cache_version": 5,
            "cache_build": packages.NTSC_BUILD, "scenario_type": 1,
            "file_bytes": cache["size"], "sha256": cache["sha256"]})
        self.catalog.write_text(json.dumps(self.catalog_record))

    def arguments(self):
        return dict(prepared_collections=[self.collection], approved_catalog=self.catalog,
                    stock_maps=self.fixture.maps, tool_bin=self.tools,
                    toolchain_manifest=self.fixture.toolchain,
                    expected_count=len(self.catalog_record["maps"]))

    def fresh_stock(self, binaries, stock_maps, destination, logs):
        shutil.copytree(self.fixture.original, destination)
        logs.mkdir()

    def rebuild(self, *, package, destination, **unused):
        manifest = packages.read_package(package)
        destination.mkdir()
        (destination / "maps").mkdir()
        ident = manifest["id"]
        shutil.copyfile(self.collection / ident / "maps" / (ident + ".map"),
                        destination / "maps" / (ident + ".map"))
        return {"status": "exact-reconstruction"}

    def verify(self, rebuild=None):
        with patch.object(batch, "_fresh_stock", side_effect=self.fresh_stock), \
             patch.object(packages, "reconstruct_package", side_effect=rebuild or self.rebuild):
            return batch.verify_collection(**self.arguments(), destination=self.destination)

    def test_exact_set_and_identity_required_before_outputs(self):
        original = copy.deepcopy(self.catalog_record)
        for changed in (dict(original, profile="foreign"), dict(original, schema_version=True),
                        dict(original, maps=original["maps"] * 2)):
            self.catalog.write_text(json.dumps(changed))
            with self.assertRaises(packages.PackageError):
                batch.inventory_collection(**self.arguments())
            self.assertFalse(self.destination.exists())
        self.catalog.write_text(json.dumps(original))
        broken = copy.deepcopy(original)
        broken["maps"][0]["sha256"] = "0" * 64
        self.catalog.write_text(json.dumps(broken))
        with self.assertRaises(packages.PackageError):
            batch.verify_collection(**self.arguments(), destination=self.destination)
        self.assertFalse(self.destination.exists())

    def test_duplicate_collection_and_changed_helper_rejected(self):
        args = self.arguments()
        args["prepared_collections"] *= 2
        with self.assertRaises(packages.PackageError):
            batch.inventory_collection(**args)
        executable = next(self.tools.iterdir())
        executable.write_bytes(b"changed-tool")
        with self.assertRaises(packages.PackageError):
            batch.verify_collection(**self.arguments(), destination=self.destination)
        self.assertFalse(self.destination.exists())

    def test_whole_asset_audit_and_inputs_unchanged(self):
        before = self.fixture.source_snapshot()
        report = self.verify()
        self.assertEqual((report["status"], report["verified_maps"]), ("exact-reconstruction-complete", 1))
        self.assertTrue(report["inputs_unchanged"])
        audit = json.loads((self.destination / "maps/downrush/asset-audit.json").read_text())
        self.assertEqual(audit["literal_whole_stock_matches"], [])
        self.assertEqual(audit["classifications"]["unchanged-stock"]["files"], 1)
        modified = next(item for item in audit["files"] if item["path"] == self.fixture.modified)
        self.assertEqual((modified["kind"], modified["size"]),
                         ("literal", len(self.fixture.tag_bytes[self.fixture.modified])))
        self.assertEqual(self.fixture.source_snapshot(), before)

    def test_literal_original_match_independently_detected(self):
        manifest = self.fixture.prepare()
        reference = next(item for item in manifest["files"] if item["kind"] == "stock-reference")
        reference["kind"] = "literal"
        audit = batch.asset_audit(manifest, self.fixture.original)
        self.assertEqual(len(audit["literal_whole_stock_matches"]), 1)

    def test_bad_rebuild_does_not_claim_verification_and_next_map_runs(self):
        self.add_map("atlas")
        def rebuild(**kwargs):
            result = self.rebuild(**kwargs)
            if Path(kwargs["package"]).stem == "atlas":
                output = kwargs["destination"] / "maps/atlas.map"
                raw = output.read_bytes()
                output.write_bytes(raw[:-1] + b"!")
            return result
        report = self.verify(rebuild)
        self.assertEqual((report["status"], report["verified_maps"], report["failed_maps"]), ("failed", 1, 1))
        self.assertFalse((self.destination / "maps/atlas/reconstructed").exists())
        self.assertTrue((self.destination / "maps/downrush/reconstructed/maps/downrush.map").exists())

    def test_existing_destination_and_source_output_refused(self):
        self.destination.mkdir()
        sentinel = self.destination / "preserved"
        sentinel.write_bytes(b"keep")
        with self.assertRaises(packages.PackageError):
            self.verify()
        self.assertEqual(sentinel.read_bytes(), b"keep")
        with self.assertRaises(packages.PackageError):
            batch.verify_collection(**self.arguments(), destination=self.fixture.maps / "new-output")
        self.assertFalse((self.fixture.maps / "new-output").exists())


if __name__ == "__main__":
    unittest.main()
