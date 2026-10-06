"""Compile the directory invite ABI for each native and guest target."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm@22/bin"))
CLANG = str(LLVM / "clang") if (LLVM / "clang").is_file() else shutil.which("clang")
TARGETS = ("i686-pc-windows-msvc", "i686-linux-gnu", "aarch64-linux-android",
           "arm64_32-apple-watchos", "arm64-apple-ios", "arm64-apple-macos")
PROBE = r'''#include "game_directory.h"
/* Directory input normalizes all accepted links into standard shared text.
   Delivery capacity is separate so native service fields keep their ABI. */
_Static_assert(sizeof(((struct halo_directory_game *)0)->invite) >=
    sizeof("halo://join/") + 64, "invite buffer truncates the host token");
_Static_assert(P2P_LINK_SIZE >= sizeof("halo-og-opence://join/") + 64,
    "delivery buffer truncates the private host token");
_Static_assert(__builtin_offsetof(struct halo_directory_game, player_count) == 208,
    "directory guest/native player fields moved");
_Static_assert(__builtin_offsetof(struct halo_directory_game, oddball_variant) == 240,
    "directory guest/native score fields moved");
_Static_assert(sizeof(struct halo_directory_game) == 244, "directory import ABI changed");
int invite_prefix_size(void) { return sizeof(P2P_INVITE_PREFIX) - 1; }
'''


@unittest.skipUnless(CLANG, "Clang required")
class InviteLayoutTests(unittest.TestCase):
    def test_complete_invite_and_directory_layout_on_all_targets(self):
        with tempfile.TemporaryDirectory(prefix="halo-invite-layout-") as folder:
            source = Path(folder) / "layout.c"
            source.write_text(PROBE)
            for target in TARGETS:
                with self.subTest(target=target):
                    subprocess.run([CLANG, "--target=" + target, "-std=c11", "-ffreestanding",
                        "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "port/linux/src"),
                        "-c", str(source), "-o", str(Path(folder) / (target + ".o"))],
                        check=True, capture_output=True, text=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
