"""A portal outline with a corner exactly on the clip line stays a polygon of real numbers.

`convex_polygon2d_clip_to_plane` and the helpers it calls come from production.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = ROOT / "source/math/geometry.c"
REAL_MATH = ROOT / "source/math/real_math.h"
CSERIES = ROOT / "source/cseries/cseries.h"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char boolean;
typedef float real;
typedef struct { real x,y; } real_point2d;
typedef struct { real i,j; } real_vector2d;
typedef struct { real_vector2d n;real d; } real_plane2d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define __inline static inline
#define FLAG(n) (1u<<(n))
#define TEST_FLAG(f,n) (((f)&FLAG(n))!=0)
#define SET_FLAG(f,n,v) ((f)=(v) ? ((f)|FLAG(n)) : ((f)&~FLAG(n)))
#define csmemcpy memcpy
#define match_assert(file,line,condition) assert(condition)
enum { CLIP_BUFFER_SIZE=512,NUMBER_OF_VERTICES_PER_TRIANGLE=3 };
#define long int   /* the game's long is 32 bits */
'''

HARNESS = r'''
#undef long
int main(void) {
    /* Portal outlines are clipped in screen space with this tolerance (structure_visibility.c).
       Earlier clips leave corners a rounding error apart. Find a corner exactly on the clip line
       whose neighbour, one such step away along the line, rounds to just behind it. */
    const real epsilon=0.0001f;
    real_plane2d plane={{0.70710678f,0.70710678f},0.0f};
    unsigned found=0;

    for (int base=1;base<2000 && found<8;base++) {
        real_point2d on={(real)base*0.000437f,(real)base*0.000291f-0.3f};
        plane.d=plane.n.i*on.x+plane.n.j*on.y;
        if (plane2d_distance_to_point(&plane,&on)!=0.0f) continue;
        for (int step=1;step<64 && found<8;step++) {
            real nudge=(real)step*0x1p-24f;
            real_point2d behind={on.x+nudge,on.y-nudge};
            real_vector2d vector;
            real_point2d outline[4],result[8];
            unsigned flags=0;
            boolean clipped=FALSE;
            short count;

            vector_from_points2d(&on,&behind,&vector);
            if (!(plane2d_distance_to_point(&plane,&behind)<0.0f) ||
                plane.n.i*vector.i+plane.n.j*vector.j!=0.0f)
                continue;
            /* Zero over zero: the crossing this corner used to be given. */
            assert(isnan(vector_intersect_plane2d(&on,&vector,&plane)));
            found++;
            /* An outline that really does cross the line: one corner well behind, one well in front. */
            outline[0].x=on.x+0.3f;outline[0].y=on.y-0.6f;
            outline[1]=behind;outline[2]=on;
            outline[3].x=on.x;outline[3].y=on.y+0.3f;
            assert(plane2d_distance_to_point(&plane,&outline[0])<-epsilon);
            assert(plane2d_distance_to_point(&plane,&outline[3])>epsilon);
            count=convex_polygon2d_clip_to_plane(4,outline,&plane,8,result,&flags,&clipped,epsilon);
            assert(count>=3 && clipped);
            for (short index=0;index<count;index++) {
                assert(isfinite(result[index].x) && isfinite(result[index].y));
                assert(plane2d_distance_to_point(&plane,&result[index])>-epsilon);
            }
        }
    }
    assert(found==8);

    /* An ordinary crossing is unchanged: a square cut in half by x=0. */
    {
        real_plane2d half={{1.0f,0.0f},0.0f};
        real_point2d square[4]={{-1.0f,-1.0f},{1.0f,-1.0f},{1.0f,1.0f},{-1.0f,1.0f}},result[8];
        boolean clipped=FALSE;
        short count=convex_polygon2d_clip_to_plane(4,square,&half,8,result,NULL,&clipped,epsilon);

        assert(count==4 && clipped);
        for (short index=0;index<count;index++)
            assert(result[index].x>=0.0f && result[index].x<=1.0f && fabsf(result[index].y)==1.0f);
    }
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class PortalClipTests(unittest.TestCase):
    def test_a_corner_on_the_clip_line_does_not_become_not_a_number(self):
        geometry = GEOMETRY.read_text()
        real_math = REAL_MATH.read_text()
        # The game's own pin keeps a value that is not a number, which is the fault; a stand-in may not.
        macros = "\n".join(line for line in CSERIES.read_text().splitlines()
                           if re.match(r"#define (MIN|MAX|FLOOR|CEILING|PIN)\(", line))
        self.assertEqual(macros.count("#define"), 5)
        production = macros + "\n" + "\n".join(
            [function(real_math, signature) for signature in (
                "__inline real_point2d *point_from_line2d(",
                "__inline real_vector2d *vector_from_points2d(",
                "__inline real plane2d_distance_to_point(",
                "__inline boolean valid_real(",
            )] + [function(geometry, signature) for signature in (
                "real vector_intersect_plane2d(",
                "short convex_polygon2d_clip_to_plane(",
            )])
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-portal-clip-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "clip"
            # No contraction: the game's x86 arithmetic rounds each product, and the case depends on it.
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-ffp-contract=off",
                                       "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
                                       "-fno-sanitize=float-divide-by-zero",
                                       str(harness), "-lm", "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
