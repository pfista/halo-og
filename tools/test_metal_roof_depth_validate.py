from pathlib import Path
import struct
import tempfile
import unittest

from metal_roof_depth_validate import comparison_fragment, make_depth_probe, prior_control_paths, verify_capture_payloads
from metal_roof_gpu_validate import sha

ROOT = Path(__file__).resolve().parents[1]


class DepthProbeSourceTests(unittest.TestCase):
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

    def test_prior_controls_and_raw_query_metadata_are_bound(self):
        paths = prior_control_paths(Path("/snapshot"), {"group": "pose-640x480", "surface": 5427})
        self.assertEqual(paths[-1].name, "pose-640x480-surface5427-lequal.png.json")
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "capture.png"
            payloads = ((".depth32", "depth_sha256", b"depth"),
                        (".bgra8", "color_bgra_sha256", b"color"),
                        (".visibility.u64", "visibility_sha256", struct.pack("<4Q", 0, 0, 0, 7)),
                        (".world-vp.f32", "world_vp_sha256", b"matrix"))
            data = {"roof_probe": {"mode": 4, "visibility": [{"accepted_samples": 7, "query_word_index": 3}]},
                    "roof_depth_measurement": {"query_word_count": 4}}
            for extension, key, value in payloads:
                path = Path(str(png) + extension)
                path.write_bytes(value)
                data["roof_probe"][key] = sha(path)
            verify_capture_payloads(png, data)
            data["roof_probe"]["visibility"][0]["accepted_samples"] = 8
            with self.assertRaisesRegex(ValueError, "actual GPU words"):
                verify_capture_payloads(png, data)


if __name__ == "__main__":
    unittest.main()
