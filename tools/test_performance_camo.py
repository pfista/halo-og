"""Exercise the production camo constants shared by ANGLE and native Metal.

The fixture captures the actual vertex-constant upload. It verifies the exact
original authored constants, Normal/campaign behavior and that Hardcore removes
only tint across camo intensity and hyper-stealth interpolation.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <assert.h>
#include <string.h>
typedef float real;
typedef struct {real i,j,k,l;} real_vector4d;
typedef struct {real red,green,blue;} real_rgb_color;
#define NUMBEROF(a) (sizeof(a)/sizeof(*(a)))
/* PRODUCTION SCREEN SIZE */
/* PRODUCTION FLAGS */
static struct {
    float active_camouflage_refraction_amount;
    float active_camouflage_hyper_stealth_refraction_amount;
    float active_camouflage_distance_falloff;
    float active_camouflage_hyper_stealth_distance_falloff;
    real_rgb_color active_camouflage_tint_color;
    real_rgb_color active_camouflage_hyper_stealth_tint_color;
} settings={.5f,.125f,16.f,4.f,{.125f,.25f,.75f},{.25f,.5f,.125f}},
  *global_rasterizer_data=&settings;
struct transparent_geometry_group {struct {float intensity,parameter;} effect;};
static unsigned flags, variant_reads;
static int multiplayer;
static real_vector4d uploaded[3];
static void *global_d3d_device;
static int game_engine_running(void) {return multiplayer;}
static void *game_engine_get_variant(void) {return &flags;}
static unsigned performance_variant_get_flags(void *variant) {
    assert(variant==&flags);variant_reads++;return flags;
}
static void IDirect3DDevice8_SetVertexShaderConstant(void *device,int first,
    const void *constants,unsigned count) {
    assert(device==global_d3d_device && first==-84 && count==3);
    memcpy(uploaded,constants,sizeof(uploaded));
}
static void draw_constants(float intensity,float parameter) {
    struct transparent_geometry_group value={{intensity,parameter}},*group=&value;
    variant_reads=0;
    /* PRODUCTION CONSTANTS */
    assert(group->effect.intensity==intensity && group->effect.parameter==parameter);
}
int main(void) {
    assert(_performance_option_hardcore_camo==256);
    /* These fixed binary fractions have exact original Xbox-path outputs.
     * Test all visible/revealing intensities and hyper-stealth interpolation. */
    for(int hyper=0;hyper<=4;hyper++) for(int level=0;level<=4;level++) {
        const float parameter=hyper*.25f,intensity=level*.25f;
        const float refraction=(.5f-hyper*.09375f)*intensity;
        const float falloff=16.f-hyper*3.f;
        const real_vector4d expected[3]={
            {refraction,falloff,320.f,240.f}, {0,0,0,0},
            {.125f+hyper*.03125f,.25f+hyper*.0625f,.75f-hyper*.15625f,0}
        };
        multiplayer=1;flags=0;
        draw_constants(intensity,parameter);
        assert(!memcmp(uploaded,expected,sizeof(expected)));
        flags=_performance_option_hardcore; /* Precision is a distinct setting. */
        draw_constants(intensity,parameter);
        assert(!memcmp(uploaded,expected,sizeof(expected)));
        flags=_performance_option_hardcore_camo;
        draw_constants(intensity,parameter);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(!memcmp(uploaded,expected,sizeof(real_vector4d)*2));
        const real_vector4d no_tint={1,1,1,0};
        assert(!memcmp(&uploaded[2],&no_tint,sizeof(no_tint)));
        assert(variant_reads==1);
#else
        assert(!memcmp(uploaded,expected,sizeof(expected)));
        assert(variant_reads==0);
#endif
        multiplayer=0; /* Campaign can retain a stale multiplayer variant. */
        draw_constants(intensity,parameter);
        assert(!memcmp(uploaded,expected,sizeof(expected)));
        assert(variant_reads==0);
    }
    return 0;
}
'''

COMBINER_FIXTURE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t DWORD;
#define csmemset memset
#define TEST_FLAG(f,b) (((f)&(1u<<(b)))!=0)
/* PRODUCTION XDK ENUMS */
/* PRODUCTION XDK PACKING */
#include "rasterizer/xbox/rasterizer_xbox_pixel_shader.h"
enum {_active_camouflage_tint_edge_density_bit=0};
static struct {unsigned active_camouflage_flags;} settings,*global_rasterizer_data=&settings;
struct transparent_geometry_group {struct {float intensity;} effect;};
static struct pixel_shader_definition submitted;
static unsigned long real_alpha_to_pixel32(float alpha) {
    return (unsigned long)(alpha*255.f+.5f)<<24;
}
static void rasterizer_set_pixel_shader(const struct pixel_shader_definition *shader) {
    submitted=*shader;
}
static void submit(int edge,float intensity) {
    struct transparent_geometry_group value={{intensity}},*group=&value;
    struct pixel_shader_definition pixel_shader;
    settings.active_camouflage_flags=edge;
    /* PRODUCTION COMBINERS */
}
int main(void) {
    for(int edge=0;edge<=1;edge++) for(int level=0;level<=4;level++) {
        submit(edge,level*.25f);
        assert(submitted.combiner_count==2);
        printf("%d %d %lu %lu %lu %lu %lu %lu %lu\n",edge,level,
            submitted.rgb_inputs[0],submitted.rgb_outputs[0],
            submitted.rgb_inputs[1],submitted.rgb_outputs[1],
            submitted.final_combiner_inputs_abcd,submitted.final_combiner_inputs_efg,
            submitted.final_combiner_constant_0);
    }
    return 0;
}
'''


def mapped_input(value, registers, channel):
    """Independent scalar NV2A input-byte interpretation for these combiners."""
    register = registers[value & 15]
    component = register[3 if value & 16 else channel]
    mapping = value & 224
    if mapping == 0:
        return max(component, 0)
    if mapping == 32:
        return 1 - max(0, min(component, 1))
    raise AssertionError(f"Unexpected camo combiner mapping {mapping}")


def evaluate_combiners(words, tint, scene, distance, density):
    registers = {0: [0] * 4, 1: [0, 0, 0, (words[6] >> 24) / 255],
                 4: [*tint, distance], 8: [0, 0, 0, density],
                 10: [*scene, 1], 12: [0] * 4}
    for inputs, outputs in zip(words[:4:2], words[1:4:2]):
        # The production general combiners write the sum to R0, discarding
        # AB/CD. Unexpected output modes must not pass this limited evaluator.
        assert outputs == 12 << 8
        values = [(inputs >> shift) & 255 for shift in (24, 16, 8, 0)]
        result = []
        for channel in range(3):
            a, b, c, d = [mapped_input(v, registers, channel) for v in values]
            result.append(max(-1, min(a * b + c * d, 1)))
        registers[12][:3] = result
    final = [(words[4] >> shift) & 255 for shift in (24, 16, 8, 0)]
    result = []
    for channel in range(3):
        a, b, c, d = [mapped_input(v, registers, channel) for v in final]
        result.append(a * b + (1 - a) * c + d)
    result.append(mapped_input((words[5] >> 8) & 255, registers, 3))
    return result


class PerformanceCamoTests(unittest.TestCase):
    def test_production_upload_preserves_every_non_tint_constant(self):
        source = (ROOT / "source/rasterizer/xbox/rasterizer_xbox_active_camouflage.c").read_text()
        constants = block(source, "{\n\t\t\treal_vector4d vertex_constants[3];")
        screen_size = block(source, "enum\n{\n\tACTIVE_CAMOUFLAGE_SCREEN_WIDTH") + ";"
        flags = block((ROOT / "source/game/performance_variant.h").read_text(), "enum\n{") + ";"
        fixture = (FIXTURE.replace("/* PRODUCTION CONSTANTS */", constants)
                   .replace("/* PRODUCTION FLAGS */", flags)
                   .replace("/* PRODUCTION SCREEN SIZE */", screen_size))
        with tempfile.TemporaryDirectory(prefix="halo-hardcore-camo-") as temporary:
            test_source = Path(temporary) / "fixture.c"
            test_source.write_text(fixture)
            for port in (False, True):
                binary = Path(temporary) / ("port" if port else "stock")
                if sys.platform == "win32":
                    binary = binary.with_suffix(".exe")
                subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror",
                                "-Wno-unused-function", *(["-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=16"] if port else []),
                                str(test_source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_production_combiners_preserve_scene_with_neutral_white(self):
        source = (ROOT / "source/rasterizer/xbox/rasterizer_xbox_active_camouflage.c").read_text()
        tint_upload = source.index("vertex_constants[2].l = 0.0f;")
        start = source.index("csmemset(&pixel_shader, 0, sizeof(pixel_shader));", tint_upload)
        end = source.index("rasterizer_set_pixel_shader(&pixel_shader);", start)
        combiners = source[start:end + len("rasterizer_set_pixel_shader(&pixel_shader);")]
        pdb = (ROOT / "port/include/xdk/xdk_pdb.h").read_text()
        enums = "\n".join(block(pdb, "enum " + name + " {") + ";" for name in (
            "PS_CHANNEL", "PS_COMBINERCOUNTFLAGS", "PS_COMBINEROUTPUT", "PS_DOTMAPPING",
            "PS_INPUTMAPPING", "PS_REGISTER", "PS_TEXTUREMODES"))
        d3d = (ROOT / "port/include/xdk/xdk_d3d8.h").read_text()
        macros = d3d[d3d.index("#define PS_COMBINERINPUTS"):d3d.index("/* ---------- functions */")]
        fixture = (COMBINER_FIXTURE.replace("/* PRODUCTION COMBINERS */", combiners)
                   .replace("/* PRODUCTION XDK ENUMS */", enums)
                   .replace("/* PRODUCTION XDK PACKING */", macros))
        with tempfile.TemporaryDirectory(prefix="halo-camo-combiners-") as temporary:
            test_source = Path(temporary) / "fixture.c"
            binary = test_source.with_suffix(".exe" if sys.platform == "win32" else "")
            test_source.write_text(fixture)
            subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "source"), str(test_source), "-o", str(binary)], check=True)
            records = subprocess.check_output([str(binary)], text=True).splitlines()
        self.assertEqual(len(records), 10)
        for record in records:
            edge, level, *words = map(int, record.split())
            for distance_step in range(5):
                for density_step in range(5):
                    distance, density = distance_step * .25, density_step * .25
                    scene, blue_tint = [.25, .5, .75], [.5, .75, 1]
                    factor = distance * (density if edge else 1)
                    neutral = evaluate_combiners(words, [1, 1, 1], scene, distance, density)
                    normal = evaluate_combiners(words, blue_tint, scene, distance, density)
                    self.assertEqual(neutral[:3], scene)
                    self.assertEqual(normal[:3], [rgb * (1 - factor * (1 - tint))
                                                for rgb, tint in zip(scene, blue_tint)])
                    self.assertEqual(neutral[3], normal[3])
                    self.assertEqual(neutral[3], int(level * .25 * 255 + .5) / 255)
                    if factor:
                        self.assertLess(normal[0], neutral[0])
                        self.assertLess(normal[1], neutral[1])
                        self.assertEqual(normal[2], neutral[2])


if __name__ == "__main__":
    unittest.main()
