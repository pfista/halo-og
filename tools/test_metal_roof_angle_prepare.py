"""Portable camera-pose checks for the roof investigation helper."""
import math
import unittest

from metal_roof_angle_prepare import camera_text


class AngleCameraPreparationTests(unittest.TestCase):
    def test_requested_pose_float_roundtrip_and_orthogonal_basis(self):
        rows = [[float(v) for v in row.split()] for row in camera_text([95.5, -159.5, 6.5, 2.3427739711, -0.707691043], 65).splitlines()]
        self.assertEqual(rows[0], [95.5, -159.5, 6.5])
        self.assertAlmostEqual(sum(a*b for a, b in zip(rows[1], rows[2])), 0, places=6)
        self.assertAlmostEqual(sum(a*a for a in rows[1]), 1, places=6)
        self.assertAlmostEqual(math.degrees(2*math.atan(math.tan(rows[3][0]/2)/(4/3))), 65, places=5)


if __name__ == "__main__":
    unittest.main()
