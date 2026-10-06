/* Native-port extensions for compatible Xbox v5 multiplayer caches. */
#ifndef HALO_CUSTOM_MAPS_H
#define HALO_CUSTOM_MAPS_H

#define HALO_CUSTOM_MAP_LIMIT 128
#define HALO_CUSTOM_MAP_NAME_SIZE 32
/* -1 already means the tag's default string; -2 uses the widget's own text. */
#define HALO_CUSTOM_MAP_TEXT (-2)

char **native_multiplayer_map_list(char **stock, short stock_count, short *count);
int native_map_is_custom(char const *map);
char const *native_map_basename(char const *map);
int native_map_header_valid(unsigned char const *header, char const *filename);
/* User-supplied files take precedence over the read-only managed-map overlay. */
int native_map_get_path(char const *map, char *path, unsigned int capacity);
/* Resolve original geometry even if its name collides with a hidden identity. */
int native_map_get_original_path(char const *map, char *path, unsigned int capacity);
/* 2 while downloading, -1 on a visible download failure, 0 otherwise. */
int native_map_download_pending(char const *map);
#ifdef HALO_MACOS
/* Host imports; these only inspect/schedule work and never wait for network I/O. */
#ifdef __ILP32__
#define halo_map_download_directory host_halo_map_download_directory
#define halo_map_download_request host_halo_map_download_request
#define halo_arsenal_download_request host_halo_arsenal_download_request
#endif
int halo_map_download_directory(char *path, unsigned long capacity);
int halo_map_download_request(char const *map);
#endif
/* Nonblocking host service; expected digest empty/NULL means latest compatible.
   -1 failed, 0 unavailable, 1 installed, 2 queued/downloading. */
int halo_arsenal_download_request(char const *logical_map, char const *base_sha256_hex,
    char const *cache_sha256_hex);

#endif
