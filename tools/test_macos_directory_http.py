"""Exercise production Mac directory HTTPS with authored in-process responses."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "Foundation transport requires macOS")
class MacDirectoryHTTPTests(unittest.TestCase):
    def test_retry_after_and_bounded_error_responses(self):
        with tempfile.TemporaryDirectory(prefix="halo-directory-http-") as folder:
            executable = Path(folder) / "directory-http"
            compiled = subprocess.run([
                "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                "-Wno-unused-parameter", "-Iport/linux/src", "port/macos/tests/directory_http.m",
                "port/macos/native/HaloDirectoryHTTP.m", "-framework", "Foundation", "-o", str(executable),
            ], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS Mac directory Retry-After", result.stdout)


if __name__ == "__main__":
    unittest.main()
