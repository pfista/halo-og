"""Freeze a completed native game build without changing or rebuilding it.

The execution record is supplied by the process observer, independently of
these binary/graph checks. This tool never infers a successful exit from files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LLVM_NM = Path('/opt/homebrew/opt/llvm@22/bin/llvm-nm')
FORBIDDEN_SYMBOL = re.compile(r'(?<![A-Za-z0-9])_?(?:gl[A-Z]|egl[A-Z]|host_gl_|hostgl_|host_sdl_gl_|SDL_GL_)')
FORBIDDEN_LINK = re.compile(r'ANGLE|libEGL|libGLES|OpenGL\.framework', re.I)
FORBIDDEN_GRAPH = ('d3d8_gl.', 'gl_functions.', 'guest_gl.', 'guest_gl_stubs',
                   'android_gl_stubs', 'gl_imports.list', 'toolchain/gl', 'GLES2', 'GLES3')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def relative(path):
    return str(path.resolve().relative_to(ROOT))


def describe(path):
    return {'path': relative(path), 'sha256': digest(path.read_bytes())}


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def copy_snapshot(source, destination, expected_sha256):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('Snapshot destination already exists')
    shutil.copy2(source, destination)
    if digest(destination.read_bytes()) != expected_sha256:
        raise ValueError('Input changed during snapshot copy: ' + str(source))


def record_command(output, name, command):
    run = subprocess.run(command, cwd=ROOT, capture_output=True)
    write_new(output / (name + '.stdout'), run.stdout)
    write_new(output / (name + '.stderr'), run.stderr)
    if run.returncode:
        raise ValueError(f'{name} exited {run.returncode}')
    return run.stdout.decode(), {
        'command': [str(word) for word in command], 'returncode': run.returncode,
        'stdout': describe(output / (name + '.stdout')),
        'stderr': describe(output / (name + '.stderr')),
    }


def binding_paths(reference, texture_contract='original', fixed_function=False):
    """Select the existing proof inputs plus explicitly requested helpers."""
    paths = [item['path'] for item in reference['source_bindings']]
    for path in ('port/linux/src/metal_packet_room.c', 'port/linux/src/metal_packet_room.h',
                 'port/linux/src/xbox_xapi.c'):
        if path not in paths:
            paths.append(path)
    if len(paths) != 32 or len(set(paths)) != len(paths):
        raise ValueError('Expected 32 distinct native build bindings')
    extended = texture_contract in ('copy-volume', 'copy-volume-depth', 'copy-volume-depth-border')
    typed_depth = texture_contract in ('copy-volume-depth', 'copy-volume-depth-border')
    if extended:
        paths += ['port/linux/src/metal_mip_composite.c', 'port/linux/src/metal_mip_composite.h']
    if fixed_function:
        paths += ['port/linux/src/metal_fixed_function.c', 'port/linux/src/metal_fixed_function.h']
    additional_paths = [
        'build.ninja', 'port/linux/src/xgpu_msl.h', 'tools/metal_live_build_proof.py',
        'tools/test_macos_renderer_build.py',
        'tools/test_metal_packet_room.py', 'tools/test_metal_host_frame_coalesce.py',
        'build/macos-metal/guest/gen/native_host_imports.list',
        'build/macos-metal/guest/gen/imports.s',
        *[f'build/macos-metal/guest/obj/port/linux/src/{name}.o'
          for name in ('d3d8_metal', 'metal_packet_room', 'xbox_xapi')],
    ]
    if extended:
        additional_paths += [f'build/macos-metal/guest/obj/port/linux/src/{name}.o'
                             for name in ('metal_mip_composite', 'xbox_textures')]
    if typed_depth:
        additional_paths += ['source/rasterizer/rasterizer.h', 'source/rasterizer/rasterizer.c',
                             'build/macos-metal/guest/obj/source/rasterizer/rasterizer.o']
    if fixed_function:
        additional_paths.append('build/macos-metal/guest/obj/port/linux/src/metal_fixed_function.o')
    return paths, additional_paths


def graph_checks(text, fixed_function=False):
    logical = text.replace('$\n', '')
    native = [line for line in logical.splitlines()
              if line.startswith('build ') and 'build/macos-metal/' in line.split(':', 1)[0]]
    if not native:
        raise ValueError('No native build graph')
    for line in native:
        if any(token in line for token in FORBIDDEN_GRAPH):
            raise ValueError('GL dependency in native build edge')
    paths = ('d3d8_metal', 'metal_packet_room', 'xbox_xapi')
    if fixed_function:
        paths += ('metal_fixed_function',)
    edges = {}
    for name in paths:
        target = f'build/macos-metal/guest/obj/port/linux/src/{name}.o'
        matches = [line for line in native if line.startswith('build ' + target + ':')]
        if len(matches) != 1 or f'port/linux/src/{name}.c' not in matches[0]:
            raise ValueError('Missing native source edge: ' + name)
        if name == 'metal_fixed_function' and f'port/linux/src/{name}.c' not in matches[0].split():
            raise ValueError('Missing exact fixed-function source edge')
        edges[name] = matches[0]
    links = [line for line in native if line.startswith('build build/macos-metal/halo_guest.elf:')]
    if len(links) != 1 or not all(f'/port/linux/src/{name}.o' in links[0] for name in paths):
        raise ValueError('Native guest link omits source object')
    if fixed_function and 'build/macos-metal/guest/obj/port/linux/src/metal_fixed_function.o' not in links[0].split():
        raise ValueError('Native guest link omits exact fixed-function object')
    return {'native_build_edges': len(native), 'source_edges': edges,
            'guest_link_edge': links[0], 'no_gl_native_edges': True}


def implementation_checks(name, symbols, object_symbols, guest_symbols, compile_text):
    lines = [line for line in compile_text.splitlines() if f'port/linux/src/{name}.c' in line]
    if len(lines) != 1 or not all(flag in lines[0] for flag in (
            '--target=arm64_32-apple-watchos', '-DHALO_MACOS_NATIVE_METAL=1', '-ffp-contract=off')):
        raise ValueError('Missing ILP32 native compile flags: ' + name)
    for symbol in symbols:
        if not re.search(r'\b[Tt]\s+_?' + re.escape(symbol) + r'\s*$', object_symbols, re.M):
            raise ValueError('Native object omits exported implementation: ' + symbol)
        if not re.search(r'\b[Tt]\s+_?' + re.escape(symbol) + r'\s*$', guest_symbols, re.M):
            raise ValueError('Final guest omits linked implementation: ' + symbol)
    if FORBIDDEN_SYMBOL.search(object_symbols):
        raise ValueError('Native source object retains GL boundary: ' + name)


def prepare(output, execution_path, reference_path, texture_contract='original', fixed_function=False):
    if output.exists():
        raise ValueError('Output already exists; historical proofs must be preserved')
    execution_bytes = execution_path.read_bytes()
    execution = json.loads(execution_bytes)
    if execution.get('returncode') != 0 or execution.get('timed_out', False) is not False:
        raise ValueError('Build observer did not report exit 0 without timeout')
    if not isinstance(execution.get('command'), list) or not execution['command']:
        raise ValueError('Build observer command is missing')
    log = execution.get('log')
    if not isinstance(log, dict) or set(log) != {'path', 'sha256'}:
        raise ValueError('Build observer requires a path/SHA256 log descriptor')
    log_path = ROOT / log['path']
    if describe(log_path) != log:
        raise ValueError('Build log changed after observed completion')
    reference = read_json(reference_path)
    extended = texture_contract in ('copy-volume', 'copy-volume-depth', 'copy-volume-depth-border')
    typed_depth = texture_contract in ('copy-volume-depth', 'copy-volume-depth-border')
    paths, additional_paths = binding_paths(reference, texture_contract, fixed_function)
    bindings = [describe(ROOT / path) for path in paths]
    evidence_bindings = [describe(ROOT / path) for path in additional_paths]
    if typed_depth:
        header = (ROOT / 'source/rasterizer/rasterizer.h').read_text()
        if not re.search(r'offsetof\(struct rasterizer_globals_definition,\s*floating_point_zbuffer\)\s*==\s*0x3C', header):
            raise ValueError('Original float-Z global ABI assertion changed')
    unchanged = ('port/macos/include/halo_metal_abi.h', 'port/macos/host/host_metal.mm',
                 'port/linux/src/metal_guest_transport.c', 'port/linux/src/metal_guest_transport.h')
    old = {item['path']: item['sha256'] for item in reference['source_bindings']}
    unchanged_checks = {path: describe(ROOT / path)['sha256'] == old[path] for path in unchanged}
    if not extended and not all(unchanged_checks.values()):
        raise ValueError('ABI/backend/transport differs from the reference build')
    if extended:
        abi = (ROOT / 'port/macos/include/halo_metal_abi.h').read_text()
        for symbol, value in (('HALO_METAL_CAP_COPY_SUBRESOURCE', 4096),
                              ('HALO_METAL_CAP_VOLUME', 8192),
                              ('HALO_METAL_COPY_SUBRESOURCE', 20),
                              ('HALO_METAL_TEXTURE_3D', 3)):
            if not re.search(r'\b' + symbol + r'\s*=\s*' + str(value) + r'u?\b', abi):
                raise ValueError('Missing explicit additive texture contract: ' + symbol)
        if texture_contract == 'copy-volume-depth-border':
            for symbol, value in (('HALO_METAL_CAP_VOLUME_BORDER', 16384),
                                  ('HALO_METAL_DRAW_VOLUME_BORDER', 21)):
                if not re.search(r'\b' + symbol + r'\s*=\s*' + str(value) + r'u?\b', abi):
                    raise ValueError('Missing explicit volume colour border contract: ' + symbol)
    output.mkdir(parents=True)
    write_new(output / 'execution.json', execution_bytes)
    write_new(output / 'build.log', log_path.read_bytes())
    for item in bindings + evidence_bindings:
        data = (ROOT / item['path']).read_bytes()
        if digest(data) != item['sha256']:
            raise ValueError('Input changed during freeze: ' + item['path'])
        copy_snapshot(ROOT / item['path'], output / 'snapshot' / item['path'], item['sha256'])
    graph = graph_checks((ROOT / 'build.ninja').read_text(), fixed_function)
    linkage, linkage_command = record_command(output, 'linkage', ['otool', '-L', 'build/macos-metal/halo'])
    host_symbols, host_command = record_command(output, 'host-undefined', ['nm', '-u', 'build/macos-metal/halo'])
    guest_symbols, guest_command = record_command(output, 'guest-defined',
        [str(LLVM_NM), '--defined-only', '--extern-only', 'build/macos-metal/halo_guest.elf'])
    if FORBIDDEN_LINK.search(linkage) or FORBIDDEN_SYMBOL.search(host_symbols):
        raise ValueError('GL linkage or host boundary symbol found')
    import_text = '\n'.join((ROOT / path).read_text() for path in (
        'build/macos-metal/host/host_import_table.c',
        'build/macos-metal/guest/gen/native_host_imports.list',
        'build/macos-metal/guest/gen/imports.s', 'port/macos/metal_imports.list'))
    if FORBIDDEN_SYMBOL.search(import_text):
        raise ValueError('GL guest or host import found')
    commands = [linkage_command, host_command, guest_command]
    compiled = {}
    object_implementations = [('d3d8_metal', 'halo_metal_flush_pending'),
                             ('metal_packet_room', 'halo_metal_packet_room'),
                             ('xbox_xapi', 'XLaunchNewImageA')]
    if extended:
        object_implementations += [('metal_mip_composite', 'halo_metal_mip_composite_plan'),
                                   ('xbox_textures', 'xgpu_texture_volume_mip_copy')]
    if fixed_function:
        object_implementations.append(('metal_fixed_function', 'metal_fixed_function_pack_unlit_immediate'))
    for name, symbol in object_implementations:
        path = f'build/macos-metal/guest/obj/port/linux/src/{name}.o'
        object_symbols, obj_command = record_command(output, name + '-symbols',
            [str(LLVM_NM), '--extern-only', path])
        compile_text, compile_command = record_command(output, name + '-compile-command',
            ['ninja', '-t', 'commands', path])
        symbols = (symbol,)
        if name == 'metal_fixed_function':
            symbols += ('metal_fixed_function_vertex_to_msl',)
        implementation_checks(name, symbols, object_symbols, guest_symbols, compile_text)
        compiled[name] = {'object': describe(ROOT / path), 'symbol': symbol,
                          'linked_in_guest': True, 'native_ilp32_flags': True}
        if name == 'metal_fixed_function':
            compiled[name]['additional_linked_symbols'] = list(symbols[1:])
        commands.extend((obj_command, compile_command))
    original_global = None
    if typed_depth:
        original_object = 'build/macos-metal/guest/obj/source/rasterizer/rasterizer.o'
        original_symbols, original_command = record_command(output, 'original-rasterizer-symbols',
            [str(LLVM_NM), '--extern-only', original_object])
        for symbols in (original_symbols, guest_symbols):
            if not re.search(r'\b[BbDdRr]\s+_?rasterizer_globals\s*$', symbols, re.M):
                raise ValueError('Original float-Z global is not linked in the native guest')
        original_global = {'object': describe(ROOT / original_object), 'symbol': 'rasterizer_globals',
                           'field': 'floating_point_zbuffer', 'verified_original_byte_offset': 60,
                           'linked_in_guest': True}
        commands.append(original_command)
    for item in bindings + evidence_bindings:
        if describe(ROOT / item['path']) != item:
            raise ValueError('Build input changed while recording proof: ' + item['path'])
    if execution_path.read_bytes() != execution_bytes or describe(log_path) != log:
        raise ValueError('Observed build execution changed during proof')
    result = {
        'schema_version': 1, 'kind': 'native_batched_guest_host_build', 'passed': True,
        'texture_contract': texture_contract,
        'actual_build_tool_exit': execution['returncode'],
        'execution': describe(output / 'execution.json'),
        'source_bindings': bindings, 'evidence_bindings': evidence_bindings,
        'source_snapshot': relative(output / 'snapshot'),
        'reference_build': describe(reference_path), 'unchanged_backend_abi_transport': unchanged_checks,
        'no_angle_gl_linkage_or_imports': True, 'native_guest_graph': graph,
        'native_compiled_objects': compiled, 'read_only_commands': commands,
        'original_depth_global': original_global,
        'build_log_sha256': digest((output / 'build.log').read_bytes()),
        'linkage_sha256': digest((output / 'linkage.stdout').read_bytes()),
        'producer': describe(Path(__file__)),
        'gameplay_gate': False, 'gpu_alpha_border_gate': False,
        'gpu_volume_gate': False, 'original_water_gate': False, 'gpu_depth_replacement_gate': False,
        'gpu_volume_colour_border_gate': False,
        'performance_improvement_gate': False,
        'scope': 'Actual native guest/host build and linkage only; live execution and batching fidelity require separate proof.',
    }
    if fixed_function:
        result['fixed_function'] = True
    write_new(output / 'result.json', (json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps({'result': describe(output / 'result.json'), 'bindings': len(bindings),
                      'no_angle_gl_linkage_or_imports': True}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execution', type=Path, required=True)
    parser.add_argument('--reference', type=Path,
        default=ROOT / 'build/macos-metal/live-alpha-border-build-proof/result.json')
    parser.add_argument('--texture-contract', choices=('original', 'copy-volume', 'copy-volume-depth', 'copy-volume-depth-border'), default='original',
        help='Explicitly bind the additive rendered-mip copy and authored-volume implementations')
    parser.add_argument('--fixed-function', action='store_true',
        help='Additionally bind the bounded unlit fixed-function sources and linked ILP32 guest object')
    args = parser.parse_args()
    prepare(args.output.resolve(), args.execution.resolve(), args.reference.resolve(), args.texture_contract,
            fixed_function=args.fixed_function)


if __name__ == '__main__':
    main()
