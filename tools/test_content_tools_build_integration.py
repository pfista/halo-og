"""Verify default reviewed-helper build wiring without compiling or fetching."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_build, macos_build


class BuildContentToolsTests(unittest.TestCase):
    def test_mac_default_fetches_but_explicit_and_optout_never_fetch(self):
        candidate = Path("reviewed-candidate")
        with patch.object(macos_build, "fetch_content_tools", return_value=candidate) as fetch:
            self.assertEqual(macos_build.resolve_content_tools(), candidate)
            fetch.assert_called_once_with("macos-arm64")
            fetch.reset_mock()
            self.assertEqual(macos_build.resolve_content_tools(candidate), candidate)
            self.assertIsNone(macos_build.resolve_content_tools(without=True))
            fetch.assert_not_called()

    def test_mac_dataless_cli_still_stages_helpers_and_plugin_only_never_fetches(self):
        candidate = Path("reviewed-candidate")
        with patch.object(macos_build.sys, "argv", ["macos_build", "--host-only", "--no-data-path"]), \
                patch.object(macos_build, "fetch_content_tools", return_value=candidate) as fetch, \
                patch.object(macos_build, "build_host"), patch.object(macos_build, "package") as package, \
                patch.object(macos_build.os, "chdir"):
            macos_build.main()
            fetch.assert_called_once_with("macos-arm64")
            self.assertIsNone(package.call_args.args[0])
            self.assertEqual(package.call_args.kwargs["content_tools"], candidate)
        with patch.object(macos_build.sys, "argv", ["macos_build", "--plugin-only"]), \
                patch.object(macos_build, "fetch_content_tools") as fetch, \
                patch.object(macos_build, "build_plugin") as build, patch.object(macos_build.os, "chdir"):
            macos_build.main()
            build.assert_called_once(); fetch.assert_not_called()

    def test_native_release_fetches_exact_platform_and_debug_android_do_not(self):
        candidate = Path("reviewed-candidate")
        with patch.object(ci_build, "fetch_content_tools", return_value=candidate) as fetch:
            for platform in ("linux", "windows"):
                self.assertEqual(ci_build.resolve_content_tools(platform, "release"), candidate)
                fetch.assert_called_with(platform + "-x86_64")
            fetch.reset_mock()
            self.assertIsNone(ci_build.resolve_content_tools("linux", "debug"))
            self.assertIsNone(ci_build.resolve_content_tools("android", "release"))
            self.assertIsNone(ci_build.resolve_content_tools("windows", "release", without=True))
            self.assertEqual(ci_build.resolve_content_tools("windows", "release", candidate), candidate)
            fetch.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "desktop"):
                ci_build.resolve_content_tools("android", "release", candidate)

    def test_native_release_stages_helpers_beside_collected_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("build/linux/halo", "port/third_party/extract-xiso/LICENSE.TXT",
                             "port/third_party/mbedtls/LICENSE", "port/third_party/miniupnpc/LICENSE",
                             "port/third_party/miniz/LICENSE"):
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"fixture")
            candidate = root / "reviewed-candidate"
            with patch.object(ci_build, "ROOT", root), patch.object(ci_build.sys, "argv", ["ci_build", "linux", "release"]), \
                    patch.object(ci_build, "run"), patch.object(ci_build, "fetch_content_tools", return_value=candidate), \
                    patch.object(ci_build, "stage_desktop_content_tools") as stage, patch.dict(os.environ):
                self.assertEqual(ci_build.main(), 0)
                stage.assert_called_once_with(root / "dist/halo-linux-release/content-tools", candidate)
                self.assertTrue((root / "dist/halo-linux-release/halo").is_file())

    def test_missing_reviewed_artifact_fails_before_game_build_or_packaging(self):
        with patch.object(ci_build.sys, "argv", ["ci_build", "windows", "release"]), \
                patch.object(ci_build, "fetch_content_tools", side_effect=RuntimeError("not reviewed")), \
                patch.object(ci_build, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "not reviewed"): ci_build.main()
            run.assert_not_called()
        with patch.object(macos_build.sys, "argv", ["macos_build", "--host-only"]), \
                patch.object(macos_build, "fetch_content_tools", side_effect=RuntimeError("not published")), \
                patch.object(macos_build, "build_host") as build, patch.object(macos_build.os, "chdir"):
            with self.assertRaisesRegex(RuntimeError, "not published"): macos_build.main()
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
