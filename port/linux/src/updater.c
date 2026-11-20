/*
UPDATER.C

The desktop ports' self-updater (Linux and Windows; the Android app updates
itself in Java, port/android).

A build of the main branch made by GitHub Actions knows its build number
(HALO_BUILD_NUMBER, the workflow's run number, which names its release:
build-<number>); other builds have none and never look for updates. When
update.auto in config.toml is true (the default), the game asks GitHub for
the latest release when it starts, on a thread of its own: the game starts
meanwhile, and nothing happens if the release is not newer or cannot be
reached. If it is newer, the game asks whether to update:

- Yes: the release's build for this platform and configuration
  (halo-<platform>-<release|debug>.zip) is put in place of the running game's
  files (update_install.c), and the new game started; this one quits.
- No: nothing, until the next start.
- Do not ask again: after the player confirms it, update.auto = false is
  written to config.toml.

The system side (the HTTPS download, the files, starting the new game) is
update.h's: posix_update.c on Linux, win32_update.c on Windows.
*/

#if HALO_OG_RELEASE_DISCOVERY && !defined(HALO_ANDROID)
#include "release_discovery.h"

/* Halo OG CI builds find releases through release discovery, which installs
   one only from a record signed by Halo OG's update key. The upstream updater
   below follows cybersecurity's build numbers and is not compiled into this path. */
void updater_start(void) { halo_release_discovery_start(); }
void updater_poll(struct SDL_Window *window) { halo_release_discovery_poll(window); }

#else
#include "platform.h"
#include "port_config.h"
#include "update.h"
#include "update_install.h"

#ifndef HALO_ANDROID

#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* (given for this file by the build: tools/linux_build.py, windows_build.py) */
#ifndef HALO_BUILD_NUMBER
#define HALO_BUILD_NUMBER 0
#endif

#ifndef HALO_BUILD_FLAVOR
#define HALO_BUILD_FLAVOR "release"
#endif

#define UPDATE_REPOSITORY "cybersecurity/halo-ce-universal"
#ifdef _WIN32
#define UPDATE_PLATFORM "windows"
#define PATH_SEPARATOR "\\"
#else
#define UPDATE_PLATFORM "linux"
#define PATH_SEPARATOR "/"
#endif
#define UPDATE_ASSET "halo-" UPDATE_PLATFORM "-" HALO_BUILD_FLAVOR ".zip"

enum
{
	_updater_idle,
	_updater_checking,
	_updater_available,
	_updater_handled,
};

static SDL_AtomicInt updater_state;
static long updater_latest_build;
static char updater_directory[1024];

/* ---------- paths */

static void updater_path(char *path, size_t size, const char *name)
{
	snprintf(path, size, "%s" PATH_SEPARATOR "%s", updater_directory, name);
}

/* ---------- checking */

/* the build number of GitHub's latest release, 0 if there is none */
static long updater_latest_release(void)
{
	char path[1200];
	char error[512] = "";
	size_t size = 0;
	char *text;
	const char *tag;
	long build = 0;

	updater_path(path, sizeof(path), "update-check.json");
	if (!update_download("https://api.github.com/repos/" UPDATE_REPOSITORY "/releases/latest", path, NULL, NULL,
		error, sizeof(error)))
	{
		platform_log("update: could not check for a new version: %s", error);
		return 0;
	}
	text = SDL_LoadFile(path, &size);
	update_delete_file(path);
	if (!text)
		return 0;
	/* "tag_name": "build-<number>" */
	tag = strstr(text, "\"tag_name\"");
	if (tag)
	{
		tag = strchr(tag + 10, '"');
		if (tag && !strncmp(tag, "\"build-", 7))
			build = strtol(tag + 7, NULL, 10);
	}
	SDL_free(text);
	return build;
}

static int SDLCALL updater_check_thread(void *context)
{
	long latest = updater_latest_release();

	(void)context;
	if (latest > HALO_BUILD_NUMBER)
	{
		platform_log("update: build %ld is available (this is build %d)", latest, HALO_BUILD_NUMBER);
		updater_latest_build = latest;
		SDL_SetAtomicInt(&updater_state, _updater_available);
	}
	else
	{
		if (latest)
			platform_log("update: this is the latest build (%d)", HALO_BUILD_NUMBER);
		SDL_SetAtomicInt(&updater_state, _updater_handled);
	}
	return 0;
}

/* ---------- updating */

/* downloads, unpacks and puts in place the new build, and starts it; returns
only if something failed */
static void updater_update(void)
{
	char url[512], label[64], error[512] = "";
	struct update_install_request request = { url, label, 0, NULL };

	snprintf(url, sizeof(url),
		"https://github.com/" UPDATE_REPOSITORY "/releases/download/build-%ld/" UPDATE_ASSET, updater_latest_build);
	snprintf(label, sizeof(label), "build %ld", updater_latest_build);
	platform_log("update: downloading build %ld (" UPDATE_ASSET ")", updater_latest_build);
	if (update_install(&request, error, sizeof(error)))
	{
		platform_log("update: starting build %ld", updater_latest_build);
		if (update_install_relaunch())
			exit(EXIT_SUCCESS);
		snprintf(error, sizeof(error), "the new version is in place, but could not be started: start it again");
	}
	platform_log("update: failed: %s", error);
	{
		char message[800];

		snprintf(message, sizeof(message), "The update failed:\n\n%s", error);
		SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Halo", message, NULL);
	}
}

/* ---------- the game's */

/* at start-up (sdl_platform.c): looks for a new version, in the background */
void updater_start(void)
{
	char *slash;

	if (!update_executable_path(updater_directory, sizeof(updater_directory)))
		return;
	slash = strrchr(updater_directory, PATH_SEPARATOR[0]);
	if (!slash)
		return;
	*slash = 0;
	/* (and what the update before this start left behind is removed) */
	if (!update_install_prepare())
		return;
	/* (not for builds without a number, the player's no, or runs nobody is
	watching, but for a test with its answer) */
	if (HALO_BUILD_NUMBER <= 0 || !config_boolean("update.auto") ||
		(!config_string("debug.update_answer")[0] && (config_boolean("debug.hidden_window") ||
			config_real("debug.exit_after") > 0.0 || config_string("debug.network_test")[0])))
	{
		return;
	}
	SDL_SetAtomicInt(&updater_state, _updater_checking);
	{
		SDL_Thread *thread = SDL_CreateThread(updater_check_thread, "update check", NULL);

		if (thread)
			SDL_DetachThread(thread);
		else
			SDL_SetAtomicInt(&updater_state, _updater_handled);
	}
}

/* every frame, on the game's thread (sdl_platform.c): asks the player once a
new version is found */
void updater_poll(SDL_Window *window)
{
	static const SDL_MessageBoxButtonData question_buttons[] =
	{
		{ SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT, 1, "Yes" },
		{ SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT, 0, "No" },
		{ 0, 2, "Do not ask again" },
	};
	static const SDL_MessageBoxButtonData confirm_buttons[] =
	{
		{ SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT, 1, "Yes" },
		{ SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT, 0, "No" },
	};
	char message[400];
	int answer = 0;
	int fullscreen;
	const char *test_answer = config_string("debug.update_answer");

	if (SDL_GetAtomicInt(&updater_state) != _updater_available)
		return;
	SDL_SetAtomicInt(&updater_state, _updater_handled);
	/* (an automated test's answer: debug.update_answer) */
	if (test_answer[0])
	{
		platform_log("update: answering %s (debug.update_answer)", test_answer);
		if (!strcmp(test_answer, "yes"))
			updater_update();
		else if (!strcmp(test_answer, "never"))
			config_write_boolean("update.auto", 0);
		return;
	}
	/* (a dialog cannot show above a fullscreen game) */
	fullscreen = window && (SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN);
	if (fullscreen)
		SDL_SetWindowFullscreen(window, false);
	snprintf(message, sizeof(message),
		"A new version of Halo was detected (build %ld; this is build %d).\n\n"
		"Do you want to update? The game will close and start the new version.",
		updater_latest_build, HALO_BUILD_NUMBER);
	{
		SDL_MessageBoxData question = { SDL_MESSAGEBOX_INFORMATION, window, "Halo: new version", message,
			3, question_buttons, NULL };

		if (!SDL_ShowMessageBox(&question, &answer))
			answer = 0;
	}
	if (answer == 2)
	{
		SDL_MessageBoxData confirm = { SDL_MESSAGEBOX_WARNING, window, "Halo: new version",
			"Stop asking about new versions?\n\n"
			"To ask again, set auto = true in the [update] section of config.toml.",
			2, confirm_buttons, NULL };
		int confirmed = 0;

		if (SDL_ShowMessageBox(&confirm, &confirmed) && confirmed == 1)
		{
			if (config_write_boolean("update.auto", 0))
				platform_log("update: update.auto = false written to config.toml");
			else
				platform_log("update: could not write update.auto to config.toml");
		}
	}
	else if (answer == 1)
	{
		updater_update();
	}
	if (fullscreen)
		SDL_SetWindowFullscreen(window, true);
}

#else

void updater_start(void)
{
}

#endif

#endif /* browser-only Halo OG discovery versus the upstream installer */
