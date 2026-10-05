"""Bind an already completed startup smoke to its unchanged frozen build."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SYMBOL = re.compile(r'(?<![A-Za-z0-9])_?(?:gl[A-Z]|egl[A-Z]|host_gl_|hostgl_|host_sdl_gl_|SDL_GL_)')
FORBIDDEN_LINK = re.compile(r'ANGLE|libEGL|libGLES|OpenGL\.framework', re.I)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def desc(path):
    # Preserve the logical diagnostic path for read-only map symlinks into
    # the primary checkout; hash the actual bytes through that same path.
    return {'path': str(path.absolute().relative_to(ROOT)), 'sha256': sha(path)}


def write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def freeze_startup(folder, build_proof, visually_inspected, artifact_revision='', map_name='bloodgulch'):
    target = folder / 'result.json'
    if target.exists():
        raise ValueError('Result exists; preserve historical reports')
    if artifact_revision and not re.fullmatch(r'[A-Za-z0-9_-]{1,20}', artifact_revision):
        raise ValueError('Invalid proof artifact revision')
    artifact_prefix = 'startup' + ('-' + artifact_revision if artifact_revision else '')
    plan = json.loads((folder / 'launch-plan.json').read_text())
    execution = json.loads((folder / 'execution.json').read_text())
    build = json.loads(build_proof.read_text())
    if build.get('passed') is not True or build.get('actual_build_tool_exit') != 0:
        raise ValueError('Frozen build did not report actual successful compilation')
    snapshot = build_proof.parent / 'snapshot'
    for item in build['source_bindings']:
        if sha(snapshot / item['path']) != item['sha256']:
            raise ValueError('Frozen source/binary changed: ' + item['path'])
    bindings = {item['path']: item['sha256'] for item in build['source_bindings']}
    for field, original in (('host', 'build/macos-metal/halo'),
                            ('guest', 'build/macos-metal/halo_guest.elf')):
        if sha(Path(plan[field])) != bindings[original]:
            raise ValueError('Executed binary does not match frozen build: ' + field)
    config_path = folder / 'saves/config.toml'
    if sha(config_path) != plan['config_sha256']:
        raise ValueError('Startup configuration changed after launch')
    config = tomllib.loads(config_path.read_text())
    log_path = folder / 'launch.log'
    log = log_path.read_text()
    frame_records = [dict(zip(('frame', 'original_draws', 'texture_resources', 'programs'),
        map(int, values))) for values in re.findall(
        r'Native frame (\d+): (\d+) original draws, (\d+) texture resources, (\d+) programs', log)]
    if not frame_records:
        raise ValueError('No actual original-game draw statistics')
    batch_records = [dict(zip(('first_frame', 'last_frame', 'batches', 'commands', 'bytes',
                              'host_submit_microseconds', 'largest_packet_bytes'), map(int, values)))
        for values in re.findall(r'Native submissions frames (\d+)-(\d+): (\d+) batches, '
            r'(\d+) commands, (\d+) bytes, (\d+) host-submit us, largest (\d+) bytes', log)]
    depth_program_lines = [line for line in log.splitlines()
                           if 'Native original D24 depth program ' in line]
    volume_border_program_lines = [line for line in log.splitlines()
                                   if 'Native original volume border program ' in line]
    guest_exits = re.findall(r'Game exited \((-?\d+)\)', log)
    guest_exit = int(guest_exits[-1]) if guest_exits else None
    failures = [line for line in log.splitlines() if 'Native Metal:' in line and ' failed (' in line]
    api_errors = [line for line in log.splitlines() if re.search(
        r'Validation Error|failed assertion|Assertion failed|command buffer was aborted', line, re.I)]
    api_enabled = 'Metal API Validation Enabled' in log
    if not api_enabled or plan['environment_overrides'].get('MTL_DEBUG_LAYER') != '1':
        raise ValueError('Metal API validation was not enabled in this run')
    game_resolution = re.findall(r'screen: (\d+)x(\d+) drawn at (\d+)x(\d+)', log)
    drawable = re.findall(r'Metal drawable (\d+)x(\d+) \(([^)]+)\)', log)
    if len(game_resolution) != 1 or len(drawable) != 1:
        raise ValueError('Ambiguous actual game/drawable dimensions')
    bmps = sorted((folder / 'captures').glob('frame*.bmp'))
    if not bmps:
        raise ValueError('No captured original-game image')
    last_bmp = bmps[-1]
    png = folder / f'native-{map_name}-final.png'
    if not png.exists():
        # The failed run already has an independently retained PNG of its
        # last captured frame; use it rather than creating another copy.
        png = last_bmp.with_suffix('.png')
    bmp_pixels = Image.open(last_bmp).convert('RGB')
    png_pixels = Image.open(png).convert('RGB')
    if bmp_pixels.size != png_pixels.size or bmp_pixels.tobytes() != png_pixels.tobytes():
        raise ValueError('Lossless image conversion changed original RGB pixels')
    if bmp_pixels.size != (640, 480):
        raise ValueError('Unexpected game screenshot size')
    if visually_inspected is not True:
        raise ValueError('World/weapon/HUD image observation has not been provided')
    init = folder / 'data/init.txt'
    if init.read_text() != f'game_variant slayer\nmap_name {map_name}\n':
        raise ValueError('Original local startup commands differ from the requested map')
    host = Path(plan['host'])
    linkage = subprocess.run(['otool', '-L', str(host)], capture_output=True, check=True)
    symbols = subprocess.run(['nm', '-u', str(host)], capture_output=True, check=True)
    if FORBIDDEN_LINK.search(linkage.stdout.decode()) or FORBIDDEN_SYMBOL.search(symbols.stdout.decode()):
        raise ValueError('Executed native host has GL/ANGLE linkage or boundary symbols')
    imports = '\n'.join((snapshot / path).read_text() for path in (
        'build/macos-metal/host/host_import_table.c', 'port/macos/metal_imports.list'))
    if FORBIDDEN_SYMBOL.search(imports):
        raise ValueError('Executed frozen native import table includes GL')
    linkage_path = folder / (artifact_prefix + '-linkage.txt')
    symbols_path = folder / (artifact_prefix + '-host-undefined.txt')
    write_new(linkage_path, linkage.stdout)
    write_new(symbols_path, symbols.stdout)
    frozen_producer = folder / (artifact_prefix + '-proof-source.py')
    write_new(frozen_producer, Path(__file__).read_bytes())
    artifacts = [folder / 'launch-plan.json', folder / 'execution.json', log_path, config_path, init,
                 folder / f'data/maps/{map_name}.map', png,
                 linkage_path, symbols_path, frozen_producer, *bmps]
    artifact_bindings = {desc(path)['path']: sha(path) for path in artifacts}
    passed = (execution['observed_host_exit_code'] == 0 and execution['timeout'] is False
              and guest_exit == 0 and not failures and not api_errors)
    repairs = build_proof.parent / 'snapshot-permission-repair.json'
    result = {
        'schema_version': 1, 'kind': f'actual_native_game_{map_name}_startup_smoke',
        'map_name': map_name,
        'complete': True, 'passed': passed,
        'observed_host_exit_code': execution['observed_host_exit_code'],
        'guest_exit_log': guest_exit, 'timed_out': execution['timeout'],
        'elapsed_seconds': execution['elapsed_seconds'],
        'statistics': frame_records, 'last_statistics_frame': frame_records[-1]['frame'],
        'native_original_draws': frame_records[-1]['original_draws'],
        'native_texture_resources': frame_records[-1]['texture_resources'],
        'native_original_programs': frame_records[-1]['programs'],
        'submission_diagnostics': batch_records,
        'original_d24_program_diagnostics': depth_program_lines,
        'original_volume_border_program_diagnostics': volume_border_program_lines,
        'native_renderer_failures': failures, 'gpu_api_validation_enabled': api_enabled,
        'gpu_api_validation_errors': api_errors,
        'game_resolution': list(map(int, game_resolution[0])),
        'presented_drawable': {'width': int(drawable[0][0]), 'height': int(drawable[0][1]),
                              'mode': drawable[0][2]},
        'world_weapon_hud_radar_pixels_visually_inspected': visually_inspected,
        'last_capture': desc(last_bmp), 'inspection_image': desc(png),
        'image_rgb_pixels_preserved': True,
        'no_angle_gl_linkage_or_imports': True,
        'executed_binary_hashes_match_frozen_build': True,
        'executed_source_bindings': build['source_bindings'],
        'frozen_source_binary_snapshot': str(snapshot.relative_to(ROOT)),
        'frozen_build_proof': desc(build_proof),
        'frozen_binding_count_verified': len(build['source_bindings']),
        'build_metadata_repairs': [desc(repairs)] if repairs.exists() else [],
        'controlled_inputs': {'all_bindings_disabled': all(value == '' for value in config['bindings'].values()),
                              'mouse_sensitivity': config['input']['mouse_sensitivity'],
                              'scripted_debug_input': config['debug']['test_input']},
        'original_presentation_settings': {key: config['display'][key] for key in
            ('vsync', 'interpolation', 'high_res_hud', 'direct_camera')},
        'network_online': config['network']['online'],
        'artifacts': artifact_bindings, 'producer': desc(Path(__file__)),
        'frozen_producer': desc(frozen_producer),
        'preparation_attempt_history': [desc(path) for path in
            sorted(folder.glob('startup-proof-preparation-attempt*.json'))],
        'proof_python': {'path': sys.executable, 'sha256': sha(Path(sys.executable))},
        'startup_smoke_gate': passed, 'interactive_input_playtest_gate': False,
        'full_game_gate': False, 'working_port_pixel_parity_gate': False,
        'original_xbox_physical_fidelity_gate': False,
        'alpha_border_ideal_byte_precision_gate': False, 'cpu_query_timing_gate': False,
        'performance_improvement_gate': False,
        'scope': f'Bounded actual native local {map_name} startup with API validation. '
                 'Completed-run counters are diagnostic only; no timed benchmark, manual playtest, '
                 'image parity, unsupported-state coverage, or full-game completion claim.',
    }
    if failures:
        result['failure_scope'] = 'The recorded native renderer failures and nonzero host exit are retained explicitly; startup gate remains false.'
    # Revalidate immutable inputs and original snapshot after reading images
    # and linkage; never replace a recorded digest with a current substitute.
    for path, expected in artifact_bindings.items():
        if sha(ROOT / path) != expected:
            raise ValueError('Startup artifact changed during proof: ' + path)
    for item in build['source_bindings']:
        if sha(snapshot / item['path']) != item['sha256']:
            raise ValueError('Frozen build changed during proof')
    write_new(target, (json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps({'result': desc(target), 'passed': passed,
                      'last_frame': frame_records[-1]['frame'], 'draws': frame_records[-1]['original_draws']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--build-proof', type=Path, required=True)
    parser.add_argument('--visually-inspected', action='store_true')
    parser.add_argument('--artifact-revision', default='')
    parser.add_argument('--map', dest='map_name', choices=('bloodgulch', 'damnation'), default='bloodgulch')
    args = parser.parse_args()
    freeze_startup(args.run.resolve(), args.build_proof.resolve(), args.visually_inspected,
                   args.artifact_revision, args.map_name)


if __name__ == '__main__':
    main()
