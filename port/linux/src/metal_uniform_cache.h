#ifndef HALO_METAL_UNIFORM_CACHE_H
#define HALO_METAL_UNIFORM_CACHE_H

#if defined(HALO_MACOS_NATIVE_METAL) && HALO_MACOS_NATIVE_METAL
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "metal_vertex_fetch.h"

enum metal_uniform_kind {
    METAL_UNIFORM_VERTEX = 1,
    METAL_UNIFORM_PIXEL = 2
};
enum {
    METAL_UNIFORM_VERTEX_BYTES = 3120,
    METAL_UNIFORM_PIXEL_BYTES = 608,
    METAL_UNIFORM_CACHE_ENTRIES = 4096,
    METAL_UNIFORM_CACHE_BUCKETS = 2048
};

struct metal_uniform_cache_entry {
    uint64_t hash;
    uint32_t kind, size, offset, next;
};
struct metal_uniform_cache {
    uint32_t count;
    uint32_t buckets[METAL_UNIFORM_CACHE_BUCKETS];
    struct metal_uniform_cache_entry entries[METAL_UNIFORM_CACHE_ENTRIES];
};

static inline int metal_uniform_span_valid(const void *bytes, size_t size) {
    return !size || (bytes && size <= UINTPTR_MAX - (uintptr_t)bytes);
}
static inline int metal_uniform_kind_size_valid(uint32_t kind, uint32_t size) {
    return (kind == METAL_UNIFORM_VERTEX && size == METAL_UNIFORM_VERTEX_BYTES) ||
           (kind == METAL_UNIFORM_PIXEL && size == METAL_UNIFORM_PIXEL_BYTES);
}
static inline uint32_t metal_uniform_rotate32(uint32_t value, unsigned shift) {
    return (value << shift) | (value >> (32 - shift));
}

/* A fingerprint only: bounded unaligned word loads, four independent lanes,
 * and no floating-point operations. The full owned bytes always decide reuse.
 * Empty input is valid; invalid nonempty pointer extents return zero. */
static inline uint64_t metal_uniform_hash(const void *bytes, size_t size) {
    if (!metal_uniform_span_valid(bytes, size)) return 0;
    const unsigned char *input = (const unsigned char *)bytes;
    uint32_t lanes[4] = {0x9e3779b1u, 0x85ebca77u, 0xc2b2ae3du, 0x27d4eb2fu};
    size_t remaining = size;
    while (remaining >= 32) {
        uint32_t words[8];
        memcpy(words, input, sizeof(words));
        for (unsigned i = 0; i < 4; i++)
            lanes[i] = (metal_uniform_rotate32(lanes[i] + words[i], 13) ^ words[i + 4]) * 0x9e3779b1u;
        input += 32;
        remaining -= 32;
    }
    unsigned lane = 0;
    while (remaining >= 4) {
        uint32_t word;
        memcpy(&word, input, sizeof(word));
        lanes[lane] = metal_uniform_rotate32(lanes[lane] + word, 13) * 0x9e3779b1u;
        lane = (lane + 1) & 3u;
        input += 4;
        remaining -= 4;
    }
    while (remaining) {
        lanes[lane] = metal_uniform_rotate32(lanes[lane] + *input++, 13) * 0x9e3779b1u;
        lane = (lane + 1) & 3u;
        remaining--;
    }
    uint64_t hash = (((uint64_t)lanes[0] << 32) | lanes[1]) ^
                    (((uint64_t)lanes[2] << 32) | lanes[3]) * UINT64_C(0x9e3779b185ebca87) ^ (uint64_t)size;
    hash ^= hash >> 33;
    hash *= UINT64_C(0xff51afd7ed558ccd);
    hash ^= hash >> 33;
    return hash;
}

static inline uint32_t metal_uniform_cache_bucket(uint64_t hash, uint32_t kind, uint32_t size) {
    return ((uint32_t)hash ^ (uint32_t)(hash >> 32) ^ kind * 0x9e3779b1u ^ size) &
           (METAL_UNIFORM_CACHE_BUCKETS - 1u);
}

/* Call whenever packet storage begins/restarts, before replacing its bytes.
 * Entries store offsets only; resetting cannot retain a pointer to old storage. */
static inline void metal_uniform_cache_reset(struct metal_uniform_cache *cache) {
    if (!cache) return;
    cache->count = 0;
    memset(cache->buckets, 0, sizeof(cache->buckets));
}

/* Caller establishes that registered ranges are immutable payload bytes in
 * this packet. Bounds are rechecked on every lookup. A hash/kind/size match
 * never suffices: compare the current input to the owned prior packet bytes.
 * Invalid/missing lookups return zero and leave output untouched. */
static inline int metal_uniform_cache_find(const struct metal_uniform_cache *cache,
    uint64_t hash, uint32_t kind, uint32_t size, const void *packet_bytes,
    size_t packet_extent, const void *input_bytes, uint32_t *payload_offset) {
    if (!cache || !payload_offset || !metal_uniform_kind_size_valid(kind, size) ||
        !metal_uniform_span_valid(packet_bytes, packet_extent) ||
        !metal_uniform_span_valid(input_bytes, size) || cache->count > METAL_UNIFORM_CACHE_ENTRIES) return 0;
    uint32_t index = cache->buckets[metal_uniform_cache_bucket(hash, kind, size)];
    for (uint32_t visited = 0; index && visited < cache->count; visited++) {
        if (index > cache->count) return 0;
        const struct metal_uniform_cache_entry *entry = &cache->entries[index - 1];
        if (entry->hash == hash && entry->kind == kind && entry->size == size &&
            entry->offset <= packet_extent && size <= packet_extent - entry->offset &&
            metal_vertex_bytes_equal((const unsigned char *)packet_bytes + entry->offset, input_bytes, size)) {
            *payload_offset = entry->offset;
            return 1;
        }
        index = entry->next;
    }
    return 0;
}

/* Register only after copying the complete payload into owned packet storage.
 * A full cache declines retention; the caller emits a fresh owned payload.
 * Metadata stays unchanged until reset, including on bounds/full failures. */
static inline int metal_uniform_cache_register(struct metal_uniform_cache *cache,
    uint64_t hash, uint32_t kind, uint32_t size, uint32_t payload_offset,
    const void *packet_bytes, size_t packet_extent) {
    if (!cache || !metal_uniform_kind_size_valid(kind, size) ||
        !metal_uniform_span_valid(packet_bytes, packet_extent) || payload_offset > packet_extent ||
        size > packet_extent - payload_offset || cache->count >= METAL_UNIFORM_CACHE_ENTRIES) return 0;
    uint32_t bucket = metal_uniform_cache_bucket(hash, kind, size);
    struct metal_uniform_cache_entry *entry = &cache->entries[cache->count];
    *entry = (struct metal_uniform_cache_entry){hash, kind, size, payload_offset, cache->buckets[bucket]};
    cache->buckets[bucket] = ++cache->count;
    return 1;
}
#endif
#endif
