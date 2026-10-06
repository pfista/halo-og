"""Check independent original-meter/coverage reference cases before GPU use."""
import unittest

from metal_hud_hires_validate import CLEAR, border_fixtures, hud_fixtures, meter_reference, text_fixtures


class HudFixtureTests(unittest.TestCase):
    def test_transparent_edge_preserves_background_via_coverage(self):
        for blue in (0, .25, .75, 1):
            source = meter_reference(blue, 0, 0, True)
            self.assertEqual(source, [0, 0, 0, 1])
            self.assertEqual([a * .5 + b * source[3]
                              for a, b in zip(source[:3], CLEAR[:3])], CLEAR[:3])

    def test_coverage_changes_alpha_without_changing_meter_rgb(self):
        for blue in (0, .25, .75, 1):
            for coverage in (0, .25, .5, 1):
                original = meter_reference(blue, coverage, .25, False)
                corrected = meter_reference(blue, coverage, .25, True)
                self.assertEqual(original[:3], corrected[:3])
                self.assertAlmostEqual(corrected[3], 1 - coverage * (1 - original[3]))
                if coverage == 1:
                    self.assertEqual(corrected, original)

    def test_fixture_matrix_includes_alpha_kill_test_and_both_flash_polarities(self):
        cases = list(hud_fixtures())
        self.assertEqual(len(cases), 192)
        self.assertEqual(len({f['name'] for _, f in cases}), 192)
        self.assertEqual({key.coverage_alpha for key, _ in cases}, {0, 1})
        self.assertEqual({key.alpha_test_function for key, _ in cases}, {0, 516})
        self.assertEqual({key.combiner_state[36] for key, _ in cases}, {0x0C201C02, 0x0C201CE2})
        self.assertTrue(all(f['discard'] for _, f in cases if f['coverage'] == 0))
        self.assertTrue(any(f['discard'] for key, f in cases if key.alpha_test_function and f['coverage'] > 0))
        self.assertTrue(any(not f['discard'] for key, f in cases if key.alpha_test_function and f['coverage'] > 0))

    def test_border_cases_include_fractional_mips_and_original_point_controls(self):
        cases = list(border_fixtures())
        self.assertEqual(len(cases), 77)
        self.assertEqual(len({f['name'] for _, f in cases}), 77)
        self.assertTrue(any(f['textures'][0]['lod'] == 1.5 for _, f in cases))
        self.assertTrue(any(not f['textures'][0]['trilinear'] for _, f in cases))
        self.assertTrue(all(f['native_alpha_border_mask'] == 1 for _, f in cases))

    def test_text_cases_preserve_ordinary_alpha_and_rgb_only_blending(self):
        cases = list(text_fixtures())
        self.assertEqual(len(cases), 30)
        self.assertEqual(len({f['name'] for _, f in cases}), 30)
        self.assertTrue(all(key.coverage_alpha == 0 for key, _ in cases))
        transparent = [f for _, f in cases if f['text_blend'] and f['coverage'] == 0]
        self.assertEqual(len(transparent), 3)
        self.assertTrue(all(f['expected'] == CLEAR for f in transparent))
        self.assertTrue(all(f['expected'][3] == CLEAR[3] for _, f in cases if f['text_blend']))
        self.assertTrue(any(f['coverage'] == .5 for _, f in cases))
        self.assertTrue(any(f['source_expected'][:3] == [0, 0, 0] for _, f in cases))


if __name__ == '__main__':
    unittest.main()
