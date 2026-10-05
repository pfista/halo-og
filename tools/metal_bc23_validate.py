#!/usr/bin/env python3
"""Independent BC2/BC3 raw-block sampling through ANGLE and real ILP32 Metal.

Synthetic resources isolate compressed upload, authored mip selection, alpha
selectors and endpoint ordering. No reference image is uploaded to the GPU.
Working ANGLE equality is strict; ideal interpolation discrepancies stay visible.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

import metal_host_draw_validate as host

ROOT=host.ROOT
WIDTH,HEIGHT=80,32
SPEC='https://learn.microsoft.com/en-us/windows/uwp/graphics-concepts/textures-with-alpha-channels'
DEPENDENCIES=ROOT if (ROOT/'build/macos/angle/dist').exists() else ROOT.parent/'pfista-halo-macos'
FRAMEWORKS=[DEPENDENCIES/'build/macos/angle/dist/EGL.xcframework/macos-arm64',
            DEPENDENCIES/'build/macos/angle/dist/GLESv2.xcframework/macos-arm64']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def descriptor(folder,name,data):
    path=folder/name;path.write_bytes(data)
    return dict(file=name,size=len(data),sha256=sha(path))

BRIDGE_FILES=('port/macos/tests/guest_metal_draw.c','port/macos/tests/host_metal.mm',
    'port/macos/include/halo_metal_abi.h','port/macos/host/host_metal.mm','port/macos/host/host_memory.c',
    'port/macos/host/host.h','port/macos/host/metal_draw_encoder.mm','port/macos/host/metal_draw_encoder.h',
    'port/android/include/halo_android_abi.h')

def sources(folder):
    files=[ROOT/name for name in ('tools/metal_bc23_validate.py','tools/metal_host_draw_validate.py',
        'tools/metal_draw_compare.py','tools/metal_draw_replay.py','port/macos/metal-poc/bc23_glsl_validate.mm',
        'port/macos/metal_imports.list',
        'tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py')]
    files += [FRAMEWORKS[0]/'libEGL.framework/libEGL',FRAMEWORKS[1]/'libGLESv2.framework/libGLESv2']
    files += [folder/'source-snapshot'/name for name in BRIDGE_FILES]
    files.append(folder/'source-snapshot.json')
    return {str(p.resolve()):sha(p) for p in files}

def freeze_bridge(folder,snapshot_metadata):
    pinned=json.loads(snapshot_metadata.read_text());record={}
    for name in BRIDGE_FILES:
        original=ROOT/name;entry=pinned.get(str(original))
        source=Path(entry['snapshot']) if entry else original
        if entry:host.require(sha(source)==entry['sha256'],'Stale frozen bridge source: '+str(source))
        destination=folder/'source-snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        record[str(original)]=dict(file=str(destination),sha256=sha(destination),copied_from=str(source))
    (folder/'source-snapshot.json').write_text(json.dumps(record,indent=2)+'\n')

def block(slot,level,bx,by):
    """Encode independently specified endpoint/selectors, never use port decode."""
    variant=(bx+4*by+level)%5
    colors=((0xf800,0,(255,0,0),(0,0,0)),(0,0x07e0,(0,0,0),(0,255,0)),
            (0x001f,0xffff,(0,0,255),(255,255,255)),(0xffff,0,(255,255,255),(0,0,0)),
            (0x07e0,0x001f,(0,255,0),(0,0,255)))
    c0,c1,rgb0,rgb1=colors[variant]
    color_selectors=[(x+2*y+variant+level)&3 for y in range(4) for x in range(4)]
    color_word=sum(s<<(2*i) for i,s in enumerate(color_selectors))
    if slot==0:
        alpha_selectors=[(i+3*level+variant)&15 for i in range(16)]
        alpha=sum(s<<(4*i) for i,s in enumerate(alpha_selectors)).to_bytes(8,'little')
        alpha_palette=[i*17 for i in range(16)]
        exact_alpha=[True]*16
    else:
        a0,a1=((249,13),(11,243),(128,128),(255,0),(0,255))[variant]
        alpha_selectors=[(i+level+variant)&7 for i in range(16)]
        alpha=bytes((a0,a1))+sum(s<<(3*i) for i,s in enumerate(alpha_selectors)).to_bytes(6,'little')
        if a0>a1:
            alpha_palette=[a0,a1]+[((8-i)*a0+(i-1)*a1+3)//7 for i in range(2,8)]
        else:
            alpha_palette=[a0,a1]+[((6-i)*a0+(i-1)*a1+2)//5 for i in range(2,6)]+[0,255]
        exact_alpha=[s<2 or (a0<=a1 and s>=6) for s in alpha_selectors]
    color_palette=[rgb0,rgb1,tuple((2*a+b)//3 for a,b in zip(rgb0,rgb1)),
                   tuple((a+2*b)//3 for a,b in zip(rgb0,rgb1))]
    pixels=[bytes((*color_palette[c],alpha_palette[a])) for c,a in zip(color_selectors,alpha_selectors)]
    exact=[(c<2,alpha) for c,alpha in zip(color_selectors,exact_alpha)]
    return alpha+struct.pack('<HHI',c0,c1,color_word),pixels,exact

def fixture(folder):
    vs=b'''#include <metal_stdlib>
using namespace metal;
struct I { float4 position [[attribute(0)]]; };
struct V { float4 position [[position]]; };
vertex V xgpu_vertex(I i [[stage_in]]) { return {i.position}; }
'''
    ps=b'''#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; };
fragment float4 xgpu_fragment(V i [[stage_in]], texture2d<float> bc2 [[texture(0)]],
    texture2d<float> bc3 [[texture(1)]], sampler s2 [[sampler(0)]], sampler s3 [[sampler(1)]]) {
    float lod=floor(i.position.x/16.0);
    float2 uv=fmod(i.position.xy,float2(16.0))/16.0;
    return i.position.y<16.0 ? bc2.sample(s2,uv,level(lod)) : bc3.sample(s3,uv,level(lod));
}
'''
    glvs=b'''#version 300 es
precision highp float;layout(location=0)in vec4 position;
void main(){gl_Position=vec4(position.x,-position.y,position.z,position.w);}
'''
    glps=b'''#version 300 es
precision highp float;precision highp sampler2D;
uniform sampler2D bc2;uniform sampler2D bc3;out vec4 color;
void main(){float lod=floor(gl_FragCoord.x/16.0);vec2 uv=mod(gl_FragCoord.xy,vec2(16.0))/16.0;
color=gl_FragCoord.y<16.0 ? textureLod(bc2,uv,lod) : textureLod(bc3,uv,lod);}
'''
    vertices=b''.join(struct.pack('<4f',*p) for p in ((-1,1,.5,1),(1,1,.5,1),(1,-1,.5,1),(-1,-1,.5,1)))
    textures=[];decoded=[];exact_masks=[]
    for slot in range(2):
        mips=[];levels=[];masks=[]
        for level,size in enumerate((16,8,4,2,1)):
            raw=bytearray();image=[None]*(size*size);mask=[None]*(size*size)
            blocks=(size+3)//4
            for by in range(blocks):
                for bx in range(blocks):
                    encoded,pixels,exact=block(slot,level,bx,by);raw.extend(encoded)
                    for y in range(4):
                        for x in range(4):
                            if bx*4+x<size and by*4+y<size:
                                at=(by*4+y)*size+bx*4+x;image[at]=pixels[y*4+x];mask[at]=exact[y*4+x]
            mips.append(dict(descriptor(folder,f'bc{slot+2}-mip{level}.bin',raw),level=level,width=size,height=size,
                             bytes_per_row=blocks*16,bytes_per_image=blocks*blocks*16))
            levels.append(image);masks.append(mask)
        textures.append(dict(slot=slot,type='2d',pixel_format=f'bc{slot+2}_rgba',width=16,height=16,mipmaps=mips,
            sampler=dict(min_filter='nearest',mag_filter='nearest',mip_filter='nearest',address_u='clamp_to_edge',
                         address_v='clamp_to_edge',address_w='clamp_to_edge',max_anisotropy=1,lod_min=0,lod_max=4)))
        decoded.append(levels);exact_masks.append(masks)
    ideal=bytearray();masks=bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            slot=y//16;level=x//16;size=16>>level
            at=(y%16)*size//16*size+(x%16)*size//16
            ideal.extend(decoded[slot][level][at]);rgb,alpha=exact_masks[slot][level][at]
            masks.extend((rgb,rgb,rgb,alpha))
    descriptor(folder,'ideal-color.rgba',ideal);descriptor(folder,'exact-component-mask.bin',masks)
    state=dict(viewport=dict(x=0,y=0,width=WIDTH,height=HEIGHT,znear=0,zfar=1),scissor=dict(x=0,y=0,width=WIDTH,height=HEIGHT),
        raster=dict(front_face='cw',cull='none',fill='solid',depth_bias=0,slope_scale=0,depth_bias_clamp=0),
        blend=dict(enabled=False,source='one',destination='zero',operation='add',write_mask=15),
        depth=dict(enabled=True,write=True,compare='less_equal'),
        stencil=dict(enabled=False,compare='always',reference=0,read_mask=255,write_mask=0,fail='keep',depth_fail='keep',**{'pass':'keep'}))
    manifest=dict(schema_version=1,kind='bc23_transport_component_fixture',
        shaders=dict(vertex=dict(descriptor(folder,'vertex.metal',vs),entry='xgpu_vertex'),fragment=dict(descriptor(folder,'fragment.metal',ps),entry='xgpu_fragment')),
        glsl=dict(vertex=descriptor(folder,'vertex.glsl',glvs),fragment=descriptor(folder,'fragment.glsl',glps)),
        uniforms=dict(vertex=descriptor(folder,'vertex.bin',bytes(3120)),pixel=descriptor(folder,'pixel.bin',bytes(608))),
        vertex_declaration=dict(packed_mask=0,elements=[dict(register=0,stream=0,offset=0,type=0x42)]),
        vertex_streams=[dict(descriptor(folder,'stream.bin',vertices),stream=0,stride=16,offset=0,first_vertex=0)],
        fixed_attributes=[[0,0,0,1] for _ in range(16)],draw=dict(primitive='quad',indexed=False,vertex_start=0,vertex_count=4),
        textures=[*textures,None,None],render_state=state,
        target=dict(width=WIDTH,height=HEIGHT,color_format='bgra8unorm',depth_format='depth32float_stencil8',orientation='top_left',clear_color=[0,0,0,0],clear_depth=1,clear_stencil=0),
        analytic_source=SPEC,coverage=['all16 BC2 alpha codes','BC3 8-alpha/6-alpha/equal endpoint modes','all8 BC3 alpha selectors',
            'both RGB endpoint orders with all4 color selectors','five exact authored mip payloads including sub-block dimensions'])
    (folder/'fixture.json').write_text(json.dumps(manifest,indent=2)+'\n');return manifest

def verify_prepared(folder):
    prepared=json.loads((folder/'angle-prepared.json').read_text())
    host.require(prepared['source_sha256']==sources(folder),'BC23 sources/frameworks changed; prepare a fresh package')
    for path,expected in prepared['payload_sha256'].items():host.require(sha(path)==expected,'Stale BC23 payload: '+path)
    host.require(sha(folder/'bc23_glsl_validate')==prepared['runner_sha256'],'ANGLE fixture executable changed')
    return prepared

def prepare_angle(folder,snapshot_metadata):
    folder.mkdir(parents=True,exist_ok=False);freeze_bridge(folder,snapshot_metadata);before=sources(folder);fixture(folder)
    exe=folder/'bc23_glsl_validate'
    command=['xcrun','clang++','-std=c++17','-fobjc-arc','-O2','-Wall','-Wextra','-Werror',
        str(ROOT/'port/macos/metal-poc/bc23_glsl_validate.mm'),'-I'+str(DEPENDENCIES/'build/macos/toolchain/gl'),
        '-framework','Foundation','-framework','libEGL','-framework','libGLESv2','-o',str(exe)]
    for framework in FRAMEWORKS:command+=['-F',str(framework),'-Wl,-rpath,'+str(framework)]
    subprocess.run(command,check=True);host.require(before==sources(folder),'Sources changed while preparing BC23')
    prepared=dict(kind='bc23_angle_preparation',source_sha256=before,runner_sha256=sha(exe),
        payload_sha256={str(p):sha(p) for p in folder.iterdir() if p.is_file() and p!=exe},
        execution_command=[str(exe),str(folder/'fixture.json'),str(folder/'angle')])
    (folder/'angle-prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(prepared['execution_command'],indent=2))

def angle_result(folder):
    prepared=verify_prepared(folder);oracle=json.loads((folder/'angle/result.json').read_text())
    host.require(oracle['kind']=='bc23_angle_component_oracle' and oracle['backend']=='angle_metal' and
        oracle['complete'] is True and oracle['fixture_sha256']==sha(folder/'fixture.json') and
        oracle['runner_sha256']==prepared['runner_sha256'] and oracle['color_sha256']==sha(folder/'angle/color.rgba') and
        (oracle['width'],oracle['height'])==(WIDTH,HEIGHT) and
        oracle['orientation']=='logical_top_left_from_explicit_vertex_y_flip','Independent BC23 ANGLE oracle changed')
    host.require('ANGLE 2.1.28252 git hash: c053bf85793b' in oracle['gl_version'],'ANGLE oracle is not the pinned working-port revision')
    manifest=json.loads((folder/'fixture.json').read_text())
    descriptors=[*manifest['glsl'].values(),manifest['vertex_streams'][0],
                 *[mip for texture in manifest['textures'] if texture for mip in texture['mipmaps']]]
    host.require(oracle['input_sha256']=={d['file']:d['sha256'] for d in descriptors},'Incomplete ANGLE oracle payload coverage')
    for name,expected in oracle['input_sha256'].items():host.require(sha(folder/name)==expected,'ANGLE source input changed')
    actual=(folder/'angle/color.rgba').read_bytes();ideal=(folder/'ideal-color.rgba').read_bytes();mask=(folder/'exact-component-mask.bin').read_bytes()
    host.require(len(actual)==len(ideal)==len(mask)==WIDTH*HEIGHT*4,'Oracle color extent mismatch')
    exact_bad=[i for i,(a,b,m) in enumerate(zip(actual,ideal,mask)) if m and a!=b]
    ideal_metrics=dict(differing_bytes=sum(a!=b for a,b in zip(actual,ideal)),
        maximum_rgb_error=max(abs(a-b) for i,(a,b) in enumerate(zip(actual,ideal)) if i%4!=3),
        maximum_alpha_error=max(abs(a-b) for i,(a,b) in enumerate(zip(actual,ideal)) if i%4==3),
        endpoint_and_explicit_alpha_differences=len(exact_bad),first_endpoint_difference=exact_bad[:1])
    (folder/'ideal-diagnostic.json').write_text(json.dumps(ideal_metrics,indent=2)+'\n')
    host.require(not exact_bad,'BC23 exact color endpoints/explicit alpha decode differs from independent layout')
    return oracle,actual,ideal_metrics

def prepare_host(folder,plugin,llvm,linker):
    oracle,color,ideal=angle_result(folder);out=folder/'host';out.mkdir(exist_ok=False)
    manifest=json.loads((folder/'fixture.json').read_text());packet,geometry=host.wire_packet(folder,manifest)
    symbols={'halo_draw_packet':descriptor(out,'packet.bin',packet)}
    for name,data in (('color',color),('depth',struct.pack('<%df'%(WIDTH*HEIGHT),*([.5]*(WIDTH*HEIGHT)))),('stencil',bytes(WIDTH*HEIGHT))):
        symbols['halo_draw_expected_'+name]=descriptor(out,'expected-'+name+'.bin',data)
    assembly=['.section .rodata,"a",@progbits']
    for name,d in symbols.items():assembly+=['.balign 16',f'.global {name}',name+':',f'.incbin {json.dumps(str(out/d["file"]))}']
    (out/'fixture.s').write_text('\n'.join(assembly)+'\n')
    macros=dict(PACKET_BYTES=len(packet),COLOR_BYTES=WIDTH*HEIGHT*4,DEPTH_BYTES=WIDTH*HEIGHT*4,STENCIL_BYTES=WIDTH*HEIGHT,
                WIDTH=WIDTH,HEIGHT=HEIGHT,SEQUENCE=1,NEGATIVE_CASES=0,CLEAR_R=0,CLEAR_G=0,CLEAR_B=0,CLEAR_A=0)
    (out/'metal_host_draw_fixture.h').write_text('\n'.join(f'#define HALO_DRAW_{k} {v}u' for k,v in macros.items())+'\n')
    before=sources(folder);bridge=folder/'source-snapshot'
    addresses=host.build_guest(out,llvm.resolve(),linker.absolute(),plugin.resolve(),bridge);exe,_=host.build_host(out,bridge)
    host.require(before==sources(folder),'Bridge changed while preparing BC23 host fixture')
    required=('__host_import_table','__host_import_names','__host_import_count','halo_draw_report','halo_draw_actual_color','halo_draw_actual_depth','halo_draw_actual_stencil')
    native=out/'native';native.mkdir()
    command=[str(exe),str(out/'guest.elf'),*[hex(addresses[k]) for k in required[:3]],'0x1000000',*[hex(addresses[k]) for k in required[3:]],str(WIDTH),str(HEIGHT),str(native)]
    dependencies=[out/d['file'] for d in symbols.values()]+[out/'guest.elf',exe,out/'fixture.s',out/'metal_host_draw_fixture.h',plugin.resolve(),
        llvm/'clang',llvm/'opt',llvm/'llc',linker.absolute(),folder/'angle/result.json',folder/'angle/color.rgba']
    prepared=dict(kind='bc23_ilp32_host_preparation',source_sha256=before,dependency_sha256={str(p):sha(p) for p in dependencies},
        fixture_sha256=sha(folder/'fixture.json'),angle_result_sha256=sha(folder/'angle/result.json'),ideal_diagnostic=ideal,
        geometry=geometry,execution_command=command)
    (folder/'host-prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(command,indent=2))

def verify(folder,returncode):
    host.require(type(returncode) is int,'Observed native host process exit status is required')
    oracle,reference,ideal=angle_result(folder);prepared=json.loads((folder/'host-prepared.json').read_text())
    host.require(prepared['source_sha256']==sources(folder),'Bridge source changed after preparation')
    for path,expected in prepared['dependency_sha256'].items():host.require(sha(path)==expected,'Stale host fixture dependency: '+path)
    native=folder/'host/native';run_record=json.loads((native/'stdout.json').read_text())
    words=struct.unpack('<16I',(native/'guest-report.bin').read_bytes())
    host.require(run_record['kind']=='native_metal_ilp32_transport' and run_record['guest_pointer_bits']==32 and
        words[0]==1 and words[13:15]==(WIDTH,HEIGHT) and words[15]==(folder/'host/packet.bin').stat().st_size,'Wrong ILP32 guest result')
    bgra=(native/'native-color-bgra.bin').read_bytes();host.require(len(bgra)==len(reference),'Native color extent mismatch')
    rgba=bytearray(bgra);rgba[0::4]=bgra[2::4];rgba[2::4]=bgra[0::4]
    (native/'native-color.rgba').write_bytes(rgba)
    differences=dict(color=sum(a!=b for a,b in zip(rgba,reference)))
    for name in ('depth','stencil'):
        actual=(native/('native-'+name+'.bin')).read_bytes();expected=(folder/'host'/('expected-'+name+'.bin')).read_bytes()
        host.require(len(actual)==len(expected),'Native '+name+' extent mismatch');differences[name]=sum(a!=b for a,b in zip(actual,expected))
    passed=(returncode==0 and run_record['passed'] is True and run_record['guest_result']==0 and words[1]==7 and words[2]==0 and
        words[4:6]==(1,0) and
        words[6:9]==(0,0,0) and not any(differences.values()))
    output_hashes={str(native/name):sha(native/name) for name in ('native-color-bgra.bin','native-color.rgba',
        'native-depth.bin','native-stencil.bin','guest-report.bin','stdout.json','stderr.log')}
    host.require(prepared['source_sha256']==sources(folder),'Bridge changed while verifying BC23 output')
    result=dict(schema_version=1,kind='bc23_ilp32_native_angle_component',complete=True,passed=passed,host_returncode=returncode,
        fixture_sha256=sha(folder/'fixture.json'),source_sha256=sources(folder),native_preparation_sha256=sha(folder/'host-prepared.json'),
        angle_result_sha256=sha(folder/'angle/result.json'),native_output_sha256=output_hashes,guest_report=list(words),
        different_bytes=differences,visible_pixels=words[9],ideal_diagnostic=ideal,gl_version=oracle['gl_version'],analytic_source=SPEC,
        coverage=json.loads((folder/'fixture.json').read_text())['coverage'],limits=['Synthetic component proof; original full-frame replay is separate.',
            'Reference after-colors are guest comparison bytes only, never GPU uploads.','Strict working ANGLE equality; ideal interpolation errors remain reported.',
            'Physical Xbox BC2/BC3 sampling precision and BC2/BC3 cube transport remain unverified.'])
    (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    host.require(passed,'BC23 real ILP32 transport did not pass; diagnostic retained')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-angle',action='store_true');mode.add_argument('--prepare-host',action='store_true');mode.add_argument('--verify',action='store_true')
    parser.add_argument('--host-returncode',type=int);parser.add_argument('--rebase-plugin',type=Path)
    parser.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    parser.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    parser.add_argument('--bridge-snapshot',type=Path,default=ROOT/'build/metal-poc/host-frame-attachments-ready/source-snapshot.json',
                        help='Immutable pre-query backend source metadata to copy and compile')
    args=parser.parse_args();folder=args.output.resolve()
    if args.prepare_angle:prepare_angle(folder,args.bridge_snapshot.resolve())
    elif args.prepare_host:
        host.require(args.rebase_plugin is not None,'Host preparation needs the local rebase plugin')
        prepare_host(folder,args.rebase_plugin,args.llvm_bin,args.linker)
    else:verify(folder,args.host_returncode)

if __name__=='__main__':main()
