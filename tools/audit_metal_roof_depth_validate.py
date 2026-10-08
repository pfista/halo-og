"""Opt-in source-preservation audit requiring the retained roof GPU probe."""
from pathlib import Path
import unittest

from metal_roof_depth_validate import comparison_fragment, make_depth_probe

ROOT = Path(__file__).resolve().parents[1]


class DepthProbeSourceAudit(unittest.TestCase):
    def test_original_shader_is_preserved_and_depth_feedback_avoided(self):
        source = (ROOT / "build/metal-poc-0.6/roof-gpu-prepared-attempt3/probe-main.mm").read_text()
        probe = make_depth_probe(source)
        self.assertIn("roofProbeMode == 6 ? roofGlyphWriteState", probe)
        self.assertIn("toTexture:roofDepthReference", probe)
        self.assertIn("[encoder setFragmentTexture:roofDepthReference atIndex:7]", probe)
        self.assertIn("contribution.depthAttachment.loadAction = MTLLoadActionLoad", probe)
        for line in source.splitlines():
            if "setDepthBias:" in line:
                self.assertIn(line, probe)

    def test_original_rgb_body_and_raster_z_comparison(self):
        source = (ROOT / "port/macos/metal-poc/TransparentBsp.metal").read_text()
        comparison = comparison_fragment(source)
        self.assertIn("opaqueDepth.read(uint2(in.position.xy))", comparison)
        self.assertIn("in.position.z <= opaqueZ", comparison)
        self.assertIn("float3 contribution = clamp(color.rgb*in.fade, 0.0, 1.0)", comparison)
        self.assertIn("texture0.sample(repeating, in.uv0)", comparison)


if __name__ == "__main__":
    unittest.main()
