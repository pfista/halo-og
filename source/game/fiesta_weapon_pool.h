/* Loaded weapon dependencies, independent of scenario pickup placement. Expanded
 * Fiesta caches add the full global arsenal before the level is loaded.
 * Uncut identities are documented Digsite recoveries; reconstructed first-person
 * assets and map-author edits retain their authored behavior. See docs/fiesta.md.
 * All also admits later community weapons with a player first-person interface.
 */
#ifndef __FIESTA_WEAPON_POOL_H
#define __FIESTA_WEAPON_POOL_H

#include "game/weapon_sets.h"
#include "cache/cache_files.h"
#include "tag_files/tag_files.h"

struct fiesta_weapon_iterator
{
	struct tag_iterator tags;
	long weapon_set;
	short next_name;
	short seen_count;
	boolean global_arsenal;
	long seen[9];
};

static void fiesta_weapon_iterator_new(struct fiesta_weapon_iterator *iterator,
	long weapon_set)
{
	iterator->weapon_set = weapon_set;
	iterator->next_name = 0;
	iterator->seen_count = 0;
	iterator->global_arsenal = (weapon_set == GAME_WEAPON_SET_UNCUT ||
		weapon_set == GAME_WEAPON_SET_ALL) &&
		tag_loaded('bipd', "community\\weapon_pack\\player\\cyborg") != NONE;
	tag_iterator_new(&iterator->tags, 'weap');
}

static boolean fiesta_weapon_definition_eligible(long definition_index, long weapon_set)
{
	struct weapon_definition *definition;
	if (definition_index == NONE ||
		object_definition_get(definition_index)->object.type != _object_type_weapon)
		return FALSE;
	definition = weapon_definition_get(definition_index);
	/* Objective items, vehicle guns and AI-only weapons cannot be loadouts. */
	if (TEST_FLAG(definition->weapon.flags, _weapon_must_be_readied_bit))
		return FALSE;
	if ((weapon_set == GAME_WEAPON_SET_UNCUT || weapon_set == GAME_WEAPON_SET_ALL) &&
		(TEST_FLAG(definition->weapon.flags, _weapon_doesnt_count_toward_maximum_bit) ||
		 definition->weapon.interface_definition.first_person_model.index == NONE ||
		 definition->weapon.interface_definition.first_person_animations.index == NONE))
		return FALSE;
	return TRUE;
}

static boolean fiesta_weapon_is_duplicate_flamethrower(long definition_index)
{
	/* Only these reviewed compatibility identities represent the same weapon.
	 * Keep the first eligible one; an invalid canonical tag cannot hide an alias. */
	static char const *names[] =
	{
		"weapons\\flamethrower\\flamethrower",
		"community\\digsite_compat\\weapons\\flamethrower\\flamethrower",
		"community\\weapon_pack\\community\\digsite_compat\\weapons\\flamethrower\\flamethrower",
	};
	char const *name = tag_get_name(definition_index);
	short identity, preferred;
	for (identity = 1; identity < NUMBEROF(names); identity++)
		if (!strcmp(name, names[identity]))
			for (preferred = 0; preferred < identity; preferred++)
				if (fiesta_weapon_definition_eligible(tag_loaded('weap', names[preferred]),
					GAME_WEAPON_SET_ALL)) return TRUE;
	return FALSE;
}

static long fiesta_weapon_iterator_next(struct fiesta_weapon_iterator *iterator)
{
	static char const *retail_names[] =
	{
		"weapons\\assault rifle\\assault rifle",
		"weapons\\needler\\needler",
		"weapons\\pistol\\pistol",
		"weapons\\plasma pistol\\plasma pistol",
		"weapons\\plasma rifle\\plasma rifle",
		"weapons\\rocket launcher\\rocket launcher",
		"weapons\\shotgun\\shotgun",
		"weapons\\sniper rifle\\sniper rifle",
	};
	/* Reviewed against digsite/h1's original recovered weapon tags, rather
	 * than treating every weapon in a Digsite/community cache as historical. */
	static char const *uncut_names[] =
	{
		"weapons\\smg\\smg",
		"weapons\\grenade launcher\\assault rifle",
		"weapons\\chaingun\\chaingun",
		"weapons\\excavator\\excavator",
		"weapons\\gravity_wrench\\gravity_wrench",
		"weapons\\machete\\machete",
		"weapons\\speargun\\speargun",
		"weapons\\space luger\\space luger",
		"weapons\\missile launcher\\missile launcher",
	};
	for (;;)
	{
		long definition_index;
		short seen_index;
		if (iterator->weapon_set == GAME_WEAPON_SET_ALL)
		{
			definition_index = tag_iterator_next(&iterator->tags);
			if (definition_index != NONE &&
				fiesta_weapon_is_duplicate_flamethrower(definition_index))
				continue;
			if (definition_index != NONE && iterator->global_arsenal)
			{
				char const *name = tag_get_name(definition_index);
				char packed_name[512];
				long length;
				/* The global arsenal supplies one reviewed definition for each
				 * imported identity, even when the original map also has it. */
				if (strncmp(name, "community\\weapon_pack\\", 22))
				{
					length = snprintf(packed_name, sizeof(packed_name),
						"community\\weapon_pack\\%s", name);
					if (length >= 0 && length < (long)sizeof(packed_name) &&
						fiesta_weapon_definition_eligible(tag_loaded('weap', packed_name),
							GAME_WEAPON_SET_ALL)) continue;
				}
			}
		}
		else
		{
			char const **names = iterator->weapon_set == GAME_WEAPON_SET_UNCUT ?
				uncut_names : retail_names;
			short count = iterator->weapon_set == GAME_WEAPON_SET_UNCUT ?
				NUMBEROF(uncut_names) : NUMBEROF(retail_names);
			if (iterator->next_name >= count) return NONE;
			definition_index = iterator->global_arsenal ? NONE :
				tag_loaded('weap', names[iterator->next_name]);
			if (definition_index == NONE && iterator->weapon_set == GAME_WEAPON_SET_UNCUT)
			{
				char packed_name[128];
				/* The optional map authoring tool isolates imported dependencies
				 * here, so retail models, HUDs and weapon parameters stay intact. */
				sprintf(packed_name, "community\\weapon_pack\\%s", names[iterator->next_name]);
				definition_index = tag_loaded('weap', packed_name);
			}
			iterator->next_name++;
			if (definition_index == NONE) continue;
		}
		if (definition_index == NONE) return NONE;
		if (!fiesta_weapon_definition_eligible(definition_index, iterator->weapon_set))
			continue;
		/* Cache iteration visits each datum once. Named pools additionally guard
		 * against multiple canonical identities resolving to the same datum. */
		if (iterator->weapon_set != GAME_WEAPON_SET_ALL)
		{
			for (seen_index = 0; seen_index < iterator->seen_count; seen_index++)
				if (iterator->seen[seen_index] == definition_index) break;
			if (seen_index < iterator->seen_count) continue;
			iterator->seen[iterator->seen_count++] = definition_index;
		}
		return definition_index;
	}
}

#endif
