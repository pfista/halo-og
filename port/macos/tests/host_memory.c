/* Exercise the real Darwin allocator and syscall boundary without game data. */
#include "host.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
}
void host_exit(int code) { exit(code); }
extern long long host_syscall(long long, long long, long long, long long, long long, long long,
                              long long);
static uint32_t *futex_word;
static void *wake_thread(void *unused) {
    (void)unused;
    usleep(20000);
    __atomic_store_n(futex_word, 1, __ATOMIC_SEQ_CST);
    host_syscall(98, (uint32_t)(uintptr_t)futex_word, 1, 1, 0, 0, 0);
    return NULL;
}

int main(void) {
    assert(host_memory_initialize(HALO_GUEST_IMAGE_BASE, 0x40000) == 0);
    host_install_signal_handlers();
    assert(HALO_GUEST_IMAGE_BASE == HALO_GUEST_WINDOW_BASE + HALO_GUEST_WINDOW_SIZE);
    assert(HALO_GUEST_WINDOW_SIZE == 0x20000000u);
    assert(HALO_GUEST_IMAGE_BASE == 0xa0000000u && HALO_GUEST_ABI_VERSION == 0x10002);
    /* The last Xbox page now lies above the old 128 MB window. Its native
       protection bookkeeping must not index beyond the enlarged array. */
    const uint32_t last = HALO_GUEST_IMAGE_BASE - 4096;
    assert(host_guest_mmap(last, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == last);
    memset(guest_pointer(last), 0x57, 4096);
    assert(host_guest_mmap(last, 8192, PROT_READ, 0x32, -1, 0) == -22);
    assert(host_guest_mmap(HALO_GUEST_IMAGE_BASE, 4096, PROT_READ, 0x100022, -1, 0) == -22);
    assert(((unsigned char *)guest_pointer(last))[4095] == 0x57);
    assert(host_low_owns((uintptr_t)guest_pointer(0xa7ffc000), HALO_MACOS_PAGE));
    assert(!host_low_owns((uintptr_t)guest_pointer(0xa8000000), 1));

    /* Exercise the actual CE loader's fixed tag-cache request, and prove
       duplicate or partial-overlap requests cannot replace live contents. */
    const uint32_t ce = 0x40440000u, ce_size = 0x01700000u;
    assert(host_guest_mmap(ce, ce_size, PROT_READ | PROT_WRITE, 0x104022, -1, 0) == ce);
    *(uint32_t *)guest_pointer(ce) = 0x76543210;
    *(uint32_t *)guest_pointer(ce + ce_size - 4) = 0x12345678;
    assert(host_guest_mmap(ce, ce_size, PROT_READ | PROT_WRITE, 0x104022, -1, 0) == -17);
    assert(host_guest_mmap(ce - HALO_MACOS_PAGE, HALO_MACOS_PAGE * 2,
                           PROT_READ | PROT_WRITE, 0x100022, -1, 0) == -17);
    assert(host_guest_mmap(ce, ce_size, PROT_NONE, 0x32, -1, 0) == -22);
    assert(host_guest_mmap(ce + 4096, 4096, PROT_READ, 0x100022, -1, 0) == -22);
    assert(host_guest_mmap(UINT64_C(0xfffffffffffff000), 4096, PROT_READ, 0x100022, -1, 0) == -22);
    assert(host_guest_mmap(0x7fffc000, HALO_MACOS_PAGE * 2, PROT_READ, 0x100022, -1, 0) == -22);
    assert(*(uint32_t *)guest_pointer(ce) == 0x76543210);
    assert(*(uint32_t *)guest_pointer(ce + ce_size - 4) == 0x12345678);
    /* Fill only virtual address space before the fixed cache. The ordinary
       allocator must skip its occupied pages when looking for the next run. */
    void *prefix = host_low_map(ce - 0x1000000u, PROT_NONE);
    assert(prefix == guest_pointer(0x1000000u));
    void *after_cache = host_low_map(HALO_MACOS_PAGE, PROT_READ | PROT_WRITE);
    assert(after_cache == guest_pointer(ce + ce_size));
    host_low_unmap(after_cache, HALO_MACOS_PAGE);
    host_low_unmap(prefix, ce - 0x1000000u);
    host_memory_watch_protect(ce, 4096);
    uint32_t ce_generation = host_memory_watch_generation(ce, 4096);
    *(volatile uint32_t *)guest_pointer(ce) = 0xaabbccdd;
    assert(host_memory_watch_generation(ce, 4096) > ce_generation);
    assert(host_guest_munmap(ce, ce_size) == 0);
    assert(host_guest_mmap(ce, ce_size, PROT_READ | PROT_WRITE, 0x100022, -1, 0) == ce);
    assert(*(uint32_t *)guest_pointer(ce) == 0);
    assert(*(uint32_t *)guest_pointer(ce + ce_size - 4) == 0);
    assert(host_guest_munmap(ce, ce_size) == 0);
    unsigned char *first = host_low_map(4096, PROT_READ | PROT_WRITE);
    assert(first);
    assert(host_guest_mmap((uint32_t)(uintptr_t)first, 4096, PROT_NONE, 0x100022, -1, 0) == -17);
    memset(first, 0x82, HALO_MACOS_PAGE);
    host_low_unmap(first, 4096);
    unsigned char *reused = host_low_map(4096, PROT_READ | PROT_WRITE);
    assert(reused == first);
    for (unsigned i = 0; i < HALO_MACOS_PAGE; i++)
        assert(reused[i] == 0);

    const uint32_t a = HALO_GUEST_WINDOW_BASE + 0x3a5000;
    const uint32_t b = a + 4096;
    assert(host_guest_mmap(a, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == a);
    memset(guest_pointer(a), 0x63, 4096);
    assert(host_guest_mmap(b, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == b);
    memset(guest_pointer(b), 0x45, 4096);
    assert(host_guest_mmap(b, 4096, PROT_NONE, 0x32, -1, 0) == b);
    for (unsigned i = 0; i < 4096; i++)
        assert(((unsigned char *)guest_pointer(a))[i] == 0x63);
    assert(host_guest_mmap(b, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == b);
    for (unsigned i = 0; i < 4096; i++)
        assert(((unsigned char *)guest_pointer(b))[i] == 0);

    uint32_t before = host_memory_watch_generation(a, 4096);
    host_memory_watch_protect(a, 4096);
    *(volatile uint32_t *)guest_pointer(a) = 0x12345678;
    assert(host_memory_watch_generation(a, 4096) > before);
    assert(*(uint32_t *)guest_pointer(a) == 0x12345678);

    /* Forgetting a writable range still invalidates its previous contents. */
    before = host_memory_watch_generation(a, 4096);
    host_memory_watch_forget(a, 4096);
    assert(host_memory_watch_generation(a, 4096) > before);
    before = host_memory_watch_generation(a, 4096);
    host_memory_watch_forget(a, 4096);
    assert(host_memory_watch_generation(a, 4096) > before);

    host_memory_watch_protect(a, 4096);
    host_memory_watch_forget(a, 4096);
    *(volatile uint32_t *)guest_pointer(a) = 0x12345678;
    assert(*(uint32_t *)guest_pointer(a) == 0x12345678);

    /* A neighboring Xbox allocation shares this Darwin page. Making it
       writable must invalidate cached GPU data in the existing allocation. */
    host_memory_watch_protect(a, 4096);
    before = host_memory_watch_generation(a, 4096);
    assert(host_guest_mmap(b, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == b);
    *(volatile uint32_t *)guest_pointer(a) = 0x87654321;
    assert(host_memory_watch_generation(a, 4096) > before);
    assert(*(uint32_t *)guest_pointer(a) == 0x87654321);

    host_memory_watch_protect(a, 4096);
    before = host_memory_watch_generation(a, 4096);
    assert(host_guest_mprotect(b, 4096, PROT_NONE) == 0);
    *(volatile uint32_t *)guest_pointer(a) = 0x12345678;
    assert(host_memory_watch_generation(a, 4096) > before);
    assert(host_guest_mmap(0x1000, 4096, PROT_READ, 0x32, -1, 0) == -22);

    futex_word = (uint32_t *)reused;
    pthread_t thread;
    assert(pthread_create(&thread, NULL, wake_thread, NULL) == 0);
    long long wait_result = host_syscall(98, (uint32_t)(uintptr_t)futex_word, 0, 0, 0, 0, 0);
    assert(wait_result == 0 || wait_result == -11);
    pthread_join(thread, NULL);
    assert(*futex_word == 1);
    assert(host_syscall(113, 1, (uint32_t)(uintptr_t)(reused + 16), 0, 0, 0, 0) == 0);
    assert(*(int32_t *)(reused + 16) >= 0);
    puts("Darwin 512 MB window, CE fixed cache, allocator, neighbors, write watch, futex, and clock passed");
    return 0;
}
