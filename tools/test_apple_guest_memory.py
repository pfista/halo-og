"""Pin mobile/Desktop guest address contracts and exercise their real link scripts.

The native host_memory fixture separately executes allocation and protection
against Darwin; these source-only tests also run when no Apple host is present.
"""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPILER = shutil.which("clang")
LINKER = ROOT / "build/macos/toolchain/bin/ld.lld"


class AppleGuestMemoryTests(unittest.TestCase):
    CASES = [
        (("HALO_ANDROID",), 0x88000000, 0x08000000, 1, "port/android/guest/guest.ld"),
        (("HALO_ANDROID", "HALO_MACOS", "HALO_IOS"), 0x88000000, 0x08000000,
         0x20001, "port/android/guest/guest.ld"),
        (("HALO_ANDROID", "HALO_MACOS"), 0xa0000000, 0x20000000,
         0x10002, "port/macos/guest.ld"),
    ]

    def compile_contract(self, defines, base, size, abi, folder):
        if not COMPILER:
            self.skipTest("Clang is required to compile the shared guest ABI")
        source = Path(folder) / "contract.c"
        object_file = Path(folder) / "contract.o"
        source.write_text(f'''
#include "halo_android_abi.h"
_Static_assert(HALO_GUEST_WINDOW_BASE == 0x80000000u, "window base");
_Static_assert(HALO_GUEST_WINDOW_SIZE == {size}u, "window extent");
_Static_assert(HALO_GUEST_IMAGE_BASE == {base}u, "image base");
_Static_assert(HALO_GUEST_IMAGE_BASE == HALO_GUEST_WINDOW_BASE + HALO_GUEST_WINDOW_SIZE, "no overlap");
_Static_assert(HALO_GUEST_ABI_VERSION == {abi}u, "host ABI");
__attribute__((section(".guest_header"))) const uint32_t __guest_header = HALO_GUEST_IMAGE_BASE;
''')
        result = subprocess.run([COMPILER, "--target=aarch64-linux-gnu", "-ffreestanding",
            "-I", str(ROOT / "port/android/include"), *[f"-D{name}=1" for name in defines],
            "-c", str(source), "-o", str(object_file)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return object_file

    def test_mobile_and_mac_contracts(self):
        for defines, base, size, abi, _ in self.CASES:
            with self.subTest(platform=defines), tempfile.TemporaryDirectory(prefix="halo-guest-abi-") as folder:
                self.compile_contract(defines, base, size, abi, folder)

    def test_mobile_and_mac_link_addresses(self):
        if not LINKER.exists():
            self.skipTest("The public LLVM linker is required to validate guest layout")
        for defines, base, size, abi, script in self.CASES:
            with self.subTest(platform=defines), tempfile.TemporaryDirectory(prefix="halo-guest-layout-") as folder:
                object_file = self.compile_contract(defines, base, size, abi, folder)
                image = Path(folder) / "contract.elf"
                result = subprocess.run([str(LINKER), "-m", "aarch64linux", "-static", "-nostdlib",
                    "-T", str(ROOT / script), str(object_file), "-o", str(image)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                raw = image.read_bytes()
                self.assertEqual(raw[:6], b"\x7fELF\x02\x01")
                entry, offset = struct.unpack_from("<QQ", raw, 24)
                stride, count = struct.unpack_from("<HH", raw, 54)
                segments = [struct.unpack_from("<IIQQQQQQ", raw, offset + i * stride)
                            for i in range(count)]
                loads = [s for s in segments if s[0] == 1]
                self.assertEqual(entry, base)
                self.assertEqual(min(s[3] for s in loads), base)
                self.assertLessEqual(max(s[3] + s[6] for s in loads), base + 0x08000000)


if __name__ == "__main__":
    unittest.main()
