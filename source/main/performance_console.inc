/* Native PB controls run before HaloScript, so joining clients can inspect
 * their host's settings without gaining script or mutation authority. */
static boolean performance_console_word(char const **text, char *word, unsigned capacity)
{
	unsigned length = 0;
	while (**text == ' ' || **text == '\t') ++*text;
	while (**text && **text != ' ' && **text != '\t')
	{
		if (length + 1 >= capacity) return FALSE;
		word[length++] = *(*text)++;
	}
	word[length] = 0;
	return TRUE;
}

static void performance_console_status(void)
{
	static char const *const sound_modes[] = {"NORMAL", "JUST ME", "SILENT"};
	unsigned long flags = performance_options_get_flags();
	struct performance_sound_statistics sound_statistics;
	struct performance_timer_statistics timer_statistics;
	/* Preserve this diagnostic line for smoke-test clients. */
	console_printf(FALSE, "performance options: flags=%lu ticks=%ld markers=%d/%d",
		flags, performance_options_timer_ticks(),
		performance_options_markers_visible_count(), performance_options_markers_supported_count());
	console_printf(FALSE, "PB: timer %s | spawn markers %s | timer audio %s",
		(flags & _performance_option_match_timer) ? "ON" : "OFF",
		(flags & _performance_option_spawn_markers) ? "ON" : "OFF",
		(flags & _performance_option_timer_audio) ? "ON" : "OFF");
	console_printf(FALSE, "PB: movement sounds %s | weapon sounds %s",
		sound_modes[performance_variant_sound_mode(flags,
			_performance_option_silent_movement, _performance_option_self_movement)],
		sound_modes[performance_variant_sound_mode(flags,
			_performance_option_silent_weapon_ready, _performance_option_self_weapon_ready)]);
	console_printf(FALSE, "Precision Spread: %s (selected before the match)",
        (flags & _performance_option_hardcore) ? "ON" : "OFF");
	console_printf(FALSE, "Camo: %s (selected before the match)",
        (flags & _performance_option_hardcore_camo) ? "STRONGER" : "NORMAL");
	console_printf(FALSE, "timer recordings: %s", halo_performance_audio_available() ? "installed" : "missing");
	performance_options_timer_statistics(&timer_statistics);
	console_printf(FALSE, "PB timer: prefs=%u countdown=%lu beeps=%lu minutes=%lu items=%lu last=%s",
		timer_statistics.preferences, timer_statistics.countdown, timer_statistics.beeps,
		timer_statistics.minutes, timer_statistics.items, timer_statistics.last_cue);
	console_printf(FALSE, "PB timer items: rocket=%lu camo=%lu overshield=%lu",
		timer_statistics.items_by_category[0], timer_statistics.items_by_category[1], timer_statistics.items_by_category[2]);
	performance_sound_get_statistics(&sound_statistics);
	console_printf(FALSE, "PB sound voices: normal=%lu movement=%lu ready=%lu | muted: movement=%lu ready=%lu",
		sound_statistics.voices_by_role[0], sound_statistics.voices_by_role[1], sound_statistics.voices_by_role[2],
		sound_statistics.muted_dispatches_by_role[1], sound_statistics.muted_dispatches_by_role[2]);
	console_printf(FALSE, "PB sound effects=%lu particles=%lu last_voice=%lx last_tag=%lx last_role=%u",
		sound_statistics.tagged_effects, sound_statistics.tagged_particles,
		sound_statistics.last_voice_index, sound_statistics.last_definition_index, sound_statistics.last_voice_role);
}

static void performance_console_help(void)
{
	console_printf(FALSE, "PB controls: pb default | pb practice | pb pro | pb status");
	console_printf(FALSE, "pb timer|markers|audio on|off|toggle");
	console_printf(FALSE, "pb movement|weapons normal|self|silent|toggle (self = Just Me)");
	console_printf(FALSE, "Host changes apply to this session; guests can view settings.");
	console_printf(FALSE, "Presets here change aids only; select Pro match rules before play.");
}

boolean console_process_native_command(char const *command)
{
	char name[32], option[24], value[24], extra[2];
	unsigned long flags, bit = 0, self_bit = 0;
	boolean numeric;
	char const *text = command;
	if (!performance_console_word(&text, name, sizeof(name))) return FALSE;
	numeric = !strcmp(name, "performance_options");
	if (!numeric && strcmp(name, "pb")) return FALSE;
	if (!performance_console_word(&text, option, sizeof(option)) ||
		!performance_console_word(&text, value, sizeof(value)) ||
		!performance_console_word(&text, extra, sizeof(extra)) || *extra)
		goto usage;
	if (!*option || (!numeric && (!strcmp(option, "status") || !strcmp(option, "help"))))
	{
		if (*value) goto usage;
		performance_console_status();
		if (!numeric && strcmp(option, "status")) performance_console_help();
		return TRUE;
	}
	flags = performance_options_get_flags();
	if (numeric)
	{
		unsigned index;
		if (*value) goto usage;
		flags = 0;
		for (index = 0; option[index]; index++)
		{
			if (option[index] < '0' || option[index] > '9') goto usage;
			flags = flags * 10 + (unsigned long)(option[index] - '0');
			if (flags > PERFORMANCE_OPTIONS_MASK) goto usage;
		}
		if (!performance_variant_flags_valid((unsigned)flags)) goto usage;
	}
	else if (!strcmp(option, "default") || !strcmp(option, "stock") ||
		!strcmp(option, "practice") || !strcmp(option, "pro"))
	{
		if (*value) goto usage;
		flags = (flags & PERFORMANCE_MATCH_RULE_FLAGS) |
			(!strcmp(option, "pro") ? PERFORMANCE_PRO_FLAGS & ~PERFORMANCE_MATCH_RULE_FLAGS :
			 !strcmp(option, "practice") ? PERFORMANCE_PRACTICE_FLAGS : 0);
	}
	else
	{
		if (!strcmp(option, "timer")) bit = _performance_option_match_timer;
		else if (!strcmp(option, "markers")) bit = _performance_option_spawn_markers;
		else if (!strcmp(option, "audio")) bit = _performance_option_timer_audio;
		else if (!strcmp(option, "movement"))
		{
			bit = _performance_option_silent_movement;
			self_bit = _performance_option_self_movement;
		}
		else if (!strcmp(option, "weapons"))
		{
			bit = _performance_option_silent_weapon_ready;
			self_bit = _performance_option_self_weapon_ready;
		}
		else goto usage;
		if (!*value)
		{
			performance_console_status();
			return TRUE;
		}
		if (self_bit)
		{
			short mode = performance_variant_sound_mode(flags, (unsigned)bit, (unsigned)self_bit);
			if (!strcmp(value, "normal")) mode = _performance_sound_mode_normal;
			else if (!strcmp(value, "self")) mode = _performance_sound_mode_self;
			else if (!strcmp(value, "silent")) mode = _performance_sound_mode_silent;
			else if (!strcmp(value, "toggle")) mode = (short)((mode + 1) % 3);
			else goto usage;
			flags = (flags & ~(bit | self_bit)) |
				performance_variant_sound_flags(mode, (unsigned)bit, (unsigned)self_bit);
		}
		else if (!strcmp(value, "on")) flags |= bit;
		else if (!strcmp(value, "off")) flags &= ~bit;
		else if (!strcmp(value, "toggle")) flags ^= bit;
		else goto usage;
	}
	if (!performance_options_set_host_flags(flags))
	{
		if (playlist_profile_variant_is_locked(game_engine_get_variant()))
		{
			console_printf(FALSE, "Team Slayer Pro is locked. Choose another game type to change the rules.");
			return TRUE;
		}
		console_printf(FALSE, "performance options change refused: host and compatible peers required");
		if ((flags & _performance_option_timer_audio) && !halo_performance_audio_available())
			console_printf(FALSE, "Timer recordings are missing. Install the complete timer pack and restart Halo, or use pb audio off.");
		return TRUE;
	}
	performance_console_status();
	return TRUE;
usage:
	if (numeric)
		console_printf(FALSE, "usage: performance_options [flags, mask=%d] (timer=1, markers=2, audio=4, silent movement=8, silent weapons=16, input delay=32, precision spread=64, Fiesta=128, stronger camo=256, self movement=4096, self weapons=8192; choose one sound mode per role)", PERFORMANCE_OPTIONS_MASK);
	else performance_console_help();
	return TRUE;
}

/* Complete the existing F2 console controls, including option values. Return
 * NONE outside a PB command so normal HaloScript completion is preserved. */
static short performance_console_complete(char *input, char **token, char **matches, short capacity,
	boolean *native_only)
{
	static char *commands[] = {"pb", "performance_options"};
	static char *options[] = {"default", "practice", "pro", "stock", "status", "help", "timer", "markers", "audio", "movement", "weapons"};
	static char *values[] = {"on", "off", "toggle"};
	static char *sound_values[] = {"normal", "self", "silent", "toggle"};
	static char *numbers[] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
		"10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23",
		"24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37",
		"38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "48", "49", "50", "51",
		"52", "53", "54", "55", "56", "57", "58", "59", "60", "61", "62", "63"};
	char **choices = commands;
	short choice_count = NUMBEROF(commands), count = 0, index;
	char *start = input, *end;
	unsigned length;
	*native_only = FALSE;
	while (*start == ' ' || *start == '\t') start++;
	end = start;
	while (*end && *end != ' ' && *end != '\t') end++;
	if (*end)
	{
		boolean numeric = end - start == 19 && !strncmp(start, "performance_options", 19);
		if (!numeric && !(end - start == 2 && !strncmp(start, "pb", 2))) return NONE;
		*native_only = TRUE;
		start = end;
		while (*start == ' ' || *start == '\t') start++;
		choices = numeric ? numbers : options;
		choice_count = numeric ? NUMBEROF(numbers) : NUMBEROF(options);
		end = start;
		while (*end && *end != ' ' && *end != '\t') end++;
		if (*end)
		{
			boolean sound_option = (end - start == 8 && !strncmp(start, "movement", 8)) ||
				(end - start == 7 && !strncmp(start, "weapons", 7));
			if (numeric || !((end - start == 5 && (!strncmp(start, "timer", 5) || !strncmp(start, "audio", 5))) ||
				(end - start == 7 && !strncmp(start, "markers", 7)) || sound_option)) return 0;
			start = end;
			while (*start == ' ' || *start == '\t') start++;
			choices = sound_option ? sound_values : values;
			choice_count = sound_option ? NUMBEROF(sound_values) : NUMBEROF(values);
		}
	}
	*token = start;
	length = strlen(start);
	for (index = 0; index < choice_count && count < capacity; index++)
		if (!strncmp(choices[index], start, length)) matches[count++] = choices[index];
	/* A bare first token is also eligible for normal HaloScript completion. */
	return choices == commands && !count ? NONE : count;
}
