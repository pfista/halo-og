"""Exercise production precache identity helpers with synthetic 2 KiB headers.

Only extracted production C and its serialized guest declaration compile into
a temporary library. These checks never load map assets or run the game.
"""
import ctypes
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from tools.test_cache_file_capacity import c_block, guest_widths


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "halo_sha256.h"
typedef unsigned char byte;
typedef int boolean;
typedef void *HANDLE;
typedef struct { uint32_t low, high; } FILETIME;
#define TRUE 1
#define FALSE 0
#define NUMBER_OF_CACHED_MAP_FILES 6
#define HALO_PORT_MULTIPLAYER_CACHE_SIZE (512u * 1024u * 1024u)
#define INVALID_FILE_SIZE UINT32_MAX
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define GENERIC_READ 1
#define GENERIC_WRITE 2
#define OPEN_EXISTING 3
#define CREATE_ALWAYS 4
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_PATH_NOT_FOUND 3
/* PRODUCTION DEFINITIONS */
_Static_assert(sizeof(struct cache_file_header) == 2048, "guest header size");
_Static_assert(offsetof(struct cache_file_header, name) == 32, "guest map name");
_Static_assert(offsetof(struct cache_file_header, build) == 64, "guest build");
_Static_assert(offsetof(struct cache_file_header, scenario_type) == 96, "guest map type");
_Static_assert(offsetof(struct cache_file_header, checksum) == 100, "guest checksum");
_Static_assert(offsetof(struct cache_file_header, reserved68) == 104, "guest padding");
_Static_assert(offsetof(struct cache_file_header, footer_signature) == 2044, "guest footer");
struct fixture_file {
    const unsigned char *bytes;
    uint32_t size, offset;
    int present, source;
};
static struct fixture_file fixture_source, fixture_certificate;
static unsigned char fixture_written[40];
static int fixture_faults, fixture_source_size_calls, fixture_time_calls;
static uint32_t fixture_last_error;
static struct cached_map_file fixture_slots[NUMBER_OF_CACHED_MAP_FILES];
static boolean native_cache_verified_slots[NUMBER_OF_CACHED_MAP_FILES];
static unsigned char native_cache_source_digests[NUMBER_OF_CACHED_MAP_FILES][32];
enum {
    SOURCE_OPEN_ERROR = 1, SOURCE_READ_ERROR = 2, SOURCE_EARLY_EOF = 4,
    SOURCE_APPEND = 8, SOURCE_TIME_CHANGE = 16, SOURCE_HIGH_SIZE = 32,
    SOURCE_OVERSIZE = 64, SOURCE_INITIAL_STAT_ERROR = 128,
    SOURCE_FINAL_STAT_ERROR = 256, SOURCE_TIME_ERROR = 512,
    SOURCE_PARTIAL_READ = 1024, CERTIFICATE_READ_ERROR = 2048,
    CERTIFICATE_SHORT_READ = 4096, CERTIFICATE_WRITE_ERROR = 8192,
    CERTIFICATE_SHORT_WRITE = 16384, CERTIFICATE_CLOSE_ERROR = 32768,
    SOURCE_FINAL_HIGH_SIZE = 65536, SOURCE_FINAL_SIZE_CHANGE = 131072
};
static HANDLE CreateFileA(const char *path, uint32_t access, uint32_t sharing,
        void *security, uint32_t disposition, uint32_t flags, HANDLE template_file) {
    struct fixture_file *file = strstr(path, ".source") ? &fixture_certificate : &fixture_source;
    (void)sharing; (void)security; (void)flags; (void)template_file;
    if (file->source && (fixture_faults & SOURCE_OPEN_ERROR))
        return INVALID_HANDLE_VALUE;
    if (disposition == CREATE_ALWAYS && access == GENERIC_WRITE) {
        file->bytes = fixture_written; file->size = 0; file->present = 1;
    }
    if (!file->present)
        return INVALID_HANDLE_VALUE;
    file->offset = 0;
    return file;
}
static uint32_t GetFileSize(HANDLE handle, uint32_t *high) {
    struct fixture_file *file = handle;
    if (file->source) {
        fixture_source_size_calls++;
        if ((fixture_source_size_calls == 1 && (fixture_faults & SOURCE_INITIAL_STAT_ERROR)) ||
                (fixture_source_size_calls > 1 && (fixture_faults & SOURCE_FINAL_STAT_ERROR)))
            return INVALID_FILE_SIZE; /* Deliberately leave high untouched. */
        if (high) *high = !!(fixture_faults & SOURCE_HIGH_SIZE) ||
            (fixture_source_size_calls > 1 && !!(fixture_faults & SOURCE_FINAL_HIGH_SIZE));
        if (fixture_faults & SOURCE_OVERSIZE) return HALO_PORT_MULTIPLAYER_CACHE_SIZE + 1;
        if (fixture_source_size_calls > 1 && (fixture_faults & SOURCE_FINAL_SIZE_CHANGE))
            return file->size + 1;
    }
    else if (high) *high = 0;
    return file->size;
}
static boolean GetFileTime(HANDLE handle, FILETIME *created, FILETIME *accessed, FILETIME *written) {
    (void)handle; (void)accessed;
    fixture_time_calls++;
    if (fixture_faults & SOURCE_TIME_ERROR) return FALSE;
    created->low = 123; created->high = 0;
    written->low = 456 + (fixture_time_calls > 1 && !!(fixture_faults & SOURCE_TIME_CHANGE));
    written->high = 0;
    return TRUE;
}
static boolean ReadFile(HANDLE handle, void *buffer, uint32_t count, uint32_t *read, void *overlapped) {
    struct fixture_file *file = handle;
    uint32_t available = file->size - file->offset;
    (void)overlapped;
    if ((file->source && (fixture_faults & SOURCE_READ_ERROR)) ||
            (!file->source && (fixture_faults & CERTIFICATE_READ_ERROR))) return FALSE;
    if (file->source && (fixture_faults & SOURCE_EARLY_EOF) && file->offset) available = 0;
    if (file->source && !available && (fixture_faults & SOURCE_APPEND)) {
        ((unsigned char *)buffer)[0] = 0xA5; *read = 1; return TRUE;
    }
    if (count > available) count = available;
    if (file->source && (fixture_faults & SOURCE_PARTIAL_READ) && count > 7) count = 7;
    if (!file->source && (fixture_faults & CERTIFICATE_SHORT_READ) && count) count--;
    if (count) memcpy(buffer, file->bytes + file->offset, count);
    file->offset += count; *read = count;
    return TRUE;
}
static boolean WriteFile(HANDLE handle, const void *buffer, uint32_t count, uint32_t *written, void *overlapped) {
    struct fixture_file *file = handle;
    (void)overlapped;
    if (fixture_faults & CERTIFICATE_WRITE_ERROR) return FALSE;
    if (fixture_faults & CERTIFICATE_SHORT_WRITE) count--;
    if (count > sizeof(fixture_written)) return FALSE;
    memcpy(fixture_written, buffer, count); file->size = count; *written = count;
    return TRUE;
}
static boolean CloseHandle(HANDLE handle) {
    struct fixture_file *file = handle;
    return file->source || !(fixture_faults & CERTIFICATE_CLOSE_ERROR);
}
static boolean DeleteFileA(const char *path) {
    (void)path;
    if (!fixture_certificate.present) { fixture_last_error = ERROR_FILE_NOT_FOUND; return FALSE; }
    fixture_certificate.present = 0; return TRUE;
}
static uint32_t GetLastError(void) { return fixture_last_error; }
static void cache_file_get_map_path(const char *name, char *path) { sprintf(path, "%s.map", name); }
static struct cached_map_file *cached_map_file_get(short index) { return &fixture_slots[index]; }
static boolean cache_file_read_header_from_dvd(const char *name, struct cache_file_header *header) {
    (void)name;
    if (!fixture_source.present || fixture_source.size < sizeof(*header)) return FALSE;
    memcpy(header, fixture_source.bytes, sizeof(*header)); return TRUE;
}
static void fixture_reset(const void *source, uint32_t size, const void *certificate,
        uint32_t certificate_size, int faults) {
    memset(fixture_slots, 0, sizeof(fixture_slots));
    memset(native_cache_verified_slots, 0, sizeof(native_cache_verified_slots));
    memset(native_cache_source_digests, 0, sizeof(native_cache_source_digests));
    fixture_source = (struct fixture_file){source, size, 0, source != NULL, 1};
    fixture_certificate = (struct fixture_file){certificate, certificate_size, 0, certificate != NULL, 0};
    fixture_faults = faults; fixture_source_size_calls = fixture_time_calls = 0;
}
/* PRODUCTION FUNCTIONS */
int fixture_headers_equal(const void *cached, const void *source) {
    return native_cache_headers_equal(cached, source);
}
int fixture_hash(const void *source, uint32_t size, int faults, void *digest) {
    fixture_reset(source, size, NULL, 0, faults);
    return native_cache_source_hash("arena", digest);
}
int fixture_certificate_read(const void *bytes, uint32_t size, int faults, void *digest) {
    fixture_reset(NULL, 0, bytes, size, faults);
    return native_cache_certificate_read(3, digest);
}
int fixture_certificate_write(const void *digest, int faults, void *bytes) {
    int valid;
    fixture_reset(NULL, 0, NULL, 0, faults);
    valid = native_cache_certificate_write(3, digest);
    memcpy(bytes, fixture_written, sizeof(fixture_written));
    return valid;
}
int fixture_certificate_present(void) { return fixture_certificate.present; }
int fixture_certificate_remove(void) { return native_cache_certificate_remove(3); }
int fixture_validate(const void *cached_header, const void *source, uint32_t size,
        const void *certificate, uint32_t certificate_size) {
    fixture_reset(source, size, certificate, certificate_size, 0);
    memcpy(&fixture_slots[3].header, cached_header, sizeof(fixture_slots[3].header));
    return native_cache_slot_validate(3);
}
int fixture_slot_verified(void) { return native_cache_verified_slots[3]; }
int fixture_slot_named(void) { return fixture_slots[3].header.name[0] != 0; }
void fixture_slot_digest(void *digest) { memcpy(digest, native_cache_source_digests[3], 32); }
'''


class CacheFileIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if compiler is None:
            raise unittest.SkipTest("A local C compiler is required for extracted-function checks")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-cache-identity-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        production = (ROOT / "source/cache/cache_files_windows.c").read_text()
        definitions = guest_widths(c_block(production, "struct cache_file_header\n{") + ";" +
                                   c_block(production, "struct cached_map_file\n{") + ";")
        signatures = ("static boolean native_cache_headers_equal(", "static void native_cache_certificate_path(",
                      "static boolean native_cache_certificate_read(", "static boolean native_cache_certificate_remove(",
                      "static boolean native_cache_certificate_write(", "static boolean native_cache_source_hash(",
                      "static boolean native_cache_slot_validate(")
        functions = "\n".join(guest_widths(c_block(production, signature, last=True)) for signature in signatures)
        fixture = HARNESS.replace("/* PRODUCTION DEFINITIONS */", definitions)
        fixture = fixture.replace("/* PRODUCTION FUNCTIONS */", functions)
        source = directory / "identity.c"
        source.write_text(fixture)
        library = directory / ("identity.dylib" if sys.platform == "darwin" else "identity.so")
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-fPIC",
                   "-dynamiclib" if sys.platform == "darwin" else "-shared",
                   "-iquote", str(ROOT / "port/linux/include"), str(source), "-o", str(library)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Extracted cache-identity fixture did not compile:\n" + result.stderr)
        cls.native = ctypes.CDLL(str(library))
        cls.native.fixture_headers_equal.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cls.native.fixture_headers_equal.restype = ctypes.c_int
        cls.native.fixture_hash.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p]
        cls.native.fixture_certificate_read.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p]
        cls.native.fixture_certificate_write.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        cls.native.fixture_validate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.c_void_p, ctypes.c_uint32]
        cls.native.fixture_slot_digest.argtypes = [ctypes.c_void_p]

    def header(self, checksum=0xFFFFFFFF):
        data = bytearray(2048)
        data[:4], data[-4:] = b"daeh", b"toof"
        struct.pack_into("<ii", data, 4, 5, 150 * 1024 * 1024)
        struct.pack_into("<ii", data, 16, 4096, 4 * 1024 * 1024)
        data[32:37] = b"arena"
        data[64:78] = b"01.10.12.2276\0"
        struct.pack_into("<hI", data, 96, 1, 0)
        struct.pack_into("<I", data, 100, checksum)
        return data

    def equal(self, cached, source):
        buffers = [None if value is None else ctypes.create_string_buffer(bytes(value))
                   for value in (cached, source)]
        return bool(self.native.fixture_headers_equal(*buffers))

    def test_equal_headers_accept_matching_real_or_unset_checksums(self):
        for checksum in (0, 0xFFFFFFFF, 0x35AE109C):
            with self.subTest(checksum=checksum):
                cached = self.header(checksum)
                self.assertTrue(self.equal(cached, bytearray(cached)))

    def test_same_checksum_cannot_hide_any_changed_material_field(self):
        fields = {"header_signature": 0, "version": 4, "file_length": 8,
                  "tag_data_offset": 16, "tag_data_size": 20, "name": 32,
                  "build": 64, "scenario_type": 96, "footer_signature": 2044}
        for checksum in (0, 0xFFFFFFFF, 0x35AE109C):
            cached = self.header(checksum)
            for field, offset in fields.items():
                with self.subTest(checksum=checksum, field=field):
                    changed = bytearray(cached)
                    changed[offset] ^= 1
                    self.assertFalse(self.equal(cached, changed))
                    self.assertFalse(self.equal(changed, cached))

    def test_checksum_and_all_name_and_build_bytes_participate(self):
        cached = self.header(0x35AE109C)
        for checksum in (0, 0xFFFFFFFF, 0x35AE109D):
            with self.subTest(checksum=checksum):
                self.assertFalse(self.equal(cached, self.header(checksum)))
        for field, offset in (("name", 32), ("build", 64)):
            for index in range(32):
                with self.subTest(field=field, index=index):
                    changed = bytearray(cached)
                    changed[offset + index] ^= 1
                    self.assertFalse(self.equal(cached, changed))

    def test_reserved_padding_is_ignored_even_when_every_reserved_byte_changes(self):
        cached = self.header()
        changed = bytearray(cached)
        ranges = ((12, 16), (24, 32), (98, 100), (104, 2044))
        for start, end in ranges:
            for index in range(start, end):
                changed[index] ^= 0xA5
        self.assertTrue(self.equal(cached, changed))
        changed[20] ^= 1
        self.assertFalse(self.equal(cached, changed))

    def test_absent_headers_do_not_match(self):
        header = self.header()
        for cached, source in ((None, header), (header, None), (None, None)):
            with self.subTest(cached_present=cached is not None, source_present=source is not None):
                self.assertFalse(self.equal(cached, source))

    def source_bytes(self):
        return bytes(self.header()) + bytes(range(256)) * 25 + b"exact source ending"

    def hash_source(self, source, faults=0):
        buffer = None if source is None else ctypes.create_string_buffer(source)
        digest = ctypes.create_string_buffer(b"\xA5" * 32, 32)
        valid = self.native.fixture_hash(buffer, 0 if source is None else len(source), faults, digest)
        return bool(valid), digest.raw

    def test_streamed_physical_source_hash_matches_python_with_positive_partial_reads(self):
        source = self.source_bytes()
        for faults in (0, 1024):
            with self.subTest(partial_reads=bool(faults)):
                valid, digest = self.hash_source(source, faults)
                self.assertTrue(valid)
                self.assertEqual(digest, hashlib.sha256(source).digest())
        # Declared decompressed length is much larger than this physical source.
        self.assertGreater(struct.unpack_from("<I", source, 8)[0], len(source))

    def test_source_hash_rejects_io_stat_size_time_and_eof_failures(self):
        source = self.source_bytes()
        faults = {"open_error": 1, "read_error": 2, "early_eof": 4, "append": 8,
                  "mtime_changed": 16, "high_size": 32, "oversized": 64,
                  "initial_stat_failure_leaves_high_untouched": 128,
                  "final_stat_failure_leaves_high_untouched": 256, "time_error": 512,
                  "final_high_size": 65536, "final_size_changed": 131072}
        for label, fault in faults.items():
            with self.subTest(fault=label):
                valid, digest = self.hash_source(source, fault)
                self.assertFalse(valid)
                self.assertEqual(digest, b"\xA5" * 32)
        for small in (None, b"", b"x" * 2047):
            with self.subTest(size=None if small is None else len(small)):
                self.assertFalse(self.hash_source(small)[0])

    def read_certificate(self, certificate, faults=0):
        buffer = None if certificate is None else ctypes.create_string_buffer(certificate)
        digest = ctypes.create_string_buffer(b"\xA5" * 32, 32)
        valid = self.native.fixture_certificate_read(
            buffer, 0 if certificate is None else len(certificate), faults, digest)
        return bool(valid), digest.raw

    def test_certificate_requires_exact_schema_size_and_complete_successful_read(self):
        digest = hashlib.sha256(self.source_bytes()).digest()
        certificate = b"HOGCS001" + digest
        self.assertEqual(self.read_certificate(certificate), (True, digest))
        for candidate in (None, b"", certificate[:-1], certificate + b"\0", b"HOGCS002" + digest):
            with self.subTest(size=None if candidate is None else len(candidate)):
                self.assertEqual(self.read_certificate(candidate), (False, b"\xA5" * 32))
        for fault in (2048, 4096):
            with self.subTest(fault=fault):
                self.assertEqual(self.read_certificate(certificate, fault), (False, b"\xA5" * 32))

    def test_certificate_write_is_exact_and_failed_or_short_writes_remove_partial_file(self):
        digest = hashlib.sha256(self.source_bytes()).digest()
        input_buffer = ctypes.create_string_buffer(digest, 32)
        certificate = ctypes.create_string_buffer(40)
        self.assertTrue(self.native.fixture_certificate_write(input_buffer, 0, certificate))
        self.assertEqual(certificate.raw, b"HOGCS001" + digest)
        self.assertTrue(self.native.fixture_certificate_present())
        for fault in (8192, 16384, 32768):
            with self.subTest(fault=fault):
                self.assertFalse(self.native.fixture_certificate_write(input_buffer, fault, certificate))
                self.assertFalse(self.native.fixture_certificate_present())
        self.assertTrue(self.native.fixture_certificate_remove())  # Missing file is already invalid.

    def validate_slot(self, cached, source, certificate):
        buffers = [ctypes.create_string_buffer(bytes(value)) if value is not None else None
                   for value in (cached, source, certificate)]
        return bool(self.native.fixture_validate(buffers[0], buffers[1], len(source),
                    buffers[2], 0 if certificate is None else len(certificate)))

    def slot_digest(self):
        digest = ctypes.create_string_buffer(32)
        self.native.fixture_slot_digest(digest)
        return digest.raw

    def test_slot_certificate_accepts_exact_source_and_clear_removes_in_memory_proof(self):
        source = self.source_bytes()
        digest = hashlib.sha256(source).digest()
        self.assertTrue(self.validate_slot(source[:2048], source, b"HOGCS001" + digest))
        self.assertTrue(self.native.fixture_slot_verified())
        self.assertTrue(self.native.fixture_slot_named())
        self.assertEqual(self.slot_digest(), digest)
        self.assertTrue(self.native.fixture_certificate_remove())
        self.assertFalse(self.native.fixture_slot_verified())
        self.assertEqual(self.slot_digest(), bytes(32))

    def test_same_header_and_restored_timestamp_cannot_hide_changed_source_bytes(self):
        original = self.source_bytes()
        certificate = b"HOGCS001" + hashlib.sha256(original).digest()
        changed = bytearray(original)
        changed[4096] ^= 1
        self.assertEqual(original[:2048], changed[:2048])
        # Every source metadata call returns the same creation/write time.
        self.assertFalse(self.validate_slot(original[:2048], changed, certificate))
        self.assertFalse(self.native.fixture_slot_verified())
        self.assertFalse(self.native.fixture_slot_named())
        self.assertEqual(self.slot_digest(), bytes(32))

    def test_invalid_certificate_or_changed_header_invalidates_slot(self):
        source = self.source_bytes()
        certificate = b"HOGCS001" + hashlib.sha256(source).digest()
        for invalid in (None, certificate[:-1], b"HOGCS002" + certificate[8:],
                        certificate[:-1] + bytes([certificate[-1] ^ 1])):
            with self.subTest(certificate_size=None if invalid is None else len(invalid)):
                self.assertFalse(self.validate_slot(source[:2048], source, invalid))
                self.assertFalse(self.native.fixture_slot_named())
                self.assertEqual(self.slot_digest(), bytes(32))
        cached = bytearray(source[:2048])
        cached[16] ^= 1
        self.assertFalse(self.validate_slot(cached, source, certificate))
        self.assertFalse(self.native.fixture_slot_named())


if __name__ == "__main__":
    unittest.main()
