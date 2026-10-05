/* Fixed nominal 33 ms action delay. The current simulation step is 1/30 s. */
#ifndef __PLAYER_INPUT_DELAY_H
#define __PLAYER_INPUT_DELAY_H
#pragma once

/* A future simulation-rate change must preserve the setting's duration rather
 * than silently redefining it as one shorter tick. */
typedef char player_input_delay_rate_assert[TICKS_PER_SECOND == 30 ? 1 : -1];

struct player_input_delay
{
	boolean valid;
	long update_number;
	long player_index;
	long unit_index;
	struct player_action pending;
	struct player_action selected;
};

static inline void player_input_delay_reset(struct player_input_delay *delay)
{
	csmemset(delay, 0, sizeof(*delay));
}

/* Called once per logical simulation update, after display-frame button
 * accumulation and before prediction, transmission or one-shot latching.
 * Identity includes datum generations so input never crosses player lives.
 * Repeated selection of an update must not advance the buffer a second time. */
static inline void player_input_delay_select(
	struct player_input_delay *delay,
	boolean enabled,
	long update_number,
	long player_index,
	long unit_index,
	struct player_action const *sampled,
	real_euler_angles2d const *idle_facing,
	struct player_action *selected)
{
	if (!enabled)
	{
		player_input_delay_reset(delay);
		*selected = *sampled;
		return;
	}
	if (delay->valid && delay->player_index == player_index &&
		delay->unit_index == unit_index && delay->update_number == update_number)
	{
		*selected = delay->selected;
		return;
	}
	if (delay->valid && delay->player_index == player_index &&
		delay->unit_index == unit_index && update_number > delay->update_number &&
		update_number - delay->update_number == 1)
	{
		*selected = delay->pending;
	}
	else
	{
		/* No prior sample: hold the unit's existing aim, without executing
		 * the newly sampled movement, buttons or inventory choices early. */
		csmemset(selected, 0, sizeof(*selected));
		selected->desired_facing = *idle_facing;
		selected->desired_weapon_index = NONE;
		selected->desired_grenade_index = NONE;
		selected->desired_zoom_level = NONE;
	}
	delay->valid = player_index != NONE && unit_index != NONE;
	delay->update_number = update_number;
	delay->player_index = player_index;
	delay->unit_index = unit_index;
	delay->pending = *sampled;
	delay->selected = *selected;
}

#endif /* __PLAYER_INPUT_DELAY_H */
