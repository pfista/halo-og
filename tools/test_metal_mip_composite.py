#!/usr/bin/env python3
"""CPU-only rendered-mip planning tests, including the actual ILP32 guest ABI.

The production Xbox mip-offset helper supplies physical offsets. No GL/Metal
calls, captured after-target uploads, application launch, or mip generation occur.
"""
import argparse
import copy
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
SOURCE = ROOT/'port/linux/src/metal_mip_composite.c'
HEADER = SOURCE.with_suffix('.h')
OK, INVALID, UNSUPPORTED, UNDEFINED = 0, -1, -2, -7
RGBA, BGRA, DEPTH, BC1 = 1, 2, 3, 4


class Ref(C.Structure):
    _fields_ = [('id', C.c_uint32), ('generation', C.c_uint32)]


class Key(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('physical_data', 'width', 'height', 'levels')]


class Request(C.Structure):
    _fields_ = [('key', Key), ('storage_format', C.c_uint32), ('level_offsets', C.c_uint32*17)]


class Target(C.Structure):
    _fields_ = [('resource', Ref)] + [(n, C.c_uint32) for n in (
        'physical_data', 'width', 'height', 'storage_width', 'storage_height', 'levels',
        'type', 'format', 'usage', 'initialized')] + [
        ('last_rendered', C.c_uint64), ('content_version', C.c_uint64)]


class Copy(C.Structure):
    _fields_ = [('source', Ref), ('source_content_version', C.c_uint64)] + [
        (n, C.c_uint32) for n in ('source_physical_data', 'source_mip', 'source_slice',
                                 'destination_mip', 'destination_slice', 'width', 'height')]


class Plan(C.Structure):
    _fields_ = [('key', Key), ('storage_format', C.c_uint32), ('copy_count', C.c_uint32),
                ('copies', Copy*16)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request(width=128, height=128, levels=4, base=0x00100000, bpp=4, fmt=BGRA):
    offsets = [0]
    for level in range(levels):
        offsets.append(offsets[-1]+max(1, width//2**level)*max(1, height//2**level)*bpp)
    return Request(Key(base, width, height, levels), fmt,
                   (C.c_uint32*17)(*(offsets+[0]*(17-len(offsets)))))


def targets(req):
    return [Target(Ref(level+1, 3), req.key.physical_data+req.level_offsets[level],
                   max(1, req.key.width//2**level), max(1, req.key.height//2**level),
                   max(1, req.key.width//2**level), max(1, req.key.height//2**level),
                   1, 1, req.storage_format, 3, 1, 100+level, (1<<40)+level+1)
            for level in range(req.key.levels)]


def oracle(req, aliases):
    """Select addresses independently using grouping and greatest timestamps."""
    key = req.key
    if (not key.physical_data or not key.width or not key.height or
            max(key.width, key.height) > 32768 or key.width & (key.width-1) or
            key.height & (key.height-1) or not 1 <= key.levels <= 16 or
            key.levels > max(key.width, key.height).bit_length() or req.level_offsets[0] or
            any(req.level_offsets[n+1] <= req.level_offsets[n] for n in range(key.levels)) or
            key.physical_data+req.level_offsets[key.levels] > 2**32 or len(aliases) > 65536):
        return INVALID, None
    if req.storage_format not in (RGBA, BGRA):
        return UNSUPPORTED, None
    plan = Plan()
    plan.key, plan.storage_format, plan.copy_count = key, req.storage_format, key.levels
    for level in range(key.levels):
        address = key.physical_data+req.level_offsets[level]
        candidates = [a for a in aliases if a.physical_data == address and a.usage & 2 and a.format != DEPTH]
        if not candidates:
            return UNSUPPORTED, None
        latest = max(a.last_rendered for a in candidates)
        selected = [a for a in candidates if a.last_rendered == latest]
        # Compare named values; ignore ABI padding in input metadata.
        values = {(a.resource.id, a.resource.generation, a.physical_data, a.width, a.height,
                   a.storage_width, a.storage_height, a.levels, a.type, a.format, a.usage,
                   a.initialized, a.last_rendered, a.content_version) for a in selected}
        a = selected[0]
        if len(values) != 1 or not a.resource.id or not a.resource.generation or a.initialized > 1:
            return INVALID, None
        width, height = max(1, key.width//2**level), max(1, key.height//2**level)
        if ((a.width, a.height, a.storage_width, a.storage_height, a.levels, a.type, a.format) !=
                (width, height, width, height, 1, 1, req.storage_format) or a.usage & ~3):
            return UNSUPPORTED, None
        if not a.initialized or not a.last_rendered or not a.content_version:
            return UNDEFINED, None
        plan.copies[level] = Copy(a.resource, a.content_version, address, 0, 0, level, 0, width, height)
    return OK, plan


def cases():
    result = []
    for level_count in (1, 2, 3, 4):
        req = request(levels=level_count)
        result.append((req, targets(req)))
    req = request(256, 128, 9, bpp=2)
    result.append((req, targets(req)))  # Physical texel pitch differs from native BGRA8 storage.
    rng = random.Random(0x4d495043)
    for _ in range(512):
        req = request(2**rng.randrange(0, 13), 2**rng.randrange(0, 13), levels=1)
        req = request(req.key.width, req.key.height,
                      rng.randrange(1, max(req.key.width, req.key.height).bit_length()+1),
                      bpp=rng.choice((1, 2, 4)))
        aliases = targets(req)
        level = rng.randrange(len(aliases))
        action = rng.randrange(12)
        if action == 0:
            aliases.pop(level)
        elif action == 1:
            aliases[level].initialized = 0
        elif action == 2:
            aliases[level].content_version = 0
        elif action == 3:
            aliases[level].storage_width *= 2
        elif action == 4:
            aliases[level].format = RGBA if req.storage_format == BGRA else BGRA
        elif action == 5:
            stale = copy.copy(aliases[level]); stale.last_rendered -= 1; stale.resource.id += 500
            aliases.append(stale)
        elif action == 6:
            tied = copy.copy(aliases[level]); tied.resource.id += 500; aliases.append(tied)
        elif action == 7:
            aliases.append(copy.copy(aliases[level]))
        elif action == 8:
            aliases[level].type = 2
        elif action == 9:
            aliases[level].resource.generation = 0
        elif action == 10:
            depth = copy.copy(aliases[level]); depth.format = DEPTH; depth.last_rendered += 500
            aliases.append(depth)
        else:
            req.key.physical_data = 0xfffffff0
        rng.shuffle(aliases)
        result.append((req, aliases))
    return result


def compile_host(directory):
    sys.path.insert(0, str(ROOT/'tools'))
    from test_xgpu_texture_copy import harness_prefix
    wrapper = directory/'planner.c'
    wrapper.write_text(harness_prefix() + '#include "'+str(ROOT/'port/linux/src/xbox_textures.c')+'"\n'
        '#include "'+str(SOURCE)+'"\n'
        'unsigned long original_offset(uint32_t f,uint32_t size,uint32_t n) {\n'
        ' struct xgpu_texture_description d; xgpu_texture_describe(f,size,&d);\n'
        ' return xgpu_texture_level_offset(&d,n); }\n')
    library = directory/'planner.dylib'
    subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    wrapper, '-o', library], check=True, capture_output=True)
    lib = C.CDLL(str(library))
    lib.halo_metal_mip_composite_plan.argtypes = [C.POINTER(Request), C.POINTER(Target), C.c_uint32, C.POINTER(Plan)]
    lib.halo_metal_mip_composite_plan.restype = C.c_int
    lib.original_offset.argtypes = [C.c_uint32]*3
    lib.original_offset.restype = C.c_ulong
    return lib


class CompositeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='halo-metal-mip-planner-')
        cls.lib = compile_host(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, req, aliases, expected=None):
        status, desired = oracle(req, aliases)
        if expected is not None:
            self.assertEqual(status, expected)
        output = Plan.from_buffer_copy(b'\xa7'*C.sizeof(Plan))
        actual = self.lib.halo_metal_mip_composite_plan(C.byref(req),
            (Target*len(aliases))(*aliases) if aliases else None, len(aliases), C.byref(output))
        self.assertEqual(actual, status)
        self.assertEqual(bytes(output), bytes(desired) if desired is not None else b'\xa7'*C.sizeof(Plan))
        return output

    def test_original_damnation_offsets_dynamic_counts_and_current_serials(self):
        # Original source rule, not a guessed native BGRA8 layout: Xbox X8R8G8B8,
        # nonlinear128x128 with4 requested authored levels.
        original = (2<<4) | (7<<8) | (4<<16) | (7<<20) | (7<<24)
        offsets = [self.lib.original_offset(original, 0, n) for n in range(5)]
        self.assertEqual(offsets, [0, 65536, 81920, 86016, 87040])
        full = request()
        aliases = targets(full)
        for count in (4, 1, 3, 2, 4):
            req = request(levels=count)
            for n in range(count+1):
                req.level_offsets[n] = self.lib.original_offset(original, 0, n)
            plan = self.check(req, aliases, OK)
            self.assertEqual(plan.key.levels, count)
            self.assertEqual([plan.copies[n].destination_mip for n in range(count)], list(range(count)))
        aliases[2].content_version += 1
        aliases[2].last_rendered += 500
        self.assertEqual(self.check(full, aliases, OK).copies[2].source_content_version, (1<<40)+4)

    def test_latest_alias_no_stale_fallback_ties_and_irrelevant_depth(self):
        req, aliases = request(), targets(request())
        newer = copy.copy(aliases[1]); newer.resource.id = 100; newer.last_rendered += 1
        newer.content_version = (1<<48)+1
        self.assertEqual(self.check(req, aliases+[newer], OK).copies[1].source.id, 100)
        newer.width *= 2
        self.check(req, aliases+[newer], UNSUPPORTED)
        newer.width //= 2; newer.last_rendered = aliases[1].last_rendered
        self.check(req, aliases+[newer], INVALID)
        newest = copy.copy(newer); newest.resource.id += 1; newest.last_rendered += 1
        self.check(req, [newer]+aliases+[newest], OK)  # Older ambiguity cannot taint the newest alias.
        self.check(req, aliases+[copy.copy(aliases[1])], OK)
        depth = copy.copy(newest); depth.format = DEPTH; depth.last_rendered += 1
        shader_only = copy.copy(newest); shader_only.usage = 1; shader_only.last_rendered += 1
        self.check(req, aliases+[depth, shader_only], OK)

    def test_missing_suffix_uninitialized_and_storage_constraints_are_atomic(self):
        req = request()
        for count in range(4):
            self.check(req, targets(req)[:count], UNSUPPORTED)
        for field, value, status in [('initialized', 0, UNDEFINED), ('content_version', 0, UNDEFINED),
            ('last_rendered', 0, UNDEFINED), ('initialized', 2, INVALID), ('storage_height', 65, UNSUPPORTED),
            ('type', 2, UNSUPPORTED), ('levels', 2, UNSUPPORTED), ('format', BC1, UNSUPPORTED),
            ('usage', 7, UNSUPPORTED)]:
            aliases = targets(req); setattr(aliases[3], field, value)
            self.check(req, aliases, status)

    def test_rectangular_physical_pitch_and_endpoint_bounds(self):
        req = request(256, 128, 9, bpp=2)
        plan = self.check(req, targets(req), OK)
        self.assertEqual([(c.width, c.height) for c in plan.copies[:9]][-2:], [(2, 1), (1, 1)])
        req = request(32, 32, 1, base=0xfffff000)
        self.check(req, targets(req), OK)  # Exclusive endpoint exactly2^32.
        req.key.physical_data += 1
        self.check(req, targets(req), INVALID)

    def test_invalid_input_never_changes_output(self):
        for field, value in [('width', 0), ('width', 127), ('height', 65536), ('levels', 0),
                             ('levels', 17), ('physical_data', 0)]:
            req = request(); setattr(req.key, field, value)
            self.check(req, [], INVALID)
        req = request(1, 1, 2); self.check(req, [], INVALID)
        for level, offset in [(0, 1), (2, 65536), (4, 0xffffffff)]:
            req = request(); req.level_offsets[level] = offset
            self.check(req, targets(req), INVALID)
        output = Plan.from_buffer_copy(b'\xa7'*C.sizeof(Plan))
        req = request()
        for args in [(None, None, 0, C.byref(output)), (C.byref(req), None, 1, C.byref(output)),
                     (C.byref(req), None, 65537, C.byref(output)), (C.byref(req), None, 0, None)]:
            self.assertEqual(self.lib.halo_metal_mip_composite_plan(*args), INVALID)
            self.assertEqual(bytes(output), b'\xa7'*C.sizeof(Plan))

    def test_independent_shuffled_alias_corpus(self):
        for req, aliases in cases():
            self.check(req, aliases)


def prepare_ilp32(output):
    sys.path.insert(0, str(ROOT))
    from tools.android_build import GUEST_ABI_FLAGS
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = [SOURCE, HEADER, ROOT/'port/macos/include/halo_metal_abi.h', Path(__file__).resolve(),
             ROOT/'port/linux/src/xbox_textures.c', ROOT/'port/linux/src/xgpu.h',
             ROOT/'port/include/xdk/xdk_d3d8.h', ROOT/'tools/test_xgpu_texture_copy.py',
             ROOT/'tools/android_build.py', ROOT/'tools/android_asm_convert.py',
             ROOT/'tools/android_imports.py', ROOT/'port/macos/metal_imports.list']
    bindings = {str(p): sha(p) for p in files}
    snapshot = output/'source-snapshot'
    for path in files:
        destination = snapshot/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    corpus = cases()
    blob = bytearray()
    for req, aliases in corpus:
        status, plan = oracle(req, aliases)
        blob += struct.pack('<IiII', len(aliases), status, 0, 0)+bytes(req)
        blob += b''.join(bytes(a) for a in aliases)
        blob += bytes(plan) if plan is not None else b'\xa7'*C.sizeof(Plan)
    (output/'cases.bin').write_bytes(blob)
    (output/'cases.s').write_text('.section .rodata\n.balign 16\n.global mip_cases\nmip_cases:\n.incbin "'+str(output/'cases.bin')+'"\n')
    guest = output/'guest.c'
    guest.write_text('''#define HALO_MACOS_NATIVE_METAL 1
#include <stdint.h>
#include "'''+str(snapshot/SOURCE.relative_to(ROOT))+'''"
_Static_assert(sizeof(void*)==4 && sizeof(unsigned long)==4,"actualILP32");
_Static_assert(sizeof(struct halo_metal_mip_composite_request)==88,"requestABI");
_Static_assert(sizeof(struct halo_metal_mip_composite_target)==64,"targetABI");
_Static_assert(sizeof(struct halo_metal_mip_composite_plan)==792,"planABI");
void *memset(void *p,int c,unsigned long n) {unsigned char *d=p;for(unsigned long i=0;i<n;i++)d[i]=(unsigned char)c;return p;}
void *memcpy(void *p,const void *q,unsigned long n) {unsigned char *d=p;const unsigned char *s=q;for(unsigned long i=0;i<n;i++)d[i]=s[i];return p;}
extern const unsigned char mip_cases[];
uint32_t guest_test(uint32_t unused) {
    (void)unused;const unsigned char *cursor=mip_cases;
    for(uint32_t i=0;i<'''+str(len(corpus))+''';i++) {
        const uint32_t *header=(const uint32_t *)(const void *)cursor;
        uint32_t count=header[0];int32_t expected=(int32_t)header[1];cursor+=16;
        const struct halo_metal_mip_composite_request *request=(const void *)cursor;cursor+=88;
        const struct halo_metal_mip_composite_target *targets=(const void *)cursor;cursor+=64*count;
        const unsigned char *expected_plan=cursor;cursor+=792;
        struct halo_metal_mip_composite_plan plan;memset(&plan,0xa7,792);
        int status=halo_metal_mip_composite_plan(request,targets,count,&plan);
        if(status!=expected)return 10000+i;
        const unsigned char *actual=(const void *)&plan;
        for(uint32_t j=0;j<792;j++)if(actual[j]!=expected_plan[j])return 20000+i;
    }
    return 0;
}
''')
    llvm = Path('/opt/homebrew/opt/llvm@22/bin')
    linker = Path('/opt/homebrew/opt/lld@22/bin/ld.lld')  # Keep basename dispatch; never resolve.
    plugin = ROOT.parent/'pfista-halo-macos/build/macos/guest_rebase.dylib'
    previous = json.loads((ROOT/'build/metal-poc/native-draw-state-ilp32-final/prepared.json').read_text())
    executor = Path(previous['execution_command'][0])
    assert sha(executor) == previous['executor_sha256'], 'Retained CPU executor changed'
    def run(*args):
        result = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
    resource = Path(subprocess.check_output([llvm/'clang', '-print-resource-dir'], text=True).strip())
    run(llvm/'clang', *GUEST_ABI_FLAGS, '-ffreestanding', '-fno-builtin', '-isystem', resource/'include',
        '-std=c11', '-Wall', '-Wextra', '-Werror', '-emit-llvm', '-S', guest, '-o', output/'guest.ll')
    run(llvm/'opt', '-load-pass-plugin='+str(plugin), '-passes=halo-rebase,verify', '-S', output/'guest.ll', '-o', output/'guest.rebased.ll')
    run(llvm/'llc', '-O2', '-mtriple=arm64_32-apple-watchos', '-aarch64-neon-syntax=generic', output/'guest.rebased.ll', '-o', output/'guest.darwin.s')
    run(sys.executable, ROOT/'tools/android_asm_convert.py', output/'guest.darwin.s', output/'guest.s')
    run(sys.executable, ROOT/'tools/android_imports.py', '--host-table', output/'host_import_table.c', output/'imports.s', ROOT/'port/macos/metal_imports.list')
    for name in ('guest', 'cases', 'imports'):
        run(llvm/'clang', '--target=aarch64-linux-android', '-c', output/(name+'.s'), '-o', output/(name+'.o'))
    (output/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker, '-m', 'aarch64elf', '-T', output/'guest.ld', output/'guest.o', output/'cases.o', output/'imports.o', '-o', output/'guest.elf')
    symbols = {}
    for line in subprocess.check_output([llvm/'llvm-nm', '--defined-only', output/'guest.elf'], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    copied = output/'host_ilp32_probe'; shutil.copy2(executor, copied)
    command = [str(copied), str(output/'guest.elf'), *[hex(symbols[n]) for n in
               ('__host_import_table', '__host_import_names', '__host_import_count')], '0x5000000']
    assert all(sha(p) == h for p, h in bindings.items()), 'Source changed during preparation'
    proof = dict(kind='native_rendered_mip_cpu_planner', complete=False, passed=False,
                 case_count=len(corpus), source_sha256=bindings,
                 source_snapshot_sha256={str(snapshot/p.relative_to(ROOT)): sha(snapshot/p.relative_to(ROOT)) for p in files},
                 inputs_sha256={str(output/n): sha(output/n) for n in ('cases.bin', 'cases.s', 'guest.c', 'guest.elf', 'host_ilp32_probe')},
                 executor_sha256=sha(executor), execution_command=command,
                 toolchain_sha256={str(p): sha(p) for p in (llvm/'clang', llvm/'opt', llvm/'llc', linker, plugin)},
                 limits=['CPU planning only; no GPU copies, mip generation, or game rendering',
                         'Caller must preserve source snapshot serials/order when appending copies'])
    (output/'prepared.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(json.dumps(dict(prepared=str(output/'prepared.json'), cases=len(corpus)), indent=2))


def execute_ilp32(output):
    prepared_path = output/'prepared.json'
    proof = json.loads(prepared_path.read_text())
    hashes = {**proof['source_sha256'], **proof['source_snapshot_sha256'],
              **proof['inputs_sha256'], **proof['toolchain_sha256']}
    assert all(sha(p) == h for p, h in hashes.items()), 'Stale proof input'
    result = subprocess.run(proof['execution_command'], capture_output=True, text=True, timeout=60)
    (output/'stdout.json').write_text(result.stdout); (output/'stderr.log').write_text(result.stderr)
    observed = json.loads(result.stdout)
    passed = (result.returncode == 0 and observed.get('passed') is True and
              observed.get('guest_result') == 0 and observed.get('guest_pointer_bits') == 32)
    assert all(sha(p) == h for p, h in hashes.items()), 'Proof inputs changed during execution'
    closure = dict(proof, complete=True, passed=passed, returncode=result.returncode, guest_run=observed,
                   prepared_sha256=sha(prepared_path), stdout_sha256=sha(output/'stdout.json'), stderr_sha256=sha(output/'stderr.log'))
    (output/'closure.json').write_text(json.dumps(closure, indent=2)+'\n')
    print(json.dumps(dict(passed=passed, cases=proof['case_count'], closure=str(output/'closure.json')), indent=2))
    if not passed:
        raise RuntimeError('Actual ILP32 mip planner proof failed; diagnostic retained')


if __name__ == '__main__':
    if '--prepare-ilp32' in sys.argv or '--execute-ilp32' in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--output', type=Path, required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--prepare-ilp32', action='store_true')
        group.add_argument('--execute-ilp32', action='store_true')
        args = parser.parse_args()
        prepare_ilp32(args.output) if args.prepare_ilp32 else execute_ilp32(args.output.resolve())
    else:
        unittest.main()
