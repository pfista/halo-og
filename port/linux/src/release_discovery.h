/* Halo OG release discovery, and the signed record that lets a desktop build
   install the release it finds. Without a valid record the download only opens
   in the browser. */
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

/* Signed install records live beside the maps: updates/<platform>/<tag>.txt
   and the same name with .sig, a raw 64-byte Ed25519 signature of the record. */
#define HALO_RELEASE_INSTALL_URL "https://dl.oghalo.com/updates/"
#define HALO_RELEASE_INSTALL_RECORD_BYTES 512u
#define HALO_RELEASE_INSTALL_MAXIMUM_BYTES (256ull * 1024ull * 1024ull)

/* What a signed record authorizes: this exact file of the discovered release. */
struct halo_release_install {
    char url[256];
    unsigned long long size;
    unsigned char sha256[32];
};

/* A release is installed only from a record signed by Halo OG's update key
   (halo_update_key.h). The record is "Halo OG update 1" and seven "name: value"
   lines, each ended by a newline: platform, tag, source, date, file, size and
   sha256. It must name the release, source commit, commit date and platform
   file that discovery selected, so a record for another release, an older
   build or another platform is refused. Nothing in the record is read before
   its signature is checked, and anything unexpected fails closed. */
int halo_release_install_parse(const void *record, size_t record_size,
    const void *signature, size_t signature_size, const unsigned char public_key[32],
    const char *asset, const struct halo_release_notice *notice, struct halo_release_install *install);

struct SDL_Window;
void halo_release_discovery_start(void);
void halo_release_discovery_poll(struct SDL_Window *window);
/* Called by the game at a safe main-menu boundary, never from a network match. */
void halo_release_discovery_set_main_menu(int safe);

#endif
