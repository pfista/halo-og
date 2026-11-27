"""Screen effects at more than 480 lines: the added blur passes and the quad that covers the viewport.

The three helpers come from production `rasterizer_xbox_screen_effect.c`. The
Direct3D calls are stubs that record the quad.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source/rasterizer/xbox/rasterizer_xbox_screen_effect.c"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <math.h>
typedef unsigned char boolean;
typedef float real;
typedef struct { real x0,x1,y0,y1; } real_rectangle2d;
typedef struct { real i,j; } real_vector2d;
#define TRUE 1
#define FALSE 0
#define D3DPT_TRIANGLEFAN 6
enum { _rasterizer_vertex_register_position=0 };
static int global_d3d_device,begun,ended,corners;
static real texture[4][2],position[4][2];
static long IDirect3DDevice8_Begin(int device,int type) { (void)device;assert(type==D3DPT_TRIANGLEFAN);begun++;return 0; }
static long IDirect3DDevice8_End(int device) { (void)device;ended++;return 0; }
static long IDirect3DDevice8_SetVertexData2f(int device,int reg,real a,real b) {
    (void)device;assert(corners<4);
    if (reg==4) { texture[corners][0]=a;texture[corners][1]=b; }
    else { assert(reg==_rasterizer_vertex_register_position);position[corners][0]=a;position[corners][1]=b;corners++; }
    return 0;
}
'''

HARNESS = r'''
/* Where the native renderers put a vertex: half of one of the Xbox's pixels right and down. */
static double screen_x(real x,double width,double scale) { return ((x+1.0)*0.5*width+0.5)*scale; }
static double screen_y(real y,double height,double scale) { return ((1.0-y)*0.5*height+0.5)*scale; }
static void covers(real_rectangle2d bounds,double target_width,double target_height,short width,short height,double scale) {
    real_vector2d pixel={(real)(2.0/target_width),(real)(2.0/target_height)};
    double left=(bounds.x0+1.0)*0.5*target_width*scale,top=(1.0-bounds.y0)*0.5*target_height*scale;

    begun=ended=corners=0;
    assert(screen_effect_draw_covering_quad(&bounds,&pixel,width,height));
    assert(begun==1 && ended==1 && corners==4);
    /* The fan goes bottom left, bottom right, top right, top left, as the Xbox's. */
    assert(fabs(screen_x(position[0][0],target_width,scale)-left)<1e-2);
    assert(fabs(screen_x(position[3][0],target_width,scale)-left)<1e-2);
    assert(fabs(screen_x(position[1][0],target_width,scale)-(left+width*scale))<1e-2);
    assert(fabs(screen_x(position[2][0],target_width,scale)-(left+width*scale))<1e-2);
    assert(fabs(screen_y(position[2][1],target_height,scale)-top)<1e-2);
    assert(fabs(screen_y(position[3][1],target_height,scale)-top)<1e-2);
    assert(fabs(screen_y(position[0][1],target_height,scale)-(top+height*scale))<1e-2);
    assert(fabs(screen_y(position[1][1],target_height,scale)-(top+height*scale))<1e-2);
    /* Every pixel samples where the Xbox's quad made it sample: its own place, in the Xbox's pixels. */
    for (int corner=0;corner<4;corner++) {
        assert(fabs(texture[corner][0]-((screen_x(position[corner][0],target_width,scale)-left)/scale-0.5))<1e-2);
        assert(fabs(texture[corner][1]-((screen_y(position[corner][1],target_height,scale)-top)/scale-0.5))<1e-2);
    }
}
int main(void) {
    /* 480 lines draw the Xbox's passes and nothing else. */
    assert(screen_effect_refinement_passes(1.0f)==0);
    assert(screen_effect_refinement_passes(0.5f)==0 && screen_effect_refinement_passes(0.0f)==0);
    assert(screen_effect_refinement_passes(-3.0f)==0 && screen_effect_refinement_passes(NAN)==0);
    /* One pair up to nine screen pixels to the Xbox's one, two pairs beyond. */
    assert(screen_effect_refinement_passes(1.01f)==2);
    assert(screen_effect_refinement_passes(1.5f)==2 && screen_effect_refinement_passes(2.25f)==2);
    assert(screen_effect_refinement_passes(4.5f)==2 && screen_effect_refinement_passes(9.0f)==2);
    assert(screen_effect_refinement_passes(9.5f)==4 && screen_effect_refinement_passes(81.0f)==4);
    assert(screen_effect_refinement_passes(1000.0f)==4 && screen_effect_refinement_passes(INFINITY)==4);

    /* The Xbox's passes keep the radius; each added pass has a third of the one before. */
    for (short pass=0;pass<4;pass++) assert(screen_effect_pass_radius(9.0f,pass,4)==9.0f);
    assert(screen_effect_pass_radius(9.0f,4,4)==3.0f && screen_effect_pass_radius(9.0f,5,4)==1.0f);
    assert(fabsf(screen_effect_pass_radius(9.0f,6,4)-1.0f/3.0f)<1e-6f);
    assert(fabsf(screen_effect_pass_radius(9.0f,7,4)-1.0f/9.0f)<1e-6f);
    assert(screen_effect_pass_radius(0.0f,5,2)==0.0f && screen_effect_pass_radius(6.0f,2,2)==2.0f);

    /* The whole viewport, at several sizes of screen. */
    {
        real_rectangle2d whole={-1.0f,1.0f,1.0f,-1.0f};
        covers(whole,640,480,640,480,1.5);
        covers(whole,640,480,640,480,2.25);
        covers(whole,853,480,853,480,3.0);
        covers(whole,853,480,853,480,4.5);
        /* A split-screen window's first pass is placed inside the whole target. */
        {
            real_rectangle2d lower={-1.0f,1.0f,0.0f,-1.0f};
            covers(lower,640,480,640,240,2.25);
        }
    }
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class ScreenEffectScaleTests(unittest.TestCase):
    def test_refinement_passes_and_the_covering_quad(self):
        source = SOURCE.read_text()
        production = "\n".join(function(source, signature) for signature in (
            "static short screen_effect_refinement_passes(",
            "static real screen_effect_pass_radius(",
            "static boolean screen_effect_draw_covering_quad(",
        ))
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-screen-effect-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "effect"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-fsanitize=address,undefined",
                                       "-fno-sanitize-recover=undefined", str(harness), "-lm", "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_xbox_quad_is_kept_at_480_lines(self):
        source = SOURCE.read_text()
        draw = function(source, "void _rasterizer_screen_effect(")
        self.assertIn("if (halo_screen_pixel_scale() > 1.0f)", draw)
        self.assertIn("IDirect3DDevice8_SetVertexData2s(", draw)
        self.assertNotIn("convolution_radius /=", draw)


if __name__ == "__main__":
    unittest.main()
