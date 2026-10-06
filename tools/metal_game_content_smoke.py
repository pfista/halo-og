#!/usr/bin/env python3
"""Bounded original stock-MP runtime coverage on an immutable native build.

No renderer implementation or fallback lives here. Each map uses a fresh
offline/muted bot run. A successful process does not pass until its saved
nonblack image has been explicitly inspected for world/weapon/HUD content.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import tomllib
from PIL import Image
from metal_poc_export import Cache

ROOT=Path(__file__).resolve().parents[1]
MAPS=ROOT.parent/'pfista-halo-macos/assets/maps'
STOCK=('beavercreek','sidewinder','damnation','ratrace','prisoner','hangemhigh','chillout',
       'carousel','boardingaction','bloodgulch','wizard','putput','longest')
SOURCE_LIST=ROOT/'source/interface/ui_widget_event_handler_functions.c'
BUILD=ROOT/'build/macos-metal/live-volume-colour-build-proof/result.json'
NORMAL=ROOT/'build/macos-metal/native-metal-gameplay-playtest/bloodgulch/saves/config.toml'

def require(ok,text):
    if not ok:raise ValueError(text)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def desc(p):return {'file':str(Path(p).absolute()),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_text())
def new_json(p,value):
    with Path(p).open('x') as f:json.dump(value,f,indent=2);f.write('\n')

def original_names(text):
    pairs=re.findall(r'"levels\\\\test\\\\([a-z0-9]+)\\\\([a-z0-9]+)"',text)
    names=tuple(dict.fromkeys(a for a,b in pairs if a==b))
    require(names==STOCK,'Original multiplayer initializer differs from stock13 whitelist')
    return names

def header_metadata(path):
    with Path(path).open('rb') as f:h=f.read(2048)
    require(len(h)==2048 and h[:4]==b'daeh' and h[2044:]==b'toof','Invalid cache header')
    version,size=struct.unpack_from('<II',h,4);name=h[32:64].split(b'\0')[0].decode('ascii')
    build=h[64:96].split(b'\0')[0].decode('ascii');type_=struct.unpack_from('<H',h,96)[0]
    require(version==5 and type_<=2,'Not an original Xboxv5 scenario cache')
    return dict(name=name,version=version,decoded_size=size,build=build,scenario_type=type_)

def stock_inventory():
    names=original_names(SOURCE_LIST.read_text());mp=[];excluded=[]
    for p in sorted(MAPS.glob('*.map')):
        h=header_metadata(p)
        require(h['name']==p.stem,'Cache filename/header name mismatch')
        if p.stem not in names:
            excluded.append(dict(name=p.stem,category={0:'campaign',1:'nonstock_multiplayer',2:'ui'}[h['scenario_type']],header=h))
    for name in names:
        p=MAPS/(name+'.map');h=header_metadata(p)
        require(h['scenario_type']==1 and h['build']=='01.10.12.2276','Unexpected stock cache provenance')
        cache=Cache(p);tag_id=cache.u32(cache.tag_offset+4);group,offset,tag_name=cache.tag(tag_id)
        require(group=='scnr' and tag_name==f'levels\\test\\{name}\\{name}','Original scenario tag identity mismatch')
        scenario_type=cache.unpack('<h',offset+0x3c)[0]
        require(scenario_type==1,'Stock scenario tag is not multiplayer')
        mp.append(dict(name=name,cache=desc(p),header=h,scenario_tag=tag_name,scenario_tag_id=tag_id,
                       decoded_scenario_type=scenario_type,scenario_type_byte_offset=60))
    require(len(mp)==13,'Stock13 caches unavailable')
    return mp,excluded

def set_key(text,section,key,value):
    pattern=re.compile(r'(?ms)(^\['+re.escape(section)+r'\]\n)(.*?)(?=^\[|\Z)')
    match=pattern.search(text);require(match is not None,'Missing config section '+section)
    body=match[2];item=re.compile(r'(?m)^'+re.escape(key)+r'\s*=.*$')
    require(len(item.findall(body))==1,'Ambiguous config key '+key)
    body=item.sub(key+' = '+value,body)
    return text[:match.start()]+match[1]+body+text[match.end():]

def controlled_config(template,folder,duration):
    require(15<=duration<=20,'Smoke must be bounded15..20seconds')
    result=template
    updates={'audio':{'enabled':'false'},'input':{'mouse_sensitivity':'1e-20'},
      'network':{'online':'false','allow_upnp':'false','join_from_clipboard':'false'},
      'update':{'auto':'false'},'display':{'fullscreen':'false','vsync':'false','interpolation':'false','high_res_hud':'false','direct_camera':'false'},
      'debug':{'test_input':'"bot:0"','exit_after':str(float(duration)),'gpu_stats':'true','screenshot_every':'30',
               'screenshot_directory':json.dumps(str(folder/'captures')),'texture_dump_directory':json.dumps(str(folder/'dumps')),
               'hidden_window':'false','null_renderer':'false'}}
    original=tomllib.loads(template)
    updates['bindings']={key:'""' for key in original['bindings']}
    for section,values in updates.items():
        for key,value in values.items():result=set_key(result,section,key,value)
    validate_config(tomllib.loads(result),folder,duration)
    return result

def validate_config(c,folder,duration):
    require(c['display']['screen_width']==640 and c['display']['window_scale']==2,'Unexpected game/drawable request')
    require(all(c['display'][k] is False for k in ('fullscreen','vsync','interpolation','direct_camera','high_res_hud')),'Presentation override')
    require(not c['audio']['enabled'] and not any(c['bindings'].values()) and c['input']['mouse_sensitivity']==1e-20,'Human input/audio not isolated')
    require(not c['network']['online'] and not c['network']['allow_upnp'] and not c['network']['join_from_clipboard'] and not c['update']['auto'],'Offline configuration violated')
    d=c['debug'];require(d['test_input']=='bot:0' and d['exit_after']==duration and d['gpu_stats'] and d['screenshot_every']==30,'Bounded scripted diagnostics differ')
    require(not d['null_renderer'] and not d['hidden_window'],'No actual visible renderer')
    require(d['screenshot_directory']==str(folder/'captures') and d['texture_dump_directory']==str(folder/'dumps'),'Output paths escape isolated map')
    require(d['gpu_dump_shaders']=='' and not d['gpu_debug_expression'] and not d['gpu_debug_texture0'] and not d['gpu_debug_flat'] and not d['gpu_skip_vertex_shaders'],'Shader fallback/debug override')

def frozen_build(build_path,current=False):
    b=read(build_path);require(b['passed'] and b['actual_build_tool_exit']==0,'Native build unsuccessful')
    require(sha(build_path)=='f69b523befbc90fba17015cf4d2309bc4769a0d16059f6bc229e946b6f30d162','Unexpected frozen native build')
    snapshot=ROOT/b['source_snapshot'];records=[]
    for x in b['source_bindings']+b['evidence_bindings']:
        require(sha(snapshot/x['path'])==x['sha256'],'Frozen build binding changed '+x['path'])
        digest=sha(ROOT/x['path']);equal=digest==x['sha256']
        if current:require(equal,'Current production source drift before preparation '+x['path'])
        records.append({**x,'snapshot':str(snapshot/x['path']),'current_sha256':digest,'current_matches':equal})
    require(len(records)==50,'Incomplete build bindings')
    host=snapshot/'build/macos-metal/halo';guest=snapshot/'build/macos-metal/halo_guest.elf'
    require(stat.S_IMODE(host.stat().st_mode)==0o755,'Frozen host is not executable')
    return b,host,guest,records

def prepare(out,duration):
    require(not out.exists(),'Fresh output required; preserve historical coverage');out.mkdir(parents=True)
    b,host,guest,bindings=frozen_build(BUILD,current=True);cases,excluded=stock_inventory()
    sources=[Path(__file__),ROOT/'tools/test_metal_game_content_smoke.py',ROOT/'tools/metal_poc_export.py',SOURCE_LIST,
             ROOT/'source/scenario/scenario_definitions.h',ROOT/'source/cache/cache_files_windows.c',NORMAL]
    source_records=[]
    for p in sources:
        target=out/'source-snapshot'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target);require(sha(p)==sha(target),'Source changed during preparation')
        source_records.append(dict(original=str(p),snapshot=str(target),sha256=sha(p)))
    plans=[]
    for c in cases:
        folder=out/c['name'];(folder/'data').mkdir(parents=True);(folder/'saves').mkdir();(folder/'captures').mkdir();(folder/'dumps').mkdir()
        (folder/'data/maps').symlink_to(MAPS);(folder/'data/sounds').symlink_to(MAPS.parent/'sounds')
        (folder/'data/init.txt').write_text(f'game_variant slayer\nmap_name {c["name"]}\n')
        config=folder/'saves/config.toml';config.write_text(controlled_config(NORMAL.read_text(),folder,duration))
        plan=dict(schema_version=1,kind='original_stock_multiplayer_smoke_plan',map=c['name'],host=str(host),guest=str(guest),cwd=str(ROOT),
          environment_overrides=dict(HALO_DATA_ROOT=str(folder/'data'),HALO_SAVE_ROOT=str(folder/'saves'),HALO_WINDOWED='1',MTL_DEBUG_LAYER='1'),
          config_sha256=sha(config),init_sha256=sha(folder/'data/init.txt'),cache=c,duration_seconds=duration,frozen_build_proof=desc(BUILD),
          scope='Single fresh stockMP bounded wallclock bot0 movement/firing run. Muted/offline/human bindings disabled. No benchmark/manual/audio/original-renderer pixel parity/full-game claim.')
        new_json(folder/'launch-plan.json',plan);plans.append(desc(folder/'launch-plan.json'))
    value=dict(schema_version=1,kind='original_stock_multiplayer_smoke_prepared',complete=True,passed=False,producer=desc(__file__),
               proof_python=desc(Path(sys.executable)),build=desc(BUILD),build_bindings=bindings,source_snapshots=source_records,
               original_stock_multiplayer_cases=cases,excluded_maps=excluded,map_plans=plans,duration_seconds=duration,
               expected_maps=13,read_only_assets=True,full_game_gate=False,manual_input_audio_gate=False,original_pixel_parity_gate=False,performance_gate=False)
    new_json(out/'prepared.json',value)
    print(json.dumps(dict(prepared=str(out/'prepared.json'),maps=[x['name'] for x in cases],excluded=excluded,duration=duration)),flush=True)

def verify_prepared(out):
    p=read(out/'prepared.json');require(p['producer']['sha256']==sha(__file__),'Smoke producer drift')
    require(p['build']['sha256']==sha(BUILD),'Build proof changed')
    frozen_build(BUILD)
    for s in p['source_snapshots']:require(sha(s['snapshot'])==s['sha256'],'Frozen input source changed')
    for c in p['original_stock_multiplayer_cases']:require(sha(c['cache']['file'])==c['cache']['sha256'],'Original cache changed')
    for d in p['map_plans']:require(sha(d['file'])==d['sha256'],'Launch plan changed')
    return p

def parse_log(log):
    statistics=[dict(zip(('frame','original_draws','texture_resources','programs'),map(int,v))) for v in re.findall(
        r'Native frame (\d+): (\d+) original draws, (\d+) texture resources, (\d+) programs',log)]
    failures=[x for x in log.splitlines() if 'Native Metal:' in x and ' failed (' in x]
    api_errors=[x for x in log.splitlines() if re.search(r'Validation Error|failed assertion|Assertion failed|command buffer was aborted',x,re.I)]
    exits=re.findall(r'Game exited \((-?\d+)\)',log)
    resolution=re.findall(r'screen: (\d+)x(\d+) drawn at (\d+)x(\d+)',log)
    drawable=re.findall(r'Metal drawable (\d+)x(\d+) \(([^)]+)\)',log)
    return dict(statistics=statistics,native_renderer_failures=failures,gpu_api_validation_errors=api_errors,
                guest_exit=int(exits[-1]) if exits else None,gpu_api_validation_enabled='Metal API Validation Enabled' in log,
                game_resolution=list(map(int,resolution[0])) if len(resolution)==1 else None,
                presented_drawable=dict(width=int(drawable[0][0]),height=int(drawable[0][1]),mode=drawable[0][2]) if len(drawable)==1 else None,
                depth_program_logs=[x for x in log.splitlines() if 'Native original D24 depth program ' in x],
                volume_border_program_logs=[x for x in log.splitlines() if 'Native original volume border program ' in x],
                failure_diagnostics=[x for x in log.splitlines() if any(t in x for t in ('Native unsupported','Native failed program','Native failed volume','Native original draw state:','Native stage '))])

def collect(out,name):
    p=verify_prepared(out);folder=out/name;plan=read(folder/'launch-plan.json');e=read(folder/'execution.json')
    require(name in STOCK and sha(folder/'saves/config.toml')==plan['config_sha256'],'Map configuration drift')
    require(sha(folder/'data/init.txt')==plan['init_sha256'],'Map init drift')
    validate_config(tomllib.loads((folder/'saves/config.toml').read_text()),folder,p['duration_seconds'])
    log=(folder/'launch.log').read_text();state=parse_log(log);bmps=sorted((folder/'captures').glob('frame*.bmp'))
    image=None
    if bmps:
        bmp=bmps[-1];im=Image.open(bmp).convert('RGB');png=folder/f'native-{name}-final.png'
        if not png.exists():im.save(png)
        other=Image.open(png).convert('RGB');require(other.size==im.size and other.tobytes()==im.tobytes(),'PNG changed original RGB')
        image=dict(bmp=desc(bmp),png=desc(png),rgb_sha256=hashlib.sha256(im.tobytes()).hexdigest(),rgb_preserved=True,
                   width=im.width,height=im.height,nonblack=any(im.tobytes()),capture_frame=int(bmp.stem[5:]),visually_observed=False)
    require(e['executor_sha256']==p['producer']['sha256'],'Actual executor changed')
    execution_gate=e['observed_host_exit_code']==0 and not e['timeout'] and state['guest_exit']==0 and not state['native_renderer_failures'] and not state['gpu_api_validation_errors']
    candidate=execution_gate and state['gpu_api_validation_enabled'] and bool(state['statistics']) and image is not None and image['nonblack'] and state['game_resolution']==[640,480,640,480]
    assets=[folder/'launch-plan.json',folder/'execution.json',folder/'launch.log',folder/'saves/config.toml',folder/'data/init.txt',Path(plan['cache']['cache']['file'])]
    assets+=bmps+sorted((folder/'dumps').glob('*.bin'))
    if image:assets.append(Path(image['png']['file']))
    result=dict(schema_version=1,kind='actual_original_stock_mp_native_smoke',complete=True,passed=False,map=name,
                execution=e,execution_gate=execution_gate,awaiting_image_review=bool(candidate),**state,image=image,
                last_statistics=state['statistics'][-1] if state['statistics'] else None,counters_are_last_logged_not_final=True,
                producer=desc(__file__),prepared=desc(out/'prepared.json'),frozen_build=desc(BUILD),
                artifacts=[desc(x) for x in assets],failure_dumps=[desc(x) for x in sorted((folder/'dumps').glob('*.bin'))],
                original_game_pixel_parity_gate=False,full_game_gate=False,manual_input_audio_gate=False,cpu_query_timing_gate=False,performance_gate=False,
                scope=plan['scope'])
    new_json(folder/'result.json',result)
    return result

def run_map(out,name):
    require(name in STOCK,'Only source-proven stockMP names are authorized')
    p=verify_prepared(out);folder=out/name;plan=read(folder/'launch-plan.json')
    require(not (folder/'execution.json').exists() and not (folder/'launch.log').exists(),'Each fresh map runs once; preserve prior execution')
    require(sha(folder/'saves/config.toml')==plan['config_sha256'],'Config changed before execution')
    env=dict(os.environ);env.update(plan['environment_overrides']);start=time.monotonic();timeout=False
    command=[plan['host'],plan['guest']]
    with (folder/'launch.log').open('xb') as log:
        process=subprocess.Popen(command,cwd=plan['cwd'],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:process.wait(timeout=p['duration_seconds']+20)
        except subprocess.TimeoutExpired:
            timeout=True;process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    e=dict(schema_version=1,kind='observed_original_stock_mp_native_execution',observed_host_exit_code=process.returncode,timeout=timeout,
           elapsed_seconds=time.monotonic()-start,command=command,launch_plan=desc(folder/'launch-plan.json'),
           executor_sha256=sha(__file__),prepared_sha256=sha(out/'prepared.json'),validation_environment=plan['environment_overrides'])
    new_json(folder/'execution.json',e);r=collect(out,name)
    print(json.dumps(dict(map=name,host_exit=process.returncode,guest_exit=r['guest_exit'],timeout=timeout,elapsed=e['elapsed_seconds'],
       execution_gate=r['execution_gate'],awaiting_image_review=r['awaiting_image_review'],last_statistics=r['last_statistics'],
       failures=r['native_renderer_failures'],failure_dumps=r['failure_dumps'],image=r['image'],result=desc(folder/'result.json'))),flush=True)
    return r

def review(out,name,observation):
    verify_prepared(out);folder=out/name;r=read(folder/'result.json')
    require(not (folder/'image-review.json').exists(),'Retain earlier review')
    require(r['awaiting_image_review'] and r['image']['nonblack'],'Cannot pass a failed/missing/black image run')
    require(len(observation)>20,'Record concrete observed world/weapon/HUD content')
    for d in r['artifacts']:require(sha(d['file'])==d['sha256'],'Run artifacts changed before image review')
    observation_record=dict(schema_version=1,kind='saved_original_game_image_review',map=name,image=r['image']['png'],
                            observation=observation,world_weapon_hud_observed=True,result_before_review=desc(folder/'result.json'),reviewer='Codex saved-image visual inspection')
    new_json(folder/'image-review.json',observation_record)
    r['image']['visually_observed']=True;r['image_review']=desc(folder/'image-review.json');r['awaiting_image_review']=False;r['passed']=True
    # Preserve original provisional report under its digest before adding review.
    shutil.copy2(folder/'result.json',folder/'result-before-image-review.json')
    (folder/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(map=name,passed=True,result=desc(folder/'result.json'))),flush=True)

def summarize(out):
    p=verify_prepared(out);runs=[]
    for name in STOCK:
        f=out/name/'result.json'
        if f.exists():
            r=read(f)
            for a in r['artifacts']:require(sha(a['file'])==a['sha256'],'Run artifact drift')
            if r.get('image_review'):require(sha(r['image_review']['file'])==r['image_review']['sha256'],'Image review drift')
            runs.append(dict(map=name,result=desc(f),passed=r['passed'],execution_gate=r['execution_gate'],
                last_statistics=r['last_statistics'],host_exit=r['execution']['observed_host_exit_code'],guest_exit=r['guest_exit'],
                renderer_failures=r['native_renderer_failures'],failure_dumps=r['failure_dumps']))
    _,_,_,bindings=frozen_build(BUILD)
    value=dict(schema_version=1,kind='original_stock_mp_native_content_smoke_summary',complete=len(runs)==13,passed=len(runs)==13 and all(r['passed'] for r in runs),
               prepared=desc(out/'prepared.json'),producer=desc(__file__),runs=runs,expected_maps=13,observed_runs=len(runs),passed_maps=sum(r['passed'] for r in runs),
               current_source_drift=[x for x in bindings if not x['current_matches']],frozen_build=desc(BUILD),
               full_game_gate=False,manual_input_audio_gate=False,original_game_pixel_parity_gate=False,physical_xbox_gate=False,performance_gate=False,
               limits=['One fresh15..20second scripted run per source-proven stockMP scenario; campaign/UI/community excluded.',
                       'Wallclock bot0 movement/firing and muted audio with human bindings disabled; no manual gameplay or performance claim.',
                       'Each pass requires observed host/guest0, APIValidation, no renderer/APIerror and an inspected saved nonblack original-world image.',
                       'Failed runs and failure-only original program/texture diagnostics remain unchanged; no shader fallback.',
                       'No installed app referenced, compared, packaged or replaced.'])
    path=out/('summary-'+str(len(list(out.glob('summary-*.json')))+1)+'.json');new_json(path,value)
    print(json.dumps(dict(summary=desc(path),complete=value['complete'],passed=value['passed'],passed_maps=value['passed_maps'])),flush=True)
    return value

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run-map','run-all','review','summary']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--duration',type=int,default=15);p.add_argument('--map',choices=STOCK);p.add_argument('--observation')
    a=p.parse_args();out=a.out.resolve()
    if a.mode=='prepare':prepare(out,a.duration);return 0
    if a.mode=='run-map':require(a.map is not None,'Map required');run_map(out,a.map);return 0
    if a.mode=='run-all':
        for name in STOCK:run_map(out,name)
        summarize(out);return 0
    if a.mode=='review':require(a.map is not None and a.observation is not None,'Map/observation required');review(out,a.map,a.observation);return 0
    s=summarize(out);return 0 if s['passed'] else 1
if __name__=='__main__':sys.exit(main())
