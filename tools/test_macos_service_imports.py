"""Execute low-heap guest service calls through the Mac import ABI.

No game assets, graphics, HTTP, installation or personal preferences are used.
"""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm@22/bin"))


@unittest.skipUnless(sys.platform == "darwin" and platform.machine() == "arm64",
                     "Apple Silicon guest execution required")
class MacServiceImportTests(unittest.TestCase):
    def test_low_guest_heap_pointers_nulls_scalars_and_returns(self):
        self.assertTrue((ROOT / "build/macos/guest_rebase.dylib").is_file(),
                        "Build the existing Mac rebase plugin before this ABI probe")
        with tempfile.TemporaryDirectory(prefix="halo-service-imports-") as temporary:
            out = Path(temporary)
            env = dict(os.environ, HALO_MACOS_LLVM_BIN=str(LLVM))

            def run(*args):
                result = subprocess.run([str(arg) for arg in args], cwd=ROOT, env=env,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            run(sys.executable, "tools/macos_guest_cc.py", "--target=arm64_32-apple-watchos",
                "-mcpu=cortex-a53", "-O2", "-fno-stack-protector", "-fno-unwind-tables",
                "-fno-asynchronous-unwind-tables", "-S", "port/macos/tests/guest_services.c",
                "-o", out / "guest.darwin.s")
            run(sys.executable, "tools/android_asm_convert.py", out / "guest.darwin.s", out / "guest.s")
            run(sys.executable, "tools/android_imports.py", "--host-table", out / "imports.c",
                out / "imports.s", "port/macos/host_imports.list")
            for name in ("guest", "imports"):
                run(LLVM / "clang", "--target=aarch64-linux-android", "-c", out / (name + ".s"),
                    "-o", out / (name + ".o"))
            run(ROOT / "build/macos/toolchain/bin/ld.lld", "-m", "aarch64linux", "-static", "-nostdlib",
                "-Ttext=0x88000000", "-e", "guest_test", out / "guest.o", out / "imports.o",
                "-o", out / "guest.elf")
            symbols = {}
            for line in run(LLVM / "llvm-nm", out / "guest.elf").splitlines():
                fields = line.split()
                if len(fields) == 3:
                    symbols[fields[2]] = fields[0]
            run("clang", "-arch", "arm64", "-O2", "-Wall", "-Wextra", "-Wno-unused-parameter",
                "-DHALO_MACOS=1", "port/macos/tests/service_host.c",
                "port/macos/host/host_services.c", out / "imports.c", "-o", out / "service_host")
            output = run(out / "service_host", out / "guest.elf", symbols["__host_import_names"],
                         symbols["__host_import_table"], symbols["__host_import_count"])
            self.assertIn("guest service result=93 expected=93; native calls=6 expected=6", output)


@unittest.skipUnless(shutil.which("clang"), "clang required")
class IOSServiceStubTests(unittest.TestCase):
    def test_ios_host_services_are_unavailable_without_native_mac_dependencies(self):
        fixture = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
int host_halo_map_download_directory(char *, size_t);
int host_halo_map_download_request(const char *);
int host_halo_directory_http(const char *, const char *, const char *, const char *, char *, int, int *);
int main(void) {
    char output[32] = "unchanged";
    int status = 201;
    assert(host_halo_map_download_directory(output, sizeof(output)) == 0);
    assert(!strcmp(output, "unchanged"));
    assert(host_halo_map_download_directory(NULL, 0) == 0);
    assert(host_halo_map_download_request("downrush") == 0);
    assert(host_halo_map_download_request(NULL) == 0);
    assert(host_halo_directory_http("GET", "https://fixture.invalid", NULL, NULL,
                                   output, sizeof(output), &status) == -1);
    assert(status == 0 && !strcmp(output, "unchanged"));
    assert(host_halo_directory_http(NULL, NULL, NULL, NULL, NULL, 0, NULL) == -1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="halo-ios-service-stubs-") as temporary:
            out = Path(temporary)
            source = out / "stubs.c"
            source.write_text(fixture)
            executable = out / ("stubs.exe" if sys.platform == "win32" else "stubs")
            result = subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                                     "-Wno-unused-parameter", "-DHALO_MACOS=1", "-DHALO_IOS=1",
                                     str(source), str(ROOT / "port/macos/host/host_services.c"),
                                     "-o", str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
