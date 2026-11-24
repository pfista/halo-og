/* Fixed regular-Xbox multiplayer pause primitives. Imported maps contribute
 * resident artwork and real leave actions, never the menu's geometry or rows. */
#include <string.h>

/* The Pause list has two sizes: one player's and split screen's. */
enum { NUMBER_OF_NATIVE_MULTIPLAYER_PAUSE_SIZES = 2 };
static char const *const native_multiplayer_pause_button_names[NUMBER_OF_NATIVE_MULTIPLAYER_PAUSE_SIZES][2] = {
	{"ui\\native_pause\\resume_game", "ui\\native_pause\\leave_game"},
	{"ui\\native_pause\\split_resume_game", "ui\\native_pause\\split_leave_game"}};
static char const native_multiplayer_pause_labels_name[] = "ui\\native_pause\\labels";
static struct ui_widget_definition native_multiplayer_pause_roots[3];
static struct ui_widget_definition native_multiplayer_pause_styles[NUMBER_OF_NATIVE_PAUSE_STYLES];
static struct ui_widget_definition native_multiplayer_pause_buttons[NUMBER_OF_NATIVE_MULTIPLAYER_PAUSE_SIZES][2];
static struct ui_widget_event_handler_reference native_multiplayer_pause_root_events[3];
static struct ui_widget_event_handler_reference native_multiplayer_pause_resume_events[2];
static wchar_t native_multiplayer_pause_text[2][16] = {L"RESUME GAME", L"LEAVE GAME"};
static struct string_list_entry native_multiplayer_pause_string_entries[2];
static struct string_list native_multiplayer_pause_strings;
static long native_multiplayer_pause_button_tags[NUMBER_OF_NATIVE_MULTIPLAYER_PAUSE_SIZES][2];
static boolean native_multiplayer_pause_ready;

static void native_multiplayer_pause_reference(struct tag_reference *reference,
	long group, long tag)
{
	csmemset(reference, 0, sizeof(*reference));
	reference->group_tag = group;
	reference->index = tag;
}

static void native_multiplayer_pause_clear(struct ui_widget_definition *definition)
{
	csmemset(definition, 0, sizeof(*definition));
	definition->controller_index = _widget_controller_any;
	native_multiplayer_pause_reference(&definition->background_bitmap, 'bitm', NONE);
	native_multiplayer_pause_reference(&definition->text_label_string_list, UNICODE_STRING_LIST_TAG, NONE);
	native_multiplayer_pause_reference(&definition->text_font, FONT_GROUP_TAG, NONE);
	native_multiplayer_pause_reference(&definition->list_header_bitmap, 'bitm', NONE);
	native_multiplayer_pause_reference(&definition->list_footer_bitmap, 'bitm', NONE);
	native_multiplayer_pause_reference(&definition->extended_description_widget, UI_WIDGET_DEFINITION_TAG, NONE);
}

static void native_multiplayer_pause_close_event(struct ui_widget_event_handler_reference *event,
	short type)
{
	csmemset(event, 0, sizeof(*event));
	event->event_type = type;
	event->flags = FLAG(_event_handler_close_current_widget_bit);
	native_multiplayer_pause_reference(&event->widget_tag, UI_WIDGET_DEFINITION_TAG, NONE);
	native_multiplayer_pause_reference(&event->sound_effect, 'snd!', NONE);
}

/* Event table entry 72 is network_game_remove_local_player. Follow existing
 * confirmation widgets instead of replacing their confirm/cancel behavior. */
static boolean native_multiplayer_pause_has_leave_action(long tag, short depth)
{
	struct ui_widget_definition const *definition;
	long index;
	if (!depth || !tag_index_is_group(tag, UI_WIDGET_DEFINITION_TAG)) return FALSE;
	definition = ui_widget_definition_get(tag);
	for (index = 0; index < definition->event_handlers.count; index++)
	{
		struct ui_widget_event_handler_reference const *event =
			(struct ui_widget_event_handler_reference const *)definition->event_handlers.address + index;
		if (TEST_FLAG(event->flags, _event_handler_run_function_bit) && event->function == 72)
			return TRUE;
		if ((TEST_FLAG(event->flags, _event_handler_open_widget_bit) ||
			TEST_FLAG(event->flags, _event_handler_replace_with_other_widget_bit)) &&
			native_multiplayer_pause_has_leave_action(event->widget_tag.index, depth - 1))
			return TRUE;
	}
	for (index = 0; index < definition->child_widgets.count; index++)
	{
		struct ui_widget_child_reference const *child =
			(struct ui_widget_child_reference const *)definition->child_widgets.address + index;
		if (native_multiplayer_pause_has_leave_action(child->widget_tag.index, depth - 1))
			return TRUE;
	}
	return FALSE;
}

static struct ui_widget_definition const *native_multiplayer_pause_leave_definition(void)
{
	struct tag_iterator iterator;
	struct ui_widget_definition const *candidate = NULL;
	long tag = native_pause_resident_tag(UI_WIDGET_DEFINITION_TAG,
		"ui\\shell\\multiplayer_game\\pause_game\\quit_netgame_button");
	if (tag != NONE) return ui_widget_definition_get(tag);
	tag_iterator_new(&iterator, UI_WIDGET_DEFINITION_TAG);
	while ((tag = tag_iterator_next(&iterator)) != NONE)
	{
		char const *name = tag_get_name(tag);
		struct ui_widget_definition const *definition = ui_widget_definition_get(tag);
		/* Do not mistake a lobby's remove-player row or a confirmation's Yes
 		 * row for the pause menu's Leave action. */
		if (!name || !strstr(name, "pause") ||
			(!strstr(name, "quit") && !strstr(name, "leave")) ||
			strstr(name, "confirm") || strstr(name, "yes") ||
			definition->type != _ui_widget_type_text_box)
			continue;
		if (native_multiplayer_pause_has_leave_action(tag, 8))
		{
			if (candidate) return NULL;
			candidate = definition;
		}
	}
	return candidate;
}

static boolean native_multiplayer_pause_build(void)
{
	struct ui_widget_definition const *resume, *leave;
	long resume_source, labels, dim, index, size;
	static short const widths[3] = {640, 640, 320};
	static short const heights[3] = {480, 240, 240};
	if (native_multiplayer_pause_ready &&
		tag_loaded(UI_WIDGET_DEFINITION_TAG, native_multiplayer_pause_button_names[0][0]) == native_multiplayer_pause_button_tags[0][0] &&
		tag_loaded(UI_WIDGET_DEFINITION_TAG, native_multiplayer_pause_button_names[1][1]) == native_multiplayer_pause_button_tags[1][1])
		return TRUE;
	native_multiplayer_pause_ready = FALSE;
	resume_source = native_pause_resident_tag(UI_WIDGET_DEFINITION_TAG,
		"ui\\shell\\multiplayer_game\\pause_game\\resume_game_button");
	resume = resume_source != NONE ? ui_widget_definition_get(resume_source) : NULL;
	leave = native_multiplayer_pause_leave_definition();
	if (!leave || !leave->event_handlers.count) return FALSE;
	for (index = 0; index < NUMBER_OF_NATIVE_PAUSE_STYLES; index++)
		if (!native_pause_row_definition(&native_multiplayer_pause_styles[index], (short)index,
			resume ? resume->background_bitmap.index : NONE))
			return FALSE;
	dim = native_pause_resident_tag('bitm', "ui\\shell\\bitmaps\\semi_transparent_grey");
	for (index = 0; index < 3; index++)
	{
		struct ui_widget_definition *root = &native_multiplayer_pause_roots[index];
		native_multiplayer_pause_clear(root);
		root->type = _ui_widget_type_container;
		root->bounds = (rectangle2d){0, 0, heights[index], widths[index]};
		root->flags = FLAG(_widget_pass_unhandled_events_to_children_bit);
		root->background_bitmap.index = dim;
		root->event_handlers.count = 3;
		root->event_handlers.address = native_multiplayer_pause_root_events;
	}
	native_multiplayer_pause_close_event(&native_multiplayer_pause_root_events[0], _widget_event_b_button);
	native_multiplayer_pause_close_event(&native_multiplayer_pause_root_events[1], _widget_event_back_button);
	native_multiplayer_pause_close_event(&native_multiplayer_pause_root_events[2], _gamepad_binary_button_start);
	native_multiplayer_pause_close_event(&native_multiplayer_pause_resume_events[0], _gamepad_analog_button_a);
	native_multiplayer_pause_close_event(&native_multiplayer_pause_resume_events[1], _gamepad_binary_button_start);
	for (index = 0; index < 2; index++)
	{
		struct string_list_entry *entry = &native_multiplayer_pause_string_entries[index];
		csmemset(entry, 0, sizeof(*entry));
		entry->string.address = native_multiplayer_pause_text[index];
		entry->string.size = (ustrlen(native_multiplayer_pause_text[index]) + 1) * sizeof(wchar_t);
	}
	csmemset(&native_multiplayer_pause_strings, 0, sizeof(native_multiplayer_pause_strings));
	native_multiplayer_pause_strings.strings.count = 2;
	native_multiplayer_pause_strings.strings.address = native_multiplayer_pause_string_entries;
	labels = cache_files_register_runtime_ui_tag(UNICODE_STRING_LIST_TAG,
		native_multiplayer_pause_labels_name, &native_multiplayer_pause_strings);
	if (labels == NONE) return FALSE;
	for (size = 0; size < NUMBER_OF_NATIVE_MULTIPLAYER_PAUSE_SIZES; size++)
		for (index = 0; index < 2; index++)
		{
			struct ui_widget_definition *button = &native_multiplayer_pause_buttons[size][index];
			*button = native_multiplayer_pause_styles[size ? _native_pause_split_menu : _native_pause_wide];
			button->text_label_string_list.index = labels;
			button->string_list_index = (short)index;
			if (index == 0)
			{
				button->event_handlers.count = 2;
				button->event_handlers.address = native_multiplayer_pause_resume_events;
			}
			else
			{
				button->event_handlers = leave->event_handlers;
				button->conditional_widgets = leave->conditional_widgets;
			}
			native_multiplayer_pause_button_tags[size][index] = cache_files_register_runtime_ui_tag(
				UI_WIDGET_DEFINITION_TAG, native_multiplayer_pause_button_names[size][index], button);
			if (native_multiplayer_pause_button_tags[size][index] == NONE) return FALSE;
		}
	native_multiplayer_pause_ready = TRUE;
	return TRUE;
}

static struct ui_widget_definition const *native_multiplayer_pause_root(short layout)
{
	if (layout < 0 || layout >= 3 || !native_multiplayer_pause_build()) return NULL;
	return &native_multiplayer_pause_roots[layout];
}

/* The row every native Pause page builds on, in one of the kit's styles. */
static struct ui_widget_definition const *native_multiplayer_pause_button_style(short style)
{
	if (style < 0 || style >= NUMBER_OF_NATIVE_PAUSE_STYLES || !native_multiplayer_pause_build()) return NULL;
	return &native_multiplayer_pause_styles[style];
}

static long native_multiplayer_pause_resume_tag(short style)
{
	return native_multiplayer_pause_build() ? native_multiplayer_pause_button_tags[style != _native_pause_wide][0] : NONE;
}

static long native_multiplayer_pause_leave_tag(short style)
{
	return native_multiplayer_pause_build() ? native_multiplayer_pause_button_tags[style != _native_pause_wide][1] : NONE;
}

static boolean native_multiplayer_pause_is_resume(long tag)
{
	return native_multiplayer_pause_ready && tag != NONE &&
		(tag == native_multiplayer_pause_button_tags[0][0] || tag == native_multiplayer_pause_button_tags[1][0]);
}
