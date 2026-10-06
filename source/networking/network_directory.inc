/* The original System Link list combines LAN, Halo OG's directory and OpenCE's
   signed public listings. Remote records are display data; joining always
   waits for the authenticated tunnel and a real protocol advertisement. */
#include "../../port/linux/src/game_directory.h"
#include "../../port/linux/src/p2p.h"

static struct network_advertised_game directory_games[HALO_DIRECTORY_MAX_GAMES];
static struct halo_directory_game directory_metadata[HALO_DIRECTORY_MAX_GAMES];
static byte directory_identities[HALO_DIRECTORY_MAX_GAMES][6];
static long directory_game_count;
static char directory_join_invite[P2P_LINK_SIZE];
static unsigned long directory_join_started;
static boolean directory_join_event_posted;
static unsigned long directory_join_event_time;
void platform_show_message(char const *title, char const *message);

typedef char directory_xnaddr_size_assert[
    sizeof(XNADDR) == sizeof(((struct network_advertised_game *)0)->xnaddr) ? 1 : -1];

static boolean directory_game_matches_host(struct network_advertised_game const *game,
    unsigned char const identity[6], unsigned long const *address)
{
    XNADDR xnaddr;
    /* The Xbox record begins with size/flags, then abEnet, then IPv4. Use
       its actual type rather than assuming an IPv4/port/MAC byte layout. */
    csmemcpy(&xnaddr, &game->xnaddr, sizeof(xnaddr));
    return !csmemcmp(xnaddr.abEnet, identity, sizeof(xnaddr.abEnet)) &&
        (!address || !csmemcmp(&xnaddr.ina, address, sizeof(xnaddr.ina)));
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
    p2p_lobby_browse(FALSE);
}

/* A remote row shares neither keys nor authoritative rules with the game.
   Both providers deduplicate by the same authenticated host identity as LAN. */
static void directory_game_add(struct network_game_client *client,
    struct halo_directory_game const *metadata, short engine,
    byte const identity[6], boolean replace_older)
{
    struct network_advertised_game *game;
    long index, output_index = directory_game_count;

    for (index = 0; index < MAXIMUM_NETWORK_ADVERTISED_GAMES; index++)
        if (network_game_client_advertised_game_is_valid(&client->available_games[index]) &&
            directory_game_matches_host(&client->available_games[index], identity, NULL)) return;
    for (index = 0; index < directory_game_count; index++)
        if (!csmemcmp(identity, directory_identities[index], 6))
        {
            /* OG leases use one TTL: greater remaining lifetime is fresher.
               An OpenCE copy does not replace the same host's OG directory row. */
            if (!replace_older || metadata->lifetime_seconds <= directory_metadata[index].lifetime_seconds) return;
            output_index = index;
            break;
        }
    if (output_index >= HALO_DIRECTORY_MAX_GAMES) return;
    game = &directory_games[output_index];
    csmemset(game, 0, sizeof(*game));
    directory_metadata[output_index] = *metadata;
    csmemcpy(directory_identities[output_index], identity, 6);
    if (output_index == directory_game_count) directory_game_count++;
    for (index = 0; index < NETWORK_GAME_NAME_LENGTH - 1 && metadata->name[index]; index++)
        game->game_name[index] = (wchar_t)(unsigned char)metadata->name[index];
    if (metadata->invite[0] && !csstrcmp(metadata->invite, directory_join_invite))
        ustrncpy(game->game_name, L"Connecting...", NETWORK_GAME_NAME_LENGTH - 1);
    csstrncpy(game->map.name, metadata->map, NETWORK_GAME_MAP_NAME_LENGTH - 1);
    game->engine_type = engine;
    game->player_count = (word)metadata->player_count;
    game->maximum_player_count = (short)metadata->max_players;
    game->unknown100 = (short)metadata->score_limit;
    game->oddball_variant = (boolean)metadata->oddball_variant;
    game->machine_count = 1;
    game->platform = _network_game_platform_xbox;
    game->open = (boolean)metadata->open;
    game->has_teams = (boolean)metadata->has_teams;
    game->valid = TRUE;
    game->update_time = system_milliseconds();
}

static boolean directory_listing_text_valid(char const *text, unsigned size)
{
    unsigned index;
    boolean nonspace = FALSE;
    for (index = 0; index < size && text[index]; index++)
    {
        unsigned char character = (unsigned char)text[index];
        if (character < 32 || character > 126) return FALSE;
        if (character != ' ') nonspace = TRUE;
    }
    return index < size && nonspace;
}

struct network_advertised_game *network_game_client_get_directory_games(
    struct network_game_client *client, long *count)
{
    struct halo_directory_game snapshot[HALO_DIRECTORY_MAX_GAMES];
    struct p2p_listing public_games[HALO_DIRECTORY_MAX_GAMES];
    long i, input_count;
    *count = 0;
    directory_game_count = 0;
    if (!client || client->state != _network_game_client_state_searching) {
        game_directory_browse(FALSE);
        p2p_lobby_browse(FALSE);
        return directory_games;
    }
    game_directory_browse(TRUE);
    p2p_lobby_browse(TRUE);
    input_count = game_directory_snapshot(snapshot, HALO_DIRECTORY_MAX_GAMES);
    csmemset(directory_games, 0, sizeof(directory_games));
    for (i = 0; i < input_count; i++) {
        unsigned char identity[6];
        struct halo_directory_game metadata = snapshot[i];
        boolean legacy = metadata.network_version == 11 || metadata.network_version == 0x800B;
        if ((snapshot[i].network_version != HALO_PORT_NETWORK_VERSION &&
             snapshot[i].network_version != NETWORK_PERFORMANCE_ADVERTISED_VERSION && !legacy) ||
            !halo_directory_engine(snapshot[i].gametype) ||
            !p2p_invite_identity(snapshot[i].invite, identity)) continue;
        if (legacy)
        {
            unsigned index;
            csmemset(metadata.name, 0, sizeof(metadata.name));
            csstrncpy(metadata.name, "OG v11: ", sizeof(metadata.name) - 1);
            for (index = 0; index < sizeof(metadata.name) - 9 && snapshot[i].name[index]; index++)
                metadata.name[index + 8] = snapshot[i].name[index];
            metadata.name[index + 8] = 0;
            /* Useful discovery of the original app's hosts, without claiming
               its protocol11 game packets are interchangeable with20. */
            metadata.open = FALSE;
        }
        directory_game_add(client, &metadata, (short)halo_directory_engine(snapshot[i].gametype), identity, TRUE);
    }
    /* This API exposes only protocol20 listings whose Ed25519 signature, key
       hash, sequence and retained timestamp passed OpenCE's cache validation.
       Its worker removes expired games; snapshot withdrawal removes the row. */
    input_count = p2p_lobby_games(public_games, HALO_DIRECTORY_MAX_GAMES);
    for (i = 0; i < input_count && i < HALO_DIRECTORY_MAX_GAMES; i++)
    {
        struct p2p_listing const *listing = &public_games[i];
        struct halo_directory_game metadata;
        unsigned char identity[6];
        if ((listing->identifier[0] & 3) != 2 ||
            listing->engine_type > 5 || !listing->maximum_player_count ||
            listing->maximum_player_count > HALO_PORT_MAXIMUM_NETWORK_PLAYERS ||
            listing->player_count > listing->maximum_player_count ||
            listing->open > 1 || listing->in_progress > 1 || listing->has_teams > 1 || listing->locked > 1 ||
            !directory_listing_text_valid(listing->name, sizeof(listing->name)) ||
            !directory_listing_text_valid(listing->map, sizeof(listing->map)) ||
            !directory_listing_text_valid(listing->gametype, sizeof(listing->gametype)) ||
            strchr(listing->map, '/') || strstr(listing->map, "..")) continue;
        if (!listing->locked &&
            (!memchr(listing->invite, 0, sizeof(listing->invite)) ||
             !p2p_invite_identity(listing->invite, identity) || csmemcmp(identity, listing->identifier, 6))) continue;
        if (listing->locked) csmemcpy(identity, listing->identifier, 6);
        csmemset(&metadata, 0, sizeof(metadata));
        csstrncpy(metadata.name, listing->name, sizeof(metadata.name) - 1);
        csstrncpy(metadata.map, listing->map, sizeof(metadata.map) - 1);
        csstrncpy(metadata.gametype, listing->gametype, sizeof(metadata.gametype) - 1);
        csstrncpy(metadata.invite, listing->invite, sizeof(metadata.invite) - 1);
        metadata.player_count = listing->player_count;
        metadata.max_players = listing->maximum_player_count;
        metadata.open = listing->open && !listing->locked;
        metadata.in_progress = listing->in_progress;
        metadata.has_teams = listing->has_teams;
        metadata.network_version = HALO_PORT_NETWORK_VERSION;
        /* A signed listing does not carry a score limit or Oddball mode. */
        metadata.score_limit = -1;
        if (listing->locked)
        {
            unsigned index;
            csstrncpy(metadata.name, "Password: ", sizeof(metadata.name) - 1);
            for (index = 0; index < sizeof(metadata.name) - 11 && listing->name[index]; index++)
                metadata.name[index + 10] = listing->name[index];
            metadata.name[index + 10] = 0;
        }
        directory_game_add(client, &metadata, listing->engine_type, identity, FALSE);
    }
    *count = directory_game_count;
    return directory_games;
}
boolean network_game_client_directory_begin_join(struct network_advertised_game *game)
{
    long i = directory_game_index(game);
    if (i == NONE) { directory_join_invite[0] = 0; directory_join_event_posted = FALSE; return FALSE; }
    if (!game->open || !directory_metadata[i].invite[0]) return TRUE;
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
    if (!p2p_invite_identity(directory_join_invite, identity) ||
        !p2p_invite_peer_address(directory_join_invite, &address)) return NULL;
    for (i = 0; i < MAXIMUM_NETWORK_ADVERTISED_GAMES; i++) {
        struct network_advertised_game *game = &client->available_games[i];
        if (network_game_client_advertised_game_is_valid(game) &&
            directory_game_matches_host(game, identity, &address)) return game;
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
