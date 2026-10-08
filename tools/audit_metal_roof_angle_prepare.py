"""Opt-in source-preservation audit requiring the retained roof capture build."""
from pathlib import Path
import unittest

from metal_roof_angle_prepare import camera_capture_header, camera_capture_source

ROOT = Path(__file__).resolve().parents[1]


class AngleCameraCaptureAudit(unittest.TestCase):
    def test_raw_render_snapshot_extends_draw_without_changing_old_body(self):
        source = (ROOT / "build/metal-reference-20261004/ordered-frame-runtime/metal_frame_capture.h").read_text()
        instrumented = camera_capture_header(source)
        for line in source.splitlines():
            self.assertIn(line, instrumented)
        self.assertIn("metal_roof_camera_capture(file, metal_frame_blob)", instrumented)
        helper = camera_capture_source()
        self.assertIn("blob(file, &render.camera, sizeof(render.camera))", helper)
        self.assertIn("blob(file, &render.frustum, sizeof(render.frustum))", helper)
        self.assertIn("offsetof(struct render_camera, up)", helper)
        self.assertIn("offsetof(struct render_frustum, projection_matrix)", helper)
        self.assertNotIn("render.camera =", helper)


if __name__ == "__main__":
    unittest.main()
