/*
XGPU.H

Internals shared by the OpenGL implementation of the Xbox Direct3D API:
the NV2A shader translators (nv2a_vsh.c, nv2a_psh.c), texture decoding
(xbox_textures.c), guest memory write tracking (memory_watch.c) and the
device itself (d3d8_gl.c).
*/

#ifndef __HALO_LINUX_XGPU_H
#define __HALO_LINUX_XGPU_H

#include "platform.h"
#ifndef HALO_MACOS_NATIVE_METAL
#include "gl.h"
#endif

#ifdef HALO_ANDROID
/* OpenGL ES features that are optional (d3d8_gl.c gl_initialize) */
struct xgpu_capabilities
{
	BOOL copy_image;
	BOOL border_clamp;
	BOOL anisotropy;
	BOOL s3tc;
	/* ES 3.2: glDrawElementsBaseVertex */
	BOOL base_vertex;
	/* ES 3.1 with fragment atomic counters: exact visibility test counts */
	BOOL atomic_counters;
	/* "300 es" or "310 es" */
	const char *shading_language;
};

extern struct xgpu_capabilities xgpu_capabilities;

#ifndef HALO_MACOS_NATIVE_METAL
/* port/android/guest/runtime/guest_host.h */
int host_gl_has_extension(const char *name);
unsigned int host_gl_read_buffer_word(unsigned int buffer, unsigned int offset);
void host_gl_buffer_write(unsigned int target, unsigned int offset, unsigned int size, const void *data);
void host_gl_fence_frame(unsigned int slot);
void host_gl_wait_frame(unsigned int slot);
#endif
#endif

/* ---------- GL state

The device caches the GL state it sets for draws (d3d8_gl.c); code that
changes GL state behind it (binding a texture to upload it, deleting one)
must call this afterwards. */

#ifndef HALO_MACOS_NATIVE_METAL
void xgpu_gl_state_invalidate(void);
/* Upstream optional post-processing's shared GL compilation API. */
GLuint xgpu_compile_shader(GLenum type, const char *source, const char *what);
GLuint xgpu_link_program(GLuint vertex_shader, GLuint fragment_shader, const char *what);
#endif

/* ---------- generated source text */

struct xgpu_text
{
	char *buffer;
	unsigned long length;
	unsigned long capacity;
};

void xgpu_text_append(struct xgpu_text *text, const char *format, ...) __attribute__((format(printf, 2, 3)));

/* ---------- vertex shaders */

#define XGPU_VERTEX_ATTRIBUTE_COUNT 16
#define XGPU_VERTEX_CONSTANT_COUNT 192
/* D3D constant register -96 is hardware register 0 */
#define XGPU_VERTEX_CONSTANT_BIAS 96

/* GLSL for an NV2A vertex program (the instruction words after the program
header). Attributes whose bit is set in packed_attribute_mask are fed as
NORMPACKED3 32-bit integers and unpacked in the shader. Returns a malloc'd
string. */
char *nv2a_vertex_shader_to_glsl(const DWORD *instructions, unsigned long instruction_count,
	unsigned long packed_attribute_mask);
/* Direct NV2A -> native Metal. NULL means unsupported/invalid instructions. */
char *nv2a_vertex_shader_to_msl(const DWORD *instructions, unsigned long instruction_count,
	unsigned long packed_attribute_mask);

/* ---------- pixel shaders */

enum
{
	_xgpu_sampler_none = 0,
	_xgpu_sampler_2d,
	_xgpu_sampler_3d,
	_xgpu_sampler_cube,
};

/* everything a translated pixel shader depends on; the GLSL program cache
is keyed by these bytes */
struct nv2a_pixel_shader_key
{
	DWORD combiner_state[D3DRS_PS_MAX];
	/* D3DRS_PSTEXTUREMODES lies past D3DRS_PS_MAX */
	DWORD texture_modes;
	unsigned char sampler_type[4];
	unsigned char alpha_kill[4];
	/* D3DTSS_COLORSIGN: channels (bit 0 alpha ... bit 3 blue, as
	D3DTSIGN_*) that hold signed data in an unsigned texture format */
	unsigned char color_sign[4];
	/* GLES without texture_border_clamp: bit0/1 select U/V. Filtering0..3
	 * selects single-level linear min/magnification by bit0/1; filtering4
	 * selects the optional HUD's complete unbiased trilinear mip chain. */
	unsigned char border_axes[4];
	unsigned char border_filter[4];
	/* D3DCMP_* function for the alpha test, or 0 when disabled */
	unsigned long alpha_test_function;
	unsigned char fog_enable;
	unsigned char fog_table_mode;
	/* inside a visibility test: count the samples that pass (Android) */
	unsigned char count_samples;
	/* a high-res HUD meter (hud_hires.h) drawn with the meter's blend (the
	destination kept by the source's alpha): that alpha is eased to 1 by the
	coverage texture 0's green holds, so that the meter darkens what is
	behind it only where it covers it (the Xbox's point-sampled meters stop
	at their texels' edges; filtered ones have a fringe of faint texels) */
	unsigned char coverage_alpha;
	/* Halo PC resource channels, applied after sampling on Native Metal.
	   GL uses the texture object's swizzle; zero retains Xbox channel order. */
	unsigned char custom_edition_channels[4];
};

char *nv2a_pixel_shader_to_glsl(const struct nv2a_pixel_shader_key *key);
/* Direct register-combiner/texture-stage -> native Metal. Unsupported states
are rejected rather than silently replaced with approximate shading. */
char *nv2a_pixel_shader_to_msl(const struct nv2a_pixel_shader_key *key);

#ifdef HALO_ANDROID
/* ES samplers have no LOD bias of their own */
#define XGPU_PIXEL_UNIFORMS_ES "uniform vec4 texture_lod_bias;\n"
#else
#define XGPU_PIXEL_UNIFORMS_ES ""
#endif

/* the combiner registers that live in uniforms rather than in the program:
C0/C1 of each stage and the final combiner, and texture constants */
#define XGPU_PIXEL_UNIFORMS \
	"uniform vec4 ps_c0[8];\n" \
	"uniform vec4 ps_c1[8];\n" \
	"uniform vec4 ps_final_c0;\n" \
	"uniform vec4 ps_final_c1;\n" \
	"uniform vec4 fog_color;\n" \
	"uniform vec4 fog_parameters;\n" \
	"uniform float alpha_reference;\n" \
	"uniform vec4 bump_matrix[4];\n" \
	"uniform vec4 bump_luminance[4];\n" \
	"uniform vec4 texture_scale[4];\n" \
	"uniform vec4 texture_border_color[4];\n" \
	XGPU_PIXEL_UNIFORMS_ES

/* ---------- textures */

struct xgpu_texture_description
{
	DWORD format;       /* D3DFMT_* */
	unsigned long width, height, depth, levels;
	BOOL cube_map;
	BOOL linear;        /* not swizzled; addressed with texel coordinates */
	BOOL compressed;
	unsigned long pitch; /* linear textures */
	BOOL hires;         /* a high-res HUD texture drawn in the texture's place (hud_hires.h) */
	BOOL hires_coverage; /* ... whose green is its coverage (a meter's) */
};

void xgpu_texture_describe(DWORD format_word, DWORD size_word, struct xgpu_texture_description *description);
/* bytes of one face, mip levels included (cube faces are padded) */
unsigned long xgpu_texture_face_size(const struct xgpu_texture_description *description);
unsigned long xgpu_texture_level_offset(const struct xgpu_texture_description *description, unsigned long level);
unsigned long xgpu_texture_level_pitch(const struct xgpu_texture_description *description, unsigned long level);

/* CPU-only authored mip extraction. Compressed levels retain their original
blocks; other color formats are decoded into tightly packed byte channels.
Cube faces use the original +X,-X,+Y,-Y,+Z,-Z order and padded face chains. */
enum xgpu_texture_copy_order
{
	_xgpu_texture_copy_rgba, _xgpu_texture_copy_bgra,
};

enum xgpu_texture_copy_format
{
	_xgpu_texture_copy_rgba8 = 1, _xgpu_texture_copy_bgra8,
	_xgpu_texture_copy_bc1, _xgpu_texture_copy_bc2, _xgpu_texture_copy_bc3,
};

enum xgpu_texture_copy_status
{
	_xgpu_texture_copy_ok = 0, _xgpu_texture_copy_invalid = -1,
	_xgpu_texture_copy_unsupported = -2, _xgpu_texture_copy_bounds = -3,
};

struct xgpu_texture_mip_layout
{
	unsigned long texture_width, texture_height, levels, faces;
	unsigned long face, level, width, height;
	unsigned long source_face_pitch, source_total_size, source_offset, source_size, source_row_pitch;
	unsigned long output_row_pitch, output_size;
	enum xgpu_texture_copy_format format;
};

enum xgpu_texture_copy_status xgpu_texture_mip_layout(DWORD format_word, DWORD size_word,
	unsigned long face, unsigned long level, enum xgpu_texture_copy_order order,
	struct xgpu_texture_mip_layout *layout);
/* Source spans the entire authored allocation, including cube face padding.
P8 requires its current 256-entry ARGB32 palette. Destination must not overlap
source or palette. Failures clear *layout and never write destination bytes.
No GL calls, memory tracking, caching, allocation or mip generation occur. */
enum xgpu_texture_copy_status xgpu_texture_mip_copy(DWORD format_word, DWORD size_word,
	const void *source, unsigned long source_bytes, const D3DCOLOR *palette, unsigned long palette_entries,
	unsigned long face, unsigned long level, enum xgpu_texture_copy_order order,
	void *destination, unsigned long destination_bytes, struct xgpu_texture_mip_layout *layout);

/* Separate volume API preserves the 2D/cube layout and rejection contract.
The source is a swizzled 3D allocation. source_image_pitch is its logical
plane size, not a contiguous Morton slice offset. Output slices are tightly
packed at output_image_pitch. Only uncompressed, normalized color is accepted. */
struct xgpu_texture_volume_mip_layout
{
	struct xgpu_texture_mip_layout mip;
	unsigned long texture_depth, depth, source_image_pitch, output_image_pitch;
};
enum xgpu_texture_copy_status xgpu_texture_volume_mip_layout(DWORD format_word, DWORD size_word,
	unsigned long face, unsigned long level, enum xgpu_texture_copy_order order,
	struct xgpu_texture_volume_mip_layout *layout);
/* The same bounds, palette, overlap and failure rules as mip_copy apply. */
enum xgpu_texture_copy_status xgpu_texture_volume_mip_copy(DWORD format_word, DWORD size_word,
	const void *source, unsigned long source_bytes, const D3DCOLOR *palette, unsigned long palette_entries,
	unsigned long face, unsigned long level, enum xgpu_texture_copy_order order,
	void *destination, unsigned long destination_bytes, struct xgpu_texture_volume_mip_layout *layout);

#ifndef HALO_MACOS_NATIVE_METAL
/* the GL texture for an Xbox texture header, uploading or refreshing it
from guest memory as needed; *target receives GL_TEXTURE_2D etc. */
GLuint xgpu_texture_get(const DWORD *resource, const D3DCOLOR *palette, GLenum *target,
	struct xgpu_texture_description *description);
void xgpu_texture_cache_begin_frame(void);

/* ---------- render targets */

struct xgpu_render_target
{
	unsigned long data;  /* physical address */
	unsigned long width, height;
	BOOL depth;
	GLuint texture;
	/* pixels per unit of width and height: more than 1 for the screen's
	targets when the game draws at the display's resolution (d3d8_gl.c) */
	float scale[2];
	unsigned long gl_width, gl_height;
	/* Changes whenever the target is drawn into or cleared. */
	unsigned long written;
};

/* the GL texture holding a render target with this physical address, or 0 */
struct xgpu_render_target *xgpu_render_target_find(unsigned long data);
#endif

#endif
