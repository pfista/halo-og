"""Publishing a Mac update must never replace an archive or advance the feed early."""
import hashlib
import json
from pathlib import Path
import unittest

from tools.macos_build import update_configuration
from tools.macos_release import CONFIG, object_key, upload
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
