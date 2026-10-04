"""Exercise production bounded-download code with memory responses, never a network.

The POSIX fixture replaces TLS reads. The Windows fixture replaces WinHTTP with
typed API stubs, so it verifies the production control flow on every host; an
actual Windows build remains responsible for SDK and native API acceptance.
Only temporary synthetic files are created. No game, app or user data is used.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


COMMON = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#define access _access
#define unlink _unlink
#define F_OK 0
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#else
#include <strings.h>
#include <unistd.h>
#endif
typedef void (*update_progress_proc)(void *, unsigned long long, unsigned long long);
static unsigned long long progressed;
static void progress(void *context, unsigned long long received, unsigned long long total)
{ (void)context; (void)total; progressed = received; }
'''


POSIX = r'''
#define UPDATE_USER_AGENT "fixture"
#define MAXIMUM_HEADER_SIZE 16384
#define MAXIMUM_REDIRECTS 8
/* glibc's stdlib headers already declare pthread types. Keep fixture stubs
   distinct, then alias only the production function names being exercised. */
typedef int fixture_pthread_once_t;
#define pthread_once_t fixture_pthread_once_t
#define PTHREAD_ONCE_INIT 0
#define pthread_once fixture_pthread_once
static int fixture_pthread_once(fixture_pthread_once_t *state, void (*callback)(void))
{ if (!*state) { callback(); *state = 1; } return 0; }
static pthread_once_t certificates_once = PTHREAD_ONCE_INIT;
typedef int fixture_pthread_mutex_t;
#define pthread_mutex_t fixture_pthread_mutex_t
#define PTHREAD_MUTEX_INITIALIZER 0
#define pthread_mutex_lock fixture_pthread_mutex_lock
#define pthread_mutex_unlock fixture_pthread_mutex_unlock
static pthread_mutex_t download_lock = PTHREAD_MUTEX_INITIALIZER;
static int pthread_mutex_lock(pthread_mutex_t *lock) { assert(!*lock); *lock=1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *lock) { assert(*lock); *lock=0; return 0; }
static int fixture_transfer_locked(void) { return download_lock != 0; }
static int crypto_ready = 1, certificates_loaded = 1;
static void load_certificates(void) {}
static const char *fixture_strcasestr(const char *text, const char *part)
{
    for (; *text; ++text)
        if (!strncasecmp(text, part, strlen(part))) return text;
    return NULL;
}
#define strcasestr fixture_strcasestr
struct connection { const char *text; size_t at; };
static const char *response;
static int opens, body_reads, redirect_first;
static int connection_open(struct connection *c, const char *host, const char *port, char *error, int error_size)
{
    assert(fixture_transfer_locked());
    (void)host; (void)port; (void)error; (void)error_size;
    c->text = redirect_first && !opens ? "HTTP/1.1 302 Found\r\nLocation: https://example.test/final\r\n\r\n" : response;
    c->at = 0; ++opens; return 1;
}
static void connection_free(struct connection *c) { assert(fixture_transfer_locked()); (void)c; }
static int connection_write(struct connection *c, const char *data, size_t size)
{ (void)c; assert(size && !strncmp(data, "GET ", 4)); return 1; }
static int connection_read_line(struct connection *c, char *line, size_t size)
{
    const char *newline = strchr(c->text + c->at, '\n');
    if (!newline) return 0;
    size_t count = (size_t)(newline - (c->text + c->at));
    if (count && c->text[c->at + count - 1] == '\r') --count;
    if (count >= size) return 0;
    memcpy(line, c->text + c->at, count); line[count] = 0;
    c->at = (size_t)(newline - c->text) + 1; return 1;
}
static int connection_read(struct connection *c, unsigned char *buffer, size_t size)
{
    assert(fixture_transfer_locked());
    ++body_reads;
    size_t left = strlen(c->text + c->at);
    if (size > left) size = left;
    memcpy(buffer, c->text + c->at, size); c->at += size; return (int)size;
}
'''


POSIX_CASES = r'''
static void run_case(const char *path, const char *text, unsigned long long maximum, int expect, unsigned long long last_progress)
{
    char error[512] = {0}; response = text; opens = body_reads = 0; progressed = 0;
    int result = update_download_limited("https://example.test/map", path, maximum, progress, NULL, error, sizeof(error));
    assert(result == expect); assert(progressed == last_progress);
    assert((access(path, F_OK) == 0) == expect);
    if (expect) unlink(path);
}
int main(int argc, char **argv)
{
    assert(argc == 2); const char *path = argv[1];
    run_case(path, "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nHELLO", 5, 1, 5);
    run_case(path, "HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nHELLO!", 5, 0, 0);
    assert(body_reads == 0);
    run_case(path, "HTTP/1.1 200 OK\r\nContent-Length: 4294967296\r\n\r\nHELLO!", 5, 0, 0);
    assert(body_reads == 0);
    run_case(path, "HTTP/1.1 200 OK\r\n\r\nHELLO!", 5, 0, 0);
    run_case(path, "HTTP/1.1 200 OK\r\n\r\nHELLO", 5, 1, 5);
    run_case(path, "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n3\r\ndef\r\n0\r\n\r\n", 5, 0, 3);
    run_case(path, "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nab\r\n3\r\ncde\r\n0\r\n\r\n", 5, 1, 5);
    run_case(path, "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nabc", 5, 0, 3);
    redirect_first = 1;
    run_case(path, "HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nHELLO!", 5, 0, 0); assert(opens == 1);
    char error[512] = {0}; opens = 0; progressed = 0;
    assert(update_download("https://example.test/map", path, progress, NULL, error, sizeof(error)) == 1);
    assert(opens == 2 && progressed == 6); unlink(path);
    struct download d = {0}; d.file = tmpfile(); assert(d.file); d.maximum = ULLONG_MAX; d.received = ULLONG_MAX - 2;
    assert(!body_write(&d, (const unsigned char *)"abc", 3)); assert(d.received == ULLONG_MAX - 2 && ftell(d.file) == 0);
    assert(body_write(&d, (const unsigned char *)"ab", 2)); assert(d.received == ULLONG_MAX && ftell(d.file) == 2);
    fclose(d.file);
    puts("PASS POSIX production cap/length/chunk/truncation/redirect/wrapper/overflow fixture");
    return 0;
}
'''

POSIX_CONCURRENT_CASES = r'''
static pthread_mutex_t start_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t start_changed = PTHREAD_COND_INITIALIZER;
static int ready, go;
struct transfer_fixture { char path[1280]; int index, result; };
static void *transfer_thread(void *context)
{
    struct transfer_fixture *t = context;
    char error[512] = {0};
    pthread_mutex_lock(&start_lock);
    ready++; pthread_cond_broadcast(&start_changed);
    while (!go) pthread_cond_wait(&start_changed, &start_lock);
    pthread_mutex_unlock(&start_lock);
    t->result = update_download_limited(t->index == 7 ? "https://fail.test/map" : "https://example.test/map",
        t->path, 6, progress, NULL, error, sizeof(error));
    return NULL;
}
int main(int argc, char **argv)
{
    pthread_t threads[8];
    struct transfer_fixture transfers[8];
    assert(argc == 2);
    response = "HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nHELLO!";
    for (int i = 0; i < 8; i++) {
        transfers[i].index = i;
        snprintf(transfers[i].path, sizeof(transfers[i].path), "%s.%d", argv[1], i);
        assert(!pthread_create(&threads[i], NULL, transfer_thread, &transfers[i]));
    }
    pthread_mutex_lock(&start_lock);
    while (ready < 8) pthread_cond_wait(&start_changed, &start_lock);
    go = 1; pthread_cond_broadcast(&start_changed);
    pthread_mutex_unlock(&start_lock);
    for (int i = 0; i < 8; i++) {
        assert(!pthread_join(threads[i], NULL));
        assert(transfers[i].result == (i != 7));
        if (i != 7) {
            char bytes[8] = {0}; FILE *file = fopen(transfers[i].path, "rb"); assert(file);
            assert(fread(bytes, 1, 7, file) == 6 && !strcmp(bytes, "HELLO!")); fclose(file); unlink(transfers[i].path);
        }
        else assert(access(transfers[i].path, F_OK) != 0);
    }
    assert(active_transfers == 0 && !overlapping_crypto && opens == 8);
    /* A failed transfer must release the lock for the next independent GET. */
    char error[512] = {0};
    assert(update_download_limited("https://example.test/map", argv[1], 6, progress, NULL, error, sizeof(error)));
    unlink(argv[1]);
    puts("PASS simultaneous metadata/map transfers preserve responses, serialize shared PSA, and release failure locks");
    return 0;
}
'''


WINDOWS = r'''
#include <wchar.h>
typedef uint32_t DWORD;
typedef int BOOL;
typedef void *HINTERNET;
typedef FILE *HANDLE;
typedef struct {
    DWORD dwStructSize; wchar_t *lpszHostName; DWORD dwHostNameLength;
    wchar_t *lpszUrlPath; DWORD dwUrlPathLength; int nScheme; unsigned short nPort;
} URL_COMPONENTS;
#define CP_UTF8 65001
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define INTERNET_SCHEME_HTTPS 2
#define UPDATE_USER_AGENT L"fixture"
#define TIMEOUT_MILLISECONDS 20000
#define WINHTTP_ACCESS_TYPE_DEFAULT_PROXY 0
#define WINHTTP_NO_PROXY_NAME NULL
#define WINHTTP_NO_PROXY_BYPASS NULL
#define WINHTTP_NO_REFERER NULL
#define WINHTTP_DEFAULT_ACCEPT_TYPES NULL
#define WINHTTP_NO_ADDITIONAL_HEADERS NULL
#define WINHTTP_NO_REQUEST_DATA NULL
#define WINHTTP_HEADER_NAME_BY_INDEX NULL
#define WINHTTP_NO_HEADER_INDEX NULL
#define WINHTTP_FLAG_SECURE 0x00800000
#define WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_2 0x00000800
#define WINHTTP_FLAG_SECURE_PROTOCOL_TLS1_3 0x00002000
#define WINHTTP_OPTION_SECURE_PROTOCOLS 84
#define WINHTTP_OPTION_REDIRECT_POLICY 88
#define WINHTTP_OPTION_REDIRECT_POLICY_NEVER 0
#define WINHTTP_QUERY_STATUS_CODE 19
#define WINHTTP_QUERY_CONTENT_LENGTH 5
#define WINHTTP_QUERY_FLAG_NUMBER 0x20000000
#define ERROR_WINHTTP_HEADER_NOT_FOUND 12150
#define ERROR_INSUFFICIENT_BUFFER 122
#define ERROR_WINHTTP_INTERNAL_ERROR 12004
#define GENERIC_WRITE 0x40000000
#define CREATE_ALWAYS 2
#define FILE_ATTRIBUTE_NORMAL 0x00000080
static DWORD last_error, status_code;
static const char *header, *body;
static size_t body_at, read_chunk;
static int sent, reads, writes, creates, deletes, redirect_set, fail_redirect, fail_header, fail_read, short_write;
static DWORD GetLastError(void) { return last_error; }
static int MultiByteToWideChar(unsigned page, DWORD flags, const char *text, int length, wchar_t *wide, int capacity)
{
    (void)flags; assert(page == CP_UTF8 && length == -1);
    size_t count = mbstowcs(wide, text, (size_t)capacity);
    return count != (size_t)-1 && count < (size_t)capacity ? (int)count + 1 : 0;
}
static BOOL WinHttpCrackUrl(const wchar_t *url, DWORD length, DWORD flags, URL_COMPONENTS *c)
{
    (void)length; (void)flags;
    c->nScheme = wcsncmp(url, L"https://", 8) ? 1 : INTERNET_SCHEME_HTTPS;
    wcscpy(c->lpszHostName, L"example.test"); wcscpy(c->lpszUrlPath, L"/map"); c->nPort = 443; return 1;
}
static HINTERNET WinHttpOpen(const wchar_t *agent, DWORD access, const wchar_t *proxy, const wchar_t *bypass, DWORD flags)
{ (void)agent; (void)access; (void)proxy; (void)bypass; (void)flags; return (HINTERNET)(intptr_t)1; }
static BOOL WinHttpSetOption(HINTERNET handle, DWORD option, void *value, DWORD size)
{
    assert(size == sizeof(DWORD));
    if (option == WINHTTP_OPTION_REDIRECT_POLICY) {
        assert(handle == (HINTERNET)(intptr_t)3 && !sent);
        assert(*(DWORD *)value == WINHTTP_OPTION_REDIRECT_POLICY_NEVER);
        if (fail_redirect) { last_error = ERROR_WINHTTP_INTERNAL_ERROR; return 0; }
        redirect_set = 1;
    } else assert(option == WINHTTP_OPTION_SECURE_PROTOCOLS);
    return 1;
}
static BOOL WinHttpSetTimeouts(HINTERNET h, int a, int b, int c, int d)
{ (void)h; assert(a > 0 && b > 0 && c > 0 && d > 0); return 1; }
static HINTERNET WinHttpConnect(HINTERNET h, const wchar_t *host, unsigned short port, DWORD flags)
{ (void)h; (void)host; (void)port; (void)flags; return (HINTERNET)(intptr_t)2; }
static HINTERNET WinHttpOpenRequest(HINTERNET h, const wchar_t *verb, const wchar_t *path,
    const wchar_t *version, const wchar_t *referer, const wchar_t **accept, DWORD flags)
{
    (void)h; (void)path; (void)version; (void)referer; (void)accept;
    assert(!wcscmp(verb, L"GET") && flags == WINHTTP_FLAG_SECURE); return (HINTERNET)(intptr_t)3;
}
static BOOL WinHttpSendRequest(HINTERNET h, const wchar_t *headers, DWORD count, void *data, DWORD size, DWORD total, uintptr_t context)
{ (void)h; (void)headers; (void)count; (void)data; (void)size; (void)total; (void)context; ++sent; return 1; }
static BOOL WinHttpReceiveResponse(HINTERNET h, void *context) { (void)h; (void)context; return 1; }
static BOOL WinHttpQueryHeaders(HINTERNET h, DWORD query, const wchar_t *name, void *output, DWORD *size, DWORD *index)
{
    (void)h; (void)name; (void)index;
    if (query == (WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER)) {
        assert(*size == sizeof(DWORD)); *(DWORD *)output = status_code; return 1;
    }
    if (fail_header) { last_error = ERROR_WINHTTP_INTERNAL_ERROR; return 0; }
    if (!header) { last_error = ERROR_WINHTTP_HEADER_NOT_FOUND; return 0; }
    if (query == (WINHTTP_QUERY_CONTENT_LENGTH | WINHTTP_QUERY_FLAG_NUMBER)) {
        assert(!redirect_set && *size == sizeof(DWORD)); *(DWORD *)output = (DWORD)strtoul(header, NULL, 10); return 1;
    }
    assert(query == WINHTTP_QUERY_CONTENT_LENGTH && redirect_set);
    size_t bytes = (strlen(header) + 1) * sizeof(wchar_t);
    if (bytes > *size) { *size = (DWORD)bytes; last_error = ERROR_INSUFFICIENT_BUFFER; return 0; }
    assert(mbstowcs(output, header, *size / sizeof(wchar_t)) != (size_t)-1);
    *size = (DWORD)(bytes - sizeof(wchar_t)); return 1;
}
static BOOL WinHttpReadData(HINTERNET h, void *buffer, DWORD capacity, DWORD *count)
{
    (void)h; ++reads;
    if (fail_read && body_at) { last_error = ERROR_WINHTTP_INTERNAL_ERROR; return 0; }
    size_t wanted = strlen(body + body_at);
    if (wanted > capacity) wanted = capacity;
    if (wanted > read_chunk) wanted = read_chunk;
    memcpy(buffer, body + body_at, wanted); body_at += wanted; *count = (DWORD)wanted; return 1;
}
static BOOL WinHttpCloseHandle(HINTERNET h) { (void)h; return 1; }
static void narrow_path(const wchar_t *wide, char *path, size_t capacity)
{ size_t count = wcstombs(path, wide, capacity); assert(count != (size_t)-1 && count < capacity); }
static HANDLE CreateFileW(const wchar_t *path, DWORD access, DWORD share, void *security, DWORD creation, DWORD flags, HANDLE template_file)
{
    (void)share; (void)security; (void)flags; (void)template_file; assert(access == GENERIC_WRITE && creation == CREATE_ALWAYS);
    ++creates; char narrow[2048]; narrow_path(path, narrow, sizeof(narrow));
    FILE *result = fopen(narrow, "wb"); return result ? result : INVALID_HANDLE_VALUE;
}
static BOOL WriteFile(HANDLE file, const void *data, DWORD count, DWORD *written, void *overlapped)
{
    (void)overlapped; ++writes;
    *written = (DWORD)fwrite(data, 1, short_write && count ? count - 1 : count, file); return 1;
}
static BOOL CloseHandle(HANDLE file) { return fclose(file) == 0; }
static BOOL DeleteFileW(const wchar_t *path)
{ ++deletes; char narrow[2048]; narrow_path(path, narrow, sizeof(narrow)); return unlink(narrow) == 0; }
'''


WINDOWS_CASES = r'''
static void reset(void)
{
    last_error = 0; status_code = 200; body_at = 0; read_chunk = 3;
    sent = reads = writes = creates = deletes = redirect_set = fail_redirect = fail_header = fail_read = short_write = 0;
    progressed = 0;
}
static void run_case(const char *path, const char *length, const char *text, unsigned long long maximum,
    int expect, unsigned long long last_progress)
{
    char error[512] = {0}; header = length; body = text;
    int result = update_download_limited("https://example.test/map", path, maximum, progress, NULL, error, sizeof(error));
    assert(result == expect && progressed == last_progress);
    assert(redirect_set || fail_redirect || !maximum);
    assert((access(path, F_OK) == 0) == expect);
    if (expect) unlink(path);
}
int main(int argc, char **argv)
{
    assert(argc == 2); const char *path = argv[1];
    reset(); run_case(path, "5", "HELLO", 5, 1, 5); assert(creates == 1 && writes == 2);
    const char *invalid[] = {"6", "4294967296", "18446744073709551615", "18446744073709551616",
        "", "-1", "+5", "5x", "5,5", " 5", "99999999999999999999999999999999999999999999999999999999999999999999"};
    for (size_t i = 0; i < sizeof(invalid) / sizeof(*invalid); ++i) {
        reset(); run_case(path, invalid[i], "HELLO", 5, 0, 0); assert(!reads && !writes && !creates && !deletes);
    }
    reset(); run_case(path, NULL, "HELLO", 5, 1, 5);
    reset(); run_case(path, NULL, "HELLO!", 5, 0, 3); assert(writes == 1 && deletes == 1);
    reset(); run_case(path, "5", "abc", 5, 0, 3); assert(deletes == 1);
    reset(); run_case(path, "0", "", 5, 1, 0);
    reset(); run_case(path, "0", "x", 5, 0, 1); assert(deletes == 1);
    reset(); status_code = 302; run_case(path, NULL, "", 5, 0, 0); assert(sent == 1 && !reads && !creates);
    reset(); fail_redirect = 1; run_case(path, NULL, "", 5, 0, 0); assert(!sent && !reads && !creates);
    reset(); fail_header = 1; run_case(path, NULL, "", 5, 0, 0); assert(!reads && !creates);
    reset(); fail_read = 1; run_case(path, "5", "HELLO", 5, 0, 3); assert(writes == 1 && deletes == 1);
    reset(); short_write = 1; run_case(path, "5", "HELLO", 5, 0, 0); assert(writes == 1 && deletes == 1);
    reset(); header = "6"; body = "HELLO!";
    char error[512] = {0};
    assert(update_download("https://example.test/map", path, progress, NULL, error, sizeof(error)) == 1);
    assert(!redirect_set && progressed == 6 && sent == 1); unlink(path);
    puts("PASS Windows production wide-header/cap/truncation/redirect-option/wrapper/cleanup fixture");
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang is required for the production C fixtures")
class DownloadTransportLimitTests(unittest.TestCase):
    def compile_and_run(self, name, fixture, extra_flags=()):
        with tempfile.TemporaryDirectory(prefix="halo-download-transport-test-") as directory:
            root = Path(directory).resolve()
            source = root / (name + ".c")
            binary = root / (name + (".exe" if sys.platform == "win32" else ""))
            source.write_text(COMMON + fixture, encoding="utf-8")
            command = ["clang", "-std=gnu11", "-Wall", "-Wextra", "-Werror", *extra_flags]
            if sys.platform == "win32":
                command += ["-D_CRT_SECURE_NO_WARNINGS"]
            else:
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            compiled = subprocess.run(command + [str(source), "-o", str(binary)], capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary), str(root / "download.tmp")], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS", result.stdout)
            self.assertFalse((root / "download.tmp").exists())

    def test_posix_production_response_limits_and_legacy_wrapper(self):
        source = (ROOT / "port/linux/src/posix_update.c").read_text(encoding="utf-8")
        signatures = ("static int parse_url(", "struct download\n{", "static int body_write(",
                      "static int read_body(", "static int https_get(", "static int update_download_serialized(", "int update_download_limited(",
                      "int update_download(")
        pieces = [function(source, signature) + (";" if signature.startswith("struct") else "")
                  for signature in signatures]
        self.compile_and_run("posix", POSIX + "\n".join(pieces) + POSIX_CASES)

    def test_windows_production_header_limits_and_request_flags(self):
        source = (ROOT / "port/windows/src/win32_update.c").read_text(encoding="utf-8")
        signatures = ("static int wide_from_utf8(", "static void set_error(",
                      "int update_download_limited(", "int update_download(")
        pieces = [function(source, signature) for signature in signatures]
        self.compile_and_run("windows", WINDOWS + "\n".join(pieces) + WINDOWS_CASES)

    @unittest.skipIf(sys.platform == "win32", "POSIX concurrency uses the native pthread backend")
    def test_simultaneous_map_and_release_transfers_serialize_psa_and_keep_individual_responses(self):
        source = (ROOT / "port/linux/src/posix_update.c").read_text(encoding="utf-8")
        signatures = ("static int parse_url(", "struct download\n{", "static int body_write(",
                      "static int read_body(", "static int https_get(", "static int update_download_serialized(",
                      "int update_download_limited(", "int update_download(")
        pieces = [function(source, signature) + (";" if signature.startswith("struct") else "") for signature in signatures]
        start = POSIX.index("/* glibc's stdlib headers")
        end = POSIX.index("static int crypto_ready")
        native = (POSIX[:start] + "#include <pthread.h>\n#include <time.h>\n"
                  "static pthread_once_t certificates_once = PTHREAD_ONCE_INIT;\n"
                  "static pthread_mutex_t download_lock = PTHREAD_MUTEX_INITIALIZER;\n"
                  "static int fixture_transfer_locked(void) { int result=pthread_mutex_trylock(&download_lock); "
                  "if (!result) pthread_mutex_unlock(&download_lock); return result == EBUSY; }\n"
                  "static int active_transfers, overlapping_crypto;\n" + POSIX[end:])
        native = native.replace("c->text = redirect_first", """
    if (__atomic_add_fetch(&active_transfers, 1, __ATOMIC_SEQ_CST) > 1)
        __atomic_store_n(&overlapping_crypto, 1, __ATOMIC_SEQ_CST);
    struct timespec pause = {0, 10000000}; nanosleep(&pause, NULL);
    c->text = redirect_first""")
        native = native.replace("c->at = 0; ++opens; return 1;", "c->at = 0; ++opens; return !strstr(host, \"fail.test\");")
        native = native.replace("static void connection_free(struct connection *c) { assert(fixture_transfer_locked()); (void)c; }",
                                "static void connection_free(struct connection *c) { assert(fixture_transfer_locked()); (void)c; __atomic_sub_fetch(&active_transfers, 1, __ATOMIC_SEQ_CST); }")
        self.compile_and_run("concurrent", native + "\n".join(pieces) + POSIX_CONCURRENT_CASES, extra_flags=("-pthread",))


if __name__ == "__main__":
    unittest.main()
