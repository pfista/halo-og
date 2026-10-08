#!/usr/bin/env python3
"""Submit one actual Xbox NV2A draw through the real ILP32 Metal host imports.

Wire inputs come only from the hashed actual-draw replay. The independent ANGLE
after-target buffers are embedded for guest comparison, never renderer uploads.
Original packed registers, authored mips and pinned per-stage compiler policy stay
intact. This is an isolated transport/draw proof, not a complete game frame.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import metal_draw_compare as comparison

def require(value,message):
    if not value:raise ValueError(message)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def payload(root,descriptor):
    _,data=comparison.checked_payload(root,descriptor);return data

def enum(value,names,label,first=0):
    require(type(value) is str and value in names,f'Unsupported {label}: {value}')
    return names.index(value)+first

def u32(value,label):
    require(type(value) is int and 0<=value<2**32,f'Invalid {label}')
    return value

def boolean(value,label):
    require(type(value) is bool,f'Missing boolean {label}');return int(value)

def finite(value,label):
    require(type(value) in (int,float) and math.isfinite(value),f'Invalid {label}')
    return value

ATTRIBUTE_BYTES={0x02:0,0x12:4,0x22:8,0x32:12,0x72:12,0x42:16,0x40:4,0x16:4,
                 0x11:2,0x15:2,0x21:4,0x25:4,0x31:6,0x35:6,0x41:8,0x45:8,
                 0x14:1,0x24:2,0x34:3,0x44:4}

def fetch_attribute(data,kind):
    require(kind in ATTRIBUTE_BYTES and len(data)==ATTRIBUTE_BYTES[kind],'Unknown/truncated vertex fetch format')
    out=bytearray(struct.pack('<4f',0,0,0,1))
    if kind==0x16:out[:4]=data;return bytes(out) # Preserve original packed word, including any float-NaN bit pattern.
    if kind==0x40:return struct.pack('<4f',data[2]/255,data[1]/255,data[0]/255,data[3]/255)
    count=3 if kind==0x72 else kind>>4;format_id=kind&15
    for component in range(count):
        if format_id==2:
            raw=data[component*4:component*4+4]
            require(math.isfinite(struct.unpack('<f',raw)[0]),'Nonfinite original vertex input')
            out[component*4:component*4+4]=raw
        else:
            if format_id in (1,5):
                value=struct.unpack_from('<h',data,component*2)[0]
                value=max(-1,value/32767) if format_id==1 else value
            elif format_id==4:value=data[component]/255
            else:raise ValueError('Unverified vertex fetch format')
            struct.pack_into('<f',out,component*4,value)
    return bytes(out)

def geometry(root,manifest):
    draw=manifest['draw'];declaration=manifest['vertex_declaration'];streams={}
    for stream in manifest['vertex_streams']:
        number=u32(stream['stream'],'stream');require(number not in streams,'Duplicate stream')
        streams[number]=(stream,payload(root,stream))
    if draw['indexed']:
        indices=payload(root,draw['index_buffer']);size={'uint16':2,'uint32':4}.get(draw['index_type'])
        require(size and draw['index_offset_bytes']%size==0,'Unknown/misaligned original index type')
        start=draw['index_offset_bytes'];count=draw['index_count']
        require(count>0 and start+count*size<=len(indices),'Truncated original indices')
        raw=[value[0]+draw.get('base_vertex',0) for value in struct.iter_unpack('<H' if size==2 else '<I',indices[start:start+count*size])]
    else:
        require(draw.get('base_vertex',0)==0,'Nonindexed base vertex is unsupported')
        raw=list(range(draw['vertex_start'],draw['vertex_start']+draw['vertex_count']))
    require(raw and min(raw)>=0 and max(raw)<2**32,'Invalid original vertex range')
    first,last=min(raw),max(raw);require(last-first<1024*1024,'Original vertex range exceeds wire bound')
    attributes=manifest['fixed_attributes']
    if isinstance(attributes,dict):fixed=payload(root,attributes)
    else:
        require(isinstance(attributes,list) and len(attributes)==16 and
                all(isinstance(v,list) and len(v)==4 for v in attributes),'Missing16 fixed input registers')
        fixed=struct.pack('<64f',*[finite(x,'fixed input register') for v in attributes for x in v])
    require(len(fixed)==256,'Missing16 fixed input registers')
    packed=declaration['packed_mask'];fixed=bytearray(fixed)
    for reg in range(16):
        if packed&(1<<reg):fixed[reg*16:reg*16+16]=struct.pack('<4f',0,0,0,1)
    vertices=bytearray(fixed*(last-first+1));seen=set();decoded_mask=0
    for element in declaration['elements']:
        reg=element['register'];kind=element['type']
        require(0<=reg<16 and reg not in seen and kind in ATTRIBUTE_BYTES,'Unsupported/duplicate original declaration')
        seen.add(reg);decoded_mask|=(1<<reg) if kind==0x16 else 0
        if not ATTRIBUTE_BYTES[kind] or element['stream'] not in streams:continue
        description,data=streams[element['stream']]
        for index,vertex in enumerate(range(first,last+1)):
            relative=vertex-description.get('first_vertex',0)
            require(relative>=0,'Original stream origin exceeds referenced vertex')
            offset=description.get('offset',0)+element['offset']+relative*description['stride'];length=ATTRIBUTE_BYTES[kind]
            require(offset>=0 and offset+length<=len(data),'Vertex fetch exceeds captured stream')
            vertices[index*256+reg*16:index*256+reg*16+16]=fetch_attribute(data[offset:offset+length],kind)
    require(decoded_mask==packed,'Original packed-mask/declaration mismatch')
    raw=[i-first for i in raw];primitive=draw['primitive']
    if primitive=='quad':
        require(len(raw)%4==0,'Incomplete original quadlist')
        raw=[raw[i+j] for i in range(0,len(raw),4) for j in (0,1,2,0,2,3)];primitive='triangle'
    elif primitive=='triangle_fan':
        require(len(raw)>=3,'Incomplete original triangle fan')
        raw=[v for i in range(1,len(raw)-1) for v in (raw[0],raw[i],raw[i+1])];primitive='triangle'
    elif primitive=='line_loop':raw.append(raw[0]);primitive='line_strip'
    code=enum(primitive,('point','line','line_strip','triangle','triangle_strip'),'primitive')
    require(primitive!='triangle' or len(raw)%3==0,'Incomplete original triangle list')
    require(primitive!='line' or len(raw)%2==0,'Incomplete original line list')
    return bytes(vertices),struct.pack('<'+'I'*len(raw),*raw),packed,code,first

def state_bytes(state):
    comparisons=('never','less','equal','less_equal','greater','not_equal','greater_equal','always')
    stencil_ops=('keep','zero','replace','increment_clamp','decrement_clamp','invert','increment_wrap','decrement_wrap')
    blend_factors=('zero','one','source_color','one_minus_source_color','source_alpha','one_minus_source_alpha',
        'destination_alpha','one_minus_destination_alpha','destination_color','one_minus_destination_color',
        'source_alpha_saturated','blend_color','one_minus_blend_color','blend_alpha','one_minus_blend_alpha')
    blend=state['blend'];depth=state['depth'];stencil=state['stencil'];raster=state['raster']
    require(raster['fill']=='solid','Wire draw fill mode is unsupported')
    values=[u32(blend['write_mask'],'color write mask'),boolean(blend['enabled'],'blend enable'),
        enum(blend['source'],blend_factors,'blend source',1),enum(blend['destination'],blend_factors,'blend destination',1),
        enum(blend['operation'],('add','subtract','reverse_subtract','min','max'),'blend operation',1),
        boolean(depth['enabled'],'depth enable'),boolean(depth['write'],'depth write'),enum(depth['compare'],comparisons,'depth comparison',1),
        boolean(stencil['enabled'],'stencil enable'),enum(stencil['compare'],comparisons,'stencil comparison',1),
        u32(stencil['read_mask'],'stencil read mask'),u32(stencil['write_mask'],'stencil write mask'),
        enum(stencil['fail'],stencil_ops,'stencil failure',1),enum(stencil['depth_fail'],stencil_ops,'stencil depth failure',1),
        enum(stencil['pass'],stencil_ops,'stencil pass',1),u32(stencil['reference'],'stencil reference'),
        enum(raster['front_face'],('cw','ccw'),'front face'),enum(raster['cull'],('none','front','back'),'culling'),0,0]
    viewport=[finite(state['viewport'][name],'viewport') for name in ('x','y','width','height','znear','zfar')]
    scissor=[u32(state['scissor'][name],'scissor') for name in ('x','y','width','height')]
    bias=[finite(raster[name],'depth bias') for name in ('depth_bias','slope_scale','depth_bias_clamp')]+[0.]
    color=blend.get('color',[0.,0.,0.,0.]);require(len(color)==4,'Invalid blend color')
    return struct.pack('<20I6f4I8f',*values,*viewport,*scissor,*bias,*color)

def sampler_bytes(sampler):
    if sampler is None:return bytes(40)
    values=[enum(sampler[name],('nearest','linear'),name) for name in ('min_filter','mag_filter')]
    values+=[enum(sampler['mip_filter'],('none','nearest','linear'),'mip filter')]
    values+=[enum(sampler['address_'+axis],('repeat','mirror_repeat','clamp_to_edge'),'address '+axis) for axis in 'uvw']
    values+=[u32(sampler['max_anisotropy'],'anisotropy'),0]
    return struct.pack('<8I2f',*values,finite(sampler['lod_min'],'LOD min'),finite(sampler['lod_max'],'LOD max'))

class Packet:
    def __init__(self,sequence):self.data=bytearray(24);self.count=0;self.sequence=sequence
    def command(self,fixed,payloads=()):
        start=len(self.data);body=bytearray(fixed)
        for offset_field,data in payloads:
            body.extend(bytes((-(start+len(body)))&15));offset=start+len(body)
            struct.pack_into('<I',body,offset_field,offset);body.extend(data)
        body.extend(bytes((-len(body))&7));struct.pack_into('<I',body,4,len(body))
        self.data.extend(body);self.count+=1
    def finish(self):
        require(len(self.data)<=64*1024*1024,'Wire packet exceeds64MB')
        struct.pack_into('<4IQ',self.data,0,0x4c544d48,1,len(self.data),self.count,self.sequence)
        return bytes(self.data)

def wire_packet(root,manifest):
    target=manifest['target'];width,height=target['width'],target['height']
    require(target['color_format']=='bgra8unorm' and target['depth_format']=='depth32float_stencil8','Unsupported transport target format')
    require(target['orientation']=='top_left','Unverified target orientation')
    # Only genuinely cleared initial targets are supported by this first draw
    # probe. Independent after-target references can never enter packet data.
    for name,size,clear in (('color',4,bytes(round(c*255) for c in target['clear_color'])),
                            ('depth',4,struct.pack('<f',target['clear_depth'])),
                            ('stencil',1,bytes([target['clear_stencil']]))):
        descriptor=target.get('initial_'+name)
        if descriptor is not None:require(payload(root,descriptor)==clear*(width*height),'Initial target is not the declared independent clear')
    packet=Packet(1)
    for resource,format_id in ((1,2),(2,3)):
        packet.command(struct.pack('<12I',10,48,resource,1,format_id,width,height,1,1,1,2,0))
    texture_refs=[]
    for slot,texture in enumerate(manifest['textures']):
        if texture is None:texture_refs.append((0,0));continue
        resource=10+slot;texture_refs.append((resource,1))
        format_id={'rgba8unorm':1,'bc1_rgba':4,'bc2_rgba':5,'bc3_rgba':6}.get(texture['pixel_format']);require(format_id,'Unverified wire sampled texture format')
        texture_type={'2d':1,'cube':2}.get(texture['type']);require(texture_type,'Unverified wire texture dimension')
        packet.command(struct.pack('<12I',10,48,resource,1,format_id,texture['width'],texture['height'],1,
            texture_type,len(texture['mipmaps']),1,0))
        for level,mip in enumerate(texture['mipmaps']):
            faces=mip['faces'] if texture_type==2 else [dict(mip,face=0)]
            require(texture_type!=2 or sorted(face['face'] for face in faces)==list(range(6)),
                    'Cube mip must contain all six unique faces')
            for face in faces:
                data=payload(root,face)
                fixed=struct.pack('<18I',11,72,resource,1,level,face['face'],0,0,0,mip['width'],mip['height'],1,
                    face['bytes_per_row'],face['bytes_per_image'],0,len(data),1,0)
                packet.command(fixed,[(56,data)])
    clear=struct.pack('<12I5fI',4,72,1,1,2,1,7,0,0,width,height,target['clear_stencil'],
                      *target['clear_color'],target['clear_depth'],0);packet.command(clear)
    shaders=manifest['shaders'];require(shaders['vertex']['entry']=='xgpu_vertex' and shaders['fragment']['entry']=='xgpu_fragment','Unknown generated entrypoint')
    from metal_draw_replay import fragment_wire_contract
    fragment_contract=fragment_wire_contract(shaders['fragment'],lambda descriptor:payload(root,descriptor))
    policy=shaders['vertex'].get('compile_options');contract=0
    if policy is not None:
        require(policy==dict(contract='angle_metal_invariant_fast_v1',fast_math=True,preserve_invariance=True,
            math_mode='fast',floating_point_functions='fast'),'Unverified vertex compiler policy')
        require('compiler_evidence' in shaders['vertex'] and 'compiler_baseline' in shaders['vertex'],'Missing pinned compiler evidence')
        contract=1
    vertex=payload(root,shaders['vertex']);fragment=payload(root,shaders['fragment'])
    packet.command(struct.pack('<10I',7,40,100,1,contract,0,len(vertex),0,len(fragment),fragment_contract),[(20,vertex),(28,fragment)])
    vertices,indices,packed,primitive,first=geometry(root,manifest)
    uniforms=manifest['uniforms'];vu=payload(root,uniforms['vertex']);pu=payload(root,uniforms['pixel'])
    require(len(vu)==3120 and len(pu)==608,'Unknown generated uniform ABI')
    fixed=struct.pack('<16I',9,416,100,1,1,1,2,1,*[word for pair in texture_refs for word in pair])
    fixed+=b''.join(sampler_bytes(t['sampler'] if t else None) for t in manifest['textures'])
    fixed+=state_bytes(manifest['render_state'])
    fixed+=struct.pack('<10I',len(vertices)//256,len(indices)//4,packed,primitive,0,0,0,0,0,0)
    require(len(fixed)==416,'Wire DRAW layout mismatch')
    packet.command(fixed,[(392,vertices),(396,indices),(400,vu),(404,pu)])
    return packet.finish(),dict(vertices=len(vertices)//256,indices=len(indices)//4,packed_mask=packed,source_first_vertex=first,command_count=packet.count)

def rejection_packet(original,width,height):
    """Copy the actual DRAW into CLEAR+DRAW, relocating its four payloads.

    The clear deliberately changes all attachments if preflight is not atomic.
    No new shaders, textures, vertices, uniforms, or after-target data enter it.
    """
    require(len(original)>=24,'Truncated original packet')
    magic,version,size,count,sequence=struct.unpack_from('<4IQ',original)
    require((magic,version,size)==(0x4c544d48,1,len(original)),'Invalid original packet')
    commands=[];position=24
    for _ in range(count):
        require(position+8<=size,'Truncated original command')
        opcode,length=struct.unpack_from('<2I',original,position)
        require(length>=8 and length%8==0 and position+length<=size,'Invalid original command extent')
        commands.append((opcode,position,length));position+=length
    require(position==size and commands and commands[-1][0]==9,'Original packet does not end with actual DRAW')
    _,position,length=commands[-1]
    require(length>=416,'Truncated original DRAW')
    fixed=original[position:position+416]
    vertices,indices=struct.unpack_from('<2I',fixed,376)
    payloads=[]
    for field,extent in ((392,vertices*256),(396,indices*4),(400,3120),(404,608)):
        offset=struct.unpack_from('<I',fixed,field)[0]
        require(extent>0 and offset%16==0 and position+416<=offset and offset+extent<=position+length,
                'Original DRAW payload exceeds command')
        payloads.append((field,original[offset:offset+extent]))
    packet=Packet(sequence+1)
    packet.command(struct.pack('<12I5fI',4,72,1,1,2,1,7,0,0,width,height,165,1.,0.,1.,1.,0.,0))
    draw_offset=len(packet.data);packet.command(fixed,payloads)
    result=packet.finish()
    offsets=dict(draw=draw_offset,vertices=struct.unpack_from('<I',result,draw_offset+392)[0],
        indices=struct.unpack_from('<I',result,draw_offset+396)[0],
        vertex_uniforms=struct.unpack_from('<I',result,draw_offset+400)[0],
        pixel_uniforms=struct.unpack_from('<I',result,draw_offset+404)[0])
    return result,offsets

def run(*args):
    subprocess.run([str(value) for value in args],cwd=ROOT,check=True)

def build_fixture(input_manifest,reference_path,out,negative_preflight=False):
    original=comparison.load_manifest(input_manifest)
    from metal_draw_replay import fragment_wire_contract
    fragment_wire_contract(original['shaders']['fragment'],lambda d:payload(input_manifest.parent,d))
    # Regenerate from the actual capture rather than trust edited prepared
    # source/asset descriptors merely because they have internally valid SHAs.
    from metal_draw_replay import prepare
    evidence=original['shaders']['vertex'].get('compiler_evidence')
    evidence_path=(input_manifest.parent/evidence['file']).resolve() if evidence else None
    fragment_evidence=original['shaders']['fragment'].get('compiler_evidence')
    fragment_evidence_path=(input_manifest.parent/fragment_evidence['file']).resolve() if fragment_evidence else None
    replay=out/'replay';replay.mkdir(exist_ok=True)
    prepare(Path(original['source_capture']['file']),replay,vertex_compiler_evidence=evidence_path,
            fragment_compiler_evidence=fragment_evidence_path)
    replay_path=replay/'replay.json';manifest=comparison.load_manifest(replay_path)
    reference,attachments=comparison.load_result(reference_path,replay_path,manifest,'angle')
    require(set(attachments)=={'color','depth','stencil'},'All three independent attachments are required')
    require(reference.get('actual_depth_format')=='depth32float_stencil8','Independent backing depth format is not verified')
    packet,geometry_info=wire_packet(replay,manifest)
    (out/'packet.bin').write_bytes(packet)
    symbols={'halo_draw_packet':out/'packet.bin'}
    for name,data in attachments.items():
        file=out/f'expected-{name}.bin';file.write_bytes(data);symbols['halo_draw_expected_'+name]=file
    negative_offsets={}
    if negative_preflight:
        rejection,negative_offsets=rejection_packet(packet,manifest['target']['width'],manifest['target']['height'])
        file=out/'rejection-template.bin';file.write_bytes(rejection);symbols['halo_draw_rejection_template']=file
    assembly=['.section .rodata,"a",@progbits']
    for name,file in symbols.items():
        # JSON quotes provide assembler string escaping, not shell execution.
        assembly+=['.balign 16',f'.global {name}',f'{name}:',f'.incbin {json.dumps(str(file))}']
    (out/'fixture.s').write_text('\n'.join(assembly)+'\n')
    target=manifest['target'];clear=[math.floor(c*255+.5) for c in target['clear_color']]
    macros={'PACKET_BYTES':len(packet),'COLOR_BYTES':len(attachments['color']),
        'DEPTH_BYTES':len(attachments['depth']),'STENCIL_BYTES':len(attachments['stencil']),
        'WIDTH':target['width'],'HEIGHT':target['height'],'SEQUENCE':1,
        'NEGATIVE_CASES':5 if negative_preflight else 0,
        'CLEAR_R':clear[0],'CLEAR_G':clear[1],'CLEAR_B':clear[2],'CLEAR_A':clear[3]}
    if negative_preflight:
        macros['REJECTION_BYTES']=len(rejection)
        macros.update({'REJECTION_'+name.upper()+'_OFFSET':value for name,value in negative_offsets.items()})
    (out/'metal_host_draw_fixture.h').write_text('\n'.join(f'#define HALO_DRAW_{name} {value}u' for name,value in macros.items())+'\n')
    fixture={'schema_version':1,'kind':'actual_draw_ilp32_wire_fixture','complete':True,
        'replay':str(replay_path),'replay_sha256':sha(replay_path),'source_capture':manifest['source_capture'],
        'independent_reference_result':str(reference_path),'independent_reference_sha256':sha(reference_path),
        'packet':{'file':'packet.bin','size':len(packet),'sha256':sha(out/'packet.bin')},
        'geometry':geometry_info,'target':target,'payload_sha256':{str(file):sha(file) for file in symbols.values()},
        'negative_preflight_cases':['invalid_state','index_out_of_range','nonfinite_unpacked_vertex',
            'nonfinite_vertex_uniform','nonfinite_pixel_uniform'] if negative_preflight else [],
        'limits':['One actual isolated draw; not an ordered gameplay frame.','Only verified independently cleared targets are accepted.','Expected after-target buffers are guest comparisons only, never packet resources.','Actual ANGLEFloat32 storage; physical Xbox D24/F24 precision remains unverified.']}
    (out/'fixture.json').write_text(json.dumps(fixture,indent=2)+'\n')
    return fixture

def build_guest(out,llvm,linker,plugin,source_root=ROOT):
    sys.path.insert(0,str(ROOT))
    from tools.android_build import GUEST_ABI_FLAGS
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    guest=source_root/'port/macos/tests/guest_metal_draw.c'
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-std=gnu11','-DHALO_MACOS=1','-I',out,'-emit-llvm','-S',guest,'-o',out/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',out/'guest.ll','-o',out/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',out/'guest.rebased.ll','-o',out/'guest.darwin.s')
    run(sys.executable,'tools/android_asm_convert.py',out/'guest.darwin.s',out/'guest.s')
    for source in ('guest','fixture'):
        run(llvm/'clang','--target=aarch64-linux-android','-c',out/(source+'.s'),'-o',out/(source+'.o'))
    run(sys.executable,'tools/android_imports.py','--host-table',out/'host_import_table.c',out/'imports.s','port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',out/'imports.s','-o',out/'imports.o')
    script=out/'guest.ld';script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',script,out/'guest.o',out/'fixture.o',out/'imports.o','-o',out/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(out/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    return symbols

def build_host(out,source_root=ROOT):
    flags=['-arch','arm64','-mmacosx-version-min=14.0','-O2','-g','-DHALO_MACOS=1',
           '-I'+str(source_root/'port/macos/host'),'-I'+str(source_root/'port/android/include')]
    sources=[source_root/'port/macos/host/host_memory.c',out/'host_import_table.c',source_root/'port/macos/host/host_metal.mm',
             source_root/'port/macos/host/metal_draw_encoder.mm',source_root/'port/macos/tests/host_metal.mm']
    objects=[]
    for index,source in enumerate(sources):
        obj=out/(str(index)+'-'+source.name+'.o');cpp=source.suffix=='.mm'
        run('clang++' if cpp else 'clang',*flags,*(['-std=c++17','-fobjc-arc','-fblocks'] if cpp else []),'-c',source,'-o',obj)
        objects.append(obj)
    executable=out/'host_metal_probe'
    run('clang++',*flags,*objects,'-framework','Foundation','-framework','Metal','-framework','QuartzCore','-o',executable)
    return executable,sources

def consume_run(out,stdout_path,returncode=None):
    require(type(returncode) is int,'Observed native host process return code is required')
    prepared=json.loads((out/'prepared.json').read_text());fixture=json.loads((out/'fixture.json').read_text())
    def unchanged():
        for path,expected in prepared['source_and_binary_sha256'].items():
            require(sha(path)==expected,f'Stale host draw source/binary: {path}')
        require(sha(out/'fixture.json')==prepared['fixture_sha256'],'Stale host draw fixture')
        for path,expected in fixture['payload_sha256'].items():
            require(sha(path)==expected,f'Stale embedded comparison/packet payload: {path}')
    unchanged()
    require(sha(fixture['replay'])==fixture['replay_sha256'],'Prepared replay changed')
    require(sha(fixture['independent_reference_result'])==fixture['independent_reference_sha256'],'Independent reference changed')
    replay=Path(fixture['replay']);manifest=comparison.load_manifest(replay)
    native=out/'native';run_record=json.loads(stdout_path.read_text())
    require(run_record.get('kind')=='native_metal_ilp32_transport' and run_record.get('guest_pointer_bits')==32,
            'Result did not execute the real ILP32 host transport')
    words=struct.unpack('<16I',(native/'guest-report.bin').read_bytes())
    require(words[0]==1 and words[13:15]==(fixture['target']['width'],fixture['target']['height']) and
            words[15]==fixture['packet']['size'],'Guest diagnostic belongs to another fixture')
    proof=dict(prepared,complete=words[1]>=6,build_only=False,guest_run=run_record,guest_report=list(words),
               returncode=returncode,native_stdout_sha256=sha(stdout_path),passed=False)
    if words[1]>=6:
        bgra=(native/'native-color-bgra.bin').read_bytes();rgba=bytearray(len(bgra))
        require(len(bgra)==fixture['target']['width']*fixture['target']['height']*4,'Native color size differs')
        rgba[0::4]=bgra[2::4];rgba[1::4]=bgra[1::4];rgba[2::4]=bgra[0::4];rgba[3::4]=bgra[3::4]
        (native/'native-color.rgba').write_bytes(rgba)
        def attachment(name,file,format_name):
            data=(native/file).read_bytes()
            return dict(file=file,size=len(data),sha256=sha(native/file),format=format_name,
                        width=fixture['target']['width'],height=fixture['target']['height'],orientation='top_left')
        executable=out/'host_metal_probe'
        result={'schema_version':1,'kind':'nv2a_draw_result','complete':True,'backend':'native_metal',
            'manifest_sha256':sha(replay),'source_capture':manifest['source_capture'],
            'runner':{'file':str(executable),'size':executable.stat().st_size,'sha256':sha(executable)},
            'guest':{'file':str(out/'guest.elf'),'size':(out/'guest.elf').stat().st_size,'sha256':sha(out/'guest.elf')},
            'actual_depth_format':'depth32float_stencil8','guest_pointer_bits':32,
            'color':attachment('color','native-color.rgba','rgba8unorm'),
            'depth':attachment('depth','native-depth.bin','float32'),
            'stencil':attachment('stencil','native-stencil.bin','uint8'),'limits':fixture['limits']}
        (native/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        compared=comparison.compare(replay,Path(fixture['independent_reference_result']),native/'result.json')
        (out/'comparison.json').write_text(json.dumps(compared,indent=2)+'\n')
        proof.update(byte_exact=words[6:9]==(0,0,0),comparison_sha256=sha(out/'comparison.json'),
            native_result_sha256=sha(native/'result.json'),
            negative_preflight_cases=fixture['negative_preflight_cases'],
            passed=returncode==0 and run_record.get('passed') is True and run_record.get('guest_result')==0 and words[1]==7 and words[6:9]==(0,0,0) and
                   compared['attachment_comparison_passed'] is True)
    unchanged();(out/'result.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'passed':proof['passed'],'guest_result':run_record.get('guest_result'),
                      'different_bytes':dict(zip(('color','depth','stencil'),words[6:9])),
                      'visible_pixels':words[9],'result':str(out/'result.json')},indent=2))
    if not proof['passed']:raise SystemExit('Actual draw through host imports did not pass; evidence retained')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--rebase-plugin',type=Path)
    parser.add_argument('--llvm-bin',type=Path,default=Path('/opt/homebrew/opt/llvm@22/bin'))
    parser.add_argument('--linker',type=Path,default=Path('/opt/homebrew/opt/lld@22/bin/ld.lld'))
    parser.add_argument('--output',type=Path,default=ROOT/'build/metal-poc/host-actual-draw-validation')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--build-only',action='store_true')
    mode.add_argument('--consume-run',type=Path,help='Consume JSON from an independently invoked native guest probe')
    parser.add_argument('--consume-returncode',type=int,help='Actual observed exit status of the consumed native host process')
    parser.add_argument('--negative-preflight',action='store_true',help='After the actual draw, test atomic rejection of five malformed later DRAWs')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.consume_run:
        require(args.consume_returncode is not None,'--consume-run requires --consume-returncode from the observed host process')
        consume_run(out,args.consume_run,args.consume_returncode);return
    require(args.replay and args.reference and args.rebase_plugin,'Build needs replay, independent reference, and rebase plugin paths')
    require(not (out/'fixture.json').exists(),'Output already has a fixture; preserve its identity and use a new folder')
    fixture=build_fixture(args.replay.resolve(),args.reference.resolve(),out,args.negative_preflight)
    llvm=args.llvm_bin.resolve();linker=args.linker.absolute();plugin=args.rebase_plugin.resolve()
    source_files=[ROOT/'port/macos/tests/guest_metal_draw.c',ROOT/'port/macos/host/host_memory.c',
        ROOT/'port/macos/host/host_metal.mm',ROOT/'port/macos/host/metal_draw_encoder.mm',
        ROOT/'port/macos/host/metal_function_cache.h',ROOT/'port/macos/host/metal_warmup_cache.h',ROOT/'port/macos/host/metal_draw_encoder.h',ROOT/'port/macos/tests/host_metal.mm',
        ROOT/'port/macos/host/host.h',ROOT/'port/android/include/halo_android_abi.h',
        ROOT/'port/macos/include/halo_metal_abi.h',ROOT/'port/macos/metal_imports.list',
        ROOT/'tools/android_imports.py',ROOT/'tools/android_asm_convert.py',ROOT/'tools/android_build.py',
        ROOT/'tools/metal_draw_replay.py',ROOT/'tools/metal_draw_compare.py',Path(__file__).resolve()]
    sources_before={str(path):sha(path) for path in source_files}
    symbols=build_guest(out,llvm,linker,plugin)
    executable,sources=build_host(out)
    require(sources_before=={str(path):sha(path) for path in source_files},'Host bridge source changed during build; preserve attempt and prepare again')
    required=('__host_import_table','__host_import_names','__host_import_count','halo_draw_report',
              'halo_draw_actual_color','halo_draw_actual_depth','halo_draw_actual_stencil')
    require(all(name in symbols for name in required),'Missing guest fixture/probe symbols')
    # Extended driver: old ELF/import triple plus diagnostic addresses, exact
    # logical dimensions and output directory. No new host API is introduced.
    native=out/'native';native.mkdir(exist_ok=True)
    command=[str(executable),str(out/'guest.elf'),*[hex(symbols[name]) for name in required[:3]],
             '0x1000000',*[hex(symbols[name]) for name in required[3:]],
             str(fixture['target']['width']),str(fixture['target']['height']),str(native)]
    dependencies=[*source_files,*sources,plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker,
        out/'guest.elf',executable,out/'fixture.json',out/'fixture.s',out/'metal_host_draw_fixture.h']
    proof={'schema_version':1,'kind':'actual_draw_ilp32_host_metal','complete':False,'passed':False,
        'source_capture':fixture['source_capture'],'fixture_sha256':sha(out/'fixture.json'),
        'source_and_binary_sha256':{str(path):sha(path) for path in dependencies},
        'execution_command':command,'build_only':args.build_only,'limits':fixture['limits']}
    (out/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n')
    if args.build_only:print(json.dumps({'prepared':str(out/'prepared.json'),'execution_command':command},indent=2));return
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    (native/'stdout.json').write_text(result.stdout);(native/'stderr.log').write_text(result.stderr)
    print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr)
    consume_run(out,native/'stdout.json',result.returncode)


if __name__=='__main__':main()
