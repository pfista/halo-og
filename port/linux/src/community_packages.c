/* Native whole-tag HOGPKG1 consumer. No guest structs, runtime Python, shell,
   executable downloads, source stock edits, or permissive hash fallbacks. */
#include "community_packages.h"
#include "community_mapog.h"
#if defined(HALO_ANDROID)
/* Guest/Android builds do not reconstruct content. The host-only desktop
   implementation below must never import filesystem/process ABI into them. */
int community_package_inspect(const char *package, struct community_package_info *info, char *error, size_t size)
{ (void)package; (void)info; (void)error; (void)size; return -1; }
int community_package_reconstruct(const char *package, const char *stock, const char *tools, const char *record,
    const char *work, const char *destination, community_package_progress progress, void *context, char *error, size_t size)
{ (void)package; (void)stock; (void)tools; (void)record; (void)work; (void)destination; (void)progress; (void)context; (void)error; (void)size; return -1; }
#else
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#include <aclapi.h>
#include <bcrypt.h>
#else
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
#else
#include "mbedtls/sha256.h"
#endif
#endif

#define INVADER_COMMIT "7d25a855f5ef9e4ab8407abf490b21f8780abf27"
#define PRODUCER_EXTRACT "4dc6a8c5583f055b715cf48ae011929be63749a56a68540c31e73238d46e1e3f"
#define PRODUCER_BUILD "4586b82e0db2a57e390e6d61ccf3a4cf2fde26288652cd0d3708be0e87111f65"
#define NTSC_BUILD "01.10.12.2276"
#define MAX_PACKAGE (256ULL * 1024 * 1024)
#define MAX_MANIFEST (4u * 1024 * 1024)
#define MAX_ASSET (128ULL * 1024 * 1024)
#define MAX_STOCK (512ULL * 1024 * 1024)
#define MAX_TREE (1024ULL * 1024 * 1024)
#define MAX_TAGS (22ULL * 1024 * 1024)
#define MAX_FILES 20000
#define PATH_SIZE 2048
#define MAX_NODES 300000
static const char *stock_names[] = { "bloodgulch", "a10", "ui" };
static const unsigned stock_types[] = { 1, 0, 2 };
static int fail(char *error, size_t size, const char *message)
{ if (error && size) snprintf(error, size, "%s", message); return -1; }
static int real_parent(const char *path);
static int prepare_input(const char *source, const char *work_parent, char raw[PATH_SIZE], char work[PATH_SIZE], int *owned, uint64_t *source_bytes, char *error, size_t size);
static void remove_work(const char *path);
static int join(char *out, const char *a, const char *b)
{ int n = snprintf(out, PATH_SIZE, "%s/%s", a, b); return n >= 0 && n < PATH_SIZE; }
static int same_case(const char *a, const char *b)
{ while (*a && *b) if (tolower((unsigned char)*a++) != tolower((unsigned char)*b++)) return 0; return *a == *b; }
static uint32_t le32(const unsigned char *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t le64(const unsigned char *p) { return le32(p) | (uint64_t)le32(p + 4) << 32; }
static int sha_string(const char *s)
{ if (!s || strlen(s) != 64) return 0; for (; *s; s++) if (!strchr("0123456789abcdef", *s)) return 0; return 1; }
static int safe_relative(const char *s)
{
    if (!s || !*s || strlen(s) > 512 || *s == '/') return 0;
    const char *start = s;
    for (;;) {
        const char *end = strchr(start, '/'); size_t n = end ? (size_t)(end - start) : strlen(start);
        if (!n || n > 255 || *start == '.' || start[n - 1] == '.' || start[n - 1] == ' ') return 0;
        char stem[256]; size_t k = 0;
        for (size_t i = 0; i < n; i++) {
            unsigned char c = (unsigned char)start[i];
            if (c < 32 || c > 126 || strchr("\\:<>\"|?*~", c)) return 0;
            if (c == '.' && k == i) break;
            stem[k++] = (char)toupper(c);
        }
        while (k && stem[k - 1] == ' ') k--; stem[k] = 0;
        /* Scan the entire component even when the device stem ends early. */
        for (size_t i = 0; i < n; i++) if ((unsigned char)start[i] < 32 || (unsigned char)start[i] > 126 || strchr("\\:<>\"|?*~", start[i])) return 0;
        if (!strcmp(stem, "CON") || !strcmp(stem, "PRN") || !strcmp(stem, "AUX") || !strcmp(stem, "NUL") ||
            !strcmp(stem, "CONIN$") || !strcmp(stem, "CONOUT$") ||
            (k == 4 && (!memcmp(stem, "COM", 3) || !memcmp(stem, "LPT", 3)) && stem[3] >= '1' && stem[3] <= '9')) return 0;
        if (!end) return 1; start = end + 1;
    }
}
static int safe_id(const char *s)
{
    static const char *reserved[] = { "ui", "a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40",
        "beavercreek", "bloodgulch", "boardingaction", "carousel", "chillout", "damnation", "hangemhigh", "longest", "prisoner", "putput", "ratrace", "sidewinder", "wizard" };
    if (!s || !*s || strlen(s) > 31 || !isalnum((unsigned char)*s) || !safe_relative(s)) return 0;
    for (const char *p = s; *p; p++) if (!strchr("abcdefghijklmnopqrstuvwxyz0123456789_-", *p)) return 0;
    for (unsigned i = 0; i < sizeof(reserved) / sizeof(*reserved); i++) if (!strcmp(s, reserved[i])) return 0;
    return 1;
}

#ifdef _WIN32
typedef HANDLE file_t;
#define BAD_FILE INVALID_HANDLE_VALUE
static int wide(const char *s, wchar_t out[PATH_SIZE])
{ return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, out, PATH_SIZE) > 0; }
static int kind(const char *s)
{
    wchar_t p[PATH_SIZE]; if (!wide(s, p)) return -1;
    DWORD a = GetFileAttributesW(p);
    if (a == INVALID_FILE_ATTRIBUTES) return GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND ? 0 : -1;
    if (a & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)) return -1;
    return a & FILE_ATTRIBUTE_DIRECTORY ? 2 : 1;
}
static file_t open_file(const char *s, int writing)
{
    wchar_t p[PATH_SIZE]; BY_HANDLE_FILE_INFORMATION info;
    if (!wide(s, p)) return BAD_FILE;
    file_t f = CreateFileW(p, writing ? GENERIC_WRITE : GENERIC_READ, writing ? 0 : FILE_SHARE_READ,
        NULL, writing ? CREATE_NEW : OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (f != BAD_FILE && (!GetFileInformationByHandle(f, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_DEVICE)))) { CloseHandle(f); return BAD_FILE; }
    return f;
}
static int file_size(file_t f, uint64_t *n)
{ LARGE_INTEGER v; if (!GetFileSizeEx(f, &v) || v.QuadPart < 0) return 0; *n = (uint64_t)v.QuadPart; return 1; }
static int at_read(file_t f, void *out, size_t size, uint64_t offset)
{
    LARGE_INTEGER v; v.QuadPart = (LONGLONG)offset; DWORD n;
    return SetFilePointerEx(f, v, NULL, FILE_BEGIN) && ReadFile(f, out, (DWORD)size, &n, NULL) && n == size;
}
static int write_all(file_t f, const void *p, size_t n)
{ DWORD count; return WriteFile(f, p, (DWORD)n, &count, NULL) && count == n; }
static int flush(file_t f) { return FlushFileBuffers(f); }
static void close_file(file_t f) { CloseHandle(f); }
static void unlink_file(const char *s) { wchar_t p[PATH_SIZE]; if (wide(s, p)) DeleteFileW(p); }
static void rmdir_path(const char *s) { wchar_t p[PATH_SIZE]; if (wide(s, p)) RemoveDirectoryW(p); }
static int mkdir_private(const char *s)
{
    wchar_t p[PATH_SIZE]; HANDLE token = NULL; TOKEN_USER *user = NULL; DWORD n = 0; PACL acl = NULL; int okay = 0;
    EXPLICIT_ACCESSW access; SECURITY_DESCRIPTOR descriptor; SECURITY_ATTRIBUTES attr = { sizeof(attr), &descriptor, FALSE };
    if (!wide(s, p) || !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) goto done;
    GetTokenInformation(token, TokenUser, NULL, 0, &n);
    if (!n || n > 65536 || !(user = malloc(n)) || !GetTokenInformation(token, TokenUser, user, n, &n)) goto done;
    memset(&access, 0, sizeof(access)); access.grfAccessPermissions = FILE_ALL_ACCESS; access.grfAccessMode = SET_ACCESS;
    access.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT; access.Trustee.TrusteeForm = TRUSTEE_IS_SID;
    access.Trustee.TrusteeType = TRUSTEE_IS_USER; access.Trustee.ptstrName = (LPWSTR)user->User.Sid;
    if (SetEntriesInAclW(1, &access, NULL, &acl) != ERROR_SUCCESS || !InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) ||
        !SetSecurityDescriptorDacl(&descriptor, TRUE, acl, FALSE) || !SetSecurityDescriptorControl(&descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED)) goto done;
    okay = CreateDirectoryW(p, &attr);
done:
    if (acl) LocalFree(acl); free(user); if (token) CloseHandle(token); return okay;
}
static int publish(const char *from, const char *to)
{ wchar_t a[PATH_SIZE], b[PATH_SIZE]; return wide(from, a) && wide(to, b) && MoveFileExW(a, b, 0); }
typedef struct { BCRYPT_ALG_HANDLE algorithm; BCRYPT_HASH_HANDLE hash; } hash_t;
static int hash_begin(hash_t *h)
{ memset(h, 0, sizeof(*h)); return BCryptOpenAlgorithmProvider(&h->algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) >= 0 && BCryptCreateHash(h->algorithm, &h->hash, NULL, 0, NULL, 0, 0) >= 0; }
static int hash_add(hash_t *h, const void *p, size_t n) { return BCryptHashData(h->hash, (PUCHAR)p, (ULONG)n, 0) >= 0; }
static int hash_end(hash_t *h, unsigned char digest[32]) { return BCryptFinishHash(h->hash, digest, 32, 0) >= 0; }
static void hash_free(hash_t *h) { if (h->hash) BCryptDestroyHash(h->hash); if (h->algorithm) BCryptCloseAlgorithmProvider(h->algorithm, 0); }
#else
typedef int file_t;
#define BAD_FILE -1
static int kind(const char *s)
{ struct stat v; if (lstat(s, &v)) return errno == ENOENT ? 0 : -1; return S_ISREG(v.st_mode) ? 1 : S_ISDIR(v.st_mode) ? 2 : -1; }
static file_t open_file(const char *s, int writing)
{
    int f = open(s, (writing ? O_WRONLY | O_CREAT | O_EXCL : O_RDONLY | O_NONBLOCK) | O_NOFOLLOW | O_CLOEXEC, 0600);
    struct stat v; if (f >= 0 && (fstat(f, &v) || !S_ISREG(v.st_mode))) { close(f); return BAD_FILE; } return f;
}
static int file_size(file_t f, uint64_t *n)
{ struct stat v; if (fstat(f, &v) || v.st_size < 0) return 0; *n = (uint64_t)v.st_size; return 1; }
static int at_read(file_t f, void *out, size_t n, uint64_t offset)
{
    unsigned char *p = out;
    while (n) { ssize_t count = pread(f, p, n, (off_t)offset); if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return 0; p += count; n -= (size_t)count; offset += (size_t)count; }
    return 1;
}
static int write_all(file_t f, const void *data, size_t n)
{ const unsigned char *p = data; while (n) { ssize_t k = write(f, p, n); if (k < 0 && errno == EINTR) continue; if (k <= 0) return 0; p += k; n -= (size_t)k; } return 1; }
static int flush(file_t f) { return fsync(f) == 0; }
static void close_file(file_t f) { close(f); }
static void unlink_file(const char *s) { unlink(s); }
static void rmdir_path(const char *s) { rmdir(s); }
static int mkdir_private(const char *s) { return mkdir(s, 0700) == 0; }
static int publish(const char *from, const char *to) { return link(from, to) == 0; }
#ifdef __APPLE__
typedef CC_SHA256_CTX hash_t;
static int hash_begin(hash_t *h) { return CC_SHA256_Init(h); }
static int hash_add(hash_t *h, const void *p, size_t n) { return CC_SHA256_Update(h, p, (CC_LONG)n); }
static int hash_end(hash_t *h, unsigned char digest[32]) { return CC_SHA256_Final(digest, h); }
static void hash_free(hash_t *h) { (void)h; }
#else
typedef mbedtls_sha256_context hash_t;
static int hash_begin(hash_t *h) { mbedtls_sha256_init(h); return mbedtls_sha256_starts(h, 0) == 0; }
static int hash_add(hash_t *h, const void *p, size_t n) { return mbedtls_sha256_update(h, p, n) == 0; }
static int hash_end(hash_t *h, unsigned char digest[32]) { return mbedtls_sha256_finish(h, digest) == 0; }
static void hash_free(hash_t *h) { mbedtls_sha256_free(h); }
#endif
#endif
static int hash_range(file_t f, uint64_t offset, uint64_t size, char result[65])
{
    unsigned char data[65536], digest[32]; hash_t h; int okay = hash_begin(&h);
    while (okay && size) { size_t n = size < sizeof(data) ? (size_t)size : sizeof(data);
        okay = at_read(f, data, n, offset) && hash_add(&h, data, n); size -= n; offset += n; }
    okay = okay && hash_end(&h, digest); hash_free(&h);
    if (okay) for (unsigned i = 0; i < 32; i++) snprintf(result + i * 2, 3, "%02x", digest[i]);
    return okay;
}
static int verify_file(const char *path, uint64_t size, const char *sha)
{
    file_t f = open_file(path, 0); uint64_t before, after; char actual[65];
    if (f == BAD_FILE) return 0;
    int okay = file_size(f, &before) && before == size && hash_range(f, 0, size, actual) &&
        file_size(f, &after) && after == size && !strcmp(actual, sha);
    close_file(f); return okay;
}

/* Bounded JSON DOM. Keys are decoded before duplicate checks; integers never
   accept bool, signs, floats, exponent notation or overflowing values. */
enum { J_OBJECT = 1, J_ARRAY, J_STRING, J_NUMBER, J_BOOL, J_NULL };
struct node { int type, child, next; char *text; uint64_t number; };
struct json { const unsigned char *p, *end; struct node *nodes; unsigned count, capacity; int okay; };
static void white(struct json *j) { while (j->p < j->end && strchr(" \t\r\n", *j->p)) j->p++; }
static char *json_string(struct json *j)
{
    if (j->p == j->end || *j->p++ != '"') return NULL;
    const unsigned char *start = j->p, *finish = start;
    while (finish < j->end) { unsigned char c = *finish++; if (c == '"') break;
        if (c == '\\' && finish < j->end) finish++; }
    size_t capacity = (size_t)(finish - start) + 1;
    char *s = malloc(capacity); size_t n = 0; if (!s) return NULL;
    while (j->p < j->end) {
        unsigned char c = *j->p++;
        if (c == '"') { s[n] = 0; return s; }
        if (c < 32 || c > 126) break;
        if (c == '\\') {
            if (j->p == j->end) break; c = *j->p++;
            if (c == 'u') {
                unsigned value = 0; int valid = j->end - j->p >= 4;
                for (unsigned i = 0; valid && i < 4; i++) { unsigned char h = *j->p++; const char *v = strchr("0123456789abcdef", tolower(h)); if (!v) { valid = 0; break; } value = value * 16 + (unsigned)(v - "0123456789abcdef"); }
                if (!valid || value < 32 || value > 126) break; c = (unsigned char)value;
            } else if (!strchr("\"\\/", c)) break;
        }
        s[n++] = (char)c;
    }
    free(s); return NULL;
}
static int new_node(struct json *j, int type)
{
    if (j->count == MAX_NODES) return 0;
    if (j->count + 1 >= j->capacity) { unsigned cap = j->capacity ? j->capacity * 2 : 256;
        struct node *next = realloc(j->nodes, cap * sizeof(*next)); if (!next) return 0;
        j->nodes = next; j->capacity = cap; }
    int i = (int)++j->count; memset(&j->nodes[i], 0, sizeof(j->nodes[i])); j->nodes[i].type = type; return i;
}
static int json_value(struct json *j, unsigned depth)
{
    white(j); if (depth > 64 || j->p == j->end) return 0;
    unsigned char c = *j->p; int i = new_node(j, c == '{' ? J_OBJECT : c == '[' ? J_ARRAY : c == '"' ? J_STRING : J_NUMBER);
    if (!i) return 0;
    if (c == '"') { j->nodes[i].text = json_string(j); return j->nodes[i].text ? i : 0; }
    if (c == '{' || c == '[') {
        int previous = 0; unsigned char end = c == '{' ? '}' : ']'; j->p++; white(j);
        if (j->p < j->end && *j->p == end) { j->p++; return i; }
        for (;;) {
            int key = 0;
            if (c == '{') {
                key = new_node(j, J_STRING); if (!key || !(j->nodes[key].text = json_string(j))) return 0;
                for (int old = j->nodes[i].child; old; old = j->nodes[j->nodes[old].next].next)
                    if (!strcmp(j->nodes[old].text, j->nodes[key].text)) return 0;
                white(j); if (j->p == j->end || *j->p++ != ':') return 0;
            }
            int value = json_value(j, depth + 1); if (!value) return 0;
            int first = key ? key : value;
            if (key) j->nodes[key].next = value;
            if (previous) j->nodes[previous].next = first; else j->nodes[i].child = first;
            previous = value; white(j); if (j->p == j->end) return 0;
            unsigned char separator = *j->p++;
            if (separator == end) return i;
            if (separator != ',') return 0; white(j);
        }
    }
    if (c == 't' || c == 'f' || c == 'n') {
        const char *literal = c == 't' ? "true" : c == 'f' ? "false" : "null"; size_t n = strlen(literal);
        if ((size_t)(j->end - j->p) < n || memcmp(j->p, literal, n)) return 0;
        j->p += n; j->nodes[i].type = c == 'n' ? J_NULL : J_BOOL; return i;
    }
    const unsigned char *start = j->p; uint64_t value = 0;
    while (j->p < j->end && *j->p >= '0' && *j->p <= '9') { unsigned digit = *j->p++ - '0';
        if (value > (UINT64_MAX - digit) / 10) return 0; value = value * 10 + digit; }
    if (j->p == start || (j->p - start > 1 && *start == '0')) return 0;
    j->nodes[i].number = value; return i;
}
static void free_json(struct json *j)
{ for (unsigned i = 1; i <= j->count; i++) free(j->nodes[i].text); free(j->nodes); memset(j, 0, sizeof(*j)); }
static int get(struct json *j, int object, const char *key)
{ if (!object || j->nodes[object].type != J_OBJECT) return 0; for (int n = j->nodes[object].child; n; n = j->nodes[j->nodes[n].next].next) if (!strcmp(j->nodes[n].text, key)) return j->nodes[n].next; return 0; }
static const char *text_value(struct json *j, int object, const char *key)
{ int n = get(j, object, key); return n && j->nodes[n].type == J_STRING ? j->nodes[n].text : NULL; }
static int string_is(struct json *j, int object, const char *key, const char *value)
{ const char *s = text_value(j, object, key); return s && !strcmp(s, value); }
static int number_value(struct json *j, int object, const char *key, uint64_t minimum, uint64_t maximum, uint64_t *out)
{ int n = get(j, object, key); if (!n || j->nodes[n].type != J_NUMBER || j->nodes[n].number < minimum || j->nodes[n].number > maximum) return 0; *out = j->nodes[n].number; return 1; }
static int keys(struct json *j, int object, const char *allowed, unsigned count)
{
    if (!object || j->nodes[object].type != J_OBJECT) return 0; unsigned found = 0;
    for (int n = j->nodes[object].child; n; n = j->nodes[j->nodes[n].next].next) {
        char pattern[96]; int size = snprintf(pattern, sizeof(pattern), "|%s|", j->nodes[n].text);
        if (size < 0 || (size_t)size >= sizeof(pattern) || !strstr(allowed, pattern)) return 0; found++;
    }
    return found == count;
}
static int parse_json(struct json *j, const unsigned char *data, size_t size)
{ memset(j, 0, sizeof(*j)); j->p = data; j->end = data + size; int root = json_value(j, 0); white(j); return root == 1 && j->p == j->end; }

struct asset { const char *tree, *path, *sha, *stock, *original; uint64_t size, offset; int literal; };
struct package { struct json json; struct community_package_info info; file_t file; uint64_t payload_offset, payload_bytes;
    const char *scenario; uint64_t stock_sizes[3]; const char *stock_hashes[3]; struct asset *assets; unsigned count; };
static int compare_asset(const void *a, const void *b)
{
    const struct asset *x = *(const struct asset *const *)a, *y = *(const struct asset *const *)b;
    int tree = strcmp(x->tree, y->tree); if (tree) return tree;
    const unsigned char *p = (const unsigned char *)x->path, *q = (const unsigned char *)y->path;
    while (*p && *q && tolower(*p) == tolower(*q)) { p++; q++; }
    return tolower(*p) - tolower(*q);
}
static int path_collisions(struct asset *assets, unsigned count)
{
    struct asset **sorted = malloc(count * sizeof(*sorted)); if (!sorted) return 0;
    for (unsigned i = 0; i < count; i++) sorted[i] = &assets[i]; qsort(sorted, count, sizeof(*sorted), compare_asset);
    int okay = 1;
    for (unsigned i = 1; okay && i < count; i++) {
        const struct asset *a = sorted[i - 1], *b = sorted[i]; if (strcmp(a->tree, b->tree)) continue;
        size_t n = 0, directory = 0;
        while (a->path[n] && b->path[n] && tolower((unsigned char)a->path[n]) == tolower((unsigned char)b->path[n])) {
            if (a->path[n] == '/') directory = n + 1; n++;
        }
        if ((!a->path[n] && (!b->path[n] || b->path[n] == '/')) ||
            (!b->path[n] && a->path[n] == '/') || (directory && memcmp(a->path, b->path, directory))) okay = 0;
    }
    free(sorted); return okay;
}
static int validate_manifest(struct package *p)
{
    struct json *j = &p->json; uint64_t version, n, declared, tags;
    const char *id = text_value(j, 1, "id"), *scenario = text_value(j, 1, "scenario");
    if (!keys(j, 1, "|format||version||id||profile||cache_build||scenario||invader_commit||tool_sha256||stock_inputs||output||payload_bytes||files|", 12) ||
        !string_is(j, 1, "format", "halo-og-community-package") || !number_value(j, 1, "version", 1, 1, &version) ||
        !string_is(j, 1, "profile", "stock-xbox-ntsc") || !string_is(j, 1, "cache_build", NTSC_BUILD) ||
        !string_is(j, 1, "invader_commit", INVADER_COMMIT) || !safe_id(id) || !safe_relative(scenario)) return 0;
    for (const char *s = scenario; *s; s++) if (!isalnum((unsigned char)*s) && !strchr("_ /-", *s)) return 0;
    const char *base = strrchr(scenario, '/'); if (strcmp(base ? base + 1 : scenario, id)) return 0;
    int tools = get(j, 1, "tool_sha256");
    if (!keys(j, tools, "|extract||build|", 2) || !string_is(j, tools, "extract", PRODUCER_EXTRACT) || !string_is(j, tools, "build", PRODUCER_BUILD)) return 0;
    int stock = get(j, 1, "stock_inputs"); if (!stock || j->nodes[stock].type != J_ARRAY) return 0;
    int input = j->nodes[stock].child;
    for (unsigned i = 0; i < 3; i++) {
        if (!keys(j, input, "|name||size||sha256||type|", 4) || !string_is(j, input, "name", stock_names[i]) ||
            !number_value(j, input, "type", stock_types[i], stock_types[i], &n) ||
            !number_value(j, input, "size", 2048, MAX_STOCK, &p->stock_sizes[i]) || !sha_string(p->stock_hashes[i] = text_value(j, input, "sha256"))) return 0;
        input = j->nodes[input].next;
    }
    if (input) return 0;
    int output = get(j, 1, "output");
    if (!keys(j, output, "|size||sha256||declared_bytes||tag_bytes|", 4) || !number_value(j, output, "size", 2048, MAX_ASSET, &n) ||
        !number_value(j, output, "declared_bytes", 2048, MAX_ASSET, &declared) || !number_value(j, output, "tag_bytes", 0, MAX_TAGS, &tags) ||
        !sha_string(text_value(j, output, "sha256")) || !number_value(j, 1, "payload_bytes", 0, MAX_PACKAGE - 16, &p->payload_bytes)) return 0;
    snprintf(p->info.id, sizeof(p->info.id), "%s", id); snprintf(p->info.map_sha256, sizeof(p->info.map_sha256), "%s", text_value(j, output, "sha256"));
    p->info.map_bytes = n; p->info.declared_bytes = declared; p->info.tag_bytes = tags; p->scenario = scenario;
    int files = get(j, 1, "files"); if (!files || j->nodes[files].type != J_ARRAY) return 0;
    for (int f = j->nodes[files].child; f; f = j->nodes[f].next) if (++p->count > MAX_FILES) return 0;
    if (!p->count || !(p->assets = calloc(p->count, sizeof(*p->assets)))) return 0;
    uint64_t offset = 0, expanded = 0; unsigned i = 0; int authored = 0;
    for (int f = j->nodes[files].child; f; f = j->nodes[f].next, i++) {
        struct asset *a = &p->assets[i]; a->tree = text_value(j, f, "tree"); a->path = text_value(j, f, "path"); a->sha = text_value(j, f, "sha256");
        const char *kind_value = text_value(j, f, "kind"), *classification = text_value(j, f, "classification");
        if (!a->tree || (strcmp(a->tree, "tags") && strcmp(a->tree, "data") && strcmp(a->tree, "stock-overrides")) || !safe_relative(a->path) ||
            !sha_string(a->sha) || !kind_value || !classification || !number_value(j, f, "size", 0, MAX_ASSET, &a->size) || (expanded += a->size) > MAX_TREE) return 0;
        a->literal = !strcmp(kind_value, "literal"); int overrides = !strcmp(a->tree, "stock-overrides");
        if (a->literal) {
            if (!keys(j, f, overrides ? "|tree||path||kind||classification||size||sha256||offset||original_sha256|" : "|tree||path||kind||classification||size||sha256||offset|", overrides ? 8 : 7) ||
                !number_value(j, f, "offset", offset, offset, &a->offset) || offset > p->payload_bytes || a->size > p->payload_bytes - offset) return 0;
            offset += a->size;
            if (strcmp(classification, "modified-or-different-stock") && strcmp(classification, "unknown-or-community") &&
                strcmp(classification, "compatibility-modified-stock") && strcmp(classification, "generated-data")) return 0;
        } else {
            a->stock = text_value(j, f, "stock_path");
            if (strcmp(kind_value, "stock-reference") || strcmp(a->tree, "tags") || strcmp(classification, "unchanged-stock") ||
                !safe_relative(a->stock) || !keys(j, f, "|tree||path||kind||classification||size||sha256||stock_path|", 7)) return 0;
        }
        char scenario_path[520]; snprintf(scenario_path, sizeof(scenario_path), "%s.scenario", scenario);
        if (overrides) {
            a->original = text_value(j, f, "original_sha256");
            if (!a->literal || strcmp(classification, "compatibility-modified-stock") || !sha_string(a->original) || !strcmp(a->original, a->sha) || !strcmp(a->path, scenario_path)) return 0;
        }
        if (!strcmp(a->tree, "data")) { size_t length = strlen(a->path);
            if (!a->literal || strcmp(classification, "generated-data") || length < 4 || strcmp(a->path + length - 4, ".hsc")) return 0; }
        if (!strcmp(a->tree, "tags") && !strcmp(a->path, scenario_path)) authored = a->literal;
    }
    return offset == p->payload_bytes && authored && path_collisions(p->assets, p->count);
}
static void package_close(struct package *p)
{ if (p->file != BAD_FILE) close_file(p->file); free(p->assets); free_json(&p->json); memset(p, 0, sizeof(*p)); p->file = BAD_FILE; }
static int package_open(struct package *p, const char *path)
{
    memset(p, 0, sizeof(*p)); p->file = BAD_FILE; unsigned char header[16]; uint64_t size;
    if (!real_parent(path)) return 0;
    p->file = open_file(path, 0);
    if (p->file == BAD_FILE || !file_size(p->file, &size) || size < 16 || size > MAX_PACKAGE || !at_read(p->file, header, sizeof(header), 0) || memcmp(header, "HOGPKG1\n", 8)) return 0;
    uint64_t n = le64(header + 8); if (!n || n > MAX_MANIFEST || n > size - 16) return 0;
    unsigned char *data = malloc((size_t)n); if (!data) return 0;
    int okay = at_read(p->file, data, (size_t)n, 16) && parse_json(&p->json, data, (size_t)n); free(data);
    p->payload_offset = 16 + n; p->info.package_bytes = size;
    if (!okay || !validate_manifest(p) || p->payload_bytes != size - p->payload_offset) return 0;
    for (unsigned i = 0; i < p->count; i++) if (p->assets[i].literal) {
        char actual[65]; struct asset *a = &p->assets[i];
        if (!hash_range(p->file, p->payload_offset + a->offset, a->size, actual) || strcmp(actual, a->sha)) return 0;
    }
    uint64_t final_size; return file_size(p->file, &final_size) && final_size == size;
}
int community_package_inspect(const char *path, struct community_package_info *info, char *error, size_t size)
{
    char raw[PATH_SIZE], work[PATH_SIZE] = ""; int owned = 0; uint64_t source_bytes;
    if (!prepare_input(path, NULL, raw, work, &owned, &source_bytes, error, size)) return -1;
    struct package p; int okay = package_open(&p, raw);
    if (okay && info) { *info = p.info; info->package_bytes = source_bytes; }
    package_close(&p); if (owned) remove_work(work);
    return okay ? 0 : fail(error, size, "Community package rejected: schema, path, producer, bounds or complete asset hash differs.");
}

/* All directory ancestors must be real. Fresh private trees are the only
   writable paths; package-selected names never reach an external root. */
static int real_chain(const char *path)
{
    char absolute[PATH_SIZE]; size_t begin = 1;
#ifdef _WIN32
    wchar_t input[PATH_SIZE], full[PATH_SIZE]; DWORD length;
    if (!wide(path, input) || !(length = GetFullPathNameW(input, PATH_SIZE, full, NULL)) || length >= PATH_SIZE ||
        !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, full, -1, absolute, sizeof(absolute), NULL, NULL) ||
        !isalpha((unsigned char)absolute[0]) || absolute[1] != ':' || (absolute[2] != '/' && absolute[2] != '\\')) return 0;
    begin = 3;
#else
    if (path[0] == '/') { if (strlen(path) >= sizeof(absolute)) return 0; strcpy(absolute, path); }
    else { char cwd[PATH_SIZE]; if (!getcwd(cwd, sizeof(cwd)) || !join(absolute, cwd, path)) return 0; }
#endif
    for (size_t i = begin; ; i++) if (!absolute[i] || absolute[i] == '/' || absolute[i] == '\\') {
        char c = absolute[i]; absolute[i] = 0; if (kind(absolute) != 2) return 0;
        absolute[i] = c; if (!c) break;
    }
    return 1;
}
static int real_parent(const char *path)
{
    char parent[PATH_SIZE]; if (strlen(path) >= sizeof(parent)) return 0; strcpy(parent, path);
    char *slash = strrchr(parent, '/');
#ifdef _WIN32
    char *back = strrchr(parent, '\\'); if (back && (!slash || back > slash)) slash = back;
#endif
    if (!slash) return real_chain("."); if (slash == parent) slash[1] = 0; else *slash = 0;
    return real_chain(parent);
}
static int parent_path(const char *path, char parent[PATH_SIZE])
{
    if (strlen(path) >= PATH_SIZE) return 0; strcpy(parent, path);
    char *slash = strrchr(parent, '/');
#ifdef _WIN32
    char *back = strrchr(parent, '\\'); if (back && (!slash || back > slash)) slash = back;
#endif
    if (!slash) strcpy(parent, "."); else if (slash == parent) slash[1] = 0; else *slash = 0;
    return real_chain(parent);
}
/* Compressed input is expanded only in a newly owned private tree. Inspection
   uses the OS temporary directory; reconstruction stays under its explicit
   work parent. The source's own directory is never used for output. */
static int fresh_work(const char *parent, char work[PATH_SIZE])
{
    if (!real_chain(parent)) return 0;
    for (unsigned i = 0; i < 32; i++) { char name[96];
#ifdef _WIN32
        unsigned long pid = GetCurrentProcessId(); uint64_t tick = GetTickCount64();
#else
        unsigned long pid = (unsigned long)getpid(); struct timespec now;
        if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
        uint64_t tick = (uint64_t)now.tv_sec * 1000000000 + (uint64_t)now.tv_nsec;
#endif
        snprintf(name, sizeof(name), ".halo-og-package-%lu-%llu-%u", pid, (unsigned long long)tick, i);
        if (!join(work, parent, name)) return 0;
        if (mkdir_private(work)) return 1;
    }
    return 0;
}
static int prepare_input(const char *source, const char *work_parent, char raw[PATH_SIZE], char work[PATH_SIZE], int *owned, uint64_t *source_bytes, char *error, size_t size)
{
    unsigned char magic[8]; file_t input; uint64_t bytes;
    if (!real_parent(source) || (input = open_file(source, 0)) == BAD_FILE)
        return fail(error, size, "Community package input is linked, special or inaccessible."), 0;
    int valid = file_size(input, &bytes) && bytes >= 18 && bytes <= MAX_PACKAGE && at_read(input, magic, sizeof(magic), 0);
    close_file(input);
    if (!valid) return fail(error, size, "Community package input exceeds its bounds or is truncated."), 0;
    if (source_bytes) *source_bytes = bytes;
    if (memcmp(magic, "HOGMAP2\n", 8)) {
        if (memcmp(magic, "HOGPKG1\n", 8) || strlen(source) >= PATH_SIZE)
            return fail(error, size, "Unknown community package format."), 0;
        strcpy(raw, source); return 1;
    }
    char temporary[PATH_SIZE];
    if (!work_parent) {
#ifdef _WIN32
        wchar_t native[PATH_SIZE]; DWORD n = GetTempPathW(PATH_SIZE, native);
        if (!n || n >= PATH_SIZE || !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, native, -1, temporary, sizeof(temporary), NULL, NULL))
            return fail(error, size, "A safe inspection temporary directory is unavailable."), 0;
        size_t length = strlen(temporary); while (length > 3 && (temporary[length - 1] == '/' || temporary[length - 1] == '\\')) temporary[--length] = 0;
#else
        char *canonical = realpath("/tmp", NULL);
        if (!canonical || strlen(canonical) >= sizeof(temporary)) {
            free(canonical); return fail(error, size, "A safe inspection temporary directory is unavailable."), 0;
        }
        strcpy(temporary, canonical); free(canonical);
#endif
        work_parent = temporary;
    }
    if (!fresh_work(work_parent, work)) return fail(error, size, "A fresh private package expansion directory could not be created."), 0;
    *owned = 1;
    if (!join(raw, work, "content.hogpkg") || community_mapog_expand(source, raw, error, size)) {
        remove_work(work); *owned = 0; return 0;
    }
    return 1;
}
typedef int (*child_proc)(const char *name, const char *path, void *context);
static int children(const char *directory, child_proc visit, void *context)
{
    int okay = 1;
#ifdef _WIN32
    char pattern[PATH_SIZE], name[PATH_SIZE], path[PATH_SIZE]; wchar_t search_path[PATH_SIZE]; WIN32_FIND_DATAW item;
    if (!join(pattern, directory, "*") || !wide(pattern, search_path)) return 0;
    HANDLE find = FindFirstFileW(search_path, &item); if (find == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_FILE_NOT_FOUND;
    do {
        if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, item.cFileName, -1, name, sizeof(name), NULL, NULL)) { okay = 0; break; }
        if (!strcmp(name, ".") || !strcmp(name, "..")) continue;
        if (!join(path, directory, name) || !visit(name, path, context)) { okay = 0; break; }
    } while (FindNextFileW(find, &item));
    if (okay && GetLastError() != ERROR_NO_MORE_FILES) okay = 0; FindClose(find);
#else
    DIR *find = opendir(directory); if (!find) return 0; struct dirent *item; errno = 0;
    while ((item = readdir(find))) {
        if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, "..")) continue;
        char path[PATH_SIZE]; if (!join(path, directory, item->d_name) || !visit(item->d_name, path, context)) { okay = 0; break; }
        errno = 0;
    }
    if (!item && errno) okay = 0; closedir(find);
#endif
    return okay;
}
struct find_context { const char *wanted; char *out; int found; };
static int find_visit(const char *name, const char *path, void *context)
{
    struct find_context *f = context; if (!same_case(name, f->wanted)) return 1;
    if (f->found || kind(path) < 1) { f->found = -1; return 0; }
    strcpy(f->out, path); f->found = 1; return 1;
}
static int find_child(const char *root, const char *name, char out[PATH_SIZE])
{ struct find_context f = { name, out, 0 }; return children(root, find_visit, &f) ? f.found : -1; }
static int existing_relative(const char *root, const char *relative, char out[PATH_SIZE])
{
    char component[513], current[PATH_SIZE]; if (!safe_relative(relative) || !real_chain(root) || strlen(root) >= sizeof(current)) return 0;
    strcpy(current, root); const char *p = relative;
    for (;;) { const char *end = strchr(p, '/'); size_t n = end ? (size_t)(end - p) : strlen(p);
        memcpy(component, p, n); component[n] = 0;
        if (find_child(current, component, out) != 1) return 0;
        if (!end) return kind(out) == 1;
        if (kind(out) != 2) return 0; strcpy(current, out); p = end + 1;
    }
}
static int target_relative(const char *root, const char *relative, char out[PATH_SIZE])
{
    if (!safe_relative(relative) || !join(out, root, relative)) return 0;
    size_t prefix = strlen(root) + 1;
    for (size_t i = prefix; out[i]; i++) if (out[i] == '/') { out[i] = 0;
        int k = kind(out); if ((!k && !mkdir_private(out)) || (k && k != 2)) return 0; out[i] = '/'; }
    return kind(out) == 0;
}
static int copy_range(file_t source, uint64_t offset, uint64_t size, const char *sha, const char *target)
{
    file_t out = open_file(target, 1); if (out == BAD_FILE) return 0;
    unsigned char data[65536], digest[32]; char actual[65]; hash_t h; int okay = hash_begin(&h);
    while (okay && size) { size_t n = size < sizeof(data) ? (size_t)size : sizeof(data);
        okay = at_read(source, data, n, offset) && write_all(out, data, n) && hash_add(&h, data, n); offset += n; size -= n; }
    okay = okay && hash_end(&h, digest); hash_free(&h);
    if (okay) { for (unsigned i = 0; i < 32; i++) snprintf(actual + i * 2, 3, "%02x", digest[i]); okay = !strcmp(actual, sha) && flush(out); }
    close_file(out); if (!okay) unlink_file(target); return okay;
}
static int copy_exact(const char *source, uint64_t size, const char *sha, const char *target)
{
    file_t f = open_file(source, 0); uint64_t n;
    if (f == BAD_FILE) return 0;
    int okay = file_size(f, &n) && n == size && copy_range(f, 0, size, sha, target);
    close_file(f); return okay;
}
static int remove_visit(const char *name, const char *path, void *context)
{
    (void)name; (void)context;
    if (kind(path) == 2) { if (!children(path, remove_visit, NULL)) return 0; rmdir_path(path); }
    else { unlink_file(path);
#ifdef _WIN32
        /* Junction directories are removed as links, never enumerated. */
        rmdir_path(path);
#endif
    }
    return kind(path) == 0;
}
static void remove_work(const char *root) { if (kind(root) == 2) { children(root, remove_visit, NULL); rmdir_path(root); } }
struct tree_context { const char *source, *target; struct asset *files; unsigned count; uint64_t total; unsigned depth; };
static int tree_visit(const char *name, const char *path, void *context)
{
    (void)name; struct tree_context *t = context; const char *relative = path + strlen(t->source) + 1;
    if (!safe_relative(relative) || t->depth > 64) return 0;
    int k = kind(path);
    if (k == 2) { t->depth++; int okay = children(path, tree_visit, t); t->depth--; return okay; }
    if (k != 1 || t->count == MAX_FILES) return 0;
    struct asset *a = &t->files[t->count]; file_t f = open_file(path, 0); uint64_t n; char sha[65];
    if (f == BAD_FILE) return 0;
    int okay = file_size(f, &n) && n <= MAX_ASSET && n <= MAX_TREE - t->total && hash_range(f, 0, n, sha);
    close_file(f); if (!okay) return 0;
    char *r = malloc(strlen(relative) + 1), *hash = malloc(65); if (!r || !hash) { free(r); free(hash); return 0; }
    strcpy(r, relative); strcpy(hash, sha); a->tree = "stock"; a->path = r; a->sha = hash; a->size = n; t->count++; t->total += n; return 1;
}
static int inventory_tree(const char *root, struct tree_context *tree)
{
    memset(tree, 0, sizeof(*tree)); tree->source = root; tree->files = calloc(MAX_FILES, sizeof(*tree->files));
    return tree->files && real_chain(root) && children(root, tree_visit, tree) && path_collisions(tree->files, tree->count);
}
static void free_tree(struct tree_context *t)
{ for (unsigned i = 0; i < t->count; i++) { free((char *)t->files[i].path); free((char *)t->files[i].sha); } free(t->files); }
static int map_header(const char *path, const char *name, unsigned type, uint64_t maximum, const struct community_package_info *expected)
{
    unsigned char h[2048]; file_t f = open_file(path, 0); uint64_t n;
    if (f == BAD_FILE) return 0;
    int okay = file_size(f, &n) && n >= 2048 && n <= maximum && at_read(f, h, sizeof(h), 0); close_file(f);
    if (!okay || memcmp(h, "daeh", 4) || memcmp(h + 2044, "toof", 4) || le32(h + 4) != 5 ||
        h[96] != type || h[97] || !memchr(h + 32, 0, 32) || !memchr(h + 64, 0, 32) ||
        !same_case((const char *)h + 32, name) || strcmp((const char *)h + 64, NTSC_BUILD) ||
        le32(h + 8) < 2048 || le32(h + 8) > maximum || le32(h + 16) < 2048 ||
        le32(h + 20) > MAX_TAGS || (uint64_t)le32(h + 16) + le32(h + 20) > le32(h + 8)) return 0;
    return !expected || (le32(h + 20) <= MAX_TAGS && le32(h + 8) == expected->declared_bytes && le32(h + 20) == expected->tag_bytes);
}
static int exact_map(const char *path, const struct community_package_info *info)
{ return map_header(path, info->id, 1, MAX_ASSET, info) && verify_file(path, info->map_bytes, info->map_sha256); }

/* Only a local bundled record can grant producer compatibility; package
   tool hashes never select the executable or authenticate a consumer binary. */
static int helper_hashes(const char *record, char hashes[2][65])
{
    if (!real_parent(record)) return 0;
    file_t f = open_file(record, 0); uint64_t n; unsigned char *data = NULL; struct json j; memset(&j, 0, sizeof(j)); int okay = 0;
    if (f == BAD_FILE || !file_size(f, &n) || !n || n > MAX_MANIFEST || !(data = malloc((size_t)n)) || !at_read(f, data, (size_t)n, 0) || !parse_json(&j, data, (size_t)n)) goto done;
#ifdef _WIN32
    const char *platform = "windows";
#elif defined(__APPLE__)
    const char *platform = "macos";
#else
    const char *platform = "linux";
#endif
    uint64_t schema; if (!number_value(&j, 1, "schema", 1, 1, &schema) || !string_is(&j, 1, "invader_commit", INVADER_COMMIT) ||
        !string_is(&j, 1, "consumer_platform", platform)) goto done;
    int compatible = get(&j, 1, "compatible_package_producers"); unsigned count = 0; int approved = 0;
    if (!compatible || j.nodes[compatible].type != J_ARRAY) goto done;
    for (int p = j.nodes[compatible].child; p; p = j.nodes[p].next) {
        if (++count > 32 || !keys(&j, p, "|invader_commit||tool_sha256|", 2) || !string_is(&j, p, "invader_commit", INVADER_COMMIT)) goto done;
        int pair = get(&j, p, "tool_sha256"); if (!keys(&j, pair, "|extract||build|", 2) || !sha_string(text_value(&j, pair, "extract")) || !sha_string(text_value(&j, pair, "build"))) goto done;
        if (string_is(&j, pair, "extract", PRODUCER_EXTRACT) && string_is(&j, pair, "build", PRODUCER_BUILD)) approved = 1;
    }
    if (!approved) goto done;
    int binaries = get(&j, 1, "binaries"); if (!keys(&j, binaries, "|extract||build|", 2)) goto done;
    for (unsigned i = 0; i < 2; i++) {
        int binary = get(&j, binaries, i ? "build" : "extract"); const char *hash = text_value(&j, binary, "bundled_sha256");
        if (!sha_string(hash) || !sha_string(text_value(&j, binary, "source_sha256"))) goto done;
        strcpy(hashes[i], hash);
    }
    okay = 1;
done:
    if (f != BAD_FILE) close_file(f); free(data); free_json(&j); return okay;
}

#ifdef _WIN32
static int append_argument(wchar_t *command, size_t capacity, size_t *used, const char *argument)
{
    wchar_t value[PATH_SIZE]; if (!wide(argument, value) || *used + 4 >= capacity) return 0;
    command[(*used)++] = ' '; command[(*used)++] = '"'; unsigned slashes = 0;
    for (const wchar_t *p = value; ; p++) {
        if (*p == '\\') { slashes++; continue; }
        unsigned count = *p == '"' || !*p ? slashes * 2 : slashes;
        while (count--) { if (*used + 2 >= capacity) return 0; command[(*used)++] = '\\'; }
        slashes = 0; if (!*p) break;
        if (*p == '"') { if (*used + 2 >= capacity) return 0; command[(*used)++] = '\\'; }
        if (*used + 2 >= capacity) return 0; command[(*used)++] = *p;
    }
    command[(*used)++] = '"'; command[*used] = 0; return 1;
}
#endif
static int run_helper(const char *binary, const char *sha, const char *cwd, const char *log, const char *const *arguments)
{
    file_t verify = open_file(binary, 0); uint64_t n; char actual[65];
    if (verify == BAD_FILE) return 0;
    int okay = file_size(verify, &n) && n > 0 && n <= MAX_STOCK && hash_range(verify, 0, n, actual) && !strcmp(actual, sha);
    if (!okay) { close_file(verify); return 0; }
#ifdef _WIN32
    wchar_t program[PATH_SIZE], directory[PATH_SIZE], log_path[PATH_SIZE], command[32768]; size_t used = 0;
    STARTUPINFOW startup; PROCESS_INFORMATION process; memset(&startup, 0, sizeof(startup)); startup.cb = sizeof(startup);
    if (!wide(binary, program) || !wide(cwd, directory) || !wide(log, log_path) || !append_argument(command, 32768, &used, binary)) { close_file(verify); return 0; }
    for (unsigned i = 0; arguments[i]; i++) if (!append_argument(command, 32768, &used, arguments[i])) { close_file(verify); return 0; }
    SECURITY_ATTRIBUTES attributes = { sizeof(attributes), NULL, TRUE };
    HANDLE output = CreateFileW(log_path, GENERIC_WRITE, 0, &attributes, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    HANDLE input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &attributes, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (output == INVALID_HANDLE_VALUE || input == INVALID_HANDLE_VALUE) { if (output != INVALID_HANDLE_VALUE) CloseHandle(output); if (input != INVALID_HANDLE_VALUE) CloseHandle(input); close_file(verify); return 0; }
    startup.dwFlags = STARTF_USESTDHANDLES; startup.hStdInput = input; startup.hStdOutput = output; startup.hStdError = output;
    okay = CreateProcessW(program, command + 1, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, directory, &startup, &process);
    if (okay) { DWORD status = WaitForSingleObject(process.hProcess, 180000), code = 1;
        if (status != WAIT_OBJECT_0) { TerminateProcess(process.hProcess, 1); WaitForSingleObject(process.hProcess, 5000); okay = 0; }
        else okay = GetExitCodeProcess(process.hProcess, &code) && !code;
        CloseHandle(process.hThread); CloseHandle(process.hProcess); }
    CloseHandle(input); CloseHandle(output);
#else
    file_t output = open_file(log, 1); if (output == BAD_FILE) { close_file(verify); return 0; }
    pid_t child = fork();
    if (!child) {
        if (chdir(cwd) || dup2(output, STDOUT_FILENO) < 0 || dup2(output, STDERR_FILENO) < 0) _exit(126);
        int input = open("/dev/null", O_RDONLY); if (input < 0 || dup2(input, STDIN_FILENO) < 0) _exit(126);
        char *argv[32]; unsigned i = 0; argv[i++] = (char *)binary;
        while (*arguments && i < 31) argv[i++] = (char *)*arguments++;
        argv[i] = NULL; execv(binary, argv); _exit(127);
    }
    close_file(output); okay = child > 0;
    if (okay) { struct timespec start, now; clock_gettime(CLOCK_MONOTONIC, &start); int status = 0;
        for (;;) { pid_t result = waitpid(child, &status, WNOHANG);
            if (result == child) { okay = WIFEXITED(status) && !WEXITSTATUS(status); break; }
            if (result < 0 && errno != EINTR) { okay = 0; break; }
            clock_gettime(CLOCK_MONOTONIC, &now);
            if (now.tv_sec - start.tv_sec >= 180) { kill(child, SIGKILL); while (waitpid(child, &status, 0) < 0 && errno == EINTR) {} okay = 0; break; }
            struct timespec delay = { 0, 100000000 }; nanosleep(&delay, NULL);
        }
    }
#endif
    close_file(verify); return okay;
}

static int reconstruct_raw(const char *package, const char *stock_maps, const char *tools_directory,
    const char *tools_record, const char *work_parent, const char *destination,
    community_package_progress progress, void *context, char *error, size_t error_size)
{
    struct package p; struct tree_context tree; memset(&tree, 0, sizeof(tree));
    char work[PATH_SIZE] = "", original[PATH_SIZE], stock[PATH_SIZE], tags[PATH_SIZE], data[PATH_SIZE], maps[PATH_SIZE];
    char stock_files[3][PATH_SIZE], helpers[2][PATH_SIZE], hashes[2][65], target[PATH_SIZE], source[PATH_SIZE], log[PATH_SIZE];
    int own_work = 0, result = -1; const char *reason = "Community package could not be assembled safely.";
    memset(&p, 0, sizeof(p)); p.file = BAD_FILE;
    if (!package_open(&p, package)) {
        reason = "Community package rejected: schema, path, producer, bounds or complete asset hash differs."; goto done;
    }
    if (!real_chain(stock_maps) || !real_chain(tools_directory) || !real_chain(work_parent) || !real_parent(destination)) {
        reason = "Stock, helper, work or destination directory is linked, special or inaccessible."; goto done;
    }
    const char *destination_name = strrchr(destination, '/');
#ifdef _WIN32
    const char *back = strrchr(destination, '\\'); if (back && (!destination_name || back > destination_name)) destination_name = back;
#endif
    destination_name = destination_name ? destination_name + 1 : destination; char expected_name[40]; snprintf(expected_name, sizeof(expected_name), "%s.map", p.info.id);
    if (strcmp(destination_name, expected_name)) { reason = "Destination does not use the package's community map identity."; goto done; }
    char destination_parent[PATH_SIZE], existing_destination[PATH_SIZE];
    if (!parent_path(destination, destination_parent)) goto done;
    int existing = find_child(destination_parent, expected_name, existing_destination);
    if (existing) { if (existing == 1 && exact_map(existing_destination, &p.info)) result = 1;
        else reason = "Existing or ambiguous map differs; preserved without replacement."; goto done; }
    if (!helper_hashes(tools_record, hashes)) { reason = "Locally packaged ContentTools.json does not approve this producer and platform."; goto done; }
    for (unsigned i = 0; i < 2; i++) {
#ifdef _WIN32
        const char *name = i ? "invader-build.exe" : "invader-extract.exe";
#else
        const char *name = i ? "invader-build" : "invader-extract";
#endif
        if (!join(helpers[i], tools_directory, name) || kind(helpers[i]) != 1) { reason = "Required fixed, locally packaged Invader helpers are unavailable."; goto done; }
    }
    for (unsigned i = 0; i < 3; i++) { char name[32]; snprintf(name, sizeof(name), "%s.map", stock_names[i]);
        if (find_child(stock_maps, name, stock_files[i]) != 1 || !map_header(stock_files[i], stock_names[i], stock_types[i], MAX_STOCK, NULL) ||
            !verify_file(stock_files[i], p.stock_sizes[i], p.stock_hashes[i])) { reason = "Original NTSC stock caches differ from the package's exact bases."; goto done; }
    }
    own_work = fresh_work(work_parent, work);
    if (!own_work || !join(original, work, "original") || !join(stock, work, "stock") || !join(tags, work, "tags") || !join(data, work, "data") || !join(maps, work, "maps") ||
        !mkdir_private(original) || !mkdir_private(stock) || !mkdir_private(tags) || !mkdir_private(data) || !mkdir_private(maps)) goto done;
    if (progress) progress(context, "Extracting exact original stock assets locally");
    for (unsigned i = 0; i < 3; i++) { char name[32]; snprintf(name, sizeof(name), "extract-%u.log", i);
        const char *args[] = { "-t", original, stock_files[i], NULL };
        if (!join(log, work, name) || !run_helper(helpers[0], hashes[0], work, log, args)) { reason = "Verified local Invader extraction failed or timed out."; goto done; }
    }
    if (!inventory_tree(original, &tree)) { reason = "Extracted stock contains unsafe paths, collisions, links or excessive data."; goto done; }
    /* Validate every reference and override base before materializing anything. */
    for (unsigned i = 0; i < p.count; i++) { const struct asset *a = &p.assets[i];
        if (a->stock && (!existing_relative(original, a->stock, source) || !verify_file(source, a->size, a->sha))) {
            reason = "An unchanged whole stock asset differs from its required size/SHA-256."; goto done;
        }
        if (a->original) {
            file_t f; uint64_t n; char sha[65];
            if (!existing_relative(original, a->path, source) || (f = open_file(source, 0)) == BAD_FILE) { reason = "A modified stock asset's original is missing."; goto done; }
            int okay = file_size(f, &n) && n <= MAX_ASSET && hash_range(f, 0, n, sha) && !strcmp(sha, a->original); close_file(f);
            if (!okay) { reason = "A modified stock asset's original SHA-256 differs."; goto done; }
        }
    }
    if (progress) progress(context, "Assembling complete community and modified assets in a private workspace");
    for (unsigned i = 0; i < tree.count; i++) { struct asset *a = &tree.files[i];
        if (!join(source, original, a->path) || !target_relative(stock, a->path, target) || !copy_exact(source, a->size, a->sha, target)) goto done;
    }
    for (unsigned i = 0; i < p.count; i++) { const struct asset *a = &p.assets[i]; const char *root = !strcmp(a->tree, "tags") ? tags : !strcmp(a->tree, "data") ? data : stock;
        if (a->original) { if (!existing_relative(stock, a->path, target)) goto done; unlink_file(target); }
        if (!target_relative(root, a->path, target)) goto done;
        if (a->literal) { if (!copy_range(p.file, p.payload_offset + a->offset, a->size, a->sha, target)) goto done; }
        else if (!existing_relative(original, a->stock, source) || !copy_exact(source, a->size, a->sha, target)) goto done;
    }
    if (progress) progress(context, "Building and verifying the exact community Xbox cache");
    const char *args[] = { "-g", "xbox-ntsc", "-t", stock, "-t", tags, "-m", maps, "-d", data, "-S", "data", "-E", p.scenario, NULL };
    if (!join(log, work, "build.log") || !run_helper(helpers[1], hashes[1], work, log, args)) { reason = "Verified local Invader build failed or timed out."; goto done; }
    if (!join(source, maps, expected_name) || !exact_map(source, &p.info)) { reason = "Reconstructed map differs from the approved complete bytes or Xbox bounds."; goto done; }
    for (unsigned i = 0; i < 3; i++) if (!verify_file(stock_files[i], p.stock_sizes[i], p.stock_hashes[i])) { reason = "Original stock caches changed during reconstruction."; goto done; }
    uint64_t final_package_size; if (!file_size(p.file, &final_package_size) || final_package_size != p.info.package_bytes) goto done;
    /* Helper output is regular and verified; flush before exposing the map. */
#ifdef _WIN32
    wchar_t sync_path[PATH_SIZE]; file_t sync = BAD_FILE;
    if (wide(source, sync_path)) sync = CreateFileW(sync_path, GENERIC_WRITE, 0, NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
#else
    file_t sync = open(source, O_WRONLY | O_NOFOLLOW | O_CLOEXEC);
#endif
    if (sync == BAD_FILE || !flush(sync)) { if (sync != BAD_FILE) close_file(sync); goto done; } close_file(sync);
    if (!real_parent(destination)) goto done;
    existing = find_child(destination_parent, expected_name, existing_destination);
    if (existing) { if (existing == 1 && exact_map(existing_destination, &p.info)) result = 1; else reason = "A racing existing map differs; preserved without replacement."; goto done; }
    if (!publish(source, destination)) { existing = find_child(destination_parent, expected_name, existing_destination);
        if (existing == 1 && exact_map(existing_destination, &p.info)) result = 1; else reason = "Map publication failed; existing user files were preserved."; goto done; }
    result = 0;
done:
    if (own_work) remove_work(work); free_tree(&tree); package_close(&p);
    return result >= 0 ? result : fail(error, error_size, reason);
}
int community_package_reconstruct(const char *package, const char *stock_maps, const char *tools_directory,
    const char *tools_record, const char *work_parent, const char *destination,
    community_package_progress progress, void *context, char *error, size_t error_size)
{
    char raw[PATH_SIZE], work[PATH_SIZE] = ""; int owned = 0;
    if (!prepare_input(package, work_parent, raw, work, &owned, NULL, error, error_size)) return -1;
    int result = reconstruct_raw(raw, stock_maps, tools_directory, tools_record, work_parent, destination, progress, context, error, error_size);
    if (owned) remove_work(work);
    return result;
}
#endif
