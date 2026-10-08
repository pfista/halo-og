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
	/* Removes the blue active-camouflage tint; selected before the match. */
	_performance_option_hardcore_camo = 256,
	/* Listener-specific audio remains outside the older network capabilities. */
	_performance_option_self_movement = 4096,
	_performance_option_self_weapon_ready = 8192,
	PERFORMANCE_SELF_SOUND_FLAGS = _performance_option_self_movement |
		_performance_option_self_weapon_ready,
	/* Match rules are selected before starting, independently of aid presets. */
	PERFORMANCE_MATCH_RULE_FLAGS = 480,
	/* The existing Practice preset keeps the original movement/weapon audio. */
	PERFORMANCE_PRACTICE_FLAGS = 7,
	/* Pro keeps markers and input delay off, with precise opening shots,
	 * stronger camouflage and movement/equip sounds audible only to their owner. */
	PERFORMANCE_PRO_FLAGS = _performance_option_match_timer |
		_performance_option_timer_audio | _performance_option_self_movement |
		_performance_option_self_weapon_ready | _performance_option_hardcore |
		_performance_option_hardcore_camo,
	PERFORMANCE_OPTIONS_MASK = 511 | PERFORMANCE_SELF_SOUND_FLAGS,
	/* Nominal Xbox duration; one 30 Hz simulation update is 33.333 ms.
	 * Preserve this duration if simulation frequency changes in the future. */
	PERFORMANCE_INPUT_DELAY_MILLISECONDS = 33,
};

enum
{
	_performance_sound_mode_normal = 0,
	_performance_sound_mode_self = 1,
	_performance_sound_mode_silent = 2,
};

static inline short performance_variant_sound_mode(unsigned flags,
	unsigned silent_bit, unsigned self_bit)
{
	return (flags & silent_bit) ? _performance_sound_mode_silent :
		(flags & self_bit) ? _performance_sound_mode_self : _performance_sound_mode_normal;
}

static inline unsigned performance_variant_sound_flags(short mode,
	unsigned silent_bit, unsigned self_bit)
{
	return mode == _performance_sound_mode_self ? self_bit :
		mode == _performance_sound_mode_silent ? silent_bit : 0;
}

static inline boolean performance_variant_flags_valid(unsigned flags)
{
	return !(flags & ~PERFORMANCE_OPTIONS_MASK) &&
		!((flags & _performance_option_silent_movement) &&
		  (flags & _performance_option_self_movement)) &&
		!((flags & _performance_option_silent_weapon_ready) &&
		  (flags & _performance_option_self_weapon_ready));
}

/* Preset names are derived from the saved rules. Fiesta is a separate loadout;
 * Default and Practice retain their existing independent match-rule behavior. */
static inline short performance_variant_preset(unsigned flags)
{
	if ((flags & ~_performance_option_fiesta) == PERFORMANCE_PRO_FLAGS)
		return 2;
	flags &= ~PERFORMANCE_MATCH_RULE_FLAGS;
	return flags == 0 ? 0 : flags == PERFORMANCE_PRACTICE_FLAGS ? 1 : 3;
}

/* These six named padding bytes are unused by the retail variant. Keeping the
 * extension here preserves the 104-byte ABI, existing save signature, editor
 * dirty checks and whole-variant copies (including rename/save-as). The format
 * is PFO, version 1, low flags, low flags XOR 0xA5. Version 2 adds Hardcore
 * Camo implicitly and uses low flags XOR 0xA4. This distinct checksum prevents
 * a damaged version from silently changing the camo rule. Existing options
 * retain their exact version-1 bytes. Version 3 uses pad4's upper bits for
 * camo (4), Just Me movement (8) and Just Me weapons (16), with low bits 3.
 * Its check byte is the low flags XOR 0xA5 XOR pad4. It is used only when
 * Just Me is selected; previous Normal/Silent saves stay byte-identical.
 * Stock/off is all zeros. Old padding,
 * unknown versions/flags and damaged extensions always mean all options off.
 * Never encode options in game_variant.flags: the editor excludes that field
 * when checking for changes, and the upper byte identifies default profiles. */
static inline unsigned performance_variant_get_flags(
	struct game_variant const *variant)
{
	struct universal_variant const *settings;
	unsigned flags, version, check;

	if (!variant)
		return 0;

	settings = &variant->universal_variant;
	flags = settings->pad5;
	version = settings->pad4;
	if (settings->pad0 != 'P' || settings->pad1 != 'F' ||
		settings->pad2 != 'O')
		return 0;
	if (version == 1 || version == 2)
	{
		check = version == 2 ? 0xA4 : 0xA5;
		if (version == 2) flags |= _performance_option_hardcore_camo;
	}
	else if ((version & ~28u) == 3 && (version & 24u))
	{
		check = 0xA5 ^ version;
		if (version & 4) flags |= _performance_option_hardcore_camo;
		if (version & 8) flags |= _performance_option_self_movement;
		if (version & 16) flags |= _performance_option_self_weapon_ready;
	}
	else return 0;
	if (settings->pad6 != (byte)(settings->pad5 ^ check) ||
		!performance_variant_flags_valid(flags)) return 0;
	return flags;
}

static inline void performance_variant_set_flags(
	struct game_variant *variant,
	unsigned flags)
{
	struct universal_variant *settings;
	unsigned version, check;

	if (!variant)
		return;

	settings = &variant->universal_variant;
	/* Reject an unknown option set as a whole, rather than enabling its known
	 * subset. A bad extension must never silently opt a game into practice. */
	if (!performance_variant_flags_valid(flags))
		flags = 0;
	version = (flags & _performance_option_hardcore_camo) ? 2 : (flags ? 1 : 0);
	check = version == 2 ? 0xA4 : 0xA5;
	if (flags & PERFORMANCE_SELF_SOUND_FLAGS)
	{
		version = 3 | ((flags & _performance_option_hardcore_camo) ? 4 : 0) |
			((flags & _performance_option_self_movement) ? 8 : 0) |
			((flags & _performance_option_self_weapon_ready) ? 16 : 0);
		check = 0xA5 ^ version;
	}

	settings->pad0 = flags ? 'P' : 0;
	settings->pad1 = flags ? 'F' : 0;
	settings->pad2 = flags ? 'O' : 0;
	settings->pad4 = (byte)version;
	settings->pad5 = (byte)flags;
	settings->pad6 = flags ? (byte)(flags ^ check) : 0;
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
