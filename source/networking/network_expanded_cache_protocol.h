/* Reliable full-cache identity and readiness beside the unchanged v11 record. */
#ifndef NETWORK_EXPANDED_CACHE_PROTOCOL_H
#define NETWORK_EXPANDED_CACHE_PROTOCOL_H

#include "halo_expanded_cache.h"
#include <string.h>

#define NETWORK_EXPANDED_CACHE_MESSAGE_TYPE 0xE1
#define NETWORK_EXPANDED_CACHE_MESSAGE_SIZE 160
#define NETWORK_EXPANDED_CACHE_OFFER 1
#define NETWORK_EXPANDED_CACHE_READY 2
#define NETWORK_EXPANDED_CACHE_DOWNLOAD_PENDING 3

struct network_expanded_cache_identity
{
    struct native_map_cache_selection selection;
    unsigned weapon_set;
};

static inline void network_expanded_cache_encode(unsigned char *message, unsigned kind,
    struct native_map_cache_selection const *selection, unsigned weapon_set)
{
    memset(message, 0, NETWORK_EXPANDED_CACHE_MESSAGE_SIZE);
    message[0] = 8; message[1] = 10;
    message[2] = NETWORK_EXPANDED_CACHE_MESSAGE_TYPE; message[3] = 1;
    message[8] = 'H'; message[9] = 'A'; message[10] = 'E'; message[11] = 'C';
    message[12] = 1; message[13] = (unsigned char)kind;
    message[14] = (unsigned char)selection->generation;
    message[15] = (unsigned char)weapon_set;
    memcpy(message + 16, selection->logical_name, 32);
    memcpy(message + 48, selection->physical_name, 32);
    memcpy(message + 80, selection->sha256, 32);
    memcpy(message + 112, selection->weapon_list_sha256, 32);
}

static inline int network_expanded_cache_decode(unsigned char const *message, unsigned size,
    unsigned kind, struct network_expanded_cache_identity *identity)
{
    unsigned i, length = 0;
    unsigned physical_length = 0;
    struct network_expanded_cache_identity decoded;
    if (!message || !identity || size != NETWORK_EXPANDED_CACHE_MESSAGE_SIZE ||
        (kind != NETWORK_EXPANDED_CACHE_OFFER && kind != NETWORK_EXPANDED_CACHE_READY &&
         kind != NETWORK_EXPANDED_CACHE_DOWNLOAD_PENDING) ||
        message[0] != 8 || message[1] != 10 || message[2] != NETWORK_EXPANDED_CACHE_MESSAGE_TYPE || message[3] != 1 ||
        message[8] != 'H' || message[9] != 'A' || message[10] != 'E' || message[11] != 'C' ||
        message[12] != 1 || message[13] != kind || message[14] != HALO_EXPANDED_CACHE_GENERATION ||
        (message[15] != 11 && message[15] != 12)) return 0;
    for (i = 4; i < 8; i++) if (message[i]) return 0;
    for (i = 144; i < NETWORK_EXPANDED_CACHE_MESSAGE_SIZE; i++) if (message[i]) return 0;
    while (length < 32 && message[16 + length]) {
        unsigned char c = message[16 + length++];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == ' ')) return 0;
    }
    if (!length || length >= 32) return 0;
    for (i = length; i < 32; i++) if (message[16 + i]) return 0;
    while (physical_length < 32 && message[48 + physical_length]) {
        unsigned char c = message[48 + physical_length++];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == ' ')) return 0;
    }
    if (physical_length <= 8 || physical_length >= 32) return 0;
    for (i = physical_length; i < 32; i++) if (message[48 + i]) return 0;
    if (memcmp(message + 48, "_fiesta_", 8) && memcmp(message + 48, "_fiestah_", 9)) return 0;
    memset(&decoded, 0, sizeof(decoded));
    decoded.selection.expanded = 1;
    decoded.selection.generation = message[14];
    decoded.weapon_set = message[15];
    memcpy(decoded.selection.logical_name, message + 16, 32);
    memcpy(decoded.selection.physical_name, message + 48, 32);
    memcpy(decoded.selection.sha256, message + 80, 32);
    memcpy(decoded.selection.weapon_list_sha256, message + 112, 32);
    *identity = decoded;
    return 1;
}

#endif
