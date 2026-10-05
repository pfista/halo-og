import tempfile
from pathlib import Path
import unittest

from metal_roof_gpu_validate import ROOT, make_probe_source, replace_once, sha, verify_bindings


class RoofProbePreparationTests(unittest.TestCase):
    def test_anchor_drift_fails_instead_of_rewriting_another_pass(self):
        for source in ("different", "anchor anchor"):
            with self.assertRaises(ValueError):
                replace_once(source, "anchor", "replacement")

    def test_exact_current_renderer_can_be_instrumented_without_bias_change(self):
        source = (ROOT / "port/macos/metal-poc/main.mm").read_text()
        probe = make_probe_source(source)
        self.assertIn("memset(roofVisibility.contents, 0, roofVisibility.length)", probe)
        self.assertIn("MTLVisibilityResultModeCounting offset:roofIndex * 8", probe)
        self.assertIn("roofProbeMode == 2) { [encoder endEncoding]; return; }", probe)
        self.assertIn("contribution.depthAttachment.loadAction = MTLLoadActionLoad", probe)
        for line in source.splitlines():
            if "setDepthBias:" in line:
                self.assertIn(line, probe)
        self.assertIn("options.fastMathEnabled = NO", probe)
        self.assertIn("options.preserveInvariance = YES", probe)

    def test_input_change_rejected_before_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_bytes(b"unchanged")
            bindings = {str(path): sha(path)}
            verify_bindings(bindings)
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify_bindings(bindings)


if __name__ == "__main__":
    unittest.main()
