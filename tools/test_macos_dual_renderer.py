"""Keep the normal Mac package's two renderer payloads paired and signed."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from tools import macos_build as build
from tools.macos_release import audit_bundle


class DualRendererTests(unittest.TestCase):
    def test_normal_build_selects_both_and_isolated_build_selects_one(self):
        for requested, expected in (([], ["angle", "metal"]),
                                    (["--renderer", "angle"], ["angle"]),
                                    (["--renderer", "metal"], ["metal"])):
            with self.subTest(requested=requested), ExitStack() as stack:
                calls = []
                stack.enter_context(patch("sys.argv", ["macos_build.py", "--build-only", *requested]))
                stack.enter_context(patch.object(build, "build_renderer", side_effect=lambda renderer, args: calls.append(renderer)))
                stack.enter_context(patch.object(build, "package"))
                stack.enter_context(patch.object(build, "BUILD", build.BUILD))
                stack.enter_context(patch.object(build, "RENDERER", build.RENDERER))
                build.main()
                self.assertEqual(calls, expected)

    def package(self, root, mode):
        inputs = root / "build/macos"
        native = root / "build/macos-metal"
        frameworks = root / "angle"
        sdl = root / "sdl"
        sparkle = root / "sparkle/Sparkle.framework"
        for directory in (inputs, native, sdl / "lib", sparkle / "Versions/B", root / "port/macos",
                          root / "port/assets/network"):
            directory.mkdir(parents=True, exist_ok=True)
        for directory, label in ((inputs, b"angle"), (native, b"metal")):
            (directory / "halo").write_bytes(label + b" host")
            (directory / "halo_guest.elf").write_bytes(label + b" guest")
        (sdl / "lib/libSDL3.0.dylib").write_bytes(b"synthetic SDL")
        (sparkle / "Sparkle").write_bytes(b"synthetic Sparkle")
        for name in ("EGL", "GLESv2"):
            binary = frameworks / f"{name}.xcframework/macos-arm64/lib{name}.framework/lib{name}"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"synthetic ANGLE library")
        (root / "port/macos/map-downloads.json").write_text("{}")
        (root / "port/macos/release-config.json").write_text("{}")
        (root / "port/assets/network/brokers.txt").write_text("fixture-broker.example:1883\n")
        app = root / "Halo OG.app"
        commands = []
        with ExitStack() as stack:
            for name, value in (("ROOT", root), ("BUILD", inputs), ("RENDERER", mode),
                                ("SDL", sdl), ("ANGLE", frameworks)):
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
        self.assertEqual((app / "Contents/Resources/brokers.txt").read_text(),
                         "fixture-broker.example:1883\n")
        return app, commands

    def test_dual_package_records_both_guests_and_signs_native_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, commands = self.package(Path(temporary), "dual")
            native = app / "Contents/MacOS/halo-metal"
            self.assertEqual(native.read_bytes(), b"metal host")
            info = (app / "Contents/Resources/BuildInfo.txt").read_text()
            for payload in (b"angle guest", b"metal guest"):
                self.assertIn(hashlib.sha256(payload).hexdigest(), info)
            self.assertIn("ANGLE (default), Native Metal (optional)", info)
            with (app / "Contents/Info.plist").open("rb") as stream:
                self.assertEqual(plistlib.load(stream)["CFBundleExecutable"], "halo")
            signs = [command for command in commands if command[0] == "codesign" and "--sign" in command]
            self.assertLess(signs.index(("codesign", "--force", "--sign", "-", str(native))),
                            signs.index(("codesign", "--force", "--sign", "-", str(app))))
            native_rewrites = [command for command in commands if command[0] == "install_name_tool" and command[-1] == str(native)]
            self.assertTrue(any("@executable_path/../Frameworks" in command for command in native_rewrites))
            self.assertFalse(any("libEGL" in " ".join(command) for command in native_rewrites))
            self.assertTrue(audit_bundle(app))
            (app / "Contents/Resources/halo_guest-metal.elf").unlink()
            with self.assertRaisesRegex(RuntimeError, "paired host and guest"):
                audit_bundle(app)

    def test_angle_package_keeps_old_payload_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            app, commands = self.package(Path(temporary), "angle")
            self.assertFalse((app / "Contents/MacOS/halo-metal").exists())
            self.assertFalse((app / "Contents/Resources/halo_guest-metal.elf").exists())
            self.assertTrue(audit_bundle(app))


if __name__ == "__main__":
    unittest.main()
