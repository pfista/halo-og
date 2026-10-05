#!/usr/bin/env python3
"""Validate direct Xbox shader translation on Metal, without booting the game.

Compiles all 67 checked-in Xbox vertex programs, protects existing GLES output,
and evaluates independent combiner/sampling/alpha/fog expectations on the GPU.
Optional --corpus validates the actual keys from an opt-in engine frame capture.
This establishes shader feasibility, not full-frame or physical Xbox parity.
"""
import argparse
import copy
import ctypes as C
import hashlib
import json
import itertools
import math
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'port/linux/src'


class PixelKey(C.Structure):
    _fields_ = [('combiner_state', C.c_uint32 * 57), ('texture_modes', C.c_uint32)] + [
        (name, C.c_ubyte * 4) for name in
        ('sampler_type', 'alpha_kill', 'color_sign', 'border_axes', 'border_filter')
    ] + [('alpha_test_function', C.c_ulong)] + [
        (name, C.c_ubyte) for name in ('fog_enable', 'fog_table_mode', 'count_samples', 'coverage_alpha')]


class PixelMslOptions(C.Structure):
    _fields_ = [('version', C.c_uint32), ('depth_contract', C.c_uint32)]


def run(*args):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout or f'{args[0]} failed: {result.returncode}')
    return result


def build_library(out, baseline=False):
    sources = [PORT / f'nv2a_{kind}.c' for kind in ('vsh', 'psh')]
    if baseline:
        folder = out / 'baseline'
        folder.mkdir(exist_ok=True)
        sources = []
        for kind in ('vsh', 'psh'):
            # Standalone compilation only replaces guest include dependencies.
            source = run('git', 'show', f'HEAD:port/linux/src/nv2a_{kind}.c').stdout
            source = source.replace('#include "xgpu.h"', '#include "xgpu_shader_standalone.h"')
            source = source.replace('#include "port_config.h"', '')
            path = folder / f'nv2a_{kind}.c'
            path.write_text(source)
            sources.append(path)
    path = out / ('baseline.dylib' if baseline else 'native-shaders.dylib')
    run('clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
        '-DXGPU_SHADER_STANDALONE=1', '-DHALO_ANDROID=1', '-I', PORT,
        *sources, ROOT / 'port/macos/metal-poc/shader_text.c', '-o', path)
    lib = C.CDLL(str(path), use_errno=True)
    lib.nv2a_vertex_shader_to_glsl.argtypes = [C.POINTER(C.c_uint32), C.c_ulong, C.c_ulong]
    lib.nv2a_vertex_shader_to_glsl.restype = C.c_void_p
    lib.nv2a_pixel_shader_to_glsl.argtypes = [C.POINTER(PixelKey)]
    lib.nv2a_pixel_shader_to_glsl.restype = C.c_void_p
    if not baseline:
        lib.nv2a_vertex_shader_to_msl.argtypes = lib.nv2a_vertex_shader_to_glsl.argtypes
        lib.nv2a_vertex_shader_to_msl.restype = C.c_void_p
        lib.nv2a_pixel_shader_to_msl.argtypes = lib.nv2a_pixel_shader_to_glsl.argtypes
        lib.nv2a_pixel_shader_to_msl.restype = C.c_void_p
        lib.nv2a_pixel_shader_to_msl_with_options.argtypes = [C.POINTER(PixelKey), C.POINTER(PixelMslOptions)]
        lib.nv2a_pixel_shader_to_msl_with_options.restype = C.c_void_p
    return lib


def generated(func, *args):
    pointer = func(*args)
    if not pointer:
        return None
    try:
        return C.string_at(pointer).decode()
    finally:
        free = C.CDLL(None).free
        free.argtypes = [C.c_void_p]
        free(pointer)


def vertex_programs():
    folder = ROOT / 'source/rasterizer/xbox'
    source = (folder / 'rasterizer_xbox_vertex_shaders_data.inc').read_text()
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    data = b''.join(int(word, 16).to_bytes(4, 'little') for word in re.findall(r'0x[\da-fA-F]+', source))
    entries = re.findall(r'VERTEX_SHADER_ENTRY\((0x[\da-fA-F]+), (0x[\da-fA-F]+)\)',
                         (folder / 'rasterizer_xbox_vertex_shaders.c').read_text())
    assert len(entries) == 67
    for index, (offset, size) in enumerate(entries):
        offset, size = int(offset, 16), int(size, 16)
        header = int.from_bytes(data[offset:offset + 4], 'little')
        count = header >> 16
        assert size == 4 + count * 16 and offset + size <= len(data)
        words = [int.from_bytes(data[pos:pos + 4], 'little')
                 for pos in range(offset + 4, offset + size, 4)]
        yield index, count, (C.c_uint32 * len(words))(*words)


def fixture(name):
    return dict(name=name, inputs=dict(d0=[.13, .37, .74, .62], d1=[.2, .3, .4, .5],
                b0=[0, 0, 0, 1], b1=[0, 0, 0, 1], t=[[.25, .25, .5, 1]] * 4, fog=.4),
                uniforms=dict(c0=[[.2, .4, .6, .8]] * 8, c1=[[.1, .3, .5, .7]] * 8,
                final_c0=[.2, .4, .6, .8], final_c1=[.1, .3, .5, .7],
                fog_color=[.05, .15, .25, 1], fog_parameters=[.1, .9, .5, 0],
                alpha_reference=128, bump_matrix=[[1, 0, 0, 1]] * 4,
                bump_luminance=[[1, 0, 0, 0]] * 4, texture_scale=[[1, 1, 1, 1]] * 4,
                texture_border_color=[[.1, .2, .9, .25]] * 4, texture_lod_bias=[0, 0, 0, 0]),
                textures=[dict(kind=0)] * 4, discard=False)


def clamp(x):
    return max(0., min(1., x))


def pixel_fixtures():
    # Each key comes from packed Xbox state. Expectations below use independent
    # arithmetic on fixture values, never the generated shader source.
    for mapping in range(8):
        for value in (0., .13, .5, .74, 1.):
            key = PixelKey(); key.combiner_state[53] = 1
            key.combiner_state[34] = ((mapping * 32 + 4) << 24) | (0x20 << 16)
            key.combiner_state[0] = ((mapping * 32 + 0x14) << 24) | (0x20 << 16)
            key.combiner_state[45] = key.combiner_state[26] = 0xc0
            f = fixture(f'input-mapping-{mapping}-{value}');f['inputs']['d0'] = [value] * 4
            mapped = (value, 1-value, 2*value-1, 1-2*value, value-.5, .5-value, value, -value)[mapping]
            f['expected'] = [clamp(mapped)] * 4
            yield key, f
    for flags in (0, 8, 16, 24, 32, 48):
        key = PixelKey();key.combiner_state[53] = 1
        key.combiner_state[34] = 0x04050000;key.combiner_state[0] = 0x14150000
        key.combiner_state[45] = key.combiner_state[26] = 0xc0 | (flags << 12)
        f = fixture(f'output-mapping-{flags}')
        values = [a*b for a,b in zip(f['inputs']['d0'], f['inputs']['d1'])]
        f['expected'] = [clamp({0:v,8:v-.5,16:v*2,24:(v-.5)*2,32:v*4,48:v*.5}[flags]) for v in values]
        yield key, f
    # Dot products, RGB/alpha simultaneous reads, and the stage-local constants.
    key = PixelKey();key.combiner_state[53] = 1;key.combiner_state[34] = 0x04050000
    key.combiner_state[0] = 0x14150000;key.combiner_state[45] = 0xc0 | (2 << 12);key.combiner_state[26] = 0xc0
    f=fixture('dot-product');v=sum(a*b for a,b in zip(f['inputs']['d0'][:3],f['inputs']['d1'][:3]))
    f['expected']=[v]*3+[.62*.5];yield key,f
    for unique in (False, True):
        key=PixelKey();key.combiner_state[53]=2 | (0x1000 if unique else 0)
        key.combiner_state[34]=key.combiner_state[35]=0x01200000
        key.combiner_state[45]=key.combiner_state[46]=0xc0
        f=fixture(f'unique-c0-{unique}');f['uniforms']['c0']=copy.deepcopy(f['uniforms']['c0'])
        f['uniforms']['c0'][1]=[.6,.5,.4,.3];f['expected']=f['uniforms']['c0'][int(unique)][:3]+[1]
        yield key,f
    for msb in (True,False):
        for alpha in (0.,127/255,128/255,129/255,1.):
            key=PixelKey();key.texture_modes=4;key.combiner_state[53]=1 | (0x100 if msb else 0)
            key.combiner_state[34]=0x04200520;key.combiner_state[45]=0xc00 | (4 << 12)
            f=fixture(f'mux-{msb}-{alpha}');f['inputs']['t']=copy.deepcopy(f['inputs']['t']);f['inputs']['t'][0][3]=alpha
            choice=alpha>=.5 if msb else bool(round(alpha*255)&1)
            f['expected']=f['inputs']['d1' if choice else 'd0'][:3]+[alpha];yield key,f
    # The final combiner is A*B+(1-A)*C+D, with separately selected alpha.
    key=PixelKey();key.combiner_state[8]=0x01020400;key.combiner_state[9]=0x00001100
    f=fixture('final-lerp');a=f['uniforms']['final_c0'];b=f['uniforms']['final_c1'];c=f['inputs']['d0']
    f['expected']=[a[i]*b[i]+(1-a[i])*c[i] for i in range(3)]+[a[3]];yield key,f
    key=PixelKey();key.combiner_state[8]=0x0000000f;key.combiner_state[9]=0x04051400
    f=fixture('final-ef-product');f['expected']=[a*b for a,b in zip(f['inputs']['d0'][:3],f['inputs']['d1'][:3])]+[.62];yield key,f
    for mode in range(4):
        key=PixelKey();key.fog_enable=1;key.fog_table_mode=mode;key.combiner_state[8]=0x13040300;key.combiner_state[9]=0x00001400
        f=fixture(f'fog-{mode}');x=f['inputs']['fog'];p=f['uniforms']['fog_parameters']
        factor=clamp((x,math.exp(-p[2]*x),math.exp(-(p[2]*x)**2),(p[1]-x)/(p[1]-p[0]))[mode])
        f['expected']=[factor*a+(1-factor)*b for a,b in zip(f['inputs']['d0'][:3],f['uniforms']['fog_color'][:3])]+[.62];yield key,f
    for function in range(512,520):
        for alpha in (127/255,128/255,129/255):
            key=PixelKey();key.alpha_test_function=function;key.combiner_state[8]=4;key.combiner_state[9]=0x1400
            f=fixture(f'alpha-test-{function}-{alpha}');f['inputs']['d0'][3]=alpha;v=math.floor(alpha*255+.5)
            passes=(False,v<128,v==128,v<=128,v>128,v!=128,v>=128,True)[function-512]
            f['discard']=not passes;f['expected']=f['inputs']['d0'];yield key,f
    pixels=[17,43,89,255, 67,97,127,192, 151,173,199,128, 211,229,251,64]
    for linear in (False,True):
        for border_axes in (0,1,2,3):
            for uv in ((.25,.25),(.5,.5),(-.125,.25),(1.125,.75)):
                key=PixelKey();key.texture_modes=1;key.sampler_type[0]=1;key.border_axes[0]=border_axes
                key.border_filter[0]=3 if linear else 0;key.combiner_state[8]=8;key.combiner_state[9]=0x1800
                f=fixture(f'sampling-{linear}-{border_axes}-{uv}');f['inputs']['t']=copy.deepcopy(f['inputs']['t']);f['inputs']['t'][0]=[*uv,0,1]
                f['textures']=copy.deepcopy(f['textures']);f['textures'][0]=dict(kind=1,width=2,height=2,rgba=pixels,linear=linear,clamp_axes=border_axes)
                def texel(x,y):
                    if (border_axes&1 and not 0<=x<2) or (border_axes&2 and not 0<=y<2):return f['uniforms']['texture_border_color'][0]
                    x,y=x%2,y%2;return [v/255 for v in pixels[(y*2+x)*4:(y*2+x+1)*4]]
                if linear:
                    x,y=uv[0]*2-.5,uv[1]*2-.5;ix,iy=math.floor(x),math.floor(y);fx,fy=x-ix,y-iy
                    f['expected']=[sum(texel(ix+dx,iy+dy)[c]*wx*wy for dx,wx in ((0,1-fx),(1,fx)) for dy,wy in ((0,1-fy),(1,fy))) for c in range(4)]
                else:f['expected']=texel(math.floor(uv[0]*2),math.floor(uv[1]*2))
                yield key,f


def uint(value, bits=32):
    return type(value) is int and 0 <= value < 2**bits


def load_corpus(folder):
    """Validate the complete fixed-width capture before passing words to C."""
    hashes={}
    def read(path):
        data=path.read_bytes();hashes[str(path.resolve())]=hashlib.sha256(data).hexdigest()
        return data
    status=json.loads(read(folder/'status.json'))
    if status.get('schema_version')!=1 or status.get('kind')!='capture' or status.get('complete') is not True:
        raise RuntimeError('Shader corpus is incomplete or has no valid completion record')
    for field in ('frame','vertex_count','pixel_count','use_count'):
        if not uint(status.get(field)):raise RuntimeError(f'Invalid capture status field: {field}')
    records=[];ids={'vertex':set(),'pixel':set()}
    for path in sorted(folder.glob('*.json')):
        if path.name=='status.json':continue
        r=json.loads(read(path));kind=r.get('kind')
        if r.get('schema_version')!=1 or kind not in ids or r.get('frame')!=status['frame'] or not uint(r.get('id')):
            raise RuntimeError(f'Invalid captured shader header: {path.name}')
        if r['id'] in ids[kind]:raise RuntimeError(f'Duplicate shader id: {path.name}')
        ids[kind].add(r['id'])
        if kind=='vertex':
            count=r.get('instruction_count');words=r.get('instructions')
            if not uint(count) or not 0<count<=4096 or not isinstance(words,list) or len(words)!=4*count or not all(uint(w) for w in words):
                raise RuntimeError(f'Invalid captured instruction array: {path.name}')
            if not uint(r.get('packed_mask'),16):raise RuntimeError(f'Invalid packed mask: {path.name}')
        else:
            for field,_ in PixelKey._fields_:
                value=r.get(field)
                if field=='combiner_state':valid=isinstance(value,list) and len(value)==57 and all(uint(v) for v in value)
                elif field in ('sampler_type','alpha_kill','color_sign','border_axes','border_filter'):
                    valid=isinstance(value,list) and len(value)==4 and all(uint(v,8) for v in value)
                else:valid=uint(value,32 if field in ('texture_modes','alpha_test_function') else 8)
                if not valid:raise RuntimeError(f'Invalid pixel key {field}: {path.name}')
        records.append((path,r))
    for kind in ids:
        if len(ids[kind])!=status[kind+'_count'] or sorted(ids[kind])!=list(range(len(ids[kind]))):
            raise RuntimeError(f'Incomplete {kind} capture: ids or count mismatch')
    uses=[json.loads(line) for line in read(folder/'uses.jsonl').splitlines()]
    if len(uses)!=status['use_count']:raise RuntimeError('Incomplete draw-use capture: count mismatch')
    for index,u in enumerate(uses):
        if u.get('schema_version')!=1 or u.get('frame')!=status['frame'] or u.get('use')!=index or u.get('immediate') not in (0,1):
            raise RuntimeError('Invalid draw-use header')
        for kind in ids:
            if not uint(u.get(kind+'_id')) or u[kind+'_id'] not in ids[kind]:raise RuntimeError('Draw uses missing shader')
        if not uint(u.get('program_id')) or not uint(u.get('declaration_id')):raise RuntimeError('Invalid draw program/declaration')
    return records,uses,status,hashes


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = [PORT/'nv2a_vsh.c', PORT/'nv2a_psh.c', PORT/'xgpu_msl.h',
             PORT/'xgpu_shader_standalone.h',
             ROOT/'port/macos/metal-poc/shader_text.c',
             ROOT/'port/macos/metal-poc/shader_validate.mm', Path(__file__).resolve(),
             ROOT/'source/rasterizer/xbox/rasterizer_xbox_vertex_shaders_data.inc',
             ROOT/'source/rasterizer/xbox/rasterizer_xbox_vertex_shaders.c']
    provider=ROOT/'tools/metal_pixel_fixtures.py'
    if provider.exists(): paths.append(provider)
    return {str(p.relative_to(ROOT)):digest(p) for p in paths}


def consume_result(out, manifest_path, gpu):
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('source_sha256') != source_hashes():
        raise RuntimeError('GPU result is stale: shader, fixture, or harness sources changed; prepare again')
    if manifest.get('baseline_commit') != run('git','rev-parse','HEAD').stdout.strip():
        raise RuntimeError('GPU result is stale: GLES baseline changed; prepare again')
    for path,expected in manifest.get('corpus_sha256',{}).items():
        if digest(Path(path)) != expected:
            raise RuntimeError(f'GPU result is stale: captured input changed: {path}')
    for name,expected in manifest['shader_sha256'].items():
        if digest(out/name) != expected:
            raise RuntimeError(f'GPU result is stale: generated shader changed: {name}')
    if digest(out/'shader_validate') != manifest['runner_sha256'] or gpu.get('runner_sha256') != manifest['runner_sha256']:
        raise RuntimeError('GPU result is stale: compiled harness changed')
    if gpu.get('manifest_sha256') != digest(manifest_path):
        raise RuntimeError('GPU result is stale: different manifest or compiled sources')
    if gpu['compiled'] != len(manifest['compile']) or gpu['pixel_cases'] != len(manifest['pixel_tests']):
        raise RuntimeError('GPU result does not cover current fixture manifest')
    if gpu.get('depth_cases') != sum('expected_depth' in f for f in manifest['pixel_tests']):
        raise RuntimeError('GPU result does not cover current depth attachment fixtures')
    result=dict(gpu=gpu,existing_glsl_unchanged=manifest['existing_glsl_unchanged'],
                corpus=manifest['corpus'],source_sha256=manifest['source_sha256'],
                baseline_commit=manifest['baseline_commit'],
                limits=['shader tests only; no complete game frame',
                        'current GLES translator is not a physical Xbox reference',
                        'no measured complete-frame speedup', 'no renderer selection or gameplay changes'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/metal-poc/shader-validation')
    parser.add_argument('--corpus',type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only',action='store_true',help='Compile native harness and save fixtures; do not access GPU')
    mode.add_argument('--gpu-result',type=Path,help='Consume JSON from an independently run native GPU harness')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=out/'manifest.json'
    if args.gpu_result:
        if args.corpus:parser.error('--corpus belongs to preparation; omit it when consuming an existing GPU result')
        consume_result(out,manifest,json.loads(args.gpu_result.read_text()))
        return
    prepared_sources=source_hashes()
    prepared_commit=run('git','rev-parse','HEAD').stdout.strip()
    lib=build_library(out);baseline=build_library(out,True)
    compiled=[];preserved=0;pixel_tests=[];shader_keys={}
    for index,count,words in vertex_programs():
        for mask in (0,14):
            name=f'vertex-{index:02}-{mask}.metal';source=generated(lib.nv2a_vertex_shader_to_msl,words,count,mask)
            if source is None:raise RuntimeError(f'Xbox vertex shader {index}/{mask} unsupported, errno={C.get_errno()}')
            assert generated(lib.nv2a_vertex_shader_to_glsl,words,count,mask)==generated(baseline.nv2a_vertex_shader_to_glsl,words,count,mask)
            (out/name).write_text(source);compiled.append(name);preserved+=1
    # The fixture provider imports this shared ctypes key when run as a script.
    sys.modules.setdefault('metal_shader_validate',sys.modules[__name__])
    from metal_pixel_fixtures import extra_pixel_fixtures
    for key,f in itertools.chain(pixel_fixtures(), extra_pixel_fixtures()):
        identity=(bytes(key),f.get('depth_contract'))
        if identity not in shader_keys:
            name=f'pixel-{len(shader_keys):03}.metal'
            if f.get('depth_contract') == 'raw_d24':
                options=PixelMslOptions(1,1)
                source=generated(lib.nv2a_pixel_shader_to_msl_with_options,C.byref(key),C.byref(options))
            else:
                source=generated(lib.nv2a_pixel_shader_to_msl,C.byref(key))
            if source is None:raise RuntimeError(f'{f["name"]} unsupported, errno={C.get_errno()}')
            assert generated(lib.nv2a_pixel_shader_to_glsl,C.byref(key))==generated(baseline.nv2a_pixel_shader_to_glsl,C.byref(key)),f['name']
            (out/name).write_text(source);compiled.append(name);shader_keys[identity]=name;preserved+=1
        f['shader']=shader_keys[identity];pixel_tests.append(f)
    corpus=dict(vertex=0,pixel=0,pixel_glsl_unchanged=0,rejected=[]);corpus_hashes={}
    if args.corpus:
        records,uses,status,corpus_hashes=load_corpus(args.corpus)
        corpus['capture']=status;unsupported={'vertex':set(),'pixel':set()}
        for path,record in records:
            kind=record['kind']
            if kind=='vertex':
                words=(C.c_uint32*len(record['instructions']))(*record['instructions'])
                source=generated(lib.nv2a_vertex_shader_to_msl,words,record['instruction_count'],record['packed_mask'])
            else:
                key=PixelKey()
                for field,_ in PixelKey._fields_:
                    if isinstance(record[field],list):getattr(key,field)[:]=record[field]
                    else:setattr(key,field,record[field])
                assert generated(lib.nv2a_pixel_shader_to_glsl,C.byref(key))==generated(baseline.nv2a_pixel_shader_to_glsl,C.byref(key)),path.name
                corpus['pixel_glsl_unchanged']+=1
                source=generated(lib.nv2a_pixel_shader_to_msl,C.byref(key))
            if source is None:
                rejection=dict(file=path.name,kind=kind,id=record['id'],errno=C.get_errno())
                if kind=='pixel':rejection.update(texture_modes=record['texture_modes'],sampler_type=record['sampler_type'],count_samples=record['count_samples'])
                corpus['rejected'].append(rejection);unsupported[kind].add(record['id']);continue
            name='captured-'+path.stem+'.metal';(out/name).write_text(source);compiled.append(name);corpus[kind]+=1
        corpus['uses_with_supported_shaders']=sum(not any(u[k+'_id'] in unsupported[k] for k in unsupported) for u in uses)
    manifest=out/'manifest.json'
    executable=out/'shader_validate'
    run('xcrun','clang++','-std=c++17','-O2','-fobjc-arc','-Wall','-Wextra',
        ROOT/'port/macos/metal-poc/shader_validate.mm','-framework','Foundation','-framework','Metal','-o',executable)
    run('codesign','--force','--sign','-',executable)
    if prepared_sources!=source_hashes() or prepared_commit!=run('git','rev-parse','HEAD').stdout.strip():
        raise RuntimeError('Sources changed during preparation; prepare again')
    if any(digest(Path(path))!=expected for path,expected in corpus_hashes.items()):
        raise RuntimeError('Captured inputs changed during preparation; prepare again')
    manifest.write_text(json.dumps(dict(compile=compiled,pixel_tests=pixel_tests,
        shader_sha256={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in compiled},
        runner_sha256=digest(executable),source_sha256=prepared_sources,
        existing_glsl_unchanged=preserved,corpus=corpus,corpus_sha256=corpus_hashes,
        baseline_commit=prepared_commit),indent=2)+'\n')
    if args.prepare_only:
        print(json.dumps(dict(executable=str(executable),manifest=str(manifest),existing_glsl_unchanged=preserved),indent=2))
        return
    consume_result(out,manifest,json.loads(run(executable,manifest).stdout))



if __name__=='__main__':main()
