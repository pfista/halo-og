#ifndef HALO_COMMUNITY_PACKAGES_H
#define HALO_COMMUNITY_PACKAGES_H
#include <stddef.h>

/* Host ABI only. Packages are data; only the two fixed, locally packaged
   Invader helpers authenticated by ContentTools.json may execute. */
struct community_package_info {
    char id[32], map_sha256[65];
    /* package_bytes is the received outer file length, including .mapog. */
    unsigned long long package_bytes, map_bytes, declared_bytes, tag_bytes;
};
typedef void (*community_package_progress)(void *context, const char *message);
int community_package_inspect(const char *package, struct community_package_info *info,
                              char *error, size_t error_size);
/* Returns 0 after exclusive publication, 1 for an existing exact output, and
   -1 on failure. Never replaces stock inputs or a different destination. */
int community_package_reconstruct(const char *package, const char *stock_maps,
    const char *tools_directory, const char *tools_record, const char *work_parent,
    const char *destination, community_package_progress progress, void *context,
    char *error, size_t error_size);
#endif
