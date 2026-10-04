/* Halo OG release discovery. This deliberately opens the platform download
   in the player's browser rather than running the old upstream self-installer. */
#include "release_discovery.h"
#include <stdio.h>
#include <string.h>

struct release_json { const unsigned char *p, *end; };

static void release_space(struct release_json *j)
{
    while (j->p < j->end && (*j->p == ' ' || *j->p == '\t' || *j->p == '\r' || *j->p == '\n')) j->p++;
}
static int release_token(struct release_json *j, unsigned char token)
{
    release_space(j);
    if (j->p == j->end || *j->p != token) return 0;
    j->p++;
    return 1;
}
static int release_hex(unsigned char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int release_string(struct release_json *j, char *out, size_t capacity)
{
    size_t length = 0;
    if (!release_token(j, '"')) return 0;
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
                    if (j->p == j->end || (digit = release_hex(*j->p++)) < 0) return 0;
                    code = (code << 4) | (unsigned)digit;
                }
                /* Known metadata is ASCII. Preserve its escaped ASCII; other
                   characters cannot become a path or an identity marker. */
                if (code == 0 && out) return 0;
                c = code < 128 ? (unsigned char)code : '?';
                break;
            default: return 0;
            }
        }
        if (out) {
            if (length + 1 >= capacity) return 0;
            out[length] = c < 128 ? (char)c : '?';
        }
        length++;
    }
    if (j->p == j->end) return 0;
    j->p++;
    if (out) out[length] = 0;
    return 1;
}
static int release_literal(struct release_json *j, const char *word)
{
    size_t length = strlen(word);
    release_space(j);
    if ((size_t)(j->end - j->p) < length || memcmp(j->p, word, length)) return 0;
    j->p += length;
    return 1;
}
static int release_number(struct release_json *j)
{
    release_space(j);
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
static int release_skip(struct release_json *j, unsigned depth)
{
    unsigned char close;
    release_space(j);
    if (depth > 16 || j->p == j->end) return 0;
    if (*j->p == '"') return release_string(j, NULL, 0);
    if (*j->p == 't') return release_literal(j, "true");
    if (*j->p == 'f') return release_literal(j, "false");
    if (*j->p == 'n') return release_literal(j, "null");
    if (*j->p != '[' && *j->p != '{') return release_number(j);
    close = *j->p++ == '[' ? ']' : '}';
    if (release_token(j, close)) return 1;
    do {
        if (close == '}' && (!release_string(j, NULL, 0) || !release_token(j, ':'))) return 0;
        if (!release_skip(j, depth + 1)) return 0;
        if (release_token(j, close)) return 1;
    } while (release_token(j, ','));
    return 0;
}
static int release_boolean(struct release_json *j, int *value)
{
    if (release_literal(j, "true")) { *value = 1; return 1; }
    if (release_literal(j, "false")) { *value = 0; return 1; }
    return 0;
}
static int release_date(const char *date)
{
    static const unsigned separators[] = {4, 7, 10, 13, 16, 19};
    static const char values[] = "--T::Z";
    unsigned month, day, year, days;
    if (strlen(date) != 20) return 0;
    for (unsigned i = 0; i < 20; i++) {
        int separator = 0;
        for (unsigned k = 0; k < 6; k++) if (i == separators[k]) {
            separator = 1;
            if (date[i] != values[k]) return 0;
        }
        if (!separator && (date[i] < '0' || date[i] > '9')) return 0;
    }
    year = (date[0]-'0')*1000 + (date[1]-'0')*100 + (date[2]-'0')*10 + date[3]-'0';
    month = (date[5]-'0')*10 + date[6]-'0';
    day = (date[8]-'0')*10 + date[9]-'0';
    if (year < 2000 || month < 1 || month > 12 || day < 1) return 0;
    days = month == 2 ? (28 + (!(year % 4) && ((year % 100) || !(year % 400)))) :
        (month == 4 || month == 6 || month == 9 || month == 11 ? 30 : 31);
    return day <= days && (date[11]-'0')*10 + date[12]-'0' < 24 &&
        (date[14]-'0')*10 + date[15]-'0' < 60 && (date[17]-'0')*10 + date[18]-'0' < 60;
}
static int release_sha(const char *sha)
{
    if (strlen(sha) != 40) return 0;
    for (unsigned i = 0; i < 40; i++)
        if (!(sha[i] >= '0' && sha[i] <= '9') && !(sha[i] >= 'a' && sha[i] <= 'f')) return 0;
    return 1;
}
static int release_tag(const char *tag)
{
    size_t length = strlen(tag);
    if (!length || length > 80) return 0;
    for (size_t i = 0; i < length; i++)
        if (!(tag[i] >= 'a' && tag[i] <= 'z') && !(tag[i] >= 'A' && tag[i] <= 'Z') &&
            !(tag[i] >= '0' && tag[i] <= '9') && tag[i] != '-' && tag[i] != '_' && tag[i] != '.') return 0;
    return tag[0] != '.';
}
static int release_body_sha(const char *body, char sha[41])
{
    const char *prefix = "https://github.com/pfista/halo-og/commit/";
    const char *match = strstr(body, prefix);
    if (!match) return 0;
    match += strlen(prefix);
    if (strlen(match) < 41 || match[40] != ')') return 0;
    memcpy(sha, match, 40); sha[40] = 0;
    if (!release_sha(sha)) return 0;
    /* Ambiguous source claims are not update identities. */
    match += 41;
    while ((match = strstr(match, prefix))) {
        match += strlen(prefix);
        if (strlen(match) < 41 || memcmp(match, sha, 40) || match[40] != ')') return 0;
        match += 41;
    }
    return 1;
}
static int release_assets(struct release_json *j, const char *asset, const char *tag, unsigned *complete)
{
    char key[64], name[128], state[32], url[256], expected[256];
    unsigned count = 0;
    *complete = 0;
    if (!release_token(j, '[')) return 0;
    if (release_token(j, ']')) return 1;
    do {
        unsigned fields = 0, bit;
        if (++count > 32 || !release_token(j, '{')) return 0;
        name[0] = state[0] = url[0] = 0;
        if (!release_token(j, '}')) do {
            if (!release_string(j, key, sizeof(key)) || !release_token(j, ':')) return 0;
            bit = 0;
            if (!strcmp(key, "name")) { bit = 1; if (!release_string(j, name, sizeof(name))) return 0; }
            else if (!strcmp(key, "state")) { bit = 2; if (!release_string(j, state, sizeof(state))) return 0; }
            else if (!strcmp(key, "browser_download_url")) { bit = 4; if (!release_string(j, url, sizeof(url))) return 0; }
            else if (!release_skip(j, 1)) return 0;
            if (fields & bit) return 0;
            fields |= bit;
            if (release_token(j, '}')) break;
            if (!release_token(j, ',')) return 0;
        } while (1);
        if (fields == 7 && !strcmp(state, "uploaded")) {
            unsigned marker = !strcmp(name, asset) ? 1 : !strcmp(name, "SHA256SUMS") ? 2 : !strcmp(name, "provenance.json") ? 4 : 0;
            if (marker) {
                snprintf(expected, sizeof(expected), "https://github.com/pfista/halo-og/releases/download/%s/%s", tag, name);
                if (strcmp(expected, url) || (*complete & marker)) return 0;
                *complete |= marker;
            }
        }
        if (release_token(j, ']')) return 1;
        if (!release_token(j, ',')) return 0;
    } while (1);
}
static int release_record(struct release_json *j, const char *asset, struct halo_release_notice *record, int *usable)
{
    char key[64], body[16384];
    unsigned fields = 0, bit, complete = 0;
    int draft = 1;
    struct release_json assets = {0};
    memset(record, 0, sizeof(*record));
    body[0] = 0; *usable = 0;
    if (!release_token(j, '{')) return 0;
    if (release_token(j, '}')) return 1;
    do {
        if (!release_string(j, key, sizeof(key)) || !release_token(j, ':')) return 0;
        bit = 0;
        if (!strcmp(key, "tag_name")) { bit = 1; if (!release_string(j, record->tag, sizeof(record->tag))) return 0; }
        else if (!strcmp(key, "created_at")) { bit = 2; if (!release_string(j, record->source_date, sizeof(record->source_date))) return 0; }
        else if (!strcmp(key, "published_at")) {
            bit = 4;
            if (!release_literal(j, "null") && !release_string(j, record->published_at, sizeof(record->published_at))) return 0;
        }
        else if (!strcmp(key, "draft")) { bit = 8; if (!release_boolean(j, &draft)) return 0; }
        else if (!strcmp(key, "body")) { bit = 16; if (!release_literal(j, "null") && !release_string(j, body, sizeof(body))) return 0; }
        else if (!strcmp(key, "assets")) {
            bit = 32; assets.p = j->p;
            if (!release_skip(j, 1)) return 0;
            assets.end = j->p;
        }
        else if (!release_skip(j, 1)) return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (release_token(j, '}')) break;
        if (!release_token(j, ',')) return 0;
    } while (1);
    if (fields != 63 || draft || !release_tag(record->tag) || !release_date(record->source_date) ||
        !release_date(record->published_at) || !release_body_sha(body, record->source_sha)) return 1;
    if (!release_assets(&assets, asset, record->tag, &complete)) return 0;
    release_space(&assets);
    if (assets.p != assets.end) return 0;
    if (complete != 7) return 1;
    snprintf(record->download_url, sizeof(record->download_url),
        "https://github.com/pfista/halo-og/releases/download/%s/%s", record->tag, asset);
    *usable = 1;
    return 1;
}
int halo_release_discovery_parse(const void *data, size_t size, const char *asset,
    const char *current_sha, const char *current_date, struct halo_release_notice *notice)
{
    struct release_json j;
    struct halo_release_notice record, candidate;
    unsigned count = 0;
    int usable, found = 0;
    if (!notice) return 0;
    memset(notice, 0, sizeof(*notice));
    if (!data || !size || size > HALO_RELEASE_DISCOVERY_BYTES || !asset || !current_sha || !current_date ||
        !release_sha(current_sha) || !release_date(current_date) ||
        (strcmp(asset, "halo-windows-release.zip") && strcmp(asset, "halo-linux-release.zip") && strcmp(asset, "Halo-OG-macos-arm64.dmg"))) return 0;
    j.p = data; j.end = j.p + size;
    if (!release_token(&j, '[')) return 0;
    if (!release_token(&j, ']')) do {
        if (++count > 5 || !release_record(&j, asset, &record, &usable)) return 0;
        if (usable && strcmp(record.source_sha, current_sha) && strcmp(record.source_date, current_date) > 0 &&
            (!found || strcmp(record.source_date, candidate.source_date) > 0)) {
            candidate = record; found = 1;
        }
        if (release_token(&j, ']')) break;
        if (!release_token(&j, ',')) return 0;
    } while (1);
    release_space(&j);
    if (j.p != j.end) return 0;
    if (found) *notice = candidate;
    return found;
}

#if HALO_OG_RELEASE_DISCOVERY && !defined(HALO_MACOS) && !defined(HALO_ANDROID) && !defined(HALO_IOS)
#include "port_config.h"
#include "update.h"
#include <SDL3/SDL.h>

#ifdef _WIN32
#define RELEASE_ASSET "halo-windows-release.zip"
#else
#define RELEASE_ASSET "halo-linux-release.zip"
#endif

extern void platform_log(const char *format, ...);
enum { release_off, release_checking, release_available, release_handled };
static SDL_AtomicInt release_state, release_main_menu;
static struct halo_release_notice release_notice;

static int SDLCALL release_check_thread(void *context)
{
    char directory[1024], path[1200], error[512] = "";
    size_t size = 0;
    char *data = NULL;
    int available = 0, length;
    (void)context;
    if (!update_make_private_temporary_directory(directory, sizeof(directory))) {
        platform_log("Halo OG updates: could not create temporary metadata directory");
        SDL_SetAtomicInt(&release_state, release_handled);
        return 0;
    }
    length = snprintf(path, sizeof(path), "%s/release-check.json", directory);
    if (length > 0 && (size_t)length < sizeof(path) &&
        update_download_limited(HALO_RELEASE_DISCOVERY_URL, path, HALO_RELEASE_DISCOVERY_BYTES,
            NULL, NULL, error, sizeof(error))) {
        data = SDL_LoadFile(path, &size);
        if (data) available = halo_release_discovery_parse(data, size, RELEASE_ASSET,
            HALO_OG_SOURCE_REVISION, HALO_OG_SOURCE_DATE, &release_notice);
    }
    else if (error[0]) platform_log("Halo OG updates: check unavailable: %s", error);
    SDL_free(data);
    update_delete_file(path);
    update_delete_file(directory);
    if (available) platform_log("Halo OG updates: %s available: %s", release_notice.tag, release_notice.download_url);
    SDL_SetAtomicInt(&release_state, available ? release_available : release_handled);
    return 0;
}

void halo_release_discovery_start(void)
{
    SDL_Thread *thread;
    if (!config_boolean("update.auto") || config_boolean("debug.hidden_window") ||
        config_boolean("debug.null_renderer") || config_real("debug.exit_after") > 0.0 ||
        config_string("debug.network_test")[0]) return;
    if (!SDL_CompareAndSwapAtomicInt(&release_state, release_off, release_checking)) return;
    thread = SDL_CreateThread(release_check_thread, "Halo OG release check", NULL);
    if (thread) SDL_DetachThread(thread);
    else SDL_SetAtomicInt(&release_state, release_handled);
}

void halo_release_discovery_set_main_menu(int safe)
{
    SDL_SetAtomicInt(&release_main_menu, safe != 0);
}

void halo_release_discovery_poll(struct SDL_Window *window)
{
    static const SDL_MessageBoxButtonData buttons[] = {
        { SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT, 1, "Open download" },
        { SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT, 0, "Later" },
        { 0, 2, "Stop checking" },
    };
    char message[400];
    int answer = 0;
    int fullscreen;
    SDL_MessageBoxData box;
    /* A modal prompt is allowed only at the original local main menu. The
       background check never pauses network simulation or an offline game. */
    if (!window || !SDL_GetAtomicInt(&release_main_menu) ||
        SDL_GetAtomicInt(&release_state) != release_available) return;
    SDL_SetAtomicInt(&release_state, release_handled);
    fullscreen = (SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN) != 0;
    if (fullscreen) SDL_SetWindowFullscreen(window, false);
    snprintf(message, sizeof(message), "Halo OG %s is available.\n\n"
        "Open the download for this platform on GitHub? Install it after quitting the game.\n\n"
        "Your maps and settings stay in their current data folders.", release_notice.tag);
    memset(&box, 0, sizeof(box));
    box.flags = SDL_MESSAGEBOX_INFORMATION;
    box.window = window;
    box.title = "Halo OG update available";
    box.message = message;
    box.numbuttons = 3;
    box.buttons = buttons;
    if (!SDL_ShowMessageBox(&box, &answer)) answer = 0;
    if (answer == 2) {
        if (!config_write_boolean("update.auto", 0))
            platform_log("Halo OG updates: could not save update.auto=false");
    }
    if (fullscreen) SDL_SetWindowFullscreen(window, true);
    if (answer == 1 && !SDL_OpenURL(release_notice.download_url))
        platform_log("Halo OG updates: could not open download: %s", SDL_GetError());
}
#else
void halo_release_discovery_start(void) {}
void halo_release_discovery_poll(struct SDL_Window *window) { (void)window; }
void halo_release_discovery_set_main_menu(int safe) { (void)safe; }
#endif
