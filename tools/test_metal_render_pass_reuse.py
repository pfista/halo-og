"""Headless GPU comparison of isolated, reused and cached production draws.

All modes use the same shared encoder and analytic attachment/query tests,
including fractional BGRA8 replacement blends and their following ADD boundary.
Their intermediate color/depth/stencil/query checkpoints must match byte for
byte. Reused modes create fewer passes; binding reuse submits fewer setters.
"""
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


@unittest.skipUnless(sys.platform == "darwin", "The headless Metal GPU test requires macOS")
class RenderPassReuseTests(unittest.TestCase):
    def test_exact_attachment_query_history_with_fewer_passes(self):
        compiler = shutil.which("clang++")
        if not compiler:
            self.skipTest("clang++ is required")
        with tempfile.TemporaryDirectory(prefix="halo-metal-pass-reuse-") as temporary:
            folder = Path(temporary)
            binary = folder / "draw-encoder"
            command = [compiler, "-std=c++17", "-fobjc-arc", "-O2", "-Wall", "-Wextra", "-Werror",
                       str(ROOT / "port/macos/host/metal_draw_encoder.mm"),
                       str(ROOT / "port/macos/tests/metal_draw_encoder.mm"),
                       "-framework", "Foundation", "-framework", "Metal", "-o", str(binary)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = os.environ.copy()
            environment["MTL_DEBUG_LAYER"] = "1"
            results = {}
            checkpoints = {}
            for mode in ("isolated", "reuse", "cached"):
                output = folder / (mode + ".bin")
                execution = subprocess.run([str(binary), mode, str(output)], env=environment,
                                           capture_output=True, text=True, timeout=90)
                self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
                self.assertNotIn("Validation Error", execution.stderr)
                results[mode] = json.loads(execution.stdout)
                self.assertTrue(results[mode]["complete"])
                self.assertTrue(results[mode]["color_depth_stencil_history"])
                self.assertTrue(results[mode]["state_and_resource_validation"])
                self.assertTrue(results[mode]["bgra8_replacement_history"])
                self.assertTrue(results[mode]["replacement_store_boundary"])
                self.assertEqual(results[mode]["replacement_blend_draws"], 6)
                self.assertEqual(results[mode]["replacement_blend_passes"], 6 if mode == "isolated" else 1)
                self.assertEqual(results[mode]["replacement_boundary_cases"], 2)
                self.assertEqual(results[mode]["replacement_boundary_passes"], 6 if mode == "isolated" else 4)
                self.assertEqual(results[mode]["pass_reuse"], mode != "isolated")
                self.assertEqual(results[mode]["binding_cache"], mode == "cached")
                checkpoints[mode] = output.read_bytes()
                self.assertEqual(len(checkpoints[mode]), results[mode]["checkpoint_bytes"])
            self.assertEqual(checkpoints["isolated"], checkpoints["reuse"])
            self.assertEqual(checkpoints["isolated"], checkpoints["cached"])
            self.assertGreater(len(checkpoints["reuse"]), 0)
            self.assertLess(results["reuse"]["render_passes"], results["isolated"]["render_passes"])
            self.assertEqual(results["cached"]["render_passes"], results["reuse"]["render_passes"])
            self.assertGreater(results["cached"]["binding_skips"], 0)
            self.assertLess(results["cached"]["binding_sets"], results["reuse"]["binding_sets"])
            print(json.dumps(dict(kind="native_metal_render_pass_reuse", api_validation=True,
                                  isolated_passes=results["isolated"]["render_passes"],
                                  reused_passes=results["reuse"]["render_passes"],
                                  checkpoint_bytes=len(checkpoints["reuse"]),
                                  checkpoint_sha256=hashlib.sha256(checkpoints["reuse"]).hexdigest(),
                                  cached_binding_sets=results["cached"]["binding_sets"],
                                  cached_binding_skips=results["cached"]["binding_skips"],
                                  reference_binding_sets=results["reuse"]["binding_sets"],
                                  replacement_blend_draws=results["reuse"]["replacement_blend_draws"],
                                  replacement_blend_passes=results["reuse"]["replacement_blend_passes"],
                                  replacement_store_boundary=True,
                                  identical_checkpoints=True)))


if __name__ == "__main__":
    unittest.main()
