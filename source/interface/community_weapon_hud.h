/* Scoped presentation for the reviewed Digsite AR grenade launcher.
 * Fiesta copies retain the full source identity under community/weapon_pack.
 * Do not match arbitrary custom tags by basename. */
#ifndef __COMMUNITY_WEAPON_HUD_H
#define __COMMUNITY_WEAPON_HUD_H

static __inline boolean community_weapon_hud_path_matches(
	char const *name,
	char const *original)
{
	char const prefix[] = "community\\weapon_pack\\";
	return name && (!csstrcasecmp(name, original) ||
		(!csstrncmp(name, prefix, sizeof(prefix)-1) &&
		 !csstrcasecmp(name + sizeof(prefix)-1, original)));
}

#endif
