#!/usr/bin/env python3
"""Independent BC2 authored-mip alpha-border proof through actual ILP32 DRAW.

RGB preservation compares against an independent legacy production shader draw
using the same hardware-black sampler. Alpha substitutes the authored byte70
before CPU bilinear interpolation; expected targets never enter GPU uploads.
Rounding disagreements remain strict failures with per-case diagnostics.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess

import metal_black_border_validate as black
import metal_host_draw_validate as wire
import metal_shader_validate as shader

ROOT=wire.ROOT
WIDTH,HEIGHT=104,182
ASSETS=ROOT/'build/metal-poc/alpha-border-authored-hud-assets/assets.json'
class Options(C.Structure):
    _fields_=[('version',C.c_uint32),('depth_contract',C.c_uint32),('native_alpha_border_mask',C.c_uint32)]

def require(c,m):wire.require(c,m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,b):p.write_bytes(b);return b
def quantize(x):return min(255,max(0,math.floor(x+.5)))

def pattern(x,y,size,level):
    if x in (0,size-1) or y in (0,size-1):return 2+4*((x+y+level)%4)
    return (5*x+3*y+level)%16

def synthetic(out):
    levels=[]
    for level,size in enumerate((64,32,16,8,4)):
        raw=bytearray();alpha=[]
        for y in range(size):
            alpha.append([17*pattern(x,y,size,level) for x in range(size)])
        for by in range(size//4):
            for bx in range(size//4):
                nibbles=[pattern(bx*4+x,by*4+y,size,level) for y in range(4) for x in range(4)]
                raw.extend(sum(n<<(4*i) for i,n in enumerate(nibbles)).to_bytes(8,'little'))
                raw.extend(bytes(8)) # RGB endpoints/selectors are literal zero.
        path=out/f'synthetic-mip{level}.bc2';write(path,raw)
        levels.append(dict(file=path,width=size,height=size,bytes_per_row=(size//4)*16,alpha=alpha))
    return dict(name='synthetic_all16_bc2_alpha_codes',levels=levels)

def decode_alpha(raw,size):
    require(len(raw)==size*size,'BC2 compressed extent differs from independent16Bblock layout')
    alpha=[[0]*size for _ in range(size)]
    blocks=size//4
    for by in range(blocks):
        for bx in range(blocks):
            codes=int.from_bytes(raw[(by*blocks+bx)*16:(by*blocks+bx)*16+8],'little')
            for y in range(4):
                for x in range(4):alpha[by*4+y][bx*4+x]=17*((codes>>(4*(y*4+x)))&15)
    return alpha

def alpha_reference(image,u,v,axes=3,border=70):
    size=len(image);x,y=u*size-.5,v*size-.5;ix,iy=math.floor(x),math.floor(y);fx,fy=x-ix,y-iy
    def texel(a,b):
        if (axes&1 and not 0<=a<size) or (axes&2 and not 0<=b<size):return border
        return image[b%size][a%size]
    return ((1-fx)*(1-fy)*texel(ix,iy)+fx*(1-fy)*texel(ix+1,iy)+
            (1-fx)*fy*texel(ix,iy+1)+fx*fy*texel(ix+1,iy+1))

def compare_alpha(value,func,reference):
    return {0:True,2:value<reference,3:value==reference,5:value>reference,7:value>=reference}[func]

def records():
    result=[]
    for fast in (False,True):
        for lod in range(5):
            for axes in (1,2,3):result.append(dict(fast=fast,lod=lod,axes=axes,texture=0,kind='fringe'))
        for lod in (1,2,3):result.append(dict(fast=fast,lod=lod,axes=3,texture=0,kind='derivative'))
        for blend in ('sweep','mask'):
            for lod in range(5):result.append(dict(fast=fast,lod=lod,axes=3,texture=0,kind='blend',blend=blend))
        for func in (2,3,5,7):
            for reference in (68,69,70,71):result.append(dict(fast=fast,lod=0,axes=3,texture=0,kind='threshold',func=func,reference=reference))
        for texture in (1,2):
            for lod in range(5):result.append(dict(fast=fast,lod=lod,axes=3,texture=texture,kind='authored'))
    require(len(result)==108,'Case matrix changed without resizing layout')
    return result

def state(blend,depth_write=True):
    return dict(viewport=dict(x=0,y=0,width=WIDTH,height=HEIGHT,znear=0,zfar=1),scissor=dict(x=0,y=0,width=WIDTH,height=HEIGHT),
        raster=dict(front_face='cw',cull='none',fill='solid',depth_bias=0,slope_scale=0,depth_bias_clamp=0),
        blend=dict(enabled=bool(blend),source='zero' if blend=='mask' else 'one',destination='source_alpha' if blend else 'zero',operation='add',write_mask=15),
        depth=dict(enabled=True,write=depth_write,compare='less_equal'),
        stencil=dict(enabled=False,compare='always',reference=0,read_mask=255,write_mask=0,fail='keep',depth_fail='keep',**{'pass':'keep'}))

def add_draw(packet,program,texture,color,vertices,indices,pu,lod,axes,draw_state,extended=True,derivative=False):
    sampler=struct.pack('<8I2f',1,1,1,3 if axes&1 else 0,3 if axes&2 else 0,2,1,0,0 if derivative else lod,4 if derivative else lod)
    fixed=struct.pack('<16I',19 if extended else 9,424 if extended else 416,program,1,color,1,2,1,texture,1,0,0,0,0,0,0)
    fixed+=sampler+bytes(120)+wire.state_bytes(draw_state)+struct.pack('<10I',len(vertices)//256,len(indices),0,3,0,0,0,0,0,0)
    if extended:fixed+=struct.pack('<2I',1,0)
    start=len(packet.data)
    packet.command(fixed,[(392,vertices),(396,struct.pack('<%dI'%len(indices),*indices)),(400,bytes(3120)),(404,pu)])
    return start

def rejection_packet(raw,draw_offset):
    fixed=raw[draw_offset:draw_offset+424];vertices,indices=struct.unpack_from('<2I',fixed,376)
    packet=wire.Packet(2)
    packet.command(struct.pack('<12I5fI',4,72,1,1,2,1,7,0,0,WIDTH,HEIGHT,165,1,0,1,1,0,0))
    payloads=[]
    for field,n in ((392,vertices*256),(396,indices*4),(400,3120),(404,608)):
        pos=struct.unpack_from('<I',fixed,field)[0];payloads.append((field,raw[pos:pos+n]))
    position=len(packet.data);packet.command(fixed,payloads)
    return packet.finish(),position

def fixture(out):
    lib=shader.build_library(out)
    lib.nv2a_pixel_shader_to_msl_with_options.argtypes=[C.POINTER(shader.PixelKey),C.POINTER(Options)]
    lib.nv2a_pixel_shader_to_msl_with_options.restype=C.c_void_p
    packet=wire.Packet(1);programs={}
    def program(func,fast,masked):
        key=(func,fast,masked)
        if key in programs:return programs[key]
        pskey=shader.PixelKey();pskey.texture_modes=1;pskey.sampler_type[0]=1;pskey.combiner_state[8]=8;pskey.combiner_state[9]=0x18<<8
        pskey.alpha_test_function=511+func if func else 0 # Original Xbox D3DCMP enum begins at0x200.
        source=shader.generated(lib.nv2a_pixel_shader_to_msl_with_options,C.byref(pskey),C.byref(Options(2,0,int(masked))))
        require(source is not None,'Production v2 alpha border emitter rejected supported key')
        identifier=101 if not masked else (100 if not func and not fast else 102 if not func else 110+func*2+int(fast))
        programs[key]=identifier;write(out/f'fragment-{identifier}.metal',source.encode())
        varyings=source[source.index('struct XgpuVaryings'):source.index('struct XgpuPixelUniforms')]
        vs=('#include <metal_stdlib>\nusing namespace metal;\n'+varyings+
            'struct I { float4 p [[attribute(0)]]; float4 uv [[attribute(4)]]; };\n'
            'vertex XgpuVaryings xgpu_vertex(I i [[stage_in]]) { XgpuVaryings o={};o.position=i.p;o.xT0=i.uv;return o;}\n').encode()
        write(out/'vertex.metal',vs)
        packet.command(struct.pack('<10I',7,40,identifier,1,0,0,len(vs),0,len(source.encode()),int(fast)),[(20,vs),(28,source.encode())])
        return identifier
    for identifier,fmt in ((1,2),(2,3),(31,2)):packet.command(struct.pack('<12I',10,48,identifier,1,fmt,WIDTH,HEIGHT,1,1,1,2,0))
    textures=[synthetic(out)];metadata=json.loads(ASSETS.read_text());asset_hashes={str(ASSETS):sha(ASSETS)}
    for asset in metadata['textures']:
        levels=[]
        for mip in asset['mipmaps']:
            src=ASSETS.parent/mip['file'];require(sha(src)==mip['sha256'],'Authored asset changed');asset_hashes[str(src)]=sha(src)
            dst=out/src.name;raw=src.read_bytes();write(dst,raw)
            levels.append(dict(file=dst,width=mip['width'],height=mip['height'],bytes_per_row=mip['bytes_per_row'],alpha=decode_alpha(raw,mip['width'])))
        textures.append(dict(name=asset['name'],levels=levels))
    for index,texture in enumerate(textures):
        identifier=10+index if not index else 20+index #11 is reserved for invalid cube.
        texture['identifier']=identifier
        packet.command(struct.pack('<12I',10,48,identifier,1,5,64,64,1,1,5,1,0))
        for lod,mip in enumerate(texture['levels']):
            raw=mip['file'].read_bytes();n=mip['width'];packet.command(struct.pack('<18I',11,72,identifier,1,lod,0,0,0,0,n,n,1,mip['bytes_per_row'],len(raw),0,len(raw),1,0),[(56,raw)])
    packet.command(struct.pack('<12I',10,48,11,1,1,1,1,1,2,1,1,0))
    for face in range(6):packet.command(struct.pack('<18I',11,72,11,1,0,face,0,0,0,1,1,1,4,4,0,4,1,0),[(56,bytes(4))])
    for target in (1,31):packet.command(struct.pack('<12I5fI',4,72,target,1,2,1,7,0,0,WIDTH,HEIGHT,0,0,0,0,0,1,0))
    program(0,False,False);program(0,False,True)
    expected=bytearray(WIDTH*HEIGHT*4);components=bytearray([1])*(WIDTH*HEIGHT*4);depth=[1.]*(WIDTH*HEIGHT);case_records=records();last_extended=None
    for ordinal,record in enumerate(case_records):
        lod,axes=record['lod'],record['axes'];mip=textures[record['texture']]['levels'][lod];size=mip['width'];ox=(ordinal%8)*13;oy=(ordinal//8)*13
        derivative=record['kind']=='derivative';tile=3 if derivative else 1;blend=record.get('blend');func=record.get('func',0)
        if record['kind']=='threshold':uvs=[(3.5/64,7.5/64),(0,1/64),(-2/64,.5),(1,.5)]
        else:
            coordinates=([0,.5,1] if derivative else [-2/size,-.5/size,0,.5/size,1.5/size,2.5/size,.5,1-2.5/size,1-1.5/size,1-.5/size,1,1+.5/size,1+2/size])
            uvs=[(u,v) for v in coordinates for u in coordinates]
        columns=2 if func else len(coordinates);vertices=bytearray();indices=[];pixel_records=[]
        if blend:packet.command(struct.pack('<12I5fI',4,72,1,1,0,0,1,ox,oy,13,13,0,16/255,32/255,64/255,128/255,1,0))
        # A blended rectangle initializes every pixel, including unused cells.
        if blend:
            for y in range(13):
                for x in range(13):at=((oy+y)*WIDTH+ox+x)*4;expected[at:at+4]=bytes((16,32,64,128))
        for number,(u,v) in enumerate(uvs):
            x,y=number%columns,number//columns;left,top=ox+x*tile,oy+y*tile;base=len(vertices)//256
            for px,py in ((left,top),(left+tile,top),(left+tile,top+tile),(left,top+tile)):
                vertex=bytearray(256);struct.pack_into('<4f',vertex,0,2*px/WIDTH-1,1-2*py/HEIGHT,.5,1)
                du=(px-left-1.5)/size if derivative else 0;dv=(py-top-1.5)/size if derivative else 0
                struct.pack_into('<4f',vertex,64,u+du,v+dv,0,1);vertices.extend(vertex)
            indices.extend((base,base+1,base+2,base,base+2,base+3))
            for ty in range(tile):
                for tx in range(tile):
                    su=u+(tx-1)/size if derivative else u;sv=v+(ty-1)/size if derivative else v
                    alpha=alpha_reference(mip['alpha'],su,sv,axes);q=quantize(alpha);passed=compare_alpha(q,func,record.get('reference',0));at=((top+ty)*WIDTH+left+tx)*4
                    if passed:
                        depth[at//4]=.5
                        if blend:
                            rgb=[quantize(c*alpha/255) for c in (16,32,64)];a=quantize((alpha if blend=='sweep' else 0)+128*alpha/255)
                            expected[at:at+4]=bytes((*rgb,a))
                        else:expected[at+3]=q;components[at:at+3]=bytes(3)
                    pixel_records.append(dict(x=left+tx,y=top+ty,u=su,v=sv,ideal_alpha_byte_units=alpha,quantized_alpha=q,discard=not passed))
        pu=bytearray(608);struct.pack_into('<f',pu,320,record.get('reference',0))
        for stage in range(4):struct.pack_into('<4f',pu,464+16*stage,1,1,1,1)
        struct.pack_into('<4f',pu,528,0,0,0,70/255)
        pid=program(func,record['fast'],True)
        draw_offset=add_draw(packet,pid,textures[record['texture']]['identifier'],1,vertices,indices,pu,lod,axes,state(blend),derivative=derivative)
        if not func and not record['fast'] and not blend:last_extended=draw_offset
        if not blend:
            # Reference RGB from the unmodified production emitter; alpha is
            # independently analytical and never taken from this reference.
            add_draw(packet,101,textures[record['texture']]['identifier'],31,vertices,indices,pu,lod,axes,state(None,False),extended=False,derivative=derivative)
        record.update(origin=[ox,oy],source_texture=textures[record['texture']]['name'],pixels=pixel_records)
    raw=packet.finish();write(out/'packet.bin',raw);rejection,offset=rejection_packet(raw,last_extended);write(out/'rejection.bin',rejection)
    write(out/'expected-color.rgba',expected);write(out/'expected-components.bin',components);write(out/'expected-depth.bin',struct.pack('<%df'%len(depth),*depth));write(out/'expected-stencil.bin',bytes(WIDTH*HEIGHT))
    (out/'cases.json').write_text(json.dumps(case_records,indent=2)+'\n');(out/'asset-identity.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return offset,asset_hashes,case_records

def prepare(out,llvm,linker,plugin):
    out.mkdir(parents=True,exist_ok=False);snapshot=out/'source-snapshot';hashes={}
    sources=tuple(n for n in black.SOURCE_FILES if n!='port/macos/tests/guest_metal_black_border.c')+('tools/metal_alpha_border_validate.py','port/macos/tests/guest_metal_alpha_border.c')
    for name in sources:
        p=ROOT/name;d=snapshot/name;d.parent.mkdir(parents=True,exist_ok=True);h=sha(p);shutil.copy2(p,d);require(sha(p)==sha(d)==h,'Source changed during snapshot');hashes[str(p)]=h;hashes[str(d)]=h
    offset,assets,cases=fixture(out);hashes.update(assets)
    names={'halo_draw_packet':'packet.bin','halo_draw_rejection_template':'rejection.bin','halo_draw_expected_color':'expected-color.rgba',
        'halo_draw_expected_depth':'expected-depth.bin','halo_draw_expected_stencil':'expected-stencil.bin','halo_draw_expected_components':'expected-components.bin'}
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n'+'\n'.join(f'.balign 16\n.global {k}\n{k}:\n.incbin {json.dumps(str(out/v))}' for k,v in names.items())+'\n')
    macros=dict(PACKET_BYTES=(out/'packet.bin').stat().st_size,REJECTION_BYTES=(out/'rejection.bin').stat().st_size,REJECTION_DRAW_OFFSET=offset,
        COLOR_BYTES=WIDTH*HEIGHT*4,DEPTH_BYTES=WIDTH*HEIGHT*4,STENCIL_BYTES=WIDTH*HEIGHT,WIDTH=WIDTH,HEIGHT=HEIGHT)
    (out/'metal_host_draw_fixture.h').write_text('\n'.join(f'#define HALO_DRAW_{k} {v}u' for k,v in macros.items())+'\n')
    # Reuse the established ILP32 build routine. Its fixed guest source basename
    # is a test-only snapshot alias of this new alpha guest, never a repository
    # replacement of the previous black-border proof.
    alias=snapshot/'port/macos/tests/guest_metal_black_border.c';shutil.copy2(snapshot/'port/macos/tests/guest_metal_alpha_border.c',alias);hashes[str(alias)]=sha(alias)
    symbols=black.build_guest(out,llvm,linker,plugin,snapshot);exe,_=wire.build_host(out,source_root=snapshot)
    wire.run('xcrun','clang++','-std=c++17','-fobjc-arc','-fblocks','-DHALO_MACOS=1','-Wall','-Wextra','-Werror',
        '-I'+str(snapshot/'port/macos/host'),'-I'+str(snapshot/'port/android/include'),'-c',snapshot/'port/macos/host/host_metal.mm','-o',out/'strict-host.o')
    for p,h in hashes.items():require(sha(p)==h,'Proof input changed during preparation')
    native=out/'native';native.mkdir();needed=('__host_import_table','__host_import_names','__host_import_count','halo_draw_report','halo_draw_actual_color','halo_draw_actual_depth','halo_draw_actual_stencil')
    command=[str(exe),str(out/'guest.elf'),*[hex(symbols[k]) for k in needed[:3]],'0x4000000',*[hex(symbols[k]) for k in needed[3:]],str(WIDTH),str(HEIGHT),str(native)]
    prepared=dict(kind='native_metal_alpha_border_preparation',source_sha256=hashes,artifact_sha256={str(p):sha(p) for p in out.rglob('*') if p.is_file()},
        execution_command=command,draw_cases=len(cases),sample_cases=sum(len(c['pixels']) for c in cases),guest_source_alias=dict(source='port/macos/tests/guest_metal_alpha_border.c',compiled_as=str(alias)))
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(command,indent=2))

def consume(out,returncode):
    prepared=json.loads((out/'prepared.json').read_text())
    for mapping in ('source_sha256','artifact_sha256'):
        for p,h in prepared[mapping].items():require(sha(p)==h,'Changed proof input: '+p)
    native=out/'native';record=json.loads((native/'stdout.json').read_text());raw=(native/'guest-report.bin').read_bytes();require(len(raw)==64,'Truncated raw guest report');words=struct.unpack('<16I',raw)
    require(json.loads((native/'returncode.json').read_text())==dict(returncode=returncode),'Returncode evidence differs')
    require('Metal API Validation Enabled' in (native/'stderr.log').read_text(),'Missing API Validation evidence')
    bgra=(native/'native-color-bgra.bin').read_bytes();rgba=bytearray(bgra);rgba[0::4]=bgra[2::4];rgba[2::4]=bgra[0::4];write(native/'native-color.rgba',rgba)
    expected=(out/'expected-color.rgba').read_bytes();components=(out/'expected-components.bin').read_bytes();wanted_depth=(out/'expected-depth.bin').read_bytes();depth=(native/'native-depth.bin').read_bytes()
    require(len(rgba)==len(expected)==len(components)==WIDTH*HEIGHT*4 and len(depth)==len(wanted_depth),'Wrong attachment extent')
    case_diagnostics=[]
    for case in json.loads((out/'cases.json').read_text()):
        errors=[];maximum=0;ties=0
        for p in case['pixels']:
            at=(p['y']*WIDTH+p['x'])*4
            mismatch=[c for c in range(4) if components[at+c] and rgba[at+c]!=expected[at+c]]
            depth_changed=depth[at:at+4]!=wanted_depth[at:at+4]
            if mismatch or depth_changed:errors.append(dict(x=p['x'],y=p['y'],channels=mismatch,depth_differs=depth_changed,
                actual=list(rgba[at:at+4]),expected=list(expected[at:at+4]),ideal_alpha=p['ideal_alpha_byte_units']))
            maximum=max(maximum,abs(rgba[at+3]-expected[at+3]));ties+=p['ideal_alpha_byte_units']%1==.5
        case_diagnostics.append(dict(kind=case['kind'],fast=case['fast'],lod=case['lod'],axes=case['axes'],source_texture=case['source_texture'],
            threshold_function=case.get('func'),threshold_reference=case.get('reference'),samples=len(case['pixels']),half_ties=ties,
            differing_samples=len(errors),maximum_alpha_byte_error=maximum,first_differences=errors[:20]))
    different=dict(cpu_color=sum(bool(m) and a!=b for a,b,m in zip(rgba,expected,components)),
        depth=sum(a!=b for a,b in zip(depth,wanted_depth)),stencil=sum(x!=0 for x in (native/'native-stencil.bin').read_bytes()))
    passed=returncode==0 and record.get('guest_result')==0 and record.get('guest_pointer_bits')==32 and words[0:3]==(1,3,0) and words[4]==13 and words[5]&2048 and words[6:9]==(0,0,0) and not any(different.values())
    result=dict(kind='native_metal_alpha_border_ilp32',schema_version=1,complete=True,passed=bool(passed),returncode=returncode,guest_report=list(words),
        draw_cases=prepared['draw_cases'],sample_cases=prepared['sample_cases'],atomic_rejections=words[4],different_bytes=different,
        prepared_sha256=sha(out/'prepared.json'),source_sha256=prepared['source_sha256'],case_diagnostics=case_diagnostics,
        limits=['Source-identified HUD assets; no original live resource-pointer or full-motion capture parity is inferred.',
            'RGB preservation is exact against unmodified production shader GPU draws, not an after-target upload.',
            'Alpha oracle is independent BC2 nibble decoding and bilinear texel substitution before original byte alpha testing.',
            'Synthetic sweep/mask blends use original ONE/SRCALPHA and ZERO/SRCALPHA factors; original HUD geometry/timing remains separate.',
            'Rounding mismatches are strict failures; no byte or original-parity tolerance is increased.',
            'Nearest mip/linear min and mag/anisotropy1 only; colored RGB border and elongated anisotropic footprints remain unsupported.'])
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('passed','returncode','draw_cases','sample_cases','atomic_rejections','different_bytes')},indent=2))
    require(passed,'Strict alpha-border proof failed; diagnostic preserved')
    closure=dict(kind='native_metal_alpha_border_source_closure',complete=True,passed=True,gpu_validation_layer=True,
        result_sha256=sha(out/'result.json'),source_sha256=prepared['source_sha256'],artifact_sha256={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='closure.json'})
    (out/'closure.json').write_text(json.dumps(closure,indent=2)+'\n')


FLOAT_RUNNER=r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <cstdio>
static void check(bool b,const char *s) { if(!b){fprintf(stderr,"alpha-float: %s\n",s);exit(1);} }
static NSData *read(NSString *p) { NSData *d=[NSData dataWithContentsOfFile:p];check(d!=nil,p.UTF8String);return d; }
int main(int argc,const char **argv) { @autoreleasepool {
 check(argc==3,"arguments");NSString *planPath=@(argv[1]),*out=@(argv[2]);
 NSDictionary *plan=[NSJSONSerialization JSONObjectWithData:read(planPath) options:0 error:nil];
 id<MTLDevice> device=MTLCreateSystemDefaultDevice();check(device!=nil,"device");id<MTLCommandQueue> queue=[device newCommandQueue];
 NSMutableArray *reports=[NSMutableArray new];NSMutableDictionary *pipelines=[NSMutableDictionary new];
 for(NSDictionary *group in plan[@"groups"]) {
   NSString *policy=[group[@"fast"] boolValue]?@"fast":@"safe";id<MTLComputePipelineState> pipeline=pipelines[policy];
   if(!pipeline) {
     auto options=[MTLCompileOptions new];
     options.preserveInvariance=![group[@"fast"] boolValue];
     if(@available(macOS15.0,*)) { options.mathMode=[group[@"fast"] boolValue]?MTLMathModeFast:MTLMathModeSafe;
       options.mathFloatingPointFunctions=[group[@"fast"] boolValue]?MTLMathFloatingPointFunctionsFast:MTLMathFloatingPointFunctionsPrecise; }
     else check(false,"float controls require explicit macOS15 math policy");
     NSError *error=nil;auto library=[device newLibraryWithSource:[[NSString alloc] initWithData:read(plan[@"source"]) encoding:NSUTF8StringEncoding] options:options error:&error];
     if(!library)fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);check(library!=nil,"library");
     pipeline=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"observe"] error:&error];check(pipeline!=nil,"pipeline");pipelines[policy]=pipeline;
   }
   auto td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBC2_RGBA width:64 height:64 mipmapped:YES];
   td.mipmapLevelCount=5;td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageShaderRead;auto texture=[device newTextureWithDescriptor:td];check(texture!=nil,"texture");
   for(NSDictionary *mip in group[@"mipmaps"]) { NSData *bytes=read(mip[@"file"]);NSUInteger n=[mip[@"width"] unsignedIntegerValue];
     [texture replaceRegion:MTLRegionMake2D(0,0,n,n) mipmapLevel:[mip[@"level"] unsignedIntegerValue] withBytes:bytes.bytes bytesPerRow:[mip[@"bytes_per_row"] unsignedIntegerValue]]; }
   auto sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterLinear;sd.mipFilter=MTLSamplerMipFilterNearest;
   unsigned axes=[group[@"axes"] unsignedIntValue];sd.sAddressMode=axes&1?MTLSamplerAddressModeClampToBorderColor:MTLSamplerAddressModeRepeat;
   sd.tAddressMode=axes&2?MTLSamplerAddressModeClampToBorderColor:MTLSamplerAddressModeRepeat;sd.rAddressMode=MTLSamplerAddressModeClampToEdge;
   sd.maxAnisotropy=1;sd.normalizedCoordinates=YES;sd.lodMinClamp=sd.lodMaxClamp=[group[@"lod"] floatValue];
   sd.borderColor=MTLSamplerBorderColorTransparentBlack;auto black=[device newSamplerStateWithDescriptor:sd];
   sd.borderColor=MTLSamplerBorderColorOpaqueBlack;auto opaque=[device newSamplerStateWithDescriptor:sd];check(black&&opaque,"samplers");
   NSData *coordinates=read(group[@"coordinates"]),*uniform=read(plan[@"uniforms"]);NSUInteger count=coordinates.length/8;
   auto uv=[device newBufferWithBytes:coordinates.bytes length:coordinates.length options:MTLResourceStorageModeShared];
   auto u=[device newBufferWithBytes:uniform.bytes length:uniform.length options:MTLResourceStorageModeShared];
   auto values=[device newBufferWithLength:count*16 options:MTLResourceStorageModeShared];check(uv&&u&&values,"buffers");
   auto command=[queue commandBuffer];auto encoder=[command computeCommandEncoder];[encoder setComputePipelineState:pipeline];
   [encoder setBuffer:u offset:0 atIndex:0];[encoder setBuffer:uv offset:0 atIndex:1];[encoder setBuffer:values offset:0 atIndex:2];
   uint32_t lod=[group[@"lod"] unsignedIntValue];[encoder setBytes:&lod length:4 atIndex:3];[encoder setTexture:texture atIndex:0];
   [encoder setSamplerState:black atIndex:0];[encoder setSamplerState:opaque atIndex:4];
   [encoder dispatchThreads:MTLSizeMake(count,1,1) threadsPerThreadgroup:MTLSizeMake(MIN(count,pipeline.maxTotalThreadsPerThreadgroup),1,1)];
   [encoder endEncoding];[command commit];[command waitUntilCompleted];check(command.status==MTLCommandBufferStatusCompleted,"compute execution");
   NSString *file=[group[@"name"] stringByAppendingString:@".float4"];check([[NSData dataWithBytes:values.contents length:values.length] writeToFile:[out stringByAppendingPathComponent:file] atomically:YES],"output");
   [reports addObject:@{@"file":file,@"count":@(count),@"fast":group[@"fast"]}];
 }
 NSDictionary *report=@{@"kind":@"alpha_border_float_controls",@"complete":@YES,@"device":device.name,@"groups":reports};
 NSData *data=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];check([data writeToFile:[out stringByAppendingPathComponent:@"gpu-result.json"] atomically:YES],"report");
 puts("alpha-border float controls completed");return0;
} }
'''.replace('macOS15.0','macOS 15.0').replace('return0','return 0')


def float_prepare(previous,out):
    previous=previous.resolve();old=json.loads((previous/'prepared.json').read_text())
    # Historical production sources may advance, but the actual retained input
    # artifacts used by this failed draw must still match their original hashes.
    for p,h in old['artifact_sha256'].items():require(sha(p)==h,'Historical artifact changed: '+p)
    out.mkdir(parents=True,exist_ok=False)
    production=(previous/'fragment-100.metal').read_text()
    prefix=production[:production.index('float signed_byte(')]
    prefix=prefix.replace('constant XgpuPixelUniforms &u, float2 uv)','constant XgpuPixelUniforms &u, float2 uv, uint lod)')
    prefix=prefix.replace('bias(u.texture_lod_bias[0])','level(lod)')
    kernel='''
kernel void observe(constant XgpuPixelUniforms &u [[buffer(0)]],device const float2 *uv [[buffer(1)]],
 device float4 *values [[buffer(2)]],constant uint &lod [[buffer(3)]],texture2d<float> tex [[texture(0)]],
 sampler black [[sampler(0)]],sampler opaque [[sampler(4)]],uint i [[thread_position_in_grid]]) {
 float B=tex.sample(black,uv[i],level(lod)).a;float O=tex.sample(opaque,uv[i],level(lod)).a;
 float E=sample_alpha_border0(tex,black,opaque,u,uv[i],lod).a;
 values[i]=float4(B,O,E,0);
}
'''
    write(out/'observe.metal',(prefix+kernel).encode());write(out/'float-probe.mm',FLOAT_RUNNER.encode())
    u=bytearray(608);struct.pack_into('<4f',u,528,0,0,0,70/255);write(out/'uniform.bin',u)
    groups=[];cases=json.loads((previous/'cases.json').read_text())
    for i,case in enumerate(cases):
        if case['kind'] in ('blend','threshold','derivative'):continue
        name=f'case{i}';uv=b''.join(struct.pack('<2f',p['u'],p['v']) for p in case['pixels']);write(out/(name+'.uv'),uv)
        texture='synthetic' if case['texture']==0 else 'hud_sweeper' if case['texture']==1 else 'hud_sweeper_mask'
        files=[previous/f'{texture}-mip{level}.bc2' if not case['texture'] else previous/f'{texture}-mip-{level}.bc2' for level in range(5)]
        groups.append(dict(name=name,fast=case['fast'],axes=case['axes'],lod=case['lod'],coordinates=str(out/(name+'.uv')),
            mipmaps=[dict(level=l,width=64>>l,bytes_per_row=((64>>l)//4)*16,file=str(p)) for l,p in enumerate(files)],case_index=i))
    plan=dict(source=str(out/'observe.metal'),uniforms=str(out/'uniform.bin'),groups=groups,production_draw=str(previous))
    (out/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    exe=out/'float-probe';wire.run('xcrun','clang++','-std=c++17','-O2','-fobjc-arc','-Wall','-Wextra','-Werror',out/'float-probe.mm','-framework','Foundation','-framework','Metal','-o',exe)
    files=[Path(__file__),previous/'prepared.json',previous/'result.json',previous/'native/native-color.rgba',previous/'cases.json',
        previous/'fragment-100.metal',*out.iterdir(),*[Path(m['file']) for g in groups for m in g['mipmaps']]]
    prepared=dict(kind='alpha_border_float_preparation',input_sha256={str(p):sha(p) for p in files if p.is_file()},execution_command=[str(exe),str(out/'plan.json'),str(out)])
    (out/'float-prepared.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(prepared['execution_command'],indent=2))


def float_consume(out,returncode):
    prepared=json.loads((out/'float-prepared.json').read_text())
    for p,h in prepared['input_sha256'].items():require(sha(p)==h,'Float control input changed: '+p)
    require(returncode==0 and json.loads((out/'returncode.json').read_text())==dict(returncode=0),'Float control process failed')
    require('Metal API Validation Enabled' in (out/'stderr.log').read_text(),'Missing API Validation execution')
    plan=json.loads((out/'plan.json').read_text());previous=Path(plan['production_draw']);rgba=(previous/'native/native-color.rgba').read_bytes();cases=json.loads((previous/'cases.json').read_text())
    f32=lambda v:struct.unpack('<f',struct.pack('<f',v))[0]
    reports=[];different=0;safe_math_diff=0;fused_math_diff=0;border_disagreement=0;interior_disagreement=0;count=0
    C0=f32(70/255)
    for group in plan['groups']:
        values=(out/(group['name']+'.float4')).read_bytes();case=cases[group['case_index']];require(len(values)==len(case['pixels'])*16,'Float control extent')
        examples=[];group_diff=0
        for i,p in enumerate(case['pixels']):
            B,O,E,_=struct.unpack_from('<4f',values,i*16);diff=f32(O-B);safe=f32(B+f32(C0*diff));fused=f32(B+C0*diff)
            safe_math_diff+=E!=safe;fused_math_diff+=E!=fused
            at=(p['y']*WIDTH+p['x'])*4;native=rgba[at+3];predicted=quantize(E*255);count+=1
            disagreement=native!=predicted;different+=disagreement;group_diff+=disagreement
            if disagreement:interior_disagreement+=B==O;border_disagreement+=B!=O
            if native!=quantize(p['ideal_alpha_byte_units']) and len(examples)<8:
                examples.append(dict(x=p['x'],y=p['y'],B=B,O=O,E=E,weight=diff,ideal=p['ideal_alpha_byte_units'],
                    native=native,predicted_from_float=predicted,interior=B==O,safe=safe,fused=fused))
        reports.append(dict(case_index=group['case_index'],fast=case['fast'],lod=case['lod'],axes=case['axes'],
            source_texture=case['source_texture'],samples=len(case['pixels']),native_alpha_vs_float_differences=group_diff,half_tie_examples=examples))
    result=dict(kind='alpha_border_float_controls',complete=True,passed=different==0,returncode=returncode,samples=count,
        native_alpha_vs_float_differences=different,interior_differences=interior_disagreement,border_differences=border_disagreement,
        reconstructed_vs_staged_float32_differences=safe_math_diff,reconstructed_vs_fused_float32_differences=fused_math_diff,
        reports=reports,input_sha256=prepared['input_sha256'],output_sha256={str(p):sha(p) for p in out.iterdir() if p.is_file() and p.name!='float-result.json'},
        limits=['Test-only compute instrumentation uses the retained production reconstruction arithmetic and explicit authored LOD; not a production renderer or original Xbox proof.',
            'Native fragment bytes are compared with independently observed float controls; the failed ideal half-up gate remains unchanged.',
            'Control nativeByte prediction floor(E*255+.5) is an empirical agreement check, not a universal framebuffer tie rule.'])
    (out/'float-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('passed','samples','native_alpha_vs_float_differences','reconstructed_vs_staged_float32_differences','reconstructed_vs_fused_float32_differences')},indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--consume-returncode',type=int)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--rebase-plugin',type=Path,default=ROOT/'build/macos-metal/guest_rebase.dylib');p.add_argument('--float-diagnostic-from',type=Path);p.add_argument('--consume-float',action='store_true');a=p.parse_args()
    if a.float_diagnostic_from:float_prepare(a.float_diagnostic_from,a.output.resolve())
    elif a.consume_float:require(a.consume_returncode is not None,'Need observed process exitcode');float_consume(a.output.resolve(),a.consume_returncode)
    elif a.consume_returncode is not None:consume(a.output.resolve(),a.consume_returncode)
    else:prepare(a.output.resolve(),a.llvm.resolve(),a.linker.absolute(),a.rebase_plugin.resolve())

if __name__=='__main__':main()
