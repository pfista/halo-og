"""Offline timer pack checks: WAV bounds, immutable bytes, atomic staging and publication guards."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.import_performance_audio import CUES, canonical_wav
from tools import timer_audio_pack as pack
from tools import publish_timer_audio as publisher
from tools.publish_map_catalog import R2, Response, PublishError
from tools.test_publish_map_catalog import FakeHTTPS


def wav(rate=22050, channels=1, frames=16):
    return canonical_wav(rate, channels, b"\x12\x00" * frames * channels)


class TimerPackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        for cue in CUES:
            (self.source / (cue + ".wav")).write_bytes(wav())
        (self.source / "import-manifest.json").write_text('{"local_provenance":true}')
        self.output = self.root / "prepared"

    def prepared(self):
        return pack.prepare_pack(self.source, self.output)

    def test_exact_reviewed_cues_and_manifest_schema_without_import_provenance(self):
        prepared = self.prepared()
        self.assertEqual(len(CUES), 46)
        manifest = pack.validate_manifest(prepared.manifest)
        self.assertEqual(set(manifest), {"schema_version", "pack_id", "files"})
        self.assertEqual([entry["cue"] for entry in prepared.files], CUES)
        self.assertFalse((self.output / "import-manifest.json").exists())
        self.assertEqual(len(list(self.output.rglob("*.wav"))), 46)
        for entry in prepared.files:
            self.assertEqual(set(entry), pack.ENTRY_FIELDS)
            self.assertEqual(entry["file_bytes"], len(wav()))
            self.assertEqual((self.output / entry["object_key"]).read_bytes(), wav())
        self.assertEqual(pack.validate_prepared(self.output), prepared)

    def test_accepts_all_pcm_layouts_at_four_second_boundary(self):
        for channels in (1, 2):
            for rate in (22050, 44100):
                with self.subTest(channels=channels, rate=rate):
                    info = pack.validate_wav(wav(rate, channels, rate * 4))
                    self.assertEqual(info, {"sample_rate": rate, "channels": channels, "frames": rate * 4})
                    with self.assertRaises(PublishError):
                        pack.validate_wav(wav(rate, channels, rate * 4 + 1))

    def test_rejects_noncanonical_headers_lengths_formats_and_empty_data(self):
        mutations = [(0, b"RF64"), (8, b"OTHERfmt"), (12, b"JUNK"), (16, struct.pack("<I", 18)),
                     (20, struct.pack("<H", 3)), (22, struct.pack("<H", 3)),
                     (24, struct.pack("<I", 48000)), (28, struct.pack("<I", 1)),
                     (32, struct.pack("<H", 4)), (34, struct.pack("<H", 8)),
                     (36, b"LIST"), (40, struct.pack("<I", 1)), (4, struct.pack("<I", 1))]
        for offset, replacement in mutations:
            data = bytearray(wav())
            data[offset:offset + len(replacement)] = replacement
            with self.subTest(offset=offset), self.assertRaises(PublishError):
                pack.validate_wav(bytes(data))
        for data in (b"", wav(frames=0), wav() + b"junk", b"x" * (pack.MAX_WAV_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(PublishError):
                pack.validate_wav(data)
        data = bytearray(wav(channels=2))
        data.pop()
        struct.pack_into("<I", data, 4, len(data) - 8)
        struct.pack_into("<I", data, 40, len(data) - 44)
        with self.assertRaises(PublishError):
            pack.validate_wav(bytes(data))

    def test_manifest_rejects_duplicates_missing_unknown_fields_and_unsafe_keys(self):
        manifest = json.loads(self.prepared().manifest)
        for mutation in ("duplicate", "missing", "cue", "sha", "size", "key", "field", "top-field", "schema", "pack"):
            altered = copy.deepcopy(manifest)
            first = altered["files"][0]
            if mutation == "duplicate":
                altered["files"][1] = first
            elif mutation == "missing":
                altered["files"].pop()
            elif mutation == "cue":
                first["cue"] = "../outside"
            elif mutation == "sha":
                first["sha256"] = "a" * 63
            elif mutation == "size":
                first["file_bytes"] = True
            elif mutation == "key":
                first["object_key"] = "catalogs/testing/current.json"
            elif mutation == "field":
                first["approval"] = True
            elif mutation == "top-field":
                altered["author"] = "unreviewed"
            elif mutation == "schema":
                altered["schema_version"] = True
            else:
                altered["pack_id"] = "other"
            with self.subTest(mutation=mutation), self.assertRaises(PublishError):
                pack.validate_manifest(json.dumps(altered).encode())
        raw = self.output.joinpath("manifest.json").read_bytes()
        with self.assertRaisesRegex(PublishError, "duplicate key"):
            pack.validate_manifest(raw.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1'))
        with self.assertRaises(PublishError):
            pack.validate_manifest(b"{" * (pack.MAX_MANIFEST_BYTES + 1))

    def test_manifest_total_byte_limit_is_enforced(self):
        manifest = json.loads(self.prepared().manifest)
        for entry in manifest["files"]:
            entry["file_bytes"] = pack.MAX_WAV_BYTES
        with self.assertRaisesRegex(PublishError, "32 MiB"):
            pack.validate_manifest(json.dumps(manifest).encode())

    def test_missing_extra_nested_or_symlink_sources_never_stage_a_pack(self):
        first = self.source / (CUES[0] + ".wav")
        original = first.read_bytes()
        for mutation in ("missing", "extra", "directory", "symlink", "dangling", "bad-wav"):
            with self.subTest(mutation=mutation):
                extra = self.source / "unexpected.sound"
                if mutation == "missing":
                    first.unlink()
                elif mutation == "extra":
                    extra.write_text("never publish tags")
                elif mutation == "directory":
                    extra.mkdir()
                elif mutation in ("symlink", "dangling"):
                    first.unlink()
                    first.symlink_to(self.source / "import-manifest.json" if mutation == "symlink" else self.root / "absent")
                else:
                    first.write_bytes(b"invalid")
                with self.assertRaises(PublishError):
                    self.prepared()
                self.assertFalse(self.output.exists())
                if extra.is_dir():
                    extra.rmdir()
                elif extra.exists():
                    extra.unlink()
                if first.exists() or first.is_symlink():
                    first.unlink()
                first.write_bytes(original)

    def test_prepared_inventory_and_sha_are_checked(self):
        prepared = self.prepared()
        path = self.output / prepared.files[0]["object_key"]
        original = path.read_bytes()
        path.write_bytes(original[:-1] + b"X")
        with self.assertRaisesRegex(PublishError, "SHA-256"):
            pack.validate_prepared(self.output)
        path.write_bytes(original)
        extra = self.output / "permission.json"
        extra.write_text("local-only evidence belongs outside publish tree")
        with self.assertRaisesRegex(PublishError, "exactly"):
            pack.validate_prepared(self.output)
        extra.unlink()
        path.unlink()
        path.symlink_to(self.source / (CUES[0] + ".wav"))
        with self.assertRaises(PublishError):
            pack.validate_prepared(self.output)

    def test_source_and_output_parent_symlinks_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(PublishError):
            pack.prepare_pack(alias, self.output)
        with self.assertRaises(PublishError):
            pack.prepare_pack(self.source, alias / "output")

    def test_existing_output_and_racing_destination_are_preserved(self):
        self.output.mkdir()
        with self.assertRaises(PublishError):
            self.prepared()
        self.output.rmdir()
        original = pack.publish_directory
        def race(staged, destination):
            destination.mkdir()
            (destination / "keep").write_text("existing")
            original(staged, destination)
        with patch.object(pack, "publish_directory", side_effect=race), self.assertRaises(OSError):
            self.prepared()
        self.assertEqual((self.output / "keep").read_text(), "existing")
        self.assertEqual(list(self.root.glob(".prepared-*.partial")), [])

    def test_midwrite_and_atomic_rename_failures_leave_no_partial_destination(self):
        original = Path.open
        writes = 0
        def fail(path, *args, **kwargs):
            nonlocal writes
            if args and args[0] == "xb":
                writes += 1
                if writes == 3:
                    raise OSError("fixture disk failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail), self.assertRaises(OSError):
            self.prepared()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".prepared-*.partial")), [])
        with patch.object(pack, "publish_directory", side_effect=OSError("fixture rename failure")), self.assertRaises(OSError):
            self.prepared()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".prepared-*.partial")), [])


class TimerPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        source = self.root / "source"
        source.mkdir()
        for cue in CUES:
            (source / (cue + ".wav")).write_bytes(wav())
        self.prepared = pack.prepare_pack(source, self.root / "prepared")
        self.config = publisher.load_config()
        self.http = FakeHTTPS(self.config)
        self.r2 = R2(self.config, "b" * 32, "c" * 64, self.http)
        self.key = self.prepared.files[0]["object_key"]
        self.data = (self.prepared.directory / self.key).read_bytes()
        self.manifest_key = self.config["manifest_key"]
        self.progress = []

    def publish(self):
        publisher.publish(self.prepared, self.config, self.r2, self.http,
                          redistribution_approved=True, progress=self.progress.append)

    def writes(self):
        return [request for request in self.http.requests if request[0] == "PUT"]

    def test_default_and_single_flags_never_read_credentials_or_contact_network(self):
        for flags in ([], ["--redistribution-approved"], ["--publish"]):
            args = ["publisher", "--prepared", str(self.prepared.directory), *flags]
            with self.subTest(flags=flags), patch.object(publisher.sys, "argv", args), \
                    patch.object(publisher, "load_token") as token, patch.object(publisher, "HTTPS") as http, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if flags == ["--publish"]:
                    with self.assertRaises(SystemExit):
                        publisher.main()
                else:
                    publisher.main()
                token.assert_not_called()
                http.assert_not_called()
        with self.assertRaisesRegex(PublishError, "redistribution approval"):
            publisher.publish(self.prepared, self.config, self.r2, self.http)
        self.assertEqual(self.http.requests, [])

    def test_configuration_cannot_retarget_maps_or_another_origin(self):
        for field, value in (("manifest_key", "catalogs/testing/current.json"), ("bucket", "other"),
                             ("account_id", "a" * 32), ("public_base_url", "https://other.test/"),
                             ("schema_version", True)):
            changed = dict(self.config, **{field: value})
            path = self.root / "config.json"
            path.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaises(PublishError):
                publisher.load_config(path)

    def test_all_immutable_public_bytes_are_verified_before_conditional_manifest_write(self):
        self.publish()
        writes = self.writes()
        self.assertEqual(len(writes), 47)
        final = writes[-1]
        self.assertTrue(final[1].endswith("/" + self.manifest_key))
        self.assertEqual(final[2]["if-none-match"], "*")
        for entry, write in zip(self.prepared.files, writes[:-1]):
            self.assertEqual(write[2]["if-none-match"], "*")
            self.assertEqual(write[2]["content-type"], "audio/wav")
            self.assertIn("immutable", write[2]["cache-control"])
            public_index = next(index for index, request in enumerate(self.http.requests)
                                if request[1] == self.config["public_base_url"] + entry["object_key"])
            self.assertLess(public_index, self.http.requests.index(final))
        self.assertEqual(self.http.objects[self.manifest_key], self.prepared.manifest)
        self.assertFalse(any("catalogs/" in url or "/maps/" in url for _, url, _, _ in self.http.requests))

    def test_existing_objects_and_manifest_are_idempotent_and_etag_guarded(self):
        self.http.objects[self.manifest_key] = b"previous"
        self.publish()
        self.assertEqual(self.writes()[-1][2]["if-match"], FakeHTTPS.etag(b"previous"))
        self.http.requests.clear()
        self.publish()
        self.assertEqual(self.writes(), [])

    def test_conflicting_immutable_and_public_mismatch_preserve_previous_manifest(self):
        for failure in ("immutable", "public", "partial"):
            with self.subTest(failure=failure):
                self.http.objects = {self.manifest_key: b"previous"}
                self.http.requests.clear()
                self.http.public_bad.clear()
                key = self.key if failure != "partial" else self.prepared.files[10]["object_key"]
                if failure == "immutable":
                    self.http.objects[key] = b"different"
                else:
                    self.http.public_bad[key] = Response(200, {}, b"different")
                with self.assertRaisesRegex(PublishError, "manifest was not advanced"):
                    self.publish()
                self.assertEqual(self.http.objects[self.manifest_key], b"previous")
                self.assertFalse(any(url.endswith("/" + self.manifest_key) for _, url, _, _ in self.writes()))
                if failure == "partial":
                    self.assertGreaterEqual(len(self.writes()), 11)

    def test_manifest_race_is_never_overwritten(self):
        self.publish()
        self.http.objects[self.manifest_key] = b"previous"
        self.http.requests.clear()
        self.http.race = lambda key, objects: objects.update({key: b"competing manifest"})
        with self.assertRaisesRegex(PublishError, "changed during publication"):
            self.publish()
        self.assertEqual(self.http.objects[self.manifest_key], b"competing manifest")

    def test_changed_local_objects_or_inventory_fail_before_network(self):
        path = self.prepared.directory / self.key
        original = path.read_bytes()
        path.write_bytes(original[:-1] + b"X")
        with self.assertRaises(PublishError):
            self.publish()
        self.assertEqual(self.http.requests, [])
        path.write_bytes(original)
        (self.prepared.directory / "unlisted").write_text("extra")
        with self.assertRaises(PublishError):
            self.publish()
        self.assertEqual(self.http.requests, [])

    def test_lost_immutable_put_response_recovers_only_through_exact_readback(self):
        original = self.http.request
        def lose(method, url, **kwargs):
            result = original(method, url, **kwargs)
            if method == "PUT" and url.endswith("/" + self.key):
                raise PublishError("private fixture marker")
            return result
        with patch.object(self.http, "request", side_effect=lose):
            self.publish()
        self.assertEqual(len(self.writes()), 47)
        self.assertEqual(self.http.objects[self.manifest_key], self.prepared.manifest)

    def test_missing_lost_upload_is_bounded_and_never_advances_manifest(self):
        self.http.objects[self.manifest_key] = b"previous"
        original = self.http.request
        def lose(method, url, **kwargs):
            result = original(method, url, **kwargs)
            if method == "PUT" and url.endswith("/" + self.key):
                self.http.objects.pop(self.key)
                raise PublishError("private fixture marker")
            return result
        with patch.object(self.http, "request", side_effect=lose), self.assertRaises(PublishError) as error:
            self.publish()
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(len(self.writes()), 3)
        self.assertTrue(all(write[2]["if-none-match"] == "*" for write in self.writes()))
        self.assertEqual(self.http.objects[self.manifest_key], b"previous")

    def test_ambiguous_manifest_put_is_not_retried_or_claimed_rolled_back(self):
        original = self.http.request
        def lose(method, url, **kwargs):
            result = original(method, url, **kwargs)
            if method == "PUT" and url.endswith("/" + self.manifest_key):
                raise PublishError("private fixture marker")
            return result
        with patch.object(self.http, "request", side_effect=lose), self.assertRaisesRegex(PublishError, "may already have completed") as error:
            self.publish()
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(len(self.writes()), 47)
        self.assertEqual(self.http.objects[self.manifest_key], self.prepared.manifest)

    def test_postmanifest_public_failure_reports_partial_publication(self):
        self.http.public_bad[self.manifest_key] = Response(404, {}, b"")
        with self.assertRaisesRegex(PublishError, "R2 timer manifest matches.*public verification failed"):
            self.publish()
        self.assertEqual(self.http.objects[self.manifest_key], self.prepared.manifest)


if __name__ == "__main__":
    unittest.main()
