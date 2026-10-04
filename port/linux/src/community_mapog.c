/* Host-native, bounded streaming expansion. No system zlib or external tool. */
#include "community_mapog.h"
#if defined(HALO_ANDROID)
int community_mapog_expand(const char *source, const char *destination, char *error, size_t size)
{ (void)source; (void)destination; (void)error; (void)size; return -1; }
#else
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "miniz_tinfl.h"
#ifdef _WIN32
#include <windows.h>
#include <aclapi.h>
#include <bcrypt.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
#else
#include "mbedtls/sha256.h"
#endif
#endif
#define MAX_BYTES (256ULL * 1024 * 1024)
#define PATH_SIZE 2048
static uint32_t le32(const unsigned char *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t le64(const unsigned char *p) { return le32(p) | (uint64_t)le32(p + 4) << 32; }
#ifdef _WIN32
typedef HANDLE file_t;
#define BAD_FILE INVALID_HANDLE_VALUE
static int wide(const char *p, wchar_t out[PATH_SIZE])
{ return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, p, -1, out, PATH_SIZE) > 0; }
static int real_parent(const char *path, int private_output)
{
    (void)private_output; wchar_t p[PATH_SIZE], full[PATH_SIZE]; char s[PATH_SIZE]; DWORD n;
    if (!wide(path, p) || !(n = GetFullPathNameW(p, PATH_SIZE, full, NULL)) || n >= PATH_SIZE ||
        !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, full, -1, s, sizeof(s), NULL, NULL) ||
        !isalpha((unsigned char)s[0]) || s[1] != ':' || (s[2] != '/' && s[2] != '\\')) return 0;
    for (size_t i = 3; s[i]; i++) if (s[i] == '/' || s[i] == '\\') {
        char separator = s[i]; s[i] = 0; if (!wide(s, p)) return 0;
        DWORD a = GetFileAttributesW(p); s[i] = separator;
        if (a == INVALID_FILE_ATTRIBUTES || !(a & FILE_ATTRIBUTE_DIRECTORY) || (a & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE))) return 0;
    }
    return 1;
}
static file_t read_open(const char *path)
{
    wchar_t p[PATH_SIZE]; BY_HANDLE_FILE_INFORMATION info; if (!wide(path, p)) return BAD_FILE;
    file_t f = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (f != BAD_FILE && (!GetFileInformationByHandle(f, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_DEVICE)))) { CloseHandle(f); return BAD_FILE; }
    return f;
}
static file_t new_private_file(const char *path)
{
    wchar_t p[PATH_SIZE]; HANDLE token = NULL; TOKEN_USER *user = NULL; DWORD n = 0; PACL acl = NULL; file_t file = BAD_FILE;
    EXPLICIT_ACCESSW access; SECURITY_DESCRIPTOR descriptor; SECURITY_ATTRIBUTES attributes = { sizeof(attributes), &descriptor, FALSE };
    if (!wide(path, p) || !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) goto done;
    GetTokenInformation(token, TokenUser, NULL, 0, &n);
    if (!n || n > 65536 || !(user = malloc(n)) || !GetTokenInformation(token, TokenUser, user, n, &n)) goto done;
    memset(&access, 0, sizeof(access)); access.grfAccessPermissions = FILE_ALL_ACCESS; access.grfAccessMode = SET_ACCESS;
    access.Trustee.TrusteeForm = TRUSTEE_IS_SID; access.Trustee.TrusteeType = TRUSTEE_IS_USER; access.Trustee.ptstrName = (LPWSTR)user->User.Sid;
    if (SetEntriesInAclW(1, &access, NULL, &acl) != ERROR_SUCCESS || !InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) ||
        !SetSecurityDescriptorDacl(&descriptor, TRUE, acl, FALSE) || !SetSecurityDescriptorControl(&descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED)) goto done;
    file = CreateFileW(p, GENERIC_WRITE, 0, &attributes, CREATE_NEW, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
done:
    if (acl) LocalFree(acl); free(user); if (token) CloseHandle(token); return file;
}
static int size_of(file_t f, uint64_t *size)
{ LARGE_INTEGER n; if (!GetFileSizeEx(f, &n) || n.QuadPart < 0) return 0; *size = (uint64_t)n.QuadPart; return 1; }
static int read_all(file_t f, void *out, size_t n)
{ DWORD count; return ReadFile(f, out, (DWORD)n, &count, NULL) && count == n; }
static int write_all(file_t f, const void *p, size_t n)
{ DWORD count; return WriteFile(f, p, (DWORD)n, &count, NULL) && count == n; }
static int flush(file_t f) { return FlushFileBuffers(f); }
static void close_file(file_t f) { CloseHandle(f); }
static void remove_file(const char *path) { wchar_t p[PATH_SIZE]; if (wide(path, p)) DeleteFileW(p); }
typedef struct { BCRYPT_ALG_HANDLE algorithm; BCRYPT_HASH_HANDLE hash; } hash_t;
static int hash_begin(hash_t *h)
{ memset(h, 0, sizeof(*h)); return BCryptOpenAlgorithmProvider(&h->algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) >= 0 && BCryptCreateHash(h->algorithm, &h->hash, NULL, 0, NULL, 0, 0) >= 0; }
static int hash_add(hash_t *h, const void *p, size_t n) { return BCryptHashData(h->hash, (PUCHAR)p, (ULONG)n, 0) >= 0; }
static int hash_end(hash_t *h, unsigned char digest[32]) { return BCryptFinishHash(h->hash, digest, 32, 0) >= 0; }
static void hash_free(hash_t *h) { if (h->hash) BCryptDestroyHash(h->hash); if (h->algorithm) BCryptCloseAlgorithmProvider(h->algorithm, 0); }
#else
typedef int file_t;
#define BAD_FILE -1
static int real_parent(const char *path, int private_output)
{
    char absolute[PATH_SIZE];
    if (*path == '/') { if (strlen(path) >= sizeof(absolute)) return 0; strcpy(absolute, path); }
    else { char cwd[PATH_SIZE]; if (!getcwd(cwd, sizeof(cwd)) || snprintf(absolute, sizeof(absolute), "%s/%s", cwd, path) >= (int)sizeof(absolute)) return 0; }
    char *last = strrchr(absolute, '/'); if (!last) return 0;
    for (size_t i = 1; absolute[i]; i++) if (absolute[i] == '/') {
        char c = absolute[i]; absolute[i] = 0; struct stat info;
        int okay = !lstat(absolute, &info) && S_ISDIR(info.st_mode);
        if (okay && private_output && absolute + i == last) okay = info.st_uid == getuid() && !(info.st_mode & 0077);
        absolute[i] = c; if (!okay) return 0;
    }
    return 1;
}
static file_t read_open(const char *path)
{
    file_t f = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC); struct stat info;
    if (f >= 0 && (fstat(f, &info) || !S_ISREG(info.st_mode))) { close(f); return BAD_FILE; } return f;
}
static file_t new_private_file(const char *path) { return open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600); }
static int size_of(file_t f, uint64_t *size)
{ struct stat info; if (fstat(f, &info) || info.st_size < 0) return 0; *size = (uint64_t)info.st_size; return 1; }
static int read_all(file_t f, void *out, size_t n)
{ unsigned char *p = out; while (n) { ssize_t count = read(f, p, n); if (count < 0 && errno == EINTR) continue; if (count <= 0) return 0; p += count; n -= (size_t)count; } return 1; }
static int write_all(file_t f, const void *data, size_t n)
{ const unsigned char *p = data; while (n) { ssize_t count = write(f, p, n); if (count < 0 && errno == EINTR) continue; if (count <= 0) return 0; p += count; n -= (size_t)count; } return 1; }
static int flush(file_t f) { return fsync(f) == 0; }
static void close_file(file_t f) { close(f); }
static void remove_file(const char *path) { unlink(path); }
#ifdef __APPLE__
typedef CC_SHA256_CTX hash_t;
static int hash_begin(hash_t *h) { return CC_SHA256_Init(h); }
static int hash_add(hash_t *h, const void *p, size_t n) { return CC_SHA256_Update(h, p, (CC_LONG)n); }
static int hash_end(hash_t *h, unsigned char digest[32]) { return CC_SHA256_Final(digest, h); }
static void hash_free(hash_t *h) { (void)h; }
#else
typedef mbedtls_sha256_context hash_t;
static int hash_begin(hash_t *h) { mbedtls_sha256_init(h); return !mbedtls_sha256_starts(h, 0); }
static int hash_add(hash_t *h, const void *p, size_t n) { return !mbedtls_sha256_update(h, p, n); }
static int hash_end(hash_t *h, unsigned char digest[32]) { return !mbedtls_sha256_finish(h, digest); }
static void hash_free(hash_t *h) { mbedtls_sha256_free(h); }
#endif
#endif

int community_mapog_expand(const char *source, const char *destination, char *error, size_t capacity)
{
    file_t input = BAD_FILE, output = BAD_FILE; int result = -1, own_output = 0, own_hash = 0;
    unsigned char header[48], bytes[65536], ring[TINFL_LZ_DICT_SIZE], digest[32], prefix[8]; size_t prefix_bytes = 0;
    uint64_t file_bytes, remaining, expanded, written = 0; size_t available = 0, cursor = 0, ring_offset = 0;
    hash_t hash; tinfl_decompressor inflater; const char *reason = "Compressed community package is invalid, truncated, excessive or linked.";
    if (!real_parent(source, 0) || !real_parent(destination, 1) || (input = read_open(source)) == BAD_FILE ||
        !size_of(input, &file_bytes) || file_bytes < 54 || file_bytes > MAX_BYTES || !read_all(input, header, sizeof(header)) || memcmp(header, "HOGMAP2\n", 8)) goto done;
    expanded = le64(header + 8); remaining = file_bytes - sizeof(header);
    if (expanded < 18 || expanded > MAX_BYTES) goto done;
    output = new_private_file(destination); if (output == BAD_FILE) { reason = "Expansion destination already exists or is not a fresh private file."; goto done; }
    own_output = 1; own_hash = 1; if (!hash_begin(&hash)) goto done;
    tinfl_init(&inflater); int first = 1;
    for (;;) {
        if (cursor == available && remaining) {
            available = remaining < sizeof(bytes) ? (size_t)remaining : sizeof(bytes); cursor = 0;
            if (!read_all(input, bytes, available)) goto done; remaining -= available;
            if (first) { if (available < 2 || (bytes[1] & 32)) { reason = "Preset compression dictionaries are not permitted."; goto done; } first = 0; }
        }
        size_t consumed = available - cursor, produced = sizeof(ring) - ring_offset;
        unsigned flags = TINFL_FLAG_PARSE_ZLIB_HEADER | (remaining ? TINFL_FLAG_HAS_MORE_INPUT : 0);
        tinfl_status status = tinfl_decompress(&inflater, bytes + cursor, &consumed, ring, ring + ring_offset, &produced, flags);
        cursor += consumed;
        if (status < TINFL_STATUS_DONE || produced > expanded - written ||
            !write_all(output, ring + ring_offset, produced) || !hash_add(&hash, ring + ring_offset, produced)) goto done;
        if (prefix_bytes < sizeof(prefix)) { size_t n = produced < sizeof(prefix) - prefix_bytes ? produced : sizeof(prefix) - prefix_bytes;
            memcpy(prefix + prefix_bytes, ring + ring_offset, n); prefix_bytes += n; }
        written += produced; ring_offset = (ring_offset + produced) & (TINFL_LZ_DICT_SIZE - 1);
        if (status == TINFL_STATUS_DONE) {
            if (remaining || cursor != available || written != expanded) { reason = "Compressed package must contain exactly one complete stream with no trailing bytes."; goto done; }
            break;
        }
        if (!consumed && !produced) goto done;
        if (status == TINFL_STATUS_NEEDS_MORE_INPUT && cursor != available) goto done;
    }
    uint64_t current;
    if (!size_of(input, &current) || current != file_bytes || prefix_bytes != sizeof(prefix) || memcmp(prefix, "HOGPKG1\n", 8) ||
        !hash_end(&hash, digest) || memcmp(digest, header + 16, 32)) {
        reason = "Expanded package size or SHA-256 differs from its authenticated header."; goto done;
    }
    if (!flush(output)) { reason = "Expanded package could not be flushed safely."; goto done; }
    result = 0;
done:
    if (own_hash) hash_free(&hash); if (output != BAD_FILE) close_file(output); if (input != BAD_FILE) close_file(input);
    if (result && own_output) remove_file(destination);
    if (result && error && capacity) snprintf(error, capacity, "%s", reason);
    return result;
}
#endif
