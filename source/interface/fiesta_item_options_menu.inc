/* Append Fiesta to the authored Starting Equipment selector. Cache-local
 * clones preserve retail artwork, font, navigation and the other Item Options. */
#define FIESTA_ITEM_PREFIX "ui\\shell\\main_menu\\settings_select\\multiplayer_setup\\item_options_edit\\"
#define FIESTA_ITEM_SCREEN FIESTA_ITEM_PREFIX "item_options_screen"
#define FIESTA_ITEM_RUNTIME "ui\\native_fiesta\\item_options_screen"
static struct
{
    struct ui_widget_definition screen, menu, row, spinner, help;
    struct ui_widget_child_reference screen_children[3], menu_children[4], row_children[2];
    struct string_list values, descriptions;
    struct string_list_entry value_entries[3], description_entries[20];
    wchar_t fiesta_value[7];
    wchar_t fiesta_help[128];
    long screen_tag;
} fiesta_item_options;

static boolean fiesta_item_options_build(void)
{
    static wchar_t const value[] = L"FIESTA";
    static wchar_t const help[] = L"Respawn with two random original Xbox weapons.\r\nA new pair is chosen each time you spawn.";
    struct string_list *original_values, *original_descriptions;
    long tag;
    memset(&fiesta_item_options, 0, sizeof(fiesta_item_options));
    if (!pb_editor_clone(&fiesta_item_options.screen, FIESTA_ITEM_SCREEN) ||
        !pb_editor_clone(&fiesta_item_options.menu, FIESTA_ITEM_PREFIX "item_options_menu") ||
        !pb_editor_clone(&fiesta_item_options.row, FIESTA_ITEM_PREFIX "op_starting_equipment") ||
        !pb_editor_clone(&fiesta_item_options.spinner, FIESTA_ITEM_PREFIX "item_options_starting_equipment_spinner") ||
        !pb_editor_clone(&fiesta_item_options.help, FIESTA_ITEM_PREFIX "item_options_help"))
        return FALSE;
    if (fiesta_item_options.screen.child_widgets.count != 3 ||
        fiesta_item_options.menu.child_widgets.count != 4 ||
        fiesta_item_options.row.child_widgets.count != 2 ||
        fiesta_item_options.spinner.text_label_string_list.index == NONE ||
        fiesta_item_options.help.text_label_string_list.index == NONE)
        return FALSE;
    original_values = unicode_string_list_definition_get(fiesta_item_options.spinner.text_label_string_list.index);
    original_descriptions = unicode_string_list_definition_get(fiesta_item_options.help.text_label_string_list.index);
    if (original_values->strings.count != 2 || original_descriptions->strings.count != 19)
        return FALSE;
    memcpy(fiesta_item_options.value_entries, original_values->strings.address,
        2 * sizeof(fiesta_item_options.value_entries[0]));
    memcpy(fiesta_item_options.description_entries, original_descriptions->strings.address,
        19 * sizeof(fiesta_item_options.description_entries[0]));
    memcpy(fiesta_item_options.fiesta_value, value, sizeof(value));
    memcpy(fiesta_item_options.fiesta_help, help, sizeof(help));
    fiesta_item_options.value_entries[2].string.address = fiesta_item_options.fiesta_value;
    fiesta_item_options.value_entries[2].string.size = sizeof(value);
    fiesta_item_options.description_entries[19].string.address = fiesta_item_options.fiesta_help;
    fiesta_item_options.description_entries[19].string.size = sizeof(help);
    fiesta_item_options.values.strings = (struct tag_block){3, fiesta_item_options.value_entries, NULL};
    fiesta_item_options.descriptions.strings = (struct tag_block){20, fiesta_item_options.description_entries, NULL};
    tag = cache_files_register_runtime_ui_tag(UNICODE_STRING_LIST_TAG, "ui\\native_fiesta\\starting_equipment_values", &fiesta_item_options.values);
    if (tag == NONE) return FALSE;
    fiesta_item_options.spinner.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
    tag = cache_files_register_runtime_ui_tag(UNICODE_STRING_LIST_TAG, "ui\\native_fiesta\\starting_equipment_help", &fiesta_item_options.descriptions);
    if (tag == NONE) return FALSE;
    fiesta_item_options.help.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
    tag = pb_editor_register("ui\\native_fiesta\\starting_equipment_spinner", &fiesta_item_options.spinner);
    if (tag == NONE) return FALSE;
    memcpy(fiesta_item_options.row_children, fiesta_item_options.row.child_widgets.address, sizeof(fiesta_item_options.row_children));
    fiesta_item_options.row_children[1].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    fiesta_item_options.row.child_widgets.address = fiesta_item_options.row_children;
    tag = pb_editor_register("ui\\native_fiesta\\starting_equipment_row", &fiesta_item_options.row);
    if (tag == NONE) return FALSE;
    memcpy(fiesta_item_options.menu_children, fiesta_item_options.menu.child_widgets.address, sizeof(fiesta_item_options.menu_children));
    fiesta_item_options.menu_children[3].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    fiesta_item_options.menu.child_widgets.address = fiesta_item_options.menu_children;
    tag = pb_editor_register("ui\\native_fiesta\\item_options_help", &fiesta_item_options.help);
    if (tag == NONE) return FALSE;
    fiesta_item_options.menu.extended_description_widget = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    tag = pb_editor_register("ui\\native_fiesta\\item_options_menu", &fiesta_item_options.menu);
    if (tag == NONE) return FALSE;
    memcpy(fiesta_item_options.screen_children, fiesta_item_options.screen.child_widgets.address, sizeof(fiesta_item_options.screen_children));
    fiesta_item_options.screen_children[1].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    fiesta_item_options.screen.child_widgets.address = fiesta_item_options.screen_children;
    fiesta_item_options.screen_tag = pb_editor_register(FIESTA_ITEM_RUNTIME, &fiesta_item_options.screen);
    return fiesta_item_options.screen_tag != NONE;
}

static long fiesta_item_options_remap_tag(long tag)
{
    char const *name = tag_get_name(tag);
    if (!name || strcmp(name, FIESTA_ITEM_SCREEN)) return tag;
    if (tag_loaded(UI_WIDGET_DEFINITION_TAG, FIESTA_ITEM_RUNTIME) == NONE &&
        !fiesta_item_options_build()) return tag;
    return fiesta_item_options.screen_tag;
}
#undef FIESTA_ITEM_PREFIX
#undef FIESTA_ITEM_SCREEN
#undef FIESTA_ITEM_RUNTIME
