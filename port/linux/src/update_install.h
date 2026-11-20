/*
UPDATE_INSTALL.H

Putting a release's files in place of the running game's (update_install.c),
for the desktop updaters: Halo OG's (release_discovery.c) and the upstream one
(updater.c).
*/

#ifndef UPDATE_INSTALL_H
#define UPDATE_INSTALL_H

#include <stddef.h>

/* a release's zip of files for the game's folder */
struct update_install_request
{
	/* https://, redirects followed */
	const char *url;
	/* shown while it downloads: the release's name */
	const char *label;
	/* the zip's exact size and SHA-256 (32 bytes), which the download must
	match; a NULL sha256 skips the check, and size then only scales the
	progress bar */
	unsigned long long size;
	const unsigned char *sha256;
};

/* finds the running game's folder and removes what the update before this
start left there; 1 when this build can be updated in place */
int update_install_prepare(void);

/* downloads the zip, checks it, unpacks it and puts its files in place of the
game's, keeping each replaced file as <name>.old until the next start. If a
step fails the replaced files are put back and why is written to error.
1 when every new file is in place. Call it on the game's thread: it shows the
download's progress in a window of its own. */
int update_install(const struct update_install_request *request, char *error, size_t error_size);

/* starts the game again as a new process; 1 on success */
int update_install_relaunch(void);

#endif
