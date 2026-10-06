/* Native starting-equipment choices keep the authored Custom/Generic order. */
#ifndef __STARTING_EQUIPMENT_H
#define __STARTING_EQUIPMENT_H

#include "game/performance_variant.h"

enum
{
	_starting_equipment_custom = 0,
	_starting_equipment_generic,
	_starting_equipment_fiesta,
};

static inline short starting_equipment_get(struct game_variant const *variant)
{
	if (performance_variant_get_flags(variant) & _performance_option_fiesta)
		return _starting_equipment_fiesta;
	return variant && (variant->universal_variant.flags & (1u << 5)) ?
		_starting_equipment_generic : _starting_equipment_custom;
}

static inline boolean starting_equipment_set(struct game_variant *variant, short mode)
{
	unsigned flags;
	if (!variant || mode < _starting_equipment_custom || mode > _starting_equipment_fiesta)
		return FALSE;
	flags = performance_variant_get_flags(variant);
	/* A build that cannot decode Fiesta falls back to the original Generic
	 * loadout. Capability checks prevent it from participating in Fiesta games. */
	if (mode == _starting_equipment_custom) variant->universal_variant.flags &= ~(1u << 5);
	else variant->universal_variant.flags |= 1u << 5;
	if (mode == _starting_equipment_fiesta)
		performance_variant_set_flags(variant, flags | _performance_option_fiesta);
	else if (flags & _performance_option_fiesta)
		performance_variant_set_flags(variant, flags & ~_performance_option_fiesta);
	/* Untouched Custom/Generic variants retain all old unused padding bytes. */
	return TRUE;
}

#endif /* __STARTING_EQUIPMENT_H */
