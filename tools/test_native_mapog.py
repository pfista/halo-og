"""Exercise the production bounded C inflater without assets, apps or network."""
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from tools.test_native_community_packages import ROOT, native_flags, compressed_package

HARNESS = r'''
#include "community_mapog.h"
#include <stdio.h>
int main(int argc, char **argv) {
    char error[512] = "";
    if (argc != 3) return 2;
    int result = community_mapog_expand(argv[1], argv[2], error, sizeof(error));
    printf("result=%d error=%s\n", result, error);
    return result ? 1 : 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "Native compiler is required")
class NativeMapogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory(prefix="halo-mapog-native-build-")
        build = Path(cls.build_temp.name).resolve()
        harness = build / "harness.c"; harness.write_text(HARNESS)
        cls.binary = build / ("expand.exe" if sys.platform == "win32" else "expand")
        result = subprocess.run([shutil.which("clang"), str(harness), *native_flags(build), "-o", str(cls.binary)],
                                capture_output=True, text=True)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-mapog-native-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.output = self.root / "input.mapog", self.root / "content.hogpkg"

    def expand(self, encoded, expected=None, output=None, source=None):
        self.source.write_bytes(encoded)
        target = output or self.output
        result = subprocess.run([str(self.binary), str(source or self.source), str(target)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0 if expected is not None else 1, result.stdout + result.stderr)
        if expected is not None:
            self.assertEqual(target.read_bytes(), expected)
            target.unlink()
        elif output is None:
            self.assertFalse(target.exists(), "Failed expansion must remove only its own incomplete output")
        return result

    def test_ring_wrap_input_boundaries_and_python_encoder_exact_bytes(self):
        generator = random.Random(482091)
        for size, random_bytes in ((18, False), (32767, True), (32768, True), (32769, True),
                                   (65535, True), (65536, True), (65537, True), (131071, True),
                                   (2 * 1024 * 1024, False)):
            with self.subTest(size=size):
                tail = generator.randbytes(size - 8) if random_bytes else b"asset-data" * ((size + 1) // 10)
                raw = b"HOGPKG1\n" + tail[:size - 8]
                self.expand(compressed_package(raw), raw)
        # Exercise the real publisher encoder, rather than only fixture zlib.
        from tools import mapog
        raw_file = self.root / "producer.hogpkg"
        raw = b"HOGPKG1\n" + generator.randbytes(90000); raw_file.write_bytes(raw)
        encoded = self.root / "publisher.mapog"; mapog.compress_package(raw_file, encoded)
        self.expand(encoded.read_bytes(), raw)

    def test_header_and_complete_stream_boundaries_are_strict(self):
        raw = b"HOGPKG1\n" + b"community asset" * 20000
        good = compressed_package(raw)
        cases = {"magic": b"badmagic" + good[8:], "short-header": good[:47], "short-stream": good[:-1],
                 "trailing": good + b"x", "second-stream": good + zlib.compress(b"second"),
                 "bad-adler": good[:-1] + bytes([good[-1] ^ 1]),
                 "wrong-sha": good[:16] + b"\0" * 32 + good[48:],
                 "bad-inner-magic": compressed_package(b"ORIGINAL" + raw[8:])}
        for size in (0, 17, len(raw) - 1, len(raw) + 1, 256 * 1024 * 1024 + 1, 2**64 - 1):
            cases[f"size-{size}"] = good[:8] + struct.pack("<Q", size) + good[16:]
        for name, encoded in cases.items():
            with self.subTest(name=name): self.expand(encoded)

    def test_raw_gzip_dictionary_and_bomb_refused_with_no_partial_file(self):
        raw = b"HOGPKG1\n" + b"unchanged repeated asset" * 50000
        header = struct.pack("<8sQ32s", b"HOGMAP2\n", len(raw), hashlib.sha256(raw).digest())
        for name, window in (("raw-deflate", -15), ("gzip", 31)):
            compressor = zlib.compressobj(9, zlib.DEFLATED, window)
            with self.subTest(name=name): self.expand(header + compressor.compress(raw) + compressor.flush())
        compressor = zlib.compressobj(9, zdict=b"unchanged repeated asset")
        self.expand(header + compressor.compress(raw) + compressor.flush())
        # A tiny authenticated declared length cannot permit a huge expansion.
        encoded = compressed_package(raw)
        self.expand(encoded[:8] + struct.pack("<Q", 18) + encoded[16:])

    def test_exclusive_destination_existing_bytes_and_symlinks_preserved(self):
        encoded = compressed_package(b"HOGPKG1\n" + b"new content")
        self.output.write_bytes(b"user-owned bytes")
        self.expand(encoded, output=self.output)
        self.assertEqual(self.output.read_bytes(), b"user-owned bytes")
        self.output.unlink(); self.output.mkdir()
        self.expand(encoded, output=self.output); self.assertTrue(self.output.is_dir())
        self.output.rmdir()
        existing = self.root / "existing"; existing.write_bytes(b"user-owned bytes")
        try: self.output.symlink_to(existing)
        except (OSError, NotImplementedError): self.skipTest("Symlink creation requires privileges on this host")
        self.expand(encoded, output=self.output)
        self.assertTrue(self.output.is_symlink()); self.assertEqual(existing.read_bytes(), b"user-owned bytes")

    def test_non_regular_input_parent_links_and_compressed_size_cap(self):
        encoded = compressed_package(b"HOGPKG1\n" + b"new content")
        source = self.root / "source-directory"; source.mkdir()
        self.expand(encoded, source=source)
        self.source.write_bytes(encoded)
        with self.source.open("r+b") as file: file.truncate(256 * 1024 * 1024 + 1)
        result = subprocess.run([str(self.binary), str(self.source), str(self.output)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr); self.assertFalse(self.output.exists())
        self.source.write_bytes(encoded)
        source_link = self.root / "source-link"
        try: source_link.symlink_to(self.source)
        except (OSError, NotImplementedError): self.skipTest("Symlink creation requires privileges on this host")
        self.expand(encoded, source=source_link)
        real = self.root / "real"; real.mkdir(mode=0o700)
        (real / "input.mapog").write_bytes(encoded)
        link = self.root / "linked-parent"; link.symlink_to(real, target_is_directory=True)
        self.expand(encoded, source=link / "input.mapog")
        self.expand(encoded, output=link / "output.hogpkg")
        self.assertFalse((real / "output.hogpkg").exists())
        if sys.platform != "win32":
            fifo = self.root / "pipe"; os.mkfifo(fifo)
            self.expand(encoded, source=fifo)

    def test_public_output_parent_refused_and_android_stub_has_no_inflater_dependency(self):
        if sys.platform != "win32":
            public = self.root / "public"; public.mkdir(mode=0o755)
            self.expand(compressed_package(b"HOGPKG1\n" + b"private only"), output=public / "inner.hogpkg")
            self.assertFalse((public / "inner.hogpkg").exists())
        harness = self.root / "guest.c"
        harness.write_text('#include "community_packages.h"\n#include "community_mapog.h"\n'
                           'int main(void) { return community_package_inspect("", 0, 0, 0) == -1 && '
                           'community_mapog_expand("", "", 0, 0) == -1 ? 0 : 1; }\n')
        target = self.root / ("guest.exe" if sys.platform == "win32" else "guest")
        result = subprocess.run([shutil.which("clang"), "-std=c11", "-DHALO_ANDROID", "-I" + str(ROOT / "port/linux/src"),
                                 str(ROOT / "port/linux/src/community_packages.c"), str(ROOT / "port/linux/src/community_mapog.c"),
                                 str(harness), "-o", str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(subprocess.run([str(target)]).returncode, 0)

    def test_vendored_inflater_matches_pinned_official_inventory(self):
        vendor = ROOT / "port/third_party/miniz"
        manifest = json.loads((vendor / "source-manifest.json").read_text())
        self.assertEqual(manifest["commit"], "174573d60290f447c13a2b1b3405de2b96e27d6c")
        for name, digest in manifest["files_sha256"].items():
            self.assertEqual(hashlib.sha256((vendor / name).read_bytes()).hexdigest(), digest, name)


if __name__ == "__main__": unittest.main()
