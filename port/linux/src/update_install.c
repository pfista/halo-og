/*
UPDATE_INSTALL.C

Puts a release's files in place of the running game's (Linux and Windows).
The zip is downloaded into update.partial/ beside the executable, checked,
unpacked there, and its files moved over the game's one at a time. A file that
is replaced is first renamed <name>.old, because a running executable can be
renamed but not overwritten. If any file cannot be replaced, the ones already
replaced are moved back, so the folder never holds a mix of two versions.

The previous files stay as <name>.old until the new version next starts, which
removes them: if the new version cannot start, they are how to go back.

The system side (the HTTPS download, the files, starting the new game) is
update.h's: posix_update.c on Linux, win32_update.c on Windows.
*/

#if !defined(HALO_ANDROID) && !defined(HALO_MACOS) && !defined(HALO_IOS)

#include "update_install.h"
#include "update.h"
#include "../include/halo_sha256.h"

#include "memory/zlib/zlib.h"

#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define PATH_SEPARATOR "\\"
#else
#define PATH_SEPARATOR "/"
#endif
#define UPDATE_DIRECTORY "update.partial"
#define UPDATE_ZIP "update.zip"
/* the names of the files the last update replaced, one to a line */
#define UPDATE_REPLACED "update-replaced.txt"
#define MAXIMUM_UPDATE_FILES 32

static char install_directory[1024];
static char install_executable[1024];

/* ---------- paths */

static void install_path(char *path, size_t size, const char *name)
{
	snprintf(path, size, "%s" PATH_SEPARATOR "%s", install_directory, name);
}

static void install_partial_path(char *path, size_t size, const char *name)
{
	snprintf(path, size, "%s" PATH_SEPARATOR UPDATE_DIRECTORY PATH_SEPARATOR "%s", install_directory, name);
}

/* a name from a zip or from the list of replaced files: one file in the
game's folder, never a path */
static int install_name_is_flat(const char *name)
{
	size_t length = strlen(name);

	return length && length < 200 && !strchr(name, '/') && !strchr(name, '\\') && !strchr(name, ':') &&
		strcmp(name, "..") && strcmp(name, ".");
}

/* ---------- the zip file (the release's), stored or deflated entries */

static unsigned long zip_word(const unsigned char *bytes)
{
	return (unsigned long)bytes[0] | (unsigned long)bytes[1] << 8;
}

static unsigned long zip_long(const unsigned char *bytes)
{
	return zip_word(bytes) | zip_word(bytes + 2) << 16;
}

/* an entry's data, unpacked, to the file at path; why it could not be is
written to reason */
static int zip_extract_entry(SDL_IOStream *zip, unsigned long local_offset, int method,
	unsigned long packed_size, unsigned long size, unsigned long crc, const char *path,
	char *reason, size_t reason_size)
{
	unsigned char header[30];
	unsigned char input[16384], output[16384];
	SDL_IOStream *file;
	z_stream stream;
	unsigned long remaining = packed_size, written = 0, checksum = crc32(0L, Z_NULL, 0);
	int succeeded = 0, ended = 0;

	if (SDL_SeekIO(zip, (Sint64)local_offset, SDL_IO_SEEK_SET) < 0 ||
		SDL_ReadIO(zip, header, sizeof(header)) != sizeof(header) || zip_long(header) != 0x04034b50 ||
		SDL_SeekIO(zip, (Sint64)(zip_word(header + 26) + zip_word(header + 28)), SDL_IO_SEEK_CUR) < 0)
	{
		snprintf(reason, reason_size, "its header at %lu could not be read (%s)", local_offset, SDL_GetError());
		return 0;
	}
	file = SDL_IOFromFile(path, "wb");
	if (!file)
	{
		snprintf(reason, reason_size, "could not create %s (%s)", path, SDL_GetError());
		return 0;
	}
	memset(&stream, 0, sizeof(stream));
	if (method == 8 && inflateInit2(&stream, -MAX_WBITS) != Z_OK)
	{
		snprintf(reason, reason_size, "zlib would not start (%s)", stream.msg ? stream.msg : "no message");
		SDL_CloseIO(file);
		return 0;
	}
	for (;;)
	{
		size_t count = remaining < sizeof(input) ? remaining : sizeof(input);

		if (count && SDL_ReadIO(zip, input, count) != count)
		{
			snprintf(reason, reason_size, "the download ended %lu bytes early (%s)", remaining, SDL_GetError());
			break;
		}
		remaining -= (unsigned long)count;
		if (method == 0)
		{
			if (SDL_WriteIO(file, input, count) != count)
			{
				snprintf(reason, reason_size, "could not write %s after %lu bytes (%s)", path, written, SDL_GetError());
				break;
			}
			checksum = crc32(checksum, input, (uInt)count);
			written += (unsigned long)count;
		}
		else
		{
			int result = Z_OK;

			stream.next_in = input;
			stream.avail_in = (uInt)count;
			do
			{
				size_t produced;

				stream.next_out = output;
				stream.avail_out = sizeof(output);
				result = inflate(&stream, Z_NO_FLUSH);
				if (result != Z_OK && result != Z_STREAM_END)
					break;
				produced = sizeof(output) - stream.avail_out;
				if (SDL_WriteIO(file, output, produced) != produced)
				{
					snprintf(reason, reason_size, "could not write %s after %lu bytes (%s)", path, written, SDL_GetError());
					result = Z_ERRNO;
					break;
				}
				checksum = crc32(checksum, output, (uInt)produced);
				written += (unsigned long)produced;
			} while (stream.avail_out == 0 && result != Z_STREAM_END);
			if (result == Z_STREAM_END)
				ended = 1;
			else if (result != Z_OK && result != Z_BUF_ERROR)
			{
				if (result != Z_ERRNO)
				{
					snprintf(reason, reason_size, "zlib stopped with %d after %lu of %lu bytes (%s)", result, written, size,
						stream.msg ? stream.msg : "no message");
				}
				break;
			}
		}
		/* (the game's zlib is 1.1, which can want a byte past the end of a
		raw stream before it says the stream has ended: all of the input
		unpacked is enough, as the size and the CRC are checked) */
		if (ended || !remaining)
		{
			if (written != size)
				snprintf(reason, reason_size, "it unpacked to %lu bytes, not %lu", written, size);
			else if (checksum != crc)
				snprintf(reason, reason_size, "its CRC is %08lx, not %08lx", checksum, crc);
			else
				succeeded = 1;
			break;
		}
	}
	if (method == 8)
		inflateEnd(&stream);
	if (!SDL_CloseIO(file) && succeeded)
	{
		snprintf(reason, reason_size, "could not finish writing %s (%s)", path, SDL_GetError());
		succeeded = 0;
	}
	return succeeded;
}

/* the zip's files (a flat folder) into update.partial/, their names in names */
static int zip_extract(const char *zip_path, char names[][256], int *name_count, char *error, size_t error_size)
{
	SDL_IOStream *zip = SDL_IOFromFile(zip_path, "rb");
	unsigned char tail[65536 + 22];
	Sint64 size;
	size_t tail_size, index;
	unsigned long entries = 0, directory_offset = 0, entry;
	int found = 0, succeeded = 0;

	*name_count = 0;
	if (!zip)
	{
		snprintf(error, error_size, "could not open the download");
		return 0;
	}
	/* the end of the central directory, in the last 64 KB */
	size = SDL_GetIOSize(zip);
	tail_size = size < (Sint64)sizeof(tail) ? (size_t)size : sizeof(tail);
	if (size < 22 || SDL_SeekIO(zip, size - (Sint64)tail_size, SDL_IO_SEEK_SET) < 0 ||
		SDL_ReadIO(zip, tail, tail_size) != tail_size)
	{
		goto done;
	}
	for (index = tail_size - 22 + 1; index-- > 0;)
	{
		if (zip_long(tail + index) == 0x06054b50)
		{
			entries = zip_word(tail + index + 10);
			directory_offset = zip_long(tail + index + 16);
			found = 1;
			break;
		}
	}
	if (!found || SDL_SeekIO(zip, (Sint64)directory_offset, SDL_IO_SEEK_SET) < 0)
		goto done;
	for (entry = 0; entry < entries; entry++)
	{
		unsigned char header[46];
		char name[256];
		unsigned long name_length, extra_length, comment_length;
		Sint64 next;
		char path[1200];
		char reason[512] = "";

		if (SDL_ReadIO(zip, header, sizeof(header)) != sizeof(header) || zip_long(header) != 0x02014b50)
			goto done;
		name_length = zip_word(header + 28);
		extra_length = zip_word(header + 30);
		comment_length = zip_word(header + 32);
		if (name_length >= sizeof(name) || SDL_ReadIO(zip, name, name_length) != name_length)
			goto done;
		name[name_length] = 0;
		next = SDL_TellIO(zip) + (Sint64)(extra_length + comment_length);
		/* (a folder, or a name that would leave the game's folder, is left
		out: the release's files are all at its top) */
		if (name_length && name[name_length - 1] != '/' && !strchr(name, '/') && !strchr(name, '\\') &&
			strcmp(name, "..") && strcmp(name, ".") && strcmp(name, "config.toml") &&
			*name_count < MAXIMUM_UPDATE_FILES)
		{
			int method = (int)zip_word(header + 10);

			if (method != 0 && method != 8)
			{
				snprintf(error, error_size, "the download packs %s in a way this build cannot read", name);
				goto done;
			}
			install_partial_path(path, sizeof(path), name);
			if (!zip_extract_entry(zip, zip_long(header + 42), method, zip_long(header + 20), zip_long(header + 24),
				zip_long(header + 16), path, reason, sizeof(reason)))
			{
				snprintf(error, error_size, "could not unpack %s: %s", name, reason);
				update_delete_file(path);
				goto done;
			}
			snprintf(names[*name_count], 256, "%s", name);
			(*name_count)++;
		}
		if (SDL_SeekIO(zip, next, SDL_IO_SEEK_SET) < 0)
			goto done;
	}
	succeeded = *name_count > 0;

done:
	if (!succeeded && !error[0])
		snprintf(error, error_size, "the download is not a zip file this build can read");
	SDL_CloseIO(zip);
	return succeeded;
}

/* ---------- the download, with a window of its own showing how far it is */

struct install_download
{
	SDL_Mutex *lock;
	const char *url;
	char zip_path[1200];
	unsigned long long received, total;
	int finished, succeeded;
	char error[512];
};

static void install_download_progress(void *context, unsigned long long received, unsigned long long total)
{
	struct install_download *download = context;

	SDL_LockMutex(download->lock);
	download->received = received;
	download->total = total;
	SDL_UnlockMutex(download->lock);
}

static int SDLCALL install_download_thread(void *context)
{
	struct install_download *download = context;
	char error[512] = "";
	int succeeded = update_download(download->url, download->zip_path, install_download_progress, download, error,
		sizeof(error));

	SDL_LockMutex(download->lock);
	download->succeeded = succeeded;
	snprintf(download->error, sizeof(download->error), "%s", error);
	download->finished = 1;
	SDL_UnlockMutex(download->lock);
	return 0;
}

/* (drawn in software, clear of the game's renderer; the game's own events
wait, as its window is not drawn meanwhile) */
static int install_download(const struct update_install_request *request, const char *zip_path, char *error,
	size_t error_size)
{
	static struct install_download download;
	SDL_Window *window;
	SDL_Renderer *renderer = NULL;
	SDL_Thread *thread;
	int finished = 0;

	memset(&download, 0, sizeof(download));
	download.lock = SDL_CreateMutex();
	download.url = request->url;
	snprintf(download.zip_path, sizeof(download.zip_path), "%s", zip_path);
	thread = SDL_CreateThread(install_download_thread, "update download", &download);
	if (!thread)
	{
		SDL_DestroyMutex(download.lock);
		snprintf(error, error_size, "could not start the download");
		return 0;
	}
	window = SDL_CreateWindow("Halo OG", 640, 150, 0);
	if (window)
		renderer = SDL_CreateRenderer(window, SDL_SOFTWARE_RENDERER);
	while (!finished)
	{
		SDL_Event event;
		unsigned long long received, total;

		while (SDL_PollEvent(&event))
		{
		}
		SDL_LockMutex(download.lock);
		finished = download.finished;
		received = download.received;
		total = download.total ? download.total : request->size;
		SDL_UnlockMutex(download.lock);
		if (renderer)
		{
			char line[160];
			SDL_FRect bar = { 20.0f, 100.0f, 600.0f, 24.0f };
			float fraction = total ? (float)((double)received / (double)total) : 0.0f;

			SDL_SetRenderDrawColor(renderer, 12, 16, 20, 255);
			SDL_RenderClear(renderer);
			SDL_SetRenderDrawColor(renderer, 230, 230, 230, 255);
			SDL_SetRenderScale(renderer, 2.0f, 2.0f);
			SDL_RenderDebugText(renderer, 10.0f, 10.0f, "Downloading the new version...");
			SDL_SetRenderScale(renderer, 1.0f, 1.0f);
			snprintf(line, sizeof(line), "%s  (%llu of %llu MB)", request->label ? request->label : "", received >> 20,
				total >> 20);
			SDL_RenderDebugText(renderer, 20.0f, 70.0f, line);
			SDL_SetRenderDrawColor(renderer, 60, 66, 72, 255);
			SDL_RenderFillRect(renderer, &bar);
			bar.w *= fraction > 1.0f ? 1.0f : fraction;
			SDL_SetRenderDrawColor(renderer, 90, 160, 90, 255);
			SDL_RenderFillRect(renderer, &bar);
			SDL_RenderPresent(renderer);
		}
		SDL_Delay(16);
	}
	SDL_WaitThread(thread, NULL);
	if (renderer)
		SDL_DestroyRenderer(renderer);
	if (window)
		SDL_DestroyWindow(window);
	SDL_DestroyMutex(download.lock);
	if (!download.succeeded)
		snprintf(error, error_size, "%s", download.error);
	return download.succeeded;
}

/* whether the downloaded file is the one the release's signed record names:
its exact size and SHA-256 */
static int install_download_matches(const char *zip_path, unsigned long long size, const unsigned char *sha256,
	char *error, size_t error_size)
{
	SDL_IOStream *file = SDL_IOFromFile(zip_path, "rb");
	static unsigned char buffer[65536];
	unsigned char digest[32];
	struct sha256 hash;
	unsigned long long total = 0;
	size_t count;

	if (!file)
	{
		snprintf(error, error_size, "could not open the download");
		return 0;
	}
	sha256_begin(&hash);
	while ((count = SDL_ReadIO(file, buffer, sizeof(buffer))) > 0)
	{
		sha256_add(&hash, buffer, (int)count);
		total += count;
	}
	SDL_CloseIO(file);
	sha256_end(&hash, digest);
	if (total != size || memcmp(digest, sha256, sizeof(digest)))
	{
		snprintf(error, error_size, "the download is not the file this release was published with");
		return 0;
	}
	return 1;
}

/* ---------- the files */

/* undoes putting a new file in place: the previous file back, or, where there
was none, the new file removed */
static void install_restore(const char *name, int existed)
{
	char path[1200], old_path[1300], failed_path[1300];

	install_path(path, sizeof(path), name);
	if (!existed)
	{
		update_delete_file(path);
		return;
	}
	snprintf(old_path, sizeof(old_path), "%s.old", path);
	snprintf(failed_path, sizeof(failed_path), "%s.failed", path);
	if (update_replace_file(path, old_path, failed_path))
		update_delete_file(failed_path);
}

/* the names of the files just replaced, for the next start to remove their
.old copies */
static void install_write_replaced(char names[][256], int name_count)
{
	char path[1200];
	SDL_IOStream *file;
	int index;

	install_path(path, sizeof(path), UPDATE_REPLACED);
	file = SDL_IOFromFile(path, "wb");
	if (!file)
		return;
	for (index = 0; index < name_count; index++)
	{
		SDL_WriteIO(file, names[index], strlen(names[index]));
		SDL_WriteIO(file, "\n", 1);
	}
	SDL_CloseIO(file);
}

/* what the update before this start left behind: the previous version's
files, which this start shows are no longer needed, and an unfinished
download */
static void install_clean_up(void)
{
	char path[1200], old_path[1300];
	size_t size = 0;
	char *text, *name, *end;

	install_path(path, sizeof(path), UPDATE_REPLACED);
	text = SDL_LoadFile(path, &size);
	if (text)
	{
		for (name = text; *name; name = end)
		{
			end = name + strcspn(name, "\r\n");
			if (*end)
				*end++ = 0;
			if (install_name_is_flat(name))
			{
				install_path(old_path, sizeof(old_path), name);
				snprintf(old_path + strlen(old_path), sizeof(old_path) - strlen(old_path), ".old");
				update_delete_file(old_path);
			}
		}
		SDL_free(text);
		update_delete_file(path);
	}
	install_partial_path(path, sizeof(path), UPDATE_ZIP);
	update_delete_file(path);
	install_path(path, sizeof(path), UPDATE_DIRECTORY);
	update_delete_file(path);
}

/* ---------- update_install.h */

int update_install_prepare(void)
{
	char *slash;

	if (install_executable[0])
		return 1;
	if (!update_executable_path(install_executable, sizeof(install_executable)))
		return 0;
	snprintf(install_directory, sizeof(install_directory), "%s", install_executable);
	slash = strrchr(install_directory, PATH_SEPARATOR[0]);
	if (!slash)
	{
		install_executable[0] = 0;
		return 0;
	}
	*slash = 0;
	install_clean_up();
	return 1;
}

int update_install(const struct update_install_request *request, char *error, size_t error_size)
{
	static char names[MAXIMUM_UPDATE_FILES][256];
	int existed[MAXIMUM_UPDATE_FILES];
	char zip_path[1200], partial[1200], path[1200], new_path[1200], old_path[1300];
	int name_count = 0, placed = 0, index;

	error[0] = 0;
	if (!update_install_prepare())
	{
		snprintf(error, error_size, "could not find the game's folder");
		return 0;
	}
	install_path(partial, sizeof(partial), UPDATE_DIRECTORY);
	install_partial_path(zip_path, sizeof(zip_path), UPDATE_ZIP);
	if (!update_make_directory(partial))
	{
		snprintf(error, error_size, "could not make %s (is the game's folder read-only?)", partial);
		return 0;
	}
	if (install_download(request, zip_path, error, error_size) &&
		(!request->sha256 || install_download_matches(zip_path, request->size, request->sha256, error, error_size)) &&
		zip_extract(zip_path, names, &name_count, error, error_size))
	{
		/* the new files in place of the old ones */
		for (placed = 0; placed < name_count; placed++)
		{
			install_path(path, sizeof(path), names[placed]);
			install_partial_path(new_path, sizeof(new_path), names[placed]);
			snprintf(old_path, sizeof(old_path), "%s.old", path);
			existed[placed] = SDL_GetPathInfo(path, NULL);
			if (!update_replace_file(path, new_path, old_path))
			{
				snprintf(error, error_size, "could not replace %s", path);
				break;
			}
		}
		if (placed == name_count)
		{
			install_write_replaced(names, name_count);
			update_delete_file(zip_path);
			update_delete_file(partial);
			return 1;
		}
		/* one version or the other, never a mix: the previous files back,
		the last replaced first */
		while (placed-- > 0)
			install_restore(names[placed], existed[placed]);
	}
	for (index = 0; index < name_count; index++)
	{
		install_partial_path(new_path, sizeof(new_path), names[index]);
		update_delete_file(new_path);
	}
	update_delete_file(zip_path);
	update_delete_file(partial);
	return 0;
}

int update_install_relaunch(void)
{
	return install_executable[0] && update_launch(install_executable);
}

#endif
