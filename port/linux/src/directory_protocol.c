#include "game_directory.h"
#include <limits.h>
#include <stdio.h>
#include <string.h>

struct directory_json { const unsigned char *p, *end; };

static void directory_space(struct directory_json *j)
{
    while (j->p < j->end && (*j->p == ' ' || *j->p == '\t' || *j->p == '\r' || *j->p == '\n')) j->p++;
}
static int directory_token(struct directory_json *j, unsigned char token)
{
    directory_space(j);
    if (j->p == j->end || *j->p != token) return 0;
    j->p++;
    return 1;
}
static int directory_hex(unsigned char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int directory_string_internal(struct directory_json *j, char *out, size_t capacity, int display)
{
    size_t length = 0;
    if (!directory_token(j, '"')) return 0;
    while (j->p < j->end && *j->p != '"') {
        unsigned char c = *j->p++;
        if (c < 32) return 0;
        if (c == '\\') {
            unsigned code = 0;
            if (j->p == j->end) return 0;
            c = *j->p++;
            switch (c) {
            case '"': case '\\': case '/': break;
            case 'b': c = '\b'; break;
            case 'f': c = '\f'; break;
            case 'n': c = '\n'; break;
            case 'r': c = '\r'; break;
            case 't': c = '\t'; break;
            case 'u':
                for (unsigned i = 0; i < 4; i++) {
                    int digit;
                    if (j->p == j->end || (digit = directory_hex(*j->p++)) < 0) return 0;
                    code = (code << 4) | (unsigned)digit;
                }
                /* Known metadata is ASCII. Preserve its escaped ASCII; other
                   characters cannot become a path or an identity marker. */
                if (code == 0 && out) return 0;
                if (out && (code < 32 || (code > 126 && !display))) return 0;
                c = code < 128 ? (unsigned char)code : '?';
                break;
            default: return 0;
            }
        }
        /* Xbox menu names are ASCII. One replacement per UTF-8 character
           keeps a valid Unicode listing from hiding the entire directory. */
        else if (display && c >= 128) {
            while (j->p < j->end && (*j->p & 0xC0) == 0x80) j->p++;
            c = '?';
        }
        if (out) {
            if (c < 32 || (c > 126 && !display) || length + 1 >= capacity) return 0;
            out[length] = c <= 126 ? (char)c : '?';
        }
        length++;
    }
    if (j->p == j->end) return 0;
    j->p++;
    if (out) out[length] = 0;
    return 1;
}
static int directory_string(struct directory_json *j, char *out, size_t capacity)
{ return directory_string_internal(j, out, capacity, 0); }
static int directory_literal(struct directory_json *j, const char *word)
{
    size_t length = strlen(word);
    directory_space(j);
    if ((size_t)(j->end - j->p) < length || memcmp(j->p, word, length)) return 0;
    j->p += length;
    return 1;
}
static int directory_number(struct directory_json *j)
{
    directory_space(j);
    if (j->p < j->end && *j->p == '-') j->p++;
    if (j->p == j->end || *j->p < '0' || *j->p > '9') return 0;
    if (*j->p++ != '0') while (j->p < j->end && *j->p >= '0' && *j->p <= '9') j->p++;
    if (j->p < j->end && *j->p == '.') {
        j->p++;
        if (j->p == j->end || *j->p < '0' || *j->p > '9') return 0;
        while (j->p < j->end && *j->p >= '0' && *j->p <= '9') j->p++;
    }
    if (j->p < j->end && (*j->p == 'e' || *j->p == 'E')) {
        j->p++;
        if (j->p < j->end && (*j->p == '+' || *j->p == '-')) j->p++;
        if (j->p == j->end || *j->p < '0' || *j->p > '9') return 0;
        while (j->p < j->end && *j->p >= '0' && *j->p <= '9') j->p++;
    }
    return 1;
}
static int directory_skip(struct directory_json *j, unsigned depth)
{
    unsigned char close;
    directory_space(j);
    if (depth > 16 || j->p == j->end) return 0;
    if (*j->p == '"') return directory_string(j, NULL, 0);
    if (*j->p == 't') return directory_literal(j, "true");
    if (*j->p == 'f') return directory_literal(j, "false");
    if (*j->p == 'n') return directory_literal(j, "null");
    if (*j->p != '[' && *j->p != '{') return directory_number(j);
    close = *j->p++ == '[' ? ']' : '}';
    if (directory_token(j, close)) return 1;
    do {
        if (close == '}' && (!directory_string(j, NULL, 0) || !directory_token(j, ':'))) return 0;
        if (!directory_skip(j, depth + 1)) return 0;
        if (directory_token(j, close)) return 1;
    } while (directory_token(j, ','));
    return 0;
}
static int directory_boolean(struct directory_json *j, int *value)
{
    if (directory_literal(j, "true")) { *value = 1; return 1; }
    if (directory_literal(j, "false")) { *value = 0; return 1; }
    return 0;
}

static int directory_uint(struct directory_json *j, unsigned long long *value)
{
    const unsigned char *begin;
    unsigned long long result = 0;
    directory_space(j); begin = j->p;
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') {
        unsigned digit = *j->p++ - '0';
        if (result > (ULLONG_MAX - digit) / 10) return 0;
        result = result * 10 + digit;
    }
    if (j->p == begin || (j->p - begin > 1 && *begin == '0')) return 0;
    *value = result; return 1;
}
static int directory_int(struct directory_json *j, int *value, int maximum)
{
    unsigned long long number;
    if (!directory_uint(j, &number) || number > (unsigned)maximum) return 0;
    *value = (int)number; return 1;
}
static int directory_hex_string(const char *value, int length)
{
    int i;
    if ((int)strlen(value) != length) return 0;
    for (i = 0; i < length; i++) if (directory_hex((unsigned char)value[i]) < 0) return 0;
    return 1;
}
static int directory_id(const char *id)
{
    int i;
    if (strlen(id) != 36) return 0;
    for (i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) { if (id[i] != '-') return 0; }
        else if (directory_hex((unsigned char)id[i]) < 0) return 0;
    }
    return 1;
}
static int directory_invite(const char *invite)
{ return !strncmp(invite, "halo://join/", 12) && directory_hex_string(invite + 12, 64); }
static int directory_map(const char *map)
{
    int i, length = (int)strlen(map);
    if (!length || length > 31 || map[length - 1] == ' ') return 0;
    for (i = 0; i < length; i++) {
        unsigned char c = (unsigned char)map[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '-' || (i && c == ' '))) return 0;
    }
    return 1;
}
int halo_directory_engine(const char *mode)
{
    static const char *const modes[] = { "", "CTF", "Slayer", "Oddball", "King", "Race" };
    int i;
    for (i = 1; i < 6; i++) if (!strcmp(mode, modes[i])) return i;
    return 0;
}
static int directory_game(struct directory_json *j, struct halo_directory_game *game,
    unsigned long long *expiry)
{
    char key[64], value[32];
    unsigned fields = 0, bit;
    memset(game, 0, sizeof(*game)); game->open = 1; game->score_limit = -1;
    if (!directory_token(j, '{')) return 0;
    if (directory_token(j, '}')) return 0;
    do {
        bit = 0;
        if (!directory_string(j, key, sizeof(key)) || !directory_token(j, ':')) return 0;
        if (!strcmp(key, "id")) { bit = 1; if (!directory_string(j, game->id, sizeof(game->id))) return 0; }
        else if (!strcmp(key, "name")) { bit = 2; if (!directory_string_internal(j, game->name, sizeof(game->name), 1)) return 0; }
        else if (!strcmp(key, "map")) { bit = 4; if (!directory_string(j, game->map, sizeof(game->map))) return 0; }
        else if (!strcmp(key, "gametype")) { bit = 8; if (!directory_string(j, game->gametype, sizeof(game->gametype))) return 0; }
        else if (!strcmp(key, "invite")) { bit = 16; if (!directory_string(j, game->invite, sizeof(game->invite))) return 0; }
        else if (!strcmp(key, "player_count")) { bit = 32; if (!directory_int(j, &game->player_count, 128)) return 0; }
        else if (!strcmp(key, "max_players")) { bit = 64; if (!directory_int(j, &game->max_players, 128)) return 0; }
        else if (!strcmp(key, "network_version")) { bit = 128; if (!directory_int(j, &game->network_version, 65535)) return 0; }
        else if (!strcmp(key, "expires_at")) { bit = 256; if (!directory_uint(j, expiry)) return 0; }
        else if (!strcmp(key, "netcode")) { bit = 512; if (!directory_string(j, value, sizeof(value)) || strcmp(value, "distributed")) return 0; }
        else if (!strcmp(key, "open")) { bit = 1024; if (!directory_boolean(j, &game->open)) return 0; }
        else if (!strcmp(key, "in_progress")) { bit = 2048; if (!directory_boolean(j, &game->in_progress)) return 0; }
        else if (!strcmp(key, "has_teams")) { bit = 4096; if (!directory_boolean(j, &game->has_teams)) return 0; }
        else if (!strcmp(key, "score_limit")) { bit = 8192; if (!directory_int(j, &game->score_limit, 32767)) return 0; }
        else if (!strcmp(key, "oddball_variant")) { bit = 16384; if (!directory_boolean(j, &game->oddball_variant)) return 0; }
        else if (!directory_skip(j, 1)) return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (directory_token(j, '}')) break;
        if (!directory_token(j, ',')) return 0;
    } while (1);
    return (fields & 511) == 511 && directory_id(game->id) && game->name[0] &&
        directory_map(game->map) && directory_invite(game->invite) && game->network_version > 0 &&
        game->max_players > 0 && game->player_count <= game->max_players && game->gametype[0];
}
int halo_directory_parse_games(const char *json, int size, struct halo_directory_game *games, int capacity)
{
    struct directory_json j;
    struct halo_directory_game game;
    unsigned long long server_time = 0, expiry, expiries[HALO_DIRECTORY_MAX_GAMES];
    unsigned fields = 0, bit;
    char key[64];
    int version, count = 0, scanned = 0, i, kept = 0;
    if (!json || size < 0 || size > HALO_DIRECTORY_BODY_LIMIT || capacity < 0 || capacity > HALO_DIRECTORY_MAX_GAMES ||
        (capacity && !games)) return -1;
    j.p = (const unsigned char *)json; j.end = j.p + size;
    if (!directory_token(&j, '{') || directory_token(&j, '}')) return -1;
    do {
        bit = 0;
        if (!directory_string(&j, key, sizeof(key)) || !directory_token(&j, ':')) return -1;
        if (!strcmp(key, "api_version")) { bit = 1; if (!directory_int(&j, &version, 1) || version != 1) return -1; }
        else if (!strcmp(key, "server_time")) { bit = 2; if (!directory_uint(&j, &server_time)) return -1; }
        else if (!strcmp(key, "games")) {
            bit = 4;
            if (!directory_token(&j, '[')) return -1;
            if (!directory_token(&j, ']')) do {
                if (++scanned > 256 || !directory_game(&j, &game, &expiry)) return -1;
                if (count < capacity) { games[count] = game; expiries[count++] = expiry; }
                if (directory_token(&j, ']')) break;
                if (!directory_token(&j, ',')) return -1;
            } while (1);
        } else if (!directory_skip(&j, 1)) return -1;
        if (fields & bit) return -1;
        fields |= bit;
        if (directory_token(&j, '}')) break;
        if (!directory_token(&j, ',')) return -1;
    } while (1);
    directory_space(&j);
    if (fields != 7 || j.p != j.end) return -1;
    for (i = 0; i < count; i++) if (expiries[i] > server_time) {
        unsigned long long remaining = expiries[i] - server_time;
        games[i].lifetime_seconds = remaining > 90 ? 90 : (int)remaining;
        games[kept++] = games[i];
    }
    return kept;
}
int halo_directory_parse_lease(const char *json, int size, char id[37], char token[65])
{
    struct directory_json j;
    char key[64]; unsigned fields = 0, bit;
    id[0] = token[0] = 0;
    if (!json || size < 0 || size > 4096) return 0;
    j.p = (const unsigned char *)json; j.end = j.p + size;
    if (!directory_token(&j, '{') || directory_token(&j, '}')) return 0;
    do {
        bit = 0;
        if (!directory_string(&j, key, sizeof(key)) || !directory_token(&j, ':')) return 0;
        if (!strcmp(key, "id")) { bit = 1; if (!directory_string(&j, id, 37)) return 0; }
        else if (!strcmp(key, "lease_token")) { bit = 2; if (!directory_string(&j, token, 65)) return 0; }
        else if (!directory_skip(&j, 1)) return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (directory_token(&j, '}')) break;
        if (!directory_token(&j, ',')) return 0;
    } while (1);
    directory_space(&j);
    return fields == 3 && j.p == j.end && directory_id(id) && directory_hex_string(token, 64);
}
static int directory_quote(const char *text, char *out, int capacity)
{
    int length = 0;
    while (*text) {
        unsigned char c = (unsigned char)*text++;
        if (c < 32 || c > 126 || length + 2 >= capacity) return 0;
        if (c == '"' || c == '\\') out[length++] = '\\';
        out[length++] = (char)c;
    }
    out[length] = 0; return 1;
}
int halo_directory_encode(const struct halo_directory_game *game, char *out, int capacity)
{
    char name[67], score[32] = {0}; int length;
    if (!game || !out || capacity < 1) return 0;
    if (!game->name[0] || strlen(game->name) > 32 || !directory_quote(game->name, name, sizeof(name)) ||
        !directory_map(game->map) || !directory_invite(game->invite) || !halo_directory_engine(game->gametype) ||
        game->network_version <= 0 || game->network_version > 65535 || game->player_count < 0 ||
        game->max_players < 1 || game->max_players > 128 || game->player_count > game->max_players ||
        game->score_limit < -1 || game->score_limit > 32767) return 0;
    if (game->score_limit >= 0)
        snprintf(score, sizeof(score), ",\"score_limit\":%d", game->score_limit);
    length = snprintf(out, (unsigned)capacity,
        "{\"name\":\"%s\",\"map\":\"%s\",\"gametype\":\"%s\",\"invite\":\"%s\","
        "\"player_count\":%d,\"max_players\":%d,\"network_version\":%d,\"netcode\":\"distributed\","
        "\"open\":%s,\"in_progress\":%s,\"has_teams\":%s,\"oddball_variant\":%s%s}",
        name, game->map, game->gametype, game->invite, game->player_count, game->max_players,
        game->network_version, game->open ? "true" : "false", game->in_progress ? "true" : "false",
        game->has_teams ? "true" : "false", game->oddball_variant ? "true" : "false", score);
    return length >= 0 && length < capacity;
}
