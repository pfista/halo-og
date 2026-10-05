"""Offline fixtures for explicit, atomic optional timer-pack downloads."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import download_timer_audio as downloader
from tools import import_performance_audio as importer
from tools.publish_map_catalog import PublishError, Response


def fixture():
    wav = importer.canonical_wav(22050, 1, bytes(128))
    digest = hashlib.sha256(wav).hexdigest()
    entries = [{"cue": cue, "file_bytes": len(wav), "sha256": digest,
                "object_key": f"audio/timer/sha256/{digest}/{cue}.wav"} for cue in importer.CUES]
    manifest = json.dumps({"schema_version": 1, "pack_id": "performance-timer-v1", "files": entries}).encode()
    responses = {downloader.MANIFEST_URL: Response(200, {}, manifest)}
    responses.update({downloader.ORIGIN + entry["object_key"]: Response(200, {}, wav) for entry in entries})
    return wav, entries, responses


class FixtureHTTP:
    def __init__(self, responses, before=None):
        self.responses, self.before, self.requests = responses, before, []

    def request(self, method, url, *, headers, limit):
        if method != "GET" or headers.get("Accept-Encoding") != "identity" or not url.startswith(downloader.ORIGIN):
            raise AssertionError("Unexpected timer download request")
        self.requests.append((url, limit))
        if self.before:
            self.before(url)
        return self.responses.get(url, Response(404, {}, b""))


class DownloadTimerAudioTests(unittest.TestCase):
    def test_complete_pack_installs_all_cues_atomically(self):
        wav, entries, responses = fixture()
        with tempfile.TemporaryDirectory(prefix="timer-download-") as temporary:
            destination = Path(temporary).resolve() / "sounds/performance"
            http = FixtureHTTP(responses, lambda _: self.assertFalse(destination.exists()))
            self.assertEqual(downloader.download_pack(destination, http), destination)
            self.assertEqual(len(http.requests), 47)
            self.assertEqual({path.name for path in destination.iterdir()}, {cue + ".wav" for cue in importer.CUES} | {"download-manifest.json"})
            for cue in importer.CUES:
                self.assertEqual((destination / (cue + ".wav")).read_bytes(), wav)
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_last_file_failure_and_bad_hash_leave_no_partial_pack(self):
        for kind in ("missing", "hash", "pcm", "overflow"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix="timer-download-") as temporary:
                wav, entries, responses = fixture()
                url = downloader.ORIGIN + entries[-1]["object_key"]
                if kind == "missing":
                    del responses[url]
                else:
                    damaged = bytearray(wav)
                    damaged[20 if kind == "pcm" else 100] ^= 1
                    data = bytes(damaged) if kind != "overflow" else wav + b"xx"
                    responses[url] = Response(200, {}, data)
                destination = Path(temporary).resolve() / "sounds/performance"
                with self.assertRaises(PublishError):
                    downloader.download_pack(destination, FixtureHTTP(responses))
                self.assertFalse(destination.exists())
                self.assertEqual(list(destination.parent.iterdir()), [])

    def test_invalid_manifest_refuses_recording_requests(self):
        _, entries, responses = fixture()
        for files in (entries[:-1], entries[:-1] + [entries[0]]):
            responses[downloader.MANIFEST_URL] = Response(200, {}, json.dumps({"schema_version": 1, "pack_id": "performance-timer-v1", "files": files}).encode())
            with tempfile.TemporaryDirectory(prefix="timer-download-") as temporary:
                destination = Path(temporary).resolve() / "sounds/performance"
                http = FixtureHTTP(responses)
                with self.assertRaises(PublishError):
                    downloader.download_pack(destination, http)
                self.assertEqual(len(http.requests), 1)
                self.assertFalse(destination.parent.exists())

    def test_existing_directory_or_file_is_preserved_before_http(self):
        _, _, responses = fixture()
        with tempfile.TemporaryDirectory(prefix="timer-download-") as temporary:
            destination = Path(temporary).resolve() / "performance"
            destination.mkdir()
            sentinel = destination / "keep.wav"
            sentinel.write_bytes(b"user recording")
            http = FixtureHTTP(responses)
            with self.assertRaises(PublishError):
                downloader.download_pack(destination, http)
            self.assertEqual(sentinel.read_bytes(), b"user recording")
            self.assertEqual(http.requests, [])
            other = Path(temporary).resolve() / "file"
            other.write_bytes(b"existing file")
            with self.assertRaises(PublishError):
                downloader.download_pack(other, http)
            self.assertEqual(other.read_bytes(), b"existing file")
            self.assertEqual(http.requests, [])

    def test_symlink_destinations_and_parents_are_preserved(self):
        _, _, responses = fixture()
        with tempfile.TemporaryDirectory(prefix="timer-download-") as temporary:
            root = Path(temporary).resolve()
            outside = root / "outside"
            outside.mkdir()
            link = root / "link"
            link.symlink_to(outside, target_is_directory=True)
            dangling = root / "dangling"
            dangling.symlink_to(root / "missing", target_is_directory=True)
            http = FixtureHTTP(responses)
            for destination in (link, link / "performance", dangling):
                with self.assertRaises(PublishError):
                    downloader.download_pack(destination, http)
            self.assertEqual(http.requests, [])
            self.assertEqual(list(outside.iterdir()), [])
            self.assertTrue(dangling.is_symlink())

    def test_destination_racing_publication_wins(self):
        _, _, responses = fixture()
        with tempfile.TemporaryDirectory(prefix="timer-download-") as temporary:
            destination = Path(temporary).resolve() / "sounds/performance"
            original = downloader.publish_directory

            def race(staged, target):
                target.mkdir()
                (target / "keep.wav").write_bytes(b"racing user recording")
                original(staged, target)

            with patch.object(downloader, "publish_directory", side_effect=race):
                with self.assertRaises((OSError, ValueError)):
                    downloader.download_pack(destination, FixtureHTTP(responses))
            self.assertEqual((destination / "keep.wav").read_bytes(), b"racing user recording")
            self.assertEqual(list(destination.parent.iterdir()), [destination])


if __name__ == "__main__":
    unittest.main()
