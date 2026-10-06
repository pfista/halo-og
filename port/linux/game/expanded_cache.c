/* Select a verified, hidden full arsenal without changing a map's wire name. */
#include "cseries.h"
#include "cache/cache_files.h"
#include "custom_edition_cache.h"
#include "game/starting_equipment.h"
#include "game/weapon_sets.h"
#include "items/weapon_definitions.h"
#include "game/game_globals.h"
#include "memory/zlib/zlib.h"
#include "halo_custom_maps.h"
#include "halo_expanded_cache.h"
#include "halo_expanded_cache_weapons.h"
#include "halo_sha256.h"
#include "port_config.h"
#include <xtl.h>

static struct native_map_cache_selection pending_cache;
static int last_download_status;

struct arsenal_file_identity
{
    FILETIME changed, written;
    unsigned long low_size, high_size;
};
/* Repeated countdown/settings checks revalidate file identity, not cache bytes.
   This memo contains one verified immutable asset selection, never a variant. */
static struct
{
    int valid;
    struct native_map_cache_selection selection;
    char paths[3][256];
    struct arsenal_file_identity identities[3];
} verified_cache;
/* Download polling must not rehash the original cache every frame/second. */
static struct
{
    int valid;
    char path[256];
    struct arsenal_file_identity identity;
    unsigned char digest[32];
} original_cache;

static int file_identity(HANDLE file, struct arsenal_file_identity *identity)
{
    memset(identity, 0, sizeof(*identity));
    identity->low_size = GetFileSize(file, &identity->high_size);
    if (identity->low_size == INVALID_FILE_SIZE) {
        printf("Fiesta arsenal: file size metadata failed, error %u\n", (unsigned)GetLastError());
        return FALSE;
    }
    if (!GetFileTime(file, &identity->changed, NULL, &identity->written)) {
        printf("Fiesta arsenal: file timestamps failed, error %u\n", (unsigned)GetLastError());
        return FALSE;
    }
    return TRUE;
}
static int path_identity(char const *path, struct arsenal_file_identity *identity)
{
    HANDLE file = CreateFileA(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
    int valid;
    if (file == INVALID_HANDLE_VALUE) return FALSE;
    valid = file_identity(file, identity);
    CloseHandle(file);
    return valid;
}
static int verified_cache_reusable(char const *name, char const *manifest_path,
    char const *base_path, unsigned char const *expected)
{
    unsigned i;
    if (!verified_cache.valid || strcmp(name, verified_cache.selection.logical_name) ||
        strcmp(manifest_path, verified_cache.paths[0]) || strcmp(base_path, verified_cache.paths[1]) ||
        (expected && memcmp(expected, verified_cache.selection.sha256, 32))) return FALSE;
    for (i = 0; i < 3; i++) {
        struct arsenal_file_identity identity;
        if (!path_identity(verified_cache.paths[i], &identity) ||
            memcmp(&identity, &verified_cache.identities[i], sizeof(identity))) return FALSE;
    }
    return TRUE;
}

struct arsenal_manifest
{
    struct native_map_cache_selection selection;
    unsigned char base_sha256[32];
    unsigned long file_bytes, declared_bytes;
};
struct arsenal_json { char const *p, *end; };

static void json_space(struct arsenal_json *j)
{
    while (j->p < j->end && (*j->p == ' ' || *j->p == '\t' || *j->p == '\n' || *j->p == '\r')) j->p++;
}
static int json_token(struct arsenal_json *j, char token)
{
    json_space(j);
    if (j->p == j->end || *j->p != token) return FALSE;
    j->p++;
    return TRUE;
}
static int json_string(struct arsenal_json *j, char *out, unsigned capacity)
{
    unsigned length = 0;
    if (!json_token(j, '"')) return FALSE;
    while (j->p < j->end && *j->p != '"') {
        unsigned char c = (unsigned char)*j->p++;
        if (c < 32 || c > 126 || c == '\\' || length + 1 >= capacity) return FALSE;
        out[length++] = (char)c;
    }
    if (j->p == j->end) return FALSE;
    j->p++; out[length] = 0;
    return TRUE;
}
static int json_integer(struct arsenal_json *j, unsigned long *out)
{
    unsigned long value = 0;
    char const *begin;
    json_space(j); begin = j->p;
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') {
        unsigned digit = (unsigned)(*j->p++ - '0');
        if (value > (HALO_PORT_MULTIPLAYER_CACHE_SIZE - digit) / 10) return FALSE;
        value = value * 10 + digit;
    }
    if (begin == j->p || (j->p - begin > 1 && *begin == '0')) return FALSE;
    *out = value;
    return TRUE;
}
static int digest_from_hex(char const *text, unsigned char *digest)
{
    unsigned i;
    if (strlen(text) != 64) return FALSE;
    for (i = 0; i < 32; i++) {
        unsigned char a = (unsigned char)text[i * 2], b = (unsigned char)text[i * 2 + 1];
        if (!((a >= '0' && a <= '9') || (a >= 'a' && a <= 'f')) ||
            !((b >= '0' && b <= '9') || (b >= 'a' && b <= 'f'))) return FALSE;
        digest[i] = (unsigned char)(((a <= '9' ? a - '0' : a - 'a' + 10) << 4) |
            (b <= '9' ? b - '0' : b - 'a' + 10));
    }
    return TRUE;
}
static int manifest_parse(char const *text, unsigned length, struct arsenal_manifest *manifest)
{
    struct arsenal_json j = { text, text + length };
    unsigned fields = 0;
    char key[32], value[65];
    unsigned long integer;
    memset(manifest, 0, sizeof(*manifest));
    if (!json_token(&j, '{')) return FALSE;
    for (;;) {
        unsigned bit;
        if (!json_string(&j, key, sizeof(key)) || !json_token(&j, ':')) return FALSE;
        if (!strcmp(key, "schema_version")) { bit = 1; if (!json_integer(&j, &integer) || integer != 1) return FALSE; }
        else if (!strcmp(key, "generation")) { bit = 2; if (!json_integer(&j, &integer) || integer != HALO_EXPANDED_CACHE_GENERATION) return FALSE; manifest->selection.generation = (unsigned)integer; }
        else if (!strcmp(key, "logical_map")) { bit = 4; if (!json_string(&j, manifest->selection.logical_name, 32)) return FALSE; }
        else if (!strcmp(key, "physical_map")) { bit = 8; if (!json_string(&j, manifest->selection.physical_name, 32)) return FALSE; }
        else if (!strcmp(key, "cache_sha256")) { bit = 16; if (!json_string(&j, value, sizeof(value)) || !digest_from_hex(value, manifest->selection.sha256)) return FALSE; }
        else if (!strcmp(key, "base_sha256")) { bit = 32; if (!json_string(&j, value, sizeof(value)) || !digest_from_hex(value, manifest->base_sha256)) return FALSE; }
        else if (!strcmp(key, "weapon_list_sha256")) { bit = 64; if (!json_string(&j, value, sizeof(value)) || !digest_from_hex(value, manifest->selection.weapon_list_sha256)) return FALSE; }
        else if (!strcmp(key, "cache_file_bytes")) { bit = 128; if (!json_integer(&j, &manifest->file_bytes) || manifest->file_bytes < 2048) return FALSE; }
        else if (!strcmp(key, "cache_declared_bytes")) { bit = 256; if (!json_integer(&j, &manifest->declared_bytes) || manifest->declared_bytes < 2048) return FALSE; }
        else return FALSE;
        if (fields & bit) return FALSE;
        fields |= bit;
        if (json_token(&j, '}')) break;
        if (!json_token(&j, ',')) return FALSE;
    }
    json_space(&j);
    manifest->selection.expanded = TRUE;
    return fields == 511 && j.p == j.end;
}
static unsigned long cache_u32(unsigned char const *p)
{
    return (unsigned long)p[0] | (unsigned long)p[1] << 8 | (unsigned long)p[2] << 16 | (unsigned long)p[3] << 24;
}
static int arsenal_path(char const *root, char const *physical, char const *extension, char *path, unsigned capacity)
{
    int length = snprintf(path, capacity, "%sarsenal\\v1\\%s.%s", root, physical, extension);
    return length >= 0 && (unsigned)length < capacity;
}
static int file_hash(HANDLE file, unsigned char digest[32], unsigned long expected)
{
    struct sha256 hash;
    unsigned char bytes[16384];
    unsigned long size, total = 0;
    if (SetFilePointer(file, 0, NULL, FILE_BEGIN) == INVALID_SET_FILE_POINTER) return FALSE;
    sha256_begin(&hash);
    for (;;) {
        if (!ReadFile(file, bytes, sizeof(bytes), &size, NULL) || size > sizeof(bytes) ||
            size > HALO_PORT_MULTIPLAYER_CACHE_SIZE - total) return FALSE;
        if (!size) break;
        total += size; sha256_add(&hash, bytes, (int)size);
    }
    sha256_end(&hash, digest);
    return expected ? total == expected : total >= 2048;
}
static void digest_to_hex(unsigned char const digest[32], char text[65])
{
    static char const hex[] = "0123456789abcdef";
    unsigned i;
    for (i = 0; i < 32; i++) { text[i * 2] = hex[digest[i] >> 4]; text[i * 2 + 1] = hex[digest[i] & 15]; }
    text[64] = 0;
}
static int original_hash(char const *path, unsigned char digest[32], struct arsenal_file_identity *identity)
{
    struct arsenal_file_identity after;
    HANDLE file;
    int valid;
    if (!path_identity(path, identity)) return FALSE;
    if (original_cache.valid && !strcmp(path, original_cache.path) &&
        !memcmp(identity, &original_cache.identity, sizeof(*identity))) {
        memcpy(digest, original_cache.digest, 32); return TRUE;
    }
    original_cache.valid = FALSE;
    file = CreateFileA(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return FALSE;
    valid = file_hash(file, digest, 0);
    CloseHandle(file);
    if (!valid || !path_identity(path, &after) || memcmp(identity, &after, sizeof(after))) return FALSE;
    strcpy(original_cache.path, path); original_cache.identity = *identity;
    memcpy(original_cache.digest, digest, 32); original_cache.valid = TRUE;
    return TRUE;
}
static unsigned char const *arena_pointer(unsigned char const *arena, unsigned long length,
    unsigned long pointer, unsigned long required)
{
    unsigned long offset;
    if (pointer < 0x803A6000UL) return NULL;
    offset = pointer - 0x803A6000UL;
    return offset <= length && required <= length - offset ? arena + offset : NULL;
}
/* Use the pinned identities and the same player-weapon fields as the engine.
   A stale partial pack cannot acquire global status from manifest text alone. */
static int arsenal_tags_valid(unsigned char const *arena, unsigned long length)
{
    unsigned long count, i;
    unsigned char const *table;
    int found[NUMBEROF(native_expanded_cache_weapon_names)] = { 0 };
    int player_found = FALSE, player_referenced = FALSE;
    unsigned long player_index = 0;
    if (length < 40) return FALSE;
    count = cache_u32(arena + 12);
    if (!count || count > 32767) return FALSE;
    table = arena_pointer(arena, length, cache_u32(arena), count * 32);
    if (!table) return FALSE;
    for (i = 0; i < count; i++) {
        unsigned char const *tag = table + i * 32;
        char const *name = (char const *)arena_pointer(arena, length, cache_u32(tag + 16), 1);
        unsigned j;
        if (!name || !memchr(name, 0, (unsigned)(arena + length - (unsigned char const *)name))) return FALSE;
        if (cache_u32(tag) == (unsigned long)'bipd' && !strcmp(name, "community\\weapon_pack\\player\\cyborg")) {
            player_found = TRUE; player_index = cache_u32(tag + 12);
        }
        if (cache_u32(tag) != (unsigned long)'weap') continue;
        for (j = 0; j < NUMBEROF(native_expanded_cache_weapon_names); j++) {
            if (!strcmp(name, native_expanded_cache_weapon_names[j])) {
                unsigned char const *definition = arena_pointer(arena, length, cache_u32(tag + 20), sizeof(struct weapon_definition));
                unsigned long flags;
                if (!definition || found[j] || definition[0] != 2 || definition[1] != 0) return FALSE;
                flags = cache_u32(definition + offsetof(struct weapon_definition, weapon.flags));
                if (flags & ((1u << _weapon_must_be_readied_bit) | (1u << _weapon_doesnt_count_toward_maximum_bit)) ||
                    cache_u32(definition + offsetof(struct weapon_definition, weapon.interface_definition.first_person_model.index)) == 0xffffffffUL ||
                    cache_u32(definition + offsetof(struct weapon_definition, weapon.interface_definition.first_person_animations.index)) == 0xffffffffUL) return FALSE;
                found[j] = TRUE;
            }
        }
    }
    for (i = 0; i < NUMBEROF(found); i++) if (!found[i]) return FALSE;
    if (!player_found) return FALSE;
    for (i = 0; i < count; i++) {
        unsigned char const *tag = table + i * 32;
        if (cache_u32(tag) == (unsigned long)'matg') {
            unsigned char const *globals = arena_pointer(arena, length, cache_u32(tag + 20), sizeof(struct game_globals));
            unsigned char const *player;
            if (!globals || cache_u32(globals + offsetof(struct game_globals, multiplayer_information.count)) != 1) continue;
            player = arena_pointer(arena, length, cache_u32(globals + offsetof(struct game_globals, multiplayer_information.address)), sizeof(struct game_globals_multiplayer_information));
            if (player && cache_u32(player + offsetof(struct game_globals_multiplayer_information, unit.index)) == player_index) player_referenced = TRUE;
        }
    }
    return player_referenced;
}
static int arsenal_arena_valid(HANDLE file, unsigned char const *header, unsigned long file_bytes)
{
    unsigned long offset = cache_u32(header + 16), size = cache_u32(header + 20), declared = cache_u32(header + 8);
    unsigned char *arena;
    int valid = FALSE;
    if (size < 40 || size > 22UL * 1024 * 1024 || offset < 2048 ||
        offset > declared || size > declared - offset) return FALSE;
    arena = malloc(size);
    if (!arena) return FALSE;
    if (file_bytes == declared) {
        unsigned long read;
        if (SetFilePointer(file, (long)offset, NULL, FILE_BEGIN) != INVALID_SET_FILE_POINTER &&
            ReadFile(file, arena, size, &read, NULL) && read == size) valid = TRUE;
    } else {
        z_stream stream;
        unsigned char input[16384], output[16384];
        unsigned long position = 2048, copied = 0, read;
        int status = Z_OK;
        memset(&stream, 0, sizeof(stream));
        if (SetFilePointer(file, 2048, NULL, FILE_BEGIN) != INVALID_SET_FILE_POINTER && inflateInit(&stream) == Z_OK) {
            while (status == Z_OK) {
                unsigned long produced, start, end;
                if (!stream.avail_in) {
                    if (!ReadFile(file, input, sizeof(input), &read, NULL) || !read) break;
                    stream.next_in = input; stream.avail_in = (uInt)read;
                }
                stream.next_out = output; stream.avail_out = sizeof(output);
                status = inflate(&stream, Z_NO_FLUSH);
                produced = sizeof(output) - stream.avail_out;
                if (produced > declared - position) break;
                start = MAX(position, offset); end = MIN(position + produced, offset + size);
                if (end > start) { memcpy(arena + start - offset, output + start - position, end - start); copied += end - start; }
                position += produced;
            }
            valid = status == Z_STREAM_END && position == declared && copied == size;
            inflateEnd(&stream);
        }
    }
    if (valid) valid = arsenal_tags_valid(arena, size);
    free(arena);
    return valid;
}
int native_map_cache_uses_global_arsenal(struct game_variant const *variant)
{
    return game_variant_uses_expanded_weapon_set(variant) &&
        starting_equipment_get(variant) == _starting_equipment_fiesta;
}
int native_map_cache_physical_name(char const *logical, char physical[32])
{
    char normalized[32];
    unsigned i, length = (unsigned)strlen(logical);
    if (!length || length >= sizeof(normalized)) return FALSE;
    for (i = 0; i < length; i++) {
        unsigned char c = (unsigned char)logical[i];
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == ' ')) return FALSE;
        normalized[i] = (char)c;
    }
    normalized[length] = 0;
    if (length <= 23) snprintf(physical, 32, "_fiesta_%s", normalized);
    else {
        struct sha256 hash;
        unsigned char digest[32];
        static char const hex[] = "0123456789abcdef";
        sha256_begin(&hash); sha256_add(&hash, normalized, (int)length); sha256_end(&hash, digest);
        memcpy(physical, "_fiestah_", 9);
        for (i = 0; i < 8; i++) {
            physical[9 + i * 2] = hex[digest[i] >> 4];
            physical[10 + i * 2] = hex[digest[i] & 15];
        }
        physical[25] = 0;
    }
    return TRUE;
}
/* A candidate is always a complete pair in one root. A managed manifest must
   never certify a data-root cache (or vice versa). */
static int arsenal_candidate(char const *root, char const *name, char const *physical,
    char const *base_path, unsigned char const base_digest[32],
    struct arsenal_file_identity const *base_identity, unsigned char const *expected,
    struct native_map_cache_selection *selection, char const **reason)
{
    char filename[40], path[256], manifest_text[4097];
    struct arsenal_manifest manifest;
    unsigned char digest[32], pinned[32], header[2048];
    char validated_paths[3][256];
    struct arsenal_file_identity identities[3], after;
    unsigned long read;
    HANDLE file = INVALID_HANDLE_VALUE;
    *reason = "The arsenal manifest could not be opened or read.";
    if (!arsenal_path(root, physical, "json", path, sizeof(path))) goto failed;
    if (verified_cache_reusable(name, path, base_path, expected)) {
        *selection = verified_cache.selection; return TRUE;
    }
    strcpy(validated_paths[0], path);
    file = CreateFileA(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) goto failed;
    *reason = "The arsenal manifest file metadata could not be read.";
    if (!file_identity(file, &identities[0])) goto failed;
    *reason = "The arsenal manifest data could not be read or exceeds its size limit.";
    read = 0;
    if (!ReadFile(file, manifest_text, 4097, &read, NULL) || !read || read > 4096) goto failed;
    CloseHandle(file); file = INVALID_HANDLE_VALUE;
    *reason = "The arsenal manifest has a different map, generation, or weapon catalog.";
    if (!manifest_parse(manifest_text, (unsigned)read, &manifest) ||
        strcmp(name, manifest.selection.logical_name) || strcmp(physical, manifest.selection.physical_name) ||
        !digest_from_hex(HALO_EXPANDED_CACHE_WEAPON_LIST_SHA256, pinned) || memcmp(pinned, manifest.selection.weapon_list_sha256, 32)) goto failed;
    *reason = "This map differs from the original map used to build its full weapon arsenal.";
    if (memcmp(base_digest, manifest.base_sha256, 32)) goto failed;
    *reason = "This arsenal revision differs from the full cache offered by the host.";
    if (expected && memcmp(expected, manifest.selection.sha256, 32)) goto failed;
    strcpy(validated_paths[1], base_path); identities[1] = *base_identity;
    *reason = "The arsenal cache header is missing or incompatible.";
    if (!arsenal_path(root, physical, "map", path, sizeof(path))) goto failed;
    strcpy(validated_paths[2], path);
    file = CreateFileA(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
    snprintf(filename, sizeof(filename), "%s.map", physical);
    if (file == INVALID_HANDLE_VALUE || !file_identity(file, &identities[2]) ||
        !ReadFile(file, header, sizeof(header), &read, NULL) || read != sizeof(header) ||
        !native_map_header_valid(header, filename)) goto failed;
    *reason = "The arsenal cache size or SHA-256 does not match its manifest.";
    if (cache_u32(header + 8) != manifest.declared_bytes ||
        !file_hash(file, digest, manifest.file_bytes) || memcmp(digest, manifest.selection.sha256, 32)) goto failed;
    *reason = "The arsenal cache tag data is incomplete or has incompatible weapons or player references.";
    if (!arsenal_arena_valid(file, header, manifest.file_bytes)) goto failed;
    CloseHandle(file); file = INVALID_HANDLE_VALUE;
    *reason = "The map or arsenal files changed while being verified.";
    {
        unsigned i;
        for (i = 0; i < 3; i++)
            if (!path_identity(validated_paths[i], &after) || memcmp(&after, &identities[i], sizeof(after))) goto failed;
    }
    strcpy(manifest.selection.physical_path, validated_paths[2]);
    verified_cache.selection = manifest.selection;
    memcpy(verified_cache.paths, validated_paths, sizeof(validated_paths));
    memcpy(verified_cache.identities, identities, sizeof(identities));
    verified_cache.valid = TRUE;
    *selection = manifest.selection;
    return TRUE;
failed:
    if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
    return FALSE;
}
int native_map_cache_prepare_expected(char const *map, struct game_variant const *variant,
    unsigned char const *expected_sha256, struct native_map_cache_selection *selection,
    int show_error)
{
    char const *name = native_map_basename(map);
    char physical[32], base_path[256], base_hex[65], expected_hex[65];
    unsigned char base_digest[32];
    struct arsenal_file_identity base_identity;
    char const *reason = "The full weapon arsenal for this map is missing or incomplete.";
    unsigned pass;
    last_download_status = 0;
    if (!selection) return FALSE;
    memset(selection, 0, sizeof(*selection));
    if (custom_edition_level_name(map)) {
        /* CE owns its tags and full level-name namespace. Xbox arsenal caches
           may share a leaf name, but cannot replace this map's weapon data. */
        if (native_map_cache_uses_global_arsenal(variant) || expected_sha256) {
            if (show_error) {
                void platform_show_message(char const *, char const *);
                platform_show_message("Halo: weapon arsenal unavailable",
                    "Custom Edition maps use their own weapon tags. Select a standard weapon set; Halo OG full arsenal caches apply to Xbox maps.");
            }
            return FALSE;
        }
        if (strlen(map) >= sizeof(selection->physical_path)) return FALSE;
        snprintf(selection->logical_name, sizeof(selection->logical_name), "%s", name);
        strcpy(selection->physical_name, selection->logical_name);
        strcpy(selection->physical_path, map);
        last_download_status = 1;
        return TRUE;
    }
    if (strlen(name) >= sizeof(selection->logical_name)) goto failed;
    strcpy(selection->logical_name, name); strcpy(selection->physical_name, name);
    if (!native_map_cache_uses_global_arsenal(variant)) { last_download_status = 1; return TRUE; }
    if (!native_map_cache_physical_name(name, physical)) goto failed;
    {
        unsigned i;
        for (i = 0; selection->logical_name[i]; i++)
            if (selection->logical_name[i] >= 'A' && selection->logical_name[i] <= 'Z') selection->logical_name[i] += 'a' - 'A';
        name = selection->logical_name;
    }
    reason = "The original map could not be opened or verified. Install it before requesting its weapon arsenal.";
    if (!native_map_get_original_path(map, base_path, sizeof(base_path)) ||
        !original_hash(base_path, base_digest, &base_identity)) {
        /* The ordinary managed-map service may already be obtaining geometry.
           Its completion precedes the arsenal request and original SHA memo. */
        if (native_map_download_pending(map) == 2) last_download_status = 2;
        goto failed;
    }
    digest_to_hex(base_digest, base_hex);
    expected_hex[0] = 0;
    if (expected_sha256) digest_to_hex(expected_sha256, expected_hex);
    /* First check local pairs, even with downloads disabled/offline. A READY
       service response merely permits a second validation pass, never loading. */
    for (pass = 0; pass < 2; pass++) {
        if (arsenal_candidate(cache_files_map_directory(), name, physical, base_path,
            base_digest, &base_identity, expected_sha256, selection, &reason)) {
            last_download_status = 1; return TRUE;
        }
#ifdef HALO_MACOS
        {
            char directory[1024];
            if (halo_map_download_directory(directory, sizeof(directory)) &&
                arsenal_candidate("m:\\", name, physical, base_path, base_digest,
                    &base_identity, expected_sha256, selection, &reason)) {
                last_download_status = 1; return TRUE;
            }
        }
#endif
        if (pass) { last_download_status = -1; break; }
        last_download_status = halo_arsenal_download_request(name, base_hex, expected_hex);
        if (last_download_status != 1) break;
    }
failed:
    if (show_error) {
        char message[512];
        void platform_show_message(char const *, char const *);
        if (last_download_status == 2)
            snprintf(message, sizeof(message), "Downloading the full weapon arsenal for %s. Your current map and game type are unchanged.\n\nSelect this map or game type again when the download finishes.", name[0] ? name : "the selected map");
        else {
#ifdef HALO_MACOS
            char const *retry = "Enable map downloads in Settings and use Check Maps to retry, then select this map or game type again.";
#else
            char const *retry = "Select this map or game type again to retry when downloads are available, or install the complete matching arsenal manually.";
#endif
            snprintf(message, sizeof(message), "%s\n\n%s", reason, retry);
        }
        platform_show_message(last_download_status == 2 ? "Halo: downloading Fiesta arsenal" : "Halo: Fiesta arsenal unavailable", message);
    }
    memset(selection, 0, sizeof(*selection));
    return FALSE;
}
int native_map_cache_prepare(char const *map, struct game_variant const *variant,
    struct native_map_cache_selection *selection, int show_error)
{
    return native_map_cache_prepare_expected(map, variant, NULL, selection, show_error);
}
int native_map_cache_download_status(void) { return last_download_status; }
void native_map_cache_select(struct native_map_cache_selection const *selection)
{
    if (selection) pending_cache = *selection;
    else memset(&pending_cache, 0, sizeof(pending_cache));
}
struct native_map_cache_selection const *native_map_cache_current(void) { return &pending_cache; }
char const *native_map_cache_resolve(char const *map)
{
    char const *name = native_map_basename(map);
    if (custom_edition_level_name(map)) return map;
    return pending_cache.expanded && !_stricmp(name, pending_cache.logical_name) ? pending_cache.physical_name : name;
}
int native_map_cache_selection_equal(struct native_map_cache_selection const *a,
    struct native_map_cache_selection const *b)
{
    return a && b && a->expanded == b->expanded && a->generation == b->generation &&
        (a->expanded || !strcmp(a->physical_path, b->physical_path)) &&
        !strcmp(a->logical_name, b->logical_name) && !strcmp(a->physical_name, b->physical_name) &&
        !memcmp(a->sha256, b->sha256, 32) && !memcmp(a->weapon_list_sha256, b->weapon_list_sha256, 32);
}
