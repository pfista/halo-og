#ifndef HALO_COMMUNITY_MAPS_DOWNLOAD_H
#define HALO_COMMUNITY_MAPS_DOWNLOAD_H

/* Desktop Windows/Linux only. Starts one background, bounded full-map
   prefetch into the active maps directory. No guest map-list mutation. */
void community_maps_download_start(void);

/* On-demand expanded weapon cache. The caller supplies the original-map
   SHA-256 and, when joining, the host's exact cache SHA-256 (NULL for a host).
   Returns -1 failed, 0 unavailable, 1 installed, or 2 pending. Never blocks
   the game thread on filesystem hashing or HTTPS. */
int halo_arsenal_download_request(const char *logical_map,
    const char *base_sha256_hex, const char *cache_sha256_hex);

#endif
