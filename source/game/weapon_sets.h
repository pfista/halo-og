/* Optional restored-asset weapon sets retain distinct saved/wire IDs. */
#ifndef __WEAPON_SETS_H
#define __WEAPON_SETS_H

#include "game/game_engine.h"

enum
{
	GAME_WEAPON_SET_UNCUT = 11,
	GAME_WEAPON_SET_ALL = 12,
};

static inline int game_variant_uses_expanded_weapon_set(
	struct game_variant const *variant)
{
	return variant && (variant->universal_variant.weapon_set == GAME_WEAPON_SET_UNCUT ||
		variant->universal_variant.weapon_set == GAME_WEAPON_SET_ALL);
}

#endif
