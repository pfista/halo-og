/* Browser-only update discovery. No executable files are downloaded or replaced. */
#ifndef HALO_RELEASE_DISCOVERY_H
#define HALO_RELEASE_DISCOVERY_H

#include <stddef.h>

#define HALO_RELEASE_DISCOVERY_URL "https://api.github.com/repos/pfista/halo-og/releases?per_page=5"
#define HALO_RELEASE_DISCOVERY_BYTES (256u * 1024u)

struct halo_release_notice {
    char tag[96];
    char source_sha[41];
    char source_date[21];
    char published_at[21];
    char download_url[256];
};

/* Select a newer, complete Halo OG release. GitHub's created_at records the
   release's source commit time; publication time does not establish code age.
   Tags are labels, never compared as versions. Malformed metadata fails closed. */
int halo_release_discovery_parse(const void *data, size_t size, const char *asset,
    const char *current_sha, const char *current_date, struct halo_release_notice *notice);

struct SDL_Window;
void halo_release_discovery_start(void);
void halo_release_discovery_poll(struct SDL_Window *window);
/* Called by the game at a safe main-menu boundary, never from a network match. */
void halo_release_discovery_set_main_menu(int safe);

#endif
