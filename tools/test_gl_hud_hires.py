"""Portable HUD fixture controls plus a real EGL/GLES production GPU check."""
import shutil
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hud_glsl_validate as validator
from hud_glsl_validate import gl_fixtures, libraries, pixel_tolerance, validate
from metal_hud_hires_validate import meter_reference


class GlHudFixtureTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == 'win32', 'Mac ANGLE companion uses POSIX symlinks')
    def test_standalone_angle_load_prepares_egl_companion_before_dlopen(self):
        with tempfile.TemporaryDirectory(prefix='halo-angle-loader-') as directory:
            root = Path(directory)
            angle = root / 'build/macos/angle/dist'
            egl = angle / 'EGL.xcframework/macos-arm64/libEGL.framework/libEGL'
            gles = angle / 'GLESv2.xcframework/macos-arm64/libGLESv2.framework/libGLESv2'
            for path in (egl, gles):
                path.parent.mkdir(parents=True)
                path.touch()
            companion = egl.with_name('libGLESv2.dylib')
            def load(path):
                self.assertEqual(companion.resolve(), gles.resolve())
                return path
            with patch.object(validator, 'ROOT', root), \
                    patch.object(validator.sys, 'platform', 'darwin'), \
                    patch.object(validator.C, 'CDLL', side_effect=load) as loader:
                libraries()
                self.assertEqual(loader.call_count, 2)
                companion.unlink()
                companion.symlink_to(root / 'old-checkout/libGLESv2')
                libraries()
                self.assertEqual(companion.resolve(), gles.resolve())
                gles.unlink()
                with self.assertRaisesRegex(OSError, 'Missing bundled ANGLE'):
                    libraries()

    def test_rgba8_rounding_bounds_keep_point_endpoints_and_discards_strict(self):
        cases=list(gl_fixtures())
        strict = .00002
        for key, fixture in cases:
            if fixture.get('point_control') and not fixture['hires']:
                self.assertEqual(pixel_tolerance(key, fixture), strict)
            if fixture.get('discard'):
                self.assertEqual(pixel_tolerance(key, fixture), strict)
            if 'meter_blend' in fixture and not key.coverage_alpha:
                self.assertEqual(pixel_tolerance(key, fixture), strict)
            if fixture.get('coverage') in (0, 1):
                self.assertEqual(pixel_tolerance(key, fixture), strict)
        key, fixture = next((key, fixture) for key, fixture in cases
            if fixture['name']=='hud-meter-1-0-0-64-0.375-0')
        rounded_coverage = round(fixture['coverage'] * 255) / 255
        # Independent reference: only green coverage rounds. Constant blue and
        # the quarter-weighted authored art byte already have exact codes.
        source = meter_reference(0, rounded_coverage, .25 * 64 / 255, True)
        rounded = [a * tint + background * source[3] for a, tint, background in
                   zip(source, fixture['meter_blend'], fixture['clear_color'])]
        error = max(abs(a-b) for a,b in zip(rounded,fixture['expected']))
        self.assertGreater(error, strict)
        self.assertLess(error, pixel_tolerance(key,fixture))
        self.assertLess(pixel_tolerance(key,fixture), .001)
        # A lost coverage transform is much larger than the permitted rounding.
        original = meter_reference(0, .25, .25 * 64 / 255, False)
        broken = [a * tint + background * original[3] for a,tint,background in
                  zip(original,fixture['meter_blend'],fixture['clear_color'])]
        self.assertGreater(max(abs(a-b) for a,b in zip(broken,fixture['expected'])),
                           pixel_tolerance(key,fixture))
        linear_key, linear = next((key, fixture) for key, fixture in cases
            if fixture['name']=='hud-original-point-vs-hires-linear-1-0.375')
        self.assertLess(max(abs(round(a*255)/255-a) for a in linear['expected']),
                        pixel_tolerance(linear_key,linear))
        wrong_point = [.2,.4,.6,.8]
        self.assertGreater(max(abs(a-b) for a,b in zip(wrong_point,linear['expected'])),
                           pixel_tolerance(linear_key,linear))

    def test_required_meter_border_filter_and_bias_controls_are_present(self):
        cases=list(gl_fixtures())
        self.assertEqual(len({f['name'] for _,f in cases}),len(cases))
        self.assertTrue(any('meter_blend' in f for _,f in cases))
        self.assertTrue(any(f.get('forced_border_fallback') for _,f in cases))
        for control in ('bias_control', 'point_control'):
            with self.subTest(control=control):
                self.assertEqual({f['hires'] for _,f in cases if f.get(control)}, {False, True})
        self.assertEqual({f['text_blend'] for _,f in cases if 'text_blend' in f}, {False, True})

    def test_production_shaders_and_samplers_on_egl(self):
        if not shutil.which('clang'):self.skipTest('clang required')
        try:libraries()
        except OSError as error:self.skipTest(f'EGL/GLES libraries unavailable: {error}')
        with tempfile.TemporaryDirectory(prefix='halo-gl-hud-') as directory:
            proof=validate(Path(directory))
        self.assertTrue(proof['passed'])
        self.assertGreater(proof['real_glyph_cases'],0)
        self.assertTrue(proof['production_sampler'])
        print(f"{proof['pixel_cases']} GL HUD cases passed on {proof['renderer']}")


if __name__=='__main__':unittest.main()
