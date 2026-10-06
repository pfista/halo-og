/*
EVENT_MANAGER.C

symbols in this file:
000CB700 0030:
	_event_manager_initialize (0000)
000CB730 0020:
	_event_manager_dispose (0000)
000CB750 0020:
	_event_manager_flush (0000)
000CB770 0010:
	_event_manager_suppress (0000)
000CB780 00c0:
	_get_next_event (0000)
000CB840 0010:
	_event_manager_time_of_last_event (0000)
000CB850 0300:
	_code_000cb850 (0000)
000CBB50 0110:
	_event_manager_update (0000)
002706D8 0066:
	??_C@_0GG@GKBBBOFI@event?5?$CG?$CG?5?$CI?$CIlocal_player_index?$DO?$DN0@ (0000)
00270740 0029:
	??_C@_0CJ@HBEODFJG@c?3?2halo?2SOURCE?2interface?2event_m@ (0000)
00453B60 0168:
	_event_manager_globals (0000)
*/

/* ---------- headers */

#include "cseries.h"
#include "cseries_windows.h"
#include "event_manager.h"
#include "input.h"
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
#include "controller_settings.h"
#include "menu_navigation.h"
#endif

/* ---------- constants */

enum
{
	_event_type_null,
	_event_type_left_stick,
	_event_type_right_stick,
	_event_type_button,

	STICK_EVENT_THRESHOLD = 29490,
	STICK_EVENT_REPEAT_MILLISECONDS = 250
};

#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
#define MENU_STICK_REPEAT_INTERVAL halo_menu_repeat_milliseconds()
#else
#define MENU_STICK_REPEAT_INTERVAL STICK_EVENT_REPEAT_MILLISECONDS
#endif

/* ---------- macros */

/* ---------- structures */

struct event_manager_state
{
	boolean initialized;
	boolean suppressed;
	short __unknown2;
	unsigned long time_of_last_event;
	struct event_record events[MAXIMUM_GAMEPADS][8];
};

struct event_manager_globals
{
	struct event_manager_state state;
	unsigned long stick_event_times[NUMBER_OF_GAMEPAD_STICKS][MAXIMUM_GAMEPADS];
	long previous_stick_axes[NUMBER_OF_GAMEPAD_STICKS][2][MAXIMUM_GAMEPADS];
};

typedef char verify_event_manager_state_size[
	sizeof(struct event_manager_state) == 0x108 ? 1 : -1];
typedef char verify_event_manager_globals_size[
	sizeof(struct event_manager_globals) == 0x168 ? 1 : -1];

/* ---------- prototypes */

static void queue_event(
	struct event_record *event,
	short controller_index);

/* ---------- globals */

struct event_manager_globals event_manager_globals = { 0 };

#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
/* Faster is a local menu policy. Keep its state and queue outside the retail
 * layout, and never change the gameplay button hold counters. */
enum
{
	FAST_MENU_EVENT_CAPACITY = 256,
	FAST_MENU_STICK_RELEASE_THRESHOLD = 24576,
	FAST_MENU_STICK_DIRECTION_MARGIN = 3277,
	FAST_MENU_KEYBOARD_DIRECTIONS = 8
};

struct fast_menu_repeat_state
{
	unsigned long pressed_time;
	unsigned long repeat_time;
	boolean active;
	boolean repeating;
};

struct fast_menu_stick_repeat_state
{
	short direction;
	struct fast_menu_repeat_state repeat;
};

struct fast_menu_event_queue
{
	struct event_record events[FAST_MENU_EVENT_CAPACITY];
	unsigned head;
	unsigned count;
};

static struct fast_menu_repeat_state fast_keyboard_repeats[FAST_MENU_KEYBOARD_DIRECTIONS];
static struct fast_menu_repeat_state fast_dpad_repeats[MAXIMUM_GAMEPADS][4];
static struct fast_menu_stick_repeat_state fast_stick_repeats[NUMBER_OF_GAMEPAD_STICKS][MAXIMUM_GAMEPADS];
static struct fast_menu_event_queue fast_menu_events[MAXIMUM_GAMEPADS];
static boolean fast_menu_was_enabled;

static void fast_menu_reset(void)
{
	csmemset(fast_keyboard_repeats, 0, sizeof(fast_keyboard_repeats));
	csmemset(fast_dpad_repeats, 0, sizeof(fast_dpad_repeats));
	csmemset(fast_stick_repeats, 0, sizeof(fast_stick_repeats));
	csmemset(fast_menu_events, 0, sizeof(fast_menu_events));
}

static void fast_menu_repeat_begin(struct fast_menu_repeat_state *state,
	boolean down, unsigned long time)
{
	state->active = down;
	state->repeating = FALSE;
	state->pressed_time = state->repeat_time = time;
}

static boolean fast_menu_repeat_due(struct fast_menu_repeat_state *state,
	boolean down, unsigned long time)
{
	if (!down)
	{
		fast_menu_repeat_begin(state, FALSE, time);
		return FALSE;
	}
	if (!state->active)
	{
		fast_menu_repeat_begin(state, TRUE, time);
		return TRUE;
	}
	if (state->repeating ?
		time - state->repeat_time >= HALO_MENU_REPEAT_FAST_INTERVAL :
		time - state->pressed_time >= HALO_MENU_REPEAT_INITIAL_DELAY)
	{
		/* One repeat per input update, including after a stalled frame. */
		state->repeating = TRUE;
		state->repeat_time = time;
		return TRUE;
	}
	return FALSE;
}

static void fast_menu_queue_event(struct event_record *event,
	short controller_index, unsigned long time)
{
	struct fast_menu_event_queue *queue = &fast_menu_events[controller_index];
	if (queue->count == FAST_MENU_EVENT_CAPACITY)
		return;
	event->controller_index = controller_index;
	queue->events[(queue->head + queue->count) % FAST_MENU_EVENT_CAPACITY] = *event;
	queue->count++;
	if (event->type != _event_type_null)
		event_manager_globals.state.time_of_last_event = time;
}

static void fast_menu_post_direction(short controller_index, short source,
	short direction)
{
	struct event_record event = {0};
	if (source == _event_type_button)
	{
		event.type = _event_type_button;
		event.data.button.index = (byte)(_gamepad_binary_button_dpad_up + direction);
		event.data.button.value = 1;
	}
	else
	{
		event.type = source;
		if (direction == 0) event.data.stick.y = SHORT_MAX;
		else if (direction == 1) event.data.stick.y = SHORT_MIN;
		else if (direction == 2) event.data.stick.x = SHORT_MIN;
		else event.data.stick.x = SHORT_MAX;
	}
	queue_event(&event, controller_index);
}

static void fast_menu_update_keyboard(unsigned long time)
{
	struct halo_menu_keyboard_event event;
	unsigned held;
	short direction;
	while (halo_menu_keyboard_next(&event))
	{
		for (direction = 0; direction < FAST_MENU_KEYBOARD_DIRECTIONS; direction++)
		{
			unsigned mask = 1u << direction;
			boolean down = (event.held & mask) != 0;
			/* Apply each held snapshot, including neutral/opposing keys between
			 * polls. A release can restart a remaining alias silently. */
			if (!down || !fast_keyboard_repeats[direction].active ||
				((event.pressed | event.released) & mask))
				fast_menu_repeat_begin(&fast_keyboard_repeats[direction],
					down, time);
			if ((event.pressed & mask) && (direction < 4 || down))
				fast_menu_post_direction(0, direction < 4 ? _event_type_button :
					_event_type_left_stick, direction % 4);
		}
	}
	held = halo_menu_keyboard_held();
	for (direction = 0; direction < FAST_MENU_KEYBOARD_DIRECTIONS; direction++)
		if (fast_menu_repeat_due(&fast_keyboard_repeats[direction],
			(held & (1u << direction)) != 0, time))
			fast_menu_post_direction(0, direction < 4 ? _event_type_button :
				_event_type_left_stick, direction % 4);
}

static short fast_menu_stick_direction(short x, short y, short previous)
{
	/* Prefer the dominant axis, retaining the current one around a diagonal.
	 * Separate thresholds prevent jitter from creating fresh presses. */
	if ((previous == 0 && y >= FAST_MENU_STICK_RELEASE_THRESHOLD) ||
		(previous == 1 && y <= -FAST_MENU_STICK_RELEASE_THRESHOLD))
	{
		if (ABS(x) < STICK_EVENT_THRESHOLD ||
			ABS(x) - ABS(y) < FAST_MENU_STICK_DIRECTION_MARGIN) return previous;
	}
	if ((previous == 2 && x <= -FAST_MENU_STICK_RELEASE_THRESHOLD) ||
		(previous == 3 && x >= FAST_MENU_STICK_RELEASE_THRESHOLD))
	{
		if (ABS(y) < STICK_EVENT_THRESHOLD ||
			ABS(y) - ABS(x) < FAST_MENU_STICK_DIRECTION_MARGIN) return previous;
	}
	if (ABS(y) >= STICK_EVENT_THRESHOLD && (ABS(y) > ABS(x) ||
		(ABS(y) == ABS(x) && previous < 2)))
		return y > 0 ? 0 : 1;
	if (ABS(x) >= STICK_EVENT_THRESHOLD)
		return x < 0 ? 2 : 3;
	return NONE;
}

static void fast_menu_update_navigation(short controller_index, unsigned long time)
{
	struct halo_menu_navigation_state navigation = {0};
	short direction, stick;
	if (input_has_gamepad(controller_index) && input_get_gamepad_state(controller_index))
		halo_menu_navigation_read(controller_index, &navigation);
	for (direction = 0; direction < 4; direction++)
		if (fast_menu_repeat_due(&fast_dpad_repeats[controller_index][direction],
			(navigation.dpad & (1u << direction)) != 0, time))
			fast_menu_post_direction(controller_index, _event_type_button, direction);
	for (stick = 0; stick < NUMBER_OF_GAMEPAD_STICKS; stick++)
	{
		struct fast_menu_stick_repeat_state *state = &fast_stick_repeats[stick][controller_index];
		short dead_range = halo_controller_deadzone_for_stick(stick == _gamepad_stick_right);
		unsigned x_mask = 1u << (stick * 2), y_mask = x_mask << 1;
		short x = fix_dead_zone(stick ? navigation.right_x : navigation.left_x,
			navigation.physical_axes & x_mask ? dead_range : HALO_CONTROLLER_DEADZONE_DEFAULT);
		short y = fix_dead_zone(stick ? navigation.right_y : navigation.left_y,
			navigation.physical_axes & y_mask ? dead_range : HALO_CONTROLLER_DEADZONE_DEFAULT);
		short current = fast_menu_stick_direction(x, y,
			state->repeat.active ? state->direction : NONE);
		if (current != state->direction)
			fast_menu_repeat_begin(&state->repeat, FALSE, time);
		state->direction = current;
		if (fast_menu_repeat_due(&state->repeat, current != NONE, time))
			fast_menu_post_direction(controller_index,
				stick ? _event_type_right_stick : _event_type_left_stick, current);
	}
}
#endif

/* ---------- public code */

void event_manager_initialize(
	void)
{
	csmemset(&event_manager_globals.state, 0, sizeof(event_manager_globals.state));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	fast_menu_reset();
	fast_menu_was_enabled = FALSE;
	halo_menu_keyboard_clear();
#endif
	event_manager_globals.state.time_of_last_event = system_milliseconds();
	event_manager_globals.state.initialized = TRUE;
	return;
}

void event_manager_dispose(
	void)
{
	csmemset(&event_manager_globals.state, 0, sizeof(event_manager_globals.state));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	fast_menu_reset();
	halo_menu_keyboard_clear();
#endif
	return;
}

void event_manager_flush(
	void)
{
	csmemset(event_manager_globals.state.events, 0, sizeof(event_manager_globals.state.events));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	/* Called after each processed menu frame; retain the ongoing hold timers. */
	csmemset(fast_menu_events, 0, sizeof(fast_menu_events));
#endif
	return;
}

void event_manager_suppress(
	boolean suppress)
{
	event_manager_globals.state.suppressed = suppress;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	if (suppress)
	{
		fast_menu_reset();
		halo_menu_keyboard_clear();
	}
#endif
	return;
}

boolean get_next_event(
	struct event_record *event,
	short local_player_index)
{
	boolean result = FALSE;

	match_assert(
		"c:\\halo\\SOURCE\\interface\\event_manager.c",
		211,
		event && ((local_player_index>=0 && local_player_index<MAXIMUM_GAMEPADS) || local_player_index==NONE));

	if (event_manager_globals.state.initialized)
	{
		if (local_player_index == NONE)
		{
			local_player_index = 0;
			while (!result)
			{
				if (local_player_index >= MAXIMUM_GAMEPADS)
					break;
				result = get_next_event(event, local_player_index);
				local_player_index++;
			}
		}
		else
		{
			long event_index;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
			if (halo_menu_repeat_is_fast())
			{
				struct fast_menu_event_queue *queue = &fast_menu_events[local_player_index];
				if (!queue->count) return FALSE;
				*event = queue->events[queue->head];
				queue->head = (queue->head + 1) % FAST_MENU_EVENT_CAPACITY;
				queue->count--;
				return TRUE;
			}
#endif

			for (event_index = 7; event_index >= 0; event_index--)
			{
				if (event_manager_globals.state.events[local_player_index][event_index].type != 0)
				{
					*event = event_manager_globals.state.events[local_player_index][event_index];
					event_manager_globals.state.events[local_player_index][event_index].type = 0;
					return TRUE;
				}
			}
		}
	}

	return result;
}

unsigned long event_manager_time_of_last_event(
	void)
{
	return event_manager_globals.state.time_of_last_event;
}

void event_manager_post_button(
	short controller_index,
	short button_index)
{
	struct event_record event = {0};

	if (!event_manager_globals.state.initialized ||
		controller_index < 0 ||
		controller_index >= MAXIMUM_GAMEPADS)
	{
		return;
	}
	event.type = _event_type_button;
	event.data.button.index = (byte)button_index;
	event.data.button.value = 1;
	queue_event(&event, controller_index);

	return;
}

/* ---------- private code */
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
void event_manager_post_directory_join(short controller_index)
{
	struct event_record event = {0};
	if (!event_manager_globals.state.initialized || controller_index < 0 || controller_index >= MAXIMUM_GAMEPADS) return;
	event.type = HALO_DIRECTORY_JOIN_READY_EVENT;
	queue_event(&event, controller_index);
}
#endif

static void queue_event(
	struct event_record *event,
	short controller_index)
{
	unsigned long time;
	boolean post = TRUE;

	if (event_manager_globals.state.suppressed)
		return;

	time = system_milliseconds();
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	if (halo_menu_repeat_is_fast())
	{
		fast_menu_queue_event(event, controller_index, time);
		return;
	}
#endif

	if (event->type == _event_type_left_stick)
	{
		long x = event->data.stick.x;
		long y = event->data.stick.y;

		if (ABS(x) < STICK_EVENT_THRESHOLD && ABS(y) < STICK_EVENT_THRESHOLD)
		{
			post = FALSE;
		}
		else if (!((ABS(x) >= STICK_EVENT_THRESHOLD &&
				ABS(event_manager_globals.previous_stick_axes[_gamepad_stick_left][0][controller_index]) < STICK_EVENT_THRESHOLD) ||
			(ABS(y) >= STICK_EVENT_THRESHOLD &&
				ABS(event_manager_globals.previous_stick_axes[_gamepad_stick_left][1][controller_index]) < STICK_EVENT_THRESHOLD) ||
			time - event_manager_globals.stick_event_times[_gamepad_stick_left][controller_index] >= MENU_STICK_REPEAT_INTERVAL))
		{
			post = FALSE;
		}
		else
		{
			event_manager_globals.stick_event_times[_gamepad_stick_left][controller_index] = time;
			post = TRUE;

			if (ABS(x) >= STICK_EVENT_THRESHOLD)
			{
				switch (x >= 0 ? 1 : -1)
				{
				case 1:
					x = event->data.stick.x = 32767;
					break;
				case -1:
					x = event->data.stick.x = -32768;
					break;
				}
			}
			if (ABS(y) >= STICK_EVENT_THRESHOLD)
			{
				switch (y >= 0 ? 1 : -1)
				{
				case 1:
					y = event->data.stick.y = 32767;
					break;
				case -1:
					y = event->data.stick.y = -32768;
					break;
				}
			}
		}

		event_manager_globals.previous_stick_axes[_gamepad_stick_left][0][controller_index] = x;
		event_manager_globals.previous_stick_axes[_gamepad_stick_left][1][controller_index] = y;
	}
	else if (event->type == _event_type_right_stick)
	{
		long x = event->data.stick.x;
		long y = event->data.stick.y;

		if (ABS(x) < STICK_EVENT_THRESHOLD && ABS(y) < STICK_EVENT_THRESHOLD)
		{
			post = FALSE;
		}
		else if (!((ABS(x) >= STICK_EVENT_THRESHOLD &&
				ABS(event_manager_globals.previous_stick_axes[_gamepad_stick_right][0][controller_index]) < STICK_EVENT_THRESHOLD) ||
			(ABS(y) >= STICK_EVENT_THRESHOLD &&
				ABS(event_manager_globals.previous_stick_axes[_gamepad_stick_right][1][controller_index]) < STICK_EVENT_THRESHOLD) ||
			time - event_manager_globals.stick_event_times[_gamepad_stick_right][controller_index] >= MENU_STICK_REPEAT_INTERVAL))
		{
			post = FALSE;
		}
		else
		{
			event_manager_globals.stick_event_times[_gamepad_stick_right][controller_index] = time;
			post = TRUE;

			if (ABS(x) >= STICK_EVENT_THRESHOLD)
			{
				switch (x >= 0 ? 1 : -1)
				{
				case 1:
					x = event->data.stick.x = 32767;
					break;
				case -1:
					x = event->data.stick.x = -32768;
					break;
				}
			}
			if (ABS(y) >= STICK_EVENT_THRESHOLD)
			{
				switch (y >= 0 ? 1 : -1)
				{
				case 1:
					y = event->data.stick.y = 32767;
					break;
				case -1:
					y = event->data.stick.y = -32768;
					break;
				}
			}
		}

		event_manager_globals.previous_stick_axes[_gamepad_stick_right][0][controller_index] = x;
		event_manager_globals.previous_stick_axes[_gamepad_stick_right][1][controller_index] = y;
	}

	if (post)
	{
		event->controller_index = controller_index;
		csmemmove(
			event_manager_globals.state.events[controller_index],
			&event_manager_globals.state.events[controller_index][1],
			sizeof(event_manager_globals.state.events[controller_index]) - sizeof(struct event_record));
		event_manager_globals.state.events[controller_index][0] = *event;
		if (event->type != _event_type_null)
		{
			event_manager_globals.state.time_of_last_event = time;
		}
	}

	return;
}

void event_manager_update(
	void)
{
	short gamepad_index;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	boolean fast = halo_menu_repeat_is_fast();
	unsigned long time = system_milliseconds();
#endif

	if (!event_manager_globals.state.initialized)
		return;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
	if (fast != fast_menu_was_enabled)
	{
		fast_menu_reset();
		event_manager_flush();
		fast_menu_was_enabled = fast;
	}
	if (fast && !event_manager_globals.state.suppressed)
		fast_menu_update_keyboard(time);
	else
	{
		halo_menu_keyboard_clear();
		if (fast) fast_menu_reset();
	}
#endif

	for (gamepad_index = 0; gamepad_index < MAXIMUM_GAMEPADS; gamepad_index++)
	{
		boolean posted = FALSE;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
		if (fast && !event_manager_globals.state.suppressed)
			fast_menu_update_navigation(gamepad_index, time);
#endif

		if (input_has_gamepad(gamepad_index))
		{
			struct gamepad_state const *state = input_get_gamepad_state(gamepad_index);

			if (state)
			{
				struct event_record event;
				short button_index;

				if (
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
					!fast &&
#endif
					(state->sticks[_gamepad_stick_left].x != 0 ||
					state->sticks[_gamepad_stick_left].y != 0))
				{
					event.type = _event_type_left_stick;
					event.data.stick = state->sticks[_gamepad_stick_left];
					queue_event(&event, gamepad_index);
					posted = TRUE;
				}

				if (
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
					!fast &&
#endif
					(state->sticks[_gamepad_stick_right].x != 0 ||
					state->sticks[_gamepad_stick_right].y != 0))
				{
					event.type = _event_type_right_stick;
					event.data.stick = state->sticks[_gamepad_stick_right];
					queue_event(&event, gamepad_index);
					posted = TRUE;
				}

				for (button_index = 0; button_index < NUMBER_OF_GAMEPAD_BUTTONS; button_index++)
				{
					byte value = state->buttons[button_index];
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
					if (fast && button_index >= _gamepad_binary_button_dpad_up &&
						button_index <= _gamepad_binary_button_dpad_right)
						continue;
#endif

					if (value)
					{
						event.type = _event_type_button;
						event.data.button.index = (byte)button_index;
						event.data.button.value = value;
						queue_event(&event, gamepad_index);
						posted = TRUE;
					}
				}
			}
		}

		if (!posted)
		{
			struct event_record event = {0};

			queue_event(&event, gamepad_index);
		}
	}

	return;
}
