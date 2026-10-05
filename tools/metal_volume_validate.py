#!/usr/bin/env python3
"""Independent authored 3D mip sampling, XYZ border, upload and atomicity proof.

The original AL8 bytes are decoded independently from Morton XYZ addresses.
Analytic expected images are never included in guest/GPU input tables.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_copy_subresource_validate as copy
import metal_host_frame_validate as frame
import metal_host_draw_validate as wire
sha,require=copy.sha,copy.require
SOURCE_SHA='0f23edd4a08b58514e0df7e67691da723b0095f74c0d94643747da7491454196'
ASSETS=ROOT/'build/metal-poc/volume-authored-oracle-assets'
RUNTIME=ROOT/'build/macos-metal/live-volume-diagnostic/dumps/native-volume-0726c000-55560139.bin'
GENERATED=ROOT/'build/metal-poc/volume-generated-project3d-component'
SHADER='''#include <metal_stdlib>
using namespace metal;
struct In { float4 position [[position]]; };
struct Out { float4 color [[color(0)]]; uint mask [[sample_mask]]; };
fragment Out xgpu_fragment(In i [[stage_in]], constant float4 *p [[buffer(0)]],
 texture3d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {
 float3 c=float3(i.position.xy/p[0].y,(p[0].z+0.5f)/p[0].y);
 if (p[0].w>0.5f) c=p[1].xyz;
 if (p[0].w>2.5f) c/=p[1].w;
 Out o;
 if (p[0].w>1.5f && p[0].w<2.5f) o.color=t.sample(s,c,gradient3d(float3(1.0f/128.0f,0,0),float3(0,1.0f/128.0f,0)));
 else o.color=t.sample(s,c,level(p[0].x));
 o.mask=0xffffffffu; return o;
}
'''

def morton(x,y,z):
    return sum(((x>>bit)&1)<<(3*bit)|((y>>bit)&1)<<(3*bit+1)|((z>>bit)&1)<<(3*bit+2) for bit in range(5))
def decode_authored():
    metadata=json.loads((ASSETS/'assets.json').read_text());raw=(ASSETS/'authored.bin').read_bytes()
    require(len(raw)==37449 and hashlib.sha256(raw).hexdigest()==SOURCE_SHA and RUNTIME.read_bytes()==raw,'Authored/runtime volume source mismatch')
    require(metadata['original_format_word']=='0x55560139' and metadata['authored_offsets']==[0,32768,36864,37376,37440,37448,37449],'Original volume header mismatch')
    result=[];offset=0
    for level in range(6):
        size=32>>level;encoded=raw[offset:offset+size**3];decoded=bytearray()
        for z in range(size):
            for y in range(size):
                for x in range(size):decoded.extend(bytes([encoded[morton(x,y,z)]])*4)
        require(bytes(decoded)==(ASSETS/f'mip-{level}.rgba').read_bytes() and hashlib.sha256(decoded).hexdigest()==metadata['decoded_rgba_sha256'][level],
                'Independent AL8 decode disagrees with separate source oracle')
        result.append(bytes(decoded));offset+=size**3
    return result
def synthetic(size,level,bgra=False):
    result=bytearray()
    for z in range(size):
        for y in range(size):
            for x in range(size):
                rgba=((16+16*x+32*y+48*z+16*level)&255,(32+32*x+16*y+64*z+32*level)&255,
                      (48+48*x+64*y+16*z+48*level)&255,224)
                result.extend((rgba[2],rgba[1],rgba[0],rgba[3]) if bgra else rgba)
    return bytes(result)
def linear_levels():
    # Distinct mip colors, with powers-of-two channel values chosen so the
    # spatial border and quarter-mip blend oracle has integral byte results.
    return [bytes((128 if n%2==0 else 0,128 if n%2 else 0,128 if (n//2)%2==0 else 0,128))*(32>>n)**3 for n in range(6)]
def linear_oracle(levels,lod,coordinate):
    lod=max(Fraction(0),min(Fraction(5),Fraction(lod)));first=lod.numerator//lod.denominator;next_=min(5,first+1);blend=lod-first
    def sample(level):
        size=32>>level;texel=[Fraction(c)*size-Fraction(1,2) for c in coordinate]
        base=[c.numerator//c.denominator for c in texel];fraction=[c-b for c,b in zip(texel,base)]
        result=[Fraction(0)]*4
        for bit in range(8):
            xyz=[base[a]+((bit>>a)&1) for a in range(3)];weight=Fraction(1)
            for axis in range(3):weight*=fraction[axis] if (bit>>axis)&1 else 1-fraction[axis]
            if all(0<=v<size for v in xyz):
                p=((xyz[2]*size+xyz[1])*size+xyz[0])*4
                for channel in range(4):result[channel]+=weight*levels[level][p+channel]
        return result
    a,b=sample(first),sample(next_);value=[x*(1-blend)+y*blend for x,y in zip(a,b)]
    require(all(x.denominator==1 for x in value),'Unsafe fractional oracle byte tie; retain strict fixture design')
    return bytes(int(x) for x in value)
def generated_programs():
    description=json.loads((GENERATED/'fixture.json').read_text());result=[]
    for path,digest in description['source_sha256'].items():require(sha(ROOT/path)==digest,'Generated PROJECT3D emitter source drift')
    for case in description['cases']:
        for field in ('key_file','fragment','vertex'):
            digest_field='key_sha256' if field=='key_file' else field+'_sha256'
            require(sha(GENERATED/case[field])==case[digest_field],'Generated PROJECT3D fixture changed')
        v=(GENERATED/case['vertex']).read_bytes();f=(GENERATED/case['fragment']).read_bytes();stage=case['stage']
        result.append((struct.pack('<10I',7,40,102+stage,1,0,0,len(v),0,len(f),0),[(20,v),(28,f)]))
    return result
def generated_sample(stage,level,coordinate,q=2):
    fixed,payloads=sample(35,1,11,level,lod_min=level,lod_max=level);fixed=bytearray(fixed)
    struct.pack_into('<I',fixed,8,102+stage)
    sampler=bytes(fixed[64:104]);fixed[32:40]=bytes(8);fixed[64:104]=bytes(40)
    struct.pack_into('<2I',fixed,32+stage*8,11,1);fixed[64+stage*40:104+stage*40]=sampler
    vs=bytearray(3120);struct.pack_into('<4f',vs,0,*[c*q for c in coordinate],q)
    ps=bytearray(608);struct.pack_into('<16f',ps,464,*([1.]*16))
    payloads[-2]=(400,bytes(vs));payloads[-1]=(404,bytes(ps));return bytes(fixed),payloads
def slice_bytes(data,size,z):return data[z*size*size*4:(z+1)*size*size*4]
def create(id,size=32,depth=32,mips=6,fmt=1,usage=1,type=3,gen=1):
    return struct.pack('<12I',10,48,id,gen,fmt,size,size,depth,type,mips,usage,0)
def upload(id,level,size,data,x=0,y=0,z=0,w=None,h=None,d=None,row=None,image=None,**changes):
    w=size if w is None else w;h=size if h is None else h;d=size if d is None else d
    row=w*4 if row is None else row;image=row*h if image is None else image
    values=[11,72,id,1,level,0,x,y,z,w,h,d,row,image,0,len(data),1,0]
    fields={'gen':3,'slice':5,'plane':16,'reserved':17,'data_size':15}
    for name,value in changes.items():values[fields[name]]=value
    return struct.pack('<18I',*values),[(56,data)]
def sample(id,size,texture,level,z=0,mode=0,coordinate=(0,0,0),border=True,q=1,**sampler_changes):
    fixed,payloads=copy.draw(id,size,101,texture=texture);fixed=bytearray(fixed)
    sampler=dict(min_filter=0,mag_filter=1,mip_filter=1,u=3 if border else 2,v=3 if border else 2,w=3 if border else 2,aniso=1,reserved=0,lod_min=0,lod_max=5)
    sampler.update(sampler_changes)
    fixed[64:104]=struct.pack('<8I2f',*[sampler[k] for k in ('min_filter','mag_filter','mip_filter','u','v','w','aniso','reserved')],sampler['lod_min'],sampler['lod_max'])
    ps=bytearray(608);struct.pack_into('<8f',ps,0,level,size,z,mode,*coordinate,q)
    payloads[-1]=(404,bytes(ps));return bytes(fixed),payloads

def partial_data():
    # Required bytes omit only unused final image/row padding.
    data=bytearray([0xcd]*80)
    for z in range(2):
        for y in range(2):
            for x in range(3):
                at=z*48+y*20+x*4;data[at:at+4]=bytes((208-16*z,112+16*y,64+16*x,224))
    return bytes(data)
def partial_expected(data):
    result=bytearray(data);source=partial_data()
    for z in range(2):
        for y in range(2):
            for x in range(3):
                at=(((1+z)*8+3+y)*8+2+x)*4;source_at=z*48+y*20+x*4
                result[at:at+4]=source[source_at:source_at+4]
    return bytes(result)

def fixture():
    authored=decode_authored();synth=[synthetic(32>>level,level) for level in range(6)]
    f=copy.Fixture();f.composite_versions=[];f.begin()
    for id,size,fmt in [(1,32,1),(2,32,3),(3,4,1)]+[(30+i,32>>i,1) for i in range(6)]:
        f.emit(copy.create(id,size,fmt=fmt,usage=2 if fmt==3 else 3));f.versions[id]=0
    for id in (10,11,12,14,80,81,95):f.emit(create(id))
    f.emit(struct.pack('<4I',2,16,95,1));f.emit(create(95,gen=2))
    f.emit(create(13,size=4,depth=4,mips=1,fmt=2))
    f.emit(copy.program(100,copy.PATTERN));f.emit(copy.program(101,SHADER))
    for p in generated_programs():f.emit(p)
    f.emit(struct.pack('<6I',12,24,200,1,2,0))
    f.emit(copy.clear(1,32,2));f.versions[1]=f.versions[2]=1
    f.emit(copy.upload(3,bytes((17,23,31,255))*16,4));f.versions[3]=1
    for level in range(6):
        size=32>>level;f.emit(copy.clear(30+level,size));f.versions[30+level]=1
        f.emit(upload(10,level,size,synth[level]));f.emit(upload(11,level,size,authored[level]))
        f.emit(upload(14,level,size,linear_levels()[level]))
        if level<5:f.emit(upload(80,level,size,synth[level]))
    f.emit(upload(13,0,4,synthetic(4,0,bgra=True)))
    f.emit(struct.pack('<4I',14,16,200,1));f.emit(copy.draw(1,32,100,0));f.versions[1]+=1;f.emit(struct.pack('<4I',15,16,200,1));f.submit()
    for texture,levels,label in ((10,synth,'synthetic'),(11,authored,'authored-original'),(11,authored,'authored-all-linear')):
        for level,data in enumerate(levels):
            size=32>>level
            for z in range(size):
                f.begin();f.emit(sample(30+level,size,texture,level,z,**(dict(min_filter=1,mip_filter=2) if label=='authored-all-linear' else {})));f.versions[30+level]+=1;f.submit()
                f.read(30+level,size,slice_bytes(data,size,z),f.versions[30+level],label=f'{label}/mip{level}/z{z}')
    f.begin();f.emit(sample(33,4,13,0,1,border=False));f.versions[33]+=1;f.submit()
    f.read(33,4,slice_bytes(synthetic(4,0),4,1),f.versions[33],label='bgra-volume-rgba-sample')
    # Closest mip selection, away from half-level ties.
    # Safe quarter controls are separate from retained failed near-half cases.
    # The ideal nearest rule is unchanged; no captured expected bytes are edited.
    for lod,selected in ((.25,0),(.75,1),(1.25,1),(1.75,2),(4.25,4),(4.75,5)):
        size=32>>selected;f.begin();f.emit(sample(30+selected,size,10,lod));f.versions[30+selected]+=1;f.submit()
        f.read(30+selected,size,slice_bytes(synth[selected],size,0),f.versions[30+selected],label=f'nearest-mip/{lod}')
    # Actual original XYZ border state, tested at every selected mip.
    for level in range(6):
        for axis in range(3):
            for side in (-1.,2.):
                coord=[.5,.5,.5];coord[axis]=side
                f.begin();f.emit(sample(35,1,11,level,mode=1,coordinate=coord));f.versions[35]+=1;f.submit()
                f.read(35,1,bytes(4),f.versions[35],label=f'authored-black-border/mip{level}/axis{axis}/{side}')
    # Forced magnification uses linear MAG with the narrow original sampler.
    # Powers-of-two weights and channels divisible by16 avoid rounding tolerance.
    for axis in range(3):
        for side in (0.,1.):
            coord=[.5/32]*3;coord[axis]=side
            xyz=[0,0,0];xyz[axis]=0 if side==0 else 31
            index=((xyz[2]*32+xyz[1])*32+xyz[0])*4;color=synth[0][index:index+4]
            f.begin();f.emit(sample(35,1,10,0,mode=2,coordinate=coord));f.versions[35]+=1;f.submit()
            f.read(35,1,bytes(c//2 for c in color),f.versions[35],label=f'linear-mag-border/axis{axis}/{side}')
    for axes in ((0,1),(0,2),(1,2),(0,1,2)):
        coord=[.5/32]*3
        for axis in axes:coord[axis]=0
        f.begin();f.emit(sample(35,1,10,0,mode=2,coordinate=coord));f.versions[35]+=1;f.submit()
        f.read(35,1,bytes(c//(2**len(axes)) for c in synth[0][:4]),f.versions[35],label=f'linear-mag-border/corner{axes}')
    for coordinate,expected,label in (((.75/32,.5/32,.5/32),(20,40,60,224),'linear-mag-interior-x'),
                                      ((.75/32,.75/32,.75/32),(40,60,80,224),'linear-mag-interior-xyz')):
        f.begin();f.emit(sample(35,1,10,0,mode=2,coordinate=coordinate));f.versions[35]+=1;f.submit()
        f.read(35,1,bytes(expected),f.versions[35],label=label)
    for request,selected,lower,upper in ((0,3,3,3),(9,5,0,5),(-2,1,1,1)):
        size=32>>selected;f.begin();f.emit(sample(30+selected,size,10,request,lod_min=lower,lod_max=upper));f.versions[30+selected]+=1;f.submit()
        f.read(30+selected,size,slice_bytes(synth[selected],size,0),f.versions[30+selected],label=f'lod-clamp/{request}/{selected}')
    for mode,lod,coordinate,expected,changes,label in (
       (1,3.5,(.125,.125,.125),(72,144,216,224),dict(mip_filter=2),'linear-mip-interpolation'),
       (1,3,(.1875,.125,.125),(68,136,204,224),dict(min_filter=1,mag_filter=1),'linear-min-interpolation')):
        f.begin();f.emit(sample(35,1,10,lod,mode=mode,coordinate=coordinate,border=False,**changes));f.versions[35]+=1;f.submit()
        f.read(35,1,bytes(expected),f.versions[35],label=label)
    coordinate=tuple((v+.5)/8*2 for v in (1,2,3));at=((3*8+2)*8+1)*4
    f.begin();f.emit(sample(35,1,10,2,mode=3,coordinate=coordinate,q=2));f.versions[35]+=1;f.submit()
    f.read(35,1,synth[2][at:at+4],f.versions[35],label='projected-coordinate-q-division')
    # Additional actual BORDER footprint: MIN/MAG/MIP all linear. Compute the
    # full 8-voxel plus two-mip sum with exact rational arithmetic.
    for lod in [Fraction(n) for n in range(6)]+[Fraction(n)+f for n in range(5) for f in (Fraction(1,4),Fraction(1,2),Fraction(3,4))]:
        size=32>>(lod.numerator//lod.denominator)
        coordinates=[(Fraction(0),Fraction(0),Fraction(0))]
        for axis in range(3):
            for edge in (Fraction(0),Fraction(1),-Fraction(1,4*size),Fraction(1)+Fraction(1,4*size)):
                coordinate=[Fraction(0)]*3;coordinate[axis]=edge;coordinates.append(tuple(coordinate))
        for coordinate in coordinates:
            expected=linear_oracle(linear_levels(),lod,coordinate)
            f.begin();f.emit(sample(35,1,14,float(lod),mode=1,coordinate=coordinate,min_filter=1,mip_filter=2));f.versions[35]+=1;f.submit()
            f.read(35,1,expected,f.versions[35],label=f'all-linear-xyz-border/lod{lod}/{coordinate}')
    for coordinate in ((Fraction(3,16),Fraction(1,8),Fraction(1,8)),(Fraction(1,8),Fraction(3,16),Fraction(1,8)),
                       (Fraction(1,8),Fraction(1,8),Fraction(3,16)),(Fraction(1,4),)*3):
        expected=linear_oracle(synth,Fraction(3),coordinate)
        f.begin();f.emit(sample(35,1,10,3,mode=1,coordinate=coordinate,min_filter=1,mip_filter=2));f.versions[35]+=1;f.submit()
        f.read(35,1,expected,f.versions[35],label=f'all-linear-interior-xyz/{coordinate}')
    for stage in range(3):
        for level in range(6):
            size=32>>level;coordinate=(.5/size,)*3
            f.begin();f.emit(generated_sample(stage,level,coordinate));f.versions[35]+=1;f.submit()
            f.read(35,1,authored[level][:4],f.versions[35],label=f'generated-project3d/stage{stage}/mip{level}/q2')
        for axis in range(3):
            coordinate=[.5]*3;coordinate[axis]=-1
            f.begin();f.emit(generated_sample(stage,4,coordinate));f.versions[35]+=1;f.submit()
            f.read(35,1,bytes(4),f.versions[35],label=f'generated-project3d/stage{stage}/black-border-axis{axis}/q2')
    updated=list(synth);updated[2]=partial_expected(synth[2])
    f.begin();f.emit(upload(10,2,8,partial_data(),x=2,y=3,z=1,w=3,h=2,d=2,row=20,image=48));f.submit()
    for z in range(8):
        f.begin();f.emit(sample(32,8,10,2,z));f.versions[32]+=1;f.submit()
        f.read(32,8,slice_bytes(updated[2],8,z),f.versions[32],label=f'padded-partial-retention/z{z}')
    baselines=[(1,32,copy.pattern(32,0),2,1),(2,32,struct.pack('<f',1)*1024,1,2),
               (2,32,bytes([7])*1024,1,4),(3,4,bytes((17,23,31,255))*16,1,1),(200,1,struct.pack('<Q',1024),1,8)]
    for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,1,slot,label='atomic-baseline')
    # An earlier valid upload must also remain uncommitted on a late failure.
    # Its actual voxel bytes deliberately differ from the positive partial box.
    marker=bytearray(partial_data())
    for z in range(2):
        for y in range(2):
            for x in range(3):marker[z*48+y*20+x*4:z*48+y*20+x*4+4]=bytes((16,224,160,240))
    valid=upload(10,2,8,bytes(marker),x=2,y=3,z=1,w=3,h=2,d=2,row=20,image=48)
    def changed_upload(**changes):
        kwargs=dict(x=2,y=3,z=1,w=3,h=2,d=2,row=20,image=48);kwargs.update(changes)
        return upload(10,2,8,partial_data(),**kwargs)
    def changed_draw(**changes):return sample(35,1,10,2,**changes)
    nonzero_border=changed_draw();badps=bytearray(nonzero_border[1][-1][1]);struct.pack_into('<f',badps,528,1)
    nonzero_border=(nonzero_border[0],nonzero_border[1][:-1]+[(404,bytes(badps))])
    cases=[('x-bounds',changed_upload(x=7),-1),('y-bounds',changed_upload(y=7),-1),('z-bounds',changed_upload(z=7),-1),
       ('overflow-z',changed_upload(z=0xffffffff),-1),('zero-depth',changed_upload(d=0),-1),
       ('row-pitch',changed_upload(row=8),-1),('image-pitch',changed_upload(image=20),-1),
       ('payload-too-short',changed_upload(data_size=79),-1),('payload-too-long',changed_upload(data_size=81),-1),
       ('slice',changed_upload(slice=1),-1),('reserved',changed_upload(reserved=1),-1),('plane',changed_upload(plane=2),-2),
       ('stale-generation',changed_upload(gen=2),-3),('deleted-generation',upload(95,2,8,partial_data(),x=2,y=3,z=1,w=3,h=2,d=2,row=20,image=48),-3),
       ('partial-uninitialized',upload(81,2,8,partial_data(),x=2,y=3,z=1,w=3,h=2,d=2,row=20,image=48),-7),
       ('missing-lowest-mip-draw',sample(35,1,80,0),-7),('nonzero-border',nonzero_border,-2),
       ('anisotropy',changed_draw(aniso=2),-2),('border-min-linear',changed_draw(min_filter=1),-2),
       ('border-mag-point',changed_draw(mag_filter=0),-2),('border-mip-linear',changed_draw(mip_filter=2),-2),
       ('wrong-reflected-type',sample(35,1,3,0,border=False),-1),
       ('volume-render-target',create(99,usage=3),-2),('volume-compressed',create(99,fmt=4),-2),
       ('volume-dimension-limit',create(99,size=513),-2),('volume-zero-depth',create(99,depth=0),-1),
       ('volume-mip-count',create(99,mips=7),-1),('volume-unknown-type',create(99,type=4),-1),
       ('nonvolume-depth',create(99,type=1),-1)]
    for label,invalid,status in cases:
        f.begin();f.emit(struct.pack('<4I',14,16,200,1));f.emit(copy.clear(1,32,2,(1,0,1,1),.25,99))
        f.emit(copy.upload(3,bytes((99,77,55,255))*4,2));f.emit(copy.draw(1,32,100,6,depth=2,half=True))
        f.emit(struct.pack('<4I',15,16,200,1));f.emit(valid);f.emit(invalid);f.submit(status,6,label)
        for slot,(id,size,e,v,p) in enumerate(baselines):f.read(id,size,e,v,p,2,slot,label=f'atomic/{label}')
        for z in (1,2):
            f.begin();f.emit(sample(32,8,10,2,z));f.versions[32]+=1;f.submit()
            f.read(32,8,slice_bytes(updated[2],8,z),f.versions[32],label=f'volume-after-reject/{label}/z{z}')
    return f

def snapshot(out):
    names=['port/macos/host/host_memory.c','port/macos/host/host.h','port/macos/host/host_metal.mm',
           'port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm','port/macos/include/halo_metal_abi.h',
           'port/android/include/halo_android_abi.h','port/macos/tests/host_metal_frame.mm','port/macos/tests/guest_metal_volume.c',
           'port/linux/src/metal_guest_transport.h','port/linux/src/metal_guest_transport.c','port/macos/metal_imports.list',
           'tools/metal_volume_validate.py','tools/metal_copy_subresource_validate.py','tools/metal_host_frame_validate.py',
           'tools/metal_host_draw_validate.py','tools/android_build.py','tools/android_imports.py','tools/android_asm_convert.py']
    records={}
    for name in names:
        source=ROOT/name;dest=out/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        digest=sha(source);shutil.copy2(source,dest);require(sha(source)==sha(dest)==digest,'Source changed during volume freeze')
        records[str(source)]=dict(snapshot=str(dest),sha256=digest)
    (out/'source-snapshot.json').write_text(json.dumps(records,indent=2)+'\n');return records

def build_guest(out,llvm,linker,plugin):
    frozen=out/'source-snapshot';tree=ast.parse((frozen/'tools/android_build.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUEST_ABI_FLAGS' for t in n.targets)]
    flags=ast.literal_eval(nodes[0].value);resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip());run=frame.run
    for name,path in [('guest','port/macos/tests/guest_metal_volume.c'),('transport','port/linux/src/metal_guest_transport.c')]:
        run(llvm/'clang',*flags,'-ffreestanding','-fno-builtin','-isystem',resource/'include','-std=gnu11','-Wall','-Wextra','-Werror',
            '-DHALO_MACOS=1','-DHALO_MACOS_NATIVE_METAL=1','-I',out,'-emit-llvm','-S',frozen/path,'-o',out/(name+'.ll'))
        run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/(name+'.ll'),'-o',out/(name+'.rebased.ll'))
        run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/(name+'.rebased.ll'),'-o',out/(name+'.darwin.s'))
        run(sys.executable,frozen/'tools/android_asm_convert.py',out/(name+'.darwin.s'),out/(name+'.s'))
    for name in ('guest','transport','fixture'):run(llvm/'clang','--target=aarch64-linux-android','-c',out/(name+'.s'),'-o',out/(name+'.o'))
    (out/'diagnostic-imports.list').write_text((frozen/'port/macos/metal_imports.list').read_text().rstrip()+'\nhost_frame_checkpoint\n')
    run(sys.executable,frozen/'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s',out/'diagnostic-imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    (out/'guest.ld').write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',out/'guest.ld',*[out/(n+'.o') for n in ('guest','transport','fixture','imports')],'-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    sections=subprocess.check_output([str(llvm/'llvm-size'),'--format=sysv',str(out/'guest.elf')],text=True)
    span=(sum(int(line.split()[1]) for line in sections.splitlines() if line.startswith(('.text ','.rodata ','.data ','.bss ')))+8*1024*1024+16383)&~16383
    return symbols,span

def prepare(out,llvm,linker,plugin):
    require(not out.exists(),'Keep historical proof; output must be fresh');out.mkdir(parents=True)
    records=snapshot(out);f=fixture()
    (out/'inputs.bin').write_bytes(f.inputs);(out/'actions.bin').write_bytes(b''.join(struct.pack('<12I',*a) for a in f.actions))
    (out/'fixture.s').write_text('.section .rodata,"a",@progbits\n.balign 16\n.global halo_volume_inputs\nhalo_volume_inputs:\n.incbin '+json.dumps(str(out/'inputs.bin'))+
        '\n.balign 16\n.global halo_volume_actions\nhalo_volume_actions:\n.incbin '+json.dumps(str(out/'actions.bin'))+'\n')
    (out/'metal_volume_fixture.h').write_text(f'#define HALO_VOLUME_ACTIONS {len(f.actions)}u\n#define HALO_VOLUME_INPUT_BYTES {len(f.inputs)}u\n#define HALO_VOLUME_PACKET_CAPACITY 1048576u\n#define HALO_VOLUME_REQUIRED_CAPS 8415u\n')
    for n,p in enumerate(f.packets):
        file=out/f'packet-{n:03}.bin';file.write_bytes(bytes.fromhex(p.pop('bytes')));p['file']=str(file);p['sha256']=sha(file)
    package=dict(schema_version=1,kind='volume_fixture',complete=True,actions=len(f.actions),packets=f.packets,readbacks=f.readbacks,
        negative_cases=f.negative,source_levels=[32,16,8,4,2,1],source_authored_sha256=SOURCE_SHA,source_runtime_sha256=sha(RUNTIME),
        expected_after_gpu_uploaded=False,required_capabilities=8415,near_half_nearest_gate=False,
        retained_near_half_failure=dict(file=str(ROOT/'build/metal-poc/volume-gpu-current-attempt1/failure-closure.json'),sha256=sha(ROOT/'build/metal-poc/volume-gpu-current-attempt1/failure-closure.json')))
    (out/'fixture.json').write_text(json.dumps(package,indent=2)+'\n');symbols,span=build_guest(out,llvm,linker,plugin);host,sources=frame.build_host(out)
    native=out/'native';native.mkdir();command=[str(host),str(out/'guest.elf'),*[hex(symbols[n]) for n in ('__host_import_table','__host_import_names','__host_import_count')],str(span),hex(symbols['halo_frame_report']),str(native)]
    dependencies=[Path(r['snapshot']) for r in records.values()]+sources+[plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,host,out/'guest.elf',out/'inputs.bin',out/'actions.bin',out/'fixture.s',
        out/'metal_volume_fixture.h',out/'diagnostic-imports.list',out/'imports.s',out/'host_import_table.c',out/'guest.ld',out/'source-snapshot.json',Path(__file__),RUNTIME,ROOT/'build/metal-poc/volume-gpu-current-attempt1/failure-closure.json']+list(ASSETS.iterdir())+list(GENERATED.iterdir())+[Path(p['file']) for p in f.packets]
    prepared=dict(schema_version=1,kind='volume_ilp32_prepared',complete=False,passed=False,fixture_sha256=sha(out/'fixture.json'),source_snapshot=records,
        source_and_binary_sha256={str(p):sha(p) for p in dependencies if p.is_file()},execution_command=command,validation_environment={'MTL_DEBUG_LAYER':'1'})
    (out/'prepared.json').write_text(json.dumps(prepared,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(out/'prepared.json'),readbacks=len(f.readbacks),negative_cases=len(f.negative),actions=len(f.actions)),indent=2))

def execute(out):
    require(not (out/'execution.json').exists(),'Preserve earlier volume execution');p,f=copy.verify_prepared(out)
    env=dict(os.environ);env.update(p['validation_environment']);run=subprocess.run(p['execution_command'],cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'native.stdout').write_text(run.stdout);(out/'native.stderr').write_text(run.stderr)
    execution=dict(schema_version=1,kind='volume_ilp32_execution',complete=True,returncode=run.returncode,command=p['execution_command'],prepared_sha256=sha(out/'prepared.json'),
        executor_sha256=sha(__file__),validation_environment=p['validation_environment'],stdout_sha256=sha(out/'native.stdout'),stderr_sha256=sha(out/'native.stderr'))
    (out/'execution.json').write_text(json.dumps(execution,indent=2)+'\n');copy.verify_prepared(out)
    dump=json.loads((out/'native/checkpoints.json').read_text());record=json.loads(run.stdout);expected={r['event']:r for r in f['readbacks']};comparisons=[]
    for actual in dump['checkpoints']:
        e=expected.pop(actual['event']);file=out/'native'/actual['file'];data=file.read_bytes();reference=bytes.fromhex(e['expected'])
        valid=all(actual[k]==e[k] for k in ('event','target_id','version','plane','bytes','width','height')) and actual['wire_content_version']==e['version'] and actual['completed_sequence']==e['sequence']
        differences=[abs(a-b) for a,b in zip(data,reference)]
        comparisons.append(dict(event=e['event'],label=e['label'],file=str(file),sha256=sha(file),expected_sha256=hashlib.sha256(reference).hexdigest(),
            different_bytes=sum(a!=b for a,b in zip(data,reference)) if len(data)==len(reference) else -1,max_delta=max(differences,default=0),metadata_valid=valid))
    report=dump['report'];validation='Metal API Validation Enabled' in run.stderr
    passed=run.returncode==0 and record.get('guest_result')==0 and report[:2]==[1,4] and not expected and validation and all(c['different_bytes']==0 and c['metadata_valid'] for c in comparisons)
    result=dict(p,complete=True,passed=passed,returncode=run.returncode,guest_run=record,guest_report=report,comparisons=comparisons,
        compared_readbacks=len(comparisons),missing_readbacks=len(expected),negative_cases=len(f['negative_cases']),gpu_api_validation_enabled=validation,
        execution=dict(file=str(out/'execution.json'),sha256=sha(out/'execution.json')),original_full_frame_gate=False,original_water_gate=False,original_cpu_query_timing_gate=False,
        near_half_nearest_gate=False,retained_near_half_failure=f['retained_near_half_failure'],
        limits=['Exact authored AL8 voxel samples and analytic synthetic XYZ/filter/border fixtures; no original game draw-output parity claim.',
                'The prior ANGLE edge-clamp fallback is not the XYZ transparent-black source oracle.',
                'Volume versions are not directly exposed by target-only readback; sampled voxel contents and visible/query versions are tested.',
                'Expected pixels stay exclusively in host CPU comparison.'])
    copy.verify_prepared(out);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    failures=[c for c in comparisons if c['different_bytes'] or not c['metadata_valid']]
    print(json.dumps(dict(passed=passed,returncode=run.returncode,guest_report=report,readbacks=len(comparisons),missing=len(expected),differences=len(failures),
                         first_difference=failures[0] if failures else None,result=str(out/'result.json')),indent=2));return 0 if passed else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','execute']);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'));p.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    p.add_argument('--plugin',type=Path,default=Path('/Users/pfista/src/halo/pfista-halo-macos/build/macos/guest_rebase.dylib'))
    a=p.parse_args()
    if a.mode=='prepare':prepare(a.out.resolve(),a.llvm,a.linker,a.plugin);return 0
    return execute(a.out.resolve())
if __name__=='__main__':sys.exit(main())
