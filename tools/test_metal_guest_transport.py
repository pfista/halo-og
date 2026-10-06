"""CPU byte-oracle checks for production native packet payload construction.

This compiles the production builder on the test host, omitting only its guest
pointer-width assertion. Host imports are unreachable stubs; these checks do
not claim ILP32 import or GPU behavior. The separate transport fixture exercises
those contracts through the actual rebased guest.
"""
import ctypes as C
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'port/linux/src/metal_guest_transport.c'
OK, INVALID, MEMORY = 0, -1, -4
STORAGE = 1024 * 1024


class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('clang is required for production packet CPU checks')
        source = SOURCE.read_text()
        assertion = '_Static_assert(sizeof(void *) == 4, "Native transport runs in the ILP32 guest");'
        if source.count(assertion) != 1:
            raise AssertionError('Production guest pointer-width assertion changed')
        source = source.replace(assertion, '')
        # Count actual writes made by the production initialization helper;
        # packet equality remains independently checked against the byte oracle.
        source = source.replace('unsigned char *p = pointer;',
                                'zero_written += size; unsigned char *p = pointer;')
        cls.directory = tempfile.TemporaryDirectory(prefix='metal-guest-payload-')
        folder = Path(cls.directory.name)
        harness = folder / 'payload.c'
        harness.write_text('''#define HALO_MACOS_NATIVE_METAL 1
#include <stdint.h>
#include <string.h>
static uint64_t zero_written;
''' + source + '''
static unsigned char storage[1048576] __attribute__((aligned(16)));
static struct halo_metal_guest_transport transport;
/* No host call is made by these packet-construction checks. */
int host_metal_initialize(uint32_t w,uint32_t f,uint32_t o,uint32_t n) {
    (void)w;(void)f;(void)o;(void)n;return HALO_METAL_INVALID;
}
int host_metal_submit(uint32_t p,uint32_t n,uint32_t o,uint32_t s) {
    (void)p;(void)n;(void)o;(void)s;return HALO_METAL_INVALID;
}
int host_metal_readback(uint32_t i,uint32_t g,uint32_t p,uint32_t d,uint32_t n,uint32_t o,uint32_t s) {
    (void)i;(void)g;(void)p;(void)d;(void)n;(void)o;(void)s;return HALO_METAL_INVALID;
}
void host_metal_shutdown(void) {}
int begin(uint32_t capacity) {
    memset(storage,0xa5,sizeof(storage));
    int status=halo_metal_guest_setup(&transport,storage,capacity);
    if(status)return status;
    transport.initialized=1;transport.reply.capabilities=ALL_CAPABILITIES;
    return halo_metal_guest_begin(&transport,1);
}
int restart(void) {return halo_metal_guest_begin(&transport,1);}
int command(const void *bytes,uint32_t size,uint32_t *offset) {
    return halo_metal_guest_append_command(&transport,bytes,size,offset);
}
int payload(const void *bytes,uint32_t size,uint32_t *offset) {
    return halo_metal_guest_append_payload(&transport,bytes,size,offset);
}
const void *packet(void) {return storage;}
uint32_t packet_size(void) {return transport.size;}
uint32_t command_count(void) {return transport.command_count;}
void reset_zero_counter(void) {zero_written=0;}
uint64_t zero_bytes_written(void) {return zero_written;}
''')
        library = folder / 'payload.dylib'
        subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-fPIC', '-I' + str(SOURCE.parent),
                        str(harness), '-o', str(library)], check=True, capture_output=True, text=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.begin.argtypes = [C.c_uint32]
        cls.lib.command.argtypes = cls.lib.payload.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32)]
        cls.lib.packet.restype = C.c_void_p
        cls.lib.zero_bytes_written.restype = C.c_uint64

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def packet(self):
        return C.string_at(self.lib.packet(), STORAGE)

    @staticmethod
    def metadata(size=9):
        # UPLOAD's complete host validation is outside this builder fixture.
        # The builder accepts its opcode and derives the current extent.
        return struct.pack('<II', 3, 0) + bytes((n * 13 + 7) % 256 for n in range(size - 8))

    def start(self, fixed=9, capacity=STORAGE):
        self.assertEqual(self.lib.begin(capacity), OK)
        self.expected = bytearray(b'\xa5' * STORAGE)
        self.expected[:24] = self.packet()[:24]
        self.position = 24
        self.command_offset = None
        self.add_command(self.metadata(fixed))

    def add_command(self, data):
        offset = C.c_uint32(0xffffffff)
        buffer = C.create_string_buffer(data, len(data))
        self.assertEqual(self.lib.command(buffer, len(data), C.byref(offset)), OK)
        begin = (self.position + 7) // 8 * 8
        end = (begin + len(data) + 7) // 8 * 8
        self.expected[self.position:end] = b'\0' * (end - self.position)
        self.expected[begin:begin + len(data)] = data
        struct.pack_into('<I', self.expected, begin + 4, end - begin)
        self.position = end
        self.command_offset = begin
        struct.pack_into('<II', self.expected, 8, end, self.lib.command_count())
        self.assertEqual(offset.value, begin)
        self.assertEqual(self.packet(), self.expected)

    def add_payload(self, data):
        old = self.position
        begin = (old + 15) // 16 * 16
        end = (begin + len(data) + 7) // 8 * 8
        buffer = C.create_string_buffer(data, len(data))
        offset = C.c_uint32(0xffffffff)
        self.lib.reset_zero_counter()
        self.assertEqual(self.lib.payload(buffer, len(data), C.byref(offset)), OK)
        self.expected[old:end] = b'\0' * (end - old)
        self.expected[begin:begin + len(data)] = data
        struct.pack_into('<I', self.expected, self.command_offset + 4, end - self.command_offset)
        struct.pack_into('<I', self.expected, 8, end)
        self.position = end
        self.assertEqual(offset.value, begin)
        self.assertEqual(self.lib.packet_size(), end)
        self.assertEqual(self.packet(), self.expected)
        self.assertEqual(self.lib.zero_bytes_written(), (begin - old) + (end - begin - len(data)))
        # A caller may immediately overwrite its original transient source.
        C.memset(buffer, 0, len(data))
        self.assertEqual(self.packet(), self.expected)

    def test_every_alignment_trailing_padding_and_payload_bytes(self):
        for fixed in (8, 9, 40, 72, 80, 416, 424):
            for size in range(1, 34):
                with self.subTest(fixed=fixed, payload=size):
                    self.start(fixed)
                    self.add_payload(bytes((n * 7 + 5) % 256 for n in range(size)))

    def test_multiple_payloads_commands_and_large_reused_storage(self):
        self.start()
        for size in (1, 8, 9, 16, 17, 65535, 256, 4, 3120, 608):
            self.add_payload(bytes((n * 17 + size) % 256 for n in range(size)))
        self.add_command(self.metadata(424))
        self.add_payload(bytes(range(256)))
        # Reusing the packet preserves the previous bytes beyond its new
        # header; the next command/payload must initialize only its own extent.
        self.expected = bytearray(self.packet())
        self.assertEqual(self.lib.restart(), OK)
        struct.pack_into('<II', self.expected, 8, 24, 0)
        self.position = 24
        self.assertEqual(self.packet(), self.expected)
        self.add_command(self.metadata(72))
        self.add_payload(b'\0' * 513)

    def test_random_full_packet_oracle(self):
        rng = random.Random(0x5041594c)
        for _ in range(20):
            self.start(rng.choice((8, 9, 40, 72, 80, 416, 424)))
            for _ in range(12):
                self.add_payload(rng.randbytes(rng.randrange(1, 4097)))

    def check_rejection(self, source, size, expected, offset=True):
        before = self.packet()
        old_size, old_count = self.lib.packet_size(), self.lib.command_count()
        output = C.c_uint32(0x11223344)
        self.lib.reset_zero_counter()
        self.assertEqual(self.lib.payload(source, size, C.byref(output) if offset else None), expected)
        self.assertEqual(self.packet(), before)
        self.assertEqual((self.lib.packet_size(), self.lib.command_count()), (old_size, old_count))
        self.assertEqual(output.value, 0x11223344)
        self.assertEqual(self.lib.zero_bytes_written(), 0)

    def test_rejected_null_zero_alias_and_missing_metadata_leave_bytes_unchanged(self):
        source = C.create_string_buffer(b'example')
        for pointer, size, output in ((None, 7, True), (source, 0, True), (source, 7, False)):
            self.start()
            self.check_rejection(pointer, size, INVALID, output)
        self.start()
        self.check_rejection(self.lib.packet() + 96, 7, INVALID)
        self.assertEqual(self.lib.begin(STORAGE), OK)
        self.check_rejection(source, 7, INVALID)
        self.start()
        before = self.packet()
        self.assertEqual(self.lib.payload(source, 7, C.cast(self.lib.packet() + 96, C.POINTER(C.c_uint32))), INVALID)
        self.assertEqual(self.packet(), before)

    def test_capacity_exact_end_alignment_padding_and_integer_overflow(self):
        source = C.create_string_buffer(b'x' * 17)
        self.start(9, 64)
        self.check_rejection(source, 17, MEMORY)
        self.start(9, 55)
        self.check_rejection(source, 1, MEMORY)  # data fits; trailing padding does not
        self.start(8, 40)
        self.add_payload(b'x')
        self.start(9, 56)
        self.add_payload(b'x')
        self.start(9, 40)
        self.check_rejection(source, 1, MEMORY)  # aligned payload begins past capacity
        self.start()
        self.check_rejection(source, 0xffffffff, MEMORY)


if __name__ == '__main__':
    unittest.main()
