/* OpenCE protocol 20 gametype options. Included after game_variant.
 * Preserve the complete wire layout, including no_map_weapons. Hosts default
 * to original rules; clients apply the host record through OpenCE gameplay. */
#ifndef __GAME_VARIANT_OPTIONS_H
#define __GAME_VARIANT_OPTIONS_H

/* port: the PC version's gametype options that the Xbox's variant has not
(its gametype editor's, port/linux/game/menu_functions.c). A saved gametype
keeps them after its signature (playlist_profile.c), the network game
carries them (network_game_manager.h), and the game plays by them
(game_variant_options_get). */
enum
{
	_friendly_fire_on = 0,
	_friendly_fire_off,
	_friendly_fire_shields_only,
	_friendly_fire_explosives_only,
	NUMBER_OF_FRIENDLY_FIRE_MODES
};

enum
{
	/* other players on the motion tracker: all (the variant's draw object
	in motion sensor bit set), friends only, none */
	_radar_players_all = 0,
	_radar_players_friends,
	_radar_players_none,
	NUMBER_OF_RADAR_PLAYERS
};

enum
{
	_loadout_category = 0,
	_loadout_custom,
	NUMBER_OF_LOADOUTS
};

enum
{
	_loadout_weapon_none = 0,
	_loadout_weapon_random,
	_loadout_weapon_assault_rifle,
	_loadout_weapon_pistol,
	_loadout_weapon_shotgun,
	_loadout_weapon_sniper_rifle,
	_loadout_weapon_rocket_launcher,
	_loadout_weapon_plasma_pistol,
	_loadout_weapon_plasma_rifle,
	_loadout_weapon_needler,
	NUMBER_OF_LOADOUT_WEAPONS
};

enum
{
	_variant_vehicle_warthog = 0,
	_variant_vehicle_ghost,
	_variant_vehicle_scorpion,
	_variant_vehicle_rocket_warthog,
	_variant_vehicle_banshee,
	_variant_vehicle_gun_turret,
	NUMBER_OF_VARIANT_VEHICLES,
	MAXIMUM_VARIANT_VEHICLE_COUNT = 4,
	/* a team's vehicles: those of a vehicle set (universal_variant's
	vehicle_set values), else its counts */
	VARIANT_VEHICLE_SET_CUSTOM = 0xFF
};

/* (the starting equipment, generic or the map's, is the variant's own:
_game_variant_generic_starting_equipment_bit) */
struct game_variant_options
{
	/* minutes; 0: none */
	short time_limit;
	short friendly_fire;
	/* seconds added to a team killer's respawn */
	short friendly_fire_penalty;
	/* seconds; 0: never (the Xbox game's) */
	short vehicle_respawn_time;
	boolean auto_team_balance;
	byte radar_players;
	/* red's and blue's (free for all: red's) */
	byte vehicle_set[2];
	byte vehicle_counts[2][NUMBER_OF_VARIANT_VEHICLES];
	/* the weapons: the weapon set's (category), else each player starts
	with these (custom: _loadout_weapon_none, _random, or a weapon) */
	byte loadout;
	byte primary_weapon;
	byte secondary_weapon;
	/* no weapons spawn on the map (its grenades and powerups do): for
	a loadout of none, melee only */
	boolean no_map_weapons;
};

typedef char verify_game_variant_options_size[sizeof(struct game_variant_options) == 0x1C ? 1 : -1];

/* Identical to upstream protocol 20's Xbox-rule defaults: friendly fire on, category
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

/* Diagnostic for the original client defaults retained by the fixture suite.
 * Protocol 20 gameplay supports these radar, vehicle and loadout overrides;
 * this helper does not participate in network admission. */
static inline char const *game_variant_options_unsupported(
	struct game_variant const *variant,
	struct game_variant_options const *options)
{
	struct game_variant_options defaults;

	game_variant_options_default(variant, &defaults);
	/* Host-owned rules permit all valid upstream values. */
	if (options->time_limit < 0) return "invalid time limit";
	/* Protocol 20: on, off, shields only, explosives only. Damage is host-owned. */
	if (options->friendly_fire < 0 || options->friendly_fire > 3) return "invalid friendly fire mode";
	if (options->friendly_fire_penalty < 0) return "invalid friendly fire penalty";
	if (options->vehicle_respawn_time < 0) return "invalid vehicle respawn time";
	if (options->auto_team_balance > 1) return "invalid automatic team balancing";
	if (options->radar_players != defaults.radar_players) return "radar players";
	if (options->vehicle_set[0] != defaults.vehicle_set[0] ||
		options->vehicle_set[1] != defaults.vehicle_set[1]) return "per-team vehicle sets";
	if (options->loadout) return "custom loadout";
	if (options->no_map_weapons) return "no map weapons";
	if (variant->universal_variant.weapon_set < 0 ||
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
		/* Halo OG's restored-asset sets occupy saved/wire IDs 14 and 15. */
		variant->universal_variant.weapon_set > 15) return "PC weapon set";
#else
		variant->universal_variant.weapon_set > 13) return "PC weapon set";
#endif
	/* Counts are inactive unless a vehicle set is custom (already rejected).
	 * Likewise primary/secondary weapons are inactive in category loadouts.
	 */
	return NULL;
}

#endif
