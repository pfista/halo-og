/* Presentation-only System Link prototype carried by the existing variant.
 * The low byte retains all Xbox rule bits. Current native builds transmit and
 * sign the complete variant; these unused upper bits require no wire-layout,
 * protocol, scheduling or gameplay-rule changes. Older builds ignore the view.
 * A complete marker avoids interpreting arbitrary old flags as an opt-in.
 */
#ifndef __TEAMMATE_VIEW_VARIANT_H
#define __TEAMMATE_VIEW_VARIANT_H

#include "game/game_engine.h"

#define TEAMMATE_VIEW_VARIANT_MASK 0xFFFFFF00UL
#define TEAMMATE_VIEW_VARIANT_MARKER 0x53535000UL

static inline boolean teammate_view_variant_enabled(struct game_variant const *variant)
{
	return variant && variant->universal_variant.teams &&
		(variant->universal_variant.flags & TEAMMATE_VIEW_VARIANT_MASK) == TEAMMATE_VIEW_VARIANT_MARKER;
}

static inline boolean teammate_view_variant_set_enabled(struct game_variant *variant, boolean enabled)
{
	unsigned long extension;
	if (!variant || (enabled && !variant->universal_variant.teams))
		return FALSE;
	extension = variant->universal_variant.flags & TEAMMATE_VIEW_VARIANT_MASK;
	/* Preserve unknown extensions instead of overwriting another rule set. */
	if (extension && extension != TEAMMATE_VIEW_VARIANT_MARKER)
		return FALSE;
	variant->universal_variant.flags = (variant->universal_variant.flags & ~TEAMMATE_VIEW_VARIANT_MASK) |
		(enabled ? TEAMMATE_VIEW_VARIANT_MARKER : 0);
	return TRUE;
}

#endif
