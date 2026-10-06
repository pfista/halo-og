/*
RASTERIZER_TEXT.C

symbols in this file:
00172E80 0010:
	_code_00172e80 (0000)
00172E90 0010:
	_code_00172e90 (0000)
00172EA0 0090:
	_rasterizer_text_cache_initialize (0000)
00172F30 0010:
	_rasterizer_text_set_shadow_color (0000)
00172F40 0030:
	_rasterizer_text_cache_flush (0000)
00172F70 0030:
	_rasterizer_text_cache_dispose (0000)
00172FA0 0020:
	_code_00172fa0 (0000)
00172FC0 00b0:
	_code_00172fc0 (0000)
00173070 0060:
	_code_00173070 (0000)
001730D0 0380:
	_code_001730d0 (0000)
00173450 00f0:
	_code_00173450 (0000)
00173540 0170:
	_code_00173540 (0000)
001736B0 0200:
	_rasterizer_draw_string (0000)
001738B0 0200:
	_rasterizer_draw_unicode_string (0000)
0029EEE0 0033:
	??_C@_0DD@DKOHMJNA@?$CD?$CD?$CD?5ERROR?5failed?5to?5initialize?5h@ (0000)
0029EF14 0026:
	??_C@_0CG@HPKDNNGC@?$CBhardware_character_cache?4initia@ (0000)
0029EF3C 002c:
	??_C@_0CM@KJINBGGM@c?3?2halo?2SOURCE?2rasterizer?2raster@ (0000)
0029EF68 0009:
	??_C@_08KDNNBGOA@x0?5?$CG?$CG?5y0?$AA@ (0000)
0029EF78 0054:
	??_C@_0FE@BCPFIEIE@hardware_character_index?$DO?$DN0?5?$CG?$CG?5h@ (0000)
0029EFCC 0025:
	??_C@_0CF@POBHCEMM@hardware_character_cache?4initial@ (0000)
0029EFF4 0026:
	??_C@_0CG@JHCOKPHL@font?5cache?5overwrote?5character?5i@ (0000)
0029F01C 0013:
	??_C@_0BD@PIEBJAO@hardware_character?$AA@ (0000)
0029F030 0046:
	??_C@_0EG@CBPAFGHN@font_character?9?$DObitmap_height?$DM?$DNH@ (0000)
0029F078 0044:
	??_C@_0EE@KGLMBKON@font_character?9?$DObitmap_width?$DM?$DNHA@ (0000)
0029F0C0 0068:
	??_C@_0GI@IDEJCHPO@font_character?$DN?$DNhardware_charact@ (0000)
0029F128 0074:
	??_C@_0HE@KFKECHAF@font_character?9?$DOhardware_charact@ (0000)
0030D4D0 0002:
	_data_0030d4d0 (0000)
004B82C0 0816:
	_bss_004b82c0 (0000)
*/


/* ---------- headers */

#include "cseries/cseries.h"
#include "cseries/errors.h"
#include "bitmaps/bitmap_group.h"
#include "bitmaps/bitmaps.h"
#include "math/integer_math.h"
#include "rasterizer/rasterizer.h"
#include "rasterizer/rasterizer_console_vars.h"
#include "rasterizer/rasterizer_text.h"
#include "rasterizer/xbox/rasterizer_xbox_hardware_bitmaps.h"
#include "render/render.h"
#include "text/draw_string.h"
#include "text/font_group.h"
#include "text/unicode.h"
#include "tag_files/tag_files.h"
#include "port_config.h"
#include "text_hires.h"

/* ---------- constants */

enum
{
	HARDWARE_CHARACTER_CACHE_BITMAP_WIDTH = 128,
	HARDWARE_CHARACTER_CACHE_BITMAP_HEIGHT = 128,
	MAXIMUM_HARDWARE_CHARACTERS = 256,
};

enum
{
	_bitmap_format_a4r4g4b4 = 9,
};

enum
{
	_rasterizer_target_render_primary = 0,
	_shader_framebuffer_blend_function_alpha_blend = 0,
};

/* ---------- macros */

/* ---------- structures */

struct font_character
{
	word character;
	short character_width;
	short bitmap_width;
	short bitmap_height;
	short bitmap_origin_x;
	short bitmap_origin_y;
	short hardware_character_index;
	short pad;
	long pixels_offset;
};

struct parse_string_state;

typedef void (*draw_character_proc)(
	struct parse_string_state *state,
	struct font_header *font,
	struct font_character *font_character,
	unsigned long color,
	short x0,
	short y0,
	short x,
	short y,
	short dx,
	short dy);

struct hardware_character
{
	struct font_character *character;
	short x0;
	short y0;
};

struct hardware_character_cache
{
	boolean initialized;
	byte unused1;
	short read_index;
	short write_index;
	short x0;
	short y0;
	short maximum_character_height;
	struct bitmap_data *bitmap;
	struct hardware_character characters[MAXIMUM_HARDWARE_CHARACTERS];
};

/* ---------- prototypes */

static struct bitmap_data *hardware_character_cache_get_bitmap(
	void);
static void hardware_character_cache_get_origin(
	short hardware_character_index,
	short *x0,
	short *y0);
static short hardware_character_padding(
	struct font_character const *font_character);
static void flush_hardware_character(
	struct hardware_character *hardware_character);
static void cache_hardware_format_character(
	struct font_header *font,
	struct font_character *font_character);
static void rasterizer_draw_character(
	struct parse_string_state *state,
	struct font_header *font,
	struct font_character *font_character,
	unsigned long color,
	short x0,
	short y0,
	short x,
	short y,
	short dx,
	short dy);
static void rasterizer_draw_character_with_dropshadow(
	struct parse_string_state *state,
	struct font_header *font,
	struct font_character *font_character,
	unsigned long color,
	short x0,
	short y0,
	short x,
	short y,
	short dx,
	short dy);

/* ---------- globals */


static struct hardware_character_cache hardware_character_cache;
static pixel32 global_shadow_color = 0;
static short rasterizer_text_unused = 0;
static short magic_number= 12;

/* Optional glyph atlas; created only after the user selects higher quality.
 * The placeholder retains logical texel coordinates on every renderer. */
static struct bitmap_data *hires_text_atlas;
static boolean hires_preflight_ok;
static struct
{
	struct font_header *header;
	long font;
} hires_batch_fonts[16];
static short hires_batch_font_count;

#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
static struct rasterizer_text_transform
{
	real scale, anchor_x, anchor_y;
} rasterizer_text_transform = { 1.0f, 0.0f, 0.0f };
#endif

static void rasterizer_text_submit_character(
	struct dynamic_screen_vertex *vertices)
{
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	if (rasterizer_text_transform.scale != 1.0f)
	{
		short index;
		for (index = 0; index < NUMBER_OF_VERTICES_PER_QUADRILATERAL; ++index)
		{
			vertices[index].position.x = rasterizer_text_transform.anchor_x +
				(vertices[index].position.x - rasterizer_text_transform.anchor_x) * rasterizer_text_transform.scale;
			vertices[index].position.y = rasterizer_text_transform.anchor_y +
				(vertices[index].position.y - rasterizer_text_transform.anchor_y) * rasterizer_text_transform.scale;
		}
	}
#endif
	rasterizer_text_draw_character(vertices);
}

static long hires_text_font_get(struct font_header *font)
{
	short index;
	long tag_index;
	struct font_character *capital;
	short first_row, last_row, row, column;
	long replacement = NONE;
	for (index = 0; index < hires_batch_font_count; index++)
		if (hires_batch_fonts[index].header == font)
			return hires_batch_fonts[index].font;
	if (hires_batch_font_count >= 16)
		return NONE;
	tag_index = draw_string_get_font_index(font);
	capital = font_get_character_by_ascii_code(font, 'H');
	first_row = capital ? capital->bitmap_height : 0;
	last_row = -1;
	if (tag_index != NONE && capital && capital->bitmap_width > 0 && capital->bitmap_height > 0 &&
		capital->pixels_offset >= 0 && capital->pixels_offset <= font->pixels.size &&
		(long)capital->bitmap_width * capital->bitmap_height <= font->pixels.size - capital->pixels_offset)
	{
		const byte *pixels = (const byte *)font->pixels.address + capital->pixels_offset;
		for (row = 0; row < capital->bitmap_height; row++)
			for (column = 0; column < capital->bitmap_width; column++)
				if (pixels[(long)row * capital->bitmap_width + column])
				{
					if (row < first_row)
						first_row = row;
					last_row = row;
					break;
				}
		if (last_row >= first_row)
			replacement = text_hires_font(tag_get_name(tag_index), (float)(last_row - first_row + 1));
	}
	hires_batch_fonts[hires_batch_font_count].header = font;
	hires_batch_fonts[hires_batch_font_count++].font = replacement;
	return replacement;
}

static void rasterizer_preflight_hires_character(
	struct parse_string_state *state, struct font_header *font,
	struct font_character *character, unsigned long color,
	short x0, short y0, short x, short y, short dx, short dy)
{
	struct text_hires_glyph glyph;
	long replacement;
	if (!hires_preflight_ok)
		return;
	replacement = hires_text_font_get(font);
	if (replacement == NONE || !text_hires_glyph(replacement, character->character, &glyph))
		hires_preflight_ok = FALSE;
}

static boolean hires_text_prepare(rectangle2d const *bounds, rectangle2d const *clip,
	point2d const *cursor_reference, short height_adjust, const void *string, boolean unicode)
{
	short attempt;
	if (!asset_quality_upres())
		return FALSE;
	if (!hires_text_atlas)
	{
		hires_text_atlas = bitmap_2d_new(256, 256, 0, _bitmap_format_a4r4g4b4);
		if (hires_text_atlas && !rasterizer_bitmap_new(hires_text_atlas))
		{
			bitmap_delete(hires_text_atlas);
			hires_text_atlas = NULL;
		}
		if (hires_text_atlas)
			text_hires_register_atlas((const unsigned long *)hires_text_atlas->hardware_format, 256, 256);
	}
	if (!hires_text_atlas)
		return FALSE;
	/* Repack only between draws. If even an empty atlas cannot hold a string,
	 * draw all of it with the original font instead of losing earlier quads. */
	for (attempt = 0; attempt < 2; attempt++)
	{
		point2d cursor;
		boolean retry;
		if (!text_hires_batch_begin(attempt != 0))
			return FALSE;
		hires_batch_font_count = 0;
		hires_preflight_ok = TRUE;
		if (cursor_reference)
			cursor = *cursor_reference;
		if (unicode)
			draw_unicode_string_preflight(rasterizer_preflight_hires_character, bounds,
				cursor_reference ? &cursor : NULL, clip, height_adjust, (const wchar_t *)string);
		else
			draw_string_preflight(rasterizer_preflight_hires_character, bounds,
				cursor_reference ? &cursor : NULL, clip, height_adjust, (const char *)string);
		if (hires_preflight_ok)
			return TRUE;
		retry = text_hires_batch_full();
		text_hires_batch_end();
		if (!retry)
			break;
	}
	return FALSE;
}

static void rasterizer_draw_hires_character_quad(
	struct parse_string_state *state, struct font_header *font, struct font_character *character, unsigned long color,
	short x0, short y0, short x, short y, boolean drop_shadow)
{
	struct text_hires_glyph glyph;
	struct dynamic_screen_vertex vertices[NUMBER_OF_VERTICES_PER_QUADRILATERAL];
	real left, top, right, bottom, u0, v0, u1, v1;
	real pen_x = (real)(x0 - x + character->bitmap_origin_x);
	real baseline = (real)(y0 - y + character->bitmap_origin_y);
	short pass;
	rectangle2d character_clip;
	if (!text_hires_glyph(hires_text_font_get(font), character->character, &glyph) ||
		glyph.right <= glyph.left || glyph.bottom <= glyph.top)
		return;
	draw_string_get_character_clip(state, &character_clip);
	/* Preserve the tag's advance; center the substitute within that advance. */
	pen_x += ((real)character->character_width - glyph.advance) * 0.5f;
	left = MAX(pen_x + glyph.left, (real)character_clip.x0);
	right = MIN(pen_x + glyph.right, (real)character_clip.x1);
	top = MAX(baseline + glyph.top, (real)character_clip.y0);
	bottom = MIN(baseline + glyph.bottom, (real)character_clip.y1);
	if (right <= left || bottom <= top)
		return;
	u0 = glyph.u0 + (left - pen_x - glyph.left) / (glyph.right - glyph.left) * (glyph.u1 - glyph.u0);
	u1 = glyph.u0 + (right - pen_x - glyph.left) / (glyph.right - glyph.left) * (glyph.u1 - glyph.u0);
	v0 = glyph.v0 + (top - baseline - glyph.top) / (glyph.bottom - glyph.top) * (glyph.v1 - glyph.v0);
	v1 = glyph.v0 + (bottom - baseline - glyph.top) / (glyph.bottom - glyph.top) * (glyph.v1 - glyph.v0);
	for (pass = drop_shadow ? 0 : 1; pass < 2; pass++)
	{
		real offset = pass == 0 ? 1.0f : 0.0f;
		unsigned long vertex_color = pass == 0 ? (global_shadow_color ? global_shadow_color : color & 0xFF000000) : color;
		vertices[0].color = vertices[1].color = vertices[2].color = vertices[3].color = vertex_color;
		vertices[0].position.x = vertices[3].position.x = left + offset;
		vertices[1].position.x = vertices[2].position.x = right + offset;
		vertices[0].position.y = vertices[1].position.y = top + offset;
		vertices[2].position.y = vertices[3].position.y = bottom + offset;
		vertices[0].texture_coordinates.x = vertices[3].texture_coordinates.x = u0;
		vertices[1].texture_coordinates.x = vertices[2].texture_coordinates.x = u1;
		vertices[0].texture_coordinates.y = vertices[1].texture_coordinates.y = v0;
		vertices[2].texture_coordinates.y = vertices[3].texture_coordinates.y = v1;
		rasterizer_text_submit_character(vertices);
	}
}

static void rasterizer_draw_hires_character(
	struct parse_string_state *state, struct font_header *font,
	struct font_character *character, unsigned long color,
	short x0, short y0, short x, short y, short dx, short dy)
{
	rasterizer_draw_hires_character_quad(state, font, character, color, x0, y0, x, y, FALSE);
}

static void rasterizer_draw_hires_character_with_dropshadow(
	struct parse_string_state *state, struct font_header *font,
	struct font_character *character, unsigned long color,
	short x0, short y0, short x, short y, short dx, short dy)
{
	rasterizer_draw_hires_character_quad(state, font, character, color, x0, y0, x, y, TRUE);
}

/* ---------- public code */

void lock_rasterizer_text_data(
	void)
{
	return;
}

void unlock_rasterizer_text_data(
	void)
{
	return;
}

boolean
rasterizer_text_cache_initialize(
	void)
{
	struct bitmap_data *bitmap;
	boolean success = TRUE;

	match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 118, !hardware_character_cache.initialized);

	bitmap = bitmap_2d_new(
		HARDWARE_CHARACTER_CACHE_BITMAP_WIDTH,
		HARDWARE_CHARACTER_CACHE_BITMAP_HEIGHT,
		0,
		_bitmap_format_a4r4g4b4);

	if (bitmap)
	{
		memset(&hardware_character_cache, 0, sizeof(hardware_character_cache));

		if (rasterizer_bitmap_new(bitmap))
		{
			hardware_character_cache.bitmap = bitmap;
			hardware_character_cache.initialized = TRUE;
		}
		else
		{
			error(_error_silent, "### ERROR failed to initialize hardware text cache");
			success = FALSE;
		}
	}
	else
	{
		error(_error_silent, "### ERROR failed to initialize hardware text cache");
		success = FALSE;
	}

	return success;
}

void
rasterizer_text_set_shadow_color(
	pixel32 shadow_color)
{
	global_shadow_color = shadow_color;

	return;
}

void
rasterizer_text_cache_flush(
	void)
{
	struct hardware_character *hardware_character;
	long hardware_character_count;

	if (hardware_character_cache.initialized)
	{
		hardware_character = hardware_character_cache.characters;
		hardware_character_count = MAXIMUM_HARDWARE_CHARACTERS;
		do
		{
			if (hardware_character->character)
				hardware_character->character->hardware_character_index = NONE;
			hardware_character->character = NULL;
			hardware_character++;
		} while (--hardware_character_count);
	}

	return;
}

void
rasterizer_text_cache_dispose(
	void)
{
	if (hires_text_atlas)
	{
		text_hires_dispose();
		bitmap_delete(hires_text_atlas);
		hires_text_atlas = NULL;
	}
	if (hardware_character_cache.initialized)
	{
		rasterizer_text_cache_flush();
		bitmap_delete(hardware_character_cache.bitmap);
		hardware_character_cache.initialized = FALSE;
	}

	return;
}

static void
rasterizer_draw_character(
	struct parse_string_state *state,
	struct font_header *font,
	struct font_character *font_character,
	unsigned long color,
	short x0,
	short y0,
	short x,
	short y,
	short dx,
	short dy)
{
	cache_hardware_format_character(font, font_character);

	if (font_character->hardware_character_index != NONE)
	{
		struct dynamic_screen_vertex vertices[NUMBER_OF_VERTICES_PER_QUADRILATERAL];
		short u0, v0;

		hardware_character_cache_get_origin(font_character->hardware_character_index, &u0, &v0);

		u0 += x;
		v0 += y;

		vertices[0].color = vertices[1].color = vertices[2].color = vertices[3].color = color;

		vertices[0].position.x = vertices[3].position.x = (real)x0;
		vertices[1].position.x = vertices[2].position.x = (real)(x0 + dx);
		vertices[0].position.y = vertices[1].position.y = (real)y0;
		vertices[2].position.y = vertices[3].position.y = (real)(y0 + dy);

		vertices[0].texture_coordinates.x = vertices[3].texture_coordinates.x = (real)u0;
		vertices[1].texture_coordinates.x = vertices[2].texture_coordinates.x = (real)(u0 + dx);
		vertices[0].texture_coordinates.y = vertices[1].texture_coordinates.y = (real)v0;
		vertices[2].texture_coordinates.y = vertices[3].texture_coordinates.y = (real)(v0 + dy);

		rasterizer_text_submit_character(vertices);
	}

	return;
}

void
rasterizer_draw_string(
	rectangle2d const *bounds,
	rectangle2d const *clip,
	point2d *cursor_reference,
	short height_adjust,
	char const *string)
{
	boolean drop_shadow = TRUE;

	if (rasterizer_debug_options.draw_dynamic_screen_geometry
		&& global_window_parameters.rasterizer_target == _rasterizer_target_render_primary)
	{
		struct bitmap_data *bitmap;
		struct rasterizer_dynamic_screen_geometry_parameters parameters;
		rectangle2d window_bounds;
		rectangle2d viewport_bounds;

		magic_number++;

		match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 180, string);

		bitmap = hardware_character_cache_get_bitmap();

		if (bitmap && string[0])
		{
			long length = strlen(string);
			long vertex_count;
			draw_character_proc draw_character;
			boolean hires;

			if (drop_shadow)
			{
				vertex_count = length * NUMBER_OF_VERTICES_PER_QUADRILATERAL * 2;
				draw_character = rasterizer_draw_character_with_dropshadow;
			}
			else
			{
				vertex_count = length * NUMBER_OF_VERTICES_PER_QUADRILATERAL;
				draw_character = rasterizer_draw_character;
			}

			if (!bounds)
			{
				window_bounds = render.camera.window_bounds;
				offset_rectangle2d(
					&window_bounds,
					-render.camera.viewport_bounds.x0,
					-render.camera.viewport_bounds.y0);
			}
			else
			{
				window_bounds = *bounds;
			}

			if (!clip)
			{
				viewport_bounds = render.camera.viewport_bounds;
				offset_rectangle2d(
					&viewport_bounds,
					-render.camera.viewport_bounds.x0,
					-render.camera.viewport_bounds.y0);
			}
			else
			{
				set_rectangle2d(
					&viewport_bounds,
					FLOOR(clip->x0, 0),
					FLOOR(clip->y0, 0),
					MIN(render.camera.viewport_bounds.x1 - render.camera.viewport_bounds.x0, clip->x1),
					MIN(render.camera.viewport_bounds.y1 - render.camera.viewport_bounds.y0, clip->y1));
			}

			hires = hires_text_prepare(&window_bounds, &viewport_bounds, cursor_reference, height_adjust, string, FALSE);
			if (hires)
			{
				bitmap = hires_text_atlas;
				draw_character = drop_shadow ? rasterizer_draw_hires_character_with_dropshadow : rasterizer_draw_hires_character;
			}
			memset(&parameters, 0, sizeof(parameters));
			parameters.map_texture_scale[0].i = 1.0f / (real)bitmap->width;
			parameters.map_texture_scale[0].j = 1.0f / (real)bitmap->height;
			parameters.map_scale[0].i = parameters.map_scale[0].j = 1.0f;
			parameters.meter_parameters = NULL;
			parameters.point_sampled = FALSE;
			/* port: (rasterizer.h) */
			parameters.alpha_weighted = FALSE;
			parameters.framebuffer_blend_function = _shader_framebuffer_blend_function_alpha_blend;
			parameters.map[0] = bitmap;

			rasterizer_text_begin(&parameters);
			draw_string(
				draw_character,
				&window_bounds,
				cursor_reference,
				&viewport_bounds,
				height_adjust,
				string);
			rasterizer_text_end();
			if (hires)
				text_hires_batch_end();
		}
	}

	return;
}

#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
void rasterizer_draw_string_scaled(
	rectangle2d const *bounds,
	rectangle2d const *clip,
	char const *string,
	float scale,
	float anchor_x,
	float anchor_y)
{
	struct rasterizer_text_transform previous = rasterizer_text_transform;
	/* Shrinking about a point inside the viewport preserves stock clipping. */
	rasterizer_text_transform.scale = scale >= 0.5f && scale <= 1.0f ? scale : 1.0f;
	rasterizer_text_transform.anchor_x = anchor_x;
	rasterizer_text_transform.anchor_y = anchor_y;
	rasterizer_draw_string(bounds, clip, NULL, 0, string);
	rasterizer_text_transform = previous;
}
#endif

void
rasterizer_draw_unicode_string(
	rectangle2d const *bounds,
	rectangle2d const *clip,
	point2d *cursor_reference,
	short height_adjust,
	wchar_t const *string)
{
	boolean drop_shadow = TRUE;

	if (rasterizer_debug_options.draw_dynamic_screen_geometry
		&& global_window_parameters.rasterizer_target == _rasterizer_target_render_primary)
	{
		struct bitmap_data *bitmap;
		struct rasterizer_dynamic_screen_geometry_parameters parameters;
		rectangle2d window_bounds;
		rectangle2d viewport_bounds;

		magic_number++;

		match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 310, string);

		bitmap = hardware_character_cache_get_bitmap();

		if (bitmap && string[0])
		{
			long length = ustrlen(string);
			long vertex_count;
			draw_character_proc draw_character;
			boolean hires;

			if (drop_shadow)
			{
				vertex_count = length * NUMBER_OF_VERTICES_PER_QUADRILATERAL * 2;
				draw_character = rasterizer_draw_character_with_dropshadow;
			}
			else
			{
				vertex_count = length * NUMBER_OF_VERTICES_PER_QUADRILATERAL;
				draw_character = rasterizer_draw_character;
			}

			if (!bounds)
			{
				window_bounds = render.camera.window_bounds;
				offset_rectangle2d(
					&window_bounds,
					-render.camera.viewport_bounds.x0,
					-render.camera.viewport_bounds.y0);
			}
			else
			{
				window_bounds = *bounds;
			}

			if (!clip)
			{
				viewport_bounds = render.camera.viewport_bounds;
				offset_rectangle2d(
					&viewport_bounds,
					-render.camera.viewport_bounds.x0,
					-render.camera.viewport_bounds.y0);
			}
			else
			{
				set_rectangle2d(
					&viewport_bounds,
					FLOOR(clip->x0, 0),
					FLOOR(clip->y0, 0),
					MIN(render.camera.viewport_bounds.x1 - render.camera.viewport_bounds.x0, clip->x1),
					MIN(render.camera.viewport_bounds.y1 - render.camera.viewport_bounds.y0, clip->y1));
			}

			hires = hires_text_prepare(&window_bounds, &viewport_bounds, cursor_reference, height_adjust, string, TRUE);
			if (hires)
			{
				bitmap = hires_text_atlas;
				draw_character = drop_shadow ? rasterizer_draw_hires_character_with_dropshadow : rasterizer_draw_hires_character;
			}
			memset(&parameters, 0, sizeof(parameters));
			parameters.map_texture_scale[0].i = 1.0f / (real)bitmap->width;
			parameters.map_texture_scale[0].j = 1.0f / (real)bitmap->height;
			parameters.map_scale[0].i = parameters.map_scale[0].j = 1.0f;
			parameters.meter_parameters = NULL;
			parameters.point_sampled = FALSE;
			/* port: (rasterizer.h) */
			parameters.alpha_weighted = FALSE;
			parameters.framebuffer_blend_function = _shader_framebuffer_blend_function_alpha_blend;
			parameters.map[0] = bitmap;

			rasterizer_text_begin(&parameters);
			draw_unicode_string(
				draw_character,
				&window_bounds,
				cursor_reference,
				&viewport_bounds,
				height_adjust,
				string);
			rasterizer_text_end();
			if (hires)
				text_hires_batch_end();
		}
	}

	return;
}

static void
rasterizer_draw_character_with_dropshadow(
	struct parse_string_state *state,
	struct font_header *font,
	struct font_character *font_character,
	unsigned long color,
	short x0,
	short y0,
	short x,
	short y,
	short dx,
	short dy)
{
	cache_hardware_format_character(font, font_character);

	if (font_character->hardware_character_index != NONE)
	{
		struct dynamic_screen_vertex vertices[NUMBER_OF_VERTICES_PER_QUADRILATERAL];
		real x_offset = 1.0f;
		real y_offset = 1.0f;
		unsigned long shadow_color = global_shadow_color
			? global_shadow_color
			: (color & 0xFF000000);
		real left = (real)x0;
		real right = (real)(x0 + dx);
		real top = (real)y0;
		real bottom = (real)(y0 + dy);
		boolean shadow = TRUE;

		while (TRUE)
		{
			unsigned long vertex_color;
			short u0, v0;

			hardware_character_cache_get_origin(font_character->hardware_character_index, &u0, &v0);

			u0 += x;
			v0 += y;

			vertex_color = shadow ? shadow_color : color;

			vertices[0].color = vertices[1].color = vertices[2].color = vertices[3].color = vertex_color;

			vertices[0].position.x = vertices[3].position.x = left + x_offset;
			vertices[1].position.x = vertices[2].position.x = right + x_offset;
			vertices[0].position.y = vertices[1].position.y = top + y_offset;
			vertices[2].position.y = vertices[3].position.y = bottom + y_offset;

			vertices[0].texture_coordinates.x = vertices[3].texture_coordinates.x = (real)u0;
			vertices[1].texture_coordinates.x = vertices[2].texture_coordinates.x = (real)(u0 + dx);
			vertices[0].texture_coordinates.y = vertices[1].texture_coordinates.y = (real)v0;
			vertices[2].texture_coordinates.y = vertices[3].texture_coordinates.y = (real)(v0 + dy);

			rasterizer_text_submit_character(vertices);

			if (!shadow)
				break;

			shadow = FALSE;
			x_offset = y_offset = 0.0f;
		}
	}

	return;
}

/* ---------- private code */

static struct bitmap_data *
hardware_character_cache_get_bitmap(
	void)
{
	return hardware_character_cache.initialized ? hardware_character_cache.bitmap : NULL;
}

static void
hardware_character_cache_get_origin(
	short hardware_character_index,
	short *x0,
	short *y0)
{
	struct hardware_character *hardware_character =
		&hardware_character_cache.characters[hardware_character_index];

	match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 597, hardware_character_cache.initialized);
	match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 598, hardware_character_index>=0 && hardware_character_index<MAXIMUM_HARDWARE_CHARACTERS);
	match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 599, x0 && y0);

	*x0 = hardware_character->x0 + hardware_character_padding(hardware_character->character);
	*y0 = hardware_character->y0 + hardware_character_padding(hardware_character->character);

	return;
}

/* port: the clear texels around a character in the cache (its cell is that
much larger each side). The cache packs characters edge to edge, which the
Xbox's 640x480 sampled texel for pixel; drawn larger (a fullscreen
display's resolution), each edge pixel blends in half a texel past the
character, from the next character or one the cache dropped, and the text
and its drop shadow showed the cells' borders. A character too large for
the border goes without. */
static short hardware_character_padding(
	struct font_character const *font_character)
{
	return font_character &&
		font_character->bitmap_width + 2 <= HARDWARE_CHARACTER_CACHE_BITMAP_WIDTH &&
		font_character->bitmap_height + 2 <= HARDWARE_CHARACTER_CACHE_BITMAP_HEIGHT ? 1 : 0;
}

static void
flush_hardware_character(
	struct hardware_character *hardware_character)
{
	match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 610, hardware_character);

	if (hardware_character->character)
	{
		hardware_character->character->hardware_character_index = NONE;

		if (hardware_character->character->pad == magic_number)
			error(_error_log, "font cache overwrote character in use");

		hardware_character->character = NULL;
	}

	return;
}

static void
cache_hardware_format_character(
	struct font_header *font,
	struct font_character *font_character)
{
	match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 633, hardware_character_cache.initialized);

	if (font_character->hardware_character_index != NONE)
	{
		match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 637, font_character->hardware_character_index>=0 && font_character->hardware_character_index<MAXIMUM_HARDWARE_CHARACTERS);
		match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 638, font_character==hardware_character_cache.characters[font_character->hardware_character_index].character);
	}
	else
	{
		struct hardware_character *hardware_character;
		byte *source;
		short y0, y1;
		short x, y;
		short next_write_index;
		short padding = hardware_character_padding(font_character);
		short cell_width = font_character->bitmap_width + 2 * padding;
		short cell_height = font_character->bitmap_height + 2 * padding;

		match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 645, font_character->bitmap_width<=HARDWARE_CHARACTER_CACHE_BITMAP_WIDTH);
		match_assert("c:\\halo\\SOURCE\\rasterizer\\rasterizer_text.c", 646, font_character->bitmap_height<=HARDWARE_CHARACTER_CACHE_BITMAP_HEIGHT);

		font_character->pad = magic_number;

		if (cell_width + hardware_character_cache.x0 > HARDWARE_CHARACTER_CACHE_BITMAP_WIDTH)
		{
			hardware_character_cache.x0 = 0;
			hardware_character_cache.y0 += hardware_character_cache.maximum_character_height;
			hardware_character_cache.maximum_character_height = 0;
		}

		if (cell_height + hardware_character_cache.y0 > HARDWARE_CHARACTER_CACHE_BITMAP_HEIGHT)
		{
			hardware_character_cache.y0 = 0;
			hardware_character_cache.x0 = 0;
			hardware_character_cache.maximum_character_height = 0;

			for (;
				hardware_character_cache.read_index != hardware_character_cache.write_index;
				hardware_character_cache.read_index = (hardware_character_cache.read_index + 1) & (MAXIMUM_HARDWARE_CHARACTERS - 1))
			{
				hardware_character = &hardware_character_cache.characters[hardware_character_cache.read_index];

				if (hardware_character->y0 <= 0)
					break;

				flush_hardware_character(hardware_character);
			}
		}

		if (cell_height > hardware_character_cache.maximum_character_height)
		{
			y0 = hardware_character_cache.y0 + hardware_character_cache.maximum_character_height;
			y1 = hardware_character_cache.y0 + cell_height;

			for (;
				hardware_character_cache.read_index != hardware_character_cache.write_index;
				hardware_character_cache.read_index = (hardware_character_cache.read_index + 1) & (MAXIMUM_HARDWARE_CHARACTERS - 1))
			{
				hardware_character = &hardware_character_cache.characters[hardware_character_cache.read_index];

				if (hardware_character->y0 < y0 || hardware_character->y0 >= y1)
					break;

				flush_hardware_character(hardware_character);
			}

			hardware_character_cache.maximum_character_height = cell_height;
		}

		next_write_index = (hardware_character_cache.write_index + 1) & (MAXIMUM_HARDWARE_CHARACTERS - 1);
		if (next_write_index == hardware_character_cache.read_index)
		{
			flush_hardware_character(&hardware_character_cache.characters[hardware_character_cache.read_index]);
			hardware_character_cache.read_index = (hardware_character_cache.read_index + 1) & (MAXIMUM_HARDWARE_CHARACTERS - 1);
		}

		hardware_character = &hardware_character_cache.characters[hardware_character_cache.write_index];
		font_character->hardware_character_index = hardware_character_cache.write_index;

		hardware_character->character = font_character;
		hardware_character->x0 = hardware_character_cache.x0;
		hardware_character->y0 = hardware_character_cache.y0;

		source = (byte *)font->pixels.address + font_character->pixels_offset;

		/* (port: the border clear, white with no alpha as the character's
		own clear texels are) */
		for (y = 0; y < cell_height; y++)
		{
			word *destination = (word *)bitmap_2d_address(
				hardware_character_cache.bitmap,
				hardware_character->x0,
				(short)(hardware_character->y0 + y),
				0);

			for (x = 0; x < cell_width; x++)
			{
				if (y < padding || y >= padding + font_character->bitmap_height ||
					x < padding || x >= padding + font_character->bitmap_width)
				{
					*destination++ = 0x0FFF;
				}
				else
				{
					*destination++ = (word)((*source++ << 8) | 0x0FFF);
				}
			}
		}

		rasterizer_bitmap_changed(hardware_character_cache.bitmap);

		hardware_character_cache.x0 += cell_width;
		hardware_character_cache.write_index = (hardware_character_cache.write_index + 1) & (MAXIMUM_HARDWARE_CHARACTERS - 1);
	}

	return;
}
