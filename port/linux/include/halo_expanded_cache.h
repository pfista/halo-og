/* Hidden full-arsenal caches retain the selected map's logical identity. */
#ifndef HALO_EXPANDED_CACHE_H
#define HALO_EXPANDED_CACHE_H

#define HALO_EXPANDED_CACHE_GENERATION 1
#define HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256 "2856504cbd257e1b18c273caa64237fbfe77dc77d22cce1a7fa0a0abfc53f71f"
#define HALO_EXPANDED_CACHE_NAME_SIZE 32
#define HALO_EXPANDED_CACHE_DIGEST_SIZE 32

struct game_variant;
struct native_map_cache_selection
{
    char logical_name[HALO_EXPANDED_CACHE_NAME_SIZE];
    char physical_name[HALO_EXPANDED_CACHE_NAME_SIZE];
    unsigned char sha256[HALO_EXPANDED_CACHE_DIGEST_SIZE];
    unsigned char weapon_list_sha256[HALO_EXPANDED_CACHE_DIGEST_SIZE];
    unsigned generation;
    int expanded;
    /* Local path frozen after validation; never encoded or compared on wire. */
    char physical_path[256];
};

/* Stage and validate before changing any selected map, variant or cache.
   Original map-local modes need no hidden cache. Error presentation is optional. */
int native_map_cache_prepare(char const *map, struct game_variant const *variant,
    struct native_map_cache_selection *selection, int show_error);
/* Remote clients request the exact offered digest. NULL requests a compatible
   current revision for local/host selection. Pending never selects a cache. */
int native_map_cache_prepare_expected(char const *map, struct game_variant const *variant,
    unsigned char const *expected_sha256, struct native_map_cache_selection *selection,
    int show_error);
/* Result of the most recent preparation: -1 failed, 0 unavailable, 1 verified,
   2 downloading. Callers retain their previous choice on every non-ready result. */
int native_map_cache_download_status(void);
void native_map_cache_select(struct native_map_cache_selection const *selection);
struct native_map_cache_selection const *native_map_cache_current(void);
/* Used consistently by precache/copy/open lookup, never by menus or wire maps. */
char const *native_map_cache_resolve(char const *map);
int native_map_cache_selection_equal(struct native_map_cache_selection const *a,
    struct native_map_cache_selection const *b);
int native_map_cache_uses_global_arsenal(struct game_variant const *variant);
/* Lowercase logical names up to 31 bytes map to private names up to 31 bytes. */
int native_map_cache_physical_name(char const *logical, char physical[32]);

#endif
