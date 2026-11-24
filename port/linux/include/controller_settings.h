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

/* Menu navigation always uses the immediate-press, deliberate-hold cadence.
 * This is presentation/input navigation only, never gameplay button timing. */
#define HALO_MENU_REPEAT_INITIAL_DELAY 500UL
#define HALO_MENU_REPEAT_FAST_INTERVAL 100UL

static __inline int halo_menu_repeat_is_fast(void)
{
	return 1;
}

static __inline unsigned long halo_menu_repeat_milliseconds(void)
{
	return HALO_MENU_REPEAT_FAST_INTERVAL;
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

/* Look Sensitivity is one number in an Xbox profile, 1 to 10, which sets both
 * the turning and the up/down rate from the tables below (player_ui.c). The
 * device settings can set either axis on its own; 0 keeps the profile's. */
#define HALO_CONTROLLER_LOOK_SENSITIVITY_MAX 10

static __inline long halo_controller_look_sensitivity(int vertical)
{
	long value = config_integer(vertical ? "input.look_sensitivity_vertical" :
		"input.look_sensitivity_horizontal");

	return value >= 0 && value <= HALO_CONTROLLER_LOOK_SENSITIVITY_MAX ? value : 0;
}

/* Degrees a second for a setting of 1 to 10: the profile tables' own values
 * (80 to 260 turning, 40 to 130 up and down). */
static __inline float halo_controller_look_rate(int vertical, long sensitivity)
{
	return vertical ? 30.0f + 10.0f * (float)sensitivity : 60.0f + 20.0f * (float)sensitivity;
}

/* Only physical stick axes reach this hook, before keyboard/controller merging. */
int halo_controller_look_active(short gamepad_index,
	short left_x, short left_y, short right_x, short right_y);
/* Which raw axes came from a physical controller in the latest returned packet. */
unsigned halo_controller_physical_axes(short gamepad_index);

#endif
