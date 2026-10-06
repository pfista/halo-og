"""Portable HUD fixture controls plus a real EGL/GLES production GPU check."""
import shutil
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hud_glsl_validate import gl_fixtures, libraries, validate


class GlHudFixtureTests(unittest.TestCase):
    def test_required_meter_border_filter_and_bias_controls_are_present(self):
        cases=list(gl_fixtures())
        self.assertEqual(len(cases),279)
        self.assertEqual(len({f['name'] for _,f in cases}),279)
        self.assertEqual(sum(bool(f.get('forced_border_fallback')) for _,f in cases),77)
        self.assertEqual(sum(bool(f.get('bias_control')) for _,f in cases),2)
        self.assertEqual(sum(bool(f.get('point_control')) for _,f in cases),8)

    def test_production_shaders_and_samplers_on_egl(self):
        if not shutil.which('clang'):self.skipTest('clang required')
        try:libraries()
        except OSError as error:self.skipTest(f'EGL/GLES libraries unavailable: {error}')
        with tempfile.TemporaryDirectory(prefix='halo-gl-hud-') as directory:
            proof=validate(Path(directory))
        self.assertTrue(proof['passed'])
        self.assertEqual(proof['pixel_cases'],279)
        self.assertTrue(proof['production_sampler'])
        print(f"{proof['pixel_cases']} GL HUD cases passed on {proof['renderer']}")


if __name__=='__main__':unittest.main()
