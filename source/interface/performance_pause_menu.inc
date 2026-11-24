/* Native multiplayer pause widgets. Included by ui_widget.c after its private
 * definitions and prototypes. All art and fonts stay in the current map; these
 * runtime DeLa/ustr tags do not alter the cache, its checksum, or retail tags. */

enum
{
	_performance_pause_created = 32010,
	_performance_pause_apply,
	_performance_pause_next,
};

enum
{
	_pp_pause_1p, _pp_pause_2p, _pp_pause_4p,
	_pp_list_1p, _pp_list_2p, _pp_list_4p,
	_pp_entry_1p, _pp_entry_2p, _pp_entry_4p,
	_pp_settings_1p, _pp_settings_2p, _pp_settings_4p,
	_pp_options_1p, _pp_options_2p, _pp_options_4p,
	_pp_column, _pp_preset, _pp_timer, _pp_markers, _pp_audio, _pp_movement, _pp_weapon,
	_pp_apply, _pp_title, _pp_footer,
	/* The same controls in split screen's smaller rows. Help has no room there. */
	_pp_split_column, _pp_split_preset, _pp_split_timer, _pp_split_markers, _pp_split_audio,
	_pp_split_movement, _pp_split_weapon, _pp_split_apply, _pp_split_title,
	_pp_widget_count
};
enum { PERFORMANCE_PAUSE_SPLIT = _pp_split_column - _pp_column, PERFORMANCE_PAUSE_ROWS = _pp_apply - _pp_preset + 1 };

static char const *const performance_pause_original_names[3] =
{
	"ui\\shell\\multiplayer_game\\pause_game\\1p_pause_game",
	"ui\\shell\\multiplayer_game\\pause_game\\2p_pause_game",
	"ui\\shell\\multiplayer_game\\pause_game\\4p_pause_game",
};

static char const *const performance_pause_names[_pp_widget_count] =
{
	"ui\\performance\\pause_1p", "ui\\performance\\pause_2p", "ui\\performance\\pause_4p",
	"ui\\performance\\pause_list_1p", "ui\\performance\\pause_list_2p", "ui\\performance\\pause_list_4p",
	"ui\\performance\\pause_entry_1p", "ui\\performance\\pause_entry_2p", "ui\\performance\\pause_entry_4p",
	"ui\\performance\\pause_settings_1p", "ui\\performance\\pause_settings_2p", "ui\\performance\\pause_settings_4p",
	"ui\\performance\\pause_options_1p", "ui\\performance\\pause_options_2p", "ui\\performance\\pause_options_4p",
	"ui\\performance\\pause_column", "ui\\performance\\pause_preset",
	"ui\\performance\\pause_timer", "ui\\performance\\pause_markers", "ui\\performance\\pause_audio",
	"ui\\performance\\pause_movement", "ui\\performance\\pause_weapon",
	"ui\\performance\\pause_apply", "ui\\performance\\pause_title", "ui\\performance\\pause_footer",
	"ui\\performance\\split_column", "ui\\performance\\split_preset",
	"ui\\performance\\split_timer", "ui\\performance\\split_markers", "ui\\performance\\split_audio",
	"ui\\performance\\split_movement", "ui\\performance\\split_weapon",
	"ui\\performance\\split_apply", "ui\\performance\\split_title",
};

/* unicode_string_list_get_string writes the terminating NUL; keep these
 * writable, including on ports that place wide string literals in rodata. */
static wchar_t performance_pause_text[][64] =
{
	L"PERFORMANCE OPTIONS", L"APPLY", L"RETURN",
	L"Apply to change host settings.",
	L"Host settings (view only).",
	/* A setting's row is its name, a tab and its value: the name is drawn
	 * from the row's left end and the value to its right end. */
	L"Preset\t< Default >", L"Preset\t< Practice >", L"Preset\t< Pro >", L"Preset\t< Custom >",
	L"Match Timer\t< Off >", L"Match Timer\t< On >",
	L"Markers\t< Off >", L"Markers\t< On >",
	L"PERFORMANCE OPTIONS",
	L"Timer Sounds\t< Off >", L"Timer Sounds\t< On >", L"GAME SETTINGS",
	L"Movement\t< Normal >", L"Movement\t< Just Me >", L"Movement\t< Silent >",
	L"Weapon\t< Normal >", L"Weapon\t< Just Me >", L"Weapon\t< Silent >",
	L"Original footsteps,\r\njumps and landings.",
	L"Just Me: hear your movement.\r\nOthers cannot hear it.",
	L"Silent: no movement sounds.\r\nCombat sounds stay normal.",
	L"Original equip and switch.\r\nEveryone hears them.",
	L"Just Me: hear equip and switch.\r\nOthers cannot hear them.",
	L"Silent: no equip or switch.\r\nCombat sounds stay normal.",
	L"A little field intelligence.\r\nMark player spawn locations.",
	L"A voice in your helmet.\r\nLocal volume and cues: Audio.",
	L"Pro rules are set before play.\r\nHere, change timer and sounds.",
	L"Team Slayer Pro is locked.\r\nUse another game type to edit.",
};
enum
{
	_pp_help_movement = 23, _pp_help_weapon = 26, _pp_help_markers = 29,
	_pp_help_audio, _pp_help_preset, _pp_help_locked,
};
static struct string_list_entry performance_pause_strings[NUMBEROF(performance_pause_text)];
static struct string_list performance_pause_string_lists[7];
static char const *const performance_pause_string_names[7] =
{
	"ui\\performance\\pause_labels", "ui\\performance\\pause_presets",
	"ui\\performance\\pause_timer_values", "ui\\performance\\pause_marker_values",
	"ui\\performance\\pause_audio_values",
	"ui\\performance\\pause_movement_values", "ui\\performance\\pause_weapon_values",
};
static long performance_pause_string_tags[7];
static struct ui_widget_definition performance_pause_definitions[_pp_widget_count];
static long performance_pause_tags[_pp_widget_count];
static struct ui_widget_child_reference performance_pause_children[3][3];
static struct ui_widget_child_reference performance_pause_list_children[3][4];
static struct ui_widget_child_reference performance_pause_option_children[3][5];
static struct ui_widget_child_reference performance_pause_column_children[2][PERFORMANCE_PAUSE_ROWS];
static struct ui_widget_event_handler_reference performance_pause_entry_events[3][2];
static struct ui_widget_event_handler_reference performance_pause_settings_events[3][2];
static struct ui_widget_event_handler_reference performance_pause_root_events[3];
static struct ui_widget_event_handler_reference performance_pause_apply_events[2];
static struct ui_widget_event_handler_reference performance_pause_spinner_events[1];
static boolean performance_pause_ready;
static long game_settings_pause_tag(short layout);

struct performance_pause_draft
{
	struct widget_instance *root;
	unsigned flags;
	short preset;
};
static struct performance_pause_draft performance_pause_drafts[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];

static void performance_pause_reference(struct tag_reference *reference, long group, long index)
{
	csmemset(reference, 0, sizeof(*reference));
	reference->group_tag = group;
	reference->index = index;
}

static void performance_pause_block(struct tag_block *block, long count, void *address)
{
	csmemset(block, 0, sizeof(*block));
	block->count = count;
	block->address = address;
}

static void performance_pause_event_definition(
	struct ui_widget_event_handler_reference *event, short type, short function,
	long flags, long widget_tag)
{
	csmemset(event, 0, sizeof(*event));
	event->event_type = type;
	event->function = function;
	event->flags = flags;
	performance_pause_reference(&event->widget_tag, UI_WIDGET_DEFINITION_TAG, widget_tag);
	performance_pause_reference(&event->sound_effect, 'snd!', NONE);
}

static void performance_pause_child(
	struct ui_widget_child_reference *child, long tag, short x, short y)
{
	csmemset(child, 0, sizeof(*child));
	performance_pause_reference(&child->widget_tag, UI_WIDGET_DEFINITION_TAG, tag);
	child->horizontal_offset = x;
	child->vertical_offset = y;
}

static void performance_pause_clear_definition(struct ui_widget_definition *definition)
{
	csmemset(definition, 0, sizeof(*definition));
	definition->controller_index = _widget_controller_any;
	performance_pause_reference(&definition->background_bitmap, 'bitm', NONE);
	performance_pause_reference(&definition->text_label_string_list, UNICODE_STRING_LIST_TAG, NONE);
	performance_pause_reference(&definition->text_font, FONT_GROUP_TAG, NONE);
	performance_pause_reference(&definition->list_header_bitmap, 'bitm', NONE);
	performance_pause_reference(&definition->list_footer_bitmap, 'bitm', NONE);
	performance_pause_reference(&definition->extended_description_widget, UI_WIDGET_DEFINITION_TAG, NONE);
}

static boolean performance_pause_build(void)
{
	long legend_tag, index, layout, split;
	static short const string_starts[7] = {0, 5, 9, 11, 14, 17, 20};
	static short const string_counts[7] = {NUMBEROF(performance_pause_text), 4, 2, 2, 2, 3, 3};

	/* Runtime registrations are invalidated at every scenario unload. A tag
	 * name lookup avoids dereferencing stale map definitions after a reload. */
	if (performance_pause_ready &&
		tag_loaded(UI_WIDGET_DEFINITION_TAG, performance_pause_names[_pp_pause_1p]) ==
			performance_pause_tags[_pp_pause_1p])
		return TRUE;
	performance_pause_ready = FALSE;
	csmemset(performance_pause_drafts, 0, sizeof(performance_pause_drafts));
	if (!native_multiplayer_pause_build())
		return FALSE;
	legend_tag = native_pause_legend_tag();
	if (legend_tag == NONE) return FALSE;
	for (index = 0; index < (long)NUMBEROF(performance_pause_strings); index++)
	{
		csmemset(&performance_pause_strings[index], 0, sizeof(performance_pause_strings[index]));
		performance_pause_strings[index].string.address = performance_pause_text[index];
		performance_pause_strings[index].string.size =
			(ustrlen(performance_pause_text[index]) + 1) * sizeof(wchar_t);
	}
	for (index = 0; index < 7; index++)
	{
		performance_pause_block(&performance_pause_string_lists[index].strings,
			string_counts[index], &performance_pause_strings[string_starts[index]]);
		performance_pause_string_tags[index] = cache_files_register_runtime_ui_tag(
			UNICODE_STRING_LIST_TAG, performance_pause_string_names[index],
			&performance_pause_string_lists[index]);
		if (performance_pause_string_tags[index] == NONE)
			return FALSE;
	}
	for (index = 0; index < _pp_widget_count; index++)
	{
		performance_pause_clear_definition(&performance_pause_definitions[index]);
		performance_pause_tags[index] = cache_files_register_runtime_ui_tag(
			UI_WIDGET_DEFINITION_TAG, performance_pause_names[index],
			&performance_pause_definitions[index]);
		if (performance_pause_tags[index] == NONE)
			return FALSE;
	}

	/* All maps use the regular Xbox frame, four known rows and the kit's
	 * placement in each viewport. Authored map lists cannot add or rearrange rows. */
	for (layout = 0; layout < 3; layout++)
	{
		struct ui_widget_definition *pause = &performance_pause_definitions[_pp_pause_1p + layout];
		struct ui_widget_definition *list = &performance_pause_definitions[_pp_list_1p + layout];
		struct ui_widget_definition *entry = &performance_pause_definitions[_pp_entry_1p + layout];
		struct ui_widget_definition *settings = &performance_pause_definitions[_pp_settings_1p + layout];
		struct ui_widget_definition *options = &performance_pause_definitions[_pp_options_1p + layout];
		struct ui_widget_definition const *pause_style = native_multiplayer_pause_root((short)layout);
		struct ui_widget_definition const *menu_row;
		struct native_pause_panel panel;
		short menu_style, options_style, controls, row;
		if (!pause_style) return FALSE;
		*pause = *pause_style;
		menu_style = native_pause_style_for(&pause->bounds, FALSE);
		options_style = native_pause_style_for(&pause->bounds, TRUE);
		controls = options_style == _native_pause_wide ? 0 : PERFORMANCE_PAUSE_SPLIT;
		menu_row = native_multiplayer_pause_button_style(menu_style);
		if (!menu_row || !native_pause_panel_place(&panel, menu_style, &pause->bounds, 4, FALSE, FALSE))
			return FALSE;
		performance_pause_child(&performance_pause_children[layout][0], panel.frame_tag,
			panel.x - NATIVE_PAUSE_FRAME_MARGIN, panel.y);
		performance_pause_child(&performance_pause_children[layout][1],
			performance_pause_tags[_pp_list_1p + layout], panel.x, panel.y + panel.rows_y);
		performance_pause_child(&performance_pause_children[layout][2], legend_tag,
			panel.x + native_pause_legend_x(menu_style), panel.y + panel.height - NATIVE_PAUSE_LEGEND_Y);
		performance_pause_block(&pause->child_widgets, 3, performance_pause_children[layout]);
		list->type = _ui_widget_type_column_list;
		list->flags = FLAG(_widget_pass_unhandled_events_to_children_bit) |
			FLAG(_widget_dpad_updown_tabs_thru_list_items_bit);
		list->bounds.x1 = menu_row->bounds.x1;
		list->bounds.y1 = panel.rows_height;
		for (row = 0; row < 4; row++)
			performance_pause_child(&performance_pause_list_children[layout][row],
				row == 0 ? native_multiplayer_pause_resume_tag(menu_style) :
				row == 1 ? performance_pause_tags[_pp_entry_1p + layout] :
				row == 2 ? performance_pause_tags[_pp_settings_1p + layout] :
					native_multiplayer_pause_leave_tag(menu_style),
				0, native_pause_row_y(menu_style, row, 4, FALSE));
		performance_pause_block(&list->child_widgets, 4, performance_pause_list_children[layout]);
		/* Every row of the list is the same size and font. */
		*entry = *menu_row;
		performance_pause_reference(&entry->text_label_string_list, UNICODE_STRING_LIST_TAG,
			performance_pause_string_tags[0]);
		entry->string_list_index = 0;
		performance_pause_event_definition(&performance_pause_entry_events[layout][0],
			_gamepad_analog_button_a, 0, FLAG(_event_handler_open_widget_bit), performance_pause_tags[_pp_options_1p + layout]);
		performance_pause_event_definition(&performance_pause_entry_events[layout][1],
			_gamepad_binary_button_start, 0, FLAG(_event_handler_open_widget_bit), performance_pause_tags[_pp_options_1p + layout]);
		performance_pause_block(&entry->event_handlers, 2, performance_pause_entry_events[layout]);
		*settings = *entry;
		settings->string_list_index = 16;
		{
			long settings_tag = game_settings_pause_tag((short)layout);
			if (settings_tag == NONE) return FALSE;
			performance_pause_event_definition(&performance_pause_settings_events[layout][0],
				_gamepad_analog_button_a, 0, FLAG(_event_handler_open_widget_bit), settings_tag);
			performance_pause_event_definition(&performance_pause_settings_events[layout][1],
				_gamepad_binary_button_start, 0, FLAG(_event_handler_open_widget_bit), settings_tag);
			performance_pause_block(&settings->event_handlers, 2, performance_pause_settings_events[layout]);
		}
		options->type = _ui_widget_type_container;
		/* Opening a submenu must keep the local player who invoked it. The
		 * launch path treats a zero controller index as an explicit player 0. */
		options->controller_index = _widget_controller_any;
		options->bounds = pause->bounds;
		options->flags = FLAG(_widget_pass_unhandled_events_to_children_bit);
		options->background_bitmap = pause->background_bitmap;
		performance_pause_block(&options->event_handlers, 3, performance_pause_root_events);
		/* The non-interactive frame draws first. Help needs the whole screen. */
		if (!native_pause_panel_place(&panel, options_style, &options->bounds, PERFORMANCE_PAUSE_ROWS, TRUE, TRUE))
			return FALSE;
		performance_pause_child(&performance_pause_option_children[layout][0], panel.frame_tag,
			panel.x - NATIVE_PAUSE_FRAME_MARGIN, panel.y);
		performance_pause_child(&performance_pause_option_children[layout][1],
			performance_pause_tags[_pp_column + controls], panel.x, panel.y + panel.rows_y);
		performance_pause_child(&performance_pause_option_children[layout][2],
			performance_pause_tags[_pp_title + controls], panel.x, panel.y + panel.title_y);
		performance_pause_child(&performance_pause_option_children[layout][3], legend_tag,
			panel.x + native_pause_legend_x(options_style), panel.y + panel.height - NATIVE_PAUSE_LEGEND_Y);
		performance_pause_child(&performance_pause_option_children[layout][4], performance_pause_tags[_pp_footer],
			panel.x + (native_pause_styles[options_style].row_width - NATIVE_PAUSE_HELP_WIDTH) / 2,
			panel.y + panel.height + NATIVE_PAUSE_HELP_GAP);
		performance_pause_block(&options->child_widgets, options_style == _native_pause_wide ? 5 : 4,
			performance_pause_option_children[layout]);
	}
	performance_pause_event_definition(&performance_pause_root_events[0],
		_widget_event_created, _performance_pause_created, FLAG(_event_handler_run_function_bit), NONE);
	performance_pause_event_definition(&performance_pause_root_events[1],
		_widget_event_b_button, 0, FLAG(_event_handler_go_back_to_previous_widget_bit), NONE);
	performance_pause_event_definition(&performance_pause_root_events[2],
		_widget_event_back_button, 0, FLAG(_event_handler_go_back_to_previous_widget_bit), NONE);
	performance_pause_event_definition(&performance_pause_apply_events[0],
		_gamepad_analog_button_a, _performance_pause_apply,
		FLAG(_event_handler_run_function_bit) | FLAG(_event_handler_go_back_to_previous_widget_bit), NONE);
	performance_pause_event_definition(&performance_pause_apply_events[1],
		_gamepad_binary_button_start, _performance_pause_apply,
		FLAG(_event_handler_run_function_bit) | FLAG(_event_handler_go_back_to_previous_widget_bit), NONE);
	performance_pause_event_definition(&performance_pause_spinner_events[0],
		_gamepad_analog_button_a, _performance_pause_next, FLAG(_event_handler_run_function_bit), NONE);

	for (split = 0; split < 2; split++)
	{
		short style_index = split ? _native_pause_split_options : _native_pause_wide;
		short controls = split ? PERFORMANCE_PAUSE_SPLIT : 0;
		struct native_pause_style const *style = &native_pause_styles[style_index];
		struct ui_widget_definition const *row_style = native_multiplayer_pause_button_style(style_index);
		struct ui_widget_definition *column = &performance_pause_definitions[_pp_column + controls];
		if (!row_style) return FALSE;
		column->type = _ui_widget_type_column_list;
		column->flags =
			FLAG(_widget_pass_unhandled_events_to_children_bit) | FLAG(_widget_dpad_updown_tabs_thru_list_items_bit);
		column->bounds.x1 = style->row_width;
		column->bounds.y1 = (short)(PERFORMANCE_PAUSE_ROWS * style->row_height + style->action_gap);
		performance_pause_block(&column->child_widgets, PERFORMANCE_PAUSE_ROWS, performance_pause_column_children[split]);
		for (index = _pp_preset; index <= _pp_apply; index++)
		{
			struct ui_widget_definition *definition = &performance_pause_definitions[index + controls];
			*definition = *row_style;
			performance_pause_reference(&definition->text_label_string_list,
				UNICODE_STRING_LIST_TAG, performance_pause_string_tags[0]);
			performance_pause_child(&performance_pause_column_children[split][index - _pp_preset],
				performance_pause_tags[index + controls], 0,
				native_pause_row_y(style_index, (short)(index - _pp_preset), PERFORMANCE_PAUSE_ROWS, TRUE));
			if (index <= _pp_weapon)
			{
				definition->type = _ui_widget_type_spinner_list;
				native_pause_setting_definition(definition, style_index);
				definition->flags |= FLAG(_widget_dpad_leftright_tabs_thru_list_items_bit);
				definition->list_flags = FLAG(_list_items_generated_from_string_list_tag);
				definition->text_label_string_list.index = performance_pause_string_tags[index - _pp_preset + 1];
				performance_pause_block(&definition->event_handlers, 1, performance_pause_spinner_events);
			}
		}
		performance_pause_definitions[_pp_apply + controls].string_list_index = 1;
		performance_pause_block(&performance_pause_definitions[_pp_apply + controls].event_handlers, 2,
			performance_pause_apply_events);
		/* One title style on every page: the page's own font, in white. */
		native_pause_title_definition(&performance_pause_definitions[_pp_title + controls], row_style);
		performance_pause_reference(&performance_pause_definitions[_pp_title + controls].text_label_string_list,
			UNICODE_STRING_LIST_TAG, performance_pause_string_tags[0]);
		performance_pause_definitions[_pp_title + controls].string_list_index = 13;
	}
	{
		struct ui_widget_definition *footer = &performance_pause_definitions[_pp_footer];
		long font = native_pause_resident_tag(FONT_GROUP_TAG, "ui\\small_ui");
		if (font == NONE) return FALSE;
		native_pause_title_definition(footer, native_multiplayer_pause_button_style(_native_pause_wide));
		footer->text_color = native_multiplayer_pause_button_style(_native_pause_wide)->text_color;
		performance_pause_reference(&footer->text_label_string_list,
			UNICODE_STRING_LIST_TAG, performance_pause_string_tags[0]);
		/* The native small_ui font has a 20-pixel line advance. */
		footer->bounds.y1 = 40;
		footer->bounds.x1 = NATIVE_PAUSE_HELP_WIDTH;
		footer->text_font.index = font;
		footer->horizontal_offset = footer->vertical_offset = 0;
		footer->string_list_index = 3;
	}
	performance_pause_ready = TRUE;
	return TRUE;
}

static long performance_pause_remap_tag(long tag)
{
	short layout;
	if (tag == NONE)
		return tag;
	for (layout = 0; layout < 3; layout++)
	{
		if (tag == tag_loaded(UI_WIDGET_DEFINITION_TAG, performance_pause_original_names[layout]))
			return performance_pause_build() ? performance_pause_tags[_pp_pause_1p + layout] : tag;
	}
	return tag;
}

static boolean performance_pause_is_spinner(struct widget_instance *widget)
{
	short index;
	if (!performance_pause_ready || !widget || widget->definition_tag_index == NONE) return FALSE;
	for (index = _pp_preset; index <= _pp_weapon; index++)
		if (widget->definition_tag_index == performance_pause_tags[index] ||
			widget->definition_tag_index == performance_pause_tags[index + PERFORMANCE_PAUSE_SPLIT]) return TRUE;
	return FALSE;
}

/* A control of the options page, in whichever size this root shows. */
static struct widget_instance *performance_pause_control(struct widget_instance *root, short control)
{
	struct widget_instance *widget = widget_instance_find_by_tag_index_recursive(root, performance_pause_tags[control]);
	if (!widget && control < _pp_footer)
		widget = widget_instance_find_by_tag_index_recursive(root, performance_pause_tags[control + PERFORMANCE_PAUSE_SPLIT]);
	return widget;
}

static short performance_pause_preset(unsigned flags)
{
	return performance_variant_preset(flags);
}

static struct performance_pause_draft *performance_pause_draft_for(struct widget_instance *widget)
{
	short local;
	while (widget && widget->parent)
		widget = widget->parent;
	if (!widget || !performance_pause_ready ||
		(widget->definition_tag_index != performance_pause_tags[_pp_options_1p] &&
		 widget->definition_tag_index != performance_pause_tags[_pp_options_2p] &&
		 widget->definition_tag_index != performance_pause_tags[_pp_options_4p]))
		return NULL;
	local = widget->local_player_index;
	if (local == NONE)
		local = 0;
	if (local < 0 || local >= MAXIMUM_NUMBER_OF_LOCAL_PLAYERS)
		return NULL;
	return &performance_pause_drafts[local];
}

static void performance_pause_update(struct widget_instance *widget)
{
	struct performance_pause_draft *draft = performance_pause_draft_for(widget);
	struct widget_instance *preset, *timer, *markers, *audio, *movement, *weapon, *apply, *footer, *focus;
	boolean locked = playlist_profile_variant_is_locked(game_engine_get_variant());
	boolean editable = global_network_game_server_get() != NULL && !locked;
	unsigned flags;
	if (!draft || !draft->root)
		return;
	widget = draft->root;
	preset = performance_pause_control(widget, _pp_preset);
	timer = performance_pause_control(widget, _pp_timer);
	markers = performance_pause_control(widget, _pp_markers);
	audio = performance_pause_control(widget, _pp_audio);
	movement = performance_pause_control(widget, _pp_movement);
	weapon = performance_pause_control(widget, _pp_weapon);
	apply = performance_pause_control(widget, _pp_apply);
	footer = performance_pause_control(widget, _pp_footer);
	if (!preset || !timer || !markers || !audio || !movement || !weapon || !apply)
		return;
	if (!editable)
	{
		draft->flags = performance_options_get_flags() & PERFORMANCE_OPTIONS_MASK;
		draft->preset = performance_pause_preset(draft->flags);
	}
	else if (preset->parameters.list.selected_index != draft->preset)
	{
		draft->preset = preset->parameters.list.selected_index;
		if (draft->preset == 0)
			draft->flags &= PERFORMANCE_MATCH_RULE_FLAGS;
		else if (draft->preset == 1)
			draft->flags = (draft->flags & PERFORMANCE_MATCH_RULE_FLAGS) | PERFORMANCE_PRACTICE_FLAGS;
		else if (draft->preset == 2)
		{
			/* Input delay, spread and camouflage stay locked in a live game.
			 * A full Pro match is selected in Edit Gametypes before starting. */
			draft->flags = (draft->flags & PERFORMANCE_MATCH_RULE_FLAGS) |
				(PERFORMANCE_PRO_FLAGS & ~PERFORMANCE_MATCH_RULE_FLAGS);
			draft->preset = performance_pause_preset(draft->flags);
		}
	}
	else
	{
		/* Pregame match rules have no pause controls and cannot be changed here. */
		flags = (draft->flags & PERFORMANCE_MATCH_RULE_FLAGS) |
			(timer->parameters.list.selected_index ? _performance_option_match_timer : 0) |
			(markers->parameters.list.selected_index ? _performance_option_spawn_markers : 0) |
			(audio->parameters.list.selected_index ? _performance_option_timer_audio : 0) |
			performance_variant_sound_flags(movement->parameters.list.selected_index,
				_performance_option_silent_movement, _performance_option_self_movement) |
			performance_variant_sound_flags(weapon->parameters.list.selected_index,
				_performance_option_silent_weapon_ready, _performance_option_self_weapon_ready);
		if (flags != draft->flags)
		{
			draft->flags = flags;
			draft->preset = performance_pause_preset(flags);
		}
	}
	preset->parameters.list.selected_index = draft->preset;
	timer->parameters.list.selected_index = (draft->flags & _performance_option_match_timer) != 0;
	markers->parameters.list.selected_index = (draft->flags & _performance_option_spawn_markers) != 0;
	audio->parameters.list.selected_index = (draft->flags & _performance_option_timer_audio) != 0;
	movement->parameters.list.selected_index = performance_variant_sound_mode(draft->flags,
		_performance_option_silent_movement, _performance_option_self_movement);
	weapon->parameters.list.selected_index = performance_variant_sound_mode(draft->flags,
		_performance_option_silent_weapon_ready, _performance_option_self_weapon_ready);
	preset->disabled = timer->disabled = markers->disabled = audio->disabled = movement->disabled = weapon->disabled = !editable;
	apply->parameters.text_box.string_list_index = editable ? 1 : 2;
	if (footer) footer->parameters.text_box.string_list_index = locked ? _pp_help_locked : editable ? 3 : 4;
	if (footer && editable)
		for (focus = widget; focus; focus = focus->focused_child)
		{
			if (focus == preset) footer->parameters.text_box.string_list_index = _pp_help_preset;
			if (focus == markers) footer->parameters.text_box.string_list_index = _pp_help_markers;
			if (focus == audio) footer->parameters.text_box.string_list_index = _pp_help_audio;
			if (focus == movement) footer->parameters.text_box.string_list_index =
				_pp_help_movement + movement->parameters.list.selected_index;
			if (focus == weapon) footer->parameters.text_box.string_list_index =
				_pp_help_weapon + weapon->parameters.list.selected_index;
		}
}

static boolean performance_pause_event(struct widget_instance *widget, short function)
{
	struct performance_pause_draft *draft = performance_pause_draft_for(widget);
	if (!draft)
		return FALSE;
	if (function == _performance_pause_created)
	{
		struct widget_instance *preset = performance_pause_control(widget, _pp_preset);
		struct widget_instance *timer = performance_pause_control(widget, _pp_timer);
		struct widget_instance *markers = performance_pause_control(widget, _pp_markers);
		struct widget_instance *audio = performance_pause_control(widget, _pp_audio);
		struct widget_instance *movement = performance_pause_control(widget, _pp_movement);
		struct widget_instance *weapon = performance_pause_control(widget, _pp_weapon);
		if (!preset || !timer || !markers || !audio || !movement || !weapon)
		{
			draft->root = NULL;
			return FALSE;
		}
		draft->root = widget;
		draft->flags = performance_options_get_flags() & PERFORMANCE_OPTIONS_MASK;
		draft->preset = performance_pause_preset(draft->flags);
		/* Set all selections before update so opening never treats the native
		 * default zero selection as an edit of the host's current settings. */
		preset->parameters.list.selected_index = draft->preset;
		timer->parameters.list.selected_index = (draft->flags & _performance_option_match_timer) != 0;
		markers->parameters.list.selected_index = (draft->flags & _performance_option_spawn_markers) != 0;
		audio->parameters.list.selected_index = (draft->flags & _performance_option_timer_audio) != 0;
		movement->parameters.list.selected_index = performance_variant_sound_mode(draft->flags,
			_performance_option_silent_movement, _performance_option_self_movement);
		weapon->parameters.list.selected_index = performance_variant_sound_mode(draft->flags,
			_performance_option_silent_weapon_ready, _performance_option_self_weapon_ready);
		performance_pause_update(widget);
		return TRUE;
	}
	if (function == _performance_pause_apply)
	{
		if (!draft->root)
			return FALSE;
		performance_pause_update(widget);
		/* Guests can return with A but cannot write; the server setter also
		 * rechecks authority and peer capability at the moment of Apply. */
		return global_network_game_server_get() == NULL ||
			playlist_profile_variant_is_locked(game_engine_get_variant()) ||
			performance_options_set_host_flags(draft->flags);
	}
	if (function == _performance_pause_next && global_network_game_server_get() != NULL &&
		!playlist_profile_variant_is_locked(game_engine_get_variant()))
	{
		boolean deleted = FALSE;
		struct event_record event = {0};
		if (widget->type != _ui_widget_type_spinner_list || widget->parameters.list.number_of_items == 0)
			return FALSE;
		widget_event_function_list_widget_goto_next_item(widget, &event, &deleted);
		performance_pause_update(widget);
		return TRUE;
	}
	return FALSE;
}
