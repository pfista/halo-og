/* Optional practice and match rules stored in the original signed variant. */
#ifndef __PERFORMANCE_VARIANT_H
#define __PERFORMANCE_VARIANT_H
#pragma once

#include "game/game_engine.h"

enum
{
	_performance_option_match_timer = 1,
	_performance_option_spawn_markers = 2,
	_performance_option_timer_audio = 4,
	_performance_option_silent_movement = 8,
	_performance_option_silent_weapon_ready = 16,
	_performance_option_input_delay = 32,
	_performance_option_hardcore = 64,
	/* Starting Equipment selects Fiesta; it is not a Performance menu aid. */
	_performance_option_fiesta = 128,
	/* Match rules are selected before starting, independently of aid presets. */
	PERFORMANCE_MATCH_RULE_FLAGS = 224,
	/* The existing Practice preset keeps the original movement/weapon audio. */
	PERFORMANCE_PRACTICE_FLAGS = 7,
	PERFORMANCE_OPTIONS_MASK = 255,
	/* Nominal Xbox duration; one 30 Hz simulation update is 33.333 ms.
	 * Preserve this duration if simulation frequency changes in the future. */
	PERFORMANCE_INPUT_DELAY_MILLISECONDS = 33,
};

/* These six named padding bytes are unused by the retail variant. Keeping the
 * extension here preserves the 104-byte ABI, existing save signature, editor
 * dirty checks and whole-variant copies (including rename/save-as). The format
 * is PFO, version 1, flags, flags XOR 0xA5. Stock/off is all zeros. Old padding,
 * unknown versions/flags and damaged extensions always mean all options off.
 * Fiesta occupies the final flags-byte bit; future rules need a new format.
 * Never encode options in game_variant.flags: the editor excludes that field
 * when checking for changes, and the upper byte identifies default profiles. */
static inline unsigned performance_variant_get_flags(
	struct game_variant const *variant)
{
	struct universal_variant const *settings;
	unsigned flags;

	if (!variant)
		return 0;

	settings = &variant->universal_variant;
	flags = settings->pad5;
	if (settings->pad0 != 'P' || settings->pad1 != 'F' ||
		settings->pad2 != 'O' || settings->pad4 != 1 ||
		(flags & ~PERFORMANCE_OPTIONS_MASK) != 0 ||
		settings->pad6 != (byte)(flags ^ 0xA5))
		return 0;

	return flags;
}

static inline void performance_variant_set_flags(
	struct game_variant *variant,
	unsigned flags)
{
	struct universal_variant *settings;

	if (!variant)
		return;

	settings = &variant->universal_variant;
	/* Reject an unknown option set as a whole, rather than enabling its known
	 * subset. A bad extension must never silently opt a game into practice. */
	if ((flags & ~PERFORMANCE_OPTIONS_MASK) != 0)
		flags = 0;

	settings->pad0 = flags ? 'P' : 0;
	settings->pad1 = flags ? 'F' : 0;
	settings->pad2 = flags ? 'O' : 0;
	settings->pad4 = flags ? 1 : 0;
	settings->pad5 = (byte)flags;
	settings->pad6 = flags ? (byte)(flags ^ 0xA5) : 0;
}

static inline unsigned performance_variant_get_input_delay_milliseconds(
	struct game_variant const *variant)
{
	return (performance_variant_get_flags(variant) & _performance_option_input_delay) ?
		PERFORMANCE_INPUT_DELAY_MILLISECONDS : 0;
}

static inline boolean performance_variant_set_input_delay_milliseconds(
	struct game_variant *variant,
	unsigned milliseconds)
{
	unsigned flags;
	if (!variant || (milliseconds != 0 && milliseconds != PERFORMANCE_INPUT_DELAY_MILLISECONDS))
		return FALSE;
	flags = performance_variant_get_flags(variant) & ~_performance_option_input_delay;
	if (milliseconds) flags |= _performance_option_input_delay;
	performance_variant_set_flags(variant, flags);
	return TRUE;
}

#endif /* __PERFORMANCE_VARIANT_H */
