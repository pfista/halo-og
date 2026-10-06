/* Display-resolution font rasterization, selectively adapted from upstream
 * 0182da81. This core has no GL/Metal dependencies: adapters upload its RGBA
 * atlas. A batch cannot repack its atlas, so a full/unsupported string safely
 * returns to the original bitmap font before any glyph draw is submitted. */
#include "text_hires.h"
#include "port_config.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* stb's bitmap API returns void even when its scratch allocation fails. Track
 * that failure so the caller can select the original font for the whole draw. */
static int raster_allocation_failed;
static void *text_hires_raster_malloc(size_t size, void *user)
{
	void *memory = malloc(size);
	(void)user;
	if (!memory)
		raster_allocation_failed = 1;
	return memory;
}
#define STBTT_malloc(size,user) text_hires_raster_malloc(size,user)
#define STBTT_free(memory,user) free(memory)
#define STBTT_STATIC
#define STB_TRUETYPE_IMPLEMENTATION
#include "../../third_party/stb/stb_truetype.h"

#define MAXIMUM_FONTS 32
#define ATLAS_SIZE 2048
#define ATLAS_PADDING 2
#define GLYPH_CACHE_SIZE 4096

static struct
{
	const char *tag;
	stbtt_fontinfo info;
	float scale, cap_height;
} fonts[MAXIMUM_FONTS];
static long font_count;

static struct
{
	long font;
	unsigned long code;
	int x, y, width, height, left, top;
	float advance;
} glyphs[GLYPH_CACHE_SIZE];

static unsigned char *atlas;
static float atlas_scale;
static int pack_x, pack_y, pack_row_height, batch_active, batch_full;
static unsigned long placeholder_data, placeholder_width, placeholder_height;
static uint64_t atlas_revision;
static uint64_t row_revision[ATLAS_SIZE];
static void (*atlas_dispose_proc)(void);

static int names_differ(const char *a, const char *b)
{
	while (*a && tolower((unsigned char)*a) == tolower((unsigned char)*b))
	{
		a++;
		b++;
	}
	return tolower((unsigned char)*a) != tolower((unsigned char)*b);
}

static int atlas_reset(float scale)
{
	size_t index;
	if (!atlas)
		atlas = malloc((size_t)ATLAS_SIZE * ATLAS_SIZE * 4);
	if (!atlas)
		return 0;
	for (index = 0; index < (size_t)ATLAS_SIZE * ATLAS_SIZE; index++)
	{
		atlas[index * 4] = atlas[index * 4 + 1] = atlas[index * 4 + 2] = 255;
		atlas[index * 4 + 3] = 0;
	}
	for (index = 0; index < GLYPH_CACHE_SIZE; index++)
		glyphs[index].font = -1;
	atlas_scale = scale;
	pack_x = pack_y = pack_row_height = 0;
	atlas_revision++;
	for (index = 0; index < ATLAS_SIZE; index++)
		row_revision[index] = atlas_revision;
	return 1;
}

long text_hires_font(const char *tag_name, float cap_height)
{
	unsigned int index;
	long font;
	if (!asset_quality_upres() || !tag_name || !isfinite(cap_height) || cap_height <= 0.0f || cap_height > ATLAS_SIZE)
		return -1;
	for (font = 0; font < font_count; font++)
		if (!names_differ(fonts[font].tag, tag_name) && fonts[font].cap_height == cap_height)
			return font;
	if (font_count >= MAXIMUM_FONTS)
		return -1;
	for (index = 0; index < text_hires_embedded_count; index++)
	{
		const struct text_hires_embedded *embedded = &text_hires_embedded[index];
		const unsigned char *data = (const unsigned char *)embedded->data;
		int x0, y0, x1, y1, offset;
		if (!embedded->tag || names_differ(embedded->tag, tag_name) || !data || embedded->size < 12)
			continue;
		offset = stbtt_GetFontOffsetForIndex(data, 0);
		if (offset < 0 || (unsigned int)offset >= embedded->size ||
			!stbtt_InitFont(&fonts[font_count].info, data, offset) ||
			!stbtt_GetCodepointBox(&fonts[font_count].info, 'H', &x0, &y0, &x1, &y1) || y1 <= y0)
			return -1;
		fonts[font_count].tag = embedded->tag;
		fonts[font_count].cap_height = cap_height;
		fonts[font_count].scale = cap_height / (float)(y1 - y0);
		return font_count++;
	}
	return -1;
}

int text_hires_covers(long font, unsigned long code)
{
	if (!asset_quality_upres() || font < 0 || font >= font_count || code > 0x10ffffUL ||
		(code >= 0xd800UL && code <= 0xdfffUL))
		return 0;
	return code < 32 || code == ' ' || stbtt_FindGlyphIndex(&fonts[font].info, (int)code) != 0;
}

int text_hires_batch_begin(int reset)
{
	float scale;
	if (batch_active || !asset_quality_upres() || !placeholder_data ||
		!placeholder_width || !placeholder_height)
		return 0;
	scale = halo_screen_pixel_scale();
	if (!isfinite(scale) || scale <= 0.0f || scale > 64.0f)
		return 0;
	if ((!atlas || scale != atlas_scale || reset) && !atlas_reset(scale))
		return 0;
	batch_active = 1;
	batch_full = 0;
	return 1;
}

void text_hires_batch_end(void)
{
	batch_active = 0;
}

int text_hires_batch_full(void)
{
	return batch_full;
}

int text_hires_glyph(long font, unsigned long code, struct text_hires_glyph *glyph)
{
	unsigned long slot;
	long probe;
	if (!batch_active || !glyph || !text_hires_covers(font, code))
		return 0;
	slot = ((unsigned long)font * 2654435761UL ^ code * 40503UL) & (GLYPH_CACHE_SIZE - 1);
	for (probe = 0; probe < GLYPH_CACHE_SIZE; probe++, slot = (slot + 1) & (GLYPH_CACHE_SIZE - 1))
		if (glyphs[slot].font == -1 || (glyphs[slot].font == font && glyphs[slot].code == code))
			break;
	if (probe == GLYPH_CACHE_SIZE)
	{
		batch_full = 1;
		return 0;
	}
	if (glyphs[slot].font == -1)
	{
		float pixels = fonts[font].scale * atlas_scale;
		int index = stbtt_FindGlyphIndex(&fonts[font].info, (int)code);
		int x0 = 0, y0 = 0, x1 = 0, y1 = 0, advance = 0, bearing = 0;
		int width, height, cell_width, cell_height, next_x = pack_x, next_y = pack_y, row_height = pack_row_height;
		if (index && code >= 32)
		{
			stbtt_GetGlyphBitmapBox(&fonts[font].info, index, pixels, pixels, &x0, &y0, &x1, &y1);
			stbtt_GetGlyphHMetrics(&fonts[font].info, index, &advance, &bearing);
		}
		width = x1 - x0;
		height = y1 - y0;
		cell_width = width + 2 * ATLAS_PADDING;
		cell_height = height + 2 * ATLAS_PADDING;
		if (width < 0 || height < 0 || cell_width > ATLAS_SIZE || cell_height > ATLAS_SIZE)
			return 0;
		if (width && height)
		{
			unsigned char *coverage;
			int x, y;
			if (next_x + cell_width > ATLAS_SIZE)
			{
				next_x = 0;
				next_y += row_height;
				row_height = 0;
			}
			if (next_y + cell_height > ATLAS_SIZE)
			{
				batch_full = 1;
				return 0;
			}
			coverage = malloc((size_t)width * height);
			if (!coverage)
				return 0;
			memset(coverage, 0, (size_t)width * height);
			raster_allocation_failed = 0;
			stbtt_MakeGlyphBitmap(&fonts[font].info, coverage, width, height, width, pixels, pixels, index);
			if (raster_allocation_failed)
			{
				free(coverage);
				return 0;
			}
			for (y = 0; y < height; y++)
				for (x = 0; x < width; x++)
					atlas[((size_t)(next_y + ATLAS_PADDING + y) * ATLAS_SIZE + next_x + ATLAS_PADDING + x) * 4 + 3] = coverage[(size_t)y * width + x];
			free(coverage);
			pack_x = next_x + cell_width;
			pack_y = next_y;
			pack_row_height = cell_height > row_height ? cell_height : row_height;
			atlas_revision++;
			for (y = next_y; y < next_y + cell_height; y++)
				row_revision[y] = atlas_revision;
		}
		glyphs[slot].font = font;
		glyphs[slot].code = code;
		glyphs[slot].x = next_x + ATLAS_PADDING;
		glyphs[slot].y = next_y + ATLAS_PADDING;
		glyphs[slot].width = width;
		glyphs[slot].height = height;
		glyphs[slot].left = x0;
		glyphs[slot].top = y0;
		glyphs[slot].advance = advance * fonts[font].scale;
	}
	glyph->left = glyphs[slot].left / atlas_scale;
	glyph->top = glyphs[slot].top / atlas_scale;
	glyph->right = (glyphs[slot].left + glyphs[slot].width) / atlas_scale;
	glyph->bottom = (glyphs[slot].top + glyphs[slot].height) / atlas_scale;
	glyph->advance = glyphs[slot].advance;
	glyph->u0 = (float)glyphs[slot].x * placeholder_width / ATLAS_SIZE;
	glyph->v0 = (float)glyphs[slot].y * placeholder_height / ATLAS_SIZE;
	glyph->u1 = (float)(glyphs[slot].x + glyphs[slot].width) * placeholder_width / ATLAS_SIZE;
	glyph->v1 = (float)(glyphs[slot].y + glyphs[slot].height) * placeholder_height / ATLAS_SIZE;
	return 1;
}

void text_hires_register_atlas(const unsigned long *texture, unsigned long width, unsigned long height)
{
	placeholder_data = texture ? texture[1] : 0;
	placeholder_width = width;
	placeholder_height = height;
}

int text_hires_atlas_pixels(unsigned long data, struct text_hires_atlas_pixels *out)
{
	return text_hires_atlas_pixels_since(data, 0, out);
}

int text_hires_atlas_pixels_since(unsigned long data, uint64_t uploaded_revision,
	struct text_hires_atlas_pixels *out)
{
	unsigned long row;
	if (!out)
		return 0;
	memset(out, 0, sizeof(*out));
	if (!asset_quality_upres() || !data || data != placeholder_data || !atlas)
		return 0;
	out->rgba = atlas;
	out->width = out->height = ATLAS_SIZE;
	out->revision = atlas_revision;
	out->dirty_top = ATLAS_SIZE;
	for (row = 0; row < ATLAS_SIZE; row++)
		if (row_revision[row] > uploaded_revision || uploaded_revision > atlas_revision)
		{
			if (row < out->dirty_top)
				out->dirty_top = row;
			out->dirty_bottom = row + 1;
		}
	return 1;
}

void text_hires_dispose(void)
{
	if (atlas_dispose_proc)
	{
		atlas_dispose_proc();
		atlas_dispose_proc = NULL;
	}
	free(atlas);
	atlas = NULL;
	font_count = 0;
	batch_active = 0;
	placeholder_data = placeholder_width = placeholder_height = 0;
	atlas_revision++;
}

void text_hires_set_atlas_dispose_proc(void (*dispose)(void))
{
	atlas_dispose_proc = dispose;
}
