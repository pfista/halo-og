"""Network-free fixtures for the production on-demand desktop arsenal worker.

The existing bounded transport/thread harness is reused. Catalog parsing,
SHA-256, original-cache checks and safe pair publication run in production C.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

if __package__:
    from . import test_desktop_map_downloads as maps
else:
    import test_desktop_map_downloads as maps

PIN = "2856504cbd257e1b18c273caa64237fbfe77dc77d22cce1a7fa0a0abfc53f71f"
MAIN = r'''
int main(int count, char **arguments) {
    if (count != 6) return 2;
    root = arguments[1]; fixtures = arguments[2]; mode = arguments[3];
    if (!strcmp(mode, "exhaust")) {
        char revision[65];
        for (unsigned i = 1; i <= 130; i++) {
            snprintf(revision, sizeof(revision), "%064x", i);
            if (halo_arsenal_download_request("prisoner", arguments[4], revision) != 2) return 3;
        }
    }
    int first = halo_arsenal_download_request("prisoner", arguments[4], arguments[5]);
    int second = halo_arsenal_download_request("prisoner", arguments[4], arguments[5]);
    int third = halo_arsenal_download_request("prisoner", arguments[4], arguments[5]);
    printf("status=%d,%d,%d requests=%u objects=%u\n", first, second, third, calls, map_calls);
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang required for production downloader fixture")
class DesktopArsenalDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = maps.HARNESS
        try:
            harness = original[:original.index("int main(int count,")] + MAIN
            harness = harness.replace(
                'int catalog = strstr(url, "/catalogs/testing/current.json") != NULL;',
                'int catalog = strstr(url, "/catalogs/testing/arsenals-v1.json") != NULL;')
            maps.HARNESS = harness
            maps.DesktopMapDownloadTests.setUpClass.__func__(cls)
        finally:
            maps.HARNESS = original

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-og-arsenal-test-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.data, self.fixtures = root / "data", root / "fixtures"
        (self.data / "maps").mkdir(parents=True)
        self.fixtures.mkdir()
        self.originals = {}
        for logical, kind in (("bloodgulch", 1), ("a10", 0), ("ui", 2), ("prisoner", 1)):
            data = maps.cache(logical, kind)
            (self.data / "maps" / f"{logical}.map").write_bytes(data)
            self.originals[logical] = data
        self.base_sha = hashlib.sha256(self.originals["prisoner"]).hexdigest()
        self.cache = maps.cache("_fiesta_prisoner")
        self.cache_sha = hashlib.sha256(self.cache).hexdigest()
        self.manifest = {
            "schema_version": 1, "generation": 1, "logical_map": "prisoner",
            "physical_map": "_fiesta_prisoner", "base_sha256": self.base_sha,
            "cache_sha256": self.cache_sha, "weapon_list_sha256": PIN,
            "cache_file_bytes": len(self.cache), "cache_declared_bytes": 4096,
        }
        self.entry = {
            "logical_map": "prisoner", "physical_map": "_fiesta_prisoner",
            "base_sha256": self.base_sha, "cache_sha256": self.cache_sha,
            "cache_file_bytes": len(self.cache), "cache_declared_bytes": 4096,
            "cache_object_key": f"arsenals/v1/sha256/{self.cache_sha}/_fiesta_prisoner.map",
        }
        self.write_manifest()
        (self.fixtures / "_fiesta_prisoner.map").write_bytes(self.cache)
        self.catalog = {"schema_version": 1, "profile": "fiesta-arsenal-v1", "generation": 1,
                        "weapon_list_sha256": PIN, "arsenals": [self.entry]}
        self.destination = self.data / "maps/arsenal/v1"

    def write_manifest(self):
        raw = json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (self.fixtures / "_fiesta_prisoner.json").write_bytes(raw)
        self.entry.update(manifest_sha256=digest, manifest_bytes=len(raw),
                          manifest_object_key=f"arsenals/v1/sha256/{digest}/_fiesta_prisoner.json")

    def run_fixture(self, mode="normal", expected="", base=None, raw=None):
        (self.fixtures / "catalog.json").write_bytes(raw if raw is not None else json.dumps(self.catalog).encode())
        result = subprocess.run([str(self.binary), str(self.data), str(self.fixtures), mode,
                                 base or self.base_sha, expected], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(list((self.data / "maps").glob(".halo-og-arsenal-*")))
        for name, data in self.originals.items():
            self.assertEqual((self.data / "maps" / f"{name}.map").read_bytes(), data)
        return result.stdout

    def test_downloads_only_requested_pair_and_ready_after_verification(self):
        self.assertIn("status=2,1,1 requests=3 objects=2", self.run_fixture(expected=self.cache_sha))
        self.assertEqual((self.destination / "_fiesta_prisoner.map").read_bytes(), self.cache)
        self.assertEqual(json.loads((self.destination / "_fiesta_prisoner.json").read_bytes()), self.manifest)

    def test_existing_matching_pair_reused_without_object_download(self):
        self.destination.mkdir(parents=True)
        for suffix in ("map", "json"):
            shutil.copyfile(self.fixtures / f"_fiesta_prisoner.{suffix}", self.destination / f"_fiesta_prisoner.{suffix}")
        self.assertIn("status=2,1,1 requests=1 objects=0", self.run_fixture())

    def test_disabled_does_not_contact_network(self):
        self.assertIn("status=0,0,0 requests=0 objects=0", self.run_fixture(mode="disabled"))
        self.assertFalse(self.destination.exists())

    def test_host_revision_or_original_digest_must_match_catalog(self):
        for arguments in ({"expected": "a" * 64}, {"base": "b" * 64}):
            with self.subTest(arguments=arguments):
                result = self.run_fixture(**arguments)
                self.assertIn("status=2,-1,2", result)
                self.assertIn("objects=0", result)
                self.assertFalse(self.destination.exists())

    def test_failed_transport_never_publishes_pair(self):
        self.assertIn("status=2,-1,2", self.run_fixture(mode="fail-map"))
        self.assertFalse(list(self.destination.glob("*")))

    def test_invalid_manifest_rejected_before_cache_download(self):
        self.manifest["weapon_list_sha256"] = "a" * 64
        self.write_manifest()
        result = self.run_fixture()
        self.assertIn("status=2,-1,2", result)
        self.assertNotIn("_fiesta_prisoner.map", " ".join(p.name for p in self.destination.glob("*")))

    def test_corrupt_cache_is_not_published(self):
        (self.fixtures / "_fiesta_prisoner.map").write_bytes(self.cache[:-1] + b"X")
        self.assertIn("status=2,-1,2", self.run_fixture())
        self.assertFalse(list(self.destination.glob("*")))

    def test_hidden_cache_requires_exact_physical_header_name(self):
        raw = bytearray(self.cache); raw[33] = ord("F")
        self.cache = bytes(raw); self.cache_sha = hashlib.sha256(self.cache).hexdigest()
        self.entry["cache_sha256"] = self.manifest["cache_sha256"] = self.cache_sha
        self.entry["cache_object_key"] = f"arsenals/v1/sha256/{self.cache_sha}/_fiesta_prisoner.map"
        self.write_manifest()
        (self.fixtures / "_fiesta_prisoner.map").write_bytes(self.cache)
        self.assertIn("status=2,-1,2", self.run_fixture())
        self.assertFalse(list(self.destination.glob("*")))

    def test_failed_host_revisions_do_not_exhaust_lifetime_request_slots(self):
        self.assertIn("status=2,1,1 requests=133 objects=2", self.run_fixture(mode="exhaust"))
        self.assertEqual((self.destination / "_fiesta_prisoner.map").read_bytes(), self.cache)

    def test_existing_different_file_is_preserved(self):
        self.destination.mkdir(parents=True)
        target = self.destination / "_fiesta_prisoner.map"
        target.write_bytes(b"user supplied cache")
        self.assertIn("status=2,-1,2", self.run_fixture())
        self.assertEqual(target.read_bytes(), b"user supplied cache")
        self.assertFalse((self.destination / "_fiesta_prisoner.json").exists())

    def test_verified_partial_pair_can_be_completed_after_interruption(self):
        self.destination.mkdir(parents=True)
        (self.destination / "_fiesta_prisoner.map").write_bytes(self.cache)
        self.assertIn("status=2,1,1 requests=2 objects=1", self.run_fixture())
        self.assertTrue((self.destination / "_fiesta_prisoner.json").is_file())

    def test_duplicate_identity_unknown_field_and_object_path_are_rejected(self):
        invalid = []
        duplicate = copy.deepcopy(self.catalog)
        duplicate["arsenals"].append(copy.deepcopy(self.entry)); invalid.append(duplicate)
        extra = copy.deepcopy(self.catalog); extra["unexpected"] = 1; invalid.append(extra)
        traversal = copy.deepcopy(self.catalog); traversal["arsenals"][0]["cache_object_key"] = "../prisoner.map"; invalid.append(traversal)
        wrong_generation = copy.deepcopy(self.catalog); wrong_generation["generation"] = 2; invalid.append(wrong_generation)
        for catalog in invalid:
            with self.subTest(catalog=catalog):
                result = self.run_fixture(raw=json.dumps(catalog).encode())
                self.assertIn("status=2,-1,2", result)
                self.assertIn("objects=0", result)
                self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
