#!/usr/bin/env python3
"""Prepare and run isolated A/B native original-game batching measurements.

Preparation never launches the game. Execute a prepared folder explicitly once
with --execute-prepared. Timings describe a stationary local Blood Gulch game;
they are not a full-game performance or original-Xbox fidelity gate.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BLOODGULCH_SHA = '50fe52406f075d975e24100a65b26ff696458023dd3509878953052ab0ef858f'
NTSC_BUILD = '01.10.12.2276'
START_FRAME, END_FRAME, EXIT_SECONDS = 120, 600, 45.0
SOURCE_FILES = [
    'port/linux/src/d3d8_metal.c', 'port/linux/src/metal_guest_transport.c',
    'port/linux/src/metal_guest_transport.h', 'port/linux/src/metal_packet_room.c',
    'port/linux/src/metal_packet_room.h', 'port/linux/src/metal_draw_state.c',
    'port/linux/src/metal_draw_state.h', 'port/linux/src/metal_vertex_fetch.c',
    'port/linux/src/metal_vertex_fetch.h', 'port/linux/src/nv2a_vsh.c',
    'port/linux/src/nv2a_psh.c', 'port/linux/src/xgpu.h', 'port/linux/src/xgpu_msl.h',
    'port/linux/src/xbox_textures.c', 'port/linux/src/xbox_xapi.c', 'port/linux/src/sdl_platform.c',
    'port/linux/src/port_config.c', 'port/linux/src/input_bindings.def',
    'port/linux/src/xinput_sdl.c', 'port/macos/host/host_main.c',
    'port/macos/host/host_sdl.c', 'port/macos/host/host_metal.mm',
    'port/macos/host/metal_draw_encoder.mm', 'port/macos/host/metal_draw_encoder.h',
    'port/macos/include/halo_metal_abi.h', 'source/cseries/cseries.h',
    'source/game/game_time.c', 'source/main/main.c', 'configure.py',
    'tools/macos_build.py', 'tools/android_build.py',
]
FRAME = re.compile(r'Native frame (\d+): (\d+) original draws, (\d+) texture resources, (\d+) programs')
SUBMISSIONS = re.compile(r'Native submissions frames (\d+)-(\d+): (\d+) batches, (\d+) commands, '
                         r'(\d+) bytes, (\d+) host-submit us, largest (\d+) bytes')
SCREEN = re.compile(r'screen: (\d+)x(\d+) drawn at ([0-9.]+)x([0-9.]+)')
DRAWABLE = re.compile(r'Metal drawable (\d+)x(\d+) \(([^)]+)\)')
FAULT = re.compile(r'ASSERTION FAILED|guest abort|Native Metal: .* failed|SIGSEGV|EXCEPTION halt in', re.I)
SETTINGS = {
    'display': dict(screen_width=640,window_scale=2,fullscreen=False,vsync=False,
                    interpolation=False,direct_camera=False,high_res_hud=False),
    'audio': dict(enabled=False),
    'network': dict(online=False,allow_upnp=False,join_from_clipboard=False),
    'update': dict(auto=False),
    'discord': dict(application_id=''),
    'debug': dict(exit_after=EXIT_SECONDS,gpu_stats=True,screenshot_every=0,
                  screenshot_directory='',test_input='',hidden_window=False,null_renderer=False,
                  update_answer='no',telnet_console=False,network_test='',gpu_trace_frame=-1,
                  gpu_trace_constants=False,gpu_skip_vertex_shaders='',gpu_dump_shaders='',
                  gpu_debug_expression='',gpu_debug_texture0=False,gpu_debug_flat=False,
                  texture_log=False,texture_dump_directory='',texture_no_cache=False,gl_debug=False),
    'paths': dict(data='',saves=''),
    # Benchmark-only input controls. Zero/negative sensitivity restores1 in
    # the original native input code; a tiny positive value suppresses motion.
    'input': dict(mouse_sensitivity=1e-20),
    'bindings': {name:'' for name in (
        'move_forward','move_back','move_left','move_right','dpad_up','dpad_down','dpad_left','dpad_right',
        'a','b','x','y','start','select','crouch','zoom','white','black','left_trigger','right_trigger',
        'console','release_mouse')},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def toml_scalar(value):
    if isinstance(value,bool):
        return str(value).lower()
    if isinstance(value,str):
        return json.dumps(value,ensure_ascii=False)
    if isinstance(value,int):
        return str(value)
    if isinstance(value,float):
        require(math.isfinite(value),'Template configuration contains a nonfinite number')
        return repr(value)
    if isinstance(value,list):
        return '['+', '.join(toml_scalar(v) for v in value)+']'
    raise ValueError('Unsupported template TOML value type: '+type(value).__name__)


def controlled_config(template):
    parsed = tomllib.loads(template)
    for section, values in SETTINGS.items():
        require(isinstance(parsed.setdefault(section,{}),dict),'Configuration section is not a table: '+section)
        parsed[section].update(values)
    # Disable any additional template bindings as well, never silently retain
    # a locally customized button during a stationary benchmark.
    for name in parsed['bindings']:
        parsed['bindings'][name]=''
    lines = []
    def table(data, path=()):
        if path:
            lines.extend(['','['+'.'.join(json.dumps(p) for p in path)+']'])
        for key,value in data.items():
            if not isinstance(value,dict):
                lines.append(json.dumps(key)+' = '+toml_scalar(value))
        for key,value in data.items():
            if isinstance(value,dict):
                table(value,(*path,key))
    table(parsed)
    text = '\n'.join(lines)+'\n'
    require(tomllib.loads(text)==parsed,'Controlled configuration does not round-trip')
    return text


def sanitized_environment(data, saves, source=None):
    source = os.environ if source is None else source
    removed = []
    environment = {}
    for key,value in source.items():
        if (key.startswith(('HALO_','MTL_','METAL_','Malloc')) or
                key in ('DYLD_INSERT_LIBRARIES','ASAN_OPTIONS','UBSAN_OPTIONS','LLVM_PROFILE_FILE')):
            removed.append(key)
        else:
            environment[key]=value
    overrides=dict(HALO_DATA_ROOT=str(data),HALO_SAVE_ROOT=str(saves),HALO_WINDOWED='1')
    environment.update(overrides)
    return environment, dict(added=overrides,removed_names=sorted(removed))


def tree_hashes(directory):
    records = {}
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(),'Save template must have no symlinks: '+str(path))
        if path.is_file():
            records[str(path.relative_to(directory))]=sha(path)
    return records


def original_maps(data):
    records = {}
    for name in ('ui','bloodgulch'):
        path=(data/'maps'/(name+'.map')).resolve(strict=True)
        with path.open('rb') as stream:
            header=stream.read(2048)
        require(len(header)==2048 and header[:4]==b'daeh' and header[2044:]==b'toof',
                'Original Xbox cache header missing: '+str(path))
        require(struct.unpack_from('<I',header,4)[0]==5,'Xbox version5 cache required: '+str(path))
        build=header[64:96].split(b'\0',1)[0].decode('ascii')
        require(build==NTSC_BUILD,'Original NTSC2276 data required: '+str(path))
        digest=sha(path)
        if name=='bloodgulch':
            require(digest==BLOODGULCH_SHA,'Blood Gulch differs from the retained original stock cache')
        records[str(path)]=dict(sha256=digest,bytes=path.stat().st_size,build=build)
    return records


def validate_paths(a_host,a_guest,b_host,b_guest,data,template,config,output):
    require(not output.exists(),'Output must not exist; prior runs are preserved: '+str(output))
    for path in (a_host,b_host):
        require(path.is_file() and os.access(path,os.X_OK),'Host must be an executable file: '+str(path))
    for path in (a_guest,b_guest,config):
        require(path.is_file(),'Required file missing: '+str(path))
    require(data.is_dir() and (data/'maps').is_dir(),'Original data root needs a maps directory')
    require(template.is_dir(),'Template saves directory is missing')
    for source in (data,template):
        require(not output.is_relative_to(source),'Output cannot be nested in an input tree: '+str(source))
    tree_hashes(template)


def prepare(args):
    paths={name:Path(getattr(args,name)).expanduser().resolve(strict=True) for name in
           ('a_host','a_guest','b_host','b_guest','data_root','template_saves')}
    config=(args.template_config or paths['template_saves']/'config.toml').expanduser().resolve(strict=True)
    output=args.output.expanduser().resolve()
    validate_paths(paths['a_host'],paths['a_guest'],paths['b_host'],paths['b_guest'],
                   paths['data_root'],paths['template_saves'],config,output)
    require(1<=args.repetitions<=16,'Repetitions must be1 through16')
    require(45<args.timeout<=180,'External timeout must be greater than45 and at most180 seconds')
    binding_names=set(re.findall(r'^BINDING\((\w+),',(ROOT/'port/linux/src/input_bindings.def').read_text(),re.M))
    require(binding_names==set(SETTINGS['bindings']),'Binding defaults changed; update benchmark controls explicitly')
    maps=original_maps(paths['data_root'])
    settings=controlled_config(config.read_text())
    template_hashes=tree_hashes(paths['template_saves'])
    bindings={str(path):sha(path) for name,path in paths.items() if name.endswith(('host','guest'))}
    bindings[str(config)]=sha(config)
    bindings[str(Path(__file__).resolve())]=sha(Path(__file__).resolve())
    source_roots={name:Path(getattr(args,name.lower()+'_source_root') or ROOT).expanduser().resolve(strict=True)
                  for name in ('A','B')}
    sources={}
    for variant,root in source_roots.items():
        sources[variant]=dict(root=str(root),files={str(root/name):sha(root/name) for name in SOURCE_FILES
                                                 if (root/name).is_file()})
        require(sources[variant]['files'],'No renderer source inputs found in '+str(root))
        bindings.update(sources[variant]['files'])
    output.mkdir(parents=True,exist_ok=False)
    variants={}
    for variant in ('A','B'):
        folder=output/'binaries'/variant
        folder.mkdir(parents=True)
        for kind,target in (('host','halo'),('guest','halo_guest.elf')):
            original=paths[variant.lower()+'_'+kind]
            shutil.copy2(original,folder/target)
            require(sha(folder/target)==bindings[str(original)],'Binary changed during retention')
        variants[variant]=dict(host=str(folder/'halo'),guest=str(folder/'halo_guest.elf'),
                               supplied_host=str(paths[variant.lower()+'_host']),
                               supplied_guest=str(paths[variant.lower()+'_guest']))
    runs=[]
    for repeat in range(args.repetitions):
        for variant in ('A','B','B','A'):
            name=f'run-{len(runs)+1:02d}-{variant}'
            folder=output/name;folder.mkdir()
            saves=folder/'saves'
            shutil.copytree(paths['template_saves'],saves)
            require(tree_hashes(saves)==template_hashes,'Save clone differs from template')
            (saves/'config.toml').write_text(settings)
            data=folder/'data';data.mkdir()
            (data/'maps').symlink_to((paths['data_root']/'maps').resolve(),target_is_directory=True)
            if (paths['data_root']/'sounds').is_dir():
                (data/'sounds').symlink_to((paths['data_root']/'sounds').resolve(),target_is_directory=True)
            (data/'init.txt').write_text('game_variant slayer\nmap_name bloodgulch\n')
            _env,env_binding=sanitized_environment(data,saves)
            runs.append(dict(name=name,variant=variant,repetition=repeat+1,folder=str(folder),
                command=[variants[variant]['host'],variants[variant]['guest']],
                config_sha256=sha(saves/'config.toml'),init_sha256=sha(data/'init.txt'),
                saves_initial_sha256=tree_hashes(saves),environment=env_binding))
    for path,digest in bindings.items():
        require(sha(path)==digest,'Input changed during preparation: '+path)
    require(tree_hashes(paths['template_saves'])==template_hashes,'Template changed during preparation')
    frozen={str(p):sha(p) for p in output.rglob('*') if p.is_file()}
    plan=dict(schema_version=1,kind='native_live_batch_benchmark',complete=False,executed=False,passed=False,
        variants=variants,source_snapshots=sources,source_binary_correlation_verified=False,
        bindings_sha256=bindings,prepared_files_sha256=frozen,map_bindings=maps,
        template_saves=str(paths['template_saves']),template_sha256=template_hashes,
        settings=SETTINGS,timeout_seconds=args.timeout,runs=runs,
        measurement=dict(start_frame=START_FRAME,end_frame=END_FRAME,clock='monotonic_ns at unbuffered stderr line arrival'),
        limits=['Stationary local original Blood Gulch workload only; no full-game performance gate.',
                'Original30Hz game simulation and presentation throttle remain enabled.',
                'Benchmark-only tiny positive mouse sensitivity and empty keyboard/mouse bindings suppress incidental input.',
                'Physical gamepads and native pause/back shortcuts are not disabled; supply no input during a run.',
                'Exact camera equivalence is not observed by this harness; verify separately.',
                'Source hashes describe supplied snapshots, not independently proved source-to-binary builds.',
                'Host-submit microseconds include synchronous executor work/waits; they are not GPU execution time.',
                'Driver/library caches are not cleared; A/B/B/A ordering limits warm-cache order effects.'])
    write_json(output/'prepared.json',plan)
    print(json.dumps(dict(prepared=str(output/'prepared.json'),runs=len(runs),executed=False),indent=2))
    return plan


class Observation:
    def __init__(self):
        self.frames=[];self.submissions=[];self.screen=[];self.drawable=[];self.guest_exits=[]
        self.faults=[];self.native_backend=False;self.errors=[]

    def line(self,text,now):
        match=FRAME.search(text)
        if match:
            frame,draws,textures,programs=map(int,match.groups())
            if self.frames and (frame<=self.frames[-1]['frame'] or draws<self.frames[-1]['draws']):
                self.errors.append('Frame/draw statistics are duplicated or regress')
            self.frames.append(dict(frame=frame,draws=draws,textures=textures,programs=programs,monotonic_ns=now))
        match=SUBMISSIONS.search(text)
        if match:
            self.submissions.append(dict(zip(('first_frame','last_frame','batches','commands','bytes','host_submit_us','largest_bytes'),
                                             map(int,match.groups())),monotonic_ns=now))
        match=SCREEN.search(text)
        if match:
            self.screen.append(dict(width=int(match[1]),height=int(match[2]),drawn_width=float(match[3]),drawn_height=float(match[4])))
        match=DRAWABLE.search(text)
        if match:
            self.drawable.append(dict(width=int(match[1]),height=int(match[2]),mode=match[3]))
        match=re.search(r'Game exited \((-?\d+)\)',text)
        if match:
            self.guest_exits.append(int(match[1]))
        if 'Native Metal guest command interface:' in text:
            self.native_backend=True
        if FAULT.search(text):
            self.faults.append(text)

    def summary(self):
        by_frame={r['frame']:r for r in self.frames}
        expected=list(range(START_FRAME,END_FRAME+1,60))
        require(all(f in by_frame for f in expected),'Required frame120 through600 checkpoints were not all observed')
        intervals=[]
        for first,last in zip(expected,expected[1:]):
            a,b=by_frame[first],by_frame[last]
            seconds=(b['monotonic_ns']-a['monotonic_ns'])/1e9
            require(seconds>0,'Nonpositive monotonic measurement interval')
            intervals.append(dict(first_frame=first,last_frame=last,wall_seconds=seconds,fps=60/seconds,
                                  original_draws=b['draws']-a['draws']))
        elapsed=(by_frame[END_FRAME]['monotonic_ns']-by_frame[START_FRAME]['monotonic_ns'])/1e9
        return dict(wall_seconds=elapsed,fps=(END_FRAME-START_FRAME)/elapsed,intervals=intervals,
                    original_draws=by_frame[END_FRAME]['draws']-by_frame[START_FRAME]['draws'],
                    start=by_frame[START_FRAME],end=by_frame[END_FRAME],
                    submission_intervals=[r for r in self.submissions if START_FRAME<r['last_frame']<=END_FRAME])


def verify_plan(plan, initial=False):
    for path,digest in plan['bindings_sha256'].items():
        require(sha(path)==digest,'Source/binary/template config changed: '+path)
    for path,record in plan['map_bindings'].items():
        require(sha(path)==record['sha256'],'Original map changed: '+path)
    require(tree_hashes(Path(plan['template_saves']))==plan['template_sha256'],'Template save files changed')
    for path,digest in plan['prepared_files_sha256'].items():
        if initial or '/binaries/' in path:
            require(sha(path)==digest,'Prepared input changed: '+path)


def execute_one(run,timeout):
    folder=Path(run['folder']);saves=folder/'saves';data=folder/'data'
    require(not (folder/'execution-started.json').exists(),'Run already started; prior evidence is preserved')
    require(sha(saves/'config.toml')==run['config_sha256'] and sha(data/'init.txt')==run['init_sha256'],
            'Run configuration/startup input changed')
    require(tree_hashes(saves)==run['saves_initial_sha256'],'Fresh save clone changed before run')
    environment,env_binding=sanitized_environment(data,saves)
    started=time.monotonic_ns()
    write_json(folder/'execution-started.json',dict(started_monotonic_ns=started,command=run['command'],environment=env_binding))
    observation=Observation();timed_out=False;launch_error=None
    process=None
    with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr, \
            (folder/'arrivals.jsonl').open('w') as arrivals:
        try:
            process=subprocess.Popen(run['command'],cwd=folder,env=environment,stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,start_new_session=True)
            with selectors.DefaultSelector() as selector:
                buffers={}
                for name,pipe,log in (('stdout',process.stdout,stdout),('stderr',process.stderr,stderr)):
                    os.set_blocking(pipe.fileno(),False)
                    selector.register(pipe,selectors.EVENT_READ,(name,log));buffers[name]=bytearray()
                deadline=time.monotonic()+timeout
                while selector.get_map():
                    remaining=deadline-time.monotonic()
                    if remaining<=0:
                        timed_out=True
                        os.killpg(process.pid,signal.SIGTERM)
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
                        deadline=time.monotonic()+3
                    for key,_mask in selector.select(min(.2,max(.001,remaining))):
                        name,log=key.data
                        raw=os.read(key.fileobj.fileno(),65536)
                        now=time.monotonic_ns()
                        if not raw:
                            selector.unregister(key.fileobj);continue
                        log.write(raw);log.flush();buffers[name].extend(raw)
                        while b'\n' in buffers[name]:
                            line,_sep,rest=buffers[name].partition(b'\n');buffers[name]=bytearray(rest)
                            text=line.decode('utf8',errors='replace').rstrip('\r')
                            arrivals.write(json.dumps(dict(stream=name,monotonic_ns=now,text=text))+'\n');arrivals.flush()
                            observation.line(text,now)
                for name,raw in buffers.items():
                    if raw:
                        text=raw.decode('utf8',errors='replace')
                        arrivals.write(json.dumps(dict(stream=name,monotonic_ns=time.monotonic_ns(),text=text,partial=True))+'\n')
            process.wait(timeout=3)
        except Exception as error:
            launch_error=str(error)
            if process and process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
    result=dict(name=run['name'],variant=run['variant'],complete=True,passed=False,
        observed_host_exit_code=process.returncode if process else None,timed_out=timed_out,
        elapsed_seconds=(time.monotonic_ns()-started)/1e9,launch_error=launch_error,
        guest_exit_logs=observation.guest_exits,native_backend=observation.native_backend,
        screen=observation.screen,drawable=observation.drawable,faults=observation.faults,
        statistics_errors=observation.errors,frames=observation.frames,submissions=observation.submissions)
    try:
        result['measurement']=observation.summary()
    except ValueError as error:
        result['measurement_error']=str(error)
    screen_ok=bool(observation.screen) and all(r['width']==640 and r['height']==480 and
        r['drawn_width']==640 and r['drawn_height']==480 for r in observation.screen)
    window_ok=bool(observation.drawable) and all(r['mode']=='windowed' for r in observation.drawable)
    result['passed']=(process is not None and process.returncode==0 and not timed_out and not launch_error and
        observation.guest_exits==[0] and observation.native_backend and not observation.errors and not observation.faults and
        screen_ok and window_ok and 'measurement' in result)
    result['requested_render_gate']=screen_ok;result['requested_window_gate']=window_ok
    result['files_sha256']={str(p):sha(p) for p in folder.rglob('*') if p.is_file()}
    write_json(folder/'result.json',result)
    return result


def comparison(runs):
    accepted=[r for r in runs if r.get('passed')]
    variants={variant:[r for r in accepted if r['variant']==variant] for variant in ('A','B')}
    result={}
    for variant,values in variants.items():
        fps=[r['measurement']['fps'] for r in values]
        result[variant]=dict(runs=len(values),median_fps=statistics.median(fps) if fps else None,
                            min_fps=min(fps) if fps else None,max_fps=max(fps) if fps else None)
    signatures=[]
    for r in accepted:
        m=r['measurement']
        signatures.append((m['original_draws'],m['start']['textures'],m['end']['textures'],
                           m['start']['programs'],m['end']['programs'],
                           tuple((d['width'],d['height'],d['mode']) for d in r['drawable'])))
    result['exact_workload_count_and_resource_parity']=bool(signatures) and all(s==signatures[0] for s in signatures)
    if all(result[v]['median_fps'] for v in ('A','B')):
        result['median_throughput_change_percent']=(result['B']['median_fps']/result['A']['median_fps']-1)*100
    return result


def execute(output):
    output=output.expanduser().resolve(strict=True)
    require(not (output/'result.json').exists(),'Benchmark already attempted; choose a fresh prepared folder')
    path=output/'prepared.json';plan=json.loads(path.read_text())
    verify_plan(plan,initial=True)
    result=dict(plan,executed=True,complete=False,passed=False,prepared_sha256=sha(path),run_results=[])
    try:
        for run in plan['runs']:
            verify_plan(plan)
            print('Running '+run['name'],flush=True)
            observed=execute_one(run,plan['timeout_seconds'])
            result['run_results'].append(observed)
            verify_plan(plan)
            result['comparison']=comparison(result['run_results'])
            write_json(output/'progress.json',result)
            if not observed['passed']:
                raise ValueError('Run failed or lacks required measurement: '+run['name'])
        result['complete']=True
        result['passed']=all(r['passed'] for r in result['run_results']) and result['comparison']['exact_workload_count_and_resource_parity']
    except Exception as error:
        result['failure']=str(error)
    result['camera_equivalence_observed']=False
    result['full_game_performance_gate']=False
    write_json(output/'result.json',result)
    print(json.dumps(dict(passed=result['passed'],complete=result['complete'],
                         comparison=result.get('comparison'),result=str(output/'result.json')),indent=2))
    return result['passed']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute-prepared',action='store_true')
    for name in ('a-host','a-guest','b-host','b-guest','data-root','template-saves','template-config','a-source-root','b-source-root'):
        parser.add_argument('--'+name,type=Path)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--timeout',type=float,default=75.0)
    args=parser.parse_args()
    try:
        if args.execute_prepared:
            return 0 if execute(args.output) else 1
        for name in ('a_host','a_guest','b_host','b_guest','data_root','template_saves'):
            require(getattr(args,name) is not None,'Preparation requires --'+name.replace('_','-'))
        prepare(args)
        return 0
    except (OSError,ValueError,AssertionError) as error:
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
