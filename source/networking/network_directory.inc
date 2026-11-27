/* System Link discovery through the public directory. Directory records are
   display data; joining always waits for the authenticated tunnel and a real
   advertisement from the host it reaches. */
#include "../../port/linux/src/game_directory.h"
#include "../../port/linux/src/p2p.h"

static struct network_advertised_game directory_games[HALO_DIRECTORY_MAX_GAMES];
static struct halo_directory_game directory_metadata[HALO_DIRECTORY_MAX_GAMES];
static long directory_game_count;
static char directory_join_invite[P2P_LINK_SIZE];
static unsigned long directory_join_started;
static boolean directory_join_event_posted;
static unsigned long directory_join_event_time;
/* A host that closed without withdrawing its listing (an app that was quit
   or put in the background) stays in the directory until the listing lapses.
   One that never answers a request to join is left out of the list for as
   long as a listing lasts. */
#define DIRECTORY_ANSWER_MILLISECONDS 10000
#define DIRECTORY_RENEWED_SECONDS 50
#define DIRECTORY_SILENT_MILLISECONDS 90000
#define DIRECTORY_SILENT_HOSTS 4
static char directory_silent_invites[DIRECTORY_SILENT_HOSTS][P2P_LINK_SIZE];
static unsigned long directory_silent_times[DIRECTORY_SILENT_HOSTS];
static long directory_silent_next;
void platform_show_message(char const *title, char const *message);

typedef char directory_xnaddr_size_assert[
    sizeof(XNADDR) == sizeof(((struct network_advertised_game *)0)->xnaddr) ? 1 : -1];

static boolean directory_game_matches_host(struct network_advertised_game const *game,
    unsigned char const identity[6])
{
    XNADDR xnaddr;
    /* The Xbox record begins with size/flags, then abEnet, then IPv4. Use
       its actual type rather than assuming an IPv4/port/MAC byte layout.
       The identity alone names the host: the record's IPv4 address is the
       host's own on its local network, never the tunnel's, and the join
       reaches a tunnel peer by its identity (XNetXnAddrToInAddr). Comparing
       that address with the tunnel's never matched, so a selected game was
       only joined on a second press. */
    csmemcpy(&xnaddr, &game->xnaddr, sizeof(xnaddr));
    return !csmemcmp(xnaddr.abEnet, identity, sizeof(xnaddr.abEnet));
}

static boolean directory_host_is_silent(char const *invite)
{
    long i;
    for (i = 0; i < DIRECTORY_SILENT_HOSTS; i++)
        if (directory_silent_invites[i][0] && !csstrcmp(directory_silent_invites[i], invite) &&
            (unsigned long)(system_milliseconds() - directory_silent_times[i]) < DIRECTORY_SILENT_MILLISECONDS)
            return TRUE;
    return FALSE;
}

static long directory_game_index(struct network_advertised_game const *game)
{
    long i;
    for (i = 0; i < directory_game_count; i++) if (game == &directory_games[i]) return i;
    return NONE;
}
void network_game_client_directory_cancel(void)
{
    directory_join_invite[0] = 0;
    directory_join_event_posted = FALSE;
    directory_game_count = 0;
    game_directory_browse(FALSE);
}
struct network_advertised_game *network_game_client_get_directory_games(
    struct network_game_client *client, long *count)
{
    struct halo_directory_game snapshot[HALO_DIRECTORY_MAX_GAMES];
    long i, j, input_count;
    *count = 0;
    directory_game_count = 0;
    if (!client || client->state != _network_game_client_state_searching) {
        game_directory_browse(FALSE);
        return directory_games;
    }
    game_directory_browse(TRUE);
    input_count = game_directory_snapshot(snapshot, HALO_DIRECTORY_MAX_GAMES);
    csmemset(directory_games, 0, sizeof(directory_games));
    for (i = 0; i < input_count; i++) {
        struct network_advertised_game *game;
        unsigned char identity[6], previous_identity[6];
        long output_index = directory_game_count;
        boolean duplicate = FALSE;
        if ((snapshot[i].network_version != HALO_PORT_NETWORK_VERSION &&
             snapshot[i].network_version != NETWORK_PERFORMANCE_ADVERTISED_VERSION) ||
            !halo_directory_engine(snapshot[i].gametype) ||
            !p2p_invite_identity(snapshot[i].invite, identity) ||
            directory_host_is_silent(snapshot[i].invite)) continue;
        /* The same host reached over the LAN or a tunnel gets one row. */
        for (j = 0; j < MAXIMUM_NETWORK_ADVERTISED_GAMES; j++)
            if (network_game_client_advertised_game_is_valid(&client->available_games[j]) &&
                directory_game_matches_host(&client->available_games[j], identity)) duplicate = TRUE;
        for (j = 0; j < directory_game_count; j++)
            if (p2p_invite_identity(directory_metadata[j].invite, previous_identity) &&
                !csmemcmp(identity, previous_identity, 6)) {
                /* Every lease uses the same TTL: greater remaining lifetime
                   identifies the more recently refreshed record for a host. */
                if (snapshot[i].lifetime_seconds <= directory_metadata[j].lifetime_seconds)
                    duplicate = TRUE;
                else
                    output_index = j;
                break;
            }
        if (duplicate) continue;
        game = &directory_games[output_index];
        csmemset(game, 0, sizeof(*game));
        directory_metadata[output_index] = snapshot[i];
        if (output_index == directory_game_count) directory_game_count++;
        for (j = 0; j < NETWORK_GAME_NAME_LENGTH - 1 && snapshot[i].name[j]; j++)
            game->game_name[j] = (wchar_t)(unsigned char)snapshot[i].name[j];
        if (!csstrcmp(snapshot[i].invite, directory_join_invite))
            ustrncpy(game->game_name, L"Connecting...", NETWORK_GAME_NAME_LENGTH - 1);
        csstrncpy(game->map.name, snapshot[i].map, NETWORK_GAME_MAP_NAME_LENGTH - 1);
        game->engine_type = (short)halo_directory_engine(snapshot[i].gametype);
        game->player_count = (word)snapshot[i].player_count;
        game->maximum_player_count = (short)snapshot[i].max_players;
        game->unknown100 = (short)snapshot[i].score_limit;
        game->oddball_variant = (boolean)snapshot[i].oddball_variant;
        game->machine_count = 1;
        game->platform = _network_game_platform_xbox;
        game->open = (boolean)snapshot[i].open;
        game->has_teams = (boolean)snapshot[i].has_teams;
        game->valid = TRUE;
        game->update_time = system_milliseconds();
    }
    /* Listings their hosts keep renewing come first, in the directory's
       order. A host renews every 30 seconds of the 90 a listing lasts, so one
       with less than DIRECTORY_RENEWED_SECONDS left has missed a renewal: a
       host that closed without withdrawing leaves such a listing, and the
       game it opens next under the same name then stands above it. (Not by
       time left alone: live games would trade places at every renewal, under
       the player's selection.) */
    for (i = 1; i < directory_game_count; i++) {
        struct network_advertised_game game = directory_games[i];
        struct halo_directory_game metadata = directory_metadata[i];
        if (metadata.lifetime_seconds < DIRECTORY_RENEWED_SECONDS) continue;
        for (j = i; j > 0 && directory_metadata[j - 1].lifetime_seconds < DIRECTORY_RENEWED_SECONDS; j--) {
            directory_games[j] = directory_games[j - 1];
            directory_metadata[j] = directory_metadata[j - 1];
        }
        directory_games[j] = game;
        directory_metadata[j] = metadata;
    }
    *count = directory_game_count;
    return directory_games;
}
boolean network_game_client_directory_begin_join(struct network_advertised_game *game)
{
    long i = directory_game_index(game);
    if (i == NONE) { directory_join_invite[0] = 0; directory_join_event_posted = FALSE; return FALSE; }
    if (!game->open) return TRUE;
    csstrncpy(directory_join_invite, directory_metadata[i].invite, sizeof(directory_join_invite) - 1);
    directory_join_invite[sizeof(directory_join_invite) - 1] = 0;
    directory_join_started = system_milliseconds();
    directory_join_event_posted = FALSE;
    p2p_join_invite(directory_join_invite);
    network_event("System Link directory: connecting to selected host");
    return TRUE;
}
struct network_advertised_game *network_game_client_directory_join_ready(struct network_game_client *client)
{
    unsigned long address;
    unsigned char identity[6];
    long i;
    if (!directory_join_invite[0] || !client || client->state != _network_game_client_state_searching) return NULL;
    if ((unsigned long)(system_milliseconds() - directory_join_started) >= 30000) {
        directory_join_invite[0] = 0; directory_join_event_posted = FALSE;
        platform_show_message("Halo OG: unable to connect",
            "The host did not become reachable. It may have stopped hosting, or the networks may not allow a direct connection.\n\nTry again, or use a private invite or LAN game.");
        return NULL;
    }
    if (!p2p_invite_identity(directory_join_invite, identity)) return NULL;
    if (!p2p_invite_peer_address(directory_join_invite, &address)) {
        /* Not reached yet. A host that has not even answered by now has
           closed: say so at once, and leave its listing out of the list. */
        if ((unsigned long)(system_milliseconds() - directory_join_started) >= DIRECTORY_ANSWER_MILLISECONDS &&
            !p2p_invite_answered(directory_join_invite)) {
            csstrncpy(directory_silent_invites[directory_silent_next], directory_join_invite, P2P_LINK_SIZE - 1);
            directory_silent_invites[directory_silent_next][P2P_LINK_SIZE - 1] = 0;
            directory_silent_times[directory_silent_next] = system_milliseconds();
            directory_silent_next = (directory_silent_next + 1) % DIRECTORY_SILENT_HOSTS;
            directory_join_invite[0] = 0; directory_join_event_posted = FALSE;
            platform_show_message("Halo OG: unable to connect",
                "That game's host did not answer. It has probably closed; a closed game can stay listed for a minute or so.\n\nPick another game, or create one.");
        }
        return NULL;
    }
    for (i = 0; i < MAXIMUM_NETWORK_ADVERTISED_GAMES; i++) {
        struct network_advertised_game *game = &client->available_games[i];
        if (network_game_client_advertised_game_is_valid(game) &&
            directory_game_matches_host(game, identity)) return game;
    }
    return NULL;
}
boolean network_game_client_directory_should_post_join(struct network_game_client *client)
{
    /* Menus can suppress/drop queued events. Retry after a second while
       retaining the selected authenticated host, rather than getting stuck. */
    if ((directory_join_event_posted &&
        (unsigned long)(system_milliseconds() - directory_join_event_time) < 1000) ||
        !network_game_client_directory_join_ready(client)) return FALSE;
    directory_join_event_posted = TRUE;
    directory_join_event_time = system_milliseconds();
    return TRUE;
}
struct network_advertised_game *network_game_client_directory_take_join(struct network_game_client *client)
{
    struct network_advertised_game *game = network_game_client_directory_join_ready(client);
    if (game) { directory_join_invite[0] = 0; directory_join_event_posted = FALSE; }
    return game;
}
