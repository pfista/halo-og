"""Network-free source-builder and trusted desktop-helper packaging checks."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from tools import community_toolchain as tools


class ToolchainTests(unittest.TestCase):
    def test_authoring_helpers_are_opt_in_and_desktop_trust_set_stays_small(self):
        self.assertEqual(tools.toolset_names("desktop"), ("extract", "build"))
        self.assertEqual(tools.TOOLS, ("extract", "build"))
        self.assertEqual(set(tools.toolset_names("authoring")),
                         {"extract", "build", "dependency", "convert", "refactor", "edit", "bludgeon"})
        for toolset in tools.TOOLSETS:
            options = tools.toolset_options(toolset)
            self.assertEqual(len(options), len(tools.OPTIONS))
            enabled = {option.removeprefix("-DINVADER_").removesuffix("=ON")
                       for option in options if option.endswith("=ON")}
            self.assertEqual(enabled, {name.upper() for name in tools.toolset_names(toolset)})
            self.assertIn("-DINVADER_EDIT_QT=OFF", options)

    def test_unknown_toolset_fails_before_creating_output(self):
        output = self.root / "candidate"
        with self.assertRaisesRegex(ValueError, "Unknown native toolset"):
            tools.build(output, toolset="arbitrary")
        self.assertFalse(output.exists())

    def authoring_source(self):
        source = self.root / "sources/invader"
        path = source / tools.STARTING_PROFILE_SOURCE
        path.parent.mkdir(parents=True)
        path.write_text("// fixture\n" + tools.STARTING_PROFILE_BEFORE + "\n")
        return source, path

    def test_authoring_patch_is_pinned_scoped_and_records_input_output_hashes(self):
        source, path = self.authoring_source()
        original = path.read_bytes()
        self.assertEqual(tools.apply_authoring_patches(source, "desktop"), [])
        self.assertEqual(path.read_bytes(), original)
        records = tools.apply_authoring_patches(source, "authoring")
        self.assertEqual(records[0]["sha256"], tools.sha256(tools.STARTING_PROFILE_PATCH))
        self.assertEqual(records[0]["source_sha256_before"], hashlib.sha256(original).hexdigest())
        self.assertEqual(records[0]["source_sha256_after"], tools.sha256(path))
        self.assertIn("find_thing(scenario.player_starting_profile, n.string_data)", path.read_text())
        converted = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "no longer applies"):
            tools.apply_authoring_patches(source, "authoring")
        self.assertEqual(path.read_bytes(), converted)

    def test_changed_authoring_patch_is_rejected_before_source_mutation(self):
        source, path = self.authoring_source()
        original = path.read_bytes()
        changed = self.root / "changed.patch"
        changed.write_bytes(b"different compiler decisions")
        with patch.object(tools, "STARTING_PROFILE_PATCH", changed):
            with self.assertRaisesRegex(RuntimeError, "differs from its pin"):
                tools.apply_authoring_patches(source, "authoring")
        self.assertEqual(path.read_bytes(), original)

    def test_authoring_finalization_requires_matching_unchanged_build_receipt(self):
        source, path = self.authoring_source()
        with self.assertRaisesRegex(RuntimeError, "original patched build receipt"):
            tools.review_build_receipt(self.root, "authoring")
        records = tools.apply_authoring_patches(source, "authoring")
        receipt = self.root / "toolset-build.json"
        receipt.write_text(json.dumps({"toolset": "authoring", "source_patches": records}))
        self.assertEqual(tools.review_build_receipt(self.root, "authoring"), records)
        with self.assertRaisesRegex(RuntimeError, "differs from the original"):
            tools.review_build_receipt(self.root, "desktop")
        path.write_text(path.read_text() + "\n// changed after build")
        with self.assertRaisesRegex(RuntimeError, "unchanged reviewed compiler repair"):
            tools.review_build_receipt(self.root, "authoring")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, entries):
        path = self.root / "input.tar"
        with tarfile.open(path, "w") as stream:
            for name, kind, data in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = "../../outside" if kind == tarfile.SYMTYPE else ""
                info.size = len(data) if kind == tarfile.REGTYPE else 0
                stream.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        return path

    def test_extract_source_archive_regular_only(self):
        archive = self.archive([("root/a/file", tarfile.REGTYPE, b"source"), ("root/b", tarfile.DIRTYPE, b"")])
        tools.extract_archive(archive, self.root / "safe")
        self.assertEqual((self.root / "safe/a/file").read_bytes(), b"source")
        self.assertTrue((self.root / "safe/b").is_dir())

    def test_archive_rejects_traversal_links_casefold_and_collisions_before_write(self):
        cases = [[("root/../../escape", tarfile.REGTYPE, b"x")],
                 [("root/link", tarfile.SYMTYPE, b"")],
                 [("root/a", tarfile.REGTYPE, b"a"), ("root/A", tarfile.REGTYPE, b"b")],
                 [("root/a", tarfile.REGTYPE, b"a"), ("root/a/b", tarfile.REGTYPE, b"b")],
                 [("root/a", tarfile.FIFOTYPE, b"")],
                 [("one/a", tarfile.REGTYPE, b"x"), ("two/b", tarfile.REGTYPE, b"y")]]
        for entries in cases:
            with self.subTest(entries=entries):
                with self.assertRaises(RuntimeError):
                    tools.extract_archive(self.archive(entries), self.root / "refused")
                self.assertFalse((self.root / "refused").exists())

    def test_cached_dependency_bytes_are_checked_before_build(self):
        cache = self.root / "cache"
        cache.mkdir(); (cache / "dep.tar").write_bytes(b"changed")
        with patch.object(tools.urllib.request, "urlopen") as network:
            with self.assertRaisesRegex(RuntimeError, "SHA256"):
                tools.download_pinned("https://example.invalid/source", "0" * 64, self.root / "dep.tar", cache)
            network.assert_not_called()

    def test_build_creates_missing_parents_but_preserves_existing_output(self):
        output = self.root / "fresh-checkout/build/content-tools"
        with patch.object(tools, "host_platform", return_value="linux-x86_64"), \
                patch.object(tools.subprocess, "check_output", side_effect=RuntimeError("stop before build")):
            with self.assertRaisesRegex(RuntimeError, "stop before build"):
                tools.build(output)
            self.assertTrue((output / "sources").is_dir())
            self.assertTrue((output / "archives").is_dir())
            prior = output / "keep"
            prior.write_bytes(b"existing candidate")
            with self.assertRaises(FileExistsError):
                tools.build(output)
            self.assertEqual(prior.read_bytes(), b"existing candidate")

    def test_git_archive_cache_is_verified_without_using_working_files(self):
        cache = self.root / "cache"; cache.mkdir()
        archive = self.archive([("source/a", tarfile.REGTYPE, b"pinned source")])
        (cache / "invader.tar").write_bytes(archive.read_bytes())
        with patch.object(tools.subprocess, "run") as commands:
            tools.git_source("https://github.com/example/repo", "a" * 40, self.root / "source",
                             self.root / "invader.tar", cache, None, tools.sha256(archive))
            commands.assert_not_called()
        self.assertEqual((self.root / "source/a").read_bytes(), b"pinned source")

    def test_git_archive_cache_cannot_substitute_source(self):
        cache = self.root / "cache"; cache.mkdir(); (cache / "invader.tar").write_bytes(b"unreviewed")
        with self.assertRaisesRegex(RuntimeError, "reviewed pin"):
            tools.git_source("https://github.com/example/repo", "a" * 40, self.root / "source",
                             self.root / "invader.tar", cache, None, "0" * 64)
        self.assertFalse((self.root / "source").exists())

    def test_actual_git_source_archive_is_canonical_despite_windows_crlf_config(self):
        cache = self.root / "cache"
        repository = cache / "invader"; repository.mkdir(parents=True)
        subprocess.run(["git", "init", str(repository)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def git(*args, **kwargs):
            return subprocess.check_output(["git", "-C", str(repository), *args], **kwargs)
        git("config", "core.autocrlf", "true")
        blob = git("hash-object", "-w", "--stdin", input=b"source\nLF bytes\n").decode().strip()
        tree = git("mktree", input=("100644 blob " + blob + "\tREADME.txt\n").encode()).decode().strip()
        env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
               "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
               "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00"}
        commit = git("commit-tree", tree, input=b"fixture\n", env=env).decode().strip()
        canonical = git("-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "tar.umask=0002", "archive", "--format=tar", "--prefix=source/", commit)
        converted = git("archive", "--format=tar", "--prefix=source/", commit)
        self.assertNotEqual(canonical, converted)
        archive = self.root / "invader.tar"
        tools.git_source("https://example.invalid/never-fetched", commit, self.root / "invader", archive,
                         cache, None, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(archive.read_bytes(), canonical)
        self.assertEqual((self.root / "invader/README.txt").read_bytes(), b"source\nLF bytes\n")

    def test_corresponding_source_archive_is_stable_and_has_recipe(self):
        sources = self.root / "sources"; sources.mkdir()
        (sources / "license").write_bytes(b"license")
        script = self.root / "script.py"; script.write_bytes(b"# source recipe\n")
        for name in ("a.gz", "b.gz"):
            tools.source_archive(sources, {"tools/script.py": script}, self.root / name, 100)
        self.assertEqual((self.root / "a.gz").read_bytes(), (self.root / "b.gz").read_bytes())
        with tarfile.open(self.root / "a.gz") as stream:
            self.assertEqual(stream.getnames(), ["source/license", "source/recipe/tools/script.py"])
            self.assertTrue(all(x.mtime == 100 and x.uid == 0 and x.gid == 0 for x in stream.getmembers()))

    def test_macos_deployment_target_is_set_for_all_cmake_calls(self):
        options = tools.cmake_options(self.root / "prefix", "macos", tools.read_pins())
        self.assertIn("-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0", options)
        self.assertIn("-DCMAKE_OSX_ARCHITECTURES=arm64", options)
        self.assertEqual([x for x in tools.OPTIONS if x in ("EXTRACT", "BUILD")], ["BUILD", "EXTRACT"])

    def test_native_startup_uses_supported_info_flag_without_assets_or_unbounded_wait(self):
        helper = self.root / "build/invader-extract"
        helper.parent.mkdir()
        def run(command, **options):
            self.assertEqual(command, [str(helper), "--info"])
            self.assertTrue(options["check"])
            self.assertEqual(options["timeout"], 30)
            self.assertTrue(options["capture_output"])
            self.assertEqual(list(Path(options["cwd"]).iterdir()), [])
            return subprocess.CompletedProcess(command, 0, b"Invader 0.55.0.unknown\n\nCredits\n", b"")
        with patch.object(tools.subprocess, "run", side_effect=run):
            record = tools.smoke_native_helper(helper, "extract")
        self.assertEqual(record, {"argument": "--info", "exit_code": 0, "version": "Invader 0.55.0.unknown"})
        self.assertEqual(list(self.root.iterdir()), [helper.parent])

    def test_native_startup_refuses_failure_timeout_missing_version_and_oversized_output(self):
        helper = self.root / "build/invader-build"
        helper.parent.mkdir()
        for failure in (subprocess.CalledProcessError(1, [str(helper)]), subprocess.TimeoutExpired([str(helper)], 30)):
            with self.subTest(failure=type(failure).__name__), patch.object(tools.subprocess, "run", side_effect=failure), self.assertRaises(type(failure)):
                tools.smoke_native_helper(helper, "build")
        for stdout, stderr in ((b"", b""), (b"unexpected program\n", b""), (b"Invader " + b"x" * 32768, b""),
                               (b"Invader 0.55\n", b"x" * 32769)):
            with self.subTest(size=(len(stdout), len(stderr))), patch.object(tools.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout, stderr)), self.assertRaises(RuntimeError):
                tools.smoke_native_helper(helper, "build")
        self.assertEqual(list(self.root.iterdir()), [helper.parent])

    def test_unreviewed_runtime_dependency_is_named_but_still_refused(self):
        for consumer, header, imports in (
                ("linux", "Advanced Micro Devices X86-64", "Shared library: [unreviewed.so]"),
                ("windows", "architecture: i386:x86-64", "DLL Name: unreviewed.dll")):
            with self.subTest(consumer=consumer), \
                    patch.object(tools.subprocess, "check_output", side_effect=[header, imports]):
                with self.assertRaisesRegex(RuntimeError, "unbundled.*unreviewed"):
                    tools.inspect_binary(self.root / "candidate", consumer)

    def test_linux_system_loader_allowed_but_dynamic_zlib_still_refused(self):
        imports = "\n".join("Shared library: [" + name + "]" for name in
                            ("libstdc++.so.6", "libm.so.6", "libgcc_s.so.1", "libc.so.6", "ld-linux-x86-64.so.2"))
        with patch.object(tools.subprocess, "check_output", side_effect=["Advanced Micro Devices X86-64", imports]):
            libraries, _ = tools.inspect_binary(self.root / "candidate", "linux")
        self.assertIn("ld-linux-x86-64.so.2", libraries)
        with patch.object(tools.subprocess, "check_output", side_effect=["Advanced Micro Devices X86-64", imports + "\nShared library: [libz.so.1]"]), \
                self.assertRaisesRegex(RuntimeError, "unbundled.*libz.so.1"):
            tools.inspect_binary(self.root / "candidate", "linux")

    def test_windows_crt_is_checked_from_actual_headers_not_configure_substrings(self):
        with patch.object(tools.subprocess, "check_output", side_effect=["x86_64-w64-mingw32\n", "#define __MSVCRT_VERSION__ 0x700\n"]):
            self.assertEqual(tools.verify_windows_compiler(), "0x700")
        for target, macros in (("x86_64-w64-mingw32", "#define _UCRT\n#define __MSVCRT_VERSION__ 0xE00\n"),
                               ("x86_64-w64-mingw32", "#define __MSVCRT_VERSION__ 0x1400\n"),
                               ("x86_64-pc-cygwin", "#define __MSVCRT_VERSION__ 0x700\n"),
                               ("x86_64-w64-mingw32", "")):
            with self.subTest(target=target, macros=macros), \
                    patch.object(tools.subprocess, "check_output", side_effect=[target, macros]), \
                    self.assertRaisesRegex(RuntimeError, "MSVCRT headers"):
                tools.verify_windows_compiler()

    def test_windows_static_runtime_notices_are_delivered_and_required(self):
        prefix = self.root / "compiler"; output = self.root / "notices"; output.mkdir()
        for relative in ("gcc/COPYING3", "gcc/COPYING.RUNTIME", "crt/COPYING",
                         "crt/COPYING.MinGW-w64-runtime.txt", "crt/COPYING.MinGW-w64.txt", "libwinpthread/COPYING"):
            path = prefix / "share/licenses" / relative
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(relative.encode())
        tools.windows_runtime_notices(prefix, output)
        self.assertEqual(len(list(output.iterdir())), 6)
        self.assertEqual((output / "GCC-COPYING.RUNTIME.txt").read_bytes(), b"gcc/COPYING.RUNTIME")
        (prefix / "share/licenses/crt/COPYING").unlink()
        with self.assertRaisesRegex(RuntimeError, "notice is missing"):
            tools.windows_runtime_notices(prefix, output)

    def fixture_platform(self, consumer="linux"):
        pins = tools.read_pins()
        key = consumer + "-x86_64"
        selected = pins["platforms"][key]
        toolchain = self.root / "toolchain"; (toolchain / "build").mkdir(parents=True)
        selected["binaries"] = {}
        binaries = {}
        for name in tools.TOOLS:
            filename = "invader-" + name + (".exe" if consumer == "windows" else "")
            path = toolchain / "build" / filename
            path.write_bytes(("native " + name).encode())
            selected["binaries"][name] = tools.sha256(path)
            binaries[name] = {"sha256": tools.sha256(path)}
        archive = toolchain / "halo-content-tools-source.tar.gz"; archive.write_bytes(b"corresponding source")
        licenses = toolchain / "Licenses"; licenses.mkdir(); (licenses / "GPL-3.0.txt").write_bytes(b"license")
        manifest = {name: pins[name] for name in ("schema", "invader_repository", "invader_commit", "riat_repository", "riat_commit", "rust_version", "compatible_package_producers")}
        manifest.update({"consumer_platform": consumer, "architecture": "x86_64", "fresh_ci_ready": False,
                         "binaries": binaries, "corresponding_source": {"file": archive.name, "size": archive.stat().st_size, "sha256": tools.sha256(archive)},
                         "notices_sha256": {"GPL-3.0.txt": tools.sha256(licenses / "GPL-3.0.txt")}})
        selected["corresponding_source_sha256"] = manifest["corresponding_source"]["sha256"]
        selected["license_manifest_sha256"] = hashlib.sha256(json.dumps(manifest["notices_sha256"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        (toolchain / "source-manifest.json").write_text(json.dumps(manifest))
        return pins, toolchain, manifest

    def test_stage_uses_platform_native_suffix_and_explicit_producer_allowlist(self):
        for consumer in ("linux", "windows"):
            with self.subTest(consumer=consumer), tempfile.TemporaryDirectory(dir=self.root) as temp:
                prior = self.root; self.root = Path(temp)
                try:
                    pins, toolchain, _ = self.fixture_platform(consumer)
                    with patch.object(tools, "read_pins", return_value=pins), patch.object(tools, "host_platform", return_value=consumer + "-x86_64"), patch.object(tools, "inspect_binary", return_value=(["system"], "minimum")):
                        destination = tools.stage_desktop_content_tools(self.root / "content-tools", toolchain)
                    record = json.loads((destination / "ContentTools.json").read_text())
                    self.assertEqual(record["compatible_package_producers"], pins["compatible_package_producers"])
                    self.assertEqual(record["consumer_platform"], consumer)
                    for name in tools.TOOLS:
                        filename = "invader-" + name + (".exe" if consumer == "windows" else "")
                        self.assertEqual(record["binaries"][name]["bundled_sha256"], tools.sha256(destination / filename))
                finally:
                    self.root = prior

    def test_candidate_manifest_does_not_automatically_trust_its_hashes(self):
        pins, toolchain, manifest = self.fixture_platform()
        manifest["binaries"]["extract"]["sha256"] = "0" * 64
        (toolchain / "source-manifest.json").write_text(json.dumps(manifest))
        with patch.object(tools, "read_pins", return_value=pins), patch.object(tools, "host_platform", return_value="linux-x86_64"), patch.object(tools, "inspect_binary", return_value=(["system"], "minimum")):
            with self.assertRaisesRegex(RuntimeError, "binary pin"):
                tools.stage_desktop_content_tools(self.root / "content-tools", toolchain)
        self.assertFalse((self.root / "content-tools").exists())

    def test_unreviewed_platform_cannot_be_packaged(self):
        with patch.object(tools, "host_platform", return_value="windows-x86_64"):
            with self.assertRaisesRegex(RuntimeError, "not been reviewed"):
                tools.stage_desktop_content_tools(self.root / "content-tools", self.root)

    def test_existing_packaged_helpers_are_preserved(self):
        pins, toolchain, _ = self.fixture_platform()
        destination = self.root / "content-tools"; destination.mkdir(); (destination / "prior").write_bytes(b"keep")
        with patch.object(tools, "read_pins", return_value=pins), patch.object(tools, "host_platform", return_value="linux-x86_64"), patch.object(tools, "inspect_binary", return_value=(["system"], "minimum")):
            with self.assertRaises(FileExistsError):
                tools.stage_desktop_content_tools(destination, toolchain)
        self.assertEqual((destination / "prior").read_bytes(), b"keep")

    def test_source_and_license_records_are_independently_pinned(self):
        pins, toolchain, manifest = self.fixture_platform()
        for field, replacement in (("corresponding_source", {"file": "halo-content-tools-source.tar.gz", "size": 20, "sha256": "0" * 64}),
                                   ("notices_sha256", {"GPL-3.0.txt": "0" * 64})):
            with self.subTest(field=field):
                changed = dict(manifest); changed[field] = replacement
                (toolchain / "source-manifest.json").write_text(json.dumps(changed))
                with patch.object(tools, "read_pins", return_value=pins), patch.object(tools, "host_platform", return_value="linux-x86_64"), patch.object(tools, "inspect_binary", return_value=(["system"], "minimum")):
                    with self.assertRaises(RuntimeError):
                        tools.stage_desktop_content_tools(self.root / "content-tools", toolchain)
                self.assertFalse((self.root / "content-tools").exists())


if __name__ == "__main__":
    unittest.main()
