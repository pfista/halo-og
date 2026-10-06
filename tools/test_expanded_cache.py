"""Run the production hidden-arsenal resolver with bounded synthetic cache data.

Guest tag layouts come from production definitions with fixed-width pointer and
long fields. File APIs use local temporary files; no installed game data changes.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from tools.test_network_pings import block
from tools.test_custom_maps import header

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>
#include <zlib.h>
#include "halo_expanded_cache.h"
#include "halo_expanded_cache_weapons.h"
#include "halo_sha256.h"
#define TRUE 1
#define FALSE 0
#define NUMBEROF(a) (sizeof(a)/sizeof((a)[0]))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define HALO_PORT_MULTIPLAYER_CACHE_SIZE 0x08000000
#define _stricmp strcasecmp
#define _strnicmp strncasecmp
#define csstrlen strlen
#define INVALID_FILE_SIZE UINT32_MAX
#define INVALID_SET_FILE_POINTER UINT32_MAX
#define FILE_BEGIN SEEK_SET
#define GENERIC_READ 1
#define OPEN_EXISTING 1
#define INVALID_HANDLE_VALUE ((HANDLE)-1)
typedef FILE *HANDLE;
typedef struct { uint32_t low,high; } FILETIME;
typedef unsigned char byte;
typedef unsigned short word;
typedef unsigned char boolean;
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define HALO_MACOS 1
#define NONE (-1)
typedef float real;
typedef struct { real x,y,z; } real_point3d, real_vector3d;
struct tag_reference { uint32_t group_tag,name; int32_t name_length,index; };
struct tag_block { int32_t count; uint32_t address,definition; };
/* TAG DECLARATIONS */
enum { _weapon_must_be_readied_bit=3, _weapon_doesnt_count_toward_maximum_bit=4 };
struct game_variant { unsigned flags; struct { short weapon_set; unsigned flags; } universal_variant; };
static unsigned performance_variant_get_flags(struct game_variant const *v) { return v?v->flags:0; }
enum { _starting_equipment_custom=0,_starting_equipment_generic=1,_starting_equipment_fiesta=2,_performance_option_fiesta=128 };
/* VARIANT HELPERS */
static char fixture_directory[256], fixture_managed[256], shown[512];
static int download_status;
static unsigned download_requests;
static char requested_map[32], requested_base[65], requested_cache[65];
static unsigned file_reads;
char const *cache_files_map_directory(void) { return fixture_directory; }
char const *cache_files_build_region(char const *build) {
    return !strcmp(build,"01.10.12.2276") || !strcmp(build,"01.01.14.2342") ? "region" : NULL;
}
static HANDLE CreateFileA(char const *name,int access,int share,void *security,int creation,int flags,void *template) {
    char path[512];(void)access;(void)share;(void)security;(void)creation;(void)flags;(void)template;
    if(!strncmp(name,"m:\\",3)) snprintf(path,sizeof(path),"%s/%s",fixture_managed,name+3);
    else snprintf(path,sizeof(path),"%s",name);for(unsigned i=0;path[i];i++) if(path[i]=='\\') path[i]='/';
    FILE *file=fopen(path,"rb");return file?file:INVALID_HANDLE_VALUE;
}
static unsigned GetLastError(void) { return 0; }
static int CloseHandle(HANDLE file) { return !fclose(file); }
static int ReadFile(HANDLE file,void *data,uint32_t size,uint32_t *read,void *context) {
    (void)context;file_reads++;*read=(uint32_t)fread(data,1,size,file);return !ferror(file);
}
static uint32_t SetFilePointer(HANDLE file,int32_t offset,void *high,int method) {
    (void)high;return fseek(file,offset,method)?UINT32_MAX:(uint32_t)ftell(file);
}
static uint32_t GetFileSize(HANDLE file,uint32_t *high) {
    struct stat info;if(fstat(fileno(file),&info)) return UINT32_MAX;
    if(high) *high=(uint32_t)((uint64_t)info.st_size>>32);return (uint32_t)info.st_size;
}
static int GetFileTime(HANDLE file,FILETIME *changed,void *access,FILETIME *written) {
    struct stat info;(void)access;if(fstat(fileno(file),&info)) return FALSE;
#ifdef __APPLE__
    uint64_t c=(uint64_t)info.st_ctimespec.tv_sec*1000000000+info.st_ctimespec.tv_nsec;
    uint64_t m=(uint64_t)info.st_mtimespec.tv_sec*1000000000+info.st_mtimespec.tv_nsec;
#else
    uint64_t c=(uint64_t)info.st_ctim.tv_sec*1000000000+info.st_ctim.tv_nsec;
    uint64_t m=(uint64_t)info.st_mtim.tv_sec*1000000000+info.st_mtim.tv_nsec;
#endif
    changed->low=(uint32_t)c;changed->high=(uint32_t)(c>>32);
    written->low=(uint32_t)m;written->high=(uint32_t)(m>>32);return TRUE;
}
void platform_show_message(char const *title,char const *message) { snprintf(shown,sizeof(shown),"%s: %s",title,message); }
/* MAP HELPERS */
int halo_map_download_directory(char *out,unsigned long capacity) {
    if(!fixture_managed[0]) return 0;
    snprintf(out,capacity,"%s",fixture_managed);return 1;
}
int halo_arsenal_download_request(char const *map,char const *base,char const *cache) {
    download_requests++;snprintf(requested_map,32,"%s",map);snprintf(requested_base,65,"%s",base);
    snprintf(requested_cache,65,"%s",cache?cache:"");return download_status;
}
int native_map_download_pending(char const *map) { (void)map;return 0; }
int native_map_get_original_path(char const *map,char *path,unsigned capacity) {
    int length=snprintf(path,capacity,"%s%s.map",fixture_directory,native_map_basename(map));
    return length>=0 && (unsigned)length<capacity;
}
/* PRODUCTION RESOLVER */
#define NUMBER_OF_CACHED_MAP_FILES 6
struct cached_map_file { struct { char name[32]; } header; };
static struct cached_map_file fixture_slots[NUMBER_OF_CACHED_MAP_FILES];
static struct native_map_cache_selection expanded_cache_slots[NUMBER_OF_CACHED_MAP_FILES];
static struct cached_map_file *cached_map_file_get(short index) { return &fixture_slots[index]; }
/* PRODUCTION CACHE LOOKUP */
void fixture_slot(unsigned index,char const *name,struct native_map_cache_selection const *selection) {
    snprintf(fixture_slots[index].header.name,32,"%s",name);
    if(selection) expanded_cache_slots[index]=*selection;
    else memset(&expanded_cache_slots[index],0,sizeof(expanded_cache_slots[index]));
}
int fixture_find(char const *name) { return cached_map_files_find_map(name); }
void fixture_reset(char const *directory) {
    snprintf(fixture_directory,sizeof(fixture_directory),"%s/",directory);
    memset(&pending_cache,0,sizeof(pending_cache));memset(&verified_cache,0,sizeof(verified_cache));
    memset(&original_cache,0,sizeof(original_cache));fixture_managed[0]=shown[0]=0;file_reads=download_requests=0;
    download_status=0;last_download_status=0;requested_map[0]=requested_base[0]=requested_cache[0]=0;
    memset(fixture_slots,0,sizeof(fixture_slots));memset(expanded_cache_slots,0,sizeof(expanded_cache_slots));
}
int fixture_prepare(char const *map,int set,int fiesta,struct native_map_cache_selection *selection) {
    struct game_variant variant={0};variant.universal_variant.weapon_set=(short)set;variant.flags=fiesta?128:0;
    return native_map_cache_prepare(map,&variant,selection,1);
}
void fixture_managed_root(char const *root) { snprintf(fixture_managed,256,"%s",root); }
void fixture_download(int status) { download_status=status; }
unsigned fixture_requests(void) { return download_requests; }
char const *fixture_requested(unsigned field) { return field==0?requested_map:field==1?requested_base:requested_cache; }
int fixture_expected(char const *map,char const *expected,struct native_map_cache_selection *selection) {
    struct game_variant variant={0};unsigned char digest[32];
    variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;variant.flags=128;
    if(!digest_from_hex(expected,digest))return 0;
    return native_map_cache_prepare_expected(map,&variant,digest,selection,1);
}
char const *fixture_error(void) { return shown; }
unsigned fixture_reads(void) { return file_reads; }
char const *fixture_weapon(unsigned index) { return native_expanded_cache_weapon_names[index]; }
unsigned fixture_weapon_count(void) { return NUMBEROF(native_expanded_cache_weapon_names); }
unsigned fixture_layout(unsigned field) {
    switch(field) {
    case 0:return sizeof(struct weapon_definition);
    case 1:return offsetof(struct weapon_definition,weapon.flags);
    case 2:return offsetof(struct weapon_definition,weapon.interface_definition.first_person_model.index);
    case 3:return offsetof(struct weapon_definition,weapon.interface_definition.first_person_animations.index);
    case 4:return sizeof(struct game_globals);
    case 5:return offsetof(struct game_globals,multiplayer_information.count);
    case 6:return offsetof(struct game_globals,multiplayer_information.address);
    case 7:return sizeof(struct game_globals_multiplayer_information);
    case 8:return offsetof(struct game_globals_multiplayer_information,unit.index);
    case 9:return offsetof(struct game_globals,player_information.count);
    case 10:return offsetof(struct game_globals,player_information.address);
    case 11:return sizeof(struct game_globals_player_information);
    case 12:return offsetof(struct game_globals_player_information,player_unit.index);
    } return 0;
}
int fixture_arena(unsigned char const *data,unsigned length) { return arsenal_tags_valid(data,length); }
'''


def production_fixture():
    declarations = []
    for path, names in (
        ("source/game/aim_assist.h", ("aim_assist_parameters",)),
        ("source/objects/object_definitions.h", ("_object_definition",)),
        ("source/items/item_definitions.h", ("_item_definition",)),
        ("source/items/weapon_definitions.h", ("weapon_interface_definition", "_weapon_definition", "weapon_definition")),
        ("source/game/game_globals.h", ("game_globals_multiplayer_information", "game_globals_player_information", "game_globals")),
    ):
        text = (ROOT / path).read_text()
        declarations += [block(text, f"struct {name}\n") + ";" for name in names]
    declarations = "\n".join(declarations)
    declarations = re.sub(r"\bunsigned long\b", "uint32_t", declarations)
    declarations = re.sub(r"\blong\b", "int32_t", declarations)
    weapons = (ROOT / "source/game/weapon_sets.h").read_text()
    helpers = block(weapons, "enum\n") + ";\n" + block(weapons, "static inline int game_variant_uses_expanded_weapon_set(")
    helpers += "\n" + block((ROOT / "source/game/starting_equipment.h").read_text(), "static inline short starting_equipment_get(")
    custom = (ROOT / "port/linux/game/custom_maps.c").read_text()
    maps = "\n".join(block(custom, signature) for signature in (
        "char const *native_map_basename(", "static unsigned long little_u32(", "int native_map_header_valid("))
    ce_header = (ROOT / "port/linux/game/custom_edition_cache.h").read_text()
    maps += "\n" + re.search(r'^#define CUSTOM_EDITION_LEVEL_NAME_PREFIX .+$', ce_header, re.M).group(0)
    maps += "\n" + block((ROOT / "port/linux/game/custom_edition_cache.c").read_text(), "boolean custom_edition_level_name(")
    resolver = (ROOT / "port/linux/game/expanded_cache.c").read_text()
    resolver = re.sub(r'^#include.*\n', '', resolver, flags=re.M)
    resolver = re.sub(r"\bunsigned long\b", "uint32_t", resolver)
    resolver = re.sub(r"\blong\b", "int32_t", resolver)
    maps = re.sub(r"\bunsigned long\b", "uint32_t", maps)
    cache = (ROOT / "source/cache/cache_files_windows.c").read_text()
    lookup = block(cache[cache.rindex("static short cached_map_files_find_map("):], "static short cached_map_files_find_map(")
    return PREFIX.replace("/* TAG DECLARATIONS */", declarations).replace("/* VARIANT HELPERS */", helpers).replace("/* MAP HELPERS */", maps).replace("/* PRODUCTION RESOLVER */", resolver).replace("/* PRODUCTION CACHE LOOKUP */", lookup)


class Selection(ctypes.Structure):
    _fields_ = [("logical_name", ctypes.c_char * 32), ("physical_name", ctypes.c_char * 32),
                ("sha256", ctypes.c_ubyte * 32), ("weapon_list_sha256", ctypes.c_ubyte * 32),
                ("generation", ctypes.c_uint), ("expanded", ctypes.c_int), ("physical_path", ctypes.c_char * 256)]


class ExpandedCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = tempfile.TemporaryDirectory(prefix="halo-arsenal-fixture-")
        cls.addClassCleanup(cls.runtime.cleanup)
        path = Path(cls.runtime.name) / "runtime.c"
        path.write_text(production_fixture())
        library = path.with_suffix(".dylib" if sys.platform == "darwin" else ".so")
        compiler = shutil.which("clang") or shutil.which("cc")
        result = subprocess.run([compiler, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-D_DARWIN_C_SOURCE=1", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                                 "-iquote", str(ROOT / "port/linux/include"), str(path), "-lz", "-o", str(library)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.fixture_reset.argtypes = [ctypes.c_char_p]
        cls.lib.fixture_prepare.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(Selection)]
        cls.lib.fixture_managed_root.argtypes = [ctypes.c_char_p]
        cls.lib.fixture_download.argtypes = [ctypes.c_int]
        cls.lib.fixture_requested.argtypes = [ctypes.c_uint]
        cls.lib.fixture_requested.restype = ctypes.c_char_p
        cls.lib.fixture_expected.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(Selection)]
        cls.lib.fixture_error.restype = ctypes.c_char_p
        cls.lib.fixture_weapon.argtypes = [ctypes.c_uint]
        cls.lib.fixture_weapon.restype = ctypes.c_char_p
        cls.lib.fixture_slot.argtypes = [ctypes.c_uint, ctypes.c_char_p, ctypes.POINTER(Selection)]
        cls.lib.fixture_find.argtypes = [ctypes.c_char_p]
        cls.lib.fixture_layout.argtypes = [ctypes.c_uint]
        cls.lib.fixture_arena.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        cls.lib.native_map_cache_select.argtypes = [ctypes.POINTER(Selection)]
        cls.lib.native_map_cache_resolve.argtypes = [ctypes.c_char_p]
        cls.lib.native_map_cache_resolve.restype = ctypes.c_char_p
        cls.lib.native_map_cache_selection_equal.argtypes = [ctypes.POINTER(Selection), ctypes.POINTER(Selection)]
        cls.lib.native_map_cache_physical_name.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
        cls.names = [cls.lib.fixture_weapon(i).decode() for i in range(cls.lib.fixture_weapon_count())]
        cls.pin = hashlib.sha256(("\n".join(cls.names) + "\n").encode()).hexdigest()
        cls.layout = [cls.lib.fixture_layout(i) for i in range(9)]

    def setUp(self):
        self.files = tempfile.TemporaryDirectory(prefix="halo-arsenal-data-")
        self.addCleanup(self.files.cleanup)
        self.directory = Path(self.files.name)
        self.lib.fixture_reset(str(self.directory).encode())
        self.selection = Selection()

    def arena(self):
        size, flags, model, animations, globals_size, count, address, player_size, unit = self.layout
        data = bytearray(40 + (len(self.names) + 2) * 32)
        struct.pack_into("<4I", data, 0, 0x803A6000 + 40, 0, 0, len(self.names) + 2)
        def append(value):
            at = len(data);data.extend(value)
            data.extend(b"\0" * (-len(data) % 4));return 0x803A6000 + at
        for i, name in enumerate(self.names):
            definition = bytearray(size);definition[0] = 2
            struct.pack_into("<I", definition, model, 1);struct.pack_into("<I", definition, animations, 2)
            name_pointer=append(name.encode()+b"\0");definition_pointer=append(definition)
            struct.pack_into("<8I", data, 40+i*32, 0x77656170,0,0,i,name_pointer,definition_pointer,0,0)
        player_index = len(self.names)
        player_pointer = append(b"community\\weapon_pack\\player\\cyborg\0")
        struct.pack_into("<8I", data, 40+player_index*32, 0x62697064,0,0,player_index,player_pointer,0,0,0)
        information = bytearray(player_size);struct.pack_into("<I", information, unit, player_index)
        info_pointer=append(information)
        globals_definition = bytearray(globals_size)
        struct.pack_into("<I", globals_definition, count, 1);struct.pack_into("<I", globals_definition, address, info_pointer)
        globals_name=append(b"globals\\globals\0");globals_pointer=append(globals_definition)
        struct.pack_into("<8I", data, 40+(player_index+1)*32, 0x6d617467,0,0,player_index+1,globals_name,globals_pointer,0,0)
        return data

    def write_cache(self, name="prisoner", arena=None, compressed=True):
        arena = self.arena() if arena is None else arena
        physical = ctypes.create_string_buffer(32)
        self.assertTrue(self.lib.native_map_cache_physical_name(name.encode(), physical))
        target = self.directory / "arsenal/v1";target.mkdir(parents=True, exist_ok=True)
        base = header(name);base.extend(b"source geometry")
        (self.directory / f"{name}.map").write_bytes(base)
        cache_header = header(physical.value.decode(), length=2048+len(arena))
        struct.pack_into("<II", cache_header, 16, 2048, len(arena))
        cache = cache_header + (zlib.compress(arena) if compressed else arena)
        if compressed: cache.extend(b"\0" * (-len(cache) % 4096))
        cache_path=target / (physical.value.decode()+".map");cache_path.write_bytes(cache)
        manifest = {"schema_version":1,"generation":1,"logical_map":name,"physical_map":physical.value.decode(),
                    "cache_sha256":hashlib.sha256(cache).hexdigest(),"base_sha256":hashlib.sha256(base).hexdigest(),
                    "weapon_list_sha256":self.pin,"cache_file_bytes":len(cache),"cache_declared_bytes":2048+len(arena)}
        manifest_path=cache_path.with_suffix(".json");manifest_path.write_text(json.dumps(manifest))
        return cache_path,manifest_path,manifest

    def prepare(self, name="prisoner", weapon_set=15, fiesta=1):
        return bool(self.lib.fixture_prepare(name.encode(),weapon_set,fiesta,ctypes.byref(self.selection)))

    def test_pending_download_memoizes_base_and_requests_exact_offered_revision(self):
        original = header("prisoner") + b"source geometry"
        (self.directory / "prisoner.map").write_bytes(original)
        self.lib.fixture_download(2)
        expected = b"19" * 32
        self.assertFalse(self.lib.fixture_expected(b"prisoner", expected, ctypes.byref(self.selection)))
        self.assertEqual(self.lib.native_map_cache_download_status(), 2)
        reads = self.lib.fixture_reads()
        self.assertGreater(reads, 0)
        for _ in range(20):
            self.assertFalse(self.lib.fixture_expected(b"prisoner", expected, ctypes.byref(self.selection)))
        self.assertEqual(self.lib.fixture_reads(), reads)
        self.assertEqual(self.lib.fixture_requested(0), b"prisoner")
        self.assertEqual(self.lib.fixture_requested(1), hashlib.sha256(original).hexdigest().encode())
        self.assertEqual(self.lib.fixture_requested(2), expected)
        self.assertIn(b"Downloading", self.lib.fixture_error())
        self.assertFalse(self.selection.expanded)
        original += b"changed"
        (self.directory / "prisoner.map").write_bytes(original)
        self.assertFalse(self.prepare())
        self.assertGreater(self.lib.fixture_reads(), reads)
        self.assertEqual(self.lib.fixture_requested(1), hashlib.sha256(original).hexdigest().encode())
        self.assertEqual(self.lib.fixture_requested(2), b"")
        self.lib.fixture_download(1)
        self.assertFalse(self.prepare())
        self.assertEqual(self.lib.native_map_cache_download_status(), -1)

    def test_complete_managed_pair_freezes_path_and_exact_digest_overrides_latest_data_pair(self):
        cache, manifest_path, manifest = self.write_cache()
        with tempfile.TemporaryDirectory(prefix="halo-managed-arsenal-") as temporary:
            managed = Path(temporary) / "arsenal/v1";managed.mkdir(parents=True)
            cache.rename(managed / cache.name);manifest_path.rename(managed / manifest_path.name)
            self.lib.fixture_managed_root(temporary.encode())
            self.assertTrue(self.prepare(), self.lib.fixture_error())
            self.assertEqual(self.selection.physical_path, b"m:\\arsenal\\v1\\_fiesta_prisoner.map")
            managed_selection = bytes(self.selection)
            self.write_cache(arena=self.arena()+b"\0"*4)
            self.assertTrue(self.lib.fixture_expected(b"prisoner", manifest["cache_sha256"].encode(), ctypes.byref(self.selection)))
            self.assertEqual(bytes(self.selection), managed_selection)
            self.assertTrue(self.prepare())
            self.assertTrue(self.selection.physical_path.startswith(str(self.directory).encode()))
            self.assertNotEqual(bytes(self.selection.sha256).hex(), manifest["cache_sha256"])
            self.assertEqual(self.lib.fixture_requests(), 0)

    def test_pair_roots_cannot_be_mixed_and_pending_does_not_replace_selection(self):
        cache, manifest_path, _ = self.write_cache()
        self.assertTrue(self.prepare());self.lib.native_map_cache_select(ctypes.byref(self.selection))
        selected = bytes(self.selection)
        with tempfile.TemporaryDirectory(prefix="halo-managed-arsenal-") as temporary:
            managed = Path(temporary) / "arsenal/v1";managed.mkdir(parents=True)
            cache.rename(managed / cache.name)
            self.lib.fixture_managed_root(temporary.encode());self.lib.fixture_download(2)
            self.assertFalse(self.prepare());self.assertEqual(self.lib.native_map_cache_download_status(), 2)
            self.lib.native_map_cache_current.restype = ctypes.POINTER(Selection)
            self.assertEqual(bytes(self.lib.native_map_cache_current().contents), selected)
            manifest_path.rename(managed / manifest_path.name)
            self.assertTrue(self.prepare())
            self.assertEqual(self.selection.physical_path, b"m:\\arsenal\\v1\\_fiesta_prisoner.map")

    def test_cache_bank_transitions_certify_actual_selection_and_allow_normal_prefix_names(self):
        self.write_cache();self.assertTrue(self.prepare())
        self.lib.fixture_slot(0,b"prisoner",None)
        self.lib.fixture_slot(1,b"_fiesta_prisoner",ctypes.byref(self.selection))
        self.lib.fixture_slot(2,b"_fiesta_prisoner",None)
        self.lib.fixture_slot(3,b"ui",None)
        self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.fixture_find(b"prisoner"),1)
        self.assertEqual(self.lib.fixture_find(b"ui"),3)
        self.selection.sha256[0]^=1;self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.fixture_find(b"prisoner"),-1)
        self.assertTrue(self.prepare(fiesta=0));self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.fixture_find(b"prisoner"),0)
        self.assertTrue(self.prepare(name="_fiesta_prisoner",fiesta=0));self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.fixture_find(b"_fiesta_prisoner"),2)
        self.assertTrue(self.prepare());self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.fixture_find(b"prisoner"),1)

    def test_original_modes_require_no_hidden_content(self):
        for weapon_set, fiesta in ((0,0),(0,1),(11,0),(12,0),(13,0),(14,0),(15,0)):
            self.assertTrue(self.prepare(weapon_set=weapon_set,fiesta=fiesta))
            self.assertFalse(self.selection.expanded)
        self.assertFalse(self.prepare())
        self.assertIn(b"original map",self.lib.fixture_error())

    def test_full_cache_hash_tag_catalog_and_memo(self):
        self.write_cache()
        for weapon_set in (14,15):
            self.assertTrue(self.prepare(weapon_set=weapon_set),self.lib.fixture_error())
            self.assertEqual(self.selection.physical_name,b"_fiesta_prisoner")
        reads=self.lib.fixture_reads()
        self.assertTrue(self.prepare());self.assertEqual(self.lib.fixture_reads(),reads)
        self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.native_map_cache_resolve(b"levels\\prisoner\\prisoner"),b"_fiesta_prisoner")
        self.assertTrue(self.prepare(fiesta=0));self.lib.native_map_cache_select(ctypes.byref(self.selection))
        self.assertEqual(self.lib.native_map_cache_resolve(b"prisoner"),b"prisoner")
        self.assertTrue(self.prepare());self.assertEqual(self.lib.fixture_reads(),reads)

    def test_changed_base_and_cache_invalidate_verified_memo(self):
        cache,_,_=self.write_cache();self.assertTrue(self.prepare())
        original=self.directory/"prisoner.map";original.write_bytes(original.read_bytes()+b"edited")
        self.assertFalse(self.prepare());self.assertIn(b"differs from the original",self.lib.fixture_error())
        self.write_cache();self.assertTrue(self.prepare())
        cache.write_bytes(cache.read_bytes()+b"changed")
        self.assertFalse(self.prepare());self.assertIn(b"SHA-256",self.lib.fixture_error())

    def test_partial_arsenal_and_player_override_are_rejected_even_with_matching_sha(self):
        for mutation in ("missing", "must-ready", "excluded", "no-fp", "no-animation", "wrong-player"):
            arena=self.arena();entry=40
            definition=struct.unpack_from("<I",arena,entry+20)[0]-0x803A6000
            if mutation=="missing":struct.pack_into("<I",arena,entry,0)
            if mutation=="must-ready":struct.pack_into("<I",arena,definition+self.layout[1],8)
            if mutation=="excluded":struct.pack_into("<I",arena,definition+self.layout[1],16)
            if mutation=="no-fp":struct.pack_into("<I",arena,definition+self.layout[2],0xffffffff)
            if mutation=="no-animation":struct.pack_into("<I",arena,definition+self.layout[3],0xffffffff)
            if mutation=="wrong-player":struct.pack_into("<I",arena,40+len(self.names)*32+12,900)
            self.write_cache(arena=arena)
            with self.subTest(mutation=mutation):
                self.assertFalse(self.prepare());self.assertIn(b"tag data",self.lib.fixture_error())

    def test_strict_manifest_identity_pin_generation_and_bounds(self):
        for mutation in ("logical_map", "physical_map", "weapon_list_sha256", "generation", "schema_version", "unknown", "duplicate", "large"):
            _,path,manifest=self.write_cache()
            if mutation in ("logical_map","physical_map"):manifest[mutation]="other"
            elif mutation=="weapon_list_sha256":manifest[mutation]="0"*64
            elif mutation in ("generation","schema_version"):manifest[mutation]=2
            elif mutation=="unknown":manifest["surprise"]=1
            text=json.dumps(manifest)
            if mutation=="duplicate":text=text[:-1]+',"generation":1}'
            if mutation=="large":text+=' '*4096
            path.write_text(text)
            with self.subTest(mutation=mutation):self.assertFalse(self.prepare())

    def test_hashed_long_name_is_case_normalized_and_collision_separate(self):
        for name in ("prisoner","abcdefghijklmnopqrstuvwx","x"*31):
            out=ctypes.create_string_buffer(32);self.assertTrue(self.lib.native_map_cache_physical_name(name.upper().encode(),out))
            expected="_fiesta_"+name if len(name)<=23 else "_fiestah_"+hashlib.sha256(name.encode()).hexdigest()[:16]
            self.assertEqual(out.value,expected.encode())
        for name in ("", "x"*32, "../prisoner", "bad.name"):
            self.assertFalse(self.lib.native_map_cache_physical_name(name.encode(),ctypes.create_string_buffer(32)))
        name="abcdefghijklmnopqrstuvwx";self.write_cache(name=name)
        self.assertTrue(self.prepare(name=name),self.lib.fixture_error())

    def test_single_player_override_cannot_substitute_for_multiplayer_player(self):
        arena=self.arena()
        globals_entry=40+(len(self.names)+1)*32
        globals_offset=struct.unpack_from("<I",arena,globals_entry+20)[0]-0x803A6000
        mp_offset=struct.unpack_from("<I",arena,globals_offset+self.layout[6])[0]-0x803A6000
        struct.pack_into("<I",arena,mp_offset+self.layout[8],0)
        sp=bytearray(self.lib.fixture_layout(11))
        struct.pack_into("<I",sp,self.lib.fixture_layout(12),len(self.names))
        sp_pointer=0x803A6000+len(arena);arena.extend(sp)
        struct.pack_into("<I",arena,globals_offset+self.lib.fixture_layout(9),1)
        struct.pack_into("<I",arena,globals_offset+self.lib.fixture_layout(10),sp_pointer)
        self.write_cache(arena=arena)
        self.assertFalse(self.prepare())
        self.assertIn(b"tag data",self.lib.fixture_error())

    def test_uncompressed_full_cache_accepts(self):
        self.write_cache(compressed=False);self.assertTrue(self.prepare(),self.lib.fixture_error())

    def test_ce_namespace_cannot_alias_pending_xbox_arsenal(self):
        self.write_cache()
        self.assertTrue(self.prepare())
        self.lib.native_map_cache_select(ctypes.byref(self.selection))
        for name in (b"custom_maps\\prisoner", b"CUSTOM_MAPS\\prisoner"):
            with self.subTest(name=name):
                self.assertEqual(self.lib.native_map_cache_resolve(name), name)
                ce = Selection()
                self.assertTrue(self.lib.fixture_prepare(name, 0, 0, ctypes.byref(ce)))
                self.assertFalse(ce.expanded)
                self.assertEqual(ce.physical_path, name)
        self.assertEqual(self.lib.native_map_cache_resolve(b"prisoner"), b"_fiesta_prisoner")

    def test_long_ce_level_names_keep_distinct_identity(self):
        left, right = Selection(), Selection()
        names = [b"custom_maps\\" + b"x" * 40 + suffix for suffix in (b"a", b"b")]
        for name, selection in zip(names, (left, right)):
            self.assertTrue(self.lib.fixture_prepare(name, 0, 0, ctypes.byref(selection)))
            self.assertEqual(selection.physical_path, name)
            self.assertEqual(self.lib.native_map_cache_resolve(name), name)
        self.assertFalse(self.lib.native_map_cache_selection_equal(ctypes.byref(left), ctypes.byref(right)))
        self.assertEqual(self.lib.fixture_reads(), 0)

    def test_ce_map_rejects_xbox_arsenal_without_requesting_download(self):
        for set_id in (14, 15):
            with self.subTest(set_id=set_id):
                self.assertFalse(self.lib.fixture_prepare(b"custom_maps\\prisoner", set_id, 1, ctypes.byref(self.selection)))
                self.assertFalse(self.selection.expanded)
                self.assertEqual(self.selection.physical_path, b"")
                self.assertIn(b"own weapon tags", self.lib.fixture_error())
        self.assertFalse(self.lib.fixture_expected(b"custom_maps\\prisoner", b"11" * 32, ctypes.byref(self.selection)))
        self.assertEqual(self.lib.fixture_requests(), 0)
        self.assertEqual(self.lib.fixture_reads(), 0)


if __name__ == "__main__":
    unittest.main()
