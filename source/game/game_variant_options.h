/* Version 11's PC gametype-options wire record. Included after game_variant.
 * Keep its complete layout for interoperability while this fork continues to
 * host its existing Xbox rules. The helper below classifies unsupported options
 * for review; best-effort v11 client admission does not call it. Protocol,
 * capability, packet and map checks remain separate admission requirements.
 */
#ifndef __GAME_VARIANT_OPTIONS_H
#define __GAME_VARIANT_OPTIONS_H

struct game_variant_options
{
	short time_limit;
	short friendly_fire;
	short friendly_fire_penalty;
	short vehicle_respawn_time;
	boolean auto_team_balance;
	byte radar_players;
	byte vehicle_set[2];
	byte vehicle_counts[2][6];
	byte loadout;
	byte primary_weapon;
	byte secondary_weapon;
	byte pad;
};

typedef char verify_game_variant_options_size[sizeof(struct game_variant_options) == 0x1C ? 1 : -1];

/* Identical to upstream v11's Xbox-rule defaults: friendly fire on, category
 * loadout, no time/respawn/penalty/team-balancing overrides, the variant's radar
 * and vehicle set. The primary/secondary fields are inactive with this loadout.
 */
static inline void game_variant_options_default(
	struct game_variant const *variant,
	struct game_variant_options *options)
{
	csmemset(options, 0, sizeof(*options));
	options->primary_weapon = 2; /* assault rifle */
	options->secondary_weapon = 3; /* pistol */
	options->radar_players = variant &&
		!TEST_FLAG(variant->universal_variant.flags, _game_variant_draw_object_in_motion_sensor_bit) ? 2 : 0;
	options->vehicle_set[0] = options->vehicle_set[1] =
		variant ? (byte)variant->universal_variant.vehicle_set : 0;
}

static inline char const *game_variant_options_unsupported(
	struct game_variant const *variant,
	struct game_variant_options const *options)
{
	struct game_variant_options defaults;

	game_variant_options_default(variant, &defaults);
	/* Distributed clients receive the host's match end, damage, object
	 * creations/deletions and player spawns/teams. These options only affect
	 * those host decisions, so accept their valid v11 values. Our own hosts
	 * still use the Xbox defaults above. Rules affecting the client's local
	 * presentation or map initialization still need compatible support. */
	if (options->time_limit < 0) return "invalid time limit";
	/* v11: on, off, shields only, explosives only. Damage is host-owned. */
	if (options->friendly_fire < 0 || options->friendly_fire > 3) return "invalid friendly fire mode";
	if (options->friendly_fire_penalty < 0) return "invalid friendly fire penalty";
	if (options->vehicle_respawn_time < 0) return "invalid vehicle respawn time";
	if (options->auto_team_balance > 1) return "invalid automatic team balancing";
	if (options->radar_players != defaults.radar_players) return "radar players";
	if (options->vehicle_set[0] != defaults.vehicle_set[0] ||
		options->vehicle_set[1] != defaults.vehicle_set[1]) return "per-team vehicle sets";
	if (options->loadout) return "custom loadout";
	if (variant->universal_variant.weapon_set < 0 ||
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
		/* Halo OG's restored-asset sets occupy saved/wire IDs 11 and 12. */
		variant->universal_variant.weapon_set > 12) return "PC weapon set";
#else
		variant->universal_variant.weapon_set > 10) return "PC weapon set";
#endif
	/* Counts are inactive unless a vehicle set is custom (already rejected).
	 * Likewise primary/secondary weapons are inactive in category loadouts.
	 */
	return NULL;
}

#endif
