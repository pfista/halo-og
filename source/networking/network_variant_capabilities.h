#ifndef __NETWORK_VARIANT_CAPABILITIES_H
#define __NETWORK_VARIANT_CAPABILITIES_H

#include "game/performance_variant.h"
#include "game/weapon_sets.h"
#include "networking/network_performance_protocol.h"
#include "networking/network_powerup_sync.h"

/* Weapon-set support is a transport capability, not a saved Performance aid.
 * Older peers clamp these saved IDs to Normal. Require support even without
 * Fiesta so every machine prepares the same weapon population before loading. */
static inline unsigned network_game_variant_required_capabilities(
	struct game_variant const *variant)
{
	return performance_variant_get_flags(variant) |
		(game_variant_uses_expanded_weapon_set(variant) ?
		 NETWORK_PERFORMANCE_EXPANDED_WEAPONS_CAPABILITY : 0) |
		(game_variant_uses_expanded_weapon_set(variant) &&
		 (performance_variant_get_flags(variant) & _performance_option_fiesta) ?
		 NETWORK_PERFORMANCE_GLOBAL_ARSENAL_CAPABILITY : 0);
}

/* The experimental policy belongs to the hosted session, not saved padding. */
static inline unsigned network_game_host_required_capabilities(
	struct game_variant const *variant)
{
	return network_game_variant_required_capabilities(variant) |
		(network_powerup_sync_host_enabled() ? NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG : 0);
}

#endif
