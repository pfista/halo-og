/* Execute the actual rebased guest and production forwarding adapters without
 * graphics, HTTP, downloader state or any personal files. */
#include <assert.h>
#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "../native/HaloMapDownloads.h"
#include "../../linux/src/game_directory.h"
#define BASE UINT64_C(0x10000000000)
typedef struct {
    unsigned char ident[16];
    uint16_t type, machine;
    uint32_t version;
    uint64_t entry, phoff, shoff;
    uint32_t flags;
    uint16_t ehsize, phentsize, phnum, shentsize, shnum, shstrndx;
} Elf;
typedef struct {
    uint32_t type, flags;
    uint64_t offset, vaddr, paddr, filesz, memsz, align;
} Ph;
extern void *host_resolve_import(const char *name);
static uint32_t (*guest)(uint32_t);
static unsigned native_calls;

uint64_t host_sdl_window_flags(uint32_t window)
{
    native_calls++;
    if (!window) return 0;
    assert(window == 0x12345678);
    return UINT64_C(0x8000000012345678);
}

static void *pointer(uint32_t offset) { return (void *)(BASE + offset); }
int halo_map_download_directory(char *out, size_t capacity)
{
    native_calls++;
    if (!out) { assert(capacity == 0); return 0; }
    assert(out == pointer(0x02000400) && capacity == 1024);
    memcpy(out, "/fixture/maps", 14);
    return 1;
}
int halo_map_download_request(const char *name)
{
    native_calls++;
    if (!name) return 0;
    assert(name == pointer(0x02000200) && !strcmp(name, "downrush"));
    return HALO_MAP_DOWNLOAD_PENDING;
}
int halo_arsenal_download_request(const char *name, const char *base, const char *expected)
{
    native_calls++;
    if (!name) { assert(!base && !expected); return HALO_MAP_DOWNLOAD_UNAVAILABLE; }
    assert(name == pointer(0x02001000) && !strcmp(name, "prisoner"));
    assert(base == pointer(0x02001100) && strlen(base) == 64 && base[0] == 'b');
    if (expected) assert(expected == pointer(0x02001200) && strlen(expected) == 64 && expected[0] == 'c');
    return HALO_MAP_DOWNLOAD_PENDING;
}
int halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status, int *retry_after_seconds)
{
    native_calls++;
    assert(method == pointer(0x02000100) && !strcmp(method, "GET"));
    assert(url == pointer(0x02000300) && !strcmp(url, "https://fixture.invalid/v1/games"));
    assert(response == pointer(0x02000800) && status == pointer(0x02000c00));
    assert(retry_after_seconds == pointer(0x02000c04));
    if (!lease) {
        assert(!body && capacity == 17);
        *status = 0;
        *retry_after_seconds = 0;
        return -7;
    }
    assert(lease == pointer(0x02000500) && !strcmp(lease, "fixture lease"));
    assert(body == pointer(0x02000600) && !strcmp(body, "fixture body"));
    assert(capacity == 1024);
    memcpy(response, "ok", 3);
    *status = 201;
    *retry_after_seconds = 30;
    return 3;
}
static void *map_at(uint64_t address, size_t size)
{
    void *result = mmap((void *)address, size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(result == (void *)address);
    return result;
}
static void *run(void *unused)
{
    uint32_t result = guest(0);
    printf("guest service result=%u expected=93; native calls=%u expected=11\n", result, native_calls);
    return (void *)(uintptr_t)(result != 93 || native_calls != 11);
}
int main(int argc, char **argv)
{
    if (argc != 5) return 2;
    FILE *file = fopen(argv[1], "rb");
    assert(file);
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    rewind(file);
    unsigned char *data = malloc((size_t)length);
    assert(fread(data, 1, (size_t)length, file) == (size_t)length);
    fclose(file);
    Elf *elf = (Elf *)data;
    assert(!memcmp(elf->ident, "\177ELF", 4) && elf->phentsize == sizeof(Ph));
    void *image = map_at(BASE + 0x88000000, 0x40000);
    for (unsigned i = 0; i < elf->phnum; i++) {
        Ph *segment = (Ph *)(data + elf->phoff + i * sizeof(Ph));
        if (segment->type != 1 || segment->vaddr < 0x88000000) continue;
        assert(segment->vaddr + segment->memsz <= 0x88040000);
        assert(segment->offset + segment->filesz <= (uint64_t)length);
        memcpy(pointer((uint32_t)segment->vaddr), data + segment->offset, (size_t)segment->filesz);
    }
    char *name = pointer((uint32_t)strtoul(argv[2], NULL, 16));
    uint64_t *table = pointer((uint32_t)strtoul(argv[3], NULL, 16));
    uint32_t count = *(uint32_t *)pointer((uint32_t)strtoul(argv[4], NULL, 16));
    for (unsigned i = 0; i < count; i++) {
        table[i] = (uintptr_t)host_resolve_import(name);
        assert(table[i]);
        name += strlen(name) + 1;
    }
    sys_icache_invalidate(image, 0x40000);
    assert(!mprotect(image, 0x40000, PROT_READ | PROT_EXEC));
    map_at(BASE + 0x02000000, 0x4000);
    strcpy(pointer(0x02000100), "GET");
    strcpy(pointer(0x02000200), "downrush");
    strcpy(pointer(0x02000300), "https://fixture.invalid/v1/games");
    strcpy(pointer(0x02000500), "fixture lease");
    strcpy(pointer(0x02000600), "fixture body");
    strcpy(pointer(0x02001000), "prisoner");
    memset(pointer(0x02001100), 'b', 64);
    memset(pointer(0x02001200), 'c', 64);
    guest = pointer((uint32_t)elf->entry);
    void *stack = map_at(BASE + 0x90000000, 0x400000);
    pthread_attr_t attributes;
    pthread_attr_init(&attributes);
    assert(!pthread_attr_setstack(&attributes, stack, 0x400000));
    pthread_t thread;
    assert(!pthread_create(&thread, &attributes, run, NULL));
    void *result;
    assert(!pthread_join(thread, &result));
    return (int)(uintptr_t)result;
}
