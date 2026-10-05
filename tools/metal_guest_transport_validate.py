#!/usr/bin/env python3
"""Exercise the production C packet builder through real rebased ILP32 imports.

This isolated guest creates/uploads/copies/clears small native textures, checks
lossless readbacks, and tests packet bounds plus actual atomic host rejection.
It uses the existing native executor and never loads or installs the game.
"""
import argparse
import ast
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import metal_host_draw_validate as wire

require, sha = wire.require, wire.sha
SOURCES = [
    'port/linux/src/metal_guest_transport.h', 'port/linux/src/metal_guest_transport.c',
    'port/macos/tests/guest_metal_transport.c', 'port/macos/tests/guest_metal_transport_reply.c',
    'port/macos/tests/host_metal.mm',
    'port/macos/host/host_memory.c', 'port/macos/host/host.h',
    'port/macos/host/host_metal.mm', 'port/macos/host/metal_draw_encoder.h',
    'port/macos/host/metal_draw_encoder.mm', 'port/macos/include/halo_metal_abi.h',
    'port/android/include/halo_android_abi.h', 'port/macos/metal_imports.list',
    'tools/android_build.py', 'tools/android_asm_convert.py', 'tools/android_imports.py',
    'tools/metal_host_draw_validate.py', 'tools/metal_guest_transport_validate.py',
]
CASES = [
    'aligned_bounded_storage', 'window_offscreen_contract', 'required_capability_handshake',
    'original_u64_sequences', 'create_color_and_depth_stencil', 'exact_full_clear_readbacks',
    'immutable_aligned_upload_payload', 'zero_command_and_payload_padding', 'exact_texture_copy',
    'exact_rect_clear_preserves_outside', 'stale_sequence_rejection', 'payload_requires_command',
    'unknown_opcode_rejection', 'overflow_rejects_without_local_mutation', 'fixed_metadata_patch_bounds',
    'empty_packet_rejection', 'later_invalid_create_prevents_earlier_clear', 'undefined_content_rejection',
    'shutdown_prevents_readback',
]


def snapshot_sources(out):
    records = {}
    # Copy all inputs first, then verify the complete set again. Never mix a
    # header/backend mutation in progress into an allegedly frozen executor.
    for name in SOURCES:
        src, dst = ROOT / name, out / 'source-snapshot' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        digest = sha(src)
        shutil.copy2(src, dst)
        require(sha(src) == sha(dst) == digest, f'Source changed while copied: {name}')
        records[str(src)] = dict(snapshot=str(dst), sha256=digest)
    for path, record in records.items():
        require(sha(path) == record['sha256'], f'Source changed during snapshot: {path}')
    (out / 'source-snapshot.json').write_text(json.dumps(records, indent=2) + '\n')
    return records


def build_guest(out, llvm, linker, plugin, source_root):
    # ABI flags are loaded from the exact copied source, not a live build graph.
    assignments = [node for node in ast.parse((source_root / 'tools/android_build.py').read_text()).body
                   if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'GUEST_ABI_FLAGS'
                                                          for target in node.targets)]
    require(len(assignments) == 1, 'Missing original guest ABI flags')
    abi_flags = ast.literal_eval(assignments[0].value)
    require(isinstance(abi_flags, list) and all(isinstance(flag, str) for flag in abi_flags), 'Invalid guest ABI flags')
    resource = Path(subprocess.check_output([str(llvm / 'clang'), '-print-resource-dir'], text=True).strip())
    objects = []
    for name, source in [('guest', 'port/macos/tests/guest_metal_transport.c'),
                         ('transport', 'port/linux/src/metal_guest_transport.c'),
                         ('reply-guards', 'port/macos/tests/guest_metal_transport_reply.c')]:
        wire.run(llvm / 'clang', *abi_flags, '-ffreestanding', '-fno-builtin',
                 '-isystem', resource / 'include', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                 '-DHALO_MACOS=1', '-DHALO_MACOS_NATIVE_METAL=1', '-emit-llvm', '-S',
                 source_root / source, '-o', out / (name + '.ll'))
        wire.run(llvm / 'opt', '-load-pass-plugin=' + str(plugin), '-passes=halo-rebase,verify', '-S',
                 out / (name + '.ll'), '-o', out / (name + '.rebased.ll'))
        wire.run(llvm / 'llc', '-O2', '-mtriple=arm64_32-apple-watchos', '-aarch64-neon-syntax=generic',
                 out / (name + '.rebased.ll'), '-o', out / (name + '.darwin.s'))
        wire.run(sys.executable, source_root / 'tools/android_asm_convert.py',
                 out / (name + '.darwin.s'), out / (name + '.s'))
        obj = out / (name + '.o')
        wire.run(llvm / 'clang', '--target=aarch64-linux-android', '-c', out / (name + '.s'), '-o', obj)
        objects.append(obj)
    wire.run(sys.executable, source_root / 'tools/android_imports.py', '--host-table',
             out / 'host_import_table.c', out / 'imports.s', source_root / 'port/macos/metal_imports.list')
    wire.run(llvm / 'clang', '--target=aarch64-linux-android', '-c', out / 'imports.s', '-o', out / 'imports.o')
    script = out / 'guest.ld'
    script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    wire.run(linker, '-m', 'aarch64elf', '-T', script, *objects, out / 'imports.o', '-o', out / 'guest.elf')
    symbols = {}
    for line in subprocess.check_output([str(llvm / 'llvm-nm'), '--defined-only', str(out / 'guest.elf')], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    # The default platform glob sees an empty translation unit, not host imports.
    wire.run(llvm / 'clang', *abi_flags, '-ffreestanding', '-fno-builtin',
             '-isystem', resource / 'include', '-std=gnu11', '-emit-llvm', '-S',
             source_root / 'port/linux/src/metal_guest_transport.c', '-o', out / 'default-transport.ll')
    require('define ' not in (out / 'default-transport.ll').read_text(), 'Default graph exposes native transport functions')
    return symbols


def verify_prepared(out):
    prepared = json.loads((out / 'prepared.json').read_text())
    for path, digest in prepared['source_and_binary_sha256'].items():
        require(sha(path) == digest, f'Frozen transport input changed: {path}')
    require(prepared['execution_command'][0] == str(out / 'host_metal_probe'), 'Executor path differs')
    return prepared


def execute(out):
    prepared = verify_prepared(out)
    native = out / 'native'
    require(not any((native / name).exists() for name in ('stdout.json', 'stderr.log', 'execution.json')),
            'Execution already exists; preserve it and select a new folder')
    result = subprocess.run(prepared['execution_command'], cwd=ROOT, capture_output=True)
    (native / 'stdout.json').write_bytes(result.stdout)
    (native / 'stderr.log').write_bytes(result.stderr)
    verify_prepared(out)
    execution = dict(schema_version=1, kind='guest_transport_host_execution', complete=True,
                     returncode=result.returncode, command=prepared['execution_command'],
                     prepared_sha256=sha(out / 'prepared.json'), executor_sha256=sha(out / 'host_metal_probe'),
                     stdout_sha256=sha(native / 'stdout.json'), stderr_sha256=sha(native / 'stderr.log'))
    (native / 'execution.json').write_text(json.dumps(execution, indent=2) + '\n')
    record = json.loads(result.stdout)
    report = struct.unpack('<16I', (native / 'guest-report.bin').read_bytes())
    # Existing driver labels its generic dumps for the DRAW fixture. Here the
    # resource is explicitly RGBA8 and the guest report uses transport fields.
    aliases = {'native-color-bgra.bin': 'color.rgba', 'native-depth.bin': 'depth.f32',
               'native-stencil.bin': 'stencil.u8'}
    for source, target in aliases.items():
        shutil.copyfile(native / source, native / target)
    color, depth, stencil = (native / 'color.rgba').read_bytes(), (native / 'depth.f32').read_bytes(), (native / 'stencil.u8').read_bytes()
    expected_color = bytearray()
    expected_depth, expected_stencil = [], bytearray()
    for y in range(7):
        for x in range(13):
            inside = 3 <= x < 7 and 2 <= y < 5
            expected_color.extend((0, 255, 0, 255) if inside else (41 + x, 21 + y, 109, 255))
            expected_depth.append(.375 if inside else .75)
            expected_stencil.append(9 if inside else 17)
    expected = {'color': bytes(expected_color), 'depth': struct.pack('<91f', *expected_depth), 'stencil': bytes(expected_stencil)}
    actual = {'color': color, 'depth': depth, 'stencil': stencil}
    differences = {}
    for name in expected:
        require(len(actual[name]) == len(expected[name]), 'Readback extent differs')
        differences[name] = sum(a != b for a, b in zip(actual[name], expected[name]))
    passed = (result.returncode == 0 and record.get('kind') == 'native_metal_ilp32_transport' and
              record.get('guest_pointer_bits') == 32 and record.get('guest_result') == 0 and
              record.get('passed') is True and report[0:2] == (0, len(CASES)) and
              report[4:8] == (7, 1, 18, 8) and not any(differences.values()))
    proof = dict(prepared, complete=True, passed=passed, build_only=False, returncode=result.returncode,
                 execution=dict(file=str(native / 'execution.json'), sha256=sha(native / 'execution.json')),
                 guest_run=record, transport_report=list(report), readback_different_bytes=differences,
                 actual_payload_sha256={str(native / name): sha(native / name) for name in
                                       ['guest-report.bin', 'color.rgba', 'depth.f32', 'stencil.u8']})
    (out / 'result.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(dict(passed=passed, returncode=result.returncode, guest_result=record.get('guest_result'),
                         readback_different_bytes=differences, result=str(out / 'result.json')), indent=2))
    require(passed, 'Actual guest C transport fixture failed; output preserved')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rebase-plugin', type=Path)
    parser.add_argument('--llvm-bin', type=Path, default=Path('/opt/homebrew/opt/llvm@22/bin'))
    parser.add_argument('--linker', type=Path, default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--build-only', action='store_true')
    mode.add_argument('--execute-prepared', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.execute_prepared:
        execute(out)
        return
    require(args.rebase_plugin, 'Actual ILP32 build needs the existing rebase plugin')
    require(not (out / 'source-snapshot.json').exists(), 'Output already contains a snapshot; preserve it')
    records = snapshot_sources(out)
    llvm, linker, plugin = args.llvm_bin.resolve(), args.linker.absolute(), args.rebase_plugin.resolve()
    symbols = build_guest(out, llvm, linker, plugin, out / 'source-snapshot')
    executable, sources = wire.build_host(out, source_root=out / 'source-snapshot')
    required = ['__host_import_table', '__host_import_names', '__host_import_count', 'halo_transport_report', 'color', 'depth', 'stencil']
    require(all(name in symbols for name in required), 'Required fixture symbols are missing')
    native = out / 'native'
    native.mkdir()
    command = [str(executable), str(out / 'guest.elf'), *[hex(symbols[name]) for name in required[:3]], '0x400000',
               *[hex(symbols[name]) for name in required[3:]], '13', '7', str(native)]
    dependencies = [*[Path(record['snapshot']) for record in records.values()], *sources, plugin,
                    llvm / 'clang', llvm / 'opt', llvm / 'llc', linker, out / 'guest.elf', executable,
                    out / 'source-snapshot.json', out / 'guest.ld', out / 'imports.s', out / 'host_import_table.c']
    prepared = dict(schema_version=1, kind='actual_ilp32_guest_c_transport', complete=False, passed=False,
                    build_only=True, cases=CASES, protocol_corruption_guards=18, alpha_border_transport_guards=8, source_snapshot=records,
                    source_and_binary_sha256={str(path): sha(path) for path in dependencies}, execution_command=command,
                    limits=['Isolated synthetic resource transport; no live gameplay or presentation.',
                            'Alpha-border guards validate guest record construction and capability gates; they do not execute an alpha-border GPU draw.',
                            'Native original cached-query timing is not tested by this fixture.'])
    (out / 'prepared.json').write_text(json.dumps(prepared, indent=2) + '\n')
    if args.build_only:
        print(json.dumps(dict(prepared=str(out / 'prepared.json'), execution_command=command), indent=2))
    else:
        execute(out)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
