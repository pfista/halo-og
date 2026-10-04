#ifndef HALO_GAME_DIRECTORY_H
#define HALO_GAME_DIRECTORY_H

/* Shared desktop directory. Fixed-width character buffers and ints keep the
   same layout in the Apple ILP32 guest and native host. No Cloudflare token. */
#define HALO_DIRECTORY_MAX_GAMES 64
#define HALO_DIRECTORY_BODY_LIMIT (256 * 1024)
struct halo_directory_game {
    char id[37], name[33], map[33], gametype[25], invite[77];
    int player_count, max_players, network_version, open, in_progress, has_teams;
    int lifetime_seconds;
};

int halo_directory_parse_games(const char *json, int size,
    struct halo_directory_game *games, int capacity);
int halo_directory_parse_lease(const char *json, int size, char id[37], char token[65]);
int halo_directory_encode(const struct halo_directory_game *game, char *out, int capacity);
int halo_directory_engine(const char *gametype);

void game_directory_set_invite(const char *invite);
void game_directory_publish(const char *name, const char *map, int engine,
    int players, int maximum, int version, int open, int in_progress, int teams, int enabled);
void game_directory_browse(int enabled);
int game_directory_snapshot(struct halo_directory_game *games, int capacity);

/* Synchronous only on a directory worker. Certificate/hostname verification,
   bounded response, no redirects. Returns response bytes, or -1 on failure. */
#if defined(HALO_MACOS) && defined(__ILP32__)
/* The guest compiler rebases pointer arguments to host-prefixed imports. */
#define halo_directory_http host_halo_directory_http
#endif
int halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status);

#endif
