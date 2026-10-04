"""Synthetic compressed-map integrity, expansion bounds and exact inner assets."""
import hashlib
from pathlib import Path
import struct
import unittest
import zlib

from tools import community_packages as packages
from tools import mapog
from tools import test_community_packages as fixtures


class MapOGTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CommunityPackageTests(methodName="test_whole_unchanged_assets_only_and_exact_materialization")
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.manifest = self.fixture.prepare()
        self.compressed = self.fixture.root / "downrush.mapog"
        self.expanded = self.fixture.root / "expanded.hogpkg"

    def compress(self):
        return mapog.compress_package(self.fixture.package, self.compressed)

    def test_lossless_smaller_outer_transport_keeps_complete_asset_audit(self):
        before = self.fixture.source_snapshot()
        result = self.compress()
        self.assertLess(result["compressed_bytes"], result["expanded_bytes"])
        self.assertEqual(result["sha256"], packages.digest(self.compressed))
        self.assertEqual(packages.read_package(self.compressed), self.manifest)
        mapog.expand_package(self.compressed, self.expanded)
        self.assertEqual(self.expanded.read_bytes(), self.fixture.package.read_bytes())
        with mapog.raw_package(self.compressed) as private:
            self.assertTrue(private.exists())
            owned_parent = private.parent
        self.assertFalse(owned_parent.exists())
        self.assertEqual(packages.materialize_package(package=self.compressed,
            original_stock_tags=self.fixture.original, destination=self.fixture.destination), self.manifest)
        self.assertEqual(fixtures.tree_bytes(self.fixture.destination / "tags"), self.fixture.tag_bytes)
        self.assertEqual(before, self.fixture.source_snapshot())

    def forged(self, raw_size=None, raw_hash=None, payload=None, suffix=b""):
        raw = self.fixture.package.read_bytes()
        header = mapog.HEADER.pack(mapog.MAGIC, len(raw) if raw_size is None else raw_size,
            hashlib.sha256(raw).digest() if raw_hash is None else raw_hash)
        path = self.fixture.root / "forged.mapog"
        path.write_bytes(header + (zlib.compress(raw) if payload is None else payload) + suffix)
        return path

    def test_wrong_hash_size_truncation_dictionary_multiple_streams_or_trailing_data_cleanup(self):
        raw = self.fixture.package.read_bytes()
        dictionary = zlib.compressobj(zdict=b"original-content")
        dict_stream = dictionary.compress(raw) + dictionary.flush()
        cases = [dict(raw_hash=b"x" * 32), dict(raw_size=len(raw) - 1),
                 dict(raw_size=len(raw) + 1), dict(payload=zlib.compress(raw)[:-1]),
                 dict(payload=dict_stream), dict(suffix=zlib.compress(b"second-stream")),
                 dict(suffix=b"!"), dict(payload=b"invalid compressed stream"),
                 dict(raw_size=mapog.MAX_BYTES + 1)]
        for change in cases:
            with self.subTest(change=next(iter(change))):
                with self.assertRaises(ValueError): mapog.expand_package(self.forged(**change), self.expanded)
                self.assertFalse(self.expanded.exists())

    def test_compression_bomb_cannot_write_past_declared_expansion(self):
        path = self.forged(raw_size=18, payload=zlib.compress(mapog.RAW_MAGIC + b"A" * (4 * 1024 * 1024)))
        with self.assertRaisesRegex(ValueError, "exceeds its exact bound"):
            mapog.expand_package(path, self.expanded)
        self.assertFalse(self.expanded.exists())

    def test_existing_output_is_preserved_and_invalid_inner_format_refused(self):
        self.compress()
        self.expanded.write_bytes(b"keep me")
        with self.assertRaises(FileExistsError): mapog.expand_package(self.compressed, self.expanded)
        self.assertEqual(self.expanded.read_bytes(), b"keep me")
        with self.assertRaises(FileExistsError): self.compress()
        self.assertEqual(packages.read_package(self.compressed), self.manifest)
        self.expanded.unlink()
        wrong = b"NOT-A-PACKAGE" * 20
        path = self.forged(raw_size=len(wrong), raw_hash=hashlib.sha256(wrong).digest(), payload=zlib.compress(wrong))
        with self.assertRaises(ValueError): mapog.expand_package(path, self.expanded)
        self.assertFalse(self.expanded.exists())

    def test_large_stream_is_bounded_chunkwise_and_lossless(self):
        source = self.fixture.root / "large.hogpkg"
        source.write_bytes(mapog.RAW_MAGIC + bytes(range(256)) * 32768)
        mapog.compress_package(source, self.compressed)
        mapog.expand_package(self.compressed, self.expanded)
        self.assertEqual(packages.digest(source), packages.digest(self.expanded))


if __name__ == "__main__": unittest.main()
