/* Optional practice controls beside v11 distributed messages. All controls
 * use the reliable connection; unextended v11 ignores subtype 0xE0. */
#ifndef __NETWORK_PERFORMANCE_PROTOCOL_H
#define __NETWORK_PERFORMANCE_PROTOCOL_H

#define NETWORK_PERFORMANCE_MESSAGE_TYPE 0xE0
#define NETWORK_PERFORMANCE_MESSAGE_SIZE 16
#define NETWORK_PERFORMANCE_VERSION 7
#define NETWORK_PERFORMANCE_SELF_AUDIO_VERSION 6
#define NETWORK_PERFORMANCE_DOWNLOAD_WAIT_VERSION 5
#define NETWORK_PERFORMANCE_GLOBAL_ARSENAL_VERSION 4
#define NETWORK_PERFORMANCE_EXPANDED_WEAPONS_VERSION 3
#define NETWORK_PERFORMANCE_CAMO_VERSION 2
#define NETWORK_PERFORMANCE_LEGACY_VERSION 1
#define NETWORK_PERFORMANCE_CAPABILITY 1
#define NETWORK_PERFORMANCE_SETTINGS 2
#define NETWORK_PERFORMANCE_SETTINGS_ACK 3
#define NETWORK_PERFORMANCE_SUPPORTED_FLAGS 29183
#define NETWORK_PERFORMANCE_EXPANDED_WEAPONS_CAPABILITY 512
#define NETWORK_PERFORMANCE_GLOBAL_ARSENAL_CAPABILITY 1024
#define NETWORK_PERFORMANCE_DOWNLOAD_WAIT_CAPABILITY 2048
#define NETWORK_PERFORMANCE_SELF_MOVEMENT_FLAG 4096
#define NETWORK_PERFORMANCE_SELF_WEAPON_READY_FLAG 8192
#define NETWORK_PERFORMANCE_SELF_AUDIO_FLAGS 12288
#define NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG 16384
#define NETWORK_PERFORMANCE_SUPPORTED_CAPABILITIES 32767
#define NETWORK_PERFORMANCE_SILENT_MOVEMENT_FLAG 8
#define NETWORK_PERFORMANCE_SILENT_WEAPON_READY_FLAG 16
#define NETWORK_PERFORMANCE_TIMER_AUDIO_FLAG 4
#define NETWORK_PERFORMANCE_INPUT_DELAY_FLAG 32
#define NETWORK_PERFORMANCE_HARDCORE_FLAG 64
#define NETWORK_PERFORMANCE_FIESTA_FLAG 128
#define NETWORK_PERFORMANCE_HARDCORE_CAMO_FLAG 256
#define NETWORK_PERFORMANCE_MATCH_RULE_FLAGS 480
#define NETWORK_PERFORMANCE_ADVERTISED_FLAG 4
/* Outside upstream's sequential versions: stock clients show their existing
 * update-required dialog only while practice options are on. */
#define NETWORK_PERFORMANCE_ADVERTISED_VERSION 0x800B

static inline unsigned network_performance_runtime_supported_flags(
    int queue_supported, int timer_audio_available)
{
    unsigned flags = NETWORK_PERFORMANCE_SUPPORTED_CAPABILITIES &
        ~(NETWORK_PERFORMANCE_TIMER_AUDIO_FLAG | NETWORK_PERFORMANCE_MATCH_RULE_FLAGS |
          NETWORK_PERFORMANCE_EXPANDED_WEAPONS_CAPABILITY | NETWORK_PERFORMANCE_GLOBAL_ARSENAL_CAPABILITY |
          NETWORK_PERFORMANCE_DOWNLOAD_WAIT_CAPABILITY | NETWORK_PERFORMANCE_SELF_AUDIO_FLAGS |
          NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG);
    /* The native queue/audio hooks share HALO_PORT_MAXIMUM_NETWORK_PLAYERS.
     * Fallback builds cannot promise listener-specific sound filtering. */
    if (queue_supported) flags |= NETWORK_PERFORMANCE_MATCH_RULE_FLAGS |
        NETWORK_PERFORMANCE_EXPANDED_WEAPONS_CAPABILITY | NETWORK_PERFORMANCE_GLOBAL_ARSENAL_CAPABILITY |
        NETWORK_PERFORMANCE_DOWNLOAD_WAIT_CAPABILITY | NETWORK_PERFORMANCE_SELF_AUDIO_FLAGS |
        NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG;
    if (timer_audio_available) flags |= NETWORK_PERFORMANCE_TIMER_AUDIO_FLAG;
    return flags;
}

/* A newer host must send a capability frame an older peer can decode. The
 * extension generations deliberately reject every unknown bit as a whole. */
static inline unsigned network_performance_capability_for_peer(unsigned supported,
    int peer_hardcore_supported, int peer_fiesta_supported, int peer_camo_supported,
    int peer_expanded_weapons_supported, int peer_global_arsenal_supported,
    int peer_download_wait_supported, int peer_self_audio_supported,
    int peer_powerup_sync_supported)
{
    return supported & (peer_powerup_sync_supported ? 32767u : (peer_self_audio_supported ? 16383u :
        (peer_download_wait_supported ? 4095u : (peer_global_arsenal_supported ? 2047u :
        (peer_expanded_weapons_supported ? 1023u :
        (peer_camo_supported ? 511u :
         (peer_fiesta_supported ? 255u : (peer_hardcore_supported ? 127u : 63u))))))));
}

/* An older host preserves unknown saved padding, but decodes that entire
 * extension as Off. Do not infer host timing support from those raw bytes. */
static inline unsigned network_performance_host_settings_flags(
    unsigned flags, unsigned host_supported)
{
    /* Older hosts retain unknown saved bytes but run the entire extension Off.
     * Require their acknowledgement before applying any new match rule or
     * actor-only audio. The audio controls remain editable during a match. */
    return (flags & (NETWORK_PERFORMANCE_MATCH_RULE_FLAGS | NETWORK_PERFORMANCE_SELF_AUDIO_FLAGS) &
        ~host_supported) ? 0 : flags;
}

static inline int network_performance_can_join(unsigned required, unsigned supported)
{
    return !(required & ~NETWORK_PERFORMANCE_SUPPORTED_CAPABILITIES) &&
        (required & supported) == required;
}

/* Capabilities may include every mode. Settings choose one sound mode per
 * category; an invalid pair must not be normalized differently by a peer. */
static inline int network_performance_settings_flags_valid(unsigned flags)
{
    return !(flags & ~NETWORK_PERFORMANCE_SUPPORTED_FLAGS) &&
        !((flags & NETWORK_PERFORMANCE_SILENT_MOVEMENT_FLAG) &&
          (flags & NETWORK_PERFORMANCE_SELF_MOVEMENT_FLAG)) &&
        !((flags & NETWORK_PERFORMANCE_SILENT_WEAPON_READY_FLAG) &&
          (flags & NETWORK_PERFORMANCE_SELF_WEAPON_READY_FLAG));
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
    /* Previous frames remain byte-identical. Version 7 adds the independent
     * experimental session policy; saved Performance flags still use v1-v6. */
    message[12] = flags > 16383 ? NETWORK_PERFORMANCE_VERSION :
        (flags > 4095 ? NETWORK_PERFORMANCE_SELF_AUDIO_VERSION :
        (flags > 2047 ? NETWORK_PERFORMANCE_DOWNLOAD_WAIT_VERSION :
        (flags > 1023 ? NETWORK_PERFORMANCE_GLOBAL_ARSENAL_VERSION :
        (flags > 511 ? NETWORK_PERFORMANCE_EXPANDED_WEAPONS_VERSION :
        (flags > 255 ? NETWORK_PERFORMANCE_CAMO_VERSION : NETWORK_PERFORMANCE_LEGACY_VERSION)))));
    message[13] = (unsigned char)flags;
    message[14] = (unsigned char)kind;
    message[15] = (unsigned char)(flags >> 8);
}

static inline int network_performance_decode(unsigned char const *message,
    unsigned size, unsigned kind, unsigned *flags)
{
    unsigned index, decoded;
    if ((kind != NETWORK_PERFORMANCE_CAPABILITY && kind != NETWORK_PERFORMANCE_SETTINGS &&
         kind != NETWORK_PERFORMANCE_SETTINGS_ACK) ||
        !message || !flags || size != NETWORK_PERFORMANCE_MESSAGE_SIZE ||
        message[0] != 8 || message[1] != 1 ||
        message[2] != NETWORK_PERFORMANCE_MESSAGE_TYPE || message[3] != 1 ||
        message[8] != 'H' || message[9] != 'P' || message[10] != 'F' || message[11] != 'O' ||
        message[14] != kind ||
        !((message[12] == NETWORK_PERFORMANCE_LEGACY_VERSION && message[15] == 0) ||
          (message[12] == NETWORK_PERFORMANCE_CAMO_VERSION && message[15] == 1) ||
          (message[12] == NETWORK_PERFORMANCE_EXPANDED_WEAPONS_VERSION &&
           kind == NETWORK_PERFORMANCE_CAPABILITY &&
           (message[15] == 2 || message[15] == 3)) ||
          (message[12] == NETWORK_PERFORMANCE_GLOBAL_ARSENAL_VERSION &&
           kind == NETWORK_PERFORMANCE_CAPABILITY && message[15] >= 4 && message[15] <= 7) ||
          (message[12] == NETWORK_PERFORMANCE_DOWNLOAD_WAIT_VERSION &&
           kind == NETWORK_PERFORMANCE_CAPABILITY && message[15] >= 8 && message[15] <= 15) ||
          (message[12] == NETWORK_PERFORMANCE_SELF_AUDIO_VERSION &&
           message[15] >= 16 && message[15] <= 63) ||
          (message[12] == NETWORK_PERFORMANCE_VERSION && message[15] <= 127 &&
           (kind != NETWORK_PERFORMANCE_CAPABILITY || message[15] >= 64))))
        return 0;
    if (kind == NETWORK_PERFORMANCE_SETTINGS_ACK && message[12] != NETWORK_PERFORMANCE_VERSION)
        return 0;
    for (index = 4; index < 8; ++index)
        if (message[index] != 0) return 0;
    decoded = message[13] | ((unsigned)message[15] << 8);
    if (decoded & ~(kind == NETWORK_PERFORMANCE_CAPABILITY ?
        NETWORK_PERFORMANCE_SUPPORTED_CAPABILITIES : NETWORK_PERFORMANCE_SUPPORTED_FLAGS)) return 0;
    if (kind == NETWORK_PERFORMANCE_SETTINGS &&
        !network_performance_settings_flags_valid(decoded)) return 0;
    if (kind == NETWORK_PERFORMANCE_SETTINGS_ACK &&
        (decoded & ~NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG)) return 0;
    *flags = decoded;
    return 1;
}

/* EXPERIMENTAL_POWERUP_SYNC: explicit v7 Off is needed to override a joining
 * client's saved On preference. These controls contain no saved variant flags. */
static inline void network_performance_powerup_sync_encode(unsigned char *message,
    unsigned kind, int enabled)
{
    network_performance_encode(message, kind, enabled ? NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG : 0);
    message[12] = NETWORK_PERFORMANCE_VERSION;
}

static inline int network_performance_powerup_sync_decode(unsigned char const *message,
    unsigned size, unsigned kind, int *enabled)
{
    unsigned flags;
    if (!enabled || !message || size != NETWORK_PERFORMANCE_MESSAGE_SIZE ||
        message[12] != NETWORK_PERFORMANCE_VERSION ||
        (kind != NETWORK_PERFORMANCE_SETTINGS && kind != NETWORK_PERFORMANCE_SETTINGS_ACK) ||
        !network_performance_decode(message, size, kind, &flags) ||
        (flags & ~NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG)) return 0;
    *enabled = (flags & NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG) != 0;
    return 1;
}

#endif
