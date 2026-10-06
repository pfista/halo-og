"""Exercise production texture-budget lifecycle and LRU page pressure.

Physical allocation/read completion are controlled dependencies. The actual
budget selection, memory replacement, borrowing and LRU allocation functions
run with sanitizers; the fixture does not certify physical renderer output.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_runtime_ui_tags import c_block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "halo_port_capacity.h"
#include "halo_expanded_cache.h"
typedef unsigned char byte;
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define SHORT_BITS 16
#define NUMBEROF(x) (sizeof(x)/sizeof((x)[0]))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define FLAG(n) (1u<<(n))
#define csmemset memset
#define csstrncpy strncpy
#define _stricmp strcasecmp
#define match_assert(file,line,test) assert(test)
#define match_malloc(file,line,size) malloc(size)
#define match_free(file,line,pointer) free(pointer)
#define PAGE_READWRITE 4
#define PAGE_READONLY 2
#define PAGE_WRITECOMBINE 0x400
struct data_array {
    short maximum_count,size,actual_count;
    int valid;
    byte *data,*used;
};
struct data_iterator { struct data_array *data; long datum_index,next; };
static long data_allocation_size(short count,short size) {
    (void)count;(void)size;return sizeof(struct data_array);
}
static void data_initialize(struct data_array *data,char const *name,short count,short size) {
    (void)name;memset(data,0,sizeof(*data));data->maximum_count=count;data->size=size;
    data->data=calloc((unsigned)count,(unsigned)size);data->used=calloc((unsigned)count,1);
    assert(data->data && data->used);
}
static void data_make_valid(struct data_array *data) { data->valid=TRUE; }
static void data_verify(struct data_array *data) {
    assert(data && data->valid && data->actual_count>=0 && data->actual_count<=data->maximum_count);
}
static void data_dispose(struct data_array *data) { free(data->data);free(data->used); }
static void *datum_get(struct data_array *data,long index) {
    data_verify(data);assert(index>=0 && index<data->maximum_count && data->used[index]);
    return data->data+index*data->size;
}
static long datum_new(struct data_array *data) {
    for(long i=0;i<data->maximum_count;i++) if(!data->used[i]) {
        data->used[i]=1;data->actual_count++;memset(data->data+i*data->size,0,(unsigned)data->size);return i;
    }
    return NONE;
}
static void datum_delete(struct data_array *data,long index) {
    (void)datum_get(data,index);data->used[index]=0;data->actual_count--;
}
static void data_iterator_new(struct data_iterator *iterator,struct data_array *data) {
    iterator->data=data;iterator->next=0;iterator->datum_index=NONE;
}
static void *data_iterator_next(struct data_iterator *iterator) {
    while(iterator->next<iterator->data->maximum_count) {
        long index=iterator->next++;
        if(iterator->data->used[index]) { iterator->datum_index=index;return datum_get(iterator->data,index); }
    }
    return NULL;
}
/* LRU STRUCTURES */
/* PRODUCTION LRU */
/* CACHE CONSTANTS */
/* PHYSICAL STRUCTURE */
static struct physical_memory_map_globals physical_memory_map_globals;
static long physical_memory_texture_cache_size=HALO_PORT_TEXTURE_CACHE_SIZE;
static int allocation_fail,allocations,frees;
static long last_allocation_size;
static void *XPhysicalAlloc(long size,long address,long alignment,long protection) {
    (void)address;(void)alignment;(void)protection;allocations++;last_allocation_size=size;
    return allocation_fail?NULL:malloc((size_t)size);
}
static void XPhysicalFree(void *memory) { assert(memory);frees++;free(memory); }
static unsigned protections;
static long last_protected_size;
static void *last_protected_address;
static void XPhysicalProtect(void *base,long size,long protection) {
    (void)protection;assert(size>0);
    uintptr_t offset=(uintptr_t)base-(uintptr_t)physical_memory_map_globals.texture_cache_base_address;
    assert(offset+(unsigned long)size<=(unsigned long)physical_memory_texture_cache_size);
    protections++;last_protected_size=size;last_protected_address=base;
}
/* PRODUCTION PHYSICAL */
static struct data_array texture_slots;
static struct { struct data_array *textures; byte *base_address; struct lruv_cache *cache;
    boolean stolen_memory; } xbox_texture_cache_globals;
static long texture_cache_page_count=XBOX_TEXTURE_CACHE_PAGE_COUNT;
static struct native_map_cache_selection selection;
struct native_map_cache_selection const *native_map_cache_current(void) { return &selection; }
static unsigned budget_logs;
static char budget_log[256];
void platform_log(char const *format,...) {
    va_list args;va_start(args,format);vsnprintf(budget_log,sizeof(budget_log),format,args);va_end(args);budget_logs++;
}
/* PRODUCTION TEXTURE */
'''

HARNESS = r'''
static unsigned deletion_callbacks;
static void deleted_block(long index) { (void)index;deletion_callbacks++; }
static boolean locked_block(long index) { (void)index;return FALSE; }
static void setup(void) {
    physical_memory_map_globals.texture_cache_base_address=XPhysicalAlloc(HALO_PORT_TEXTURE_CACHE_SIZE,-1,0,4);
    assert(physical_memory_map_globals.texture_cache_base_address);
    assert(last_allocation_size==HALO_PORT_TEXTURE_CACHE_SIZE);
    data_initialize(&texture_slots,"textures",XBOX_TEXTURE_CACHE_PAGE_COUNT,32);data_make_valid(&texture_slots);
    xbox_texture_cache_globals.textures=&texture_slots;
    xbox_texture_cache_globals.cache=lruv_new("fixture",XBOX_TEXTURE_CACHE_PAGE_COUNT,14,
        XBOX_TEXTURE_CACHE_PAGE_COUNT,deleted_block,locked_block);
    xbox_texture_cache_globals.base_address=physical_memory_get_texture_cache_base_address();
}
static void teardown(void) {
    lruv_flush(xbox_texture_cache_globals.cache);lruv_delete(xbox_texture_cache_globals.cache);
    data_dispose(&texture_slots);XPhysicalFree(physical_memory_get_texture_cache_base_address());
}
static void configure(char const *name,int expanded) {
    memset(&selection,0,sizeof(selection));selection.expanded=expanded;selection.generation=1;
    snprintf(selection.logical_name,sizeof(selection.logical_name),"chillout_digsite");
    snprintf(selection.physical_name,sizeof(selection.physical_name),"_fiesta_chillout_digsite");
    assert(texture_cache_set_map(name));
}
static void assert_budget(long size) {
    assert(physical_memory_texture_cache_size==size);
    assert(texture_cache_page_count==(size>>14));
    assert(xbox_texture_cache_globals.cache->page_count==(size>>14));
    assert(xbox_texture_cache_globals.base_address==physical_memory_get_texture_cache_base_address());
}
static void pressure(void) {
    struct lruv_cache *cache=xbox_texture_cache_globals.cache;
    /* The observed cold-load case: every original page is pinned in the same
       allocator tick. One more read cannot fit until the map budget grows. */
    assert(lruv_block_new(cache,HALO_PORT_TEXTURE_CACHE_SIZE)!=NONE);
    long extra=lruv_block_new(cache,171*(1<<14));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(extra!=NONE);
#else
    assert(extra==NONE);
#endif
    /* Page-usage diagnostics must write within a buffer for the active budget. */
    byte usage[(HALO_PORT_GLOBAL_FIESTA_TEXTURE_CACHE_SIZE>>14)+8];memset(usage,0xA5,sizeof(usage));
    lruv_cache_get_page_usage(cache,usage);
    for(unsigned i=(unsigned)cache->page_count;i<sizeof(usage);i++) assert(usage[i]==0xA5);
    lruv_flush(cache);
}
static void borrow_and_return(void) {
    long pages=texture_cache_page_count;
    unsigned old_protections=protections;
    void *borrowed=texture_cache_steal_memory(1<<20);
    assert(borrowed && xbox_texture_cache_globals.stolen_memory);
    assert(xbox_texture_cache_globals.cache->page_count==pages-2*(0x104000>>14)-65);
    assert(protections==old_protections+3);
    texture_cache_return_memory();assert(!xbox_texture_cache_globals.stolen_memory);
    assert(xbox_texture_cache_globals.cache->page_count==pages);
    assert(last_protected_address==physical_memory_get_texture_cache_base_address());
    assert(last_protected_size==pages*(1<<14));
}
int main(int argc,char **argv) {
    assert(argc==2);setup();assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
    if(!strcmp(argv[1],"lifecycle")) {
        configure("chillout_digsite",0);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        configure("ui",1);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        configure("a10",1);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        configure("prisoner",1);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        configure("_fiesta_chillout_digsite",1);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        configure("CHILLOUT_DIGSITE",1);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert_budget(HALO_PORT_GLOBAL_FIESTA_TEXTURE_CACHE_SIZE);
        assert(last_allocation_size==HALO_PORT_GLOBAL_FIESTA_TEXTURE_CACHE_SIZE);
        assert(budget_logs==1 && strstr(budget_log,"32 MiB for CHILLOUT_DIGSITE"));
#else
        assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        assert(budget_logs==0);
#endif
        int old_allocations=allocations,old_frees=frees;unsigned old_logs=budget_logs;
        configure("chillout_digsite",1);assert(allocations==old_allocations && frees==old_frees);
        assert(budget_logs==old_logs);
        /* A pending lobby change does not change an already-open cache or its
           borrowing budget. Only the next explicit map hook can select pages. */
        strcpy(selection.logical_name,"prisoner");selection.expanded=FALSE;
        borrow_and_return();configure("ui",1);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        assert(last_allocation_size==HALO_PORT_TEXTURE_CACHE_SIZE);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(budget_logs==2 && strstr(budget_log,"22 MiB for ui"));
#endif
        borrow_and_return();assert(xbox_texture_cache_globals.cache->blocks->maximum_count==1408);
    } else if(!strcmp(argv[1],"pressure")) {
        configure("chillout_digsite",1);pressure();
    } else if(!strcmp(argv[1],"failure")) {
        void *old=physical_memory_get_texture_cache_base_address();int old_frees=frees;
        assert(!physical_memory_resize_texture_cache(-1));assert(frees==old_frees);
        assert(!physical_memory_resize_texture_cache(0x4000000));assert(frees==old_frees);
        allocation_fail=TRUE;selection.expanded=TRUE;strcpy(selection.logical_name,"chillout_digsite");
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(!texture_cache_set_map("chillout_digsite"));
        assert(last_allocation_size==HALO_PORT_GLOBAL_FIESTA_TEXTURE_CACHE_SIZE);
#else
        assert(texture_cache_set_map("chillout_digsite"));
#endif
        assert(frees==old_frees && physical_memory_get_texture_cache_base_address()==old);
        assert(texture_slots.valid && xbox_texture_cache_globals.cache->blocks->valid);
        assert(texture_slots.actual_count==0 && xbox_texture_cache_globals.cache->blocks->actual_count==0);
        assert(!xbox_texture_cache_globals.stolen_memory && deletion_callbacks==0);
        assert(xbox_texture_cache_globals.cache->delete_block_proc==deleted_block);
        assert(xbox_texture_cache_globals.cache->locked_block_proc==locked_block);
        assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);assert(budget_logs==0);allocation_fail=FALSE;
        configure("chillout_digsite",1);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        /* A failed ordinary-map replacement also preserves the currently
           allocated arena, reports failure, and never exposes a stale base. */
        old=physical_memory_get_texture_cache_base_address();old_frees=frees;allocation_fail=TRUE;
        assert(!texture_cache_set_map("ui"));assert(frees==old_frees);
        assert(last_allocation_size==HALO_PORT_TEXTURE_CACHE_SIZE);
        assert(old==physical_memory_get_texture_cache_base_address());
        assert_budget(HALO_PORT_GLOBAL_FIESTA_TEXTURE_CACHE_SIZE);allocation_fail=FALSE;
#endif
        configure("ui",1);assert_budget(HALO_PORT_TEXTURE_CACHE_SIZE);
        assert(last_allocation_size==HALO_PORT_TEXTURE_CACHE_SIZE);
    } else return 2;
    teardown();puts("texture budget fixture passed");return 0;
}
'''


def fixture():
    texture = (ROOT / "source/cache/xbox_texture_cache.c").read_text()
    physical = (ROOT / "source/cache/physical_memory_map.c").read_text()
    lru = (ROOT / "source/memory/lruv_cache.c").read_text()
    lru = re.sub(r'^#include.*\n', '', lru, flags=re.M)
    lru = lru.replace(c_block(lru, "void lruv_debug_to_file(\n"), "")
    header = (ROOT / "source/memory/lruv_cache.h").read_text()
    structures = header[header.index("typedef void (*lruv_delete_block_proc)"):header.index("typedef char lruv_cache_size_assert")]
    constants = c_block(texture, "enum\n") + ";"
    functions = "\n".join(c_block(texture, signature) for signature in (
        "boolean texture_cache_set_map(\n", "void *texture_cache_steal_memory(\n", "void texture_cache_return_memory(\n"))
    memory_functions = "\n".join(c_block(physical, signature) for signature in (
        "void *physical_memory_get_texture_cache_base_address(\n", "int physical_memory_resize_texture_cache(\n"))
    return (PREFIX.replace("/* LRU STRUCTURES */", structures)
            .replace("/* PRODUCTION LRU */", lru)
            .replace("/* CACHE CONSTANTS */", constants + "\n#define TEXTURE_CACHE_SIZE HALO_PORT_TEXTURE_CACHE_SIZE")
            .replace("/* PHYSICAL STRUCTURE */", c_block(physical, "struct physical_memory_map_globals\n") + ";")
            .replace("/* PRODUCTION PHYSICAL */", memory_functions)
            .replace("/* PRODUCTION TEXTURE */", functions) + HARNESS)


class TextureCacheBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-texture-budget-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / "fixture.c"
        source.write_text(fixture())
        cls.executables = {}
        for native in (False, True):
            executable = directory / ("native" if native else "retail")
            command = [shutil.which("clang") or shutil.which("cc"), "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                       "-Wno-unused-function", "-Wno-unused-variable", "-Wno-multichar", "-iquote", str(ROOT / "port/linux/include")]
            if sys.platform != "win32":
                command.append("-fsanitize=address,undefined")
            if native:
                command.append("-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=128")
            result = subprocess.run([*command, str(source), "-o", str(executable)], capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.executables[native] = executable

    def run_fixture(self, name):
        for native, executable in self.executables.items():
            with self.subTest(native=native):
                result = subprocess.run([str(executable), name], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("fixture passed", result.stdout)

    def test_normal_and_expanded_transitions_and_borrowing(self):
        self.run_fixture("lifecycle")

    def test_locked_original_pages_leave_room_only_in_expanded_mode(self):
        self.run_fixture("pressure")

    def test_failed_or_invalid_allocation_preserves_live_base_and_budget(self):
        self.run_fixture("failure")

    def test_scenario_hook_runs_at_empty_cache_boundary(self):
        source = (ROOT / "source/cache/cache_files.c").read_text()
        load = c_block(source, "long scenario_tags_load(\n")
        self.assertLess(load.index("texture_cache_open()"), load.index("texture_cache_set_map(stripped_scenario_name)"))
        self.assertLess(load.index("texture_cache_set_map(stripped_scenario_name)"), load.index("cache_file_open("))
        self.assertIn("return NONE;", load[:load.index("cache_file_open(")])

    def test_physical_header_is_self_contained_in_gnu89_ilp32(self):
        # game_state_xbox.c includes this header before cseries.h. Preserve
        # its existing built-in-only API instead of imposing a boolean typedef
        # dependency. No host SDK/library is required for this declaration check.
        source = Path(self.temporary.name) / "physical-header.c"
        source.write_text('#include "cache/physical_memory_map.h"\n'
                          'typedef char ilp32[(sizeof(void *)==4 && sizeof(long)==4)?1:-1];\n'
                          'int (*resize_texture_cache)(long)=physical_memory_resize_texture_cache;\n')
        result = subprocess.run([shutil.which("clang") or shutil.which("cc"), "-target", "i386-unknown-linux-gnu",
                                 "-std=gnu89", "-fsyntax-only", "-nostdinc", "-Wall", "-Wextra", "-Werror",
                                 "-iquote", str(ROOT / "source"), str(source)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
