/* Guest calls use the host-prefixed ABI so the ILP32 compiler rebases every
 * pointer before entering native code. Keep native service names available
 * to native callers and fixtures. */
#include "../../linux/src/game_directory.h"
#include "../native/HaloMapDownloads.h"

int host_halo_map_download_directory(char *out, size_t capacity)
{
#ifdef HALO_IOS
    return HALO_MAP_DOWNLOAD_UNAVAILABLE;
#else
    return halo_map_download_directory(out, capacity);
#endif
}

int host_halo_map_download_request(const char *map_name)
{
#ifdef HALO_IOS
    return HALO_MAP_DOWNLOAD_UNAVAILABLE;
#else
    return halo_map_download_request(map_name);
#endif
}

int host_halo_arsenal_download_request(const char *logical_map,
    const char *base_sha256_hex, const char *cache_sha256_hex)
{
#ifdef HALO_IOS
    return HALO_MAP_DOWNLOAD_UNAVAILABLE;
#else
    return halo_arsenal_download_request(logical_map, base_sha256_hex, cache_sha256_hex);
#endif
}

/* The iPhone shares the Mac's NSURLSession client. iOS blocks System Link
 * broadcasts without Apple's multicast entitlement, so the public directory
 * is how a phone finds games hosted elsewhere on the LAN or the Internet. */
int host_halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status, int *retry_after_seconds)
{
    return halo_directory_http(method, url, lease, body, response, capacity, status, retry_after_seconds);
}
