import struct
import unittest

from metal_roof_camera_replay import frustum_rows, llvm_strings, viewport_helper


class CapturedRoofReplayTests(unittest.TestCase):
    def test_original_row_product_and_column_major_storage(self):
        import numpy as np
        # Independent simple transform: translate(-3,-4,-5), then scaleXYZ.
        raw = bytearray(128)
        struct.pack_into("<13f", raw, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, -3, -4, -5)
        struct.pack_into("<16f", raw, 64, 2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 0, 0, -1, 1)
        rows, _ = frustum_rows(raw, {"world_to_view": 0, "projection_matrix": 64})
        expected = np.asarray([[2, 0, 0, -6], [0, 3, 0, -12], [0, 0, 4, -21], [0, 0, 0, 1]], dtype=np.float32)
        self.assertEqual(rows.tobytes(), expected.tobytes())
        self.assertEqual(struct.unpack("<16f", rows.T.tobytes()),
                         (2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, -6, -12, -21, 1))

    def test_original_pixel_offset_moves_positive_half_pixel_in_both_axes(self):
        scale = (320, -240, 16777215)
        ndc_delta = (.5/scale[0], .5/scale[1])
        self.assertEqual(320*ndc_delta[0], .5)
        self.assertEqual(-240*ndc_delta[1], .5)
        source = viewport_helper(scale, (320, 240, 0), scale, (320, 240, 0), 0)
        self.assertIn("float3(320.0f,-240.0f,16777215.0f)", source)
        self.assertIn("float3(0.5f,0.5f,0.0f)", source)
        self.assertIn("scaled_clip + clip_delta", source)
        self.assertNotIn("position.y = -", source)

    def test_exact_original_llvm_string_extent_and_hex_bytes(self):
        source = '@.str.1 = private unnamed_addr constant [4 x i8] c"x\\0Ay\\00", align 1'
        self.assertEqual(llvm_strings(source), {"@.str.1": "x\ny"})
        with self.assertRaises(ValueError):
            llvm_strings(source.replace("[4 x i8]", "[5 x i8]"))


if __name__ == "__main__":
    unittest.main()
