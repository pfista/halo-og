/* Portable protocol regression checks. No game data, engine, or network needed.
 * cc -std=c11 -Wall -Wextra -Werror -Isource port/macos/tests/performance_network.c -o /tmp/performance-network-test
 */
#include "networking/network_performance_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

/* Earlier hosts accept only v1 and the flags known to their generation. */
static int legacy_decode(unsigned char const *message, unsigned mask, unsigned *flags)
{
    return message[12] == 1 && message[15] == 0 && !(message[13] & ~mask) &&
        network_performance_decode(message, NETWORK_PERFORMANCE_MESSAGE_SIZE,
            NETWORK_PERFORMANCE_CAPABILITY, flags);
}

/* The previous Camo build rejects v3 and retains its last v1/v2 announcement. */
static int camo_decode(unsigned char const *message, unsigned *flags)
{
    return ((message[12] == 1 && message[15] == 0) ||
        (message[12] == 2 && message[15] == 1)) &&
        network_performance_decode(message, NETWORK_PERFORMANCE_MESSAGE_SIZE,
            NETWORK_PERFORMANCE_CAPABILITY, flags);
}

/* Map-local expanded builds retain v3 before the global-arsenal v4 frame. */
static int expanded_decode(unsigned char const *message, unsigned *flags)
{
    return message[12] <= 3 &&
        network_performance_decode(message, NETWORK_PERFORMANCE_MESSAGE_SIZE,
            NETWORK_PERFORMANCE_CAPABILITY, flags);
}

/* An installed-arsenal v4 peer retains its last capability before v5 wait. */
static int global_decode(unsigned char const *message, unsigned *flags)
{
    return message[12] <= 4 &&
        network_performance_decode(message, NETWORK_PERFORMANCE_MESSAGE_SIZE,
            NETWORK_PERFORMANCE_CAPABILITY, flags);
}

/* Download-wait v5 peers ignore actor-only audio's v6 announcement. */
static int download_wait_decode(unsigned char const *message, unsigned *flags)
{
    return message[12] <= 5 &&
        network_performance_decode(message, NETWORK_PERFORMANCE_MESSAGE_SIZE,
            NETWORK_PERFORMANCE_CAPABILITY, flags);
}

int main(void)
{
    unsigned char message[NETWORK_PERFORMANCE_MESSAGE_SIZE];
    unsigned char damaged[NETWORK_PERFORMANCE_MESSAGE_SIZE];
    unsigned flags, supported, kind, index;

    assert(network_performance_runtime_supported_flags(0,0)==27);
    assert(network_performance_runtime_supported_flags(0,1)==31);
    assert(network_performance_runtime_supported_flags(1,0)==32763);
    assert(network_performance_runtime_supported_flags(1,1)==32767);
    assert(network_performance_capability_for_peer(1023,0,0,0,0,0,0,0,0)==63);
    assert(network_performance_capability_for_peer(1023,1,0,0,0,0,0,0,0)==127);
    assert(network_performance_capability_for_peer(1023,1,1,0,0,0,0,0,0)==255);
    assert(network_performance_capability_for_peer(1019,1,1,0,0,0,0,0,0)==251);
    assert(network_performance_capability_for_peer(1023,1,1,1,0,0,0,0,0)==511);
    assert(network_performance_capability_for_peer(1019,1,1,1,0,0,0,0,0)==507);
    assert(network_performance_capability_for_peer(1023,1,1,1,1,0,0,0,0)==1023);
    assert(network_performance_capability_for_peer(1019,1,1,1,1,0,0,0,0)==1019);
    assert(network_performance_capability_for_peer(2047,1,1,1,1,1,0,0,0)==2047);
    assert(network_performance_capability_for_peer(2043,1,1,1,1,1,0,0,0)==2043);
    assert(network_performance_capability_for_peer(2047,1,1,1,1,0,0,0,0)==1023);
    assert(network_performance_capability_for_peer(4095,1,1,1,1,1,0,0,0)==2047);
    assert(network_performance_capability_for_peer(4095,1,1,1,1,1,1,0,0)==4095);
    assert(network_performance_capability_for_peer(4091,1,1,1,1,1,1,0,0)==4091);
    assert(network_performance_capability_for_peer(16383,1,1,1,1,1,1,0,0)==4095);
    assert(network_performance_capability_for_peer(16383,1,1,1,1,1,1,1,0)==16383);
    assert(network_performance_capability_for_peer(16379,1,1,1,1,1,1,1,0)==16379);
    for (flags=0;flags<=511;flags++) {
        assert(network_performance_host_settings_flags(flags,0)==((flags & 480) ? 0 : flags));
        assert(network_performance_host_settings_flags(flags,31)==((flags & 480) ? 0 : flags));
        assert(network_performance_host_settings_flags(flags,63)==((flags & 448) ? 0 : flags));
        assert(network_performance_host_settings_flags(flags,127)==((flags & 384) ? 0 : flags));
        assert(network_performance_host_settings_flags(flags,255)==((flags & 256) ? 0 : flags));
        assert(network_performance_host_settings_flags(flags,511)==flags);
    }
    for (flags=4096; flags<=12799; flags++) {
        if (flags & ~12799u) continue;
        assert(network_performance_host_settings_flags(flags,4095)==0);
        assert(network_performance_host_settings_flags(flags,16383)==flags);
    }

    /* Stock v10 retains admission in either direction with every option off;
     * every enabled combination requires precisely its supported bits. */
    for (flags = 0; flags <= 4095; ++flags) {
        unsigned version = network_performance_advertised_version(flags, 10);
        assert((version == 10) == (flags == 0));
        assert(network_performance_version_compatible(version,
            3 | NETWORK_PERFORMANCE_ADVERTISED_FLAG, 10));
        assert(network_performance_version_compatible(10, 1, 10));
        if (flags) assert(!network_performance_version_compatible(version, 1, 10));
        for (supported = 0; supported <= 4095; ++supported)
            assert(network_performance_can_join(flags, supported) == ((flags & supported) == flags));
    }
    assert(!network_performance_can_join(256, 255));
    assert(network_performance_can_join(256, 511));
    assert(!network_performance_can_join(512, 511));
    assert(network_performance_can_join(512, 1023));
    assert(!network_performance_can_join(640, 511));
    assert(network_performance_can_join(640, 1023));
    assert(!network_performance_can_join(1024, 1023));
    assert(network_performance_can_join(1024, 2047));
    assert(!network_performance_can_join(1664, 1023));
    assert(network_performance_can_join(1664, 2047));
    assert(network_performance_can_join(2048, 4095));
    assert(!network_performance_can_join(2048, 2047));
    assert(!network_performance_can_join(4096, 4095));
    assert(network_performance_can_join(4096, 8191));
    assert(!network_performance_can_join(8192, 8191));
    assert(network_performance_can_join(8192, 16383));
    assert(!network_performance_can_join(12288, 8191));
    assert(network_performance_can_join(12288, 16383));
    assert(network_performance_can_join(16384, 32767));
    assert(!network_performance_can_join(16384, 16383));
    assert(!network_performance_can_join(32768, 65535));
    /* The prior timer/marker client can still join those modes, but cannot
     * join or remain in a session where the host enables timer audio. */
    assert(network_performance_can_join(3, 3));
    assert(!network_performance_can_join(4, 3));
    assert(!network_performance_can_join(7, 3));
    assert(network_performance_can_join(7, 7));
    assert(!network_performance_can_join(8, 7));
    assert(!network_performance_can_join(16, 7));
    assert(network_performance_can_join(24, 31));
    assert(!network_performance_can_join(32, 31));
    assert(!network_performance_can_join(63, 31));
    assert(network_performance_can_join(32, 63));
    assert(network_performance_can_join(63, 63));
    assert(!network_performance_can_join(128, 127));
    assert(!network_performance_can_join(255, 127));
    assert(network_performance_can_join(128, 255));
    assert(network_performance_can_join(255, 255));
    assert(!network_performance_version_compatible(9, 3, 10));
    assert(!network_performance_version_compatible(11, 3, 10));

    /* The reliable pre-join sequence gives a prior PB host the supported
     * subset before current capabilities. The earlier v1 decoder has the
     * same packet format but rejects any payload flag outside mask 3. */
    {
        const unsigned capabilities[] = {3, 7, 31, 63, 127, 255, 511, 1023, 2047, 4095, 16383, NETWORK_PERFORMANCE_SUPPORTED_CAPABILITIES};
        unsigned prior_host_support = 0, audio_host_support = 0, sound_host_support = 0;
        unsigned delay_host_support = 0, hardcore_host_support = 0, fiesta_host_support = 0, camo_host_support = 0, expanded_host_support = 0, global_host_support = 0, wait_host_support = 0, current_host_support = 0;
        for (index = 0; index < sizeof(capabilities) / sizeof(capabilities[0]); ++index) {
            network_performance_encode(message, NETWORK_PERFORMANCE_CAPABILITY, capabilities[index]);
            assert(network_performance_decode(message, sizeof(message), NETWORK_PERFORMANCE_CAPABILITY,
                &current_host_support));
            legacy_decode(message, 255, &fiesta_host_support);
            camo_decode(message, &camo_host_support);
            expanded_decode(message, &expanded_host_support);
            global_decode(message, &global_host_support);
            download_wait_decode(message, &wait_host_support);
            legacy_decode(message, 127, &hardcore_host_support);
            legacy_decode(message, 63, &delay_host_support);
            legacy_decode(message, 31, &sound_host_support);
            legacy_decode(message, 7, &audio_host_support);
            legacy_decode(message, 3, &prior_host_support);
        }
        assert(prior_host_support == 3 && audio_host_support == 7 &&
            sound_host_support == 31 && delay_host_support == 63 &&
            hardcore_host_support == 127 && fiesta_host_support == 255 &&
            camo_host_support == 511 && expanded_host_support == 1023 && global_host_support == 2047 &&
            wait_host_support == 4095 && current_host_support == 32767);
    }

    for (kind = NETWORK_PERFORMANCE_CAPABILITY; kind <= NETWORK_PERFORMANCE_SETTINGS; ++kind) {
        unsigned maximum_flags = kind == NETWORK_PERFORMANCE_CAPABILITY ?
            NETWORK_PERFORMANCE_SUPPORTED_CAPABILITIES : NETWORK_PERFORMANCE_SUPPORTED_FLAGS;
        for (flags = 0; flags <= maximum_flags; ++flags) {
            unsigned decoded = 99;
            network_performance_encode(message, kind, flags);
            if ((flags & ~maximum_flags) ||
                (kind == NETWORK_PERFORMANCE_SETTINGS &&
                 !network_performance_settings_flags_valid(flags))) {
                assert(!network_performance_decode(message, sizeof(message), kind, &decoded));
                assert(decoded==99);
                continue;
            }
            assert(network_performance_decode(message, sizeof(message), kind, &decoded));
            assert(decoded == flags);
            if (flags <= 255) {
                unsigned char legacy[16] = {8,1,0xE0,1,0,0,0,0,'H','P','F','O',1,0,0,0};
                legacy[13] = (unsigned char)flags; legacy[14] = (unsigned char)kind;
                assert(!memcmp(message, legacy, sizeof(message)));
            } else if (flags <= 511) {
                assert(message[12] == 2 && message[15] == 1);
                assert(!legacy_decode(message, 255, &decoded));
            } else if (flags <= 1023) {
                unsigned char previous[16] = {8,1,0xE0,1,0,0,0,0,'H','P','F','O',3,0,1,0};
                previous[13] = (unsigned char)flags;
                previous[15] = (unsigned char)(flags >> 8);
                assert(!memcmp(message, previous, sizeof(message)));
                assert(message[12] == 3 && (message[15] == 2 || message[15] == 3));
                assert(!legacy_decode(message, 255, &decoded));
                assert(!camo_decode(message, &decoded));
            } else if (flags <= 2047) {
                unsigned char previous[16] = {8,1,0xE0,1,0,0,0,0,'H','P','F','O',4,0,1,0};
                previous[13] = (unsigned char)flags; previous[15] = (unsigned char)(flags >> 8);
                assert(!memcmp(message, previous, sizeof(message)));
                assert(message[12] == 4 && message[15] >= 4 && message[15] <= 7);
                assert(!expanded_decode(message, &decoded));
                assert(!camo_decode(message, &decoded));
                assert(!legacy_decode(message,255,&decoded));
            } else if (flags <= 4095) {
                unsigned char previous[16] = {8,1,0xE0,1,0,0,0,0,'H','P','F','O',5,0,1,0};
                previous[13] = (unsigned char)flags; previous[15] = (unsigned char)(flags >> 8);
                assert(!memcmp(message, previous, sizeof(message)));
                assert(message[12] == 5 && message[15] >= 8 && message[15] <= 15);
                assert(!global_decode(message, &decoded));
                assert(!expanded_decode(message, &decoded));
                assert(!camo_decode(message, &decoded));
                assert(!legacy_decode(message,255,&decoded));
            } else {
                assert(message[12] == (flags<=16383 ? 6:7));
                assert(message[15] >= 16 && message[15] <= 127);
                assert(!download_wait_decode(message, &decoded));
                assert(!global_decode(message, &decoded));
                assert(!expanded_decode(message, &decoded));
                assert(!camo_decode(message, &decoded));
                assert(!legacy_decode(message,255,&decoded));
            }
            /* Capability never grants host-setting authority, or vice versa. */
            assert(!network_performance_decode(message, sizeof(message), 3 - kind, &decoded));
            assert(!network_performance_decode(message, sizeof(message), 3, &decoded));
            for (index = 0; index < sizeof(message); ++index)
                assert(!network_performance_decode(message, index, kind, &decoded));
            assert(!network_performance_decode(message, sizeof(message) + 1, kind, &decoded));
            /* Every fixed header, magic/version, kind and reserved byte is
             * checked; damaged packets leave the caller's flags unchanged. */
            for (index = 0; index < sizeof(message); ++index) {
                if (index == 13) continue;
                memcpy(damaged, message, sizeof(message));
                damaged[index] ^= 0x80;
                decoded = 99;
                assert(!network_performance_decode(damaged, sizeof(damaged), kind, &decoded));
                assert(decoded == 99);
            }
            /* Camo requires version 2 and the high byte; toggling only the
             * version cannot make either extension generation valid. */
            memcpy(damaged, message, sizeof(message));
            damaged[12] = flags <= 255 ? 2 : 1;
            assert(!network_performance_decode(damaged, sizeof(damaged), kind, &decoded));
        }
        network_performance_encode(message, kind, maximum_flags + 1);
        assert(!network_performance_decode(message, sizeof(message), kind, &flags));
    }
    assert(!network_performance_decode(NULL, sizeof(message), 1, &flags));
    assert(!network_performance_decode(message, sizeof(message), 1, NULL));
    puts("performance network protocol: PASS");
    return 0;
}
