/* Executes the same signed guest code twice, with nonexecutable data at distinct addresses. */
#include "image.h"
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

static uintptr_t active_base;
static unsigned shader_calls;

static void shader_source(unsigned shader, int count, const uintptr_t *strings, const int *lengths) {
    assert(shader == 42 && count == 3 && lengths == NULL);
    assert((uintptr_t)strings >= active_base + STACK_OFFSET &&
           (uintptr_t)strings + count * sizeof(*strings) <= active_base + STACK_OFFSET + STACK_SIZE);
    assert(strings[0] >= active_base + HALO_IOS_IMAGE_BASE &&
           strings[0] < active_base + HALO_IOS_IMAGE_BASE + HALO_IOS_IMAGE_SIZE);
    assert(strings[1] >= active_base + STACK_OFFSET && strings[1] < active_base + STACK_OFFSET + STACK_SIZE);
    assert(strings[2] == 0);
    assert(strcmp((const char *)strings[0], "constant") == 0 && strcmp((const char *)strings[1], "stack") == 0);
    shader_calls++;
}

static void *run_guest(void *unused) {
    (void)unused;
    uint32_t (*entry)(uint32_t) = (void *)(halo_ios_image + (HALO_IOS_IMAGE_ENTRY - HALO_IOS_IMAGE_BASE));
    uint32_t result = entry(42);
    printf("Signed image probe: result=%u expected=93; code=%p arena=%p GL calls=%u\n",
           result, (void *)entry, (void *)active_base, shader_calls);
    return (void *)(uintptr_t)(result != 93 || shader_calls != 1);
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
    active_base = base;
    shader_calls = 0;
    protect(base, ARENA_SIZE, PROT_NONE);
    protect(base + HALO_IOS_IMAGE_BASE, HALO_IOS_IMAGE_SIZE, PROT_READ | PROT_WRITE);
    memcpy((void *)(base + HALO_IOS_IMAGE_BASE), halo_ios_image, HALO_IOS_IMAGE_SIZE);
    assert(PROBE_IMPORT_TABLE >= HALO_IOS_IMAGE_BASE &&
           PROBE_IMPORT_TABLE + sizeof(uintptr_t) <= HALO_IOS_IMAGE_BASE + HALO_IOS_IMAGE_SIZE);
    *(uintptr_t *)(base + PROBE_IMPORT_TABLE) = (uintptr_t)shader_source;
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
    return test_arena(UINT64_C(0x10000000000)) || test_arena(UINT64_C(0x13500000000));
}
