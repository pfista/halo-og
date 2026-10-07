/* The larger native option pages retain the pause dialog's authored corners.
 * Its three resident textures have a 159-pixel panel in a 256-pixel texture;
 * ordinary widget bounds crop texture coordinates instead of stretching it.
 * Only this runtime tag is rendered through the explicit source rectangles. */
#define NATIVE_PAUSE_FRAME_NAME "ui\\native_settings\\pause_frame_"
static char const *const native_pause_frame_names[3] = {
	NATIVE_PAUSE_FRAME_NAME "159", NATIVE_PAUSE_FRAME_NAME "213", NATIVE_PAUSE_FRAME_NAME "240"};
static short const native_pause_frame_heights[3] = {159, 213, 240};
static struct ui_widget_definition native_pause_frame_definitions[3];
static long native_pause_frame_indices[3];
static long native_pause_frame_bitmaps[3];
static boolean native_pause_frame_ready;

/* Keep the regular resident art when an imported map moved a tag to another
 * directory. A basename must identify one tag; arbitrary art is never guessed. */
static long native_pause_resident_tag(long group, char const *path)
{
	struct tag_iterator iterator;
	long tag = tag_loaded(group, path), candidate = NONE, index;
	char const *basename = path, *cursor;
	if (tag != NONE) return tag;
	for (cursor = path; *cursor; cursor++)
		if (*cursor == '\\') basename = cursor + 1;
	tag_iterator_new(&iterator, group);
	while ((index = tag_iterator_next(&iterator)) != NONE)
	{
		char const *name = tag_get_name(index), *leaf = name;
		if (!name) continue;
		for (cursor = name; *cursor; cursor++)
			if (*cursor == '\\') leaf = cursor + 1;
		if (csstrcmp(leaf, basename)) continue;
		if (candidate != NONE) return NONE;
		candidate = index;
	}
	return candidate;
}

static long native_pause_legend_tag(void)
{
	static char const strings_name[] = "ui\\native_settings\\pause_legend_labels";
	static char const widget_name[] = "ui\\native_settings\\pause_legend";
	static wchar_t text[] = L"A Select    B Back";
	static struct string_list_entry entry;
	static struct string_list strings;
	static struct ui_widget_definition legend;
	static long legend_tag = NONE;
	long tag = native_pause_resident_tag(UI_WIDGET_DEFINITION_TAG,
		"ui\\shell\\main_menu\\button_key_sm");
	long font, labels;
	if (tag != NONE) return tag;
	if (legend_tag != NONE && tag_loaded(UI_WIDGET_DEFINITION_TAG, widget_name) == legend_tag)
		return legend_tag;
	font = native_pause_resident_tag(FONT_GROUP_TAG, "ui\\small_ui");
	if (font == NONE) font = native_pause_resident_tag(FONT_GROUP_TAG, "ui\\large_ui");
	if (font == NONE) return NONE;
	csmemset(&entry, 0, sizeof(entry));
	entry.string.address = text;
	entry.string.size = (ustrlen(text) + 1) * sizeof(wchar_t);
	csmemset(&strings, 0, sizeof(strings));
	strings.strings.count = 1;
	strings.strings.address = &entry;
	labels = cache_files_register_runtime_ui_tag(UNICODE_STRING_LIST_TAG, strings_name, &strings);
	if (labels == NONE) return NONE;
	csmemset(&legend, 0, sizeof(legend));
	legend.type = _ui_widget_type_text_box;
	legend.controller_index = _widget_controller_any;
	legend.bounds = (rectangle2d){0, 0, 25, 170};
	legend.background_bitmap.index = NONE;
	legend.text_label_string_list.group_tag = UNICODE_STRING_LIST_TAG;
	legend.text_label_string_list.index = labels;
	legend.text_font.group_tag = FONT_GROUP_TAG;
	legend.text_font.index = font;
	legend.text_color.alpha = 1.0f;
	legend.text_color.red = 40.0f / 255.0f;
	legend.text_color.green = 150.0f / 255.0f;
	legend.text_color.blue = 1.0f;
	legend.justification = _text_justification_center;
	legend.list_header_bitmap.index = legend.list_footer_bitmap.index = NONE;
	legend.extended_description_widget.index = NONE;
	legend_tag = cache_files_register_runtime_ui_tag(UI_WIDGET_DEFINITION_TAG, widget_name, &legend);
	return legend_tag;
}

static long native_pause_frame_tag(short height)
{
	static char const *const names[3] = {
		"ui\\shell\\bitmaps\\pausebox2_left",
		"ui\\shell\\bitmaps\\pausebox2_center",
		"ui\\shell\\bitmaps\\pausebox2_right"};
	struct ui_widget_definition *definition;
	short index, frame;
	for (frame = 0; frame < 3; frame++)
		if (height == native_pause_frame_heights[frame]) break;
	if (frame == 3) return NONE;
	if (native_pause_frame_ready &&
		tag_loaded(UI_WIDGET_DEFINITION_TAG, native_pause_frame_names[0]) == native_pause_frame_indices[0])
		return native_pause_frame_indices[frame];
	native_pause_frame_ready = FALSE;
	for (index = 0; index < 3; index++)
	{
		native_pause_frame_bitmaps[index] = native_pause_resident_tag('bitm', names[index]);
		if (native_pause_frame_bitmaps[index] == NONE) return NONE;
	}
	for (index = 0; index < 3; index++)
	{
		definition = &native_pause_frame_definitions[index];
		csmemset(definition, 0, sizeof(*definition));
		definition->type = _ui_widget_type_container;
		definition->controller_index = _widget_controller_any;
		definition->bounds.x0 = -4;
		definition->bounds.x1 = 222;
		definition->bounds.y1 = native_pause_frame_heights[index];
		definition->background_bitmap.group_tag = 'bitm';
		definition->background_bitmap.index = NONE;
		definition->text_label_string_list.group_tag = UNICODE_STRING_LIST_TAG;
		definition->text_label_string_list.index = NONE;
		definition->text_font.group_tag = FONT_GROUP_TAG;
		definition->text_font.index = NONE;
		definition->list_header_bitmap.group_tag = definition->list_footer_bitmap.group_tag = 'bitm';
		definition->list_header_bitmap.index = definition->list_footer_bitmap.index = NONE;
		definition->extended_description_widget.group_tag = UI_WIDGET_DEFINITION_TAG;
		definition->extended_description_widget.index = NONE;
		native_pause_frame_indices[index] = cache_files_register_runtime_ui_tag(
			UI_WIDGET_DEFINITION_TAG, native_pause_frame_names[index], definition);
		if (native_pause_frame_indices[index] == NONE) return NONE;
	}
	native_pause_frame_ready = TRUE;
	return native_pause_frame_indices[frame];
}

static boolean native_pause_frame_is_widget(long tag)
{
	short index;
	if (!native_pause_frame_ready || tag == NONE) return FALSE;
	for (index = 0; index < 3; index++)
		if (tag == native_pause_frame_indices[index]) return TRUE;
	return FALSE;
}

static void native_pause_frame_slice(short piece, short band, short height, point2d origin,
	rectangle2d *destination, rectangle2d *source)
{
	static short const x[3] = {-4, 12, 206};
	static short const widths[3] = {16, 194, 16};
	static short const source_y[4] = {0, 16, 128, 159};
	short destination_y[4] = {0, 16, height - 31, height};
	destination->x0 = origin.x + x[piece];
	destination->x1 = destination->x0 + widths[piece];
	destination->y0 = origin.y + destination_y[band];
	destination->y1 = origin.y + destination_y[band + 1];
	source->x0 = 0;
	source->x1 = piece == 1 ? 4 : 16;
	source->y0 = source_y[band];
	source->y1 = source_y[band + 1];
}
