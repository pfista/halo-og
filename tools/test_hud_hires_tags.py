"""Exercise the production resident HUD bitmap registry in an offline C fixture.

Only engine tag iteration, bitmap lookup and the embedded-asset boundary are
stubbed. The complete production registration, alias matching and address
lookup implementation is compiled directly; no maps or graphics are loaded.
Pixel/CRC verification remains covered by test_hud_hires_pixels.py.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

HEADERS = {
    "cseries.h": r'''
#ifndef HUD_TAGS_FIXTURE_CSERIES_H
#define HUD_TAGS_FIXTURE_CSERIES_H
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define csstrcmp strcmp
#define csstrncmp strncmp
#define csstrlen strlen
#define csstrcasecmp fixture_strcasecmp
static int fixture_strcasecmp(const char *left, const char *right) {
    while (*left || *right) {
        unsigned char a = (unsigned char)*left, b = (unsigned char)*right;
        if (a >= 'A' && a <= 'Z') a = (unsigned char)(a + 'a' - 'A');
        if (b >= 'A' && b <= 'Z') b = (unsigned char)(b + 'a' - 'A');
        if (a != b) return (a > b) - (a < b);
        left++; right++;
    }
    return 0;
}
#define match_assert(file,line,condition) do { if (!(condition)) abort(); } while (0)
#define match_vassert(file,line,condition,message) match_assert(file,line,condition)
#endif
''',
    "bitmaps/bitmap_group.h": r'''
#ifndef HUD_TAGS_FIXTURE_BITMAP_H
#define HUD_TAGS_FIXTURE_BITMAP_H
enum { BITMAP_GROUP_TAG = 'bitm' };
struct bitmap_data {
    short width, height;
    long cache_block_index;
    void *base_address;
};
#endif
''',
    "bitmaps/bitmap_group_lookup.h": r'''
#ifndef HUD_TAGS_FIXTURE_LOOKUP_H
#define HUD_TAGS_FIXTURE_LOOKUP_H
struct bitmap_data *bitmap_group_try_and_get_bitmap(long group, short bitmap);
#endif
''',
    "tag_files/tag_groups.h": r'''
#ifndef HUD_TAGS_FIXTURE_TAG_GROUPS_H
#define HUD_TAGS_FIXTURE_TAG_GROUPS_H
long tag_loaded(unsigned long group, const char *name);
#endif
''',
    "tag_files/tag_files.h": r'''
#ifndef HUD_TAGS_FIXTURE_TAG_FILES_H
#define HUD_TAGS_FIXTURE_TAG_FILES_H
char *tag_get_name(long group);
#endif
''',
    "cache/cache_files.h": r'''
#ifndef HUD_TAGS_FIXTURE_CACHE_H
#define HUD_TAGS_FIXTURE_CACHE_H
struct tag_iterator { long next; unsigned long group_tag; };
void tag_iterator_new(struct tag_iterator *iterator, unsigned long group_tag);
long tag_iterator_next(struct tag_iterator *iterator);
char *tag_get_name(long group);
#endif
''',
}

HARNESS = r'''
#include "cseries.h"
#include "bitmaps/bitmap_group.h"
#include "cache/cache_files.h"
#include <stdarg.h>

#define MAX_GROUPS 512
#define MAX_BITMAPS 3
#define RETICLE "ui\\hud\\bitmaps\\hud_reticles"
#define BACKGROUND "ui\\hud\\bitmaps\\hud_unit_backgrounds"
static const char *asset_names[] = {RETICLE, BACKGROUND, RETICLE};
static const short asset_bitmaps[] = {0, 0, 1};
static const short asset_widths[] = {128, 128, 64};
static const short asset_heights[] = {128, 32, 64};
static struct {
    char name[1024];
    unsigned long group_tag;
    int null_name;
    short bitmap_count;
    struct bitmap_data bitmaps[MAX_BITMAPS];
} groups[MAX_GROUPS];
static long group_count;
static long allocation_attempts, live_allocations, successful_allocations;
static long fail_after = -1;
static void *fixture_malloc(size_t size) {
    long attempt = allocation_attempts++;
    if (fail_after >= 0 && attempt >= fail_after) return NULL;
    void *result = malloc(size);
    if (result) { live_allocations++; successful_allocations++; }
    return result;
}
static void fixture_free(void *pointer) {
    if (pointer) { live_allocations--; free(pointer); }
}

void platform_log(const char *format, ...) { (void)format; }
long hud_hires_asset_count(void) { return 3; }
const char *hud_hires_asset_tag(long asset) { return asset_names[asset]; }
long hud_hires_asset_bitmap(long asset) { return asset_bitmaps[asset]; }
long hud_hires_asset_fits(long asset, long width, long height) {
    return width == asset_widths[asset] && height == asset_heights[asset];
}
void tag_iterator_new(struct tag_iterator *iterator, unsigned long group_tag) {
    iterator->next = 0; iterator->group_tag = group_tag;
}
long tag_iterator_next(struct tag_iterator *iterator) {
    while (iterator->next < group_count) {
        long index = iterator->next++;
        if (groups[index].group_tag == iterator->group_tag) return index;
    }
    return NONE;
}
char *tag_get_name(long group) {
    if (group < 0 || group >= group_count || groups[group].null_name) return NULL;
    return groups[group].name;
}
long tag_loaded(unsigned long group_tag, const char *name) {
    for (long index = 0; index < group_count; index++)
        if (groups[index].group_tag == group_tag && !groups[index].null_name &&
            !strcmp(groups[index].name, name)) return index;
    return NONE;
}
struct bitmap_data *bitmap_group_try_and_get_bitmap(long group, short bitmap) {
    if (group < 0 || group >= group_count || bitmap < 0 || bitmap >= groups[group].bitmap_count)
        return NULL;
    return &groups[group].bitmaps[bitmap];
}

#define malloc fixture_malloc
#define free fixture_free
#include "hud_hires_tags.c"
#undef malloc
#undef free

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "fixture line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

static void reset(void) {
    hud_hires_tags_unloaded();
    if (live_allocations) abort();
    allocation_attempts = successful_allocations = 0; fail_after = -1;
    memset(groups, 0, sizeof(groups)); group_count = 0;
}
static long add(const char *name, long bitmap, short width, short height, unsigned long address) {
    long index = group_count++;
    if (index >= MAX_GROUPS || bitmap >= MAX_BITMAPS) abort();
    if (name) {
        size_t length = strlen(name);
        if (length >= sizeof(groups[index].name)) abort();
        memcpy(groups[index].name, name, length + 1);
    } else groups[index].null_name = 1;
    groups[index].group_tag = BITMAP_GROUP_TAG;
    groups[index].bitmap_count = (short)bitmap + 1;
    for (short b = 0; b <= bitmap; b++) groups[index].bitmaps[b].cache_block_index = NONE;
    groups[index].bitmaps[bitmap] = (struct bitmap_data){width, height, index, (void *)(uintptr_t)address};
    return index;
}

static int coexist(void) {
    reset();
    add(RETICLE, 0, 128, 128, 0x1000);
    long second = add("__native_weapons\\og\\0123456789abcdef\\" RETICLE, 0, 128, 128, 0x2000);
    groups[second].bitmap_count = 2;
    groups[second].bitmaps[1] = (struct bitmap_data){64, 64, second, (void *)(uintptr_t)0x2100};
    add("__native_hud\\stock\\abcdef0123456789\\" BACKGROUND, 0, 128, 32, 0x3000);
    add("UI\\HUD\\BITMAPS\\HUD_RETICLES", 0, 128, 128, 0x4000);
    add("__native_weapons\\og\\0123456789abcdef\\UI\\hud\\bitmaps\\hud_reticles", 0, 128, 128, 0x5000);
    add("__native_hud\\stock\\abcdef0123456789\\UI\\HUD\\bitmaps\\hud_reticles", 0, 128, 128, 0x6000);
    hud_hires_tags_loaded();
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == 0);
    CHECK(hud_hires_asset_at(0x2000, 128, 128) == 0);
    CHECK(hud_hires_asset_at(0x2100, 64, 64) == 2);
    CHECK(hud_hires_asset_at(0x3000, 128, 32) == 1);
    CHECK(hud_hires_asset_at(0x3000, 128, 128) == NONE);
    CHECK(hud_hires_asset_at(0x4000, 128, 128) == 0);
    CHECK(hud_hires_asset_at(0x5000, 128, 128) == 0);
    CHECK(hud_hires_asset_at(0x6000, 128, 128) == 0);
    return 0;
}

static int malformed(void) {
    static const char *invalid[] = {
        "hud_reticles", "custom\\hud_reticles", "ui\\hud\\bitmaps\\hud_reticles_modified",
        "ui\\hud\\bitmaps\\modified_hud_reticles", RETICLE ".bitmap", RETICLE "\\extra",
        "__native_weapons\\og\\", "__native_weapons\\og\\0123456789abcde",
        "__native_weapons\\og\\0123456789abcde\\" RETICLE,
        "__native_weapons\\og\\0123456789abcdef0\\" RETICLE,
        "__native_weapons\\og\\0123456789abcdeF\\" RETICLE,
        "__native_weapons\\og\\0123456789abcdeg\\" RETICLE,
        "__native_weapons\\og\\0123456789abcdef", "__native_weapons\\og\\0123456789abcdef\\",
        "__native_weapons\\og\\0123456789abcdef\\custom\\hud_reticles",
        "__native_weapons\\og\\0123456789abcdef\\" RETICLE "_modified",
        "__native_weapons\\og\\0123456789abcdef\\..\\" RETICLE,
        "__native_weapons\\og\\0123456789abcdef\\\\" RETICLE,
        "__native_weapons\\og\\0123456789abcdef\\__native_hud\\stock\\0123456789abcdef\\" RETICLE,
        "__native_hud\\stock\\abcdef012345678\\" RETICLE,
        "__native_hud\\stock\\abcdef01234567890\\" RETICLE,
        "__native_hud\\stock\\abcdef012345678G\\" RETICLE,
        "__native_hud\\stock\\ABCDEF0123456789\\" RETICLE,
        "__native_hud\\other\\abcdef0123456789\\" RETICLE,
        "__native_weapons\\other\\abcdef0123456789\\" RETICLE,
        "prefix\\__native_weapons\\og\\0123456789abcdef\\" RETICLE,
        "__native_hud/stock/abcdef0123456789/ui/hud/bitmaps/hud_reticles",
        "__NATIVE_WEAPONS\\og\\0123456789abcdef\\" RETICLE,
        "__native_hud\\STOCK\\abcdef0123456789\\" RETICLE
    };
    reset();
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++)
        add(invalid[i], 0, 128, 128, 0x1000 + i * 256);
    add(NULL, 0, 128, 128, 0x8000);
    long not_bitmap = add(RETICLE, 0, 128, 128, 0x9000);
    groups[not_bitmap].group_tag = 'weap';
    hud_hires_tags_loaded();
    for (long i = 0; i < group_count; i++)
        CHECK(hud_hires_asset_at((unsigned long)(uintptr_t)groups[i].bitmaps[0].base_address, 128, 128) == NONE);
    return 0;
}

static int dimensions(void) {
    reset();
    add(RETICLE, 0, 512, 512, 0x1000);
    add("__native_weapons\\og\\0123456789abcdef\\" RETICLE, 0, 128, 127, 0x2000);
    add("__native_hud\\stock\\0123456789abcdef\\" BACKGROUND, 0, 128, 128, 0x3000);
    long missing = add(RETICLE, 0, 128, 128, 0x4000);
    groups[missing].bitmap_count = 0;
    hud_hires_tags_loaded();
    CHECK(hud_hires_asset_at(0x1000, 512, 512) == NONE);
    CHECK(hud_hires_asset_at(0x2000, 128, 127) == NONE);
    CHECK(hud_hires_asset_at(0x3000, 128, 128) == NONE);
    CHECK(hud_hires_asset_at(0x4000, 128, 128) == NONE);
    return 0;
}

static int cache_reuse(void) {
    reset();
    long eligible = add(RETICLE, 0, 128, 128, 0x1000);
    long unrelated = add("custom\\different_bitmap", 0, 128, 128, 0x2000);
    hud_hires_tags_loaded();
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == 0);
    CHECK(hud_hires_asset_at(0x1000, 127, 128) == NONE);
    groups[eligible].bitmaps[0].cache_block_index = NONE;
    groups[unrelated].bitmaps[0].base_address = (void *)(uintptr_t)0x1000;
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == NONE);
    groups[eligible].bitmaps[0].cache_block_index = 5;
    groups[eligible].bitmaps[0].base_address = (void *)(uintptr_t)0x3000;
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == NONE);
    CHECK(hud_hires_asset_at(0x3000, 128, 128) == 0);
    groups[eligible].bitmaps[0].base_address = NULL;
    CHECK(hud_hires_asset_at(0x3000, 128, 128) == NONE);
    CHECK(hud_hires_asset_at(0, 128, 128) == NONE);
    return 0;
}

static int capacity(void) {
    reset();
    char name[512];
    for (unsigned i = 0; i < 260; i++) {
        const char *prefix = i % 2 ? "__native_hud\\stock" : "__native_weapons\\og";
        snprintf(name, sizeof(name), "%s\\%016x\\%s", prefix, i, RETICLE);
        add(name, 0, 128, 128, 0x1000 + i * 256);
    }
    hud_hires_tags_loaded();
    for (unsigned i = 0; i < 260; i++)
        CHECK(hud_hires_asset_at(0x1000 + i * 256, 128, 128) == 0);
    hud_hires_tags_unloaded();
    for (unsigned i = 0; i < 260; i++)
        CHECK(hud_hires_asset_at(0x1000 + i * 256, 128, 128) == NONE);
    return 0;
}

static int reload(void) {
    reset(); add(RETICLE, 0, 128, 128, 0x1000);
    hud_hires_tags_loaded();
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == 0);
    hud_hires_tags_unloaded();
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == NONE);
    /* Reuse the same tag/bitmap addresses for unrelated data in the next map. */
    memset(groups, 0, sizeof(groups)); group_count = 0;
    add("custom\\new_map_bitmap", 0, 128, 128, 0x1000);
    add(BACKGROUND, 0, 128, 32, 0x2000);
    hud_hires_tags_loaded();
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == NONE);
    CHECK(hud_hires_asset_at(0x2000, 128, 32) == 1);
    /* Loading an empty map must also discard the previous registrations. */
    group_count = 0; hud_hires_tags_loaded();
    CHECK(hud_hires_asset_at(0x2000, 128, 32) == NONE);
    hud_hires_tags_unloaded(); hud_hires_tags_unloaded();
    CHECK(hud_hires_asset_at(0x2000, 128, 32) == NONE);
    return 0;
}

static int allocation_failure(void) {
    reset(); add(RETICLE, 0, 128, 128, 0x1000);
    fail_after = 0;
    hud_hires_tags_loaded();
    CHECK(allocation_attempts == 1 && live_allocations == 0);
    CHECK(hud_hires_asset_at(0x1000, 128, 128) == NONE);
    hud_hires_tags_unloaded(); CHECK(live_allocations == 0);

    reset();
    char name[512];
    for (unsigned i = 0; i < 170; i++) {
        snprintf(name, sizeof(name), "__native_weapons\\og\\%016x\\%s", i, RETICLE);
        add(name, 0, 128, 128, 0x1000 + i * 256);
    }
    fail_after = 1; /* Initial 128 records succeed; growth allocation fails. */
    hud_hires_tags_loaded();
    CHECK(allocation_attempts == 2 && successful_allocations == 1 && live_allocations == 1);
    for (unsigned i = 0; i < 128; i++)
        CHECK(hud_hires_asset_at(0x1000 + i * 256, 128, 128) == 0);
    for (unsigned i = 128; i < 170; i++)
        CHECK(hud_hires_asset_at(0x1000 + i * 256, 128, 128) == NONE);
    hud_hires_tags_unloaded(); CHECK(live_allocations == 0);
    fail_after = -1; allocation_attempts = successful_allocations = 0;
    hud_hires_tags_loaded();
    CHECK(live_allocations == 1 && successful_allocations == 2);
    CHECK(hud_hires_asset_at(0x1000 + 169 * 256, 128, 128) == 0);
    /* A subsequent map allocation failure cannot retain the prior pointers. */
    allocation_attempts = 0; fail_after = 0;
    hud_hires_tags_loaded();
    CHECK(live_allocations == 0);
    CHECK(hud_hires_asset_at(0x1000 + 169 * 256, 128, 128) == NONE);
    hud_hires_tags_unloaded(); CHECK(live_allocations == 0);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "coexist")) return coexist();
    if (!strcmp(argv[1], "malformed")) return malformed();
    if (!strcmp(argv[1], "dimensions")) return dimensions();
    if (!strcmp(argv[1], "cache_reuse")) return cache_reuse();
    if (!strcmp(argv[1], "capacity")) return capacity();
    if (!strcmp(argv[1], "reload")) return reload();
    if (!strcmp(argv[1], "allocation_failure")) return allocation_failure();
    return 2;
}
'''


ITERATOR_HARNESS = r'''
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte;
#define NONE (-1)
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "iterator fixture line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)
/* PRODUCTION ITERATOR DECLARATION */
_Static_assert(sizeof(((struct tag_iterator *)0)->absolute_index) == 2,
               "production tag iterator retains its signed 16-bit index");
_Static_assert(SHRT_MAX == 32767, "fixture requires the guest short range");
struct cache_file_tag_instance {
    long group_tag, parent_group_tags[2], tag_index;
};
struct cache_file_tag_header { long tag_count; };
static struct cache_file_tag_header header;
static struct { struct cache_file_tag_header *tag_header; } cache_file_globals = {&header};
static struct cache_file_tag_instance *global_tag_instances;
/* PRODUCTION ITERATOR FUNCTIONS */

static void populate(long count, long group) {
    free(global_tag_instances);
    global_tag_instances = calloc((size_t)(count ? count : 1), sizeof(*global_tag_instances));
    if (!global_tag_instances) abort();
    header.tag_count = count;
    for (long i = 0; i < count; i++) {
        global_tag_instances[i].group_tag = group;
        global_tag_instances[i].parent_group_tags[0] = NONE;
        global_tag_instances[i].parent_group_tags[1] = NONE;
        global_tag_instances[i].tag_index = 0x10000 + i;
    }
}

static int all_tags(void) {
    const long counts[] = {0, 32767, 32768, 32769, 40000};
    for (unsigned sample = 0; sample < sizeof(counts) / sizeof(counts[0]); sample++) {
        long count = counts[sample], addressable = count < 32768 ? count : 32768;
        struct tag_iterator iterator;
        memset(&iterator, 0xff, sizeof(iterator));
        populate(count, 'bitm');
        tag_iterator_new(&iterator, NONE);
        CHECK(iterator.absolute_index == 0 && iterator.group_tag == NONE);
        for (long i = 0; i < addressable; i++)
            CHECK(tag_iterator_next(&iterator) == 0x10000 + i);
        for (int i = 0; i < 8; i++) CHECK(tag_iterator_next(&iterator) == NONE);
        CHECK(count >= 32768 ? iterator.absolute_index < 0 : iterator.absolute_index == count);
    }
    free(global_tag_instances); global_tag_instances = NULL;
    return 0;
}

static int filtered_tags(void) {
    const long counts[] = {32767, 32768, 40000};
    for (unsigned sample = 0; sample < sizeof(counts) / sizeof(counts[0]); sample++) {
        long count = counts[sample], last = count < 32768 ? count - 1 : 32767;
        struct tag_iterator iterator;
        populate(count, 'weap');
        tag_iterator_new(&iterator, 'bitm');
        for (int i = 0; i < 8; i++) CHECK(tag_iterator_next(&iterator) == NONE);
        global_tag_instances[last].group_tag = 'bitm';
        tag_iterator_new(&iterator, 'bitm');
        CHECK(tag_iterator_next(&iterator) == 0x10000 + last);
        for (int i = 0; i < 8; i++) CHECK(tag_iterator_next(&iterator) == NONE);
        if (count > 32768) {
            /* No out-of-range tag becomes addressable merely by matching. */
            global_tag_instances[last].group_tag = 'weap';
            global_tag_instances[32768].group_tag = 'bitm';
            global_tag_instances[count - 1].group_tag = 'bitm';
            tag_iterator_new(&iterator, 'bitm');
            for (int i = 0; i < 8; i++) CHECK(tag_iterator_next(&iterator) == NONE);
        }
    }
    free(global_tag_instances); global_tag_instances = NULL;
    return 0;
}

static int parent_groups_and_negative_state(void) {
    struct tag_iterator iterator;
    populate(4, 'snd!');
    global_tag_instances[1].parent_group_tags[0] = 'bitm';
    global_tag_instances[3].parent_group_tags[1] = 'bitm';
    tag_iterator_new(&iterator, 'bitm');
    CHECK(tag_iterator_next(&iterator) == 0x10001);
    CHECK(tag_iterator_next(&iterator) == 0x10003);
    CHECK(tag_iterator_next(&iterator) == NONE);
    iterator.absolute_index = -1;
    for (int i = 0; i < 8; i++) CHECK(tag_iterator_next(&iterator) == NONE);
    free(global_tag_instances); global_tag_instances = NULL;
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "all")) return all_tags();
    if (!strcmp(argv[1], "filtered")) return filtered_tags();
    if (!strcmp(argv[1], "parents")) return parent_groups_and_negative_state();
    return 2;
}
'''


class HudHiresTagsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("A local C compiler is required for the HUD registry fixture")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-hud-tags-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        for name, source in HEADERS.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        wrapper = folder / "registry.c"
        wrapper.write_text(HARNESS)
        cls.executable = folder / ("registry.exe" if sys.platform == "win32" else "registry")
        command = [compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Wno-multichar",
                   "-I", str(folder), "-I", str(ROOT / "port/linux/game"),
                   str(wrapper), "-o", str(cls.executable)]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError("Production HUD registry fixture did not compile:\n" + result.stdout + result.stderr)

    def run_fixture(self, name):
        result = subprocess.run([str(self.executable), name], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_canonical_and_two_private_namespaces_coexist_and_map_bitmap_indices(self):
        self.run_fixture("coexist")

    def test_only_complete_exact_original_paths_with_strict_namespace_hashes_match(self):
        self.run_fixture("malformed")

    def test_dimensions_missing_bitmap_and_wrong_tag_classes_do_not_register(self):
        self.run_fixture("dimensions")

    def test_cleared_cache_blocks_null_storage_and_reused_addresses_are_rejected(self):
        self.run_fixture("cache_reuse")

    def test_more_than_128_eligible_copies_register_and_all_unload(self):
        self.run_fixture("capacity")

    def test_unload_and_reload_clear_previous_map_registrations_even_when_storage_reused(self):
        self.run_fixture("reload")

    def test_initial_and_growth_allocation_failure_keep_safe_fallback_and_recover(self):
        self.run_fixture("allocation_failure")


class ProductionTagIteratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("A local C compiler is required for the production iterator fixture")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-hud-tag-iterator-")
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        source = (ROOT / "source/cache/cache_files.c").read_text()
        start = source.index("\nvoid tag_iterator_new(\n")
        end = source.index("\nboolean cache_file_header_verify(\n", start)
        functions = source[start:end]
        declaration = re.search(r"(?ms)^struct tag_iterator\n\{.*?^\};",
                                (ROOT / "source/cache/cache_files.h").read_text())
        if declaration is None or functions.count("long tag_iterator_next(") != 1:
            raise ValueError("Expected the production iterator declaration and its exact two functions")
        fixture = ITERATOR_HARNESS.replace("/* PRODUCTION ITERATOR DECLARATION */", declaration[0])
        fixture = fixture.replace("/* PRODUCTION ITERATOR FUNCTIONS */", functions)
        wrapper = folder / "iterator.c"
        wrapper.write_text(fixture)
        cls.executable = folder / ("iterator.exe" if sys.platform == "win32" else "iterator")
        result = subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Wno-multichar",
                                 str(wrapper), "-o", str(cls.executable)], text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError("Production tag iterator fixture did not compile:\n" + result.stdout + result.stderr)

    def run_fixture(self, name):
        result = subprocess.run([str(self.executable), name], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_signed_short_capacity_and_exhausted_calls_stop_safely(self):
        self.run_fixture("all")

    def test_no_match_last_addressable_match_and_unaddressable_matches(self):
        self.run_fixture("filtered")

    def test_parent_group_filter_and_negative_iterator_state(self):
        self.run_fixture("parents")


if __name__ == "__main__":
    unittest.main()
