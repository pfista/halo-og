/* Append Fiesta and its expanded Weapon Set choices to authored selectors. Cache-local
 * clones preserve retail artwork, font, navigation and the other Item Options. */
#define FIESTA_ITEM_PREFIX "ui\\shell\\main_menu\\settings_select\\multiplayer_setup\\item_options_edit\\"
#define FIESTA_ITEM_SCREEN FIESTA_ITEM_PREFIX "item_options_screen"
#define FIESTA_ITEM_RUNTIME "ui\\native_fiesta\\item_options_screen"
static struct
{
    struct ui_widget_definition screen, menu, row, spinner, weapon_row, weapon_spinner, help;
    struct ui_widget_child_reference screen_children[3], menu_children[4], row_children[2];
    struct ui_widget_child_reference weapon_row_children[2];
    struct string_list values, weapon_values, descriptions;
    struct string_list_entry value_entries[3], weapon_value_entries[12], description_entries[22];
    wchar_t fiesta_value[8];
    wchar_t uncut_value[6], all_value[4];
    wchar_t fiesta_help[128], uncut_help[128], all_help[128];
    long screen_tag, menu_tag;
} fiesta_item_options;

static boolean fiesta_item_options_build(void)
{
    static wchar_t const value[] = L"FIESTA";
    static wchar_t const help[] = L"Respawn with two random weapons from this set.\r\nA new pair is chosen each time you spawn.";
    static wchar_t const uncut_value[] = L"UNCUT", all_value[] = L"ALL";
    static wchar_t const uncut_help[] = L"Fiesta uses all restored pre-release weapons,\r\neven those absent from the original map.";
    static wchar_t const all_help[] = L"Pfiesta uses the full playable weapon arsenal.\r\nIncludes restored and community weapons.";
    struct string_list *original_values, *original_weapon_values, *original_descriptions;
    long tag;
    memset(&fiesta_item_options, 0, sizeof(fiesta_item_options));
    if (!pb_editor_clone(&fiesta_item_options.screen, FIESTA_ITEM_SCREEN) ||
        !pb_editor_clone(&fiesta_item_options.menu, FIESTA_ITEM_PREFIX "item_options_menu") ||
        !pb_editor_clone(&fiesta_item_options.row, FIESTA_ITEM_PREFIX "op_starting_equipment") ||
        !pb_editor_clone(&fiesta_item_options.spinner, FIESTA_ITEM_PREFIX "item_options_starting_equipment_spinner") ||
        !pb_editor_clone(&fiesta_item_options.weapon_row, FIESTA_ITEM_PREFIX "op_weapon_set") ||
        !pb_editor_clone(&fiesta_item_options.weapon_spinner, FIESTA_ITEM_PREFIX "item_options_weapon_set_spinner") ||
        !pb_editor_clone(&fiesta_item_options.help, FIESTA_ITEM_PREFIX "item_options_help"))
        return FALSE;
    if (fiesta_item_options.screen.child_widgets.count != 3 ||
        fiesta_item_options.menu.child_widgets.count != 4 ||
        fiesta_item_options.row.child_widgets.count != 2 ||
        fiesta_item_options.weapon_row.child_widgets.count != 2 ||
        fiesta_item_options.spinner.text_label_string_list.index == NONE ||
        fiesta_item_options.weapon_spinner.text_label_string_list.index == NONE ||
        fiesta_item_options.help.text_label_string_list.index == NONE)
        return FALSE;
    original_values = unicode_string_list_definition_get(fiesta_item_options.spinner.text_label_string_list.index);
    original_weapon_values = unicode_string_list_definition_get(fiesta_item_options.weapon_spinner.text_label_string_list.index);
    original_descriptions = unicode_string_list_definition_get(fiesta_item_options.help.text_label_string_list.index);
    if (original_values->strings.count != 2 || original_weapon_values->strings.count != 10 ||
        original_descriptions->strings.count != 19)
        return FALSE;
    memcpy(fiesta_item_options.value_entries, original_values->strings.address,
        2 * sizeof(fiesta_item_options.value_entries[0]));
    memcpy(fiesta_item_options.description_entries, original_descriptions->strings.address,
        17 * sizeof(fiesta_item_options.description_entries[0]));
    memcpy(&fiesta_item_options.description_entries[19],
        (struct string_list_entry *)original_descriptions->strings.address + 17,
        2 * sizeof(fiesta_item_options.description_entries[0]));
    memcpy(fiesta_item_options.weapon_value_entries, original_weapon_values->strings.address,
        10 * sizeof(fiesta_item_options.weapon_value_entries[0]));
    memcpy(fiesta_item_options.fiesta_value, value, sizeof(value));
    memcpy(fiesta_item_options.fiesta_help, help, sizeof(help));
    memcpy(fiesta_item_options.uncut_value, uncut_value, sizeof(uncut_value));
    memcpy(fiesta_item_options.all_value, all_value, sizeof(all_value));
    memcpy(fiesta_item_options.uncut_help, uncut_help, sizeof(uncut_help));
    memcpy(fiesta_item_options.all_help, all_help, sizeof(all_help));
    fiesta_item_options.value_entries[2].string.address = fiesta_item_options.fiesta_value;
    fiesta_item_options.value_entries[2].string.size = sizeof(value);
    fiesta_item_options.weapon_value_entries[10].string.address = fiesta_item_options.uncut_value;
    fiesta_item_options.weapon_value_entries[10].string.size = sizeof(uncut_value);
    fiesta_item_options.weapon_value_entries[11].string.address = fiesta_item_options.all_value;
    fiesta_item_options.weapon_value_entries[11].string.size = sizeof(all_value);
    fiesta_item_options.description_entries[17].string.address = fiesta_item_options.uncut_help;
    fiesta_item_options.description_entries[17].string.size = sizeof(uncut_help);
    fiesta_item_options.description_entries[18].string.address = fiesta_item_options.all_help;
    fiesta_item_options.description_entries[18].string.size = sizeof(all_help);
    fiesta_item_options.description_entries[21].string.address = fiesta_item_options.fiesta_help;
    fiesta_item_options.description_entries[21].string.size = sizeof(help);
    fiesta_item_options.values.strings = (struct tag_block){3, fiesta_item_options.value_entries, NULL};
    fiesta_item_options.weapon_values.strings = (struct tag_block){12, fiesta_item_options.weapon_value_entries, NULL};
    fiesta_item_options.descriptions.strings = (struct tag_block){22, fiesta_item_options.description_entries, NULL};
    tag = cache_files_register_runtime_ui_tag(UNICODE_STRING_LIST_TAG, "ui\\native_fiesta\\starting_equipment_values", &fiesta_item_options.values);
    if (tag == NONE) return FALSE;
    fiesta_item_options.spinner.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
    tag = cache_files_register_runtime_ui_tag(UNICODE_STRING_LIST_TAG, "ui\\native_fiesta\\weapon_set_values", &fiesta_item_options.weapon_values);
    if (tag == NONE) return FALSE;
    fiesta_item_options.weapon_spinner.text_label_string_list = pb_editor_reference(UNICODE_STRING_LIST_TAG, tag);
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
    tag = pb_editor_register("ui\\native_fiesta\\weapon_set_spinner", &fiesta_item_options.weapon_spinner);
    if (tag == NONE) return FALSE;
    memcpy(fiesta_item_options.weapon_row_children, fiesta_item_options.weapon_row.child_widgets.address,
        sizeof(fiesta_item_options.weapon_row_children));
    fiesta_item_options.weapon_row_children[1].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    fiesta_item_options.weapon_row.child_widgets.address = fiesta_item_options.weapon_row_children;
    tag = pb_editor_register("ui\\native_fiesta\\weapon_set_row", &fiesta_item_options.weapon_row);
    if (tag == NONE) return FALSE;
    fiesta_item_options.menu_children[2].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    fiesta_item_options.menu.child_widgets.address = fiesta_item_options.menu_children;
    tag = pb_editor_register("ui\\native_fiesta\\item_options_help", &fiesta_item_options.help);
    if (tag == NONE) return FALSE;
    fiesta_item_options.menu.extended_description_widget = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    tag = pb_editor_register("ui\\native_fiesta\\item_options_menu", &fiesta_item_options.menu);
    if (tag == NONE) return FALSE;
    fiesta_item_options.menu_tag = tag;
    memcpy(fiesta_item_options.screen_children, fiesta_item_options.screen.child_widgets.address, sizeof(fiesta_item_options.screen_children));
    fiesta_item_options.screen_children[1].widget_tag = pb_editor_reference(UI_WIDGET_DEFINITION_TAG, tag);
    fiesta_item_options.screen.child_widgets.address = fiesta_item_options.screen_children;
    fiesta_item_options.screen_tag = pb_editor_register(FIESTA_ITEM_RUNTIME, &fiesta_item_options.screen);
    return fiesta_item_options.screen_tag != NONE;
}

static void fiesta_item_options_update_name(struct widget_instance const *widget)
{
    static wchar_t const fiesta[] = L"FIESTA", pfiesta[] = L"PFIESTA";
    struct widget_instance const *row, *spinner;
    wchar_t const *value;
    long size;
    short row_index;
    if (widget->definition_tag_index != fiesta_item_options.menu_tag ||
        fiesta_item_options.values.strings.count != 3) return;
    /* Read the live Weapon Set spinner, so the spelling previews before Accept
     * and reopening after Cancel restores the saved selection. */
    row = widget->child;
    for (row_index = 0; row && row_index < 2; row_index++) row = row->next;
    if (!row) return;
    spinner = row->child;
    while (spinner && spinner->type != _ui_widget_type_spinner_list) spinner = spinner->next;
    if (!spinner) return;
    /* All is UI index 11; the mode remains the existing Fiesta choice 2. */
    value = spinner->parameters.list.selected_index == 11 ? pfiesta : fiesta;
    size = spinner->parameters.list.selected_index == 11 ? sizeof(pfiesta) : sizeof(fiesta);
    memcpy(fiesta_item_options.fiesta_value, value, size);
    fiesta_item_options.value_entries[2].string.size = size;
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
