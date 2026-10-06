/* Native menu input kept separate from the merged gameplay controller packet. */
#ifndef HALO_MENU_NAVIGATION_H
#define HALO_MENU_NAVIGATION_H

#define HALO_MENU_DIRECTION_UP 1u
#define HALO_MENU_DIRECTION_DOWN 2u
#define HALO_MENU_DIRECTION_LEFT 4u
#define HALO_MENU_DIRECTION_RIGHT 8u
#define HALO_MENU_KEYBOARD_MOVE_SHIFT 4

struct halo_menu_keyboard_event
{
	/* D-pad bindings occupy the low four bits; movement bindings the next four.
	 * Held movement directions cancel opposing keys, as the left stick does. */
	unsigned pressed, released, held;
};

/* Fresh SDL transitions, in order. OS key repeat never adds a press. */
int halo_menu_keyboard_next(struct halo_menu_keyboard_event *event);
/* Actual held directions, without the gameplay press latch; opposing movement
 * keys cancel. Fresh edges retain their physical key's direction bindings. */
unsigned halo_menu_keyboard_held(void);
/* Discard pending transitions, retaining actual held keys. */
void halo_menu_keyboard_clear(void);

struct halo_menu_navigation_state
{
	unsigned dpad;
	short left_x, left_y, right_x, right_y;
	unsigned physical_axes;
};

/* Latest raw navigation values without keyboard navigation, including physical
 * gamepads and mouse/wheel bindings. Apply the engine's stick processing once. */
int halo_menu_navigation_read(short gamepad_index, struct halo_menu_navigation_state *state);

#endif
