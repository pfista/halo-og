/*
UI_WIDGET_GAME_DATA_INPUT_FUNCTIONS.H

header included in hcex build.
*/

#ifndef __UI_WIDGET_GAME_DATA_INPUT_FUNCTIONS_H
#define __UI_WIDGET_GAME_DATA_INPUT_FUNCTIONS_H
#pragma once

/* ---------- headers */

#include "cseries/cseries.h"

/* ---------- constants */

#define UI_WIDGET_ENGINE_BUILD_NUMBER "01.01.14.2342"

/* ---------- macros */

/* ---------- structures */

struct widget_instance;
struct ui_widget_definition;
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
boolean ui_widget_is_system_link_list(struct ui_widget_definition *definition);
boolean ui_widget_game_data_function_is_server_list(word function);
#endif

typedef void (*ui_widget_game_data_function)(
	struct widget_instance *widget);

/* ---------- prototypes/UI_WIDGET_GAME_DATA_INPUT_FUNCTIONS.C */

void ui_widget_game_data_function_invoke(
	struct widget_instance *widget,
	word function);

/* ---------- globals */

/* ---------- public code */

#endif // __UI_WIDGET_GAME_DATA_INPUT_FUNCTIONS_H
