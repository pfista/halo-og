/* Optional practice controls beside v11 distributed messages. All controls
 * use the reliable connection; unextended v11 ignores subtype 0xE0. */
#ifndef __NETWORK_PERFORMANCE_PROTOCOL_H
#define __NETWORK_PERFORMANCE_PROTOCOL_H

#define NETWORK_PERFORMANCE_MESSAGE_TYPE 0xE0
#define NETWORK_PERFORMANCE_MESSAGE_SIZE 16
#define NETWORK_PERFORMANCE_VERSION 1
#define NETWORK_PERFORMANCE_CAPABILITY 1
#define NETWORK_PERFORMANCE_SETTINGS 2
#define NETWORK_PERFORMANCE_SUPPORTED_FLAGS 255
#define NETWORK_PERFORMANCE_TIMER_AUDIO_FLAG 4
#define NETWORK_PERFORMANCE_INPUT_DELAY_FLAG 32
#define NETWORK_PERFORMANCE_HARDCORE_FLAG 64
#define NETWORK_PERFORMANCE_FIESTA_FLAG 128
#define NETWORK_PERFORMANCE_MATCH_RULE_FLAGS 224
#define NETWORK_PERFORMANCE_ADVERTISED_FLAG 4
/* Outside upstream's sequential versions: stock clients show their existing
 * update-required dialog only while practice options are on. */
#define NETWORK_PERFORMANCE_ADVERTISED_VERSION 0x800B

static inline unsigned network_performance_runtime_supported_flags(
    int queue_supported, int timer_audio_available)
{
    unsigned flags = NETWORK_PERFORMANCE_SUPPORTED_FLAGS &
        ~(NETWORK_PERFORMANCE_TIMER_AUDIO_FLAG | NETWORK_PERFORMANCE_MATCH_RULE_FLAGS);
    if (queue_supported) flags |= NETWORK_PERFORMANCE_MATCH_RULE_FLAGS;
    if (timer_audio_available) flags |= NETWORK_PERFORMANCE_TIMER_AUDIO_FLAG;
    return flags;
}

/* A newer host must send a capability frame an older peer can decode. The
 * extension generations deliberately reject every unknown bit as a whole. */
static inline unsigned network_performance_capability_for_peer(unsigned supported,
    int peer_hardcore_supported, int peer_fiesta_supported)
{
    return peer_fiesta_supported ? supported :
        supported & (peer_hardcore_supported ? 127u : 63u);
}

/* An older host preserves unknown saved padding, but decodes that entire
 * extension as Off. Do not infer host timing support from those raw bytes. */
static inline unsigned network_performance_host_settings_flags(
    unsigned flags, unsigned host_supported)
{
    /* Older hosts retain unknown saved bytes but run the entire extension Off.
     * Require their acknowledgement before applying any new match rule. */
    return (flags & NETWORK_PERFORMANCE_MATCH_RULE_FLAGS & ~host_supported) ? 0 : flags;
}

static inline int network_performance_can_join(unsigned required, unsigned supported)
{
    return !(required & ~NETWORK_PERFORMANCE_SUPPORTED_FLAGS) &&
        (required & supported) == required;
}

static inline unsigned network_performance_advertised_version(unsigned flags, unsigned stock)
{
    return flags ? NETWORK_PERFORMANCE_ADVERTISED_VERSION : stock;
}

static inline int network_performance_version_compatible(unsigned version,
    unsigned advertisement_flags, unsigned stock)
{
    return version == stock || (version == NETWORK_PERFORMANCE_ADVERTISED_VERSION &&
        (advertisement_flags & NETWORK_PERFORMANCE_ADVERTISED_FLAG));
}

/* The game header is host byte order until network_connection_write swaps it.
 * All supported native hosts are little endian; the payload is byte-only. */
static inline void network_performance_encode(unsigned char *message,
    unsigned kind, unsigned flags)
{
    unsigned index;
    for (index = 0; index < NETWORK_PERFORMANCE_MESSAGE_SIZE; ++index)
        message[index] = 0;
    message[0] = 8; /* data kind (2 << 2), no flags */
    message[1] = 1; /* 16-byte size (16 << 4) */
    message[2] = NETWORK_PERFORMANCE_MESSAGE_TYPE;
    message[3] = 1;
    message[8] = 'H'; message[9] = 'P'; message[10] = 'F'; message[11] = 'O';
    message[12] = NETWORK_PERFORMANCE_VERSION;
    message[13] = (unsigned char)flags;
    message[14] = (unsigned char)kind;
}

static inline int network_performance_decode(unsigned char const *message,
    unsigned size, unsigned kind, unsigned *flags)
{
    unsigned index;
    if ((kind != NETWORK_PERFORMANCE_CAPABILITY && kind != NETWORK_PERFORMANCE_SETTINGS) ||
        !message || !flags || size != NETWORK_PERFORMANCE_MESSAGE_SIZE ||
        message[0] != 8 || message[1] != 1 ||
        message[2] != NETWORK_PERFORMANCE_MESSAGE_TYPE || message[3] != 1 ||
        message[8] != 'H' || message[9] != 'P' || message[10] != 'F' || message[11] != 'O' ||
        message[12] != NETWORK_PERFORMANCE_VERSION || message[14] != kind ||
        message[15] != 0 || (message[13] & ~NETWORK_PERFORMANCE_SUPPORTED_FLAGS) != 0)
        return 0;
    for (index = 4; index < 8; ++index)
        if (message[index] != 0) return 0;
    *flags = message[13];
    return 1;
}

#endif
