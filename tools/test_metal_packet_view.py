"""CPU proof that retained allocation slack cannot extend packet records."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PacketViewTests(unittest.TestCase):
    def test_current_extent_const_bytes_and_overflow_rejection(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("Requires clang++")
        with tempfile.TemporaryDirectory(prefix="halo-metal-packet-view-") as temporary:
            binary = Path(temporary) / "view"
            build = subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                    str(ROOT / "port/macos/tests/metal_packet_view.cpp"), "-o", str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("production packet logical extent checks passed", run.stdout)


if __name__ == "__main__":
    unittest.main()
