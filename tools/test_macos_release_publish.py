"""Publishing a Mac update must never replace an archive or advance the feed early."""
import base64
import hashlib
import json
from pathlib import Path
import unittest

from tools.ed25519_verify import verify
from tools.macos_build import BUNDLE_ID, update_configuration
from tools.macos_release import (CONFIG, appcast, feed_entry, object_key, require_newer_than_feed,
                                 require_signature, upload)
from tools import publish_map_catalog as hosting

ORIGIN = "https://dl.oghalo.com/"
DMG, FEED = b"disk image bytes", b"<rss/>"
RECORD = {
    "url": ORIGIN + "updates/mac/200/Halo-OG-0.6.0.dmg",
    "feed_url": ORIGIN + "updates/mac/testing/appcast.xml",
    "sha256": hashlib.sha256(DMG).hexdigest(),
}


class Storage:
    """An R2 bucket and its public origin, recording each request in order."""

    def __init__(self, objects=None, failing=None):
        self.objects, self.failing, self.requests = dict(objects or {}), failing or {}, []

    def request(self, method, key, *, body=None, headers=None, limit=16384):
        self.requests.append((method, key, dict(headers or {})))
        if key in self.failing:
            return hosting.Response(self.failing[key], {}, b"")
        if headers.get("If-None-Match") == "*" and key in self.objects:
            return hosting.Response(412, {}, b"")
        self.objects[key] = body
        return hosting.Response(200, {}, b"")

    def fetch(self, url):
        return self.objects.get(url[len(ORIGIN):])

    def puts(self):
        return [key for method, key, _ in self.requests if method == "PUT"]


class PublishTests(unittest.TestCase):
    archive, feed = "updates/mac/200/Halo-OG-0.6.0.dmg", "updates/mac/testing/appcast.xml"

    def publish(self, storage):
        upload(RECORD, DMG, FEED, ORIGIN, storage, storage.fetch)

    def test_new_release_creates_the_archive_then_advances_the_feed(self):
        storage = Storage()
        self.publish(storage)
        self.assertEqual(storage.puts(), [self.archive, self.feed])
        self.assertEqual(storage.requests[0][2]["If-None-Match"], "*")
        self.assertNotIn("If-None-Match", storage.requests[1][2])
        self.assertEqual(storage.requests[1][2]["Cache-Control"], "no-cache")
        self.assertEqual((storage.objects[self.archive], storage.objects[self.feed]), (DMG, FEED))

    def test_retry_with_the_same_archive_only_advances_the_feed(self):
        storage = Storage({self.archive: DMG})
        self.publish(storage)
        self.assertEqual((storage.objects[self.archive], storage.objects[self.feed]), (DMG, FEED))

    def test_a_different_archive_at_the_versioned_url_is_never_replaced(self):
        storage = Storage({self.archive: b"another build", self.feed: b"previous feed"})
        with self.assertRaisesRegex(RuntimeError, "different disk image"):
            self.publish(storage)
        self.assertEqual(storage.objects, {self.archive: b"another build", self.feed: b"previous feed"})
        self.assertEqual(storage.puts(), [self.archive])

    def test_a_failed_archive_upload_leaves_the_feed_alone(self):
        storage = Storage({self.feed: b"previous feed"}, failing={self.archive: 403})
        with self.assertRaisesRegex(RuntimeError, "feed was not changed"):
            self.publish(storage)
        self.assertEqual(storage.objects, {self.feed: b"previous feed"})
        self.assertEqual(storage.puts(), [self.archive])

    def test_an_unverified_public_download_leaves_the_feed_alone(self):
        storage = Storage({self.feed: b"previous feed"})
        with self.assertRaisesRegex(RuntimeError, "feed was not changed"):
            upload(RECORD, DMG, FEED, ORIGIN, storage, lambda url: b"truncated")
        self.assertEqual(storage.objects[self.feed], b"previous feed")
        self.assertEqual(storage.puts(), [self.archive])

    def test_a_feed_that_did_not_go_live_is_reported(self):
        storage = Storage(failing={self.feed: 500})
        with self.assertRaisesRegex(RuntimeError, "Feed upload failed"):
            self.publish(storage)

    def test_update_objects_stay_beneath_the_mac_update_prefix(self):
        self.assertEqual(object_key(RECORD["url"], ORIGIN), self.archive)
        for url in (ORIGIN + "maps/sha256/abc/chillout.map", ORIGIN + "updates/mac/appcast.xml",
                    ORIGIN + "updates/mac/../../catalogs/testing/current.json",
                    ORIGIN + "updates/windows/1/setup.exe", "https://example.com/updates/mac/1/a.dmg"):
            with self.assertRaises(RuntimeError):
                object_key(url, ORIGIN)


class ReleaseAppTests(unittest.TestCase):
    settings = {"feed_url": ORIGIN + "updates/mac/testing/appcast.xml",
                "public_update_key": base64.b64encode(bytes(32)).decode(),
                "download_base_url": ORIGIN + "updates"}

    def info(self, **changes):
        return {"CFBundleIdentifier": BUNDLE_ID, "CFBundleShortVersionString": "0.6.0", "CFBundleVersion": "512.1",
                "LSMinimumSystemVersion": "26.0", "HaloSourceSHA": "a" * 40,
                **update_configuration(self.settings), **changes}

    def test_feed_entry_comes_from_the_release_app(self):
        self.assertEqual(feed_entry(self.info(), self.settings, "0.6.0"), {
            "version": "0.6.0", "build": "512.1", "minimum_macos": "26.0", "source_revision": "a" * 40})

    def test_a_build_that_could_not_update_again_is_not_published(self):
        # Installed copies read the feed and key from their own Info.plist.
        for changes in ({"SUFeedURL": None}, {"SUFeedURL": "https://example.com/appcast.xml"},
                        {"SUPublicEDKey": base64.b64encode(bytes([1]) * 32).decode()}):
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, "update feed"):
                feed_entry(self.info(**changes), self.settings, "0.6.0")

    def test_the_app_must_be_the_tagged_version(self):
        with self.assertRaisesRegex(RuntimeError, "version 0.6.0, not 0.6.1"):
            feed_entry(self.info(), self.settings, "0.6.1")

    def test_the_feed_never_moves_back_to_an_older_build(self):
        live = appcast({"version": "0.6.0", "build": "512.1", "minimum_macos": "26.0", "size": 1,
                        "signature": "", "url": RECORD["url"]})
        for build in ("512.1", "512.2", "600.1"):
            require_newer_than_feed(build, live)
        require_newer_than_feed("1.1", None)
        for build in ("511.3", "99.1"):
            with self.subTest(build=build), self.assertRaisesRegex(RuntimeError, "is older"):
                require_newer_than_feed(build, live)


class SignatureTests(unittest.TestCase):
    # RFC 8032 section 7.1, test 3.
    key = bytes.fromhex("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025")
    message = bytes.fromhex("af82")
    signature = bytes.fromhex(
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a")

    def test_only_the_public_keys_signature_of_these_bytes_is_accepted(self):
        self.assertTrue(verify(self.key, self.message, self.signature))
        changed = bytes([self.signature[0] ^ 1]) + self.signature[1:]
        other_key = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        for key, message, signature in ((self.key, self.message + b"\0", self.signature),
                                        (self.key, self.message, changed),
                                        (other_key, self.message, self.signature),
                                        (self.key, self.message, self.signature[:63])):
            self.assertFalse(verify(key, message, signature))

    def test_a_release_whose_signature_installed_apps_would_refuse_is_stopped(self):
        public = base64.b64encode(self.key).decode()
        require_signature(self.message, base64.b64encode(self.signature).decode(), public)
        for signature in (base64.b64encode(bytes(64)).decode(), "not base64", ""):
            with self.subTest(signature=signature), self.assertRaisesRegex(RuntimeError, "does not verify"):
                require_signature(self.message, signature, public)


class CheckedInConfigurationTests(unittest.TestCase):
    def test_feed_and_download_urls_live_on_the_reviewed_storage_origin(self):
        settings = json.loads(Path(CONFIG).read_text())
        origin = hosting.load_config()["public_base_url"]
        self.assertTrue(settings["feed_url"].startswith(settings["download_base_url"] + "/"))
        object_key(settings["feed_url"], origin)
        object_key(settings["download_base_url"] + "/mac/1/Halo-OG-0.0.0.dmg", origin)
        self.assertEqual(update_configuration(settings)["SUFeedURL"], settings["feed_url"])


if __name__ == "__main__":
    unittest.main()
