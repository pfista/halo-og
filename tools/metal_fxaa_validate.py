#!/usr/bin/env python3
"""Independent edges/invariants and atomic rejection via actual ILP32 imports.

Only authored initial images enter the GPU. The comparator checks independent
boundary/alpha/flat-color invariants, not a CPU copy of the FXAA implementation.
Preparation builds an isolated executor; execution is an explicit second step.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import metal_copy_subresource_validate as copy
import metal_host_draw_validate as wire
import metal_host_frame_validate as frame

sha, require = wire.sha, wire.require
REQUIRED = 1 | 2 | 4 | 16 | 64 | 128 | 32768
SOURCES = [
    'port/macos/host/host_memory.c', 'port/macos/host/host.h',
    'port/macos/host/host_metal.mm', 'port/macos/host/metal_draw_encoder.h',
    'port/macos/host/metal_draw_encoder.mm', 'port/macos/include/halo_metal_abi.h',
    'port/android/include/halo_android_abi.h', 'port/macos/tests/host_metal_frame.mm',
    'port/macos/tests/guest_metal_fxaa.c', 'port/linux/src/metal_guest_transport.h',
    'port/linux/src/metal_guest_transport.c', 'port/macos/metal_imports.list',
    'tools/metal_fxaa_validate.py', 'tools/metal_copy_subresource_validate.py',
    'tools/metal_host_frame_validate.py', 'tools/metal_host_draw_validate.py',
    'tools/android_build.py', 'tools/android_imports.py', 'tools/android_asm_convert.py',
]


def fxaa(id=1, x=8, y=4, width=16, height=24, generation=1):
    return struct.pack('<8I', 22, 32, id, generation, x, y, width, height)


def image(size, rect):
    x0, y0, width, height = rect
    data = bytearray()
    for y in range(size):
        for x in range(size):
            # A sloped binary edge has a known flat interior and no authored
            # intermediate values. Outside is bright magenta: any sampled
            # leakage across a viewport boundary breaks RGB equality inside.
            if x0 <= x < x0+width and y0 <= y < y0+height:
                value = 32 if x < x0+width//3+(y-y0)//3 else 224
                rgb = (value, value, value)
            else:
                rgb = (253, 11, 197)
            data.extend((*rgb, (x+size*y) & 255))
    return bytes(data)


def opposite(data):
    """Reverse only the independent binary grayscale edge polarity."""
    result = bytearray(data)
    for offset in range(0, len(result), 4):
        pixel = result[offset:offset+3]
        if pixel == bytes([32])*3 or pixel == bytes([224])*3:
            result[offset:offset+3] = bytes([256-pixel[0]])*3
    return bytes(result)


class Fixture(copy.Fixture):
    def read_checked(self, id, size, data, version, label, plane=1, mode=0, slot=0, aa_rect=None):
        self.read(id, size, data, version, plane, mode, slot, label)
        self.readbacks[-1]['aa_rect'] = list(aa_rect) if aa_rect else None


def fixture():
    f = Fixture()
    rect = (8, 4, 16, 24)
    initial = image(32, rect)
    reversed_edge = opposite(initial)
    left_rect = (0, 0, 16, 32)
    split = image(32, left_rect)
    small_rect = (0, 0, 16, 16)
    small = image(16, small_rect)
    depth, stencil, query = struct.pack('<f', .75)*1024, bytes([91])*1024, struct.pack('<Q', 1024)
    f.begin()
    for id, size, fmt, usage, mips, kind in (
        (1, 32, 2, 3, 1, 1), (2, 32, 3, 2, 1, 1), (3, 32, 1, 3, 1, 1),
        (4, 16, 2, 3, 1, 1), (5, 32, 1, 1, 1, 1), (6, 32, 1, 3, 1, 1),
        (7, 32, 1, 1, 4, 1), (8, 32, 1, 1, 1, 2), (10, 32, 1, 3, 1, 1),
        (11, 32, 2, 3, 1, 1), (12, 32, 2, 3, 1, 1)):
        f.emit(copy.create(id, size, fmt, mips, usage, kind))
    f.emit(copy.upload(1, initial, 32))
    f.emit(copy.upload(3, initial, 32))
    f.emit(copy.upload(4, small, 16))
    f.emit(copy.upload(11, reversed_edge, 32))
    f.emit(copy.upload(12, split, 32))
    f.emit(copy.clear(10, 32, 2, z=.75, stencil=91))
    f.emit(copy.program(100, copy.PATTERN))
    f.emit(struct.pack('<6I', 12, 24, 200, 1, 2, 0))
    f.emit(struct.pack('<4I', 14, 16, 200, 1))
    f.emit(copy.draw(10, 32, 100))
    f.emit(struct.pack('<4I', 15, 16, 200, 1))
    f.submit()
    f.read_checked(1, 32, initial, 1, 'off-initial-bgra')
    f.read_checked(3, 32, initial, 1, 'off-initial-rgba')
    f.read_checked(4, 16, small, 1, 'off-initial-small')
    f.begin()
    # Adjacent BGRA32 inputs of opposite polarity share scratch; same-target
    # adjacent viewports follow. Later RGBA32/BGRA16 inputs retain older shapes.
    f.emit(fxaa(1)); f.emit(fxaa(11))
    f.emit(fxaa(12, *left_rect)); f.emit(fxaa(12, 16, 0, 16, 32))
    f.emit(fxaa(3)); f.emit(fxaa(4, *small_rect))
    f.submit()
    baselines = [
        (1, 32, initial, 2, 1, rect), (3, 32, initial, 2, 1, rect),
        (2, 32, depth, 1, 2, None), (2, 32, stencil, 1, 4, None),
        (200, 1, query, 1, 8, None), (10, 32, copy.pattern(32, 0), 2, 1, None),
    ]
    for slot, (id, size, data, version, plane, aa_rect) in enumerate(baselines):
        f.read_checked(id, size, data, version, 'fxaa-baseline', plane, 1, slot, aa_rect)
    f.read_checked(4, 16, small, 2, 'fxaa-smaller-shape', aa_rect=small_rect)
    f.read_checked(11, 32, reversed_edge, 2, 'fxaa-shared-scratch-opposite-polarity', aa_rect=rect)
    # The second, uniformly magenta viewport stays exact. This simultaneously
    # checks no sample leakage across the seam in either command direction.
    f.read_checked(12, 32, split, 3, 'fxaa-adjacent-viewports', aa_rect=left_rect)
    # Repeated same-shape commands refresh immutable input, never an old cache.
    f.begin(); f.emit(copy.upload(1, initial, 32)); f.emit(fxaa(1)); f.submit()
    baselines[0] = (1, 32, initial, 4, 1, rect)
    f.read_checked(1, 32, initial, 4, 'fxaa-refreshed-input', 1, 1, 0, rect)
    cases = [
        ('zero-width', fxaa(width=0), -1), ('zero-height', fxaa(height=0), -1),
        ('out-of-bounds-x', fxaa(x=24), -1), ('out-of-bounds-y', fxaa(y=16), -1),
        ('overflow-x', fxaa(x=0xffffffff), -1), ('overflow-width', fxaa(width=0xffffffff), -1),
        ('stale-reference', fxaa(generation=2), -3), ('depth-target', fxaa(id=2), -2),
        ('sample-only', fxaa(id=5), -2), ('uninitialized', fxaa(id=6), -7),
        ('mip-chain', fxaa(id=7), -2), ('cube', fxaa(id=8), -2),
        ('short-record', fxaa()[:-8], -1), ('long-record', fxaa()+bytes(8), -2),
    ]
    for label, invalid, status in cases:
        f.begin()
        f.emit(struct.pack('<4I', 14, 16, 200, 1))
        f.emit(copy.draw(10, 32, 100, phase=1))
        f.emit(struct.pack('<4I', 15, 16, 200, 1))
        f.emit(copy.clear(10, 32, 2, z=.25, stencil=17))
        f.emit(fxaa(1)); f.emit(invalid)
        f.submit(status, 5, label)
        for slot, (id, size, data, version, plane, aa_rect) in enumerate(baselines):
            f.read_checked(id, size, data, version, 'atomic/'+label, plane, 2, slot, aa_rect)
    f.begin(); f.emit(struct.pack('<4I', 14, 16, 200, 1)); f.emit(fxaa(1))
    f.submit(-2, 1, 'active-visibility-query')
    for slot, (id, size, data, version, plane, aa_rect) in enumerate(baselines):
        f.read_checked(id, size, data, version, 'atomic/active-query', plane, 2, slot, aa_rect)
    return f


def compare(data, row):
    reference = bytes.fromhex(row['expected'])
    if len(data) != len(reference):
        return dict(passed=False, reason='byte-size')
    rect = row.get('aa_rect')
    if not rect:
        different = sum(a != b for a, b in zip(data, reference))
        return dict(passed=different == 0, different_bytes=different)
    x0, y0, width, height = rect
    size = row['width']
    alpha = outside = flat = leak = changed = intermediate = 0
    for y in range(size):
        for x in range(size):
            offset = (y*size+x)*4
            actual, before = data[offset:offset+4], reference[offset:offset+4]
            alpha += actual[3] != before[3]
            if not (x0 <= x < x0+width and y0 <= y < y0+height):
                outside += actual != before
                continue
            leak += not (actual[0] == actual[1] == actual[2] and 32 <= actual[0] <= 224)
            changed += actual[:3] != before[:3]
            intermediate += 32 < actual[0] < 224
            # Far from the authored edge, a full 17x17 neighborhood is flat;
            # this exceeds the filter's bounded eight-pixel search footprint.
            edge = x0+width//3+(y-y0)//3
            if abs(x-edge) > 9:
                flat += actual[:3] != before[:3]
    return dict(passed=not (alpha or outside or flat or leak) and changed > 0 and intermediate > 0,
                alpha_differences=alpha, outside_differences=outside, flat_differences=flat,
                viewport_leak_pixels=leak, changed_edge_pixels=changed, intermediate_edge_pixels=intermediate)


def snapshot(out):
    records = {}
    for name in SOURCES:
        source, destination = ROOT/name, out/'source-snapshot'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = sha(source); shutil.copy2(source, destination)
        require(sha(source) == sha(destination) == digest, 'Source changed during freeze: '+name)
        records[str(source)] = dict(snapshot=str(destination), sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records, indent=2)+'\n')
    return records


def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    require(len(nodes)==1,'Guest ABI flags missing');flags=ast.literal_eval(nodes[0].value)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    run=frame.run
    for name,path in [('guest','port/macos/tests/guest_metal_fxaa.c'),('transport','port/linux/src/metal_guest_transport.c')]:
        run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
            '-DHALO_MACOS=1','-DHALO_MACOS_NATIVE_METAL=1','-I',out,'-emit-llvm','-S',frozen/path,'-o',out/(name+'.ll'))
        run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/(name+'.ll'),'-o',out/(name+'.rebased.ll'))
        run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/(name+'.rebased.ll'),'-o',out/(name+'.darwin.s'))
        run(sys.executable,frozen/'tools/android_asm_convert.py',out/(name+'.darwin.s'),out/(name+'.s'))
    for name in ('guest','transport','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    (out/'diagnostic-imports.list').write_text((frozen/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n')
    run(sys.executable,frozen/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',out/'guest.ld',*[out/(n+'.o') for n in ('guest','transport','fixture','imports')],'-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    sections=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sections.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    return symbols,span


def prepare(out, llvm, linker, plugin):
    require(not out.exists(), 'Preserve earlier evidence; output must be fresh')
    out.mkdir(parents=True); records = snapshot(out); f = fixture()
    (out/'inputs.bin').write_bytes(f.inputs)
    actions = out/'actions.bin'; actions.write_bytes(b''.join(struct.pack('<12I', *a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_fxaa_inputs\nhalo_fxaa_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+
        '\n.balign 16\n.global halo_fxaa_actions\nhalo_fxaa_actions:\n.incbin '+json.dumps(str(actions))+'\n')
    header = out/'metal_fxaa_fixture.h'
    header.write_text(f'#define HALO_FXAA_ACTIONS {len(f.actions)}u\n#define HALO_FXAA_INPUT_BYTES {len(f.inputs)}u\n#define HALO_FXAA_PACKET_CAPACITY 1048576u\n#define HALO_FXAA_SCRATCH 4096u\n#define HALO_FXAA_REQUIRED_CAPS {REQUIRED}u\n')
    for index, packet in enumerate(f.packets):
        path = out/f'packet-{index:03}.bin'; path.write_bytes(bytes.fromhex(packet.pop('bytes')))
        packet.update(file=str(path), sha256=sha(path))
    package = dict(schema_version=1, kind='optional_fxaa_fixture', actions=len(f.actions), packets=f.packets,
                   readbacks=f.readbacks, negative_cases=f.negative, expected_after_gpu_uploaded=False,
                   required_capabilities=REQUIRED, algorithm_oracle=False)
    (out/'fixture.json').write_text(json.dumps(package, indent=2)+'\n')
    symbols, span = build_guest(out, llvm, linker, plugin)
    host, sources = frame.build_host(out)
    native = out/'native'; native.mkdir()
    command = [str(host), str(out/'guest.elf'), *[hex(symbols[n]) for n in
        ('__host_import_table', '__host_import_names', '__host_import_count')], str(span), hex(symbols['halo_frame_report']), str(native)]
    paths = [Path(row['snapshot']) for row in records.values()]+sources+[plugin, llvm/'clang', llvm/'opt', llvm/'llc', linker,
        host, out/'guest.elf', out/'inputs.bin', actions, out/'fixture.s', header, out/'diagnostic-imports.list',
        out/'imports.s', out/'host_import_table.c', out/'guest.ld', out/'source-snapshot.json']+[Path(p['file']) for p in f.packets]
    prepared = dict(schema_version=1, kind='optional_fxaa_prepared', passed=False, complete=False, gpu_executed=False,
                    fixture_sha256=sha(out/'fixture.json'), source_snapshot=records,
                    source_and_binary_sha256={str(path): sha(path) for path in paths}, execution_command=command,
                    validation_environment={'MTL_DEBUG_LAYER': '1'})
    verify_sources(records)
    (out/'prepared.json').write_text(json.dumps(prepared, indent=2)+'\n')
    print(json.dumps(dict(prepared=str(out/'prepared.json'), execution_command=command,
                         readbacks=len(f.readbacks), negative_cases=len(f.negative)), indent=2))


def verify_sources(records):
    for path, row in records.items():
        require(sha(path) == sha(row['snapshot']) == row['sha256'], 'Source drift: '+path)


def verify(out):
    prepared = json.loads((out/'prepared.json').read_text())
    fixture = json.loads((out/'fixture.json').read_text())
    require(sha(out/'fixture.json') == prepared['fixture_sha256'], 'Fixture changed')
    for path, digest in prepared['source_and_binary_sha256'].items():
        require(sha(path) == digest, 'Frozen input changed: '+path)
    verify_sources(prepared['source_snapshot'])
    return prepared, fixture


def execute(out):
    require(not (out/'execution.json').exists(), 'Preserve prior execution')
    prepared, fixture = verify(out)
    environment = dict(os.environ); environment.update(prepared['validation_environment'])
    observed = subprocess.run(prepared['execution_command'], cwd=ROOT, env=environment, capture_output=True, text=True)
    (out/'native.stdout').write_text(observed.stdout); (out/'native.stderr').write_text(observed.stderr)
    execution = dict(schema_version=1, kind='optional_fxaa_execution', complete=True, returncode=observed.returncode,
        command=prepared['execution_command'], prepared_sha256=sha(out/'prepared.json'), executor_sha256=sha(__file__),
        validation_environment=prepared['validation_environment'], stdout_sha256=sha(out/'native.stdout'), stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution, indent=2)+'\n'); verify(out)
    dump = json.loads((out/'native/checkpoints.json').read_text()); run = json.loads(observed.stdout)
    expected = {r['event']: r for r in fixture['readbacks']}; comparisons = []
    for actual in dump['checkpoints']:
        row = expected.pop(actual['event']); file = out/'native'/actual['file']
        metadata = all(actual[key] == row[key] for key in ('event', 'target_id', 'version', 'plane', 'bytes', 'width', 'height'))
        metadata &= actual['wire_content_version'] == row['version'] and actual['completed_sequence'] == row['sequence']
        checks = compare(file.read_bytes(), row)
        comparisons.append(dict(event=row['event'], label=row['label'], file=str(file), sha256=sha(file), metadata_valid=metadata, **checks))
    validation = 'Metal API Validation Enabled' in observed.stderr
    report = dump['report']
    passed = (observed.returncode == 0 and run.get('guest_result') == 0 and report[:2] == [1, 4] and report[12] == 2
              and not expected and validation and all(c['passed'] and c['metadata_valid'] for c in comparisons))
    result = dict(prepared, complete=True, passed=passed, gpu_executed=True, returncode=observed.returncode,
                  guest_run=run, guest_report=report, comparisons=comparisons, missing_readbacks=len(expected),
                  gpu_api_validation_enabled=validation, execution_sha256=sha(out/'execution.json'),
                  full_game_gate=False, hud_hook_gate=False, performance_gate=False,
                  limits=['Synthetic authored sloped edges and independent invariants only; no CPU FXAA oracle.',
                          'Actual GPU baselines independently verify atomic rollback including processed RGB, depth/stencil/query and versions.',
                          'Original-game visual quality, pre-HUD placement, history appearance and native-resolution frame time require separate playtests.'])
    verify(out); (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(passed=passed, returncode=observed.returncode, readbacks=len(comparisons),
                         first_failure=next((c for c in comparisons if not c['passed'] or not c['metadata_valid']), None)), indent=2))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['prepare', 'execute'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--llvm', type=Path, default=Path('/opt/homebrew/opt/llvm@22/bin'))
    parser.add_argument('--linker', type=Path, default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    parser.add_argument('--plugin', type=Path, default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    arguments = parser.parse_args(); out = arguments.out.resolve()
    if arguments.mode == 'prepare':
        prepare(out, arguments.llvm, arguments.linker.absolute(), arguments.plugin); return 0
    return execute(out)


if __name__ == '__main__':
    sys.exit(main())
