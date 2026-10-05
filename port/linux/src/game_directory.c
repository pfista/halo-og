#include "game_directory.h"
#if defined(HALO_ANDROID) && !defined(HALO_MACOS)
void game_directory_set_invite(const char *invite) { (void)invite; }
void game_directory_publish(const char *name, const char *map, int engine, int players, int maximum,
    int version, int open, int in_progress, int teams, int score_limit, int oddball_variant, int enabled) {}
void game_directory_browse(int enabled) { (void)enabled; }
void game_directory_set_foreground(int enabled) { (void)enabled; }
int game_directory_snapshot(struct halo_directory_game *games, int capacity) { return 0; }
#else
#include "port_config.h"
#include "p2p_internal.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <SDL3/SDL.h>

extern void platform_log(const char *format, ...);
static pthread_mutex_t directory_lock = PTHREAD_MUTEX_INITIALIZER;
static struct halo_directory_game hosted, cached[HALO_DIRECTORY_MAX_GAMES];
static char host_invite[P2P_LINK_SIZE], directory_url[256];
static unsigned long fetched_time;
static unsigned long browse_visible_time;
static int running, browsing, publishing, cached_count;
static int foreground = 1;
static unsigned browse_generation, retry_random = 1;

/* Small positive jitter spreads retries between clients. No engine RNG state. */
static unsigned retry_delay(unsigned *backoff, unsigned maximum, int retry_after_seconds)
{
    unsigned delay;
    *backoff = !*backoff ? 5000 : *backoff >= maximum / 2 ? maximum : *backoff * 2;
    retry_random = retry_random * 1664525u + 1013904223u;
    delay = *backoff + retry_random % (*backoff / 4 + 1);
    if (delay > maximum) delay = maximum;
    if (retry_after_seconds > 0 && (unsigned)retry_after_seconds * 1000 > delay)
        delay = (unsigned)retry_after_seconds * 1000;
    return delay;
}

static int request(const char *method, const char *id, const char *lease, const char *body,
    char *response, int capacity, int *status, int *retry_after_seconds)
{
    char url[352];
    snprintf(url, sizeof(url), "%s/v1/games%s%s%s", directory_url, id && *id ? "/" : "", id ? id : "",
        !strcmp(method, "GET") ? "?invite_scheme=" P2P_INVITE_SCHEME : "");
    return halo_directory_http(method, url, lease, body, response, capacity, status, retry_after_seconds);
}
static void *directory_worker(void *unused)
{
    struct halo_directory_game previous = {0}, desired, games[HALO_DIRECTORY_MAX_GAMES];
    char id[37] = {0}, lease[65] = {0}, body[1024], small[4096];
    char *response = malloc(HALO_DIRECTORY_BODY_LIMIT);
    unsigned long published_time = 0, browse_time = 0, withdrawal_time = 0, lease_time = 0;
    unsigned publish_backoff = 0, publish_retry = 0, browse_backoff = 0, browse_retry = 0;
    unsigned withdrawal_backoff = 0, withdrawal_retry = 0, seen_generation = ~0u;
    int first_publish = 1, first_withdrawal = 1, failure_logged = 0;
    if (!response) {
        pthread_mutex_lock(&directory_lock); running = 0; pthread_mutex_unlock(&directory_lock);
        return NULL;
    }
    for (;;) {
        int browse, publish, status = 0, size, count, retry_after_seconds = 0;
        unsigned generation;
        unsigned long now = p2p_now();
        pthread_mutex_lock(&directory_lock);
        desired = hosted;
        snprintf(desired.invite, sizeof(desired.invite), "%s", host_invite);
        publish = publishing && desired.invite[0];
        pthread_mutex_unlock(&directory_lock);
        if (id[0] && (!publish || strcmp(desired.invite, previous.invite))) {
            /* Keep a failed withdrawal's lease: resuming the same host can
               renew it instead of leaving two entries until the old one expires. */
            int withdrawn = (unsigned long)(now - lease_time) >= 90000;
            if (!withdrawn && (first_withdrawal || (unsigned long)(now - withdrawal_time) >= withdrawal_retry)) {
                first_withdrawal = 0; withdrawal_time = now;
                size = request("DELETE", id, lease, NULL, small, sizeof(small), &status, &retry_after_seconds);
                withdrawn = size >= 0 && (status == 204 || status == 404);
                withdrawal_time = p2p_now();
                if (!withdrawn) withdrawal_retry = retry_delay(&withdrawal_backoff, 30000, retry_after_seconds);
            }
            if (withdrawn) {
                memset(id, 0, sizeof(id)); memset(lease, 0, sizeof(lease)); first_publish = 1;
                withdrawal_retry = withdrawal_backoff = 0;
            }
        } else { first_withdrawal = 1; withdrawal_retry = withdrawal_backoff = 0; }
        if (!publish) first_publish = 1;
        now = p2p_now();
        if (publish && (!id[0] || !strcmp(desired.invite, previous.invite)) &&
            (!publish_retry || (unsigned long)(now - published_time) >= publish_retry) &&
            (first_publish || (unsigned long)(now - published_time) >= 30000 ||
            (publish_retry && (unsigned long)(now - published_time) >= publish_retry) ||
            ((unsigned long)(now - published_time) >= 5000 && memcmp(&desired, &previous, sizeof(desired))))) {
            first_publish = 0; published_time = now;
            if (halo_directory_encode(&desired, body, sizeof(body))) {
                retry_after_seconds = 0;
                size = request(id[0] ? "PUT" : "POST", id, lease, body, small, sizeof(small), &status, &retry_after_seconds);
                /* A lost response may still have renewed the server's 90s lease.
                   Count from completion so time spent in HTTP cannot shorten it. */
                lease_time = p2p_now();
                published_time = lease_time;
                if (size >= 0 && ((!id[0] && status == 201 && halo_directory_parse_lease(small, size, id, lease)) ||
                    (id[0] && status == 200))) {
                    previous = desired; failure_logged = 0;
                    publish_retry = publish_backoff = 0;
                    platform_log("System Link directory: advertised %s (%s, %d/%d players)",
                        desired.name, desired.map, desired.player_count, desired.max_players);
                } else {
                    if (status == 404 || status == 403 || status == 201) { id[0] = lease[0] = 0; }
                    if (!failure_logged) platform_log("System Link directory: advertisement unavailable (HTTP %d); will retry", status);
                    failure_logged = 1;
                    publish_retry = retry_delay(&publish_backoff, id[0] ? 30000 : 60000, retry_after_seconds);
                }
            }
        }
        /* Publication may block in HTTP. Recheck current page/focus immediately
           before browsing, and reject responses from a previous page visit. */
        now = p2p_now();
        pthread_mutex_lock(&directory_lock);
        browse = browsing && foreground && (unsigned long)(now - browse_visible_time) < 1000;
        generation = browse_generation;
        pthread_mutex_unlock(&directory_lock);
        if (browse && (!browse_retry || (unsigned long)(now - browse_time) >= browse_retry) &&
            (generation != seen_generation ||
             (unsigned long)(now - browse_time) >= (browse_retry ? browse_retry : 10000))) {
            seen_generation = generation;
            retry_after_seconds = 0;
            size = request("GET", NULL, NULL, NULL, response, HALO_DIRECTORY_BODY_LIMIT, &status, &retry_after_seconds);
            browse_time = p2p_now();
            count = size >= 0 && status == 200 ? halo_directory_parse_games(response, size, games, HALO_DIRECTORY_MAX_GAMES) : -1;
            if (count >= 0) {
                browse_retry = browse_backoff = 0;
                pthread_mutex_lock(&directory_lock);
                if (browsing && foreground && browse_generation == generation &&
                    (unsigned long)(p2p_now() - browse_visible_time) < 1000) {
                    memcpy(cached, games, (unsigned)count * sizeof(*games));
                    cached_count = count; fetched_time = p2p_now();
                }
                pthread_mutex_unlock(&directory_lock);
            } else browse_retry = retry_delay(&browse_backoff, 60000, retry_after_seconds);
        }
        SDL_Delay(200);
    }
    return NULL;
}
static void start_locked(void)
{
    pthread_t thread;
    const char *url;
    size_t length;
    if (running || !config_boolean("network.online")) return;
    url = config_string("network.directory_url"); length = strlen(url);
    if (length < 9 || length >= sizeof(directory_url) || strncmp(url, "https://", 8) ||
        strpbrk(url + 8, "\r\n\t @?#\\") || url[8] == '/') return;
    memcpy(directory_url, url, length + 1);
    while (length && directory_url[length - 1] == '/') directory_url[--length] = 0;
    retry_random = (unsigned)p2p_now() ^ (unsigned)(uintptr_t)&directory_lock;
    if (!pthread_create(&thread, NULL, directory_worker, NULL)) { running = 1; pthread_detach(thread); }
}
void game_directory_set_invite(const char *invite)
{
    pthread_mutex_lock(&directory_lock);
    snprintf(host_invite, sizeof(host_invite), "%s", invite ? invite : "");
    pthread_mutex_unlock(&directory_lock);
}
void game_directory_publish(const char *name, const char *map, int engine, int players, int maximum,
    int version, int open, int in_progress, int teams, int score_limit, int oddball_variant, int enabled)
{
    static const char *const modes[] = { "", "CTF", "Slayer", "Oddball", "King", "Race" };
    struct halo_directory_game game = {0}; const char *base = map ? map : "";
    int i;
    for (i = 0; base[i]; i++) if (base[i] == '/' || base[i] == '\\') map = base + i + 1;
    snprintf(game.name, sizeof(game.name), "%s", name && *name ? name : "Halo OG");
    snprintf(game.map, sizeof(game.map), "%s", map ? map : "");
    snprintf(game.gametype, sizeof(game.gametype), "%s", engine >= 1 && engine <= 5 ? modes[engine] : "");
    game.player_count = players; game.max_players = maximum; game.network_version = version;
    game.open = open; game.in_progress = in_progress; game.has_teams = teams;
    game.score_limit = score_limit; game.oddball_variant = oddball_variant;
    pthread_mutex_lock(&directory_lock);
    hosted = game;
    publishing = enabled && config_boolean("network.online") && config_boolean("network.public_games");
    if (publishing) start_locked();
    pthread_mutex_unlock(&directory_lock);
}
void game_directory_browse(int enabled)
{
    pthread_mutex_lock(&directory_lock);
    int requested = enabled && config_boolean("network.online");
    unsigned long now = p2p_now();
    if (browsing != requested || (requested && (unsigned long)(now - browse_visible_time) >= 1000))
        browse_generation++;
    browsing = requested;
    if (browsing) browse_visible_time = now;
    if (browsing) start_locked();
    else cached_count = 0;
    pthread_mutex_unlock(&directory_lock);
}
void game_directory_set_foreground(int enabled)
{
    pthread_mutex_lock(&directory_lock);
    if (foreground != !!enabled) browse_generation++;
    foreground = !!enabled;
    pthread_mutex_unlock(&directory_lock);
}
int game_directory_snapshot(struct halo_directory_game *games, int capacity)
{
    unsigned long now = p2p_now(); int i, count = 0;
    pthread_mutex_lock(&directory_lock);
    for (i = 0; i < cached_count && count < capacity; i++)
        if ((unsigned long)(now - fetched_time) < (unsigned)cached[i].lifetime_seconds * 1000 &&
            strcmp(cached[i].invite, host_invite)) games[count++] = cached[i];
    pthread_mutex_unlock(&directory_lock);
    return count;
}
#endif
