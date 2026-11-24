/* The native Pause kit: the measurements every native Pause page shares, the
 * blue frame at any size and the selection box at any width.
 *
 * The resident art is three frame textures with a 159-pixel panel and one 202
 * by 27 selection box. Ordinary widget bounds crop a texture instead of
 * stretching it, so a runtime definition carrying one of the two flags below
 * is drawn from explicit source rectangles: corners and ends stay as authored
 * and only the middle stretches. No cache tag sets these flags. */
#include <stdio.h>

enum
{
	_widget_native_pause_row_bit = 29,
	_widget_native_pause_frame_bit = 30
};

enum
{
	_native_pause_wide,          /* one player: the whole screen */
	_native_pause_split_menu,    /* split screen: the Pause list and the Game Settings list */
	_native_pause_split_options, /* split screen: a page of settings, eight rows in 240 lines */
	NUMBER_OF_NATIVE_PAUSE_STYLES
};

enum
{
	/* One overflow rule: a page shows at most this many rows, its ACCEPT or
	 * APPLY included. A page that needs more gets a sub-page, as Audio has
	 * TIMER AUDIO; rows are never squeezed. */
	NATIVE_PAUSE_MAXIMUM_ROWS = 8,
	NATIVE_PAUSE_FRAME_MARGIN = 12, /* rows to the frame's outer edge */
	NATIVE_PAUSE_FRAME_BORDER = 4,  /* the frame's top line */
	NATIVE_PAUSE_FRAME_CORNER = 16,
	NATIVE_PAUSE_FOOTER = 29,       /* the legend's divider to the frame's bottom */
	NATIVE_PAUSE_LEGEND_Y = 25,     /* the legend's top, up from the frame's bottom */
	NATIVE_PAUSE_HELP_WIDTH = 284,
	NATIVE_PAUSE_HELP_GAP = 6,
	NATIVE_PAUSE_BOX_WIDTH = 202,   /* the selection box as authored */
	NATIVE_PAUSE_BOX_HEIGHT = 27,
	NATIVE_PAUSE_BOX_END = 16,
	NATIVE_PAUSE_BOX_CAP = 10,
	NATIVE_PAUSE_MAXIMUM_FRAMES = 16
};

struct native_pause_style
{
	boolean small_font;
	short row_width;  /* the selection box, and the row's place for the mouse */
	short row_height; /* rows follow each other at this pitch: a box never reaches the next row */
	short text_y;     /* text top inside a row; 3 is the stock button's */
	short text_inset; /* a setting's name and value, from the row's ends */
	short top;        /* frame top to the title */
	short title_gap;  /* title to the first row; a title is a row without a box */
	short action_gap; /* settings to ACCEPT or APPLY */
	short bottom;     /* last row to the legend's divider */
};

/* Every row of a page uses its style's font. Split screen keeps the original
 * large rows where four fit and uses the small font for pages of settings. */
static struct native_pause_style const native_pause_styles[NUMBER_OF_NATIVE_PAUSE_STYLES] =
{
	{FALSE, 284, 27, 3, 10, 10, 6, 13, 8},
	{FALSE, 250, 27, 3, 10, 10, 6, 13, 8},
	{TRUE, 250, 21, 2, 10, 5, 2, 6, 5},
};

struct native_pause_panel
{
	long frame_tag;
	short x, y;         /* the rows' left edge and the frame's top, in the viewport */
	short height;       /* the frame */
	short title_y;      /* these three from the frame's top */
	short rows_y;
	short rows_height;
};

static char native_pause_frame_names[NATIVE_PAUSE_MAXIMUM_FRAMES][48];
static struct ui_widget_definition native_pause_frame_definitions[NATIVE_PAUSE_MAXIMUM_FRAMES];
static long native_pause_frame_indices[NATIVE_PAUSE_MAXIMUM_FRAMES];
static long native_pause_frame_bitmaps[3];
static short native_pause_frame_count;

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

/* A frame for each size in use. Pages of the same size share one. */
static long native_pause_frame_tag(short width, short height)
{
	static char const *const names[3] = {
		"ui\\shell\\bitmaps\\pausebox2_left",
		"ui\\shell\\bitmaps\\pausebox2_center",
		"ui\\shell\\bitmaps\\pausebox2_right"};
	struct ui_widget_definition *definition;
	short index;
	if (width < 2 * NATIVE_PAUSE_FRAME_CORNER || height < NATIVE_PAUSE_FRAME_CORNER + 31) return NONE;
	/* Runtime registrations end with the map that made them. */
	if (native_pause_frame_count &&
		tag_loaded(UI_WIDGET_DEFINITION_TAG, native_pause_frame_names[0]) != native_pause_frame_indices[0])
		native_pause_frame_count = 0;
	for (index = 0; index < native_pause_frame_count; index++)
		if (native_pause_frame_definitions[index].bounds.x1 == width &&
			native_pause_frame_definitions[index].bounds.y1 == height)
			return native_pause_frame_indices[index];
	if (native_pause_frame_count == NATIVE_PAUSE_MAXIMUM_FRAMES) return NONE;
	for (index = 0; index < 3; index++)
	{
		native_pause_frame_bitmaps[index] = native_pause_resident_tag('bitm', names[index]);
		if (native_pause_frame_bitmaps[index] == NONE) return NONE;
	}
	index = native_pause_frame_count;
	definition = &native_pause_frame_definitions[index];
	csmemset(definition, 0, sizeof(*definition));
	definition->type = _ui_widget_type_container;
	definition->controller_index = _widget_controller_any;
	definition->flags = FLAG(_widget_native_pause_frame_bit);
	definition->bounds.x1 = width;
	definition->bounds.y1 = height;
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
	snprintf(native_pause_frame_names[index], sizeof(native_pause_frame_names[index]),
		"ui\\native_settings\\pause_frame_%dx%d", width, height);
	native_pause_frame_indices[index] = cache_files_register_runtime_ui_tag(
		UI_WIDGET_DEFINITION_TAG, native_pause_frame_names[index], definition);
	if (native_pause_frame_indices[index] == NONE) return NONE;
	native_pause_frame_count++;
	return native_pause_frame_indices[index];
}

static void native_pause_frame_slice(short piece, short band, short width, short height, point2d origin,
	rectangle2d *destination, rectangle2d *source)
{
	static short const source_y[4] = {0, 16, 128, 159};
	short const x[4] = {0, NATIVE_PAUSE_FRAME_CORNER, (short)(width - NATIVE_PAUSE_FRAME_CORNER), width};
	short const y[4] = {0, 16, (short)(height - 31), height};
	destination->x0 = origin.x + x[piece];
	destination->x1 = origin.x + x[piece + 1];
	destination->y0 = origin.y + y[band];
	destination->y1 = origin.y + y[band + 1];
	source->x0 = 0;
	source->x1 = piece == 1 ? 4 : NATIVE_PAUSE_FRAME_CORNER;
	source->y0 = source_y[band];
	source->y1 = source_y[band + 1];
}

/* The selection box in a row of any size: its rounded ends and its top and
 * bottom lines keep their authored pixels. At 202 by 27 the nine pieces are
 * the stock crop. */
static void native_pause_box_slice(short piece, short band, rectangle2d const *row,
	rectangle2d *destination, rectangle2d *source)
{
	static short const source_x[4] = {0, NATIVE_PAUSE_BOX_END,
		NATIVE_PAUSE_BOX_WIDTH - NATIVE_PAUSE_BOX_END, NATIVE_PAUSE_BOX_WIDTH};
	static short const source_y[4] = {0, NATIVE_PAUSE_BOX_CAP,
		NATIVE_PAUSE_BOX_HEIGHT - NATIVE_PAUSE_BOX_CAP, NATIVE_PAUSE_BOX_HEIGHT};
	short end = (short)((row->x1 - row->x0) / 2), cap = (short)((row->y1 - row->y0) / 2);
	if (end > NATIVE_PAUSE_BOX_END) end = NATIVE_PAUSE_BOX_END;
	if (cap > NATIVE_PAUSE_BOX_CAP) cap = NATIVE_PAUSE_BOX_CAP;
	{
		short const x[4] = {row->x0, (short)(row->x0 + end), (short)(row->x1 - end), row->x1};
		short const y[4] = {row->y0, (short)(row->y0 + cap), (short)(row->y1 - cap), row->y1};
		destination->x0 = x[piece];
		destination->x1 = x[piece + 1];
		destination->y0 = y[band];
		destination->y1 = y[band + 1];
	}
	source->x0 = source_x[piece];
	source->x1 = source_x[piece + 1];
	source->y0 = source_y[band];
	source->y1 = source_y[band + 1];
}

static short native_pause_style_for(rectangle2d const *viewport, boolean options)
{
	if (viewport->y1 - viewport->y0 >= 480) return _native_pause_wide;
	return options ? _native_pause_split_options : _native_pause_split_menu;
}

/* A row in one of the styles: the resident selection box, the style's font,
 * centred blue text. A page's title is the same without the box. */
static boolean native_pause_row_definition(struct ui_widget_definition *definition, short style_index,
	long fallback_bitmap)
{
	struct native_pause_style const *style = &native_pause_styles[style_index];
	long font = native_pause_resident_tag(FONT_GROUP_TAG, style->small_font ? "ui\\small_ui" : "ui\\large_ui");
	long bitmap = native_pause_resident_tag('bitm', "ui\\shell\\bitmaps\\menu_bkds");
	if (font == NONE)
		font = native_pause_resident_tag(FONT_GROUP_TAG, style->small_font ? "ui\\large_ui" : "ui\\small_ui");
	if (bitmap == NONE) bitmap = fallback_bitmap;
	if (font == NONE || !tag_index_is_group(bitmap, 'bitm')) return FALSE;
	csmemset(definition, 0, sizeof(*definition));
	definition->type = _ui_widget_type_text_box;
	definition->controller_index = _widget_controller_any;
	definition->flags = FLAG(_widget_native_pause_row_bit);
	definition->bounds.x1 = style->row_width;
	definition->bounds.y1 = style->row_height;
	definition->background_bitmap.group_tag = 'bitm';
	definition->background_bitmap.index = bitmap;
	definition->text_label_string_list.group_tag = UNICODE_STRING_LIST_TAG;
	definition->text_label_string_list.index = NONE;
	definition->text_font.group_tag = FONT_GROUP_TAG;
	definition->text_font.index = font;
	definition->text_color.alpha = 1.0f;
	definition->text_color.red = 40.0f / 255.0f;
	definition->text_color.green = 150.0f / 255.0f;
	definition->text_color.blue = 1.0f;
	definition->justification = _text_justification_center;
	definition->vertical_offset = style->text_y;
	definition->list_header_bitmap.group_tag = definition->list_footer_bitmap.group_tag = 'bitm';
	definition->list_header_bitmap.index = definition->list_footer_bitmap.index = NONE;
	definition->extended_description_widget.group_tag = UI_WIDGET_DEFINITION_TAG;
	definition->extended_description_widget.index = NONE;
	return TRUE;
}

static void native_pause_title_definition(struct ui_widget_definition *definition,
	struct ui_widget_definition const *row)
{
	*definition = *row;
	definition->flags = 0;
	definition->background_bitmap.index = NONE;
	definition->text_color.red = definition->text_color.green = definition->text_color.blue = 1.0f;
}

/* Where row `row` of `rows` starts in its column. */
static short native_pause_row_y(short style_index, short row, short rows, boolean action)
{
	struct native_pause_style const *style = &native_pause_styles[style_index];
	return (short)(row * style->row_height + (action && row == rows - 1 ? style->action_gap : 0));
}

static short native_pause_legend_x(short style_index)
{
	return (short)((native_pause_styles[style_index].row_width - NATIVE_PAUSE_BOX_WIDTH) / 2 + 17);
}

/* The frame follows its content: the same space above the title, between the
 * title and the rows, and between the last row and the legend on every page.
 * The panel is centred in its viewport. */
static boolean native_pause_panel_place(struct native_pause_panel *panel, short style_index,
	rectangle2d const *viewport, short rows, boolean title, boolean action)
{
	struct native_pause_style const *style = &native_pause_styles[style_index];
	if (rows < 1 || rows > NATIVE_PAUSE_MAXIMUM_ROWS) return FALSE;
	panel->title_y = style->top;
	panel->rows_y = title ? (short)(style->top + style->row_height + style->title_gap) :
		(short)(style->bottom + NATIVE_PAUSE_FRAME_BORDER);
	panel->rows_height = (short)(rows * style->row_height + (action ? style->action_gap : 0));
	panel->height = (short)(panel->rows_y + panel->rows_height + style->bottom + NATIVE_PAUSE_FOOTER);
	panel->x = (short)((viewport->x1 - viewport->x0 - style->row_width) / 2);
	panel->y = (short)((viewport->y1 - viewport->y0 - panel->height) / 2);
	if (panel->x < NATIVE_PAUSE_FRAME_MARGIN || panel->y < 0) return FALSE;
	panel->frame_tag = native_pause_frame_tag((short)(style->row_width + 2 * NATIVE_PAUSE_FRAME_MARGIN), panel->height);
	return panel->frame_tag != NONE;
}
