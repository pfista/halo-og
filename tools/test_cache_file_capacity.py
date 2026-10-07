"""Exercise production cache admission and slot choice with 2 KiB headers.

Only extracted C functions and their guest declarations compile into a tiny
temporary library. Guest longs/pointers retain their serialized 32-bit widths;
these checks do not load map assets, build the app, or run a game.
"""
import ctypes
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


def c_block(source, signature, last=False):
    start = source.rindex(signature) if last else source.index(signature)
    opening = source.index("{", start)
    depth = 0
    tokens = r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]'
    for match in re.finditer(tokens, source[opening:], re.S):
        if match[0] == "{":
            depth += 1
        elif match[0] == "}":
            depth -= 1
            if depth == 0:
                return source[start:opening + match.end()]
    raise ValueError("Unclosed production declaration: " + signature)


def guest_widths(source):
    source = re.sub(r"\bunsigned long\b", "uint32_t", source)
    return re.sub(r"\blong\b", "int32_t", source)


PREFIX = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "halo_port_capacity.h"
typedef unsigned char byte;
typedef int boolean;
typedef void *HANDLE;
typedef struct { uint32_t low, high; } FILETIME;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define csstrlen strlen
#define csprintf sprintf
#define match_assert(file,line,condition) assert(condition)
#define match_vassert(file,line,condition,message) do { (void)(message); assert(condition); } while (0)
static char temporary[512];
enum { _scenario_type_solo = 0, _scenario_type_multiplayer = 1, _scenario_type_main_menu = 2 };
/* PRODUCTION DEFINITIONS */
_Static_assert(sizeof(struct cache_file_header) == 2048, "guest header must be 2 KiB");
_Static_assert(sizeof(struct cache_file_tag_header) == 36, "guest tag header must be 36 bytes");
_Static_assert(offsetof(struct cache_file_header, name) == 32, "guest name offset");
_Static_assert(offsetof(struct cache_file_header, reserved60) == 96, "guest scenario offset");
_Static_assert(offsetof(struct cache_file_header, footer_signature) == 2044, "guest footer offset");
static struct { short open_map_file_index; } cache_file_globals;
static struct cached_map_file map_slots[NUMBER_OF_CACHED_MAP_FILES];
static struct cached_map_file *cached_map_file_get(short index) {
    assert(index >= 0 && index < NUMBER_OF_CACHED_MAP_FILES);
    return &map_slots[index];
}
static int CompareFileTime(const FILETIME *a, const FILETIME *b) {
    uint64_t x = ((uint64_t)a->high << 32) | a->low;
    uint64_t y = ((uint64_t)b->high << 32) | b->low;
    return (x > y) - (x < y);
}
/* PRODUCTION FUNCTIONS */
int fixture_verify(const void *header) {
    return cache_file_header_verify((struct cache_file_header *)header, "synthetic", FALSE);
}
int32_t fixture_tag_header_size(void) { return (int32_t)sizeof(struct cache_file_tag_header); }
int32_t fixture_slot_capacity(short index) { return cached_map_file_get_size(index); }
int fixture_slot(int32_t file_length, short scenario_type, short open_index) {
    cache_file_globals.open_map_file_index = open_index;
    for(short i = 0; i < NUMBER_OF_CACHED_MAP_FILES; i++) {
        map_slots[i].last_modification_date.low = (uint32_t)i + 1;
        map_slots[i].last_modification_date.high = 0;
    }
    return cached_map_files_find_free_map(file_length, scenario_type);
}
'''


class CacheFileCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("A local C compiler is required for extracted-function checks")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-cache-capacity-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = (ROOT / "source/cache/cache_files.c").read_text()
        windows = (ROOT / "source/cache/cache_files_windows.c").read_text()
        tag_header = c_block(source, "struct cache_file_tag_header\n{")
        tag_header = re.sub(r"struct cache_file_tag_instance\s*\*|void\s*\*", "uint32_t ", tag_header)
        definitions = [tag_header + ";", c_block(source, "struct cache_file_header\n{") + ";",
                       c_block(windows, "enum\n{") + ";", c_block(windows, "struct cached_map_file\n{") + ";"]
        signatures = [line for line in source.splitlines()
                      if line.startswith("#define CACHE_FILE_HEADER_SIGNATURE ") or line.startswith("#define CACHE_FILE_FOOTER_SIGNATURE ")]
        if len(signatures) != 2:
            raise ValueError("Expected production header/footer signature constants")
        definitions = "\n".join(signatures + [guest_widths(value) for value in definitions])
        functions = [c_block(source, "boolean cache_file_header_verify("),
                     c_block(windows, "static long cached_map_file_get_size(", last=True),
                     c_block(windows, "static short cached_map_files_find_free_map(", last=True)]
        fixture = PREFIX.replace("/* PRODUCTION DEFINITIONS */", definitions)
        fixture = fixture.replace("/* PRODUCTION FUNCTIONS */", "\n".join(guest_widths(value) for value in functions))
        path = directory / "capacity.c"; path.write_text(fixture)
        library = directory / ("capacity.dylib" if sys.platform == "darwin" else "capacity.so")
        command = [compiler, "-std=c11", "-Wno-multichar", "-O1", "-fPIC",
                   "-dynamiclib" if sys.platform == "darwin" else "-shared",
                   "-iquote", str(ROOT / "port/linux/include"), str(path), "-o", str(library)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Extracted cache-capacity fixture did not compile:\n" + result.stderr)
        cls.native = ctypes.CDLL(str(library))
        cls.native.fixture_verify.argtypes = [ctypes.c_void_p]
        cls.native.fixture_verify.restype = ctypes.c_int
        cls.native.fixture_tag_header_size.restype = ctypes.c_int32
        cls.native.fixture_slot_capacity.argtypes = [ctypes.c_int16]
        cls.native.fixture_slot_capacity.restype = ctypes.c_int32
        cls.native.fixture_slot.argtypes = [ctypes.c_int32, ctypes.c_int16, ctypes.c_int16]
        cls.native.fixture_slot.restype = ctypes.c_int

    def header(self, length=150 * MIB, kind=1, tag_offset=2048, tag_size=36,
               name=b"synthetic", version=5):
        data = bytearray(2048)
        data[:4], data[-4:] = b"daeh", b"toof"
        struct.pack_into("<iii", data, 4, version, length, 0)
        struct.pack_into("<ii", data, 16, tag_offset, tag_size)
        data[32:32 + len(name)] = name
        struct.pack_into("<h", data, 96, kind)
        return data

    def accepted(self, data):
        self.assertEqual(len(data), 2048)
        buffer = ctypes.create_string_buffer(bytes(data))
        return bool(self.native.fixture_verify(buffer))

    def test_multiplayer_150_mib_and_exact_512_mib_are_accepted(self):
        self.assertEqual(self.native.fixture_tag_header_size(), 36)
        for length in (150 * MIB, 512 * MIB):
            with self.subTest(length=length):
                self.assertTrue(self.accepted(self.header(length=length)))
                self.assertTrue(self.accepted(self.header(length=length, tag_offset=length - 36)))
        self.assertFalse(self.accepted(self.header(length=512 * MIB + 1)))

    def test_negative_small_and_overflowing_header_ranges_are_rejected(self):
        maximum = 2 ** 31 - 1
        cases = [{"length": -1}, {"length": 0}, {"length": 2047}, {"length": maximum},
                 {"tag_offset": -1}, {"tag_offset": 2047}, {"tag_offset": 150 * MIB + 1},
                 {"tag_offset": maximum}, {"tag_size": -1}, {"tag_size": 0}, {"tag_size": 35},
                 {"tag_size": 22 * MIB + 1}, {"tag_size": maximum},
                 {"tag_offset": 150 * MIB - 35, "tag_size": 36},
                 {"tag_offset": maximum - 16, "tag_size": maximum}]
        for values in cases:
            with self.subTest(values=values):
                self.assertFalse(self.accepted(self.header(**values)))
        self.assertTrue(self.accepted(self.header(tag_size=22 * MIB)))

    def test_bounded_name_version_signatures_and_scenario_type(self):
        self.assertTrue(self.accepted(self.header(name=b"x" * 31)))
        self.assertFalse(self.accepted(self.header(name=b"x" * 32)))
        self.assertFalse(self.accepted(self.header(version=7)))
        for offset in (0, 2044):
            data = self.header(); data[offset] ^= 1
            with self.subTest(signature_offset=offset):
                self.assertFalse(self.accepted(data))
        for kind in (-1, 3, 32767):
            with self.subTest(kind=kind):
                self.assertFalse(self.accepted(self.header(kind=kind)))

    def test_campaign_and_ui_keep_legacy_278_mib_header_ceiling(self):
        for kind in (0, 2):
            with self.subTest(kind=kind):
                self.assertTrue(self.accepted(self.header(kind=kind, length=0x11600000)))
                self.assertFalse(self.accepted(self.header(kind=kind, length=0x11600000 + 1)))
                self.assertFalse(self.accepted(self.header(kind=kind, length=512 * MIB)))

    def test_exact_multiplayer_slot_fit_is_selected_and_open_slot_is_skipped(self):
        self.assertEqual(self.native.fixture_slot_capacity(3), 512 * MIB)
        self.assertEqual(self.native.fixture_slot(512 * MIB, 1, 0), 3)
        self.assertEqual(self.native.fixture_slot(512 * MIB, 1, 3), 4)
        self.assertEqual(self.native.fixture_slot(512 * MIB + 1, 1, 0), -1)
        self.assertEqual(self.native.fixture_slot(150 * MIB, 1, 0), 3)

    def test_campaign_and_ui_slot_capacities_remain_unchanged(self):
        self.assertEqual(self.native.fixture_slot_capacity(0), 0x11600000)
        self.assertEqual(self.native.fixture_slot_capacity(2), 0x02300000)
        self.assertEqual(self.native.fixture_slot(0x11600000, 0, 5), 0)
        self.assertEqual(self.native.fixture_slot(0x11600000 + 1, 0, 5), -1)
        self.assertEqual(self.native.fixture_slot(0x02300000, 2, 0), 2)
        self.assertEqual(self.native.fixture_slot(0x02300000 + 1, 2, 0), -1)


if __name__ == "__main__":
    unittest.main()
