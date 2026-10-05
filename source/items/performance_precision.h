/* Optional meeting-requested precision rule, independent of tag edits.
 * Slots are the Xbox globals.weapon_list roles used by game_engine.c; an
 * authored weapon replacing the pistol/sniper role inherits that role. */
#ifndef __PERFORMANCE_PRECISION_H
#define __PERFORMANCE_PRECISION_H

static inline int performance_precision_zero_initial_spread(unsigned flags,
    int multiplayer, int player_controlled, long weapon_slot,
    short trigger_index, int zoomed)
{
    return (flags & 64u) && multiplayer && player_controlled && trigger_index == 0 &&
        (weapon_slot == 4 || (weapon_slot == 9 && !zoomed));
}

#endif
