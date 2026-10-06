/* Optional display-resolution glyphs. Original font tags still own advances,
 * wrapping, baselines, colors and clipping. Overpass is an authored substitute
 * for Interstate, rather than a claim of identical Xbox font outlines. */
#ifndef TEXT_HIRES_H
#define TEXT_HIRES_H

#include <stdint.h>

struct text_hires_embedded
{
	const char *tag;
	const char *file;
	const unsigned int *data;
	unsigned int size;
};
extern const struct text_hires_embedded text_hires_embedded[];
extern const unsigned int text_hires_embedded_count;

struct text_hires_glyph
{
	float left, top, right, bottom;
	float u0, v0, u1, v1;
	float advance;
};

long text_hires_font(const char *tag_name, float cap_height);
int text_hires_covers(long font, unsigned long code);
/* Successful empty glyphs have zero width/height. The caller must preflight a
 * complete string before submitting quads; glyph lookup never resets an atlas. */
int text_hires_glyph(long font, unsigned long code, struct text_hires_glyph *glyph);
int text_hires_batch_begin(int reset);
int text_hires_batch_full(void);
void text_hires_batch_end(void);
void text_hires_register_atlas(const unsigned long *texture, unsigned long width, unsigned long height);
void text_hires_dispose(void);
/* An adapter may release its own cache when the placeholder is disposed. */
void text_hires_set_atlas_dispose_proc(void (*dispose)(void));

/* Backend-neutral, white RGB with glyph coverage in alpha. The revision is
 * monotonic, and reading never clears another renderer's pending update. */
struct text_hires_atlas_pixels
{
	const unsigned char *rgba;
	unsigned long width, height;
	uint64_t revision;
	unsigned long dirty_top, dirty_bottom;
};
int text_hires_atlas_pixels(unsigned long data, struct text_hires_atlas_pixels *out);
/* Each adapter keeps its own uploaded revision. Dirty rows are the union of
 * changes since that revision; no acknowledgement consumes another reader. */
int text_hires_atlas_pixels_since(unsigned long data, uint64_t uploaded_revision,
	struct text_hires_atlas_pixels *out);

/* Renderer adapter: physical pixels for each unit of the game's 480 lines. */
float halo_screen_pixel_scale(void);

#endif
