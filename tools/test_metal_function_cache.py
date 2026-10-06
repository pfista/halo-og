"""Production exact-source cache CPU invariants and headless compiler proof."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FunctionCacheCpuTests(unittest.TestCase):
    def test_exact_contracts_bounds_and_retained_function_values(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ is required")
        with tempfile.TemporaryDirectory(prefix="metal-function-cache-cpu-") as temporary:
            binary = Path(temporary) / "cache"
            build = subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror",
                                    str(ROOT/"port/macos/tests/metal_function_cache.cpp"),"-o",str(binary)],
                                   capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run = subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertTrue(all(json.loads(run.stdout).values()))


@unittest.skipUnless(sys.platform == "darwin", "Headless Metal compilation requires macOS")
class FunctionCacheGpuTests(unittest.TestCase):
    def test_production_compilation_contracts_and_atomic_rejection(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ is required")
        with tempfile.TemporaryDirectory(prefix="metal-function-cache-gpu-") as temporary:
            folder=Path(temporary);memory=folder/"memory.o";binary=folder/"compiler"
            build=subprocess.run([shutil.which("clang"),"-O2","-DHALO_MACOS=1","-I"+str(ROOT/"port/android/include"),
                                  "-c",str(ROOT/"port/macos/host/host_memory.c"),"-o",str(memory)],
                                 capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            build=subprocess.run([compiler,"-std=c++17","-fobjc-arc","-O2","-Wall","-Wextra","-Werror",
                                  "-DHALO_MACOS=1","-I"+str(ROOT/"port/android/include"),
                                  str(ROOT/"port/macos/tests/metal_function_cache.mm"),
                                  str(ROOT/"port/macos/host/metal_draw_encoder.mm"),str(memory),
                                  "-framework","Foundation","-framework","Metal","-framework","QuartzCore","-o",str(binary)],
                                 capture_output=True,text=True,timeout=90)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            environment=os.environ.copy();environment["MTL_DEBUG_LAYER"]="1"
            run=subprocess.run([str(binary)],env=environment,capture_output=True,text=True,timeout=90)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn("Metal API Validation Enabled",run.stderr)
            self.assertNotIn("Validation Error",run.stderr)
            proof=json.loads(run.stdout)
            for name in ("exact_function_reuse","compile_contract_separation","failed_compile_retry",
                         "atomic_packet_rejection","shared_pipeline_retention","device_context_reset","identical_render_bytes"):
                self.assertTrue(proof[name])
            self.assertEqual(bytes.fromhex(proof["readback_hex"]),bytes((11,22,33,255))*16)
            proof["readback_sha256"]=hashlib.sha256(bytes.fromhex(proof.pop("readback_hex"))).hexdigest()
            print(json.dumps(proof))


if __name__=="__main__":
    unittest.main()
