"""Headless GPU proof of production packet storage reuse and ownership."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "Requires macOS Metal")
class PacketBufferTests(unittest.TestCase):
    def test_changing_packets_rejection_growth_and_context_reset(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("Requires clang++")
        with tempfile.TemporaryDirectory(prefix="metal-packet-buffer-") as temporary:
            folder = Path(temporary)
            memory = folder / "memory.o"
            binary = folder / "packet-buffer"
            built = subprocess.run([shutil.which("clang"), "-O2", "-DHALO_MACOS=1",
                                    "-I" + str(ROOT / "port/android/include"), "-c",
                                    str(ROOT / "port/macos/host/host_memory.c"), "-o", str(memory)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            built = subprocess.run([compiler, "-std=c++17", "-fobjc-arc", "-O2", "-Wall", "-Wextra", "-Werror",
                                    "-DHALO_MACOS=1", "-I" + str(ROOT / "port/android/include"),
                                    str(ROOT / "port/macos/tests/metal_packet_buffer.mm"),
                                    str(ROOT / "port/macos/host/metal_draw_encoder.mm"), str(memory),
                                    "-framework", "Foundation", "-framework", "Metal", "-framework", "QuartzCore",
                                    "-o", str(binary)], capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = os.environ.copy()
            environment["MTL_DEBUG_LAYER"] = "1"
            run = subprocess.run([str(binary)], env=environment, capture_output=True, text=True, timeout=90)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("Metal API Validation Enabled", run.stderr)
            self.assertNotIn("Validation Error", run.stderr)
            self.assertTrue(all(json.loads(run.stdout).values()))


if __name__ == "__main__":
    unittest.main()
