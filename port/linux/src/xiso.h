/*
XISO.H

The maps folder out of an Xbox disc image (xiso.c).
*/

#ifndef __HALO_LINUX_XISO_H
#define __HALO_LINUX_XISO_H

/* called as the copy goes: the file being copied, and the bytes copied of
all the files' */
typedef void (*xiso_progress_proc)(void *context, const char *file, unsigned long long done,
	unsigned long long total);

/* Read-only validation of an Xbox disc image, maps/ui.map directory and
supported Xbox v5 NTSC/PAL UI cache header (2276/2342).
Returns nonzero when usable by the importer, or 0 with a player-facing reason.
This checks the image contents, rather than trusting its filename extension. */
int xiso_probe_maps(const char *image_path, char *error, int error_size);

/* copies the image's maps folder to <destination>/maps; returns nonzero on
success, or 0 with the reason (for the player) in error. Called from any
thread */
int xiso_extract_maps(const char *image_path, const char *destination, xiso_progress_proc progress, void *context,
	char *error, int error_size);

#endif
