"""Network-free tests of the pinned helper ZIP writer and downloader."""
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import zipfile

from tools import community_tools_download as tools


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, headers=None, url="https://release-assets.githubusercontent.com/asset"):
        super().__init__(data)
        self.headers = headers or {}
        self.url = url

    def geturl(self):
        return self.url


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.key = "macos-arm64"
        self.pins = tools.community_toolchain.read_pins()
        self.addCleanup(patch.stopall)
        patch.object(tools.community_toolchain, "read_pins", return_value=self.pins).start()
        patch.object(tools, "CACHE", self.root / "build/downloads").start()
        self.config = self.root / "distribution.json"
        patch.object(tools, "DISTRIBUTION", self.config).start()
        self.directory = self.fixture(self.key)
        self.zip = self.root / "reviewed.zip"
        self.record = tools.archive_content_tools(self.key, self.directory, self.zip)
        self.write_config()

    def fixture(self, key):
        directory = self.root / ("candidate-" + key)
        (directory / "build").mkdir(parents=True)
        (directory / "Licenses").mkdir()
        selected = self.pins["platforms"][key]
        consumer = selected["consumer_platform"]
        binaries = {}
        for name in tools.TOOLS:
            data = (key + name + "reviewed executable fixture").encode()
            suffix = ".exe" if consumer == "windows" else ""
            (directory / "build" / ("invader-" + name + suffix)).write_bytes(data)
            binaries[name] = {"sha256": tools._digest(data), "architecture": selected["architecture"],
                              "system_libraries": ["reviewed-system"], "minimum_system": "reviewed-minimum"}
        source = b"full corresponding source fixture"
        (directory / tools.SOURCE).write_bytes(source)
        notice = b"full GPL license fixture"
        (directory / "Licenses/GPL-3.0.txt").write_bytes(notice)
        notices = {"GPL-3.0.txt": tools._digest(notice)}
        selected.update({"binaries": {name: record["sha256"] for name, record in binaries.items()},
                         "corresponding_source_sha256": tools._digest(source),
                         "license_manifest_sha256": tools._digest(json.dumps(notices, sort_keys=True, separators=(",", ":")).encode())})
        manifest = {key: self.pins[key] for key in ("schema", "invader_repository", "invader_commit", "riat_repository", "riat_commit", "rust_version", "compatible_package_producers")}
        manifest.update({"architecture": selected["architecture"], "consumer_platform": consumer,
                         "fresh_ci_ready": False, "binaries": binaries, "notices_sha256": notices,
                         "corresponding_source": {"file": tools.SOURCE, "sha256": tools._digest(source), "size": len(source)}})
        (directory / "source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return directory

    def write_config(self, record=None):
        self.config.write_text(json.dumps({"schema": 1, "platforms": {self.key: self.record if record is None else record}}), encoding="utf-8")

    def response(self, data=None, **kwargs):
        data = self.zip.read_bytes() if data is None else data
        response = Response(data, **kwargs)
        opener = patch.object(tools.urllib.request, "build_opener").start().return_value
        opener.open.return_value = response
        return opener

    def rewrite(self, name=None, data=b"extra", mode=None, directory=False):
        changed = self.root / "changed.zip"
        with zipfile.ZipFile(self.zip) as source, zipfile.ZipFile(changed, "w") as target:
            for item in source.infolist():
                if item.filename != name:
                    target.writestr(item, source.read(item))
            if name:
                item = zipfile.ZipInfo(name)
                item.create_system = 3
                item.external_attr = (mode or (stat.S_IFDIR | 0o755 if directory else stat.S_IFREG | 0o644)) << 16
                target.writestr(item, data)
        return changed

    def test_fixed_archive_layout_and_deterministic_bytes_without_execution(self):
        other = self.root / "same.zip"
        with patch.object(tools.community_toolchain.subprocess, "run", side_effect=AssertionError("no helper executes")):
            tools.archive_content_tools(self.key, self.directory, other)
        self.assertEqual(other.read_bytes(), self.zip.read_bytes())
        with zipfile.ZipFile(self.zip) as archive:
            self.assertEqual(set(archive.namelist()), {"build/invader-extract", "build/invader-build", "source-manifest.json", "Licenses/GPL-3.0.txt", tools.SOURCE})

    def test_linux_and_windows_have_fixed_native_filenames(self):
        for key in ("linux-x86_64", "windows-x86_64"):
            with self.subTest(key=key):
                directory = self.fixture(key)
                path = self.root / (key + ".zip")
                tools.archive_content_tools(key, directory, path)
                with zipfile.ZipFile(path) as archive:
                    suffix = ".exe" if key.startswith("windows") else ""
                    self.assertIn("build/invader-build" + suffix, archive.namelist())

    def test_existing_and_raced_archive_outputs_are_preserved(self):
        with self.assertRaises(FileExistsError):
            tools.archive_content_tools(self.key, self.directory, self.zip)
        output = self.root / "raced.zip"
        link = tools.os.link
        def race(source, destination):
            destination.write_bytes(b"winner")
            return link(source, destination)
        with patch.object(tools.os, "link", side_effect=race), self.assertRaises(FileExistsError):
            tools.archive_content_tools(self.key, self.directory, output)
        self.assertEqual(output.read_bytes(), b"winner")

    def test_manifest_cannot_authorize_unreviewed_bytes_source_or_producer(self):
        manifest_path = self.directory / "source-manifest.json"
        original = json.loads(manifest_path.read_text())
        for change in ("binary", "source", "producer", "platform", "license"):
            with self.subTest(change=change):
                manifest = json.loads(json.dumps(original))
                if change == "binary": manifest["binaries"]["extract"]["sha256"] = "0" * 64
                if change == "source": manifest["corresponding_source"]["sha256"] = "0" * 64
                if change == "producer": manifest["compatible_package_producers"] = []
                if change == "platform": manifest["consumer_platform"] = "windows"
                if change == "license": manifest["notices_sha256"]["GPL-3.0.txt"] = "0" * 64
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(RuntimeError):
                    tools.validate_content_tools(self.directory, self.key)
        manifest_path.write_text(json.dumps(original))

    def test_local_altered_binary_and_missing_or_extra_notices_refused(self):
        binary = self.directory / "build/invader-extract"
        prior = binary.read_bytes(); binary.write_bytes(b"unreviewed")
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            tools.validate_content_tools(self.directory, self.key)
        binary.write_bytes(prior)
        (self.directory / "Licenses/extra.txt").write_bytes(b"extra")
        with self.assertRaisesRegex(RuntimeError, "unknown or missing"):
            tools.validate_content_tools(self.directory, self.key)

    def test_malicious_zip_entries_are_rejected_before_extraction(self):
        for name, mode in (("../escape", None), ("build/../../escape", None), ("/absolute", None),
                           ("build\\escape", None), ("Licenses/NUL.txt", None), ("Licenses/trailing. ", None),
                           ("build/invader-build.exe", None), ("unknown", None),
                           ("build/link", stat.S_IFLNK | 0o777), ("build/", stat.S_IFLNK | 0o777),
                           ("Licenses/pipe", stat.S_IFIFO | 0o644), ("Licenses/GPL-3.0.TXT", None)):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                tools._extract_zip(self.rewrite(name, mode=mode), self.root / "rejected", self.key)
            self.assertFalse((self.root / "rejected").exists())

    def test_duplicate_zip_entries_and_file_directory_collision_refused(self):
        for name in ("build/invader-extract", "build"):
            path = self.root / "duplicates.zip"
            with zipfile.ZipFile(self.zip) as source, zipfile.ZipFile(path, "w") as target:
                for item in source.infolist(): target.writestr(item, source.read(item))
                with self.assertWarns(UserWarning) if "/" in name else _Nothing():
                    target.writestr(name, b"extra")
            with self.assertRaises(RuntimeError): tools._validate_zip(path, self.key)

    def test_zip_with_changed_pinned_bytes_refused_after_private_extraction(self):
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            tools._extract_zip(self.rewrite("build/invader-extract", b"altered"), self.root / "private", self.key)

    def test_unknown_platform_or_unreviewed_release_refused_without_network(self):
        with patch.object(tools.urllib.request, "build_opener") as network:
            for key in ("../escape", "windows-x86_64"):
                with self.subTest(key=key), self.assertRaises(RuntimeError): tools.fetch_content_tools(key)
            self.write_config({"url": self.record["url"], "sha256": None, "size": self.record["size"]})
            with self.assertRaises(RuntimeError): tools.fetch_content_tools(self.key)
            network.assert_not_called()

    def test_initial_release_url_is_exact_and_cannot_select_other_repo_or_tag(self):
        for url in ("https://github.com/other/repo/releases/download/content-tools-v1/content-tools-macos-arm64.zip",
                    self.record["url"].replace("content-tools-v1", "latest"), "https://objects.githubusercontent.com/asset"):
            with self.subTest(url=url):
                self.write_config({**self.record, "url": url})
                with self.assertRaisesRegex(RuntimeError, "release archive"):
                    tools.fetch_content_tools(self.key)

    def test_fetch_cache_reuse_is_offline_and_revalidates_all_bytes(self):
        opener = self.response(headers={"Content-Length": str(self.record["size"])})
        with patch.object(tools.community_toolchain.subprocess, "run", side_effect=AssertionError("never execute fetched helper")):
            fetched = tools.fetch_content_tools(self.key)
        if os.name != "nt":
            self.assertTrue((fetched / "build/invader-build").stat().st_mode & 0o111)
        opener.open.assert_called_once()
        opener.open.reset_mock()
        self.assertEqual(tools.fetch_content_tools(self.key), fetched)
        opener.open.assert_not_called()
        (fetched / "build/invader-build").write_bytes(b"tampered")
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            tools.fetch_content_tools(self.key)
        opener.open.assert_not_called()

    def test_download_status_encoding_length_hash_and_body_caps(self):
        cases = [(self.zip.read_bytes(), {"Content-Length": "-1"}, 200),
                 (self.zip.read_bytes(), {"Content-Length": str(self.record["size"] + 1)}, 200),
                 (self.zip.read_bytes(), {"Content-Encoding": "gzip"}, 200),
                 (self.zip.read_bytes(), {}, 404), (b"short", {}, 200),
                 (self.zip.read_bytes() + b"oversized", {}, 200),
                 (b"x" * self.record["size"], {}, 200)]
        for index, (data, headers, status) in enumerate(cases):
            with self.subTest(index=index):
                opener = self.response(data, headers=headers)
                opener.open.return_value.status = status
                with self.assertRaises(RuntimeError): tools._download(self.record, self.root / (str(index) + ".zip"))

    def test_failed_fetch_never_publishes_cache_or_leaves_private_files(self):
        self.response(b"wrong bytes")
        with self.assertRaises(RuntimeError): tools.fetch_content_tools(self.key)
        self.assertEqual(list((tools.CACHE / self.key).iterdir()), [])

    def test_concurrent_cache_is_verified_and_preserved(self):
        destination = tools.CACHE / self.key / self.record["sha256"]
        original = Path.mkdir
        def race(path, *args, **kwargs):
            if path == destination:
                shutil.copytree(self.directory, destination)
                raise FileExistsError("concurrent cache")
            return original(path, *args, **kwargs)
        self.response()
        with patch.object(Path, "mkdir", race):
            self.assertEqual(tools.fetch_content_tools(self.key), destination)
        self.assertEqual((destination / "build/invader-build").read_bytes(),
                         (self.directory / "build/invader-build").read_bytes())

    def test_corrupt_concurrent_cache_is_refused_without_deleting_winner(self):
        destination = tools.CACHE / self.key / self.record["sha256"]
        original = Path.mkdir
        def race(path, *args, **kwargs):
            if path == destination:
                shutil.copytree(self.directory, destination)
                (destination / "build/invader-build").write_bytes(b"winner must remain")
                raise FileExistsError("concurrent cache")
            return original(path, *args, **kwargs)
        self.response()
        with patch.object(Path, "mkdir", race), self.assertRaises(RuntimeError):
            tools.fetch_content_tools(self.key)
        self.assertEqual((destination / "build/invader-build").read_bytes(), b"winner must remain")

    def test_http_errors_and_read_timeouts_redact_signed_redirect_urls(self):
        opener = self.response()
        secret_url = "https://release-assets.githubusercontent.com/asset?signature=private"
        error = urllib.error.HTTPError(secret_url, 403, secret_url, {}, io.BytesIO())
        self.addCleanup(error.close)
        opener.open.side_effect = error
        with self.assertRaises(RuntimeError) as failed:
            tools._download(self.record, self.root / "error.zip")
        self.assertEqual(str(failed.exception), "Helper HTTPS download failed")
        opener.open.side_effect = None
        response = Response(b"")
        response.read = lambda *args: (_ for _ in ()).throw(TimeoutError(secret_url))
        opener.open.return_value = response
        with self.assertRaises(RuntimeError) as failed:
            tools._download(self.record, self.root / "timeout.zip")
        self.assertEqual(str(failed.exception), "Helper HTTPS download failed")

    def test_https_redirects_allow_only_explicit_github_asset_hosts(self):
        request = urllib.request.Request(self.record["url"])
        handler = tools._Redirects()
        for host in sorted(tools.REDIRECT_HOSTS):
            redirected = handler.redirect_request(request, None, 302, "found", {}, "https://" + host + "/asset")
            self.assertEqual(redirected.host, host)
        for url in ("http://github.com/a", "https://evil.invalid/a", "https://github.com.evil.invalid/a",
                    "https://user:secret@github.com/a", "https://github.com:8443/a"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                handler.redirect_request(request, None, 302, "found", {}, url)

    def test_final_response_url_is_checked_even_when_opener_returns_without_redirect(self):
        self.response(url="https://unapproved.invalid/asset")
        with self.assertRaisesRegex(RuntimeError, "approved HTTPS"):
            tools.fetch_content_tools(self.key)

    def test_json_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            tools._json(b'{"schema":1,"schema":1}')

    def test_linked_cache_parent_and_source_files_refused(self):
        target = self.root / "target"; target.mkdir()
        try:
            (self.root / "build").symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest("Symlink creation unavailable: " + str(error))
        self.response()
        with self.assertRaisesRegex(RuntimeError, "directory"):
            tools.fetch_content_tools(self.key)
        self.assertFalse(list(target.iterdir()))
        binary = self.directory / "build/invader-extract"
        data = binary.read_bytes(); binary.unlink()
        outside = self.root / "outside"; outside.write_bytes(data)
        binary.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "regular"):
            tools.validate_content_tools(self.directory, self.key)

    def test_expansion_metadata_limits_rejected(self):
        with patch.object(tools, "MAX_EXPANDED_BYTES", 1), self.assertRaisesRegex(RuntimeError, "expansion"):
            tools._validate_zip(self.zip, self.key)
        with patch.object(tools, "MAX_MANIFEST_BYTES", 1), self.assertRaisesRegex(RuntimeError, "manifest"):
            tools._validate_zip(self.zip, self.key)


class _Nothing:
    def __enter__(self): return self
    def __exit__(self, *args): return False


if __name__ == "__main__":
    unittest.main()
