/* Optional complete timer-pack downloads for Windows/Linux. This module uses
   the host ABI and existing bounded HTTPS transport. Mac/Android use their
   native content backends; no recordings or Timer Sounds rules are enabled here. */
#include "timer_audio_download.h"

#if defined(HALO_ANDROID) || defined(HALO_MACOS)
void timer_audio_download_start(void) {}
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
#ifdef _WIN32
#include <windows.h>
#include <aclapi.h>
#include <bcrypt.h>
#else
#include <dirent.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__linux__)
#include <linux/fs.h>
#include <sys/syscall.h>
#endif
#include "mbedtls/sha256.h"
#endif

extern const char *platform_save_root(void);
extern void platform_log(const char *format, ...);

#define MANIFEST_URL "https://dl.oghalo.com/audio/timer/v1/current.json"
#define MAX_MANIFEST_BYTES 65536u
#define MAX_FILE_BYTES 1048576u
#define MAX_PACK_BYTES 33554432u
#define CLIP_COUNT 46
#define PATH_BYTES 1024

static const char *const cues[CLIP_COUNT] = {
    "timerbeep", "1_minute", "2_minutes", "3_minutes", "4_minutes", "5_minutes",
    "6_minutes", "7_minutes", "8_minutes", "9_minutes", "10_minutes",
    "11_minutes", "12_minutes", "13_minutes", "14_minutes", "15_minutes",
    "16_minutes", "17_minutes", "18_minutes", "19_minutes", "20_minutes",
    "21_minutes", "22_minutes", "23_minutes", "24_minutes", "25_minutes",
    "26_minutes", "27_minutes", "28_minutes", "29_minutes", "30_minutes",
    "30_seconds_left", "20_seconds", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1",
    "rocket", "camo", "overshield"
};
struct clip_entry { char cue[32], sha256[65], object_key[128]; unsigned long long bytes; };
struct manifest { struct clip_entry entries[CLIP_COUNT]; unsigned count; };
struct json { const unsigned char *p, *end; };
static SDL_AtomicInt started;

static int join_path(char *out, size_t capacity, const char *root, const char *name)
{
    int length = snprintf(out, capacity, "%s/%s", root, name);
    return length >= 0 && (size_t)length < capacity;
}
static int equal_case(const char *a, const char *b)
{
    while (*a && *b) if (tolower((unsigned char)*a++) != tolower((unsigned char)*b++)) return 0;
    return *a == *b;
}
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
        if (value > (MAX_PACK_BYTES - digit) / 10) return 0;
        value = value * 10 + digit;
    }
    if (begin == j->p || (j->p - begin > 1 && *begin == '0')) return 0;
    *out = value; return 1;
}
static int clip_object(struct json *j, struct clip_entry *entry)
{
    unsigned fields = 0;
    char key[32], expected[128];
    memset(entry, 0, sizeof(*entry));
    if (!token(j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(j, key, sizeof(key)) || !token(j, ':')) return 0;
        if (!strcmp(key, "cue")) { bit = 1; if (!string(j, entry->cue, sizeof(entry->cue))) return 0; }
        else if (!strcmp(key, "sha256")) { bit = 2; if (!string(j, entry->sha256, sizeof(entry->sha256))) return 0; }
        else if (!strcmp(key, "object_key")) { bit = 4; if (!string(j, entry->object_key, sizeof(entry->object_key))) return 0; }
        else if (!strcmp(key, "file_bytes")) { bit = 8; if (!integer(j, &entry->bytes) || entry->bytes < 46 || entry->bytes > MAX_FILE_BYTES) return 0; }
        else return 0;
        if (fields & bit) return 0;
        fields |= bit;
        if (token(j, '}')) break;
        if (!token(j, ',')) return 0;
    }
    if (fields != 15 || strlen(entry->sha256) != 64) return 0;
    unsigned known = 0;
    for (unsigned i = 0; i < CLIP_COUNT; i++) if (!strcmp(cues[i], entry->cue)) known = 1;
    if (!known) return 0;
    for (unsigned i = 0; i < 64; i++)
        if (!((entry->sha256[i] >= '0' && entry->sha256[i] <= '9') || (entry->sha256[i] >= 'a' && entry->sha256[i] <= 'f'))) return 0;
    snprintf(expected, sizeof(expected), "audio/timer/sha256/%s/%s.wav", entry->sha256, entry->cue);
    return !strcmp(expected, entry->object_key);
}
static int parse_manifest(const unsigned char *data, size_t size, struct manifest *manifest)
{
    struct json j = { data, data + size };
    unsigned fields = 0;
    unsigned long long number, total = 0;
    char key[32], value[32];
    memset(manifest, 0, sizeof(*manifest));
    if (size > MAX_MANIFEST_BYTES || !token(&j, '{')) return 0;
    for (;;) {
        unsigned bit;
        if (!string(&j, key, sizeof(key)) || !token(&j, ':')) return 0;
        if (!strcmp(key, "schema_version")) { bit = 1; if (!integer(&j, &number) || number != 1) return 0; }
        else if (!strcmp(key, "pack_id")) { bit = 2; if (!string(&j, value, sizeof(value)) || strcmp(value, "performance-timer-v1")) return 0; }
        else if (!strcmp(key, "files")) {
            bit = 4;
            if (!token(&j, '[')) return 0;
            if (!token(&j, ']')) for (;;) {
                if (manifest->count == CLIP_COUNT || !clip_object(&j, &manifest->entries[manifest->count])) return 0;
                struct clip_entry *entry = &manifest->entries[manifest->count];
                for (unsigned i = 0; i < manifest->count; i++) if (!strcmp(manifest->entries[i].cue, entry->cue)) return 0;
                if ((total += entry->bytes) > MAX_PACK_BYTES) return 0;
                manifest->count++;
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
    return fields == 7 && manifest->count == CLIP_COUNT && j.p == j.end;
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
    /* A content folder can be shared. Protect our fresh temporary subtree so the
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
static int publish_directory(const char *source, const char *target)
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
static int publish_directory(const char *source, const char *target)
{
#if defined(__linux__)
    return syscall(SYS_renameat2, AT_FDCWD, source, AT_FDCWD, target, RENAME_NOREPLACE) == 0;
#elif defined(__APPLE__)
    return renamex_np(source, target, RENAME_EXCL) == 0;
#else
    (void)source; (void)target; return 0;
#endif
}
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
static unsigned little16(const unsigned char *p)
{ return (unsigned)p[0] | (unsigned)p[1] << 8; }
static int valid_wav(const unsigned char *h, unsigned long long size)
{
    unsigned channels = little16(h + 22), rate = little32(h + 24), align = little16(h + 32), bytes = little32(h + 40);
    return !memcmp(h, "RIFF", 4) && !memcmp(h + 8, "WAVEfmt ", 8) && little32(h + 16) == 16 &&
        little16(h + 20) == 1 && little16(h + 34) == 16 && !memcmp(h + 36, "data", 4) &&
        (channels == 1 || channels == 2) && (rate == 22050 || rate == 44100) && align == channels * 2 &&
        little32(h + 28) == rate * align && bytes && !(bytes % align) && bytes <= rate * align * 4 &&
        little32(h + 4) == bytes + 36 && size == (uint64_t)bytes + 44;
}
static int verify_clip(const char *path, const struct clip_entry *entry)
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
    if (!file_size(file, &size) || size != entry->bytes) goto done;
    count = read_bytes(file, bytes, 44);
    if (count != 44 || !valid_wav(bytes, size)) goto done;
    for (;;) {
        if (count < 0 || (received += (unsigned)count) > entry->bytes) goto done;
#ifdef _WIN32
        if (BCryptHashData(hash, bytes, (ULONG)count, 0) < 0) goto done;
#else
        if (mbedtls_sha256_update(&hash, bytes, (size_t)count)) goto done;
#endif
        count = read_bytes(file, bytes, sizeof(bytes));
        if (!count) break;
    }
    if (received != entry->bytes || !file_size(file, &size) || size != received) goto done;
#ifdef _WIN32
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0) goto done;
#else
    if (mbedtls_sha256_finish(&hash, digest)) goto done;
#endif
    for (unsigned i = 0; i < sizeof(digest); i++) snprintf(hex + i * 2, 3, "%02x", digest[i]);
    okay = !strcmp(hex, entry->sha256);
done:
#ifdef _WIN32
    if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
#else
    mbedtls_sha256_free(&hash);
#endif
    file_close(file); return okay;
}
static int sync_directory(const char *path)
{
#ifdef _WIN32
    (void)path; return 1; /* Each file is flushed before Windows' exclusive move. */
#else
    int file = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW), result;
    if (file < 0) return 0;
    result = fsync(file) == 0; close(file); return result;
#endif
}
static int prefetch(void *unused)
{
    char sounds[PATH_BYTES], target[PATH_BYTES], partial[PATH_BYTES], manifest_path[PATH_BYTES] = "", clip_path[PATH_BYTES], error[256] = "";
    struct manifest *manifest = NULL; unsigned char *data = NULL;
    unsigned long long size;
    file_handle file = BAD_FILE;
    int own_partial = 0, installed = 0;
    const char *root = platform_save_root();
    (void)unused;
    if (!real_directory_chain(root)) {
        platform_log("timer recordings: save root is not a real directory; existing content preserved"); return 0;
    }
    int existing = find_child(root, "sounds", sounds, sizeof(sounds));
    if (existing < 0 || (existing == 1 && path_kind(sounds) != 2) ||
        (!existing && (!join_path(sounds, sizeof(sounds), root, "sounds") || !make_directory(sounds)))) {
        platform_log("timer recordings: sounds directory is unavailable; existing content preserved"); return 0;
    }
    if (find_child(sounds, "performance", target, sizeof(target)) ||
        !join_path(target, sizeof(target), sounds, "performance")) {
        platform_log("timer recordings: existing pack folder preserved; no download needed or replacement attempted"); return 0;
    }
    for (unsigned i = 0; i < 32; i++) {
        char name[96]; snprintf(name, sizeof(name), ".halo-timer-download-%llu-%u", (unsigned long long)SDL_GetTicksNS(), i);
        if (!join_path(partial, sizeof(partial), sounds, name)) break;
        if (make_directory(partial)) { own_partial = 1; break; }
    }
    if (!own_partial || !join_path(manifest_path, sizeof(manifest_path), partial, "download-manifest.json")) {
        platform_log("timer recordings: cannot create a private download directory"); goto done;
    }
    platform_log("timer recordings: auto_download=true; checking %s (optional complete pack, up to 32 MiB)", MANIFEST_URL);
    if (!update_download_limited(MANIFEST_URL, manifest_path, MAX_MANIFEST_BYTES, NULL, NULL, error, sizeof(error))) {
        platform_log("timer recordings: manifest download failed: %s", error); goto done;
    }
    file = read_open(manifest_path);
    if (file == BAD_FILE || !file_size(file, &size) || !size || size > MAX_MANIFEST_BYTES) goto invalid;
    data = malloc((size_t)size); manifest = malloc(sizeof(*manifest));
    if (!data || !manifest) goto invalid;
    size_t have = 0;
    while (have < size) {
        int count = read_bytes(file, data + have, (unsigned)(size - have));
        if (count <= 0) goto invalid; have += (unsigned)count;
    }
    unsigned char extra;
    if (read_bytes(file, &extra, 1) != 0 || !parse_manifest(data, (size_t)size, manifest)) goto invalid;
    file_close(file); file = BAD_FILE;
    for (unsigned i = 0; i < manifest->count; i++) {
        const struct clip_entry *entry = &manifest->entries[i];
        char name[40], url[256];
        snprintf(name, sizeof(name), "%s.wav", entry->cue);
        if (!join_path(clip_path, sizeof(clip_path), partial, name) ||
            !join_path(url, sizeof(url), "https://dl.oghalo.com", entry->object_key)) goto invalid;
        if (!update_download_limited(url, clip_path, entry->bytes, NULL, NULL, error, sizeof(error))) {
            platform_log("timer recordings: %s download failed: %s; incomplete pack discarded", entry->cue, error); goto done;
        }
        if (!verify_clip(clip_path, entry) || !sync_file(clip_path)) {
            platform_log("timer recordings: %s failed exact size/SHA-256/PCM validation; incomplete pack discarded", entry->cue); goto done;
        }
    }
    if (!sync_file(manifest_path) || !sync_directory(partial) || !real_directory_chain(sounds) ||
        find_child(sounds, "performance", target, sizeof(target)) ||
        !join_path(target, sizeof(target), sounds, "performance") || !publish_directory(partial, target)) {
        platform_log("timer recordings: complete pack could not be activated; existing content preserved"); goto done;
    }
    own_partial = 0; installed = 1;
    (void)sync_directory(sounds);
    platform_log("timer recordings: complete pack installed. Restart Halo OG to enable Timer Audio; game rules stay unchanged.");
    goto done;
invalid:
    platform_log("timer recordings: manifest rejected (schema, identities or byte limits); no pack installed");
done:
    if (file != BAD_FILE) file_close(file);
    free(data); free(manifest);
    if (own_partial) {
        if (*manifest_path) remove_file(manifest_path);
        for (unsigned i = 0; i < CLIP_COUNT; i++) {
            char name[40]; snprintf(name, sizeof(name), "%s.wav", cues[i]);
            if (join_path(clip_path, sizeof(clip_path), partial, name)) remove_file(clip_path);
        }
        remove_directory(partial);
    }
    return installed;
}
void timer_audio_download_start(void)
{
    if (!config_boolean("timer_audio.auto_download")) {
        platform_log("timer recordings: auto_download=false; background downloads disabled"); return;
    }
    if (!SDL_CompareAndSwapAtomicInt(&started, 0, 1)) return;
    SDL_Thread *thread = SDL_CreateThread(prefetch, "timer recordings", NULL);
    if (thread) SDL_DetachThread(thread);
    else platform_log("timer recordings: cannot start background worker: %s", SDL_GetError());
}
#endif
