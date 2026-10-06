/* Device-wide native controller preferences. Retail Xbox response is the default. */
#ifndef HALO_CONTROLLER_SETTINGS_H
#define HALO_CONTROLLER_SETTINGS_H

#include "port_config.h"

#define HALO_CONTROLLER_DEADZONE_DEFAULT 9000
#define HALO_CONTROLLER_DEADZONE_MAX 16000
#define HALO_CONTROLLER_AXIS_LEFT_X 1u
#define HALO_CONTROLLER_AXIS_LEFT_Y 2u
#define HALO_CONTROLLER_AXIS_RIGHT_X 4u
#define HALO_CONTROLLER_AXIS_RIGHT_Y 8u

/* Local menu-only opt-in; the original quarter-second cadence remains default.
 * Read live so accepting Controller settings takes effect without a restart. */
#define HALO_MENU_REPEAT_INITIAL_DELAY 750UL
#define HALO_MENU_REPEAT_FAST_INTERVAL 150UL

static __inline int halo_menu_repeat_is_fast(void)
{
	return config_boolean("input.fast_menu_repeat");
}

static __inline unsigned long halo_menu_repeat_milliseconds(void)
{
	return halo_menu_repeat_is_fast() ? HALO_MENU_REPEAT_FAST_INTERVAL : 250UL;
}

static __inline short halo_controller_deadzone(long value)
{
	return value >= 0 && value <= HALO_CONTROLLER_DEADZONE_MAX ?
		(short)value : HALO_CONTROLLER_DEADZONE_DEFAULT;
}

static __inline short halo_controller_deadzone_for_stick(int right_stick)
{
	return halo_controller_deadzone(config_integer(right_stick ?
		"input.right_stick_deadzone" : "input.left_stick_deadzone"));
}

/* Only physical stick axes reach this hook, before keyboard/controller merging. */
int halo_controller_look_active(short gamepad_index,
	short left_x, short left_y, short right_x, short right_y);
/* Which raw axes came from a physical controller in the latest returned packet. */
unsigned halo_controller_physical_axes(short gamepad_index);

#endif
