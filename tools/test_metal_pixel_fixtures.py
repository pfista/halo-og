"""Independent reference arithmetic for generated pixel texture-stage fixtures."""
import math
import unittest

from metal_pixel_fixtures import (cube_nearest, cube_texture, depth_replace_fixtures, dot_mapped_bytes,
                                  reflect_vector, texture_stage_fixtures)


class TextureFixtureReferenceTests(unittest.TestCase):
    def test_cube_axes_and_face_spatial_orientation(self):
        t = cube_texture()
        # These explicit face/cell expectations test the reference projection,
        # rather than recomputing its sc/tc equation in the test.
        for direction, face, x, y in [((1, .25, -.625), 0, 3, 1),
                                       ((-1, .25, -.625), 1, 0, 1),
                                       ((.25, 1, -.625), 2, 2, 0),
                                       ((.25, -1, -.625), 3, 2, 3),
                                       ((.25, -.625, 1), 4, 2, 3),
                                       ((.25, -.625, -1), 5, 1, 3)]:
            expected = [17 + face * 31 + x * 11,
                        23 + face * 23 + y * 17,
                        31 + (x + y) * 19, 127 + face * 7]
            self.assertEqual(cube_nearest(t, direction), [v / 255 for v in expected])

    def test_signed_dot_mapping_boundaries_are_distinct(self):
        self.assertEqual(dot_mapped_bytes([0, 127, 128, 255], 0), [0, 127 / 255, 128 / 255])
        self.assertEqual(dot_mapped_bytes([0, 127, 128, 255], 1), [-128 / 127, -1 / 127, 0])
        self.assertEqual(dot_mapped_bytes([0, 127, 128, 255], 2), [.5 / 127.5, 1, -1])
        self.assertEqual(dot_mapped_bytes([0, 127, 128, 255], 3), [0, 1, -128 / 127])

    def test_reflection_uses_nonunit_normal_and_nonparallel_eye(self):
        self.assertEqual(reflect_vector([2, 0, 0], [.5, -.75, 1]), [.5, .75, -1])
        n, e = [.3, -.45, .8], [1, .25, -.625]
        once = reflect_vector(n, e)
        twice = reflect_vector(n, once)
        for actual, expected in zip(twice, e):
            self.assertAlmostEqual(actual, expected, places=14)
        self.assertNotEqual(once, e)

    def test_fixture_matrix_covers_required_dimensions_and_dot_chains(self):
        cases = list(texture_stage_fixtures())
        self.assertEqual(len(cases), 150)
        names = [f['name'] for _, f in cases]
        self.assertEqual(len(set(names)), len(names))
        self.assertTrue(any('dot-reflect-11' in n for n in names))
        self.assertTrue(any('dot-reflect-17' in n for n in names))
        kinds = {t['kind'] for _, f in cases for t in f['textures']}
        self.assertEqual(kinds, {0, 1, 2, 3})
        for key, f in cases:
            self.assertEqual(len(f['expected']), 4)
            self.assertTrue(all(math.isfinite(v) and 0 <= v <= 1 for v in f['expected']))
            modes = [key.texture_modes >> (5 * s) & 31 for s in range(4)]
            if modes[2] == 11:
                self.assertEqual(modes[1:4], [17, 11, 12])

    def test_depth_replacement_vectors_include_raw_d24_clip_and_attachment_state(self):
        cases = list(depth_replace_fixtures())
        self.assertEqual(len(cases), 36)
        self.assertEqual(len({f['name'] for _, f in cases}), 36)
        for key, f in cases:
            self.assertEqual(key.texture_modes, 0x54421)
            self.assertEqual(key.combiner_state[56], 0x110000)
            self.assertEqual(f['depth_contract'], 'raw_d24')
            self.assertTrue(math.isfinite(f['expected_depth']))
            self.assertGreaterEqual(f['expected_depth'], 0)
            self.assertLessEqual(f['expected_depth'], 1)
        valid = [f for _, f in cases if not f['discard']]
        self.assertTrue(any(f['expected_depth'] == 0 for f in valid))
        self.assertTrue(any(f['expected_depth'] == 1 for f in valid))
        self.assertEqual(sum('depth-test' in f['name'] for _, f in cases), 3)
        self.assertEqual(sum('dot-zw-discard' in f['name'] for _, f in cases), 2)
        final_alpha = next(f for key, f in cases if key.alpha_test_function)
        self.assertEqual(final_alpha['uniforms']['alpha_reference'], 128)
        self.assertTrue(any(f.get('depth_write') is False and f['expected_depth'] == .5
                            for _, f in cases))
        restricted = [f for _, f in cases if f['uniforms']['depth_clip_min'] == .25]
        self.assertEqual(len(restricted), 5)
        self.assertEqual([f['discard'] for f in restricted], [True, False, False, False, True])


if __name__ == '__main__':
    unittest.main()
