/* Exercise production Metal imports from the signed ILP32 guest. */
#include "../../macos/include/halo_metal_abi.h"

extern unsigned guest_test(unsigned value);
extern int host_probe_arguments(unsigned value, const char *constant, const char *local,
    const void *null_pointer, const uintptr_t *addresses, unsigned a, unsigned b, unsigned c, uint64_t stack_word);

static const struct {
    struct halo_metal_packet header;
    struct halo_metal_create create;
    struct halo_metal_clear clear;
} packet = {
    .header = {HALO_METAL_MAGIC, HALO_METAL_ABI_VERSION, sizeof(packet), 2, 1},
    .create = {{HALO_METAL_CREATE_TEXTURE, sizeof(packet.create)}, {1, 1}, HALO_METAL_RGBA8, 1, 1, 0},
    .clear = {.command = {HALO_METAL_CLEAR, sizeof(packet.clear)}, .color = {1, 1},
              .planes = HALO_METAL_COLOR, .width = 1, .height = 1, .rgba = {1, 0, 0, 1}}
};

unsigned guest_probe(unsigned value) {
    static const char constant[] = "constant";
    char local[] = "stack";
    const uintptr_t addresses[] = {(uintptr_t)constant, (uintptr_t)local, 0};
    int has_gpu = host_probe_arguments(value, constant, local, NULL, addresses, 5, 6, 7,
                                       UINT64_C(0xf00dbabe00000000) | value);
    struct halo_metal_reply reply = {0};
    uint32_t output = (uintptr_t)&reply;
    uint8_t pixel[4] = {0};

    /* A runner without a Metal device can still check the production host's
       cross-arena reply, status and stack arguments before initialization. */
    if (host_metal_readback(1, 1, HALO_METAL_COLOR, (uintptr_t)pixel, sizeof(pixel), output, sizeof(reply))
            != HALO_METAL_NOT_INITIALIZED || reply.status != HALO_METAL_NOT_INITIALIZED ||
        reply.abi_version != HALO_METAL_ABI_VERSION) return 106;
    if (has_gpu) {
        if (host_metal_initialize(0, HALO_METAL_OFFSCREEN, output, sizeof(reply)) != HALO_METAL_OK ||
            !(reply.capabilities & HALO_METAL_CAP_READBACK)) return 107;
        if (host_metal_submit((uintptr_t)&packet, sizeof(packet), output, sizeof(reply)) != HALO_METAL_OK ||
            reply.completed_sequence != 1 || reply.live_resources != 1) return 108;
        if (host_metal_readback(1, 1, HALO_METAL_COLOR, (uintptr_t)pixel, sizeof(pixel), output, sizeof(reply))
                != HALO_METAL_OK || reply.byte_size != sizeof(pixel) ||
            pixel[0] != 255 || pixel[1] != 0 || pixel[2] != 0 || pixel[3] != 255) return 109;
        host_metal_shutdown();
    }
    return guest_test(value);
}
