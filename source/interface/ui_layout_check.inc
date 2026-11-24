/* debug.ui_layout_check: report text a widget cannot show whole.
 *
 * A text box draws each line of its text from its bounds and cuts it at its
 * clip rectangle; nothing wraps. The stock screens' text was authored to fit.
 * Text Halo OG adds, or stock text in a box it changed, can run past the
 * right edge or the bottom and be cut mid-word. With this on, each such text
 * is logged once, with the box and the size the text needs, in the font's own
 * metrics. tools/menu_layout_check.py walks the menus and fails on any line. */
void platform_log(const char *format, ...);

/* The stock error dialog's text box is wider than the frame it draws: this
 * is the frame's inside, with the left margin repeated on the right. */
#define UI_LAYOUT_ERROR_DIALOG_TEXT_WIDTH 211

static void ui_layout_check_text(
	struct widget_instance const *widget,
	rectangle2d const *bounds,
	rectangle2d const *clip,
	wchar_t const *text)
{
	static int enabled = -1;
	static struct { long tag_index; short width, available, bottom; } reported[256];
	static unsigned reported_count;
	rectangle2d text_bounds, cursor, open;
	short left, right, bottom, needed_width, needed_bottom;
	char const *name;
	char narrow[72];
	unsigned index;

	if (enabled < 0)
		enabled = config_boolean("debug.ui_layout_check") != 0;
	/* (text with button icons in it is laid out piece by piece around them) */
	if (!enabled || !text || !*text || string_has_icons_to_draw(text))
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
