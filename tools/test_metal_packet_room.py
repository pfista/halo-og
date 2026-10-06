#!/usr/bin/env python3
"""Test complete-command room planning, including the real ILP32 builder.

The optional ILP32 mode uses mocked host imports and performs CPU work only.
It exercises production append operations; it does not submit a GPU packet.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'port/linux/src/metal_packet_room.c'
HEADER = SOURCE.with_suffix('.h')
TRANSPORT = ROOT/'port/linux/src/metal_guest_transport.c'
WIRE = ROOT/'build/metal-poc/host-frame-black-border-current'
MAX = 64*1024*1024
OK, INVALID, MEMORY = 0, -1, -4


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def oracle(cursor, capacity, fixed, sizes):
    """Integer division oracle independent of the C alignment implementation."""
    if (not 32 <= capacity <= MAX or not 24 <= cursor <= capacity or cursor % 8 or
            fixed < 8 or len(sizes) > 8 or any(not n for n in sizes)):
        return INVALID, None
    position = ((cursor+7)//8*8 + fixed+7)//8*8
    for size in sizes:
        position = ((position+15)//16*16 + size+7)//8*8
    return (OK, position) if position <= capacity else (MEMORY, None)


def original_commands():
    """Read retained executed packet extents; verify every source packet hash."""
    fixture_path = WIRE/'fixture.json'
    if not fixture_path.exists():
        raise unittest.SkipTest('retained original full-frame wire fixture required')
    fixture = json.loads(fixture_path.read_bytes())
    descriptors = []
    def visit(value):
        if isinstance(value, dict):
            if 'file' in value and 'sha256' in value and str(value['file']).startswith('packet-'):
                descriptors.append(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(fixture)
    hashes, rows = {}, []
    for descriptor in descriptors:
        path = WIRE/descriptor['file']
        if str(path) in hashes:
            continue
        data = path.read_bytes()
        assert sha(path) == descriptor['sha256'], 'Historical packet changed: '+str(path)
        hashes[str(path)] = sha(path)
        if not data:
            continue
        position = 24
        for _ in range(struct.unpack_from('<I',data,12)[0]):
            op, extent = struct.unpack_from('<II',data,position)
            if op == 9:
                vertices, indices = struct.unpack_from('<II',data,position+376)
                fixed, sizes = 416, [vertices*256,indices*4,3120,608]
            elif op == 11:
                fixed, sizes = 72, [struct.unpack_from('<I',data,position+60)[0]]
            elif op == 7:
                fixed, sizes = 40, list(struct.unpack_from('<II',data,position+24)[0:1])
                sizes.append(struct.unpack_from('<I',data,position+32)[0])
            else:
                fixed, sizes = extent, []
            status, end = oracle(position,MAX,fixed,sizes)
            assert status == OK and end == position+extent, (op,position,extent,fixed,sizes,end)
            rows.append(dict(opcode=op,cursor=position,fixed=fixed,payload_sizes=sizes,end=end))
            position += extent
        assert position == len(data)
    assert sum(row['opcode']==9 for row in rows)==126
    return rows, dict(fixture_sha256=sha(fixture_path),packet_sha256=hashes,
                     draws=126,commands=len(rows))


class RoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='halo-metal-packet-room-')
        cls.directory = Path(cls.temp.name)
        library = cls.directory/'room.dylib'
        subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                        '-DHALO_MACOS_NATIVE_METAL=1',SOURCE,'-o',library],check=True,capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.halo_metal_packet_room.argtypes = [C.c_uint32,C.c_uint32,C.c_uint32,
            C.POINTER(C.c_uint32),C.c_uint32,C.POINTER(C.c_uint32)]
        cls.lib.halo_metal_packet_room.restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, cursor, capacity, fixed, sizes):
        expected, end = oracle(cursor,capacity,fixed,sizes)
        values = (C.c_uint32*len(sizes))(*sizes) if sizes else None
        actual_end = C.c_uint32(0xa7a7a7a7)
        actual = self.lib.halo_metal_packet_room(cursor,capacity,fixed,values,len(sizes),C.byref(actual_end))
        self.assertEqual(actual,expected,(cursor,capacity,fixed,sizes))
        self.assertEqual(actual_end.value,end if not actual else 0xa7a7a7a7)

    def test_exact_boundary_padding_and_all_eight_payloads(self):
        for fixed in (8,9,40,72,80,416,424):
            for sizes in ([],[1],[8],[9],[16],[17],[256,4,3120,608],[1,2,3,4,5,6,7,8]):
                for cursor in (24,32,40,48):
                    _, end = oracle(cursor,MAX,fixed,sizes)
                    for capacity in (max(32,end-1),end,end+1,MAX):
                        self.check(cursor,capacity,fixed,sizes)
        self.check(MAX-8,MAX,8,[])
        self.check(MAX-16,MAX,8,[1])  # payload alignment cannot fit a byte
        self.check(24,MAX,MAX-24,[])
        self.check(24,MAX,MAX-24,[1])

    def test_malformed_overflow_and_output_unchanged(self):
        for args in [(0,MAX,8,[]),(23,MAX,8,[]),(25,MAX,8,[]),(40,32,8,[]),
            (24,31,8,[]),(24,MAX+1,8,[]),(24,MAX,7,[]),(24,MAX,8,[0]),
            (24,MAX,8,[1]*9),(24,MAX,0xffffffff,[]),(24,MAX,8,[0xffffffff]*8)]:
            self.check(*args)
        output = C.c_uint32(77)
        self.assertEqual(self.lib.halo_metal_packet_room(24,MAX,8,None,1,C.byref(output)),INVALID)
        self.assertEqual(output.value,77)
        self.assertEqual(self.lib.halo_metal_packet_room(24,MAX,8,None,0,None),INVALID)

    def test_random_sizes_and_cursor_alignment(self):
        randomizer = random.Random(0x4d544c)
        for _ in range(5000):
            capacity = randomizer.choice([32,4096,4*1024*1024,MAX])
            cursor = randomizer.randrange(24//8,capacity//8+1)*8
            fixed = randomizer.choice([8,9,40,72,80,416,424,0xfffffff8])
            sizes = [randomizer.choice([1,8,15,16,17,256,3120,608,65536,0xffffffff])
                     for _ in range(randomizer.randrange(9))]
            self.check(cursor,capacity,fixed,sizes)

    def test_all_original_executed_command_extents(self):
        rows, _ = original_commands()
        for row in rows:
            self.check(row['cursor'],MAX,row['fixed'],row['payload_sizes'])

    def test_soft_flush_complete_command_and_oversize_rejection(self):
        # Simulate the caller's policy without changing the production builder.
        cursor, target, flushes = 24, 4*1024*1024, 0
        for fixed, sizes in [(416,[3*1024*1024,12,3120,608]),(424,[2*1024*1024,12,3120,608]),
                             (72,[5*1024*1024]),(416,[256,12,3120,608])]:
            status, empty_end = oracle(24,MAX,fixed,sizes)
            self.assertEqual(status,OK)
            status, current_end = oracle(cursor,MAX,fixed,sizes)
            if cursor>24 and (status or current_end>target):
                flushes += 1
                cursor = 24
            status, cursor = oracle(cursor,MAX,fixed,sizes)
            self.assertEqual(status,OK)
            if cursor>target:
                flushes += 1
                cursor = 24
        self.assertEqual(flushes,3)
        before = (cursor,flushes)
        self.assertEqual(oracle(24,MAX,416,[MAX])[0],MEMORY)
        self.assertEqual((cursor,flushes),before)  # rejected BEFORE any flush


def prepare_ilp32(output):
    """Build the actual guest ABI, production builder and mocked imports."""
    sys.path.insert(0,str(ROOT))
    from tools.android_build import GUEST_ABI_FLAGS
    output = output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    if (output/'prepared.json').exists():
        raise ValueError('Preserve previous proof; choose a new output folder')
    llvm = Path('/opt/homebrew/opt/llvm@22/bin')
    linker = Path('/opt/homebrew/opt/lld@22/bin/ld.lld')  # do not resolve basename-dispatched symlink
    plugin = ROOT.parent/'pfista-halo-macos/build/macos/guest_rebase.dylib'
    historical = json.loads((ROOT/'build/metal-poc/native-draw-state-ilp32-final/prepared.json').read_text())
    executor = Path(historical['execution_command'][0])
    assert sha(executor)==historical['executor_sha256'], 'Historical CPU executor changed'
    rows, capture = original_commands()
    files = [SOURCE,HEADER,TRANSPORT,TRANSPORT.with_suffix('.h'),Path(__file__).resolve(),
        ROOT/'port/macos/include/halo_metal_abi.h',ROOT/'tools/android_build.py',
        ROOT/'tools/android_asm_convert.py',ROOT/'tools/android_imports.py',ROOT/'port/macos/metal_imports.list']
    bindings = {str(path):sha(path) for path in files}
    snapshot = output/'source-snapshot'
    for path in files:
        copied = snapshot/path.relative_to(ROOT)
        copied.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,copied)
    cases = [(row['cursor'],MAX,row['fixed'],row['payload_sizes']) for row in rows]
    rng = random.Random(0x494c5033)
    for _ in range(2048):
        capacity = rng.choice([32,128,4096,65536])
        cursor = rng.randrange(3,capacity//8+1)*8
        cases.append((cursor,capacity,rng.choice([8,9,40,72,80,416,424]),
            [rng.choice([1,8,9,16,17,128,256,608,3120,65536]) for _ in range(rng.randrange(9))]))
    for sizes in ([1],[8],[9],[256,12,3120,608],[1,2,3,4,5,6,7,8]):
        _,end=oracle(24,MAX,424,sizes)
        cases.extend((24,cap,424,sizes) for cap in (end-1,end,end+1))
    cases.extend([(MAX-8,MAX,8,[]),(MAX-16,MAX,8,[1]),(24,MAX,0xffffffff,[]),
                  (24,MAX,8,[0xffffffff]*8),(24,MAX,MAX-24,[])])
    # The last enormous successful metadata case would require a source record
    # of the same size; compare it in native oracle tests, not bounded guest data.
    cases.pop()
    blob = bytearray()
    for cursor,capacity,fixed,sizes in cases:
        status,end=oracle(cursor,capacity,fixed,sizes)
        blob += struct.pack('<12IiI',cursor,capacity,fixed,len(sizes),*(sizes+[0]*(8-len(sizes))),status,
                            end if end is not None else 0xa7a7a7a7)
    (output/'cases.bin').write_bytes(blob)
    (output/'cases.s').write_text('.section .rodata\n.balign 16\n.global room_cases\nroom_cases:\n.incbin "'+str(output/'cases.bin')+'"\n')
    guest = output/'guest.c'
    guest.write_text('''#define HALO_MACOS_NATIVE_METAL 1
#define host_metal_initialize room_mock_initialize
#define host_metal_submit room_mock_submit
#define host_metal_readback room_mock_readback
#define host_metal_shutdown room_mock_shutdown
#include "'''+str(snapshot/'port/linux/src/metal_guest_transport.c')+'''"
#include "'''+str(snapshot/'port/linux/src/metal_packet_room.c')+'''"
_Static_assert(sizeof(void*)==4 && sizeof(unsigned long)==4,"real ILP32 guest");
struct room_case { uint32_t cursor,capacity,fixed,count,sizes[8];int32_t status;uint32_t end; };
_Static_assert(sizeof(struct room_case)==56,"case wire layout");
extern const struct room_case room_cases['''+str(len(cases))+'''];
static unsigned char storage[HALO_METAL_MAX_PACKET] __attribute__((aligned(16)));
static unsigned char payload[2*1024*1024];
static unsigned char command[424];
static struct halo_metal_guest_transport t;
static uint32_t host_calls;
int room_mock_initialize(uint32_t window,uint32_t flags,uint32_t pointer,uint32_t bytes) {
    (void)window;(void)flags;(void)bytes;host_calls++;
    struct halo_metal_reply reply={HALO_METAL_ABI_VERSION,0,UINT32_MAX,
        ALL_CAPABILITIES & ~(HALO_METAL_CAP_PRESENT_EXACT|HALO_METAL_CAP_PRESENT_SCALED),0,0,0,0,0,0};
    copy_bytes((void*)(uintptr_t)pointer,&reply,sizeof(reply));return 0;
}
int room_mock_submit(uint32_t p,uint32_t n,uint32_t r,uint32_t b) {
    (void)p;(void)n;(void)r;(void)b;host_calls++;return HALO_METAL_INVALID;
}
int room_mock_readback(uint32_t i,uint32_t g,uint32_t p,uint32_t d,uint32_t n,uint32_t r,uint32_t b) {
    (void)i;(void)g;(void)p;(void)d;(void)n;(void)r;(void)b;host_calls++;return HALO_METAL_INVALID;
}
void room_mock_shutdown(void) {host_calls++;}
static uint32_t payload_byte_guards(void) {
    const uint32_t fixed[]={8,9,40,72,80,416,424}, sizes[]={1,7,8,9,15,16,17,65535};
    for(uint32_t f=0;f<sizeof(fixed)/sizeof(*fixed);f++)for(uint32_t s=0;s<sizeof(sizes)/sizeof(*sizes);s++) {
        for(uint32_t i=0;i<131072;i++)storage[i]=0xa5;
        if(halo_metal_guest_setup(&t,storage,131072) || halo_metal_guest_initialize(&t,0,HALO_METAL_OFFSCREEN,0) ||
           halo_metal_guest_begin(&t,1))return 60000+f*8+s;
        uint32_t command_offset=UINT32_MAX,offset=UINT32_MAX;
        if(halo_metal_guest_append_command(&t,command,fixed[f],&command_offset))return 61000+f*8+s;
        uint32_t previous=t.size,first=((previous+15)/16)*16,end=((first+sizes[s]+7)/8)*8;
        uint32_t calls=host_calls;
        if(halo_metal_guest_append_payload(&t,payload,sizes[s],&offset) || offset!=first || t.size!=end ||
           host_calls!=calls)return 62000+f*8+s;
        for(uint32_t i=previous;i<end;i++) {
            unsigned char expected=i>=first && i<first+sizes[s] ? payload[i-first]:0;
            if(storage[i]!=expected)return 63000+f*8+s;
        }
        if(storage[end]!=0xa5 || ((struct halo_metal_command*)(void*)(storage+command_offset))->byte_size!=end-command_offset ||
           ((struct halo_metal_packet*)(void*)storage)->byte_size!=end)return 64000+f*8+s;
    }
    return 0;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused;
    for(uint32_t i=0;i<sizeof(payload);i++)payload[i]=(unsigned char)(i*13+7);
    ((struct halo_metal_command*)(void*)command)->opcode=HALO_METAL_CLEAR;
    for(uint32_t i=0;i<'''+str(len(cases))+''';i++) {
        const struct room_case *c=&room_cases[i];uint32_t end=0xa7a7a7a7;
        int status=halo_metal_packet_room(c->cursor,c->capacity,c->fixed,c->sizes,c->count,&end);
        if(status!=c->status || end!=c->end)return 10000+i;
        if(halo_metal_guest_setup(&t,storage,c->capacity) || halo_metal_guest_initialize(&t,0,HALO_METAL_OFFSCREEN,0) ||
           halo_metal_guest_begin(&t,1))return 20000+i;
        /* A valid aligned occupied cursor is enough for this bounds-only
         * comparison. No fictitious preceding commands are submitted. */
        t.size=c->cursor;((struct halo_metal_packet*)(void*)storage)->byte_size=c->cursor;
        uint32_t offset=0;status=halo_metal_guest_append_command(&t,command,c->fixed,&offset);
        for(uint32_t j=0;!status && j<c->count;j++) {
            status=halo_metal_guest_append_payload(&t,payload,c->sizes[j],&offset);
            if(!status && (storage[offset]!=payload[0] || storage[offset+c->sizes[j]-1]!=payload[c->sizes[j]-1]))return 30000+i;
        }
        if(status!=c->status || (!status && t.size!=c->end))return 40000+i;
        if(host_calls!=i+1)return 50000+i; /* initialize only; never submit/readback */
    }
    return payload_byte_guards();
}
''')
    def run(*args):
        result=subprocess.run([str(x) for x in args],cwd=ROOT,capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
    resource=Path(subprocess.check_output([llvm/'clang','-print-resource-dir'],text=True).strip())
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-std=c11','-Wall','-Wextra','-Werror','-emit-llvm','-S',guest,'-o',output/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',output/'guest.ll','-o',output/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',output/'guest.rebased.ll','-o',output/'guest.darwin.s')
    run(sys.executable,ROOT/'tools/android_asm_convert.py',output/'guest.darwin.s',output/'guest.s')
    run(sys.executable,ROOT/'tools/android_imports.py','--host-table',output/'host_import_table.c',output/'imports.s',ROOT/'port/macos/metal_imports.list')
    for name in ('guest','cases','imports'):
        run(llvm/'clang','--target=aarch64-linux-android','-c',output/(name+'.s'),'-o',output/(name+'.o'))
    (output/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',output/'guest.ld',output/'guest.o',output/'cases.o',output/'imports.o','-o',output/'guest.elf')
    symbols={}
    for line in subprocess.check_output([llvm/'llvm-nm','--defined-only',output/'guest.elf'],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:
            symbols[fields[2]]=int(fields[0],16)
    copied=output/'host_ilp32_probe';shutil.copy2(executor,copied)
    command=[str(copied),str(output/'guest.elf'),*[hex(symbols[n]) for n in
        ('__host_import_table','__host_import_names','__host_import_count')],'0x5000000']
    assert bindings=={str(path):sha(path) for path in files}, 'Source changed during preparation'
    prepared=dict(kind='native_packet_room_ilp32_cpu',schema_version=1,complete=False,passed=False,
        case_count=len(cases),payload_byte_cases=56,original_capture=capture,source_sha256=bindings,
        inputs_sha256={str(p):sha(p) for p in output.rglob('*') if p.is_file()},
        execution_command=command,guest_pointer_bits=32,
        toolchain_sha256={str(p):sha(p) for p in (plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker)},
        limits=['CPU-only bounds comparison; no GPU packet submission or performance measurement.',
                'Occupied cursor is fixture state; preceding commands are not reconstructed or executed.'])
    (output/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(output/'prepared.json'),cases=len(cases),execution_command=command),indent=2))


def execute_ilp32(output):
    prepared_path=output/'prepared.json'
    proof=json.loads(prepared_path.read_text())
    for path,digest in {**proof['source_sha256'],**proof['inputs_sha256'],**proof['toolchain_sha256']}.items():
        assert sha(path)==digest, 'Stale proof input: '+path
    result=subprocess.run(proof['execution_command'],capture_output=True,text=True,timeout=60)
    (output/'stdout.json').write_text(result.stdout)
    (output/'stderr.log').write_text(result.stderr)
    observed=json.loads(result.stdout)
    passed=(result.returncode==0 and observed.get('passed') is True and observed.get('guest_result')==0 and
            observed.get('guest_pointer_bits')==32)
    for path,digest in {**proof['source_sha256'],**proof['inputs_sha256']}.items():
        assert sha(path)==digest, 'Proof input changed during execution: '+path
    closure=dict(proof,complete=True,passed=passed,returncode=result.returncode,guest_run=observed,
        prepared_sha256=sha(prepared_path),stdout_sha256=sha(output/'stdout.json'),stderr_sha256=sha(output/'stderr.log'))
    (output/'closure.json').write_text(json.dumps(closure,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,cases=proof['case_count'],closure=str(output/'closure.json')),indent=2))
    if not passed:
        raise RuntimeError('Actual ILP32 production-builder differential failed; diagnostic retained')


if __name__=='__main__':
    if '--prepare-ilp32' in sys.argv or '--execute-ilp32' in sys.argv:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--output',type=Path,required=True)
        group=parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--prepare-ilp32',action='store_true')
        group.add_argument('--execute-ilp32',action='store_true')
        args=parser.parse_args()
        prepare_ilp32(args.output) if args.prepare_ilp32 else execute_ilp32(args.output.resolve())
    else:
        unittest.main()
