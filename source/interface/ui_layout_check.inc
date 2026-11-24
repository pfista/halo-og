/* debug.ui_layout_check: report text a widget cannot show whole, and rows of
 * a list that reach each other.
 *
 * A text box draws each line of its text from its bounds and cuts it at its
 * clip rectangle; nothing wraps. The stock screens' text was authored to fit.
 * Text Halo OG adds, or stock text in a box it changed, can run past the
 * right edge or the bottom and be cut mid-word. With this on, each such text
 * is logged once, with the box and the size the text needs, in the font's own
 * metrics. tools/menu_layout_check.py walks the menus and fails on any line. */
void platform_log(const char *format, ...);

static boolean ui_layout_check_enabled(void)
{
	static int enabled = -1;
	if (enabled < 0)
		enabled = config_boolean("debug.ui_layout_check") != 0;
	return enabled != 0;
}

/* The stock error dialog's text box is wider than the frame it draws: this
 * is the frame's inside, with the left margin repeated on the right. */
#define UI_LAYOUT_ERROR_DIALOG_TEXT_WIDTH 211

static void ui_layout_check_text(
	struct widget_instance const *widget,
	rectangle2d const *bounds,
	rectangle2d const *clip,
	wchar_t const *text)
{
	static struct { long tag_index; short width, available, bottom; } reported[256];
	static unsigned reported_count;
	rectangle2d text_bounds, cursor, open;
	short left, right, bottom, needed_width, needed_bottom;
	char const *name;
	char narrow[72];
	unsigned index;

	/* (text with button icons in it is laid out piece by piece around them) */
	if (!ui_layout_check_enabled() || !text || !*text || string_has_icons_to_draw(text))
		return;
	/* Measured in a box with no right edge or bottom: the measurement cuts
	 * glyphs at its box exactly as drawing does, so measuring in the widget's
	 * own box could never find text wider than it. */
	open = *bounds;
	open.x1 = (short)(open.x0 + 8192);
	open.y1 = (short)(open.y0 + 8192);
	draw_unicode_string_compute_bounds(&open, text, &text_bounds, &cursor);
	left = MAX(bounds->x0, clip->x0);
	right = MIN(bounds->x1, clip->x1);
	bottom = MIN(bounds->y1, clip->y1);
	name = tag_get_name(widget->definition_tag_index);
	if (!csstrncmp(name, "ui\\shell\\error\\", 15) || !csstrcmp(name, "ui\\native_pb\\locked_message"))
		right = MIN(right, (short)(left + UI_LAYOUT_ERROR_DIALOG_TEXT_WIDTH));
	needed_width = (short)(text_bounds.x1 - text_bounds.x0);
	/* The last line's baseline, about a fifth of a line above its bottom:
	 * stock boxes end at the baseline and let the descenders hang below. */
	needed_bottom = (short)(cursor.y1 - (cursor.y1 - cursor.y0) / 5);
	if (needed_width <= right - left && needed_bottom <= bottom + 1)
		return;
	for (index = 0; index < reported_count; index++)
	{
		if (reported[index].tag_index == widget->definition_tag_index && reported[index].width == needed_width &&
			reported[index].available == (short)(right - left) && reported[index].bottom == needed_bottom)
			return;
	}
	if (reported_count < NUMBEROF(reported))
	{
		reported[reported_count].tag_index = widget->definition_tag_index;
		reported[reported_count].width = needed_width;
		reported[reported_count].available = (short)(right - left);
		reported[reported_count++].bottom = needed_bottom;
	}
	for (index = 0; index + 1 < sizeof(narrow) && text[index]; index++)
		narrow[index] = text[index] >= 32 && text[index] < 127 ? (char)text[index] : text[index] == L'\n' ? '|' : ' ';
	narrow[index] = 0;
	platform_log("ui layout: text does not fit: %s \"%s\" is %d wide with its last baseline at y %d; its box is %d wide and ends at y %d",
		name, narrow, needed_width, needed_bottom, right - left, bottom);
}

/* A row's bounds are its selection box and its place for the mouse. When two
 * rows of a list overlap, the focused row's box is drawn over its neighbour's
 * text and a click between them picks the wrong one. Each text can still fit
 * its own box, which is how a page of rows packed closer than their boxes
 * once passed this check. Each pair is logged once. */
static void ui_layout_check_rows(
	struct widget_instance const *list,
	struct ui_widget_definition const *list_definition)
{
	static struct { long first, second; short shared; } reported[64];
	static unsigned reported_count;
	struct widget_instance const *row, *other;
	long shown = TEST_FLAG(list_definition->list_flags, _list_items_generated_in_code) ?
		list->parameters.list.number_of_items : LONG_MAX;
	long row_index = 0, other_index;
	unsigned index;

	if (!ui_layout_check_enabled())
		return;
	for (row = list->child; row && row_index < shown; row = row->next, row_index++)
	{
		struct ui_widget_definition const *definition;

		if (!row->visible || row->definition_tag_index == NONE)
			continue;
		definition = ui_widget_definition_get(row->definition_tag_index);
		for (other = row->next, other_index = row_index + 1; other && other_index < shown;
			other = other->next, other_index++)
		{
			struct ui_widget_definition const *other_definition;
			short across, down;

			if (!other->visible || other->definition_tag_index == NONE)
				continue;
			other_definition = ui_widget_definition_get(other->definition_tag_index);
			across = (short)(MIN(definition->bounds.x1 + row->horizontal_offset,
					other_definition->bounds.x1 + other->horizontal_offset) -
				MAX(definition->bounds.x0 + row->horizontal_offset,
					other_definition->bounds.x0 + other->horizontal_offset));
			down = (short)(MIN(definition->bounds.y1 + row->vertical_offset,
					other_definition->bounds.y1 + other->vertical_offset) -
				MAX(definition->bounds.y0 + row->vertical_offset,
					other_definition->bounds.y0 + other->vertical_offset));
			if (across <= 0 || down <= 0)
				continue;
			for (index = 0; index < reported_count; index++)
			{
				if (reported[index].first == row->definition_tag_index &&
					reported[index].second == other->definition_tag_index && reported[index].shared == down)
					break;
			}
			if (index < reported_count)
				continue;
			if (reported_count < NUMBEROF(reported))
			{
				reported[reported_count].first = row->definition_tag_index;
				reported[reported_count].second = other->definition_tag_index;
				reported[reported_count++].shared = down;
			}
			platform_log("ui layout: rows overlap: %s and %s in %s share %d lines",
				tag_get_name(row->definition_tag_index), tag_get_name(other->definition_tag_index),
				tag_get_name(list->definition_tag_index), down);
		}
	}
}
