/* Prototype Team Split Screen option in the authored Xbox Rules menus.
 * Cache-local clones preserve stock rule callbacks, artwork and staged editing. */
#include "game/teammate_view_variant.h"
#define TEAM_VIEW_EDIT_PREFIX "ui\\shell\\main_menu\\settings_select\\multiplayer_setup\\playlist_edit\\"
enum { _team_view_menu_initialize = 32030, _team_view_menu_accept = 32031 };
enum { TEAM_VIEW_MENU_COUNT = 5, TEAM_VIEW_MAX_RULE_ROWS = 8, TEAM_VIEW_MAX_HELP = 64 };
static char const *const team_view_rule_names[TEAM_VIEW_MENU_COUNT] = {"ctf", "koth", "slayer", "oddball", "race"};
static short const team_view_rule_rows[TEAM_VIEW_MENU_COUNT] = {5, 3, 5, 8, 4};
static struct
{
    struct ui_widget_definition screen, menu, row, label, spinner, help;
    struct ui_widget_child_reference screen_children[3], menu_children[TEAM_VIEW_MAX_RULE_ROWS + 1], row_children[2];
    struct ui_widget_event_handler_reference events[3];
    struct string_list labels, values, descriptions;
    struct string_list_entry label_entries[1], value_entries[2], description_entries[TEAM_VIEW_MAX_HELP + 2];
    wchar_t label_text[18], off[4], on[3], off_help[128], on_help[128];
    char runtime_names[12][128];
    short runtime_name_count;
    long screen_tag, menu_tag, row_tag, spinner_tag;
    short original_initialize, original_accept;
} team_view_menus[TEAM_VIEW_MENU_COUNT];

static long teammate_view_menu_register(short mode, char const *suffix, long group, void *definition)
{
    char *name;
    if (team_view_menus[mode].runtime_name_count >= 12) return NONE;
    /* The runtime registry retains the name pointer for the cache lifetime. */
    name = team_view_menus[mode].runtime_names[team_view_menus[mode].runtime_name_count++];
    snprintf(name, sizeof(team_view_menus[mode].runtime_names[0]), "ui\\native_team_view\\%s\\%s", team_view_rule_names[mode], suffix);
    return cache_files_register_runtime_ui_tag(group, name, definition);
}

static boolean teammate_view_menu_build(short mode)
{
    static wchar_t const label[] = L"TEAM SPLIT SCREEN";
    static wchar_t const off[] = L"OFF", on[] = L"ON";
    static wchar_t const off_help[] = L"Use your own screen for System Link games.";
    static wchar_t const on_help[] = L"Show your screen and one living teammate.\r\nSystem Link prototype; your own audio only.";
    struct string_list *original_descriptions;
    char path[256];
    long tag, i, description_count;
    short rows = team_view_rule_rows[mode];
    memset(&team_view_menus[mode], 0, sizeof(team_view_menus[mode]));
    snprintf(path, sizeof(path), TEAM_VIEW_EDIT_PREFIX "%s_edit\\%s_options_screen", team_view_rule_names[mode], team_view_rule_names[mode]);
    if (!pb_editor_clone(&team_view_menus[mode].screen, path)) return FALSE;
    snprintf(path, sizeof(path), TEAM_VIEW_EDIT_PREFIX "%s_edit\\%s_options_menu", team_view_rule_names[mode], team_view_rule_names[mode]);
    if (!pb_editor_clone(&team_view_menus[mode].menu, path) ||
        !pb_editor_clone(&team_view_menus[mode].row, TEAM_VIEW_EDIT_PREFIX "slayer_edit\\op_team_play") ||
        !pb_editor_clone(&team_view_menus[mode].label, TEAM_VIEW_EDIT_PREFIX "slayer_edit\\team_play_label") ||
        !pb_editor_clone(&team_view_menus[mode].spinner, TEAM_VIEW_EDIT_PREFIX "slayer_edit\\team_play_spinner")) return FALSE;
    if (team_view_menus[mode].screen.child_widgets.count != 3 ||
        team_view_menus[mode].menu.child_widgets.count != rows ||
        team_view_menus[mode].menu.event_handlers.count != 3 ||
        team_view_menus[mode].row.child_widgets.count != 2 ||
        team_view_menus[mode].menu.extended_description_widget.index == NONE) return FALSE;
    team_view_menus[mode].help = *ui_widget_definition_get(team_view_menus[mode].menu.extended_description_widget.index);
    if (team_view_menus[mode].help.text_label_string_list.index == NONE) return FALSE;
    original_descriptions = unicode_string_list_definition_get(team_view_menus[mode].help.text_label_string_list.index);
    description_count = original_descriptions->strings.count;
    if (description_count < 1 || description_count > TEAM_VIEW_MAX_HELP) return FALSE;
    memcpy(team_view_menus[mode].description_entries, original_descriptions->strings.address,
        description_count * sizeof(team_view_menus[mode].description_entries[0]));
    memcpy(team_view_menus[mode].label_text, label, sizeof(label));
    memcpy(team_view_menus[mode].off, off, sizeof(off));
    memcpy(team_view_menus[mode].on, on, sizeof(on));
    memcpy(team_view_menus[mode].off_help, off_help, sizeof(off_help));
    memcpy(team_view_menus[mode].on_help, on_help, sizeof(on_help));
    team_view_menus[mode].label_entries[0].string.address = team_view_menus[mode].label_text;
    team_view_menus[mode].label_entries[0].string.size = sizeof(label);
    team_view_menus[mode].value_entries[0].string.address = team_view_menus[mode].off;
    team_view_menus[mode].value_entries[0].string.size = sizeof(off);
    team_view_menus[mode].value_entries[1].string.address = team_view_menus[mode].on;
    team_view_menus[mode].value_entries[1].string.size = sizeof(on);
    team_view_menus[mode].description_entries[description_count].string.address = team_view_menus[mode].off_help;
    team_view_menus[mode].description_entries[description_count].string.size = sizeof(off_help);
    team_view_menus[mode].description_entries[description_count + 1].string.address = team_view_menus[mode].on_help;
    team_view_menus[mode].description_entries[description_count + 1].string.size = sizeof(on_help);
    team_view_menus[mode].labels.strings = (struct tag_block){1, team_view_menus[mode].label_entries, NULL};
    team_view_menus[mode].values.strings = (struct tag_block){2, team_view_menus[mode].value_entries, NULL};
    team_view_menus[mode].descriptions.strings = (struct tag_block){description_count + 2, team_view_menus[mode].description_entries, NULL};
    tag = teammate_view_menu_register(mode, "labels", UNICODE_STRING_LIST_TAG, &team_view_menus[mode].labels);
    if (tag == NONE) return FALSE;
    team_view_menus[mode].label.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
    team_view_menus[mode].label.string_list_index = 0;
    tag = teammate_view_menu_register(mode, "label", UI_WIDGET_DEFINITION_TAG, &team_view_menus[mode].label);
    if (tag == NONE) return FALSE;
    memcpy(team_view_menus[mode].row_children, team_view_menus[mode].row.child_widgets.address, sizeof(team_view_menus[mode].row_children));
    team_view_menus[mode].row_children[0].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    tag = teammate_view_menu_register(mode, "values", UNICODE_STRING_LIST_TAG, &team_view_menus[mode].values);
    if (tag == NONE) return FALSE;
    team_view_menus[mode].spinner.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
    team_view_menus[mode].spinner_tag = teammate_view_menu_register(mode, "spinner", UI_WIDGET_DEFINITION_TAG, &team_view_menus[mode].spinner);
    if (team_view_menus[mode].spinner_tag == NONE) return FALSE;
    team_view_menus[mode].row_children[1].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, team_view_menus[mode].spinner_tag);
    team_view_menus[mode].row.child_widgets.address = team_view_menus[mode].row_children;
    team_view_menus[mode].row_tag = teammate_view_menu_register(mode, "row", UI_WIDGET_DEFINITION_TAG, &team_view_menus[mode].row);
    if (team_view_menus[mode].row_tag == NONE) return FALSE;
    memcpy(team_view_menus[mode].menu_children, team_view_menus[mode].menu.child_widgets.address, rows * sizeof(team_view_menus[mode].menu_children[0]));
    team_view_menus[mode].menu_children[rows] = team_view_menus[mode].menu_children[rows - 1];
    team_view_menus[mode].menu_children[rows].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, team_view_menus[mode].row_tag);
    team_view_menus[mode].menu_children[rows].vertical_offset += 30;
    /* Nine Oddball rows must fit above the authored help box. */
    if (rows == TEAM_VIEW_MAX_RULE_ROWS)
        for (i = 0; i <= rows; i++) team_view_menus[mode].menu_children[i].vertical_offset = team_view_menus[mode].menu_children[0].vertical_offset + 27 * i;
    team_view_menus[mode].menu.child_widgets = (struct tag_block){rows + 1, team_view_menus[mode].menu_children, NULL};
    memcpy(team_view_menus[mode].events, team_view_menus[mode].menu.event_handlers.address, sizeof(team_view_menus[mode].events));
    team_view_menus[mode].original_initialize = team_view_menus[mode].events[0].function;
    team_view_menus[mode].original_accept = team_view_menus[mode].events[1].function;
    team_view_menus[mode].events[0].function = _team_view_menu_initialize;
    team_view_menus[mode].events[1].function = team_view_menus[mode].events[2].function = _team_view_menu_accept;
    team_view_menus[mode].menu.event_handlers.address = team_view_menus[mode].events;
    tag = teammate_view_menu_register(mode, "descriptions", UNICODE_STRING_LIST_TAG, &team_view_menus[mode].descriptions);
    if (tag == NONE) return FALSE;
    team_view_menus[mode].help.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
    tag = teammate_view_menu_register(mode, "help", UI_WIDGET_DEFINITION_TAG, &team_view_menus[mode].help);
    if (tag == NONE) return FALSE;
    team_view_menus[mode].menu.extended_description_widget = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    team_view_menus[mode].menu_tag = teammate_view_menu_register(mode, "menu", UI_WIDGET_DEFINITION_TAG, &team_view_menus[mode].menu);
    if (team_view_menus[mode].menu_tag == NONE) return FALSE;
    memcpy(team_view_menus[mode].screen_children, team_view_menus[mode].screen.child_widgets.address, sizeof(team_view_menus[mode].screen_children));
    team_view_menus[mode].screen_children[1].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, team_view_menus[mode].menu_tag);
    team_view_menus[mode].screen.child_widgets.address = team_view_menus[mode].screen_children;
    team_view_menus[mode].screen_tag = teammate_view_menu_register(mode, "screen", UI_WIDGET_DEFINITION_TAG, &team_view_menus[mode].screen);
    return team_view_menus[mode].screen_tag != NONE;
}

static short teammate_view_menu_mode(struct widget_instance const *widget)
{
    short mode;
    for (mode = 0; mode < TEAM_VIEW_MENU_COUNT; mode++)
        if (widget->definition_tag_index == team_view_menus[mode].menu_tag) return mode;
    return NONE;
}

static struct widget_instance *teammate_view_rule_spinner(struct widget_instance *row)
{
    struct widget_instance *spinner = row ? row->child : NULL;
    while (spinner && spinner->type != _ui_widget_type_spinner_list) spinner = spinner->next;
    return spinner;
}

static void teammate_view_menu_update(struct widget_instance *widget)
{
    short mode = teammate_view_menu_mode(widget), index;
    struct widget_instance *row = widget->child, *teams = NULL, *spinner;
    boolean enabled;
    if (mode == NONE) return;
    for (index = 0; row && index < team_view_rule_rows[mode]; index++) { teams = row; row = row->next; }
    if (!row) return;
    spinner = teammate_view_rule_spinner(teams);
    enabled = mode == 0 || (spinner && spinner->parameters.list.selected_index == 0);
    widget_instance_set_visibility_recursive(row, enabled);
    row->disabled = !enabled;
    if (!enabled && widget->focused_child == row) widget->focused_child = teams;
}

static boolean teammate_view_menu_hidden_row(struct widget_instance const *widget)
{
    short mode;
    if (widget->visible) return FALSE;
    for (mode = 0; mode < TEAM_VIEW_MENU_COUNT; mode++)
        if (widget->definition_tag_index == team_view_menus[mode].row_tag) return TRUE;
    return FALSE;
}

static boolean teammate_view_menu_event(struct widget_instance *widget, struct event_record *event, short function, boolean *widget_deleted)
{
    struct game_variant *variant = player_ui_get_edit_playlist_profile();
    short mode = teammate_view_menu_mode(widget);
    struct widget_instance *spinner;
    boolean enabled, result;
    if (mode == NONE || !variant) return FALSE;
    spinner = widget_instance_find_by_tag_index_recursive(widget, team_view_menus[mode].spinner_tag);
    if (!spinner) return FALSE;
    if (function == _team_view_menu_initialize)
    {
        result = ui_widget_event_handler_function_invoke(widget, event, team_view_menus[mode].original_initialize, widget_deleted);
        if (!result || *widget_deleted) return result;
        spinner->parameters.list.selected_index = teammate_view_variant_enabled(variant) ? 1 : 0;
        teammate_view_menu_update(widget);
        return TRUE;
    }
    if (function == _team_view_menu_accept)
    {
        /* Stock Accept may delete the menu; capture its staged selection first. */
        enabled = spinner->parameters.list.selected_index == 1;
        result = ui_widget_event_handler_function_invoke(widget, event, team_view_menus[mode].original_accept, widget_deleted);
        return result && teammate_view_variant_set_enabled(variant, enabled && variant->universal_variant.teams);
    }
    return FALSE;
}

static long teammate_view_menu_remap_tag(long tag)
{
    char const *name = tag_get_name(tag);
    char path[256], runtime[128];
    short mode;
    if (!name) return tag;
    for (mode = 0; mode < TEAM_VIEW_MENU_COUNT; mode++)
    {
        snprintf(path, sizeof(path), TEAM_VIEW_EDIT_PREFIX "%s_edit\\%s_options_screen", team_view_rule_names[mode], team_view_rule_names[mode]);
        if (strcmp(name, path)) continue;
        snprintf(runtime, sizeof(runtime), "ui\\native_team_view\\%s\\screen", team_view_rule_names[mode]);
        if (tag_loaded(UI_WIDGET_DEFINITION_TAG, runtime) == NONE && !teammate_view_menu_build(mode)) return tag;
        return team_view_menus[mode].screen_tag;
    }
    return tag;
}
#undef TEAM_VIEW_EDIT_PREFIX
