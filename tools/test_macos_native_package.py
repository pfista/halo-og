"""Check the native Mac package's payload, dependency boundary, and signing order."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from tools import macos_build as build
from tools.macos_release import audit_bundle


class NativePackageTests(unittest.TestCase):
    def test_default_build_uses_canonical_path_and_isolated_build_uses_its_own(self):
        for requested, expected in (([], build.DEFAULT_BUILD), (["--renderer", "metal"], build.ROOT / "build/macos-metal")):
            with self.subTest(requested=requested), ExitStack() as stack:
                paths = []
                stack.enter_context(patch("sys.argv", ["macos_build.py", "--build-only", *requested]))
                stack.enter_context(patch.object(build, "build_game", side_effect=lambda args: paths.append(build.BUILD)))
                stack.enter_context(patch.object(build, "BUILD", build.BUILD))
                build.main()
                self.assertEqual(paths, [expected])

    def package(self, root):
        inputs = root / "build/macos"
        sdl = root / "sdl"
        sparkle = root / "sparkle/Sparkle.framework"
        for directory in (inputs, sdl / "lib", sparkle / "Versions/B", root / "port/macos"):
            directory.mkdir(parents=True, exist_ok=True)
        (inputs / "halo").write_bytes(b"metal host")
        (inputs / "halo_guest.elf").write_bytes(b"metal guest")
        (sdl / "lib/libSDL3.0.dylib").write_bytes(b"synthetic SDL")
        (sparkle / "Sparkle").write_bytes(b"synthetic Sparkle")
        (root / "port/macos/map-downloads.json").write_text("{}")
        (root / "port/macos/release-config.json").write_text("{}")
        app = root / "Halo OG.app"
        commands = []
        with ExitStack() as stack:
            for name, value in (("ROOT", root), ("BUILD", inputs), ("SDL", sdl)):
                stack.enter_context(patch.object(build, name, value))
            stack.enter_context(patch.object(build, "package_icon"))
            stack.enter_context(patch.object(build, "render_menu_icon"))
            stack.enter_context(patch.object(build, "setup_sparkle", return_value=sparkle))
            stack.enter_context(patch.object(build, "minimum_macos_version", return_value="14.0"))
            stack.enter_context(patch.object(build, "ci_source_identity", return_value=None))
            stack.enter_context(patch.object(build.subprocess, "check_output", return_value=""))
            stack.enter_context(patch.object(build, "run", side_effect=lambda *args: commands.append(tuple(map(str, args)))))
            build.package_into(app, None, sign_identity="-", release=False,
                               version=build.APP_VERSION, build="11")
        return app, commands

    def test_package_records_one_guest_and_signs_dependencies_before_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, commands = self.package(Path(temporary))
            host = app / "Contents/MacOS/halo"
            self.assertEqual(host.read_bytes(), b"metal host")
            self.assertEqual((app / "Contents/Resources/halo_guest.elf").read_bytes(), b"metal guest")
            info = (app / "Contents/Resources/BuildInfo.txt").read_text().splitlines()
            self.assertIn("Guest SHA-256: " + hashlib.sha256(b"metal guest").hexdigest(), info)
            self.assertIn("Renderer: native Metal", info)
            plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            self.assertEqual(plist["CFBundleExecutable"], "halo")
            self.assertEqual(plist["CFBundleIdentifier"], build.BUNDLE_ID)
            signed = [command[-1] for command in commands if command[0] == "codesign" and "--sign" in command]
            self.assertEqual(signed[-1], str(app))
            for dependency in ("libSDL3.0.dylib", "Sparkle.framework"):
                self.assertIn(str(app / "Contents/Frameworks" / dependency), signed)
            rewrites = [command for command in commands if command[0] == "install_name_tool" and command[-1] == str(host)]
            self.assertTrue(any("@executable_path/../Frameworks" in command for command in rewrites))
            self.assertTrue(audit_bundle(app))

    def test_audit_rejects_legacy_runtime_files_and_incomplete_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, _ = self.package(Path(temporary))
            contents = app / "Contents"
            for name in ("MacOS/halo-metal", "Resources/halo_guest-metal.elf", "Frameworks/libEGL.dylib",
                         "Frameworks/libGLESv2.dylib"):
                with self.subTest(name=name):
                    (contents / name).touch()
                    with self.assertRaises(RuntimeError):
                        audit_bundle(app)
                    (contents / name).unlink()
            (contents / "Resources/halo_guest.elf").unlink()
            with self.assertRaisesRegex(RuntimeError, "host and guest"):
                audit_bundle(app)


if __name__ == "__main__":
    unittest.main()
