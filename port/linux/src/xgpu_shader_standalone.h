/* Source-only harness interface. Xbox enum values match xdk_pdb.h; only the
 * shader translator subset is declared here, avoiding the guest/XDK/GL ABI. */
#ifndef XGPU_SHADER_STANDALONE_H
#define XGPU_SHADER_STANDALONE_H
#include <stdint.h>
#include <stddef.h>
#include "xgpu_msl.h"
typedef uint32_t DWORD;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define XGPU_VERTEX_ATTRIBUTE_COUNT 16
#define XGPU_VERTEX_CONSTANT_COUNT 192
#define XGPU_VERTEX_CONSTANT_BIAS 96
enum {
    D3DRS_PSALPHAINPUTS0=0, D3DRS_PSFINALCOMBINERINPUTSABCD=8,
    D3DRS_PSFINALCOMBINERINPUTSEFG=9, D3DRS_PSCONSTANT0_0=10,
    D3DRS_PSCONSTANT1_0=18, D3DRS_PSALPHAOUTPUTS0=26,
    D3DRS_PSRGBINPUTS0=34, D3DRS_PSCOMPAREMODE=42,
    D3DRS_PSFINALCOMBINERCONSTANT0=43, D3DRS_PSFINALCOMBINERCONSTANT1=44,
    D3DRS_PSRGBOUTPUTS0=45, D3DRS_PSCOMBINERCOUNT=53,
    D3DRS_PSDOTMAPPING=55, D3DRS_PSINPUTTEXTURE=56, D3DRS_PS_MAX=57,
    D3DRS_PSTEXTUREMODES=116
};
enum { D3DCMP_NEVER=512, D3DCMP_LESS, D3DCMP_EQUAL, D3DCMP_LESSEQUAL,
    D3DCMP_GREATER, D3DCMP_NOTEQUAL, D3DCMP_GREATEREQUAL, D3DCMP_ALWAYS };
enum { D3DFOG_NONE, D3DFOG_EXP, D3DFOG_EXP2, D3DFOG_LINEAR };
enum { _xgpu_sampler_none, _xgpu_sampler_2d, _xgpu_sampler_3d, _xgpu_sampler_cube };
struct xgpu_text { char *buffer; unsigned long length, capacity; };
void xgpu_text_append(struct xgpu_text *, const char *, ...) __attribute__((format(printf,2,3)));
struct nv2a_pixel_shader_key {
    DWORD combiner_state[D3DRS_PS_MAX];
    DWORD texture_modes;
    unsigned char sampler_type[4], alpha_kill[4], color_sign[4], border_axes[4], border_filter[4];
    unsigned long alpha_test_function;
    unsigned char fog_enable, fog_table_mode, count_samples, coverage_alpha;
};
struct xgpu_capabilities { int border_clamp; const char *shading_language; };
extern struct xgpu_capabilities xgpu_capabilities;
static inline const char *config_string(const char *name) { (void)name; return ""; }
static inline BOOL config_boolean(const char *name) { (void)name; return FALSE; }
#define XGPU_PIXEL_UNIFORMS_ES "uniform vec4 texture_lod_bias;\n"
#define XGPU_PIXEL_UNIFORMS \
    "uniform vec4 ps_c0[8], ps_c1[8];\nuniform vec4 ps_final_c0, ps_final_c1;\n" \
    "uniform vec4 fog_color, fog_parameters;\nuniform float alpha_reference;\n" \
    "uniform vec4 bump_matrix[4], bump_luminance[4], texture_scale[4], texture_border_color[4];\n" \
    XGPU_PIXEL_UNIFORMS_ES
char *nv2a_vertex_shader_to_glsl(const DWORD *, unsigned long, unsigned long);
char *nv2a_vertex_shader_to_msl(const DWORD *, unsigned long, unsigned long);
char *nv2a_pixel_shader_to_glsl(const struct nv2a_pixel_shader_key *);
char *nv2a_pixel_shader_to_msl(const struct nv2a_pixel_shader_key *);
#endif
