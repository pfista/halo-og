/* Byte-level compatibility and malformed-input checks for reliable cache identity. */
#include "networking/network_expanded_cache_protocol.h"
#include <assert.h>
#include <stdio.h>

static void rejected(unsigned char const *packet, unsigned size, unsigned kind)
{
    struct network_expanded_cache_identity identity, before;
    memset(&identity, 0xA5, sizeof(identity)); before = identity;
    assert(!network_expanded_cache_decode(packet, size, kind, &identity));
    assert(!memcmp(&identity, &before, sizeof(identity)));
}

int main(void)
{
    unsigned char packet[NETWORK_EXPANDED_CACHE_MESSAGE_SIZE], broken[NETWORK_EXPANDED_CACHE_MESSAGE_SIZE];
    struct native_map_cache_selection selection = {0};
    struct network_expanded_cache_identity identity;
    unsigned kind, set, i;
    selection.expanded = 1; selection.generation = HALO_EXPANDED_CACHE_GENERATION;
    strcpy(selection.logical_name, "prisoner"); strcpy(selection.physical_name, "_fiesta_prisoner");
    for (i = 0; i < 32; i++) {
        selection.sha256[i] = (unsigned char)(i + 1);
        selection.weapon_list_sha256[i] = (unsigned char)(255 - i);
    }
    /* A pending heartbeat carries the same immutable identity but is never
       interchangeable with an offer or an asset-ready acknowledgement. */
    strcpy(selection.physical_path, "m:\\arsenal\\v1\\_fiesta_prisoner.map");
    for (kind = 1; kind <= 3; kind++) for (set = 14; set <= 15; set++) {
        network_expanded_cache_encode(packet, kind, &selection, set);
        assert(network_expanded_cache_decode(packet, sizeof(packet), kind, &identity));
        assert(identity.weapon_set == set && identity.selection.expanded == 1);
        assert(identity.selection.generation == selection.generation);
        assert(!strcmp(identity.selection.logical_name, selection.logical_name));
        assert(!strcmp(identity.selection.physical_name, selection.physical_name));
        assert(!memcmp(identity.selection.sha256, selection.sha256, 32));
        assert(!memcmp(identity.selection.weapon_list_sha256, selection.weapon_list_sha256, 32));
        assert(identity.selection.physical_path[0] == 0);
        for (i = 0; i < sizeof(packet); i++) rejected(packet, i, kind);
        rejected(packet, sizeof(packet) + 1, kind);
        for (unsigned other = 1; other <= 3; other++)
            if (other != kind) rejected(packet, sizeof(packet), other);
        rejected(packet, sizeof(packet), 0); rejected(packet, sizeof(packet), 4);
        rejected(NULL, sizeof(packet), kind);
        assert(!network_expanded_cache_decode(packet, sizeof(packet), kind, NULL));
        for (i = 0; i < sizeof(packet); i++) {
            if (i >= 16 && i < 144) continue;
            memcpy(broken, packet, sizeof(packet)); broken[i] ^= 0x80;
            rejected(broken, sizeof(broken), kind);
        }
        /* Neither unterminated fields, unsafe paths nor ignored trailing bytes
           can be interpreted as a different immutable cache selection. */
        memcpy(broken, packet, sizeof(packet)); memset(broken + 16, 'a', 32); rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); memset(broken + 48, 'a', 32); rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[16] = '/'; rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[16] = 'P'; rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[56] = '/'; rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[47] = 'x'; rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[79] = 'x'; rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[16] = 0; rejected(broken, sizeof(broken), kind);
        memcpy(broken, packet, sizeof(packet)); broken[15] = 10; rejected(broken, sizeof(broken), kind);
        /* The whole digest is carried, including its final bytes. Validation
           against actual installed content belongs to the engine preflight. */
        memcpy(broken, packet, sizeof(packet)); broken[111] ^= 1; broken[143] ^= 1;
        assert(network_expanded_cache_decode(broken, sizeof(broken), kind, &identity));
        assert(identity.selection.sha256[31] != selection.sha256[31]);
        assert(identity.selection.weapon_list_sha256[31] != selection.weapon_list_sha256[31]);
    }
    strcpy(selection.logical_name, "a community map with long name");
    strcpy(selection.physical_name, "_fiestah_1234567890abcdef");
    network_expanded_cache_encode(packet, 1, &selection, 15);
    assert(network_expanded_cache_decode(packet, sizeof(packet), 1, &identity));
    assert(!strcmp(identity.selection.logical_name, selection.logical_name));
    assert(!strcmp(identity.selection.physical_name, selection.physical_name));
    puts("expanded cache protocol: PASS");
    return 0;
}
