/* Desktop full-map prefetch. Compiled with the host ABI, like posix_update.c;
   only scalar declarations cross into the game. Mac/Android use their own UI.
   This downloads complete Xbox caches, not stripped community packages. */
#include "community_maps_download.h"

#if defined(HALO_ANDROID) || defined(HALO_MACOS)
void community_maps_download_start(void) {}
#ifdef HALO_ANDROID
int halo_arsenal_download_request(const char *logical_map,
    const char *base_sha256_hex, const char *cache_sha256_hex)
{
    (void)logical_map; (void)base_sha256_hex; (void)cache_sha256_hex;
    return 0;
}
#endif
#else

#include "port_config.h"
#include "update.h"
#include <SDL3/SDL.h>
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../include/halo_sha256.h"
#ifdef _WIN32
#include <windows.h>
#include <aclapi.h>
#include <bcrypt.h>
#else
#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include "mbedtls/sha256.h"
#endif

extern const char *platform_data_root(void);
extern void platform_log(const char *format, ...);

#define CATALOG_URL "https://dl.oghalo.com/catalogs/testing/current.json"
#define OBJECT_ORIGIN "https://dl.oghalo.com/"
#define NTSC_BUILD "01.10.12.2276"
#define MAX_CATALOG_BYTES (1024u * 1024u)
#define MAX_MAP_BYTES (128u * 1024u * 1024u)
#define MAX_TAG_BYTES (22u * 1024u * 1024u)
#define MAX_MAPS 115
#define MAX_BATCH_BYTES (2ULL * 1024 * 1024 * 1024)
#define PATH_BYTES 1024

struct map_entry { char id[32], sha256[65], object_key[128]; unsigned long long bytes; };
struct catalog { struct map_entry entries[MAX_MAPS]; unsigned count; };
struct json { const unsigned char *p, *end; };
static SDL_AtomicInt started;

static int join_path(char *out, size_t capacity, const char *root, const char *name)
{
    int length = snprintf(out, capacity, "%s/%s", root, name);
    return length >= 0 && (size_t)length < capacity;
}
static int equal_case(const char *a, const char *b)
{
    while (*a && *b) {
        if (tolower((unsigned char)*a++) != tolower((unsigned char)*b++)) return 0;
    }
    return *a == *b;
}
static int safe_id(const char *id)
{
    static const char *reserved[] = { "ui", "a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40",
        "beavercreek", "sidewinder", "damnation", "ratrace", "prisoner", "hangemhigh", "chillout", "carousel",
        "boardingaction", "bloodgulch", "wizard", "putput", "longest", "con", "prn", "aux", "nul" };
    size_t length = strlen(id), i;
    if (!length || length > 31 || id[length - 1] == ' ' ||
        !((id[0] >= 'a' && id[0] <= 'z') || (id[0] >= '0' && id[0] <= '9'))) return 0;
    for (i = 0; i < length; i++)
        if (!((id[i] >= 'a' && id[i] <= 'z') || (id[i] >= '0' && id[i] <= '9') ||
              id[i] == '_' || id[i] == '-' || id[i] == ' ')) return 0;
    for (i = 0; i < sizeof(reserved) / sizeof(*reserved); i++) if (!strcmp(id, reserved[i])) return 0;
    if (length == 4 && (!strncmp(id, "com", 3) || !strncmp(id, "lpt", 3)) && id[3] >= '1' && id[3] <= '9') return 0;
    return 1;
}

/* A deliberately narrow JSON reader: the public schema is ASCII, has no
   escaped strings, unknown fields or nested extensions. Reject duplicates,
   floats, booleans-as-integers and trailing bytes instead of guessing. */
static void whitespace(struct json *j)
{ while (j->p < j->end && (*j->p == ' ' || *j->p == '\t' || *j->p == '\r' || *j->p == '\n')) j->p++; }
static int token(struct json *j, unsigned char c)
{ whitespace(j); if (j->p == j->end || *j->p != c) return 0; j->p++; return 1; }
static int string(struct json *j, char *out, size_t capacity)
{
    size_t length = 0;
    if (!token(j, '"')) return 0;
    while (j->p < j->end && *j->p != '"') {
        unsigned char c = *j->p++;
        if (c < 32 || c > 126 || c == '\\' || length + 1 >= capacity) return 0;
        out[length++] = (char)c;
    }
    if (j->p == j->end) return 0;
    j->p++; out[length] = 0; return 1;
}
static int integer(struct json *j, unsigned long long *out)
{
    unsigned long long value = 0;
    const unsigned char *begin;
    whitespace(j); begin = j->p;
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') {
        unsigned digit = *j->p++ - '0';
        if (value > (MAX_BATCH_BYTES - digit) / 10) return 0;
        value = value * 10 + digit;
    }
    if (begin == j->p || (j->p - begin > 1 && *begin == '0')) return 0;
    *out = value; return 1;
}
static int json_boolean(struct json *j)
{
    whitespace(j);
    if (j->end - j->p >= 4 && !memcmp(j->p, "true", 4)) { j->p += 4; return 1; }
    if (j->end - j->p >= 5 && !memcmp(j->p, "false", 5)) { j->p += 5; return 1; }
    return 0;
}
static int map_object(struct json *j, struct map_entry *entry)
{
    unsigned fields = 0;
    char key[32], value[128], expected[128];
    unsigned long long number;
    memset(entry, 0, sizeof(*entry));
    if (!token(j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(j, key, sizeof(key)) || !token(j, ':')) return 0;
        if (!strcmp(key, "id")) { bit = 1; if (!string(j, entry->id, sizeof(entry->id))) return 0; }
        else if (!strcmp(key, "sha256")) { bit = 2; if (!string(j, entry->sha256, sizeof(entry->sha256))) return 0; }
        else if (!strcmp(key, "object_key")) { bit = 4; if (!string(j, entry->object_key, sizeof(entry->object_key))) return 0; }
        else if (!strcmp(key, "cache_build")) { bit = 8; if (!string(j, value, sizeof(value)) || strcmp(value, NTSC_BUILD)) return 0; }
        else if (!strcmp(key, "file_bytes")) { bit = 16; if (!integer(j, &entry->bytes) || entry->bytes < 2048 || entry->bytes > MAX_MAP_BYTES) return 0; }
        else if (!strcmp(key, "cache_version")) { bit = 32; if (!integer(j, &number) || number != 5) return 0; }
        else if (!strcmp(key, "scenario_type")) { bit = 64; if (!integer(j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "prefetch")) { bit = 128; if (!json_boolean(j)) return 0; }
        else return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (token(j, '}')) break;
        if (!token(j, ',')) return 0;
    }
    if ((fields & 127) != 127 || !safe_id(entry->id) || strlen(entry->sha256) != 64) return 0;
    for (unsigned i = 0; i < 64; i++)
        if (!((entry->sha256[i] >= '0' && entry->sha256[i] <= '9') || (entry->sha256[i] >= 'a' && entry->sha256[i] <= 'f'))) return 0;
    snprintf(expected, sizeof(expected), "maps/sha256/%s/%s.map", entry->sha256, entry->id);
    return !strcmp(expected, entry->object_key);
}
static int parse_catalog(const unsigned char *data, size_t size, struct catalog *catalog)
{
    struct json j = { data, data + size };
    unsigned fields = 0;
    unsigned long long number, total = 0;
    char key[32], value[32];
    memset(catalog, 0, sizeof(*catalog));
    if (size > MAX_CATALOG_BYTES || !token(&j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(&j, key, sizeof(key)) || !token(&j, ':')) return 0;
        if (!strcmp(key, "schema_version")) { bit = 1; if (!integer(&j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "profile")) { bit = 2; if (!string(&j, value, sizeof(value)) || strcmp(value, "stock-xbox-ntsc")) return 0; }
        else if (!strcmp(key, "maps")) {
            bit = 4;
            if (!token(&j, '[')) return 0;
            if (!token(&j, ']')) for (;;) {
                struct map_entry *entry;
                if (catalog->count == MAX_MAPS) return 0;
                entry = &catalog->entries[catalog->count];
                if (!map_object(&j, entry)) return 0;
                for (unsigned i = 0; i < catalog->count; i++) if (!strcmp(catalog->entries[i].id, entry->id)) return 0;
                if ((total += entry->bytes) > MAX_BATCH_BYTES) return 0;
                catalog->count++;
                if (token(&j, ']')) break;
                if (!token(&j, ',')) return 0;
            }
        } else return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (token(&j, '}')) break;
        if (!token(&j, ',')) return 0;
    }
    whitespace(&j);
    return fields == 7 && j.p == j.end;
}

#ifdef _WIN32
typedef HANDLE file_handle;
#define BAD_FILE INVALID_HANDLE_VALUE
static int wide_path(const char *path, wchar_t *wide)
{ return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, PATH_BYTES) > 0; }
static int path_kind(const char *path)
{
    wchar_t wide[PATH_BYTES]; DWORD attributes;
    if (!wide_path(path, wide)) return -1;
    attributes = GetFileAttributesW(wide);
    if (attributes == INVALID_FILE_ATTRIBUTES)
        return GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND ? 0 : -1;
    if (attributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)) return -1;
    return attributes & FILE_ATTRIBUTE_DIRECTORY ? 2 : 1;
}
static int make_directory(const char *path)
{
    wchar_t wide[PATH_BYTES]; HANDLE token = NULL; DWORD size = 0;
    TOKEN_USER *user = NULL; PACL acl = NULL; int result = 0;
    SECURITY_DESCRIPTOR descriptor; EXPLICIT_ACCESSW access;
    SECURITY_ATTRIBUTES attributes = { sizeof(attributes), &descriptor, FALSE };
    /* A maps folder can be shared. Protect our fresh temporary subtree so the
       transport's path-only API cannot be redirected by another local user. */
    if (!wide_path(path, wide) || !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) goto done;
    GetTokenInformation(token, TokenUser, NULL, 0, &size);
    if (!size || size > 65536 || !(user = malloc(size)) || !GetTokenInformation(token, TokenUser, user, size, &size)) goto done;
    memset(&access, 0, sizeof(access));
    access.grfAccessPermissions = FILE_ALL_ACCESS; access.grfAccessMode = SET_ACCESS;
    access.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
    access.Trustee.TrusteeForm = TRUSTEE_IS_SID; access.Trustee.TrusteeType = TRUSTEE_IS_USER;
    access.Trustee.ptstrName = (LPWSTR)user->User.Sid;
    if (SetEntriesInAclW(1, &access, NULL, &acl) != ERROR_SUCCESS ||
        !InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) ||
        !SetSecurityDescriptorDacl(&descriptor, TRUE, acl, FALSE) ||
        !SetSecurityDescriptorControl(&descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED)) goto done;
    result = CreateDirectoryW(wide, &attributes);
done:
    if (acl) LocalFree(acl);
    free(user); if (token) CloseHandle(token); return result;
}
static void remove_file(const char *path)
{ wchar_t wide[PATH_BYTES]; if (wide_path(path, wide)) DeleteFileW(wide); }
static void remove_directory(const char *path)
{ wchar_t wide[PATH_BYTES]; if (wide_path(path, wide)) RemoveDirectoryW(wide); }
static file_handle read_open(const char *path)
{
    wchar_t wide[PATH_BYTES]; BY_HANDLE_FILE_INFORMATION info;
    if (!wide_path(path, wide)) return BAD_FILE;
    HANDLE file = CreateFileW(wide, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (file != BAD_FILE && (!GetFileInformationByHandle(file, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_DEVICE)))) {
        CloseHandle(file); return BAD_FILE;
    }
    return file;
}
static int file_size(file_handle file, unsigned long long *size)
{ LARGE_INTEGER value; if (!GetFileSizeEx(file, &value) || value.QuadPart < 0) return 0; *size = value.QuadPart; return 1; }
static int read_bytes(file_handle file, unsigned char *bytes, unsigned count)
{ DWORD received; return ReadFile(file, bytes, count, &received, NULL) ? (int)received : -1; }
static void file_close(file_handle file) { CloseHandle(file); }
static int sync_file(const char *path)
{
    wchar_t wide[PATH_BYTES]; int result; HANDLE file;
    if (!wide_path(path, wide)) return 0;
    file = CreateFileW(wide, GENERIC_WRITE, 0, NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (file == BAD_FILE) return 0;
    result = FlushFileBuffers(file); CloseHandle(file); return result;
}
static int publish_file(const char *source, const char *target)
{
    wchar_t wide_source[PATH_BYTES], wide_target[PATH_BYTES];
    /* Same-volume rename works on FAT/exFAT too. No REPLACE_EXISTING flag:
       a racing target always wins, even an exact matching file. */
    return wide_path(source, wide_source) && wide_path(target, wide_target) && MoveFileExW(wide_source, wide_target, 0);
}
#else
typedef int file_handle;
#define BAD_FILE -1
static int path_kind(const char *path)
{
    struct stat info;
    if (lstat(path, &info)) return errno == ENOENT ? 0 : -1;
    return S_ISREG(info.st_mode) ? 1 : S_ISDIR(info.st_mode) ? 2 : -1;
}
static int make_directory(const char *path) { return mkdir(path, 0700) == 0; }
static void remove_file(const char *path) { unlink(path); }
static void remove_directory(const char *path) { rmdir(path); }
static file_handle read_open(const char *path)
{
    struct stat info;
    int file = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (file >= 0 && (fstat(file, &info) || !S_ISREG(info.st_mode))) { close(file); return BAD_FILE; }
    return file;
}
static int file_size(file_handle file, unsigned long long *size)
{ struct stat info; if (fstat(file, &info) || info.st_size < 0) return 0; *size = (unsigned long long)info.st_size; return 1; }
static int read_bytes(file_handle file, unsigned char *bytes, unsigned count) { return (int)read(file, bytes, count); }
static void file_close(file_handle file) { close(file); }
static int sync_file(const char *path)
{
    struct stat info; int file = open(path, O_WRONLY | O_NOFOLLOW | O_NONBLOCK), result;
    if (file < 0) return 0;
    result = !fstat(file, &info) && S_ISREG(info.st_mode) && fsync(file) == 0;
    close(file); return result;
}
static int publish_file(const char *source, const char *target) { return link(source, target) == 0; }
#endif

/* Existing directories may use the Xbox's case-insensitive spelling. Reject
   ambiguous aliases and all links/reparse points before any write. */
static int find_child(const char *parent, const char *name, char *out, size_t capacity)
{
    int found = 0;
#ifdef _WIN32
    char pattern[PATH_BYTES], narrow[PATH_BYTES]; wchar_t wide[PATH_BYTES]; WIN32_FIND_DATAW data;
    if (!join_path(pattern, sizeof(pattern), parent, "*") || !wide_path(pattern, wide)) return -1;
    HANDLE search = FindFirstFileW(wide, &data);
    if (search == INVALID_HANDLE_VALUE) return -1;
    do {
        if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, data.cFileName, -1, narrow, sizeof(narrow), NULL, NULL)) { found = -1; break; }
        if (equal_case(narrow, name)) {
            if (found || !join_path(out, capacity, parent, narrow) || path_kind(out) < 1) { found = -1; break; }
            found = 1;
        }
    } while (FindNextFileW(search, &data));
    if (found >= 0 && GetLastError() != ERROR_NO_MORE_FILES) found = -1;
    FindClose(search);
#else
    DIR *directory = opendir(parent); struct dirent *item;
    if (!directory) return -1;
    errno = 0;
    while ((item = readdir(directory))) {
        if (equal_case(item->d_name, name)) {
            if (found || !join_path(out, capacity, parent, item->d_name) || path_kind(out) < 1) { found = -1; break; }
            found = 1;
        }
    }
    if (!item && errno) found = -1;
    closedir(directory);
#endif
    return found;
}
static int real_directory_chain(const char *path)
{
    char absolute[PATH_BYTES]; size_t begin = 1;
#ifdef _WIN32
    wchar_t input[PATH_BYTES], full[PATH_BYTES];
    DWORD length;
    if (!wide_path(path, input) || !(length = GetFullPathNameW(input, PATH_BYTES, full, NULL)) || length >= PATH_BYTES ||
        !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, full, -1, absolute, sizeof(absolute), NULL, NULL)) return 0;
    /* Refuse device/UNC namespaces rather than interpreting network aliases. */
    if (!isalpha((unsigned char)absolute[0]) || absolute[1] != ':' || (absolute[2] != '/' && absolute[2] != '\\')) return 0;
    begin = 3;
#else
    if (path[0] == '/') { if (strlen(path) >= sizeof(absolute)) return 0; strcpy(absolute, path); }
    else {
        char cwd[PATH_BYTES]; if (!getcwd(cwd, sizeof(cwd)) || !join_path(absolute, sizeof(absolute), cwd, path)) return 0;
    }
#endif
    for (size_t i = begin; ; i++) {
        if (!absolute[i] || absolute[i] == '/' || absolute[i] == '\\') {
            char separator = absolute[i]; absolute[i] = 0;
            if (path_kind(absolute) != 2) return 0;
            absolute[i] = separator; if (!separator) break;
        }
    }
    return 1;
}
static uint32_t little32(const unsigned char *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static int valid_header(const unsigned char *h, const char *id, unsigned type, int limits)
{
    uint32_t declared = little32(h + 8), offset = little32(h + 16), tags = little32(h + 20);
    return !memcmp(h, "daeh", 4) && !memcmp(h + 2044, "toof", 4) && little32(h + 4) == 5 &&
        h[96] == type && h[97] == 0 && memchr(h + 32, 0, 32) && memchr(h + 64, 0, 32) &&
        equal_case((const char *)h + 32, id) && !strcmp((const char *)h + 64, NTSC_BUILD) &&
        (!limits || (declared >= 2048 && declared <= MAX_MAP_BYTES && tags <= MAX_TAG_BYTES &&
                      offset >= 2048 && (uint64_t)offset + tags <= declared));
}
static int stock_profile(const char *maps)
{
    const char *names[] = { "bloodgulch", "a10", "ui" }; unsigned types[] = { 1, 0, 2 };
    for (unsigned i = 0; i < 3; i++) {
        char name[32], path[PATH_BYTES]; unsigned char header[2048]; file_handle file;
        snprintf(name, sizeof(name), "%s.map", names[i]);
        if (find_child(maps, name, path, sizeof(path)) != 1) return 0;
        file = read_open(path); if (file == BAD_FILE) return 0;
        int okay = read_bytes(file, header, sizeof(header)) == sizeof(header) && valid_header(header, names[i], types[i], 0);
        file_close(file); if (!okay) return 0;
    }
    return 1;
}

static int verify_payload(const char *path, const char *name,
    unsigned long long expected_bytes, const char *expected_sha256,
    unsigned long long declared_bytes)
{
    unsigned char bytes[65536], digest[32]; char hex[65]; unsigned long long size, received = 0;
    file_handle file = read_open(path); int okay = 0, count;
#ifdef _WIN32
    BCRYPT_ALG_HANDLE algorithm = NULL; BCRYPT_HASH_HANDLE hash = NULL;
    if (file == BAD_FILE) return 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0 ||
        BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) < 0) goto done;
#else
    mbedtls_sha256_context hash; mbedtls_sha256_init(&hash);
    if (file == BAD_FILE) { mbedtls_sha256_free(&hash); return 0; }
    if (mbedtls_sha256_starts(&hash, 0)) goto done;
#endif
    if (!file_size(file, &size) || !size || size > MAX_MAP_BYTES ||
        (expected_bytes && size != expected_bytes)) goto done;
    if (!expected_bytes) expected_bytes = size;
    count = read_bytes(file, bytes, name ? 2048 : sizeof(bytes));
    if (name && (count != 2048 || !valid_header(bytes, name, 1, 1) ||
        (declared_bytes && (little32(bytes + 8) != declared_bytes ||
                            strcmp((const char *)bytes + 32, name))))) goto done;
    for (;;) {
        if (count < 0 || (received += (unsigned)count) > expected_bytes) goto done;
#ifdef _WIN32
        if (BCryptHashData(hash, bytes, (ULONG)count, 0) < 0) goto done;
#else
        if (mbedtls_sha256_update(&hash, bytes, (size_t)count)) goto done;
#endif
        count = read_bytes(file, bytes, sizeof(bytes));
        if (!count) break;
    }
    if (received != expected_bytes || !file_size(file, &size) || size != received) goto done;
#ifdef _WIN32
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0) goto done;
#else
    if (mbedtls_sha256_finish(&hash, digest)) goto done;
#endif
    for (unsigned i = 0; i < sizeof(digest); i++) snprintf(hex + i * 2, 3, "%02x", digest[i]);
    okay = !strcmp(hex, expected_sha256);
done:
#ifdef _WIN32
    if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
#else
    mbedtls_sha256_free(&hash);
#endif
    file_close(file); return okay;
}
static int verify_map(const char *path, const struct map_entry *entry)
{ return verify_payload(path, entry->id, entry->bytes, entry->sha256, 0); }
static void map_progress(void *context, unsigned long long received, unsigned long long total)
{
    unsigned *last = context; unsigned percent = total ? (unsigned)(received * 100 / total) : 0;
    if (percent >= *last + 25 && percent <= 100) { *last = percent; platform_log("community maps: current map %u%%", percent); }
}
static int object_url(char *out, size_t capacity, const char *key)
{
    size_t length = strlen(OBJECT_ORIGIN);
    if (length >= capacity) return 0;
    memcpy(out, OBJECT_ORIGIN, length);
    for (; *key; key++) {
        if (length + 4 >= capacity) return 0;
        if (*key == ' ') { memcpy(out + length, "%20", 3); length += 3; }
        else out[length++] = *key;
    }
    out[length] = 0; return 1;
}
#include "community_arsenal_download.inc"
static int prefetch(void *unused)
{
    char maps[PATH_BYTES], partial[PATH_BYTES], catalog_path[PATH_BYTES] = "", map_partial[PATH_BYTES] = "", error[256] = "";
    struct catalog *catalog = NULL; unsigned char *data = NULL;
    unsigned completed = 0, preserved = 0, failed = 0; unsigned long long size;
    file_handle file = BAD_FILE; int own_partial = 0;
    (void)unused;
    const char *root = platform_data_root();
    if (!real_directory_chain(root) || find_child(root, "maps", maps, sizeof(maps)) != 1 || path_kind(maps) != 2 || !stock_profile(maps)) {
        platform_log("community maps: disabled for this run; original Xbox NTSC 2276 bloodgulch/a10/ui maps are required in a real maps directory"); return 0;
    }
    for (unsigned i = 0; i < 32; i++) {
        char name[96]; snprintf(name, sizeof(name), ".halo-og-download-%llu-%u", (unsigned long long)SDL_GetTicksNS(), i);
        if (!join_path(partial, sizeof(partial), maps, name)) break;
        if (make_directory(partial)) { own_partial = 1; break; }
    }
    if (!own_partial || !join_path(catalog_path, sizeof(catalog_path), partial, "catalog.partial") ||
        !join_path(map_partial, sizeof(map_partial), partial, "map.partial")) {
        platform_log("community maps: cannot create private temporary download directory"); goto done;
    }
    platform_log("community maps: auto_download=true; checking %s (full caches, up to 2 GiB; original files preserved)", CATALOG_URL);
    if (!update_download_limited(CATALOG_URL, catalog_path, MAX_CATALOG_BYTES, NULL, NULL, error, sizeof(error))) {
        platform_log("community maps: catalog download failed: %s", error); goto done;
    }
    file = read_open(catalog_path);
    if (file == BAD_FILE || !file_size(file, &size) || !size || size > MAX_CATALOG_BYTES) goto invalid;
    data = malloc((size_t)size); catalog = malloc(sizeof(*catalog));
    if (!data || !catalog) goto invalid;
    size_t have = 0;
    while (have < size) {
        int count = read_bytes(file, data + have, (unsigned)(size - have));
        if (count <= 0) goto invalid; have += (unsigned)count;
    }
    unsigned char extra;
    if (read_bytes(file, &extra, 1) != 0 || !parse_catalog(data, (size_t)size, catalog)) goto invalid;
    file_close(file); file = BAD_FILE;
    for (unsigned i = 0; i < catalog->count; i++) {
        const struct map_entry *entry = &catalog->entries[i];
        char name[40], target[PATH_BYTES], url[256]; unsigned last = 0;
        snprintf(name, sizeof(name), "%s.map", entry->id);
        int existing = find_child(maps, name, target, sizeof(target));
        if (existing == 1) {
            if (verify_map(target, entry)) { completed++; platform_log("community maps: %s already verified (%u/%u)", entry->id, i + 1, catalog->count); }
            else { preserved++; platform_log("community maps: %s exists with different bytes; preserved, no download", entry->id); }
            continue;
        }
        if (existing < 0 || !join_path(target, sizeof(target), maps, name) || !object_url(url, sizeof(url), entry->object_key)) {
            failed++; platform_log("community maps: unsafe or ambiguous destination for %s; preserved", entry->id); continue;
        }
        /* Never reuse an abandoned temporary file. Only our private directory
           is cleaned; no data/stock/user file is passed to the transport. */
        remove_file(map_partial);
        platform_log("community maps: downloading %s (%u/%u, %llu bytes)", entry->id, i + 1, catalog->count, entry->bytes);
        if (!update_download_limited(url, map_partial, entry->bytes, map_progress, &last, error, sizeof(error))) {
            failed++; platform_log("community maps: %s download failed: %s", entry->id, error); continue;
        }
        if (!verify_map(map_partial, entry) || !sync_file(map_partial)) {
            failed++; platform_log("community maps: %s failed exact size/SHA-256/Xbox compatibility verification", entry->id); continue;
        }
        /* Recheck case aliases immediately before exclusive publication. A
           racing exact-name file also wins: publication never replaces it. */
        existing = find_child(maps, name, target, sizeof(target));
        if (existing || !join_path(target, sizeof(target), maps, name) || !publish_file(map_partial, target)) {
            char raced[PATH_BYTES]; int race = find_child(maps, name, raced, sizeof(raced));
            if (race == 1 && verify_map(raced, entry)) completed++;
            else if (race == 1) { preserved++; platform_log("community maps: %s destination changed; existing content preserved", entry->id); }
            else { failed++; platform_log("community maps: %s could not be published safely; no existing verified destination", entry->id); }
        } else { completed++; platform_log("community maps: %s verified and published", entry->id); }
    }
    platform_log("community maps: finished; %u verified, %u existing files preserved, %u failed. Restart Halo OG to discover new maps.", completed, preserved, failed);
    goto done;
invalid:
    platform_log("community maps: catalog rejected (schema, profile, identity or byte limits); no maps downloaded");
done:
    if (file != BAD_FILE) file_close(file);
    free(data); free(catalog);
    if (own_partial) {
        if (*catalog_path) remove_file(catalog_path);
        if (*map_partial) remove_file(map_partial);
        remove_directory(partial);
    }
    return 0;
}
void community_maps_download_start(void)
{
    if (!config_boolean("community_maps.auto_download")) {
        platform_log("community maps: auto_download=false; background downloads disabled"); return;
    }
    if (!SDL_CompareAndSwapAtomicInt(&started, 0, 1)) return;
    SDL_Thread *thread = SDL_CreateThread(prefetch, "community maps", NULL);
    if (thread) SDL_DetachThread(thread);
    else platform_log("community maps: cannot start background worker: %s", SDL_GetError());
}
#endif
