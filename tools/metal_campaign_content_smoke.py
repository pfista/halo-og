#!/usr/bin/env python3
"""Bounded original campaign openings on an immutable native build.

The unchanged multiplayer helper supplies common configuration and build
guards. Campaign identity, init bytes, larger cache bounds and scene-aware
review are explicit here; no renderer or gameplay implementation lives here.
"""
import argparse,copy,hashlib,json,os,re,shutil,struct,subprocess,sys,time,tomllib,zlib
from pathlib import Path
from PIL import Image
import metal_game_content_smoke as mp
from metal_poc_export import Cache

ROOT=mp.ROOT
CAMPAIGN=('a10','a30','a50','b30','b40','c10','c20','c40','d20','d40')
MP_SHA='12d006eef3868e253d0f00332c5e860d63a0fa25acdb723e6d4d91ea0d65fe61'
MAX_CACHE_BYTES=512*1024*1024
require,sha,desc,read,new_json=mp.require,mp.sha,mp.desc,mp.read,mp.new_json

def original_names(text):
    match=re.search(r'static char const \*scenario_paths\[10\]\s*=\s*\{(.*?)\};',text,re.S)
    require(match is not None,'Original campaign initializer missing')
    pairs=re.findall(r'"levels\\\\([a-z0-9]+)\\\\([a-z0-9]+)"',match[1])
    names=tuple(a for a,b in pairs if a==b)
    require(names==CAMPAIGN and len(pairs)==10,'Original campaign whitelist differs')
    return names

def campaign_init(name):
    require(name in CAMPAIGN,'Only original campaign names allowed')
    path='levels\\'+name+'\\'+name
    return 'game_difficulty_set normal\nmap_name '+path+'\n'

def validate_init(data,name):
    require(data==campaign_init(name).encode('ascii'),'Campaign HS init differs, contains escaping or gameplay commands')
    require(data.count(b'\\')==2 and b'\x07' not in data and b'\t' not in data,'Campaign path is not literal HS bytes')

class CampaignCache(Cache):
    """Read-only metadata decoder, with a bounded campaign-sized allocation."""
    def __init__(self,path):
        path=Path(path);require(2048<=path.stat().st_size<=MAX_CACHE_BYTES,'Campaign stored cache bound exceeded')
        raw=path.read_bytes();require(raw[:4]==b'daeh' and raw[2044:2048]==b'toof','Invalid campaign cache header')
        self.sha256=hashlib.sha256(raw).hexdigest();version,size=struct.unpack_from('<II',raw,4)
        require(version==5 and 2048<=size<=MAX_CACHE_BYTES,'Invalid campaign decoded cache size/version')
        require(struct.unpack_from('<H',raw,96)[0]==0,'Cache header is not campaign')
        if len(raw)!=size:
            decoder=zlib.decompressobj();body=decoder.decompress(raw[2048:],size-2048+1)
            require(decoder.eof and len(body)==size-2048,'Invalid compressed campaign cache size')
            raw=raw[:2048]+body
        self.data=raw;self.tag_offset=self.u32(16);self.tag_base=self.u32(self.tag_offset)-36;self.tag_size=self.u32(20)
        self.span(self.tag_offset,self.tag_size);self.tag_count=self.u32(self.tag_offset+12)
        require(0<self.tag_count<=65535,'Invalid campaign tag count');self.span(self.tag_offset+36,self.tag_count*32)
        self.name=raw[32:64].split(b'\0')[0].decode('ascii')

def campaign_inventory():
    names=original_names((ROOT/'source/main/main.c').read_text());cases=[];excluded=[]
    for p in sorted(mp.MAPS.glob('*.map')):
        h=mp.header_metadata(p)
        if p.stem not in names:excluded.append(dict(name=p.stem,scenario_type=h['scenario_type']))
    for name in names:
        path=mp.MAPS/(name+'.map');h=mp.header_metadata(path)
        require(h['name']==name and h['scenario_type']==0 and h['build']=='01.10.12.2276','Campaign header provenance differs')
        cache=CampaignCache(path);tag_id=cache.u32(cache.tag_offset+4);group,offset,tag=cache.tag(tag_id)
        require(group=='scnr' and tag=='levels\\'+name+'\\'+name and cache.unpack('<h',offset+60)[0]==0,'Original campaign scenario identity differs')
        cases.append(dict(name=name,cache=desc(path),header=h,scenario_tag=tag,scenario_tag_id=tag_id,decoded_scenario_type=0,scenario_type_byte_offset=60))
    return cases,excluded

def validate_config(c,folder,duration,scripted_input):
    require(20<=duration<=30,'Campaign opening must be bounded20..30seconds')
    require(scripted_input in ('','bot:0') and c['debug']['test_input']==scripted_input,'Unsupported scripted input')
    # Common old helper guards are unchanged, including offline/presentation/
    # failure-only diagnostic paths. It expects its own bot0 input contract.
    common=copy.deepcopy(c);common['debug']['test_input']='bot:0'
    mp.validate_config(common,folder,duration)
    require(not c['debug']['telnet_console'] and c['debug']['network_test']=='','Unexpected console/network test commands')

def controlled_config(template,folder,duration,scripted_input):
    text=mp.controlled_config(template,folder,20)
    text=mp.set_key(text,'debug','exit_after',str(float(duration)))
    text=mp.set_key(text,'debug','test_input',json.dumps(scripted_input))
    validate_config(tomllib.loads(text),folder,duration,scripted_input)
    return text

def verify_helper():require(sha(Path(mp.__file__))==MP_SHA,'Frozen multiplayer common helper changed')

def prepare(out,duration,scripted_input):
    verify_helper();require(not out.exists(),'Fresh campaign output required');out.mkdir(parents=True)
    _,host,guest,bindings=mp.frozen_build(mp.BUILD,current=True);cases,excluded=campaign_inventory()
    sources=[Path(__file__),ROOT/'tools/test_metal_campaign_content_smoke.py',Path(mp.__file__),ROOT/'tools/metal_poc_export.py',
             ROOT/'source/main/main.c',ROOT/'source/main/console.c',ROOT/'source/hs/hs.c',ROOT/'source/hs/hs_compile.c',
             ROOT/'source/game/game.c',ROOT/'source/game/player_control.c',ROOT/'port/linux/src/xinput_sdl.c',
             ROOT/'source/scenario/scenario_definitions.h',ROOT/'source/cache/cache_files_windows.c',mp.NORMAL]
    snapshots=[]
    for p in sources:
        target=out/'source-snapshot'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        require(sha(p)==sha(target),'Source changed while freezing');snapshots.append(dict(original=str(p),snapshot=str(target),sha256=sha(p)))
    plans=[]
    for c in cases:
        folder=out/c['name']
        for sub in ('data','saves','captures','dumps'):(folder/sub).mkdir(parents=True)
        (folder/'data/maps').symlink_to(mp.MAPS);(folder/'data/sounds').symlink_to(mp.MAPS.parent/'sounds')
        init=campaign_init(c['name']).encode('ascii');validate_init(init,c['name']);(folder/'data/init.txt').write_bytes(init)
        config=folder/'saves/config.toml';config.write_text(controlled_config(mp.NORMAL.read_text(),folder,duration,scripted_input))
        plan=dict(schema_version=1,kind='original_campaign_opening_smoke_plan',map=c['name'],host=str(host),guest=str(guest),cwd=str(ROOT),
                  environment_overrides=dict(HALO_DATA_ROOT=str(folder/'data'),HALO_SAVE_ROOT=str(folder/'saves'),HALO_WINDOWED='1',MTL_DEBUG_LAYER='1'),
                  config_sha256=sha(config),init_sha256=sha(folder/'data/init.txt'),init_ascii=init.decode('ascii'),cache=c,duration_seconds=duration,
                  scripted_input=scripted_input,fresh_saves_required=True,frozen_build_proof=desc(mp.BUILD),
                  scope='Fresh original Normal campaign opening; no cinematic skip or cheats. Muted/offline/human bindings disabled. Scene-appropriate saved-image review; no complete mission/manual/audio/pixel-parity/performance claim.')
        new_json(folder/'launch-plan.json',plan);plans.append(desc(folder/'launch-plan.json'))
    value=dict(schema_version=1,kind='original_campaign_smoke_prepared',complete=True,passed=False,producer=desc(__file__),common_helper=desc(Path(mp.__file__)),
               proof_python=desc(Path(sys.executable)),build=desc(mp.BUILD),build_bindings=bindings,source_snapshots=snapshots,original_campaign_cases=cases,
               excluded_maps=excluded,map_plans=plans,duration_seconds=duration,scripted_input=scripted_input,expected_maps=10,read_only_assets=True,
               full_game_gate=False,completed_missions_gate=False,manual_input_audio_gate=False,original_pixel_parity_gate=False,performance_gate=False)
    new_json(out/'prepared.json',value);print(json.dumps(dict(prepared=desc(out/'prepared.json'),maps=[x['name'] for x in cases],duration=duration,scripted_input=scripted_input)),flush=True)

def verify_prepared(out):
    verify_helper();p=read(out/'prepared.json');require(p['producer']['sha256']==sha(__file__),'Campaign producer changed');require(p['common_helper']['sha256']==MP_SHA,'Wrong common helper')
    require(p['build']['sha256']==sha(mp.BUILD),'Frozen build proof changed');mp.frozen_build(mp.BUILD)
    for x in p['source_snapshots']:require(sha(x['snapshot'])==x['sha256'],'Campaign source snapshot changed')
    for x in p['original_campaign_cases']:require(sha(x['cache']['file'])==x['cache']['sha256'],'Campaign cache changed')
    for x in p['map_plans']:require(sha(x['file'])==x['sha256'],'Campaign plan changed')
    return p

def collect(out,name):
    p=verify_prepared(out);folder=out/name;plan=read(folder/'launch-plan.json');e=read(folder/'execution.json')
    require(sha(folder/'saves/config.toml')==plan['config_sha256'],'Campaign config changed')
    validate_config(tomllib.loads((folder/'saves/config.toml').read_text()),folder,p['duration_seconds'],p['scripted_input'])
    require(sha(folder/'data/init.txt')==plan['init_sha256'],'Campaign init changed');validate_init((folder/'data/init.txt').read_bytes(),name)
    log=(folder/'launch.log').read_text();state=mp.parse_log(log);debug=folder/'data/debug.txt';debug_text=debug.read_text(errors='replace') if debug.exists() else ''
    expected_init=['game_difficulty_set normal','map_name levels\\'+name+'\\'+name]
    actual_init=re.findall(r'init: ([^\r\n]+)',debug_text);init_gate=actual_init==expected_init
    bmps=sorted((folder/'captures').glob('frame*.bmp'));image=None
    if bmps:
        bmp=bmps[-1];im=Image.open(bmp).convert('RGB');png=folder/f'native-{name}-final.png'
        if not png.exists():im.save(png)
        other=Image.open(png).convert('RGB');require(im.size==other.size and im.tobytes()==other.tobytes(),'Campaign PNG RGB differs')
        image=dict(bmp=desc(bmp),png=desc(png),rgb_sha256=hashlib.sha256(im.tobytes()).hexdigest(),rgb_preserved=True,width=im.width,height=im.height,
                   nonblack=any(im.tobytes()),capture_frame=int(bmp.stem[5:]),visually_observed=False)
    require(e['executor_sha256']==p['producer']['sha256'],'Campaign execution source changed')
    execution_gate=e['observed_host_exit_code']==0 and not e['timeout'] and state['guest_exit']==0 and not state['native_renderer_failures'] and not state['gpu_api_validation_errors'] and init_gate
    candidate=execution_gate and state['gpu_api_validation_enabled'] and bool(state['statistics']) and image is not None and image['nonblack'] and state['game_resolution']==[640,480,640,480]
    assets=[folder/'launch-plan.json',folder/'execution.json',folder/'launch.log',folder/'saves/config.toml',folder/'data/init.txt',Path(plan['cache']['cache']['file'])]
    if debug.exists():assets.append(debug)
    assets+=bmps+sorted((folder/'dumps').glob('*.bin'))
    if image:assets.append(Path(image['png']['file']))
    r=dict(schema_version=1,kind='actual_original_campaign_native_smoke',complete=True,passed=False,map=name,execution=e,execution_gate=execution_gate,
           original_hs_init_gate=init_gate,executed_init_commands=actual_init,awaiting_image_review=bool(candidate),**state,image=image,
           last_statistics=state['statistics'][-1] if state['statistics'] else None,counters_are_last_logged_not_final=True,producer=desc(__file__),common_helper=desc(Path(mp.__file__)),
           prepared=desc(out/'prepared.json'),frozen_build=desc(mp.BUILD),artifacts=[desc(x) for x in assets],failure_dumps=[desc(x) for x in sorted((folder/'dumps').glob('*.bin'))],
           full_game_gate=False,completed_missions_gate=False,manual_input_audio_gate=False,original_game_pixel_parity_gate=False,cpu_query_timing_gate=False,performance_gate=False,scope=plan['scope'])
    new_json(folder/'result.json',r);return r

def run_map(out,name):
    require(name in CAMPAIGN,'Only original campaign scenarios allowed');p=verify_prepared(out);folder=out/name;plan=read(folder/'launch-plan.json')
    require(not (folder/'execution.json').exists() and not (folder/'launch.log').exists(),'Fresh campaign runs only')
    require(list((folder/'saves').iterdir())==[folder/'saves/config.toml'],'Campaign saves not fresh')
    require(sha(folder/'saves/config.toml')==plan['config_sha256'],'Campaign config changed before run')
    env=dict(os.environ);env.update(plan['environment_overrides']);start=time.monotonic();timeout=False;command=[plan['host'],plan['guest']]
    with (folder/'launch.log').open('xb') as log:
        process=subprocess.Popen(command,cwd=plan['cwd'],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:process.wait(timeout=p['duration_seconds']+20)
        except subprocess.TimeoutExpired:
            timeout=True;process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    e=dict(schema_version=1,kind='observed_original_campaign_native_execution',observed_host_exit_code=process.returncode,timeout=timeout,
           elapsed_seconds=time.monotonic()-start,command=command,launch_plan=desc(folder/'launch-plan.json'),executor_sha256=sha(__file__),
           prepared_sha256=sha(out/'prepared.json'),validation_environment=plan['environment_overrides'],fresh_save_state_verified_before_launch=True)
    new_json(folder/'execution.json',e);r=collect(out,name)
    print(json.dumps(dict(map=name,host_exit=process.returncode,guest_exit=r['guest_exit'],timeout=timeout,elapsed=e['elapsed_seconds'],execution_gate=r['execution_gate'],
                         init_gate=r['original_hs_init_gate'],awaiting_image_review=r['awaiting_image_review'],last_statistics=r['last_statistics'],failures=r['native_renderer_failures'],
                         failure_dumps=r['failure_dumps'],image=r['image'],result=desc(folder/'result.json'))),flush=True)
    return r

def review(out,name,category,observation):
    verify_prepared(out);folder=out/name;r=read(folder/'result.json');require(not (folder/'image-review.json').exists(),'Review already retained')
    require(r['awaiting_image_review'] and r['image']['nonblack'] and category in ('cinematic','gameplay','world_scene'),'Failed/black/missing/invalid scene review')
    require(len(observation)>20,'Record concrete scene content')
    for d in r['artifacts']:require(sha(d['file'])==d['sha256'],'Campaign artifact changed')
    provisional=folder/'result-before-image-review.json';shutil.copy2(folder/'result.json',provisional)
    review=dict(schema_version=1,kind='original_campaign_saved_scene_review',map=name,image=r['image']['png'],category=category,observation=observation,
                original_world_scene_observed=True,provisional_result=desc(provisional),reviewer='Codex saved-image visual inspection')
    new_json(folder/'image-review.json',review);r['image']['visually_observed']=True;r['image_review']=desc(folder/'image-review.json');r['scene_category']=category
    r['awaiting_image_review']=False;r['passed']=True;(folder/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(map=name,passed=True,scene_category=category,result=desc(folder/'result.json'))),flush=True)

def summarize(out):
    p=verify_prepared(out);runs=[]
    for name in CAMPAIGN:
        f=out/name/'result.json'
        if not f.exists():continue
        r=read(f)
        for d in r['artifacts']:require(sha(d['file'])==d['sha256'],'Campaign artifact drift')
        if r.get('image_review'):require(sha(r['image_review']['file'])==r['image_review']['sha256'],'Scene review drift')
        runs.append(dict(map=name,result=desc(f),passed=r['passed'],execution_gate=r['execution_gate'],host_exit=r['execution']['observed_host_exit_code'],
                         guest_exit=r['guest_exit'],last_statistics=r['last_statistics'],scene_category=r.get('scene_category'),failures=r['native_renderer_failures'],failure_dumps=r['failure_dumps']))
    _,_,_,bindings=mp.frozen_build(mp.BUILD)
    s=dict(schema_version=1,kind='original_campaign_native_content_smoke_summary',complete=len(runs)==10,passed=len(runs)==10 and all(r['passed'] for r in runs),
           prepared=desc(out/'prepared.json'),producer=desc(__file__),common_helper=desc(Path(mp.__file__)),runs=runs,expected_maps=10,observed_runs=len(runs),passed_maps=sum(r['passed'] for r in runs),
           current_source_drift=[x for x in bindings if not x['current_matches']],full_game_gate=False,completed_missions_gate=False,manual_input_audio_gate=False,
           original_game_pixel_parity_gate=False,physical_xbox_gate=False,cpu_query_timing_gate=False,performance_gate=False,
           limits=['Original Normal campaign openings with fresh isolated saves; 20..30second wallclock window per scenario.',
                   'No cinematic skip/cheats/Slayer init; scene review can show cinematics without weapon/HUD.',
                   'Muted/offline/human bindings disabled; no complete missions, manual input/audio, pixel parity or performance claim.',
                   'No installed app referenced, compared, packaged or replaced.'])
    path=out/('summary-'+str(len(list(out.glob('summary-*.json')))+1)+'.json');new_json(path,s)
    print(json.dumps(dict(summary=desc(path),complete=s['complete'],passed=s['passed'],passed_maps=s['passed_maps'])),flush=True);return s

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','run-map','run-rest','review','summary'));p.add_argument('--out',type=Path,required=True)
    p.add_argument('--duration',type=int,default=30);p.add_argument('--input',choices=('none','bot0'),default='none');p.add_argument('--map',choices=CAMPAIGN)
    p.add_argument('--scene-category',choices=('cinematic','gameplay','world_scene'));p.add_argument('--observation');a=p.parse_args();out=a.out.resolve()
    if a.mode=='prepare':prepare(out,a.duration,'' if a.input=='none' else 'bot:0');return 0
    if a.mode=='run-map':require(a.map is not None,'Campaign map required');r=run_map(out,a.map);return 0 if r['execution_gate'] else 1
    if a.mode=='run-rest':
        require(read(out/'a10/result.json')['passed'],'First unmodified a10 run must pass scene review')
        for name in CAMPAIGN[1:]:run_map(out,name)
        summarize(out);return 0
    if a.mode=='review':require(a.map and a.scene_category and a.observation,'Scene review fields required');review(out,a.map,a.scene_category,a.observation);return 0
    s=summarize(out);return 0 if s['passed'] else 1
if __name__=='__main__':sys.exit(main())
