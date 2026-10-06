#include <windows.h>
#include <winhttp.h>
#include <stdio.h>
#include <string.h>
#include "game_directory.h"
#include "directory_retry_after.h"

int halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status, int *retry_after_seconds)
{
    wchar_t wide_url[512], wide_method[16], host[256], path[320], authorization[128];
    URL_COMPONENTS parts = {0};
    HINTERNET session = NULL, connection = NULL, request = NULL;
    DWORD code = 0, bytes = sizeof(code), redirect = WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
    int result = -1, size = 0;
    if (status) *status = 0;
    if (retry_after_seconds) *retry_after_seconds = 0;
    if (!status || !method || !url || !response || capacity < 2 || capacity > HALO_DIRECTORY_BODY_LIMIT ||
        (body && strlen(body) > 4096) ||
        (lease && *lease && (strlen(lease) != 64 || strspn(lease, "0123456789abcdef") != 64)) ||
        !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, url, -1, wide_url, 512) ||
        !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, method, -1, wide_method, 16)) return -1;
    parts.dwStructSize = sizeof(parts); parts.lpszHostName = host; parts.dwHostNameLength = 256;
    parts.lpszUrlPath = path; parts.dwUrlPathLength = 320;
    if (!WinHttpCrackUrl(wide_url, 0, 0, &parts) || parts.nScheme != INTERNET_SCHEME_HTTPS) return -1;
    session = WinHttpOpen(L"Halo-OG-game-directory", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) goto done;
    WinHttpSetTimeouts(session, 5000, 5000, 5000, 5000);
    connection = WinHttpConnect(session, host, parts.nPort, 0);
    if (!connection) goto done;
    request = WinHttpOpenRequest(connection, wide_method, path, NULL, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE);
    if (!request || !WinHttpSetOption(request, WINHTTP_OPTION_REDIRECT_POLICY, &redirect, sizeof(redirect))) goto done;
    if (!WinHttpAddRequestHeaders(request, L"Content-Type: application/json\r\nAccept: application/json",
        (DWORD)-1L, WINHTTP_ADDREQ_FLAG_ADD)) goto done;
    if (lease && *lease) {
        char ascii[128]; snprintf(ascii, sizeof(ascii), "Authorization: Bearer %s", lease);
        if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, ascii, -1, authorization, 128) ||
            !WinHttpAddRequestHeaders(request, authorization, (DWORD)-1L, WINHTTP_ADDREQ_FLAG_ADD)) goto done;
    }
    if (!WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, (void *)body,
        body ? (DWORD)strlen(body) : 0, body ? (DWORD)strlen(body) : 0, 0) ||
        !WinHttpReceiveResponse(request, NULL) ||
        !WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
            WINHTTP_HEADER_NAME_BY_INDEX, &code, &bytes, WINHTTP_NO_HEADER_INDEX)) goto done;
    *status = (int)code;
    if (retry_after_seconds) {
        wchar_t header[64] = {0}; char value[64] = {0};
        DWORD header_bytes = sizeof(header);
        if (WinHttpQueryHeaders(request, WINHTTP_QUERY_CUSTOM, L"Retry-After", header,
            &header_bytes, WINHTTP_NO_HEADER_INDEX)) {
            unsigned i;
            for (i = 0; i < 63 && header[i]; i++) {
                if (header[i] > 127) break;
                value[i] = (char)header[i];
            }
            if (!header[i]) *retry_after_seconds = halo_directory_retry_after_seconds(value);
        }
    }
    for (;;) {
        unsigned char chunk[4096]; DWORD received = 0;
        if (!WinHttpReadData(request, chunk, sizeof(chunk), &received) ||
            received > (unsigned)(capacity - 1 - size)) goto done;
        if (!received) break;
        memcpy(response + size, chunk, received); size += (int)received;
    }
    response[size] = 0; result = size;
done:
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    if (session) WinHttpCloseHandle(session);
    return result;
}
