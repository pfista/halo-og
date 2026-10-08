"""Bounded learned-source/PSO manifest codec, without a game or GPU."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WarmupCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang++")
        if not compiler:
            raise unittest.SkipTest("Requires clang++")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-metal-warmup-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / "cache"
        built = subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                                str(ROOT / "port/macos/tests/metal_warmup_cache.cpp"), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=60)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    def check_case(self, case):
        run = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("production warmup cache checks passed", run.stdout)

    def test_roundtrip_complete_state_and_fingerprint(self):
        self.check_case("roundtrip")

    def test_exact_source_stage_math_and_invariance_identity(self):
        self.check_case("contracts")

    def test_function_count_and_byte_limits(self):
        self.check_case("bounds")

    def test_pipeline_count_limit_and_duplicate_elision(self):
        self.check_case("pipelines")

    def test_truncation_corruption_version_and_atomic_rejection(self):
        self.check_case("malformed")

    def test_pipeline_contract_and_stage_validation(self):
        self.check_case("state")


if __name__ == "__main__":
    unittest.main()
