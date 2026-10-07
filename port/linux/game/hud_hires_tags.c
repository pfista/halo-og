/*
HUD_HIRES_TAGS.C

The bitmaps the high-res HUD's textures stand for (port/linux/src/hud_hires.c),
found in each map's tags as it loads (scenario_tags_load): every map holds
its own copy of the HUD's bitmap groups.

A bitmap's pixels are loaded into the texture cache's memory at its
base_address (xbox_texture_cache.c), which it keeps until its cache block is
reused (when cache_block_index and base_address are cleared). The texture
cache of the platform layer uploads the pixels at an address whenever they
are written there, and asks hud_hires_asset_at which bitmap they are: a block
reused for another bitmap, or a map unloaded, is a write, which asks again.
*/

#include "cseries.h"
#include "bitmaps/bitmap_group.h"
#include "bitmaps/bitmap_group_lookup.h"
#include "cache/cache_files.h"
#include "tag_files/tag_files.h"
#include "tag_files/tag_groups.h"

/* the platform layer's (port/linux/src) */
void platform_log(char const *format, ...);
long hud_hires_asset_count(void);
char const *hud_hires_asset_tag(long asset);
long hud_hires_asset_bitmap(long asset);
long hud_hires_asset_fits(long asset, long width, long height);

void hud_hires_tags_loaded(void);
void hud_hires_tags_unloaded(void);
long hud_hires_asset_at(unsigned long address, long width, long height);

/* ---------- constants */

enum
{
	INITIAL_HIRES_BITMAP_CAPACITY = 128,
	/* Stay below the cseries debug allocator's maximum pointer size. */
	MAXIMUM_HIRES_REGISTRY_BYTES = 0x0FFFFFFF,
};

/* ---------- globals */

struct hud_hires_bitmap
{
	struct bitmap_data *bitmap;
	long asset;
};
static struct hud_hires_bitmap *hires_bitmaps = NULL;
static long hires_bitmap_count = 0;
static long hires_bitmap_capacity = 0;

/* ---------- private code */

static boolean hud_hires_tag_matches(
	char const *name,
	char const *original)
{
	static char const *prefixes[] =
	{
		"__native_weapons\\og\\",
		"__native_hud\\stock\\",
	};
	long prefix;

	if (!name)
		return FALSE;
	if (!csstrcasecmp(name, original))
		return TRUE;

	/* The converter retains the full original path after a 16-digit
	   fingerprint. A matching basename or arbitrary suffix is not identity;
	   the platform layer also checks the original pixels before replacing art. */
	for (prefix = 0; prefix < sizeof(prefixes) / sizeof(prefixes[0]); prefix++)
	{
		long length = csstrlen(prefixes[prefix]);
		char const *fingerprint;
		long digit;

		if (csstrncmp(name, prefixes[prefix], length))
			continue;
		fingerprint = name + length;
		for (digit = 0; digit < 16; digit++)
		{
			char value = fingerprint[digit];
			if (!((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f')))
				break;
		}
		if (digit == 16 && fingerprint[16] == '\\' &&
			!csstrcasecmp(fingerprint + 17, original))
			return TRUE;
	}
	return FALSE;
}

static boolean hud_hires_register_bitmap(
	struct bitmap_data *bitmap,
	long asset)
{
	if (hires_bitmap_count == hires_bitmap_capacity)
	{
		long capacity;
		struct hud_hires_bitmap *records;

		if (hires_bitmap_capacity >
			MAXIMUM_HIRES_REGISTRY_BYTES / sizeof(*hires_bitmaps) / 2)
			return FALSE;
		capacity = hires_bitmap_capacity ? hires_bitmap_capacity * 2 :
			INITIAL_HIRES_BITMAP_CAPACITY;
		records = malloc(capacity * sizeof(*records));
		if (!records)
			return FALSE;
		if (hires_bitmaps)
		{
			memcpy(records, hires_bitmaps, hires_bitmap_count * sizeof(*records));
			free(hires_bitmaps);
		}
		hires_bitmaps = records;
		hires_bitmap_capacity = capacity;
	}
	hires_bitmaps[hires_bitmap_count].bitmap = bitmap;
	hires_bitmaps[hires_bitmap_count].asset = asset;
	hires_bitmap_count++;
	return TRUE;
}

/* ---------- public code */

void hud_hires_tags_loaded(
	void)
{
	long asset_count = hud_hires_asset_count();
	long asset;
	long missing = 0;
	long present = 0;

	hud_hires_tags_unloaded();
	for (asset = 0; asset < asset_count; asset++)
	{
		struct tag_iterator iterator;
		long group_index;
		boolean found = FALSE;
		boolean registered = FALSE;

		/* Both the source's shared bitmap and private OG copies may be resident.
		   Register every eligible copy so the actual draw can select its artwork. */
		tag_iterator_new(&iterator, BITMAP_GROUP_TAG);
		while ((group_index = tag_iterator_next(&iterator)) != NONE)
		{
			struct bitmap_data *bitmap;
			if (!hud_hires_tag_matches(tag_get_name(group_index), hud_hires_asset_tag(asset)))
				continue;
			bitmap = bitmap_group_try_and_get_bitmap(group_index,
				(short)hud_hires_asset_bitmap(asset));
			if (!bitmap)
				continue;
			found = TRUE;
			if (!hud_hires_asset_fits(asset, bitmap->width, bitmap->height))
			{
				platform_log("high-res hud: %s bitmap %ld is %dx%d here, which its texture does not fit",
					tag_get_name(group_index), hud_hires_asset_bitmap(asset), bitmap->width, bitmap->height);
				continue;
			}
			if (!hud_hires_register_bitmap(bitmap, asset))
			{
				platform_log("high-res hud: bitmap registry allocation failed; retaining available originals");
				return;
			}
			registered = TRUE;
		}
		if (!found)
			missing++; /* the main menu's map has only some of the HUD */
		if (registered)
			present++;
	}
	platform_log("high-res hud: %ld of %ld assets in this map, %ld bitmap copies (%ld not in it)",
		present, asset_count, hires_bitmap_count, missing);

	return;
}

void hud_hires_tags_unloaded(
	void)
{
	if (hires_bitmaps)
		free(hires_bitmaps);
	hires_bitmaps = NULL;
	hires_bitmap_count = 0;
	hires_bitmap_capacity = 0;

	return;
}

long hud_hires_asset_at(
	unsigned long address,
	long width,
	long height)
{
	long index;

	for (index = 0; index < hires_bitmap_count; index++)
	{
		struct bitmap_data *bitmap = hires_bitmaps[index].bitmap;

		if (bitmap->cache_block_index != NONE && bitmap->base_address != NULL &&
			(unsigned long)bitmap->base_address == address &&
			bitmap->width == width &&
			bitmap->height == height)
		{
			return hires_bitmaps[index].asset;
		}
	}

	return NONE;
}
