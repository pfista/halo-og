"""Synthetic CI fixtures exercise selection, integrity and publication guards."""

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import ci_build, testing_release as release


SHA = "a" * 40
TAG = "v0.3.0"
DATE = "2026-10-03T00:00:00Z"
CHANGELOG = {"previous_tag": "test-v0.3.0-net11-setup2", "previous_sha": "b" * 40,
             "commits": [{"sha": "c" * 40, "subject": "Fix first launch setup"},
                         {"sha": SHA, "subject": "Show version on the home menu"}]}
DESKTOP_BINARY = ("synthetic executable\0" + SHA + "\0" + DATE + "\0"
                  "https://api.github.com/repos/pfista/halo-og/releases?per_page=5\0"
                  "Halo OG update available\0Open download\0Stop checking\0").encode()


class FixtureAPI:
    def __init__(self, root):
        self.sha = SHA
        self.claimed = False
        self.version = "0.3.0"
        self.posts = []
        self.runs, self.artifacts, self.archives = {}, {}, {}
        for run_id, (workflow, outputs) in enumerate(release.WORKFLOWS.items(), 1):
            run = {"id": run_id, "head_sha": SHA, "head_branch": "main", "status": "completed",
                   "conclusion": "success", "event": "push", "path": ".github/workflows/" + workflow,
                   "repository": {"id": 42, "full_name": release.REPOSITORY},
                   "head_repository": {"id": 42, "full_name": release.REPOSITORY},
                   "created_at": "2026-10-03T00:00:00Z"}
            self.runs[workflow] = run
            for name in outputs:
                artifact_id = len(self.artifacts) + 10
                path = root / f"{artifact_id}.zip"
                if workflow == "macos-dmg.yml":
                    data = b"synthetic disk image"
                    files = {release.DMG: data, "README.txt": "Apple Silicon, macOS 26",
                             "BuildInfo.txt": "Source: " + SHA + "\n",
                             "SHA256SUMS": hashlib.sha256(data).hexdigest() + "  " + release.DMG + "\n"}
                elif "windows" in name:
                    files = {"halo.exe": DESKTOP_BINARY + name.encode() + b".zip", "SDL3.dll": b"synthetic dll"}
                elif "linux" in name:
                    files = {"halo": DESKTOP_BINARY + name.encode() + b".zip"}
                else:
                    files = {"app-release.apk": b"synthetic apk"}
                with zipfile.ZipFile(path, "w") as archive:
                    for filename, data in files.items():
                        archive.writestr(filename, data)
                artifact = {"id": artifact_id, "name": name, "expired": False,
                            "expires_at": "2099-01-01T00:00:00Z", "size_in_bytes": path.stat().st_size,
                            "digest": "sha256:" + release.digest(path),
                            "workflow_run": {"id": run_id, "head_sha": SHA, "head_branch": "main",
                                             "repository_id": 42, "head_repository_id": 42}}
                self.artifacts[name] = artifact
                self.archives[artifact_id] = path

    def get(self, path, *, missing_ok=False):
        if path == "git/ref/heads/main":
            return {"object": {"sha": self.sha}}
        if path == "git/commits/" + SHA:
            return {"sha": SHA, "committer": {"date": DATE}}
        if path.startswith(("git/ref/tags/", "releases/tags/")):
            return {"id": 1} if self.claimed else None
        if path.startswith("contents/"):
            if "halo_og_version.h" in path:
                return {"content": base64.b64encode(f'#define HALO_OG_VERSION "{self.version}"\n'.encode()).decode()}
            return {"content": base64.b64encode(b"#define HALO_PORT_NETWORK_VERSION 11\n").decode()}
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [copy.deepcopy(self.runs[path.split("/")[2]])]}
        if path.startswith("actions/runs/"):
            if "/artifacts?" in path:
                name = path.split("name=")[1].split("&")[0]
                return {"artifacts": [copy.deepcopy(self.artifacts[name])] if name in self.artifacts else []}
            return copy.deepcopy(next(run for run in self.runs.values() if run["id"] == int(path.split("/")[2])))
        if path.startswith("actions/artifacts/"):
            return copy.deepcopy(next(a for a in self.artifacts.values() if a["id"] == int(path.split("/")[2])))
        raise AssertionError("Unexpected API request: " + path)

    def download(self, artifact_id, destination):
        shutil.copyfile(self.archives[artifact_id], destination)

    def post(self, path, payload):
        self.posts.append((path, payload))
        if path == "git/tags":
            return {"tag": payload["tag"], "sha": "d" * 40, "message": payload["message"],
                    "object": {"type": payload["type"], "sha": payload["object"]}}
        if path == "git/refs":
            self.claimed = True
            return {"ref": payload["ref"], "object": {"type": "tag", "sha": payload["sha"]}}
        raise AssertionError("Unexpected write: " + path)


class TestingReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = FixtureAPI(self.root)
        self.directory = self.root / "candidate"
        changelog = patch.object(release, "generate_changelog", side_effect=lambda *args: copy.deepcopy(CHANGELOG))
        self.changelog = changelog.start()
        self.addCleanup(changelog.stop)

    def prepare(self):
        return release.prepare(self.api, release.REPOSITORY, SHA, TAG, self.directory)

    def test_same_source_candidate_has_protocol_and_verifies(self):
        record = self.prepare()
        self.assertEqual(record["network_protocol"], 11)
        self.assertEqual(record["source_date"], DATE)
        self.assertEqual(len(record["artifacts"]), 4)
        self.assertEqual(release.verify_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory), record)
        self.assertEqual({p.name for p in self.directory.iterdir()}, release.ASSETS | {"release-notes.md"})

    def test_release_download_table_and_setup_match_selected_source_and_tag(self):
        self.prepare()
        notes = (self.directory / "release-notes.md").read_text()
        source = f"https://github.com/{release.REPOSITORY}/blob/{SHA}"
        for path in ("README.md", "docs/playtesting.md", "port/linux/README.md#requirements"):
            self.assertIn(f"({source}/{path})", notes)
        self.assertIn("| Platform | Download |", notes)
        for asset in (release.DMG, "halo-windows-release.zip", "halo-linux-release.zip", "halo-android-release.zip"):
            self.assertIn(f"[{asset}](https://github.com/{release.REPOSITORY}/releases/download/{TAG}/{asset})", notes)
        self.assertIn("automatically download all 40 complete community maps", notes)
        self.assertIn("Android map setup remains manual", notes)
        self.assertIn("ad-hoc signed and unnotarized", notes)
        self.assertIn("Physical cross-platform and Internet/NAT play still need testing", notes)
        self.assertNotIn("Downloads default off", notes)
        self.assertNotIn(".hogpkg", notes)
        self.assertNotIn(".mapog", notes)
        self.assertNotIn("/blob/main/", notes)
        (self.directory / "release-notes.md").write_text(notes.replace(SHA, "b" * 40))
        with self.assertRaisesRegex(RuntimeError, "notes changed"):
            release.verify_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)

    def test_release_links_and_protocol_follow_the_selected_candidate(self):
        record = self.prepare()
        record["tag"] = "v0.3.1"
        record["network_protocol"] = 12
        notes = release.release_notes(record)
        self.assertIn("/releases/download/v0.3.1/" + release.DMG, notes)
        self.assertIn("network protocol **12**", notes)
        self.assertNotIn("/releases/download/" + TAG + "/", notes)
        self.assertNotIn("network protocol **11**", notes)

    def test_version_only_tags_and_compiled_version_must_agree(self):
        release.validate_inputs(release.REPOSITORY, SHA, TAG)
        for tag in ("test-v0.3.0-net11", "v0.3", "0.3.0", "v0.3.0-beta", "v00.3.0", "v0.3.0+build1"):
            with self.subTest(tag=tag), self.assertRaises(RuntimeError):
                release.validate_inputs(release.REPOSITORY, SHA, tag)
        self.api.version = "0.3.1"
        with self.assertRaisesRegex(RuntimeError, "must match HALO_OG_VERSION"):
            self.prepare()
        self.assertFalse(self.directory.exists())

    def test_tag_and_release_share_the_complete_commit_changelog(self):
        record = self.prepare()
        notes = (self.directory / "release-notes.md").read_text()
        annotation = release.tag_message(record)
        self.assertEqual(release.release_title(record), "Halo OG v0.3.0")
        for commit in CHANGELOG["commits"]:
            self.assertIn(commit["sha"][:7], notes)
            self.assertIn(commit["sha"][:7], annotation)
            self.assertIn(commit["subject"], notes)
            self.assertIn(commit["subject"], annotation)
        self.assertIn(CHANGELOG["previous_tag"], notes)
        self.assertIn(CHANGELOG["previous_tag"], annotation)
        self.assertIn(f'/compare/{CHANGELOG["previous_sha"]}...{SHA}', notes)
        self.assertEqual(notes.count("https://github.com/pfista/halo-og/commit/"), 1)

    def test_publication_creates_annotation_then_ref_and_versioned_release(self):
        record = self.prepare()
        with patch.object(release.subprocess, "run") as publish:
            release.publish_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        self.assertEqual(self.api.posts, [
            ("git/tags", {"tag": TAG, "message": release.tag_message(record), "object": SHA, "type": "commit"}),
            ("git/refs", {"ref": "refs/tags/" + TAG, "sha": "d" * 40})])
        command = publish.call_args.args[0]
        self.assertEqual(command[command.index("--title") + 1], "Halo OG v0.3.0")
        self.assertIn("--verify-tag", command)
        self.assertIn("--prerelease", command)
        self.assertIn("--latest=false", command)
        self.assertEqual(set(command[-len(release.ASSETS):]), {str(self.directory / name) for name in release.ASSETS})

    def test_changed_changelog_is_rejected_before_any_publication(self):
        self.prepare()
        record = json.loads((self.directory / "provenance.json").read_text())
        record["changelog"]["commits"].pop()
        (self.directory / "provenance.json").write_text(json.dumps(record))
        with patch.object(release.subprocess, "run") as publish, self.assertRaisesRegex(RuntimeError, "changelog"):
            release.publish_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        self.assertEqual(self.api.posts, [])
        publish.assert_not_called()

    def test_new_baseline_is_rejected_before_any_publication(self):
        self.prepare()
        self.changelog.side_effect = lambda *args: {**CHANGELOG, "previous_tag": "v0.2.9"}
        with patch.object(release.subprocess, "run") as publish, self.assertRaisesRegex(RuntimeError, "previous release"):
            release.publish_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        self.assertEqual(self.api.posts, [])
        publish.assert_not_called()

    def test_annotation_for_wrong_commit_cannot_be_referenced_or_released(self):
        record = self.prepare()
        response = {"tag": TAG, "sha": "d" * 40, "message": release.tag_message(record),
                    "object": {"type": "commit", "sha": "e" * 40}}
        with patch.object(self.api, "post", return_value=response) as write, \
                patch.object(release.subprocess, "run") as publish, self.assertRaisesRegex(RuntimeError, "annotated tag"):
            release.publish_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        write.assert_called_once()
        publish.assert_not_called()

    def test_main_advancement_during_verification_is_rechecked_before_writing(self):
        self.prepare()
        get = self.api.get
        reads = 0
        def advance(path, **kwargs):
            nonlocal reads
            if path == "git/ref/heads/main":
                reads += 1
                if reads == 2:
                    self.api.sha = "e" * 40
            return get(path, **kwargs)
        with patch.object(self.api, "get", side_effect=advance), patch.object(release.subprocess, "run") as publish, \
                self.assertRaisesRegex(RuntimeError, "latest main"):
            release.publish_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        self.assertEqual(self.api.posts, [])
        publish.assert_not_called()

    def test_oversized_complete_notes_are_rejected_instead_of_truncated(self):
        self.changelog.side_effect = lambda *args: {
            **CHANGELOG, "commits": [{"sha": f"{index:040x}", "subject": "Map fix " + "x" * 200}
                                      for index in range(100)]}
        with self.assertRaisesRegex(RuntimeError, "16 KiB"):
            self.prepare()
        self.assertFalse(self.directory.exists())

    def test_runs_from_other_source_branch_repository_or_event_are_rejected(self):
        run = self.api.runs["build.yml"]
        for field, value in (("head_sha", "b" * 40), ("head_branch", "other"), ("conclusion", "failure"),
                             ("event", "pull_request"), ("head_repository", {"full_name": "someone/fork"})):
            with self.subTest(field=field):
                changed = dict(run, **{field: value})
                with self.assertRaises(RuntimeError):
                    release.validate_run(changed, "build.yml", SHA)

    def test_missing_expired_and_wrong_source_artifacts_fail(self):
        del self.api.artifacts["halo-linux-release"]
        with self.assertRaisesRegex(RuntimeError, "Expected one"):
            self.prepare()
        artifact = self.api.artifacts["halo-windows-release"]
        for changes in ({"expired": True}, {"expires_at": "2000-01-01T00:00:00Z"},
                        {"workflow_run": {"id": 999}}, {"digest": ""}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                release.validate_artifact(dict(artifact, **changes), artifact["name"], self.api.runs["build.yml"], SHA)

    def test_downloaded_archive_hash_is_checked(self):
        self.api.artifacts["halo-macos-arm64-dmg"]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            self.prepare()

    def test_desktop_binaries_without_matching_notice_identity_cannot_be_published(self):
        for platform, executable in (("windows", "halo.exe"), ("linux", "halo")):
            for missing in (SHA, DATE, "Open download", "Stop checking",
                            "https://api.github.com/repos/pfista/halo-og/releases?per_page=5",
                            f"halo-{platform}-release.zip"):
                with self.subTest(platform=platform, missing=missing):
                    path = self.root / f"{platform}-missing.zip"
                    with zipfile.ZipFile(path, "w") as archive:
                        binary = DESKTOP_BINARY + f"halo-{platform}-release.zip".encode()
                        archive.writestr(executable, binary.replace(missing.encode(), b"disabled"))
                        if platform == "windows":
                            archive.writestr("SDL3.dll", b"fixture")
                    with self.assertRaisesRegex(RuntimeError, "discovery or source identity missing"):
                        release.check_platform_archive(path, f"halo-{platform}-release",
                                                       source_sha=SHA, source_stamp=DATE)

    def test_mac_buildinfo_and_disk_image_hash_are_checked(self):
        for filename, value, expected in (("BuildInfo.txt", "Source: wrong\n", "BuildInfo"),
                                          ("SHA256SUMS", "wrong\n", "checksum")):
            with self.subTest(filename=filename):
                archive_path = self.root / (filename + ".zip")
                with zipfile.ZipFile(self.api.archives[10]) as original, zipfile.ZipFile(archive_path, "w") as output:
                    for name in original.namelist():
                        output.writestr(name, value if name == filename else original.read(name))
                destination = self.root / filename
                destination.mkdir()
                with self.assertRaisesRegex(RuntimeError, expected):
                    release.collect_mac(archive_path, destination, SHA)

    def test_legacy_mac_filename_cannot_be_published_as_the_renamed_app(self):
        legacy = "Halo-CE-Universal-macos-arm64.dmg"
        archive_path = self.root / "legacy-mac.zip"
        with zipfile.ZipFile(self.api.archives[10]) as original, zipfile.ZipFile(archive_path, "w") as output:
            for name in original.namelist():
                data = original.read(name)
                if name == "SHA256SUMS":
                    data = data.replace(release.DMG.encode(), legacy.encode())
                output.writestr(legacy if name == release.DMG else name, data)
        self.directory.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Unexpected files"):
            release.collect_mac(archive_path, self.directory, SHA)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_restricted_and_escaping_archive_entries_are_rejected(self):
        for name in ("../escape", "/absolute", "maps/ui.map", "disc.ISO", "signing.p12"):
            with self.subTest(name=name):
                path = self.root / "unsafe.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(name, "synthetic")
                with self.assertRaises(RuntimeError):
                    release.validate_zip(path)

    def test_publication_recheck_refuses_advanced_main_claimed_tag_or_changed_asset(self):
        self.prepare()
        self.api.sha = "b" * 40
        with self.assertRaisesRegex(RuntimeError, "latest main"):
            release.verify_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        self.api.sha, self.api.claimed = SHA, True
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            release.verify_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)
        self.api.claimed = False
        (self.directory / release.DMG).write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "asset changed"):
            release.verify_candidate(self.api, release.REPOSITORY, SHA, TAG, self.directory)

    def test_fork_ci_cannot_offer_upstream_updates(self):
        environment = {"GITHUB_REPOSITORY": release.REPOSITORY, "GITHUB_REF": "refs/heads/main",
                       "GITHUB_RUN_NUMBER": "70", "HALO_BUILD_NUMBER": "999"}
        self.assertEqual(ci_build.update_build_number(environment), "0")
        environment["GITHUB_REPOSITORY"] = "cybersecurity/halo-ce-universal"
        self.assertEqual(ci_build.update_build_number(environment), "70")
        environment["GITHUB_REF"] = "refs/heads/feature"
        self.assertEqual(ci_build.update_build_number(environment), "0")

    def test_fork_android_apks_increment_install_code_without_enabling_updater(self):
        (self.root / ci_build.APKS["release"]).parent.mkdir(parents=True)
        (self.root / ci_build.APKS["release"]).write_bytes(b"fixture APK")
        for dependency in ("extract-xiso", "miniupnpc"):
            license = self.root / "port/third_party" / dependency / "LICENSE.TXT"
            if dependency == "miniupnpc":
                license = license.with_name("LICENSE")
            license.parent.mkdir(parents=True)
            license.write_text("fixture license")
        for number in ("70", "71"):
            commands = []
            def capture(command, cwd=None):
                commands.append((command, os.environ["HALO_BUILD_NUMBER"]))
            environment = {"GITHUB_REPOSITORY": release.REPOSITORY, "GITHUB_REF": "refs/heads/main",
                           "GITHUB_RUN_NUMBER": number, "HALO_BUILD_NUMBER": "999"}
            with self.subTest(number=number), patch.dict(os.environ, environment, clear=True), \
                    patch.object(ci_build, "ROOT", self.root), patch.object(ci_build, "run", capture), \
                    patch("sys.argv", ["ci_build.py", "android", "release"]):
                self.assertEqual(ci_build.main(), 0)
            gradle, updater_number = commands[-1]
            self.assertIn("-PhaloInstallBuildNumber=" + number, gradle)
            self.assertIn("assembleRelease", gradle)
            self.assertTrue(all(update == "0" for _, update in commands))
            self.assertEqual(updater_number, "0")
        for invalid in ("", "-1", "abc", "2100000001", "²"):
            with self.subTest(invalid=invalid):
                self.assertEqual(ci_build.android_install_build_number({"GITHUB_RUN_NUMBER": invalid}), "0")


if __name__ == "__main__":
    unittest.main()
