/*
UI_WIDGET_EVENT_HANDLER_FUNCTIONS.H

header included in hcex build.
*/

#ifndef __UI_WIDGET_EVENT_HANDLER_FUNCTIONS_H
#define __UI_WIDGET_EVENT_HANDLER_FUNCTIONS_H
#pragma once

/* ---------- constants */

/* ---------- macros */

/* ---------- structures */

struct event_record;
struct widget_instance;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
/* UI-only entries never reach the saved-profile or network variant paths. */
enum { UI_WIDGET_GAME_TYPE_CREATE = -2, _ui_widget_create_game_type = 32040 };
boolean ui_widget_directory_join_ready(struct widget_instance *widget, boolean *widget_deleted);
boolean ui_widget_game_type_create_selected(struct widget_instance *widget, word function_index);
#endif

/* ---------- prototypes/UI_WIDGET_EVENT_HANDLER_FUNCTIONS.C */

boolean ui_widget_event_handler_function_invoke(
	struct widget_instance *widget,
	struct event_record *event,
	word function_index,
	boolean *widget_deleted);

void reset_last_player1_profile_index(
	void);

/* ---------- globals */

/* ---------- public code */

#endif // __UI_WIDGET_EVENT_HANDLER_FUNCTIONS_H
