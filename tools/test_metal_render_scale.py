#!/usr/bin/env python3
"""CPU-only backing-size/rectangle/input tests; never launches a game or GPU.

The Fraction oracle rounds absolute logical edges. Sanitizer validation runs
the production C helper in a small native process with no host imports.
"""
import ctypes as C
from fractions import Fraction
import math
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'port/linux/src/metal_render_scale.c'
HEADER = SOURCE.with_suffix('.h')
PRESETS = (480, 720, 1080, 1440, 2160)
OK, INVALID = 0, -1


class Dimensions(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ('logical_width', 'logical_height', 'storage_width', 'storage_height')]


class Edges(C.Structure):
    _fields_ = [(name, C.c_int64) for name in ('left', 'top', 'right', 'bottom')]


class Rectangle(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('x', 'y', 'width', 'height')]


class Point(C.Structure):
    _fields_ = [('x', C.c_int32), ('y', C.c_int32)]


def values(value):
    return tuple(getattr(value, name) for name, _ in value._fields_)


def sentinel(kind):
    result = kind()
    C.memset(C.byref(result), 0xa7, C.sizeof(result))
    return result


def oracle(d, edges):
    # Rational arithmetic independently expresses GL's nearest physical edge.
    ratio = Fraction(d.storage_height, d.logical_height)
    left, top, right, bottom = edges
    x0 = math.floor(max(0, min(d.logical_width, left)) * ratio + Fraction(1, 2))
    x1 = math.floor(max(0, min(d.logical_width, right)) * ratio + Fraction(1, 2))
    y0 = math.floor(max(0, min(d.logical_height, top)) * ratio + Fraction(1, 2))
    y1 = math.floor(max(0, min(d.logical_height, bottom)) * ratio + Fraction(1, 2))
    return x0, y0, x1 - x0, y1 - y0


class RenderScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='halo-metal-render-scale-')
        cls.directory = Path(cls.temp.name)
        library = cls.directory / 'render_scale.dylib'
        subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DHALO_MACOS_NATIVE_METAL=1', '-shared', '-fPIC',
                        str(SOURCE), '-o', str(library)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.halo_metal_render_target_dimensions.argtypes = [
            C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint32, C.POINTER(Dimensions)]
        cls.lib.halo_metal_render_scale_rectangle.argtypes = [
            C.POINTER(Dimensions), C.POINTER(Edges), C.POINTER(Rectangle)]
        cls.lib.halo_metal_render_presentation_box.argtypes = [
            C.POINTER(Dimensions), C.c_uint32, C.c_uint32, C.POINTER(Rectangle)]
        cls.lib.halo_metal_render_window_point.argtypes = [C.POINTER(Dimensions),
            C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint32,
            C.c_double, C.c_double, C.c_int32, C.POINTER(Point)]
        for name in ('target_dimensions', 'scale_rectangle', 'presentation_box', 'window_point'):
            getattr(cls.lib, 'halo_metal_render_' + name).restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def dimensions(self, width=640, height=480, screen_width=None, preset=480):
        result = Dimensions()
        self.assertEqual(self.lib.halo_metal_render_target_dimensions(width, height,
            screen_width if screen_width is not None else width, preset, C.byref(result)), OK)
        return result

    def rectangle(self, d, edges):
        result = Rectangle()
        self.assertEqual(self.lib.halo_metal_render_scale_rectangle(
            C.byref(d), C.byref(Edges(*edges)), C.byref(result)), OK)
        self.assertEqual(values(result), oracle(d, edges))
        return values(result)

    def box(self, d, width, height):
        result = Rectangle()
        self.assertEqual(self.lib.halo_metal_render_presentation_box(
            C.byref(d), width, height, C.byref(result)), OK)
        return values(result)

    def point(self, d, ww, wh, pw, ph, x, y, offset=0):
        result = Point()
        self.assertEqual(self.lib.halo_metal_render_window_point(
            C.byref(d), ww, wh, pw, ph, x, y, offset, C.byref(result)), OK)
        return values(result)

    def test_every_screen_width_and_preset_dimensions(self):
        for width in range(640, 1601, 2):
            for preset in PRESETS:
                d = self.dimensions(width, preset=preset)
                expected_width = math.floor(Fraction(width * preset, 480) + Fraction(1, 2))
                self.assertEqual(values(d), (width, 480, expected_width, preset))
                self.assertEqual(self.rectangle(d, (0, 0, width, 480)), (0, 0, expected_width, preset))
        self.assertEqual(values(self.dimensions(1600, preset=2160)), (1600, 480, 7200, 2160))

    def test_scale_one_and_authored_offscreen_sizes_unchanged(self):
        for width, height in ((1, 1), (731, 321), (640, 479), (8192, 8192), (1600, 481)):
            for preset in PRESETS:
                d = self.dimensions(width, height, screen_width=640, preset=preset)
                self.assertEqual(values(d), (width, height, width, height))
                self.assertEqual(self.rectangle(d, (1, 1, width, height)),
                                 (min(1, width), min(1, height), max(width-1, 0), max(height-1, 0)))
        d = self.dimensions(854)
        self.assertEqual(self.rectangle(d, (19, 21, 83, 219)), (19, 21, 64, 198))

    def test_fractional_rounding_uses_uniform_preset_ratio(self):
        d = self.dimensions(preset=720)
        self.assertEqual(self.rectangle(d, (1, 1, 2, 2)), (2, 2, 1, 1))
        d = self.dimensions(preset=1080)
        self.assertEqual(self.rectangle(d, (1, 1, 2, 2)), (2, 2, 3, 3))
        d = self.dimensions(738, preset=1080)
        self.assertEqual(values(d), (738, 480, 1661, 1080))
        # Rounded width /738 would round this divider to831 instead of830.
        self.assertEqual(self.rectangle(d, (0, 0, 369, 480)), (0, 0, 830, 1080))
        self.assertEqual(self.rectangle(d, (369, 0, 738, 480)), (830, 0, 831, 1080))

    def test_adjacent_pixels_and_splitscreen_cover_without_gaps(self):
        for width in (640, 642, 738, 854, 1600):
            for preset in PRESETS:
                d = self.dimensions(width, preset=preset)
                end = 0
                for x in range(width):
                    rectangle = self.rectangle(d, (x, 0, x+1, 480))
                    self.assertEqual(rectangle[0], end)
                    end += rectangle[2]
                self.assertEqual(end, d.storage_width)
                end = 0
                for y in range(480):
                    rectangle = self.rectangle(d, (0, y, width, y+1))
                    self.assertEqual(rectangle[1], end)
                    end += rectangle[3]
                self.assertEqual(end, d.storage_height)
                areas = []
                for left, right in ((0, width//2), (width//2, width)):
                    for top, bottom in ((0, 240), (240, 480)):
                        r = self.rectangle(d, (left, top, right, bottom))
                        areas.append(r[2] * r[3])
                self.assertEqual(sum(areas), d.storage_width * d.storage_height)

    def test_clear_intersections_offsets_clipping_and_extreme_edges(self):
        d = self.dimensions(738, preset=1080)
        self.assertEqual(self.rectangle(d, (0, 0, 738, 240)), (0, 0, 1661, 540))
        # A menu clear intersects the viewport in logical space, then shifts
        # its horizontal edges by the original49-unit centered UI offset.
        self.assertEqual(self.rectangle(d, (10+49, 20, 30+49, 40)), (133, 45, 45, 45))
        self.assertEqual(self.rectangle(d, (-10, -20, 20, 40)), (0, 0, 45, 90))
        self.assertEqual(self.rectangle(d, (-2**63, -2**63, 2**63-1, 2**63-1)),
                         (0, 0, 1661, 1080))
        self.assertEqual(self.rectangle(d, (-30, -20, -1, -1)), (0, 0, 0, 0))
        self.assertEqual(self.rectangle(d, (800, 600, 2**63-1, 2**63-1)), (1661, 1080, 0, 0))

    def test_random_clipped_rectangles_match_fraction_oracle(self):
        rng = random.Random(0x5343414c45)
        for _ in range(3000):
            width = rng.randrange(320, 801) * 2
            d = self.dimensions(width, preset=rng.choice(PRESETS))
            left, right = sorted(rng.sample(range(-2*width, 3*width), 2))
            top, bottom = sorted(rng.sample(range(-960, 1440), 2))
            self.rectangle(d, (left, top, right, bottom))

    def test_invalid_dimensions_and_rectangles_are_atomic(self):
        for args in ((0,480,640,480), (640,0,640,480), (8193,480,640,480),
                     (640,8193,640,480), (2**32-1,2**32-1,640,480),
                     (640,480,639,480), (640,480,641,480), (640,480,1602,480),
                     *((640,480,640,preset) for preset in (0,479,481,721,1079,2161,2**32-1))):
            result = sentinel(Dimensions)
            before = bytes(result)
            self.assertEqual(self.lib.halo_metal_render_target_dimensions(*args, C.byref(result)), INVALID)
            self.assertEqual(bytes(result), before)
        self.assertEqual(self.lib.halo_metal_render_target_dimensions(640,480,640,480,None), INVALID)
        d = self.dimensions(738, preset=1080)
        malformed = [Dimensions(0,480,1661,1080), Dimensions(738,480,1660,1080),
                     Dimensions(739,480,1663,1080), Dimensions(738,480,1661,1081),
                     Dimensions(2**32-1,480,2**32-1,480)]
        for dims, edges in [(bad, Edges(0,0,1,1)) for bad in malformed] + [
                (d, Edges(2,0,1,1)), (d, Edges(0,2,1,1))]:
            result = sentinel(Rectangle)
            before = bytes(result)
            self.assertEqual(self.lib.halo_metal_render_scale_rectangle(
                C.byref(dims), C.byref(edges), C.byref(result)), INVALID)
            self.assertEqual(bytes(result), before)
        e, r = Edges(0,0,1,1), sentinel(Rectangle)
        for args in ((None,C.byref(e),C.byref(r)), (C.byref(d),None,C.byref(r)), (C.byref(d),C.byref(e),None)):
            self.assertEqual(self.lib.halo_metal_render_scale_rectangle(*args), INVALID)

    def test_letterbox_retina_and_logical_menu_mouse_coordinates(self):
        for preset in PRESETS:
            d = self.dimensions(preset=preset)
            self.assertEqual(self.box(d, 1920,1080), (240,0,1440,1080))
            self.assertEqual(self.point(d, 960,540,1920,1080,480,270), (320,240))
            self.assertEqual(self.point(d, 960,540,1920,1080,120,0), (0,0))
            self.assertEqual(self.point(d, 960,540,1920,1080,0,270), (-107,240))
            self.assertEqual(self.box(d, 800,800), (0,100,800,600))
            self.assertEqual(self.point(d, 400,400,800,800,200,50), (320,0))
            self.assertEqual(self.point(d, 400,400,800,800,200,0), (320,-80))
            self.assertEqual(self.point(d, 400,400,800,800,200,350), (320,480))
        d = self.dimensions(738, preset=1080)
        self.assertEqual(self.box(d, 1920,1080), (129,0,1661,1080))
        self.assertEqual(self.point(d, 960,540,1920,1080,64.5,0,49), (-49,0))
        self.assertEqual(self.point(d, 960,540,1920,1080,480,270,49), (320,240))
        # Physical width rounding changes presentation aspect slightly. Match
        # the actual1661x1080 source, not the logical738x480 ratio.
        self.assertEqual(self.box(d, 1000,800), (0,75,1000,650))

    def test_mouse_and_letterbox_invalid_or_overflow_are_atomic(self):
        d = self.dimensions()
        for width,height in ((0,1080),(1920,0),(1,1)):
            out = sentinel(Rectangle)
            before = bytes(out)
            self.assertEqual(self.lib.halo_metal_render_presentation_box(
                C.byref(d), width,height,C.byref(out)), INVALID)
            self.assertEqual(bytes(out),before)
        # Large products still use wide integer arithmetic for aspect fit.
        self.assertEqual(self.box(d,2**32-1,2**32-1), (0,536870912,2**32-1,3221225471))
        for x,y in ((math.nan,0),(0,math.inf),(-math.inf,0),(1e300,0),(0,-1e300)):
            out = sentinel(Point)
            before = bytes(out)
            self.assertEqual(self.lib.halo_metal_render_window_point(
                C.byref(d),640,480,640,480,x,y,0,C.byref(out)), INVALID)
            self.assertEqual(bytes(out),before)
        out = sentinel(Point)
        before = bytes(out)
        self.assertEqual(self.lib.halo_metal_render_window_point(
            C.byref(d),0,480,640,480,0,0,0,C.byref(out)), INVALID)
        self.assertEqual(bytes(out),before)

    def test_native_address_undefined_and_float_cast_sanitizers(self):
        harness = self.directory / 'sanitize.c'
        harness.write_text('''#include "metal_render_scale.h"
#include <assert.h>
#include <math.h>
#include <string.h>
int main(void) {
    const uint32_t presets[]={480,720,1080,1440,2160};
    for(uint32_t width=640;width<=1600;width+=2) for(unsigned p=0;p<5;p++) {
        struct halo_metal_render_dimensions d;
        assert(!halo_metal_render_target_dimensions(width,480,width,presets[p],&d));
        uint32_t end=0;
        for(uint32_t x=0;x<width;x++) {
            struct halo_metal_render_edges e={x,0,(int64_t)x+1,480};
            struct halo_metal_render_rectangle r;
            assert(!halo_metal_render_scale_rectangle(&d,&e,&r));
            assert(r.x==end && r.y==0 && r.height==d.storage_height);
            end+=r.width;
        }
        assert(end==d.storage_width);
        struct halo_metal_render_edges e={INT64_MIN,INT64_MIN,INT64_MAX,INT64_MAX};
        struct halo_metal_render_rectangle r;
        assert(!halo_metal_render_scale_rectangle(&d,&e,&r));
        assert(!r.x && !r.y && r.width==d.storage_width && r.height==d.storage_height);
        assert(!halo_metal_render_presentation_box(&d,UINT32_MAX,UINT32_MAX,&r));
        struct halo_metal_render_point point={7,9},before=point;
        assert(halo_metal_render_window_point(&d,640,480,640,480,1e300,-1e300,0,&point)==HALO_METAL_INVALID);
        assert(!memcmp(&point,&before,sizeof(point)));
        assert(halo_metal_render_window_point(&d,640,480,640,480,NAN,INFINITY,0,&point)==HALO_METAL_INVALID);
        assert(!memcmp(&point,&before,sizeof(point)));
    }
    return 0;
}
''')
        executable = self.directory / 'sanitize'
        subprocess.run(['clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
                        '-DHALO_MACOS_NATIVE_METAL=1','-fsanitize=address,undefined,float-cast-overflow',
                        '-fno-sanitize-recover=all','-I',str(HEADER.parent),
                        str(SOURCE),str(harness),'-o',str(executable)], check=True,capture_output=True)
        subprocess.run([str(executable)], check=True, capture_output=True,timeout=60)


if __name__ == '__main__':
    unittest.main()
