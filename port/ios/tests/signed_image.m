/* Executes the same signed guest code twice, with nonexecutable data at distinct addresses. */
#include "image.h"
#include "host.h"
#import <Metal/Metal.h>
#include <assert.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define ARENA_SIZE UINT64_C(0x90000000)
#define STACK_OFFSET UINT32_C(0x01000000)
#define STACK_SIZE UINT32_C(0x00400000)
#define DELTA_OFFSET UINT32_C(0x00ff0000)
#define PAGE_SIZE_GUEST_HOST 16384u

static unsigned argument_calls;
static int has_gpu;

int host_probe_arguments(unsigned value, const char *constant, const char *local, const void *null_pointer,
                         const uint32_t *addresses, unsigned a, unsigned b, unsigned c, uint64_t stack_word) {
    uintptr_t stack = host_guest_arena_base + STACK_OFFSET;
    uintptr_t image = host_guest_arena_base + HALO_IOS_IMAGE_BASE;
    assert(value == 42 && a == 5 && b == 6 && c == 7);
    assert(stack_word == (UINT64_C(0xf00dbabe00000000) | value));
    assert((uintptr_t)constant >= image && (uintptr_t)constant + sizeof("constant") <= image + HALO_IOS_IMAGE_SIZE);
    assert((uintptr_t)local >= stack && (uintptr_t)local + sizeof("stack") <= stack + STACK_SIZE);
    assert(null_pointer == NULL && strcmp(constant, "constant") == 0 && strcmp(local, "stack") == 0);
    /* The widened array pointer still addresses ILP32 elements. */
    assert((uintptr_t)addresses >= stack && (uintptr_t)addresses + 3 * sizeof(*addresses) <= stack + STACK_SIZE);
    assert(guest_pointer(addresses[0]) == constant && guest_pointer(addresses[1]) == local &&
           guest_pointer(addresses[2]) == NULL);
    argument_calls++;
    return has_gpu;
}

void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list args;
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    fputc('\n', stderr);
}

void *host_sdl_native_metal_layer(uint32_t window) {
    (void)window;
    abort(); /* Offscreen rendering never needs a window. */
}
void host_sdl_native_metal_release(void) { abort(); }

static void *run_guest(void *unused) {
    (void)unused;
    uint32_t (*entry)(uint32_t) = (void *)(halo_ios_image + (HALO_IOS_IMAGE_ENTRY - HALO_IOS_IMAGE_BASE));
    uint32_t result = entry(42);
    printf("Signed Metal image: result=%u expected=93 code=%p arena=%p argument calls=%u GPU=%s\n",
           result, (void *)entry, (void *)host_guest_arena_base, argument_calls,
           has_gpu ? "offscreen RGBA" : "no device; reply ABI only");
    return (void *)(uintptr_t)(result != 93 || argument_calls != 1);
}

static void protect(uintptr_t address, size_t size, int protection) {
    if (mprotect((void *)address, size, protection) != 0) { perror("mprotect"); exit(1); }
}

static int test_arena(uintptr_t base) {
    mach_vm_address_t address = base;
    kern_return_t status = mach_vm_allocate(mach_task_self(), &address, ARENA_SIZE, VM_FLAGS_FIXED);
    if (status != KERN_SUCCESS) {
        fprintf(stderr, "Cannot reserve test arena at %p: %s\n", (void *)base, mach_error_string(status));
        return 1;
    }
    host_guest_arena_base = base;
    argument_calls = 0;
    protect(base, ARENA_SIZE, PROT_NONE);
    protect(base + HALO_IOS_IMAGE_BASE, HALO_IOS_IMAGE_SIZE, PROT_READ | PROT_WRITE);
    memcpy((void *)(base + HALO_IOS_IMAGE_BASE), halo_ios_image, HALO_IOS_IMAGE_SIZE);
    uint32_t count = *(uint32_t *)guest_pointer(PROBE_IMPORT_COUNT);
    uintptr_t *table = guest_pointer(PROBE_IMPORT_TABLE);
    const char *name = guest_pointer(PROBE_IMPORT_NAMES);
    const char *end = (const char *)(base + HALO_IOS_IMAGE_BASE + HALO_IOS_IMAGE_SIZE);
    assert(count == 5 && PROBE_IMPORT_TABLE >= HALO_IOS_IMAGE_BASE && (const char *)(table + count) <= end);
    for (uint32_t i = 0; i < count; ++i) {
        assert(name < end && memchr(name, 0, (size_t)(end - name)));
        table[i] = (uintptr_t)host_resolve_import(name);
        assert(table[i]);
        name += strlen(name) + 1;
    }
    protect(base + DELTA_OFFSET, PAGE_SIZE_GUEST_HOST, PROT_READ | PROT_WRITE);
    *(uint64_t *)(base + DELTA_OFFSET) = (uintptr_t)halo_ios_image - HALO_IOS_IMAGE_BASE;
    protect(base + DELTA_OFFSET, PAGE_SIZE_GUEST_HOST, PROT_READ);
    protect(base + 0x80000000u, PAGE_SIZE_GUEST_HOST, PROT_READ | PROT_WRITE);
    void *stack = (void *)(base + STACK_OFFSET);
    protect((uintptr_t)stack, STACK_SIZE, PROT_READ | PROT_WRITE);
    pthread_attr_t attributes;
    pthread_t thread;
    void *result;
    assert(pthread_attr_init(&attributes) == 0);
    assert(pthread_attr_setstack(&attributes, stack, STACK_SIZE) == 0);
    assert(pthread_create(&thread, &attributes, run_guest, NULL) == 0);
    assert(pthread_attr_destroy(&attributes) == 0);
    assert(pthread_join(thread, &result) == 0);
    assert(mach_vm_deallocate(mach_task_self(), base, ARENA_SIZE) == KERN_SUCCESS);
    return (int)(uintptr_t)result;
}

int main(void) {
    /* Both bases keep the low 32 bits free. Multiple high bits on the second
       run catch the former single-bit OR and any partial high-word mask. */
    @autoreleasepool {
        has_gpu = MTLCreateSystemDefaultDevice() != nil;
        return test_arena(UINT64_C(0x10000000000)) || test_arena(UINT64_C(0x13500000000));
    }
}
