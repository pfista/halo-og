#!/usr/bin/env python3
"""Intended original loading pass, through the production ILP32 helper/transport.

This is a separate synthetic-resource oracle, not the historical malformed UI
shader proof. Expected after images never enter guest memory or GPU uploads.
Only the explicitly labelled full-gradient diagnostic has a one-byte bound;
all register, matrix, coverage, history and atomic controls are byte-exact.
"""
import argparse
import ast
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_backbuffer_history_validate as history
import metal_copy_subresource_validate as copy
import metal_host_draw_validate as wire
import metal_host_frame_coalesce as parse
import metal_host_frame_validate as frame
import metal_shader_validate as shaders
import test_metal_fixed_function as cpu
sha,require=wire.sha,wire.require
W,H=640,480
PACKET=history.PACKET
EXPECTED_PACKET='3beca702cb0a92b553345436cbcb88e85bdc5025760b084548db7752ec17e3c8'

PATTERN='''#include <metal_stdlib>
using namespace metal;
struct In { float4 position [[position]]; };
struct Out { float4 color [[color(0)]]; uint mask [[sample_mask]]; };
fragment Out xgpu_fragment(In i [[stage_in]]) {
 uint x=uint(i.position.x), y=uint(i.position.y);
 float3 rgb=float3(16+16*((x/32)%5),32+16*((y/24)%5),48+16*((x/64+y/48)%5));
 return Out{float4(rgb/255.0f,1.0f),0xffffffffu};
}
'''


def original_routes():
    require(sha(PACKET)==EXPECTED_PACKET,'Historical original packet changed')
    sequence,records=parse.commands(PACKET.read_bytes())
    require(sequence==1398,'Wrong original capture sequence')
    routes=[]
    for program_index,draw_index,program_id in ((2,3,54),(8,9,55)):
        program,draw=records[program_index],records[draw_index]
        require(program['opcode']==7 and draw['opcode']==9 and
                struct.unpack_from('<I',program['fixed'],8)[0]==program_id,'Wrong original loading route')
        require(struct.unpack_from('<2I',draw['fixed'],376)==(4,6),'Wrong original quad')
        payload=dict(draw['payloads'])
        require(struct.unpack('<6I',payload[396])==(0,1,2,0,2,3),'Original fan indices changed')
        routes.append((program,draw))
    return routes


def source_pixel_key(name):
    source=(ROOT/'source/interface/progress_bar.c').read_text()
    pairs=re.findall(r'\b'+name+r'_shader\.([a-z_]+)(?:\[(\d+)\])?\s*=\s*(0x[0-9a-f]+|\d+)\s*;',source)
    require(len(pairs)==(12 if name=='blur' else 8),'Original shader builder changed')
    offsets=dict(alpha_inputs=0,final_combiner_inputs_abcd=8,final_combiner_inputs_efg=9,
                 alpha_outputs=26,rgb_inputs=34,rgb_outputs=45,combiner_count=53)
    key=shaders.PixelKey()
    for field,index,value in pairs:
        if field=='texture_modes':key.texture_modes=int(value,0)
        else:key.combiner_state[offsets[field]+(int(index) if index else 0)]=int(value,0)
    for stage in range(4):key.sampler_type[stage]=1
    key.fog_enable=1
    if name=='regular':key.border_axes[1]=1;key.border_filter[1]=3
    return key


class Production:
    def __init__(self,out):
        folder=out/'generated';folder.mkdir()
        prefix=folder/'fixed-prefix.h';prefix.write_text(cpu.source_prefix())
        library=folder/'fixed.dylib'
        frame.run('clang','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                  '-include',prefix,ROOT/'port/linux/src/metal_fixed_function.c','-o',library)
        self.library=C.CDLL(str(library))
        self.library.metal_fixed_function_pack_unlit_immediate.argtypes=[C.POINTER(cpu.Input),C.POINTER(cpu.Uniform),C.POINTER(cpu.Error)]
        self.library.metal_fixed_function_pack_unlit_immediate.restype=C.c_int
        self.library.metal_fixed_function_vertex_to_msl.restype=C.c_void_p
        self.vertex=shaders.generated(self.library.metal_fixed_function_vertex_to_msl).encode()
        emitter=shaders.build_library(folder)
        self.pixels={};self.keys={}
        for name in ('blur','regular'):
            key=source_pixel_key(name);self.keys[name]=key
            self.pixels[name]=shaders.generated(emitter.nv2a_pixel_shader_to_msl,C.byref(key)).encode()
        for name,data in [('fixed-vertex',self.vertex)]+[(name+'-pixel',data) for name,data in self.pixels.items()]:
            (folder/(name+'.metal')).write_bytes(data)
        for name,key in self.keys.items():(folder/(name+'-key.bin')).write_bytes(bytes(key))
        self.folder=folder

    def packed(self,base,world=None,view=None,projection=None,key=None):
        rs=(cpu.U32*144)();ts=(cpu.Row*4)()
        rs[82]=1;rs[93]=1
        if key:
            for word in range(57):rs[word]=key.combiner_state[word]
        for stage in range(4):ts[stage][28]=stage
        world=cpu.identity() if world is None else cpu.Matrix(*world)
        view=cpu.identity() if view is None else cpu.Matrix(*view)
        projection=cpu.Matrix(1,0,0,0,0,1,0,0,0,0,C.c_float(1/3).value,0,0,0,C.c_float(1/3).value,1) if projection is None else cpu.Matrix(*projection)
        original=cpu.Uniform.from_buffer_copy(base);output=cpu.Uniform();error=cpu.Error()
        data=cpu.Input(rs,ts,world,view,projection,C.pointer(original),1)
        require(self.library.metal_fixed_function_pack_unlit_immediate(C.byref(data),C.byref(output),C.byref(error))==0,
                'Production fixed helper rejected valid fixture: '+str(error.message))
        packed=bytes(output)
        parameters=bytes(rs)+bytes(ts)+bytes(world)+bytes(view)+bytes(projection)+base
        require(len(parameters)==4400 and len(packed)==3120,'Fixed helper ABI drift')
        return packed,parameters


def rgba_image(rgba):
    return bytes((rgba[2],rgba[1],rgba[0],rgba[3]))*(W*H)


def expected_rect(vertices,uniform,rgba):
    """Independent axis-aligned raster/row-matrix oracle, away from edge ties."""
    values=struct.unpack('<780f',uniform)
    matrices=[np.array(values[n*16:(n+1)*16],dtype=np.float64).reshape(4,4) for n in range(3)]
    points=[]
    for n in range(4):
        v=np.array(struct.unpack_from('<4f',vertices,n*256),dtype=np.float64)
        for matrix in matrices:v=v@matrix
        v[0]+=(.5+values[777])*v[3]/values[768];v[1]+=.5*v[3]/values[769]
        points.append(((v[0]/v[3]+1)*W/2,(1-v[1]/v[3])*H/2))
    x0=min(p[0] for p in points);x1=max(p[0] for p in points)
    y0=min(p[1] for p in points);y1=max(p[1] for p in points)
    covered=((np.arange(W)+.5>=x0)&(np.arange(W)+.5<x1))[None,:]&((np.arange(H)+.5>=y0)&(np.arange(H)+.5<y1))[:,None]
    result=np.zeros((H,W,4),dtype=np.uint8);result[:,:,3]=255
    result[covered]=[rgba[2],rgba[1],rgba[0],rgba[3]]
    return result.tobytes(),dict(bounds=[x0,y0,x1,y1],coverage=int(covered.sum()))


def gradient_image():
    y,x=np.indices((H,W),dtype=np.uint32)
    rgba=np.empty((H,W,4),dtype=np.uint8)
    rgba[:,:,0]=16+16*((x//32)%5);rgba[:,:,1]=32+16*((y//24)%5)
    rgba[:,:,2]=48+16*((x//64+y//48)%5);rgba[:,:,3]=255
    return rgba


def expected_gradient(vertices,uniform,pixel_uniform):
    # Original captured quad is affine. Interpolate all four independent
    # texture coordinates, then apply texel-center bilinear filtering in
    # double precision. This deliberately does not duplicate emitted code.
    _,bounds=expected_rect(vertices,uniform,(0,0,0,255));x0,y0,x1,y1=bounds['bounds']
    sx=(np.arange(W,dtype=np.float64)+.5-x0)/(x1-x0)
    sy=(np.arange(H,dtype=np.float64)+.5-y0)/(y1-y0)
    texture=gradient_image().astype(np.float64)/255
    scales=struct.unpack_from('<16f',pixel_uniform,464);total=np.zeros((H,W,4),dtype=np.float64)
    coordinates=[]
    for stage in range(4):
        corner=[struct.unpack_from('<4f',vertices,n*256+(9+stage)*16) for n in range(4)]
        u=corner[0][0]+(corner[1][0]-corner[0][0])*sx
        v=corner[0][1]+(corner[3][1]-corner[0][1])*sy
        fx=np.maximum(0,np.minimum(W-1,u*scales[stage*4]*W-.5))
        fy=np.maximum(0,np.minimum(H-1,v*scales[stage*4+1]*H-.5))
        ax=np.floor(fx).astype(int);ay=np.floor(fy).astype(int);bx=np.minimum(ax+1,W-1);by=np.minimum(ay+1,H-1)
        wx=(fx-ax)[None,:,None];wy=(fy-ay)[:,None,None]
        filtered=(texture[ay[:,None],ax[None,:]]*(1-wx)+texture[ay[:,None],bx[None,:]]*wx)*(1-wy)+(texture[by[:,None],ax[None,:]]*(1-wx)+texture[by[:,None],bx[None,:]]*wx)*wy
        total+=filtered*.25;coordinates.append(dict(stage=stage,first=[float(u[0]),float(v[0])],last=[float(u[-1]),float(v[-1])]))
    alpha=struct.unpack_from('<f',vertices,3*16+12)[0]
    output=np.empty((H,W,4),dtype=np.uint8)
    output[:,:,:3]=np.floor(np.clip(total[:,:,:3]*alpha,0,1)*255+.5).astype(np.uint8)
    output[:,:,3]=255
    return output[:,:,[2,1,0,3]].tobytes(),coordinates


class Fixture(history.Fixture):
    def emit_fixed(self,draw,parameters):
        super().emit(draw)
        self.actions[-1][5]=self.blob(parameters)+1

    def read_control(self,id,expected,version,label,tolerance=0,mode=0,slot=0):
        self.read_rect(id,W,H,expected,version,mode=mode,slot=slot,label=label)
        self.readbacks[-1]['maximum_byte_error']=tolerance


def fixed_draw(route,uniform,vertices=None,program=54,textures=(3,3,3,3),pixel_uniform=None):
    draw=route[1];fixed=bytearray(draw['fixed']);payload=dict(draw['payloads'])
    struct.pack_into('<2I',fixed,8,program,1)
    for stage,id in enumerate(textures):
        struct.pack_into('<2I',fixed,32+stage*8,id,1 if id else 0)
        if not id:fixed[64+stage*40:104+stage*40]=bytes(40)
    payload[400]=uniform
    if vertices is not None:payload[392]=vertices
    if pixel_uniform is not None:payload[404]=pixel_uniform
    return bytes(fixed),list(payload.items())


def constants_at(vertices,coords=None,color=None):
    result=bytearray(vertices)
    for n in range(4):
        if color:struct.pack_into('<4f',result,n*256+3*16,*color)
        if coords:
            for stage,(u,v) in enumerate(coords):struct.pack_into('<4f',result,n*256+(stage+9)*16,u,v,0,1)
    return bytes(result)


def fixture(production):
    f=Fixture();routes=original_routes();blur,regular=routes
    actual=dict(blur[1]['payloads']);regular_inputs=dict(regular[1]['payloads'])
    blur_uniform,blur_parameters=production.packed(actual[400],key=production.keys['blur'])
    regular_uniform,regular_parameters=production.packed(regular_inputs[400],key=production.keys['regular'])
    for program,data in ((54,production.pixels['blur']),(55,production.pixels['regular'])):
        require(data==dict(routes[program-54][0]['payloads'])[28],'Source-generated PS differs from captured original')
    f.begin()
    for id,fmt,w,h in ((1,2,W,H),(2,3,W,H),(3,2,W,H),(4,2,W,H),(5,2,W,H),(6,2,W,H),(7,2,320,240),(8,2,1024,16)):
        f.emit(history.create(id,w,h,fmt))
    for program,name in ((54,'blur'),(55,'regular')):
        v,p=production.vertex,production.pixels[name]
        f.emit((struct.pack('<10I',7,40,program,1,0,0,len(v),0,len(p),1),[(20,v),(28,p)]))
    f.emit(copy.program(101,PATTERN))
    f.emit(history.clear(0,depth=2));f.emit(history.clear(1));f.emit(history.clear(3))
    f.emit(history.clear(4,color=(120/255,80/255,40/255,1)))
    f.emit(history.clear(5,color=(0,80/255,0,1)));f.emit(history.clear(6,color=(0,0,0,1)))
    f.emit(history.clear(7,320,240,color=(120/255,80/255,40/255,1)))
    f.emit(history.clear(8,1024,16,color=(0,0,0,1)));f.submit()
    versions={1:1,3:1}
    f.read_control(3,rgba_image((0,0,0,255)),1,'GPU-created-startup-history-black')
    # Four independent texture stages: each constant result is exact and
    # remains distinct from the original all-stages-same-history pass.
    for stage in range(4):
        f.begin();f.emit(history.clear(1));versions[1]+=1
        textures=[6]*4;textures[stage]=4
        f.emit_fixed(fixed_draw(blur,blur_uniform,textures=textures),blur_parameters);versions[1]+=1;f.submit()
        f.read_control(1,rgba_image((27,18,9,255)),versions[1],f'exact-independent-texture-stage-{stage}')
    # GPU draw produces the source image. Only Present-like explicit copies
    # advance history, and current clear must leave the old history intact.
    synthetic=bytearray(copy.draw(3,W,101)[0]);struct.pack_into('<2f',synthetic,312,W,H);struct.pack_into('<2I',synthetic,336,W,H)
    f.begin();f.emit((bytes(synthetic),copy.draw(3,W,101)[1]));versions[3]+=1;f.submit()
    gradient=gradient_image()[:,:,[2,1,0,3]].tobytes()
    f.read_control(3,gradient,versions[3],'exact-GPU-created-gradient-history')
    blurred,coordinates=expected_gradient(actual[392],blur_uniform,actual[404])
    f.begin();f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(blur,blur_uniform),blur_parameters);versions[1]+=1;f.submit()
    f.read_control(1,blurred,versions[1],'original-unchanged-vertices-four-tap-gradient',1)
    f.read_control(3,gradient,versions[3],'history-unchanged-by-current-clear-and-blur')
    f.begin();f.emit(copy.copy(src=1,dst=3,w=W,h=H));versions[3]+=1;f.submit()
    # Copy identity is checked against the actual preceding GPU bytes, not
    # merely against the bounded analytic gradient expectation.
    f.read_control(1,blurred,versions[1],'save-actual-gradient-result',1,1,0)
    f.read_control(3,blurred,versions[3],'present-copy-bounded-gradient-actual-byte-identity',1,3,0)
    # Restore exact constant history for repeated source-order controls.
    f.begin();f.emit(history.clear(1,color=(120/255,80/255,40/255,1)));versions[1]+=1
    f.emit(copy.copy(src=1,dst=3,w=W,h=H));versions[3]+=1;f.submit()
    f.read_control(3,rgba_image((120,80,40,255)),versions[3],'present-copy-exact-constant')
    f.begin();f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(blur,blur_uniform),blur_parameters);versions[1]+=1;f.submit()
    f.read_control(1,rgba_image((108,72,36,255)),versions[1],'original-unchanged-vertices-fullscreen-constant-history')
    f.read_control(3,rgba_image((120,80,40,255)),versions[3],'skip-capture-retains-last-present')
    f.begin();f.emit(history.clear(3));versions[3]+=1
    f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(blur,blur_uniform),blur_parameters);versions[1]+=1;f.submit()
    f.read_control(1,rgba_image((0,0,0,255)),versions[1],'explicit-capture-history-clear-before-blur')
    # Four quadrant interiors establish each distinct v9..12 source route
    # without relying on ambiguous bilinear boundary rounding.
    colors=[(160,0,0,255),(0,160,0,255),(0,0,160,255),(80,80,80,255)]
    centers=[(160,120),(480,120),(480,360),(160,360)]
    f.begin()
    for (x,y),color in zip(((0,0),(320,0),(320,240),(0,240)),colors):
        c=bytearray(history.clear(3,320,240,color=tuple(v/255 for v in color)))
        struct.pack_into('<2I',c,28,x,y);f.emit(bytes(c));versions[3]+=1
    f.submit()
    for selected in range(5):
        coords=list(centers)
        if selected<4:coords[selected]=centers[(selected+1)%4]
        chosen=[colors[centers.index(value)] for value in coords]
        rgb=tuple(round(sum(value[channel] for value in chosen)/4*.9) for channel in range(3))
        f.begin();f.emit(history.clear(1));versions[1]+=1
        f.emit_fixed(fixed_draw(blur,blur_uniform,constants_at(actual[392],coords)),blur_parameters);versions[1]+=1;f.submit()
        f.read_control(1,rgba_image((*rgb,255)),versions[1],f'exact-distinct-coordinate-v{9+selected}' if selected<4 else 'exact-four-distinct-coordinate-sum')
    # Captured regular positions/registers stay unchanged. A wide constant
    # mask fixture keeps their authored T1 values inside the mask; this is
    # a register/color control, not reproduction of the old private assets.
    regular_ps=bytearray(regular_inputs[404]);struct.pack_into('<2f',regular_ps,480,1/1024,1/16)
    f.begin();f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(regular,regular_uniform,program=55,textures=(7,8,0,0),pixel_uniform=bytes(regular_ps)),regular_parameters);versions[1]+=1;f.submit()
    f.read_control(1,rgba_image((0,0,0,255)),versions[1],'original-regular-unchanged-registers-small-color')
    colored=constants_at(actual[392],[(160,120),(512,8),(480,360),(160,360)],(.25,.5,1,.5))
    f.begin();f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(regular,regular_uniform,colored,55,(7,8,0,0),bytes(regular_ps)),regular_parameters);versions[1]+=1;f.submit()
    f.read_control(1,rgba_image((15,20,20,255)),versions[1],'exact-v3-diffuse-color-and-alpha-not-stale-v9')
    # Matrix order control uses three nonidentity source-row matrices.
    world=list(cpu.identity());world[0]=world[5]=.5;world[12]=.25;world[13]=.125
    view=list(cpu.identity());view[0]=.5;view[5]=2;view[12]=-.125;view[13]=-.25
    projection=[1,0,0,0,0,1,0,0,0,0,1/3,0,0,0,1/3,1];projection[0]=2;projection[5]=.5
    transformed,parameters=production.packed(actual[400],world,view,projection,production.keys['blur'])
    matrix_vertices=constants_at(actual[392],[(320,240)]*4)
    expected,bounds=expected_rect(matrix_vertices,transformed,(27,18,9,255))
    f.begin();f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(blur,transformed,matrix_vertices,textures=(4,6,6,6)),parameters);versions[1]+=1;f.submit()
    f.read_control(1,expected,versions[1],'exact-world-view-projection-row-order-coverage')
    half=bytearray(matrix_vertices)
    for n,(x,y) in enumerate(((100.25,80.25),(164.25,80.25),(164.25,144.25),(100.25,144.25))):
        struct.pack_into('<4f',half,n*256,x/(W/2)-1,1-y/(H/2),.5,1)
    expected,half_bounds=expected_rect(half,blur_uniform,(27,18,9,255))
    require(half_bounds['coverage']==4096,'Half-pixel control became ambiguous')
    f.begin();f.emit(history.clear(1));versions[1]+=1
    f.emit_fixed(fixed_draw(blur,blur_uniform,bytes(half),textures=(4,6,6,6)),blur_parameters);versions[1]+=1;f.submit()
    f.read_control(1,expected,versions[1],'exact-half-pixel-bridge-quarter-offset-rectangle')
    baseline=[(1,expected,versions[1],1),(3,None,versions[3],1),(2,struct.pack('<f',.75)*(W*H),1,2),(2,bytes([91])*(W*H),1,4)]
    # Actual quadrant history is independently constructed from four clears.
    q=np.empty((H,W,4),dtype=np.uint8)
    for (x,y),color in zip(((0,0),(320,0),(320,240),(0,240)),colors):q[y:y+240,x:x+320]=[color[2],color[1],color[0],color[3]]
    baseline[1]=(3,q.tobytes(),versions[3],1)
    for slot,(id,data,version,plane) in enumerate(baseline):
        f.read_rect(id,W,H,data,version,plane,1,slot,label='atomic-baseline');f.readbacks[-1]['maximum_byte_error']=0
    for label,invalid in [('late-invalid-copy',copy.copy(src=1,dst=3,w=W+1,h=H))]:
        f.begin();f.emit(history.clear(1,color=(1,0,1,1)));f.emit(invalid);f.submit(-1,1,label)
        for slot,(id,data,version,plane) in enumerate(baseline):
            f.read_rect(id,W,H,data,version,plane,2,slot,label='atomic-retention/'+label);f.readbacks[-1]['maximum_byte_error']=0
    return f,dict(gradient_coordinates=coordinates,nonidentity_matrix_control=bounds,half_pixel_control=half_bounds,
                  original_vertices_sha256={name:hashlib.sha256(dict(route[1]['payloads'])[392]).hexdigest() for name,route in zip(('blur','regular'),routes)})


def snapshot(out):
    records=history.snapshot(out)
    names=['tools/metal_fixed_function_validate.py','port/macos/tests/guest_metal_fixed_function.c',
           'port/linux/src/metal_fixed_function.c','port/linux/src/metal_fixed_function.h',
           'port/linux/src/metal_draw_state.h','port/linux/src/xgpu.h','port/linux/src/platform.h',
           'port/linux/src/xgpu_msl.h','port/linux/src/nv2a_vsh.c','port/linux/src/nv2a_psh.c',
           'port/linux/src/xgpu_shader_standalone.h','port/macos/metal-poc/shader_text.c','port/include/xdk/xdk_pdb.h',
           'source/interface/progress_bar.c','port/linux/src/d3d8_resources.c','tools/test_metal_fixed_function.py','tools/metal_shader_validate.py']
    for name in names:
        source=ROOT/name;dest=out/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        digest=sha(source);shutil.copyfile(source,dest);require(sha(source)==sha(dest)==digest,'Source changed during freeze')
        records[str(source)]=dict(snapshot=str(dest),sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records


def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    require(len(nodes)==1,'Guest ABI flags missing');flags=ast.literal_eval(nodes[0].value)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    include=out/'freestanding';include.mkdir()
    (include/'math.h').write_text('#define isfinite(x) __builtin_isfinite(x)\n')
    (include/'string.h').write_text('void *memcpy(void*,const void*,unsigned long);\n')
    (include/'stdlib.h').write_text('void *malloc(unsigned long);\n')
    (out/'fixed-prefix.h').write_text(cpu.source_prefix())
    (out/'fixed-wrapper.c').write_text('#include "'+str(frozen/'port/linux/src/metal_fixed_function.c')+'"\n')
    for name,path in [('guest',frozen/'port/macos/tests/guest_metal_fixed_function.c'),('transport',frozen/'port/linux/src/metal_guest_transport.c'),('fixed',out/'fixed-wrapper.c')]:
        extra=['-include',out/'fixed-prefix.h','-I',include] if name in ('guest','fixed') else []
        frame.run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
            '-DHALO_MACOS=1','-DHALO_MACOS_NATIVE_METAL=1','-I',out,*extra,'-emit-llvm','-S',path,'-o',out/(name+'.ll'))
        frame.run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/(name+'.ll'),'-o',out/(name+'.rebased.ll'))
        frame.run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/(name+'.rebased.ll'),'-o',out/(name+'.darwin.s'))
        frame.run(sys.executable,frozen/'tools/android_asm_convert.py',out/(name+'.darwin.s'),out/(name+'.s'))
    for name in ('guest','transport','fixed','fixture'):frame.run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    (out/'diagnostic-imports.list').write_text((frozen/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n')
    frame.run(sys.executable,frozen/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    frame.run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    frame.run(linker,'-m','aarch64elf','-T',out/'guest.ld',*[out/(n+'.o') for n in ('guest','transport','fixed','fixture','imports')],'-o',out/'guest.elf')
    symbols={line.split()[2]:int(line.split()[0],16) for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines() if len(line.split())==3}
    sizes=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sizes.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    require(span<=512*1024*1024,'Fixture exceeds bounded guest arena');return symbols,span


def prepare(out,llvm,linker,plugin):
    require(not out.exists(),'Output must be fresh');out.mkdir(parents=True)
    records=snapshot(out);production=Production(out);f,controls=fixture(production)
    (out/'inputs.bin').write_bytes(f.inputs);actions=out/'actions.bin';actions.write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_fixed_inputs\nhalo_fixed_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+'\n.balign 16\n.global halo_fixed_actions\nhalo_fixed_actions:\n.incbin '+json.dumps(str(actions))+'\n')
    (out/'metal_fixed_function_fixture.h').write_text(f'#define HALO_FIXED_ACTIONS {len(f.actions)}u\n#define HALO_FIXED_INPUT_BYTES {len(f.inputs)}u\n#define HALO_FIXED_PACKET_CAPACITY 8388608u\n#define HALO_FIXED_SCRATCH 1228800u\n#define HALO_FIXED_REQUIRED_CAPS 4319u\n')
    for n,p in enumerate(f.packets):
        path=out/f'packet-{n:03}.bin';path.write_bytes(bytes.fromhex(p.pop('bytes')));p['file']=str(path);p['sha256']=sha(path)
    expected=[]
    for n,r in enumerate(f.readbacks):
        path=out/f'expected-{n:03}.bin';path.write_bytes(bytes.fromhex(r.pop('expected')))
        r.update(expected_file=str(path),expected_sha256=sha(path));expected.append(path)
    package=dict(schema_version=1,kind='intended_fixed_loading_fixture',complete=True,actions=len(f.actions),packets=f.packets,
        readbacks=f.readbacks,negative_cases=f.negative,controls=controls,expected_after_gpu_uploaded=False,
        fixed_vertex_compiler_contract=0,original_pixel_compiler_contract=1,frontend_executed=False,
        physical_xbox_fixed_function_gate=False,live_map_transition_gate=False,
        limits=['Original captured blur and regular vertices/registers are unchanged in their labelled cases.',
                'All textures are synthetic GPU clears/draws; this is not a private loading-art comparison.',
                'Only the full-gradient filtered blur oracle has a declared maximum one-byte error; exact controls stay strict.',
                'The ILP32 guest recomputes every fixed draw uniform with the production CPU helper before actual transport submission.'])
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n')
    symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out);native=out/'native';native.mkdir()
    command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    paths=[Path(r['snapshot']) for r in records.values()]+sources+[Path(__file__),plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',actions,out/'fixture.s',out/'metal_fixed_function_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json',out/'fixed-prefix.h',out/'fixed-wrapper.c']+[Path(p['file']) for p in f.packets]+expected+list((out/'generated').glob('*'))+list((out/'freestanding').glob('*'))
    for path,row in records.items():require(sha(path)==row['sha256'],'Current source changed during preparation')
    prepared=dict(schema_version=1,kind='intended_fixed_loading_prepared',complete=False,passed=False,gpu_executed=False,
        fixture_sha256=sha(out/'fixture.json'),source_snapshot=records,source_and_binary_sha256={str(p):sha(p) for p in paths},
        execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(out/'prepared.json'),readbacks=len(f.readbacks),fixed_helper_pack_calls=sum(a[0]==2 and bool(a[5]) for a in f.actions),execution_command=command),indent=2))


def verify(out):
    p=json.loads((out/'prepared.json').read_text());f=json.loads((out/'fixture.json').read_text())
    require(sha(out/'fixture.json')==p['fixture_sha256'],'Fixture changed')
    for path,digest in p['source_and_binary_sha256'].items():require(sha(path)==digest,'Frozen input changed: '+path)
    for path,row in p['source_snapshot'].items():require(sha(path)==sha(row['snapshot'])==row['sha256'],'Source drift: '+path)
    return p,f


def execute(out):
    require(not (out/'execution.json').exists(),'Preserve prior execution');p,f=verify(out)
    env=dict(os.environ);env.update(p['validation_environment'])
    observed=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(observed.stdout);(out/'native.stderr').write_text(observed.stderr)
    record=dict(schema_version=1,kind='intended_fixed_loading_execution',complete=True,returncode=observed.returncode,
                command=p['execution_command'],prepared_sha256=sha(out/'prepared.json'),executor_sha256=sha(__file__),
                validation_environment=p['validation_environment'],stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');verify(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());run=json.loads(observed.stdout)
    expected={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=expected.pop(actual['event']);file=out/'native'/actual['file'];data=file.read_bytes();reference=Path(e['expected_file']).read_bytes()
        metadata=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        require(len(data)==len(reference),'Readback byte extent mismatch')
        differences=np.abs(np.frombuffer(data,np.uint8).astype(np.int16)-np.frombuffer(reference,np.uint8).astype(np.int16))
        maximum=int(differences.max(initial=0));bound=e['maximum_byte_error']
        comparisons.append(dict(event=e['event'],label=e['label'],file=str(file),sha256=sha(file),expected_sha256=e['expected_sha256'],different_bytes=int(np.count_nonzero(differences)),maximum_byte_error=maximum,allowed_maximum_byte_error=bound,metadata_valid=metadata,passed=metadata and maximum<=bound))
    validation='Metal API Validation Enabled' in observed.stderr
    expected_packs=sum(a[0]==2 and bool(a[5]) for a in [struct.unpack_from('<12I',(out/'actions.bin').read_bytes(),n*48) for n in range(f['actions'])])
    passed=observed.returncode==0 and run.get('guest_result')==0 and dump['report'][:2]==[1,4] and dump['report'][12]==expected_packs and not expected and validation and all(c['passed'] for c in comparisons)
    result=dict(p,complete=True,passed=passed,gpu_executed=True,returncode=observed.returncode,guest_run=run,guest_report=dump['report'],comparisons=comparisons,compared_readbacks=len(comparisons),missing_readbacks=len(expected),gpu_api_validation_enabled=validation,execution_sha256=sha(out/'execution.json'),frontend_executed=False,physical_xbox_fixed_function_gate=False,live_map_transition_gate=False,full_game_gate=False,limits=f['limits'])
    verify(out);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=passed,returncode=observed.returncode,readbacks=len(comparisons),fixed_helper_pack_calls=dump['report'][12],first_difference=next((c for c in comparisons if not c['passed']),None)),indent=2));return 0 if passed else 1


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','execute']);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));parser.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    parser.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    a=parser.parse_args();out=a.out.resolve()
    if a.mode=='prepare':prepare(out,a.llvm,a.linker.absolute(),a.plugin);return 0
    return execute(out)


if __name__=='__main__':sys.exit(main())
