from pathlib import Path
import math
import unittest

from metal_roof_angle_prepare import camera_capture_header, camera_capture_source, camera_text

ROOT = Path(__file__).resolve().parents[1]


class AngleCameraPreparationTests(unittest.TestCase):
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

    def test_requested_pose_float_roundtrip_and_orthogonal_basis(self):
        rows = [[float(v) for v in row.split()] for row in camera_text([95.5, -159.5, 6.5, 2.3427739711, -0.707691043], 65).splitlines()]
        self.assertEqual(rows[0], [95.5, -159.5, 6.5])
        self.assertAlmostEqual(sum(a*b for a, b in zip(rows[1], rows[2])), 0, places=6)
        self.assertAlmostEqual(sum(a*a for a in rows[1]), 1, places=6)
        self.assertAlmostEqual(math.degrees(2*math.atan(math.tan(rows[3][0]/2)/(4/3))), 65, places=5)


if __name__ == "__main__":
    unittest.main()
