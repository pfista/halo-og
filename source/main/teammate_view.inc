/* Camera-only prototype: one real local player plus one same-team remote view.
 * Keep all state here in presentation, outside game-state/player ownership.
 * Use received units as they stand; never request or synthesize network input.
 */
static long teammate_view_player_index = NONE;

static boolean teammate_view_available(void)
{
	return game_in_progress() && game_engine_running() && local_player_count() == 1 &&
		(game_connection() == _game_connection_network_server ||
		 game_connection() == _game_connection_network_client) &&
		!game_engine_force_single_screen() && !cinematic_in_progress() &&
		teammate_view_variant_enabled(game_engine_get_variant());
}

boolean teammate_view_split_screen_active(void)
{
	/* Keep the local viewport and HUD layout stable while the teammate dies,
	 * respawns, changes teams or temporarily has no usable camera. */
	return teammate_view_available();
}

static boolean teammate_view_valid_player(long player_index)
{
	long self_index;
	struct player_datum *self, *player;
	struct unit_datum *unit;
	if (!teammate_view_available() || player_index == NONE)
		return FALSE;
	self_index = local_player_get_player_index(local_player_get_next(NONE));
	self = self_index == NONE ? NULL : player_try_and_get(self_index);
	player = player_try_and_get(player_index);
	if (!self || !player || self_index == player_index || self->quit_out_of_game ||
		player->quit_out_of_game || self->team_index < 0 || self->team_index > 1 ||
		player->team_index != self->team_index || player->local_player_index != NONE ||
		player->unit_index == NONE)
		return FALSE;
	unit = unit_try_and_get(player->unit_index);
	/* Vehicle-following cameras are outside the camera-only prototype. */
	return unit && !TEST_FLAG(unit->object.damage_flags, _object_dead_bit) &&
		unit->object.parent_object_index == NONE;
}

static long teammate_view_find_player(void)
{
	struct data_iterator iterator;
	if (!teammate_view_available())
		return NONE;
	if (teammate_view_valid_player(teammate_view_player_index))
		return teammate_view_player_index;
	data_iterator_new(&iterator, player_data);
	while (data_iterator_next(&iterator))
		if (teammate_view_valid_player(iterator.datum_index))
			return iterator.datum_index;
	return NONE;
}

long teammate_view_get_player_index(short window_index)
{
	return window_index == 1 && teammate_view_valid_player(teammate_view_player_index) ?
		teammate_view_player_index : NONE;
}

long teammate_view_get_first_person_unit_index(short window_index)
{
	long player_index = teammate_view_get_player_index(window_index);
	return player_index == NONE ? NONE : player_get(player_index)->unit_index;
}

short teammate_view_hud_player_count(void)
{
	/* Select retail split HUD assets for the extra display pane, while all
	 * ordinary/local modes retain their exact previous visual count. */
	return teammate_view_split_screen_active() ? 2 : local_player_count();
}

static void teammate_view_camera(long player_index, struct observer_result *observer)
{
	struct camera_command command;
	first_person_camera_fake(player_get(player_index)->unit_index, &command);
	memset(observer, 0, sizeof(*observer));
	observer->position = command.position;
	observer->forward = command.forward;
	observer->up = command.up;
	observer->velocity = command.velocity;
	observer->field_of_view = command.field_of_view;
}

void teammate_view_draw_label(short window_index)
{
	long player_index = teammate_view_get_player_index(window_index);
	rectangle2d bounds = render.camera.window_bounds;
	char text[64] = "TEAMMATE: ";
	short i;
	if (window_index != 1 || !teammate_view_split_screen_active() ||
		!hud_globals || hud_globals->messaging.single_player_font.index == NONE)
		return;
	/* Text bounds are relative to the current pane's viewport. */
	bounds.x0 -= render.camera.viewport_bounds.x0;
	bounds.x1 -= render.camera.viewport_bounds.x0;
	bounds.y0 -= render.camera.viewport_bounds.y0;
	bounds.y1 -= render.camera.viewport_bounds.y0;
	bounds.x0 += 8;
	bounds.y0 += 8;
	bounds.y1 = MIN(bounds.y1, bounds.y0 + 24);
	if (player_index == NONE)
	{
		strcpy(text, "TEAMMATE UNAVAILABLE");
	}
	else
	{
		for (i = 0; i < 11 && player_get(player_index)->name[i]; i++)
		{
			wchar_t c = player_get(player_index)->name[i];
			text[10 + i] = c >= 32 && c < 127 ? (char)c : '?';
		}
		text[10 + i] = 0;
	}
	rasterizer_hud_begin();
	draw_string_render_label(hud_globals->messaging.single_player_font.index, &bounds,
		global_real_argb_white, text);
	rasterizer_hud_end();
}
