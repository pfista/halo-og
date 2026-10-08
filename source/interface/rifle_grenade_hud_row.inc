/* Imported Digsite AR grenade launcher presentation. The authored ammo art is
 * a staggered two-column stack in a 128x128 A8Y8 bitmap. Draw its three pairs
 * beside each other, preserving each pair's source UVs and meter thresholds.
 * This changes draw placement only; cached tags and stock Xbox HUDs stay intact.
 * Included by hud_draw.c after hud_draw_bitmap_with_meter is declared. */
#include "interface/community_weapon_hud.h"

static boolean hud_draw_rifle_grenade_row(
	long bitmap_group_index,
	short sequence_index,
	void *meter_parameters,
	struct bitmap_data const *bitmap,
	struct hud_absolute_placement_definition const *absolute_placement,
	struct hud_placement_definition const *placement,
	real_rectangle2d const *clip,
	pixel32 color,
	boolean in_multiplayer,
	boolean is_interface_bitmap)
{
	static short const source_bounds[3][4] =
	{
		{ 46, 0, 110, 40 },
		{ 23, 44, 87, 84 },
		{ 0, 88, 64, 128 }
	};
	char const *name;
	short pair_index;

	if (bitmap_group_index == NONE || sequence_index != 0 || !bitmap ||
		bitmap->width != 128 || bitmap->height != 128 || bitmap->format != 3 ||
		is_interface_bitmap || absolute_placement->corner != _hud_anchor_top_left ||
		((placement->offset.x != 164 || placement->offset.y != 21) &&
		 (placement->offset.x != 112 || placement->offset.y != 5)) ||
		placement->scale.i != 0.25f || placement->scale.j != 0.25f ||
		placement->multiplayer_scaling_flags != 0 ||
		(clip && (clip->x0 != 0.0f || clip->y0 != 0.0f ||
			clip->x1 != 1.0f || clip->y1 != 1.0f)))
		return FALSE;

	name = tag_get_name(bitmap_group_index);
	if (!community_weapon_hud_path_matches(name,
		"digsite\\ui\\hud\\bitmaps\\rifle_grenade_alpha") &&
		!community_weapon_hud_path_matches(name,
		"digsite\\ui\\hud\\bitmaps\\rifle_grenade_meter"))
		return FALSE;

	for (pair_index = 0; pair_index < 3; pair_index++)
	{
		struct hud_placement_definition row_placement = *placement;
		real_rectangle2d row_clip;

		/* The source icon pitch is 28 texels. At the reviewed quarter scale,
		 * pairs advance 14 HUD units and span 44 units together. Center that
		 * row beneath the reviewed 37.25-unit count panel at X=164. The automatic
		 * MCC conversion also emitted the known 112,5 placement; restore that
		 * variant to the same secondary HUD position without editing its tag. */
		row_placement.offset.x = (short)(161 + pair_index * 14);
		row_placement.offset.y = 21;
		row_clip.x0 = source_bounds[pair_index][0] / 128.0f;
		row_clip.y0 = source_bounds[pair_index][1] / 128.0f;
		row_clip.x1 = source_bounds[pair_index][2] / 128.0f;
		row_clip.y1 = source_bounds[pair_index][3] / 128.0f;
		hud_draw_bitmap_with_meter(
			meter_parameters,
			bitmap,
			absolute_placement,
			&row_placement,
			&row_clip,
			1.0f,
			0.0f,
			color,
			in_multiplayer,
			FALSE,
			FALSE);
	}

	return TRUE;
}
