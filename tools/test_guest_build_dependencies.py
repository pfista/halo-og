"""Exercise the emitted ARM guest compile rule and Ninja's real header tracking."""
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import android_build
from tools.ninja_syntax import Writer


ROOT = Path(__file__).resolve().parents[1]
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm/bin"))
CLANG = str(LLVM / "clang") if (LLVM / "clang").is_file() else shutil.which("clang")
NINJA = shutil.which("ninja")


def shell_argument(value):
    return subprocess.list2cmdline([str(value)]) if os.name == "nt" else shlex.quote(str(value))


def emitted_guest_rule():
    """Stop the real graph generator at its compile rule, without downloading/building."""
    class Recorded(Exception):
        pass

    class RecordingWriter(Writer):
        def rule(self, name, **options):
            if name == "android_guest_cc":
                self.guest_rule = options
                raise Recorded
            return super().rule(name, **options)

    writer = RecordingWriter(io.StringIO())
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="halo-guest-ndk-") as ndk:
        try:
            os.chdir(ROOT)
            with patch.object(android_build, "fetch_third_party"):
                try:
                    android_build.generate_android_build(writer, SimpleNamespace(android_ndk=ndk))
                except Recorded:
                    return writer.guest_rule
        finally:
            os.chdir(previous)
    raise AssertionError("guest compile rule was not emitted")


@unittest.skipUnless(CLANG and NINJA, "Clang and Ninja are required")
class GuestBuildDependencyTests(unittest.TestCase):
    def check_dependency_rebuild(self, adapter=False):
        options = emitted_guest_rule()
        with tempfile.TemporaryDirectory(prefix="halo-guest-deps-") as folder:
            directory = Path(folder)
            (directory / "probe.c").write_text('#include "page.inc"\nint probe(void) { return page_value(); }\n')
            include = directory / "page.inc"
            header = directory / "credits.h"
            include.write_text('#include "credits.h"\nstatic int page_value(void) { return CREDIT_COUNT; }\n')
            header.write_text('#define CREDIT_COUNT 19\n')
            compiler = shell_argument(CLANG)
            environment = os.environ.copy()
            if adapter:
                plugin = directory / "build/macos/guest_rebase.dylib"
                plugin.parent.mkdir(parents=True)
                shutil.copyfile(ROOT / "build/macos/guest_rebase.dylib", plugin)
                compiler = shell_argument(sys.executable) + " " + shell_argument(ROOT / "tools/macos_guest_cc.py")
                environment["HALO_MACOS_LLVM_BIN"] = str(LLVM)
            graph = io.StringIO()
            writer = Writer(graph)
            writer.variable("android_guest_cc", compiler)
            writer.variable("python", shell_argument(sys.executable))
            writer.variable("cflags", "--target=arm64_32-apple-watchos -mcpu=cortex-a53 -O0 -ffreestanding -fno-stack-protector")
            options["command"] = options["command"].replace("tools/android_asm_convert.py", shell_argument(ROOT / "tools/android_asm_convert.py"))
            writer.rule("android_guest_cc", **options)
            writer.build("probe.o", "android_guest_cc", "probe.c")
            (directory / "build.ninja").write_text(graph.getvalue())

            def ninja(*arguments):
                return subprocess.run([NINJA, *arguments], cwd=directory, env=environment,
                                      check=True, text=True, capture_output=True, timeout=60).stdout

            ninja("-d", "keepdepfile")
            depfile = (directory / "probe.o.d").read_text()
            self.assertEqual(depfile.split(":", 1)[0], "probe.o", depfile)
            dependencies = ninja("-t", "deps", "probe.o")
            for path in ("probe.c", "page.inc", "credits.h"):
                self.assertIn("    " + path + "\n", dependencies)
            self.assertIn("no work to do", ninja("-n"))
            original = (directory / "probe.o").read_bytes()

            # A nested header changes generated content, not just a timestamp.
            header.write_text('#define CREDIT_COUNT 20\n')
            self.assertIn("ANDROID CC probe.o", ninja("-n"))
            ninja("-d", "keepdepfile")
            updated = (directory / "probe.o").read_bytes()
            self.assertNotEqual(original, updated)
            self.assertIn("no work to do", ninja("-n"))

            # Included implementation files must also be retained by Ninja.
            include.write_text('#include "credits.h"\nstatic int page_value(void) { return CREDIT_COUNT + 1; }\n')
            self.assertIn("ANDROID CC probe.o", ninja("-n"))
            ninja("-d", "keepdepfile")
            self.assertNotEqual(updated, (directory / "probe.o").read_bytes())
            self.assertIn("no work to do", ninja("-n"))

    def test_darwin_assembly_dependencies_rebuild_final_object(self):
        self.check_dependency_rebuild()

    @unittest.skipUnless(sys.platform == "darwin" and (LLVM / "opt").is_file() and
                         (ROOT / "build/macos/guest_rebase.dylib").is_file(),
                         "built Mac guest rebase plugin is required")
    def test_macos_ir_adapter_dependencies_rebuild_final_object(self):
        self.check_dependency_rebuild(adapter=True)


if __name__ == "__main__":
    unittest.main()
