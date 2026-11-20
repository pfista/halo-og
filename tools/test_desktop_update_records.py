"""A desktop install record is immutable and names only a package the game can install."""
import hashlib
import io
import unittest
import zipfile

from tools import desktop_update_records as records
from tools.test_macos_release_publish import ORIGIN, Storage

TAG, SOURCE, DATE = "v0.6.1", "b" * 40, "2026-12-01T12:00:00Z"
DIGEST = hashlib.sha256(b"package").hexdigest()


def package(names, method=zipfile.ZIP_DEFLATED):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", method) as archive:
        for name in names:
            archive.writestr(name, b"contents of " + name.encode())
    return data.getvalue()


class RecordTests(unittest.TestCase):
    def test_record_is_the_fixed_text_the_game_parses(self):
        self.assertEqual(records.record("windows", TAG, SOURCE, DATE, 13609682, DIGEST).decode(),
                         "Halo OG update 1\nplatform: windows\ntag: v0.6.1\nsource: " + SOURCE +
                         "\ndate: 2026-12-01T12:00:00Z\nfile: halo-windows-release.zip\nsize: 13609682\nsha256: " +
                         DIGEST + "\n")
        for changes in ({"tag": "v0.6"}, {"tag": "v0.6.1\nfile: other"}, {"source": "B" * 40}, {"date": "2026-12-01"},
                        {"size": 0}, {"size": records.MAXIMUM_BYTES + 1}, {"sha256": DIGEST.upper()}):
            fields = {"tag": TAG, "source": SOURCE, "date": DATE, "size": 1, "sha256": DIGEST} | changes
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                records.record("linux", **fields)

    def test_only_a_package_the_installer_fully_installs_is_signed(self):
        records.audit_package("windows", package(["halo.exe", "SDL3.dll", "stb-LICENSE.txt"]))
        records.audit_package("linux", package(["halo", "mbedtls-LICENSE.txt"], zipfile.ZIP_STORED))
        # The installer skips paths and settings and stops at 32 files, so such a package would install in part.
        for platform, names in (("windows", ["halo.exe"]), ("linux", ["halo.exe", "SDL3.dll"]),
                                ("linux", ["halo", "maps/chillout.map"]), ("linux", ["halo", "config.toml"]),
                                ("linux", ["halo", "..\\escape.txt"]),
                                ("linux", ["halo"] + [f"file-{index}.txt" for index in range(32)])):
            with self.subTest(names=names[:3]), self.assertRaises(RuntimeError):
                records.audit_package(platform, package(names))
        with self.assertRaises(RuntimeError):
            records.audit_package("linux", package(["halo"], zipfile.ZIP_BZIP2))


class UploadTests(unittest.TestCase):
    record, signature = records.record("linux", TAG, SOURCE, DATE, 1, DIGEST), bytes(range(64))
    keys = ("updates/linux/v0.6.1.txt", "updates/linux/v0.6.1.txt.sig")

    def publish(self, storage, record=None):
        records.upload("linux", TAG, record or self.record, self.signature, ORIGIN, storage, storage.fetch)

    def test_record_and_signature_are_created_once_and_a_retry_is_safe(self):
        storage = Storage()
        self.publish(storage)
        self.assertEqual(storage.puts(), list(self.keys))
        self.assertTrue(all(headers["If-None-Match"] == "*" for _, _, headers in storage.requests))
        self.assertEqual([storage.objects[key] for key in self.keys], [self.record, self.signature])
        self.publish(storage)
        self.assertEqual([storage.objects[key] for key in self.keys], [self.record, self.signature])

    def test_a_published_record_is_never_replaced(self):
        storage = Storage()
        self.publish(storage)
        with self.assertRaisesRegex(RuntimeError, "different linux install record"):
            self.publish(storage, records.record("linux", TAG, SOURCE, DATE, 2, DIGEST))
        self.assertEqual(storage.objects[self.keys[0]], self.record)

    def test_records_stay_beneath_their_platform_and_release(self):
        self.assertEqual(records.keys("linux", TAG), self.keys)
        for platform, tag in (("mac", TAG), ("linux", "../maps"), ("linux", "testing"), ("linux", "v0.6.1/x")):
            with self.subTest(platform=platform, tag=tag), self.assertRaises(RuntimeError):
                records.keys(platform, tag)
        with self.assertRaisesRegex(RuntimeError, "64 bytes"):
            records.upload("linux", TAG, self.record, bytes(63), ORIGIN, Storage(), lambda url: None)


if __name__ == "__main__":
    unittest.main()
